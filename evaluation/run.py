"""Run fixed, real-model retrieval experiments without a database or LLM API."""

import argparse
import hashlib
import importlib.metadata
import json
import logging
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

from app.chat_service import ChatService
from evaluation.dataset import load_dataset, prepare_dataset
from evaluation.metrics import ranking_metrics, summarize
from evaluation.report import write_report

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("evaluation")


def _unit(vector):
    values = [float(value) for value in vector]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("vectors must be nonempty and finite")
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        raise ValueError("zero vector cannot define cosine similarity")
    return [value / norm for value in values]


def evaluate_query(chunks, vectors, question, embed_query, *, k, candidate_k,
                   sim_threshold, rerank_threshold, reranker=None):
    """Measure one query with production selection; exact cosine replaces only DB lookup."""
    if not 1 <= k <= candidate_k or not chunks or len(chunks) != len(vectors):
        raise ValueError("invalid k, candidates or vector count")
    started = time.perf_counter()
    query_vector = _unit(embed_query(question["query"]))
    scored = []
    for chunk, vector in zip(chunks, vectors):
        normalized = _unit(vector)
        if len(normalized) != len(query_vector):
            raise ValueError("embedding dimensions differ")
        score = sum(a * b for a, b in zip(normalized, query_vector))
        scored.append({**chunk, "score": score})
    scored.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    candidates = scored[:candidate_k]
    rerank_errors = []

    def strict_rerank(query, rows):
        try:
            ranked = reranker(query, rows)
            if (len(ranked) != len(rows)
                    or {row["chunk_id"] for row in ranked} != {row["chunk_id"] for row in rows}
                    or not all(row.get("_rerank_applied") is True for row in ranked)
                    or not all(math.isfinite(float(row["score"])) for row in ranked)):
                raise RuntimeError("reranker failed, changed candidates or returned invalid scores")
            return ranked
        except Exception as exc:
            # ChatService deliberately catches reranker errors for live traffic.
            # Evaluation must detect that fallback and invalidate the experiment.
            rerank_errors.append(exc)
            raise

    service = ChatService(
        understand=lambda *_: None, has_knowledge=lambda _: True,
        search_kb=lambda *_: candidates, search_web=lambda *_: [],
        generate=lambda _: "", candidate_k=candidate_k,
        rerank_kb=strict_rerank if reranker else None, rerank_threshold=rerank_threshold,
    )
    trace = []
    selected = service._retrieve_kb(question["query"], None, k, sim_threshold, trace)
    if rerank_errors:
        raise RuntimeError("reranker experiment invalid; fallback is forbidden") from rerank_errors[0]
    elapsed = (time.perf_counter() - started) * 1000
    ids = [row["chunk_id"] for row in selected]
    return {
        **question, "candidate_ids": [row["chunk_id"] for row in candidates],
        "retrieved_ids": ids, "scores": [float(row["score"]) for row in selected],
        "metrics": ranking_metrics(ids, question["gold_ids"], k),
        "candidate_metrics": ranking_metrics(
            [row["chunk_id"] for row in candidates], question["gold_ids"], candidate_k
        ),
        "latency_ms": elapsed, "trace": trace,
    }


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_identity():
    paths = list((ROOT / "evaluation").glob("*.py"))
    paths += [ROOT / "app" / name for name in
              ("parser.py", "chunker.py", "embeddings.py", "chat_service.py", "config.py")]
    files = {str(path.relative_to(ROOT)).replace("\\", "/"): _sha256(path)
             for path in sorted(paths)}
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    return {"git_head": revision, "files_sha256": files}


def _model_identity(model_name, cache):
    from huggingface_hub import hf_hub_download
    # A model can be fully usable without unrelated ONNX exports or README images.
    snapshot = Path(hf_hub_download(
        model_name, "config.json", local_files_only=True, cache_dir=cache / "hub"
    )).parent
    names = ("config.json", "modules.json", "tokenizer.json", "tokenizer_config.json",
             "sentence_bert_config.json", "1_Pooling/config.json",
             "model.safetensors", "pytorch_model.bin")
    return {
        "model": model_name, "snapshot": snapshot.name,
        "files_sha256": {name: _sha256(snapshot / name) for name in names if (snapshot / name).is_file()},
    }


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dataset", type=Path, default=ROOT / "evaluation/data/synthetic_v1.json")
    result.add_argument("--output", type=Path, default=ROOT / "evaluation/reports/baseline-v1")
    result.add_argument("--model-cache", type=Path, default=ROOT / ".hf-cache")
    result.add_argument("--split", choices=("dev", "test", "all"), default="all")
    result.add_argument("--modes", nargs="+", choices=("dense", "dense_rerank"),
                        default=["dense", "dense_rerank"])
    result.add_argument("--k", type=int, default=4)
    result.add_argument("--candidate-k", type=int, default=8)
    result.add_argument("--sim-threshold", type=float, default=0.4)
    result.add_argument("--rerank-threshold", type=float, default=0.3)
    result.add_argument("--threads", type=int, default=4)
    return result


def main(argv=None):
    args_parser = parser()
    args = args_parser.parse_args(argv)
    if not 1 <= args.k <= 10 or not args.k <= args.candidate_k <= 1000:
        args_parser.error("require 1 <= k <= 10 and k <= candidate-k <= 1000")
    if not 0 <= args.sim_threshold <= 1 or not 0 <= args.rerank_threshold <= 1:
        args_parser.error("thresholds must be within [0, 1]")
    if not 1 <= args.threads <= 64:
        args_parser.error("threads must be within [1, 64]")
    # Do not import app.llm/main or read API credentials for an offline experiment.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["HF_HOME"] = str(args.model_cache.resolve())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        data = load_dataset(args.dataset)
        chunks, questions = prepare_dataset(data)
        questions = [q for q in questions if args.split == "all" or q["split"] == args.split]
        if not questions:
            raise ValueError("selected split has no questions")
        logger.info("validated dataset: documents=%s chunks=%s questions=%s",
                    len(data["documents"]), len(chunks), len(questions))
        import torch
        torch.set_num_threads(args.threads)
        from app import config, embeddings
        identity_started = time.perf_counter()
        model_ids = [_model_identity(config.EMBEDDING_MODEL, args.model_cache.resolve())]
        if "dense_rerank" in args.modes:
            model_ids.append(_model_identity(config.RERANK_MODEL, args.model_cache.resolve()))
        fingerprint_ms = (time.perf_counter() - identity_started) * 1000
        started = time.perf_counter()
        embedding_model = embeddings._get_model()
        if "dense_rerank" in args.modes and embeddings._get_reranker() is None:
            raise RuntimeError("reranker unavailable; cannot publish dense_rerank baseline")
        model_load_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        vectors = embeddings.embed_texts([chunk["content"] for chunk in chunks])
        corpus_encode_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        embeddings.embed_texts(["离线评测预热"], is_query=True)
        if "dense_rerank" in args.modes:
            embeddings.rerank("离线评测预热", [chunks[0]["content"]])
        warmup_ms = (time.perf_counter() - started) * 1000
        runs = {}
        for mode in dict.fromkeys(args.modes):
            results = []
            for index, question in enumerate(questions, 1):
                row = evaluate_query(
                    chunks, vectors, question,
                    lambda query: embeddings.embed_texts([query], is_query=True)[0],
                    k=args.k, candidate_k=args.candidate_k,
                    sim_threshold=args.sim_threshold, rerank_threshold=args.rerank_threshold,
                    reranker=embeddings.rerank_sources if mode == "dense_rerank" else None,
                )
                results.append(row)
                logger.info("mode=%s query=%s progress=%s/%s elapsed_ms=%.1f",
                            mode, question["id"], index, len(questions), row["latency_ms"])
            runs[mode] = {
                "overall": summarize(results, args.k),
                "by_split": {split: summarize([r for r in results if r["split"] == split], args.k)
                             for split in sorted({r["split"] for r in results})},
                "by_category": {cat: summarize([r for r in results if r["category"] == cat], args.k)
                                for cat in sorted({r["category"] for r in results})},
                "results": results,
            }
        packages = ("torch", "sentence-transformers", "transformers", "numpy", "pydantic")
        report = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "synthetic exact-cosine retrieval only; no HNSW, LLM, routing or query rewriting",
            "dataset": {"version": data["version"], "sha256": _sha256(args.dataset),
                        "documents": len(data["documents"]), "chunks": len(chunks),
                        "queries": len(questions), "provenance": data.get("provenance", "")},
            "parameters": {key: getattr(args, key) for key in
                           ("k", "candidate_k", "sim_threshold", "rerank_threshold", "threads", "split")},
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                            "device": str(embedding_model.device),
                            "packages": {name: importlib.metadata.version(name) for name in packages}},
            "source": _source_identity(), "models": model_ids,
            "setup_ms": {"model_fingerprints": fingerprint_ms, "model_load": model_load_ms,
                         "corpus_encode": corpus_encode_ms, "warmup": warmup_ms},
            "timing_scope": "single sequential pass per mode after warmup; query embedding + exact cosine + production selection/rerank; excludes startup/corpus encoding/LLM/DB/network; not a throughput benchmark",
            "chunks": chunks, "runs": runs,
        }
        write_report(report, args.output)
        logger.info("report written: %s", args.output)
        return 0
    except Exception:
        logger.exception("evaluation failed; no successful baseline is claimed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

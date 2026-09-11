import copy
import math
from pathlib import Path

import pytest

from evaluation.dataset import load_dataset, prepare_dataset
from evaluation.metrics import ranking_metrics, summarize


def sample_dataset():
    return {
        "version": "test",
        "documents": [{"id": "a", "title": "a.md", "text": "# Alpha\n批准记录需要保存七天。"}],
        "questions": [{
            "id": "q1", "group": "a", "split": "dev", "category": "direct",
            "query": "保存多久？", "answer": "七天",
            "evidence": [{"doc_id": "a", "quote": "批准记录需要保存七天。"}],
        }],
    }


def test_ranking_metrics_match_hand_calculation_and_ignore_duplicates():
    result = ranking_metrics([9, 2, 2, 3], {2, 3}, 3)
    assert result["recall"] == 1
    assert result["mrr"] == 0.5
    assert result["ndcg"] == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    )


def test_empty_gold_is_excluded_from_ranking_average():
    assert ranking_metrics([1], set(), 4) == dict(recall=None, mrr=None, ndcg=None)
    report = summarize([
        {"gold_ids": [1], "retrieved_ids": [1], "latency_ms": 10},
        {"gold_ids": [], "retrieved_ids": [2], "latency_ms": 20},
        {"gold_ids": [], "retrieved_ids": [], "latency_ms": 30},
    ], 4)
    assert report["recall"] == 1
    assert report["answerable_count"] == 1
    assert report["unanswerable_empty_rate"] == 0.5
    assert report["latency_p50_ms"] == 20
    assert summarize([], 4)["recall"] is None


def test_metrics_cutoff_and_no_hits():
    assert ranking_metrics([9, 2], {2}, 1) == dict(recall=0, mrr=0, ndcg=0)
    assert ranking_metrics([], {2}, 3) == dict(recall=0, mrr=0, ndcg=0)
    with pytest.raises(ValueError):
        ranking_metrics([1], {1}, 0)


def test_evidence_is_mapped_to_real_production_chunks():
    chunks, questions = prepare_dataset(sample_dataset())
    assert chunks[0]["content"].endswith("批准记录需要保存七天。")
    assert questions[0]["gold_ids"] == [chunks[0]["chunk_id"]]


@pytest.mark.parametrize("mutation", ["duplicate", "missing_document", "missing_quote", "split_leak"])
def test_dataset_rejects_invalid_labels(mutation):
    data = sample_dataset()
    question = data["questions"][0]
    if mutation == "duplicate":
        data["questions"].append(copy.deepcopy(question))
    elif mutation == "missing_document":
        question["evidence"][0]["doc_id"] = "unknown"
    elif mutation == "missing_quote":
        question["evidence"][0]["quote"] = "并不存在的证据"
    else:
        other = copy.deepcopy(question)
        other.update(id="q2", split="test")
        data["questions"].append(other)
    with pytest.raises(ValueError):
        prepare_dataset(data)


def test_committed_dataset_has_balanced_groups_and_evidence():
    path = Path(__file__).parents[1] / "evaluation/data/synthetic_v1.json"
    data = load_dataset(path)
    chunks, questions = prepare_dataset(data)
    assert len(data["documents"]) == 12
    assert len(questions) == 60
    assert len(chunks) >= 12
    for split in ("dev", "test"):
        subset = [q for q in questions if q["split"] == split]
        assert len(subset) == 30
        assert sum(bool(q["gold_ids"]) for q in subset) == 24


def test_runner_uses_production_rerank_threshold_after_cosine_filter():
    from evaluation.run import evaluate_query
    chunks = [
        {"chunk_id": 1, "content": "甲", "doc_id": "a"},
        {"chunk_id": 2, "content": "乙", "doc_id": "b"},
        {"chunk_id": 3, "content": "丙", "doc_id": "c"},
    ]
    vectors = [[1, 0], [0.8, 0.6], [0, 1]]
    query = {"id": "q", "query": "问", "gold_ids": [2], "split": "dev", "category": "direct"}
    seen = []
    def rerank(text, rows):
        seen.extend(row["chunk_id"] for row in rows)
        return [{**rows[1], "score": 0.9, "_rerank_applied": True},
                {**rows[0], "score": 0.1, "_rerank_applied": True}]
    result = evaluate_query(
        chunks, vectors, query, lambda _: [1, 0],
        k=1, candidate_k=3, sim_threshold=0.4, rerank_threshold=0.3, reranker=rerank,
    )
    assert seen == [1, 2]
    assert result["retrieved_ids"] == [2]
    assert result["candidate_ids"] == [1, 2, 3]
    assert result["metrics"]["mrr"] == 1


def test_runner_refuses_silent_reranker_fallback():
    from evaluation.run import evaluate_query
    with pytest.raises(RuntimeError, match="reranker"):
        evaluate_query(
            [{"chunk_id": 1, "content": "甲", "doc_id": "a"}], [[1]],
            {"id": "q", "query": "问", "gold_ids": [1]},
            lambda _: [1], k=1, candidate_k=1, sim_threshold=0.4,
            rerank_threshold=0.3,
            reranker=lambda _, rows: [{**rows[0], "_rerank_applied": False}],
        )


@pytest.mark.parametrize("vector", [[float("nan"), 0], [0, 0], [1]])
def test_runner_rejects_invalid_vectors(vector):
    from evaluation.run import evaluate_query
    with pytest.raises(ValueError):
        evaluate_query(
            [{"chunk_id": 1, "content": "甲"}], [[1, 0]],
            {"id": "q", "query": "问", "gold_ids": [1]}, lambda _: vector,
            k=1, candidate_k=1, sim_threshold=0.4, rerank_threshold=0.3,
        )


def test_model_fingerprint_does_not_require_unused_repository_files(tmp_path, monkeypatch):
    from evaluation.run import _model_identity
    import huggingface_hub
    snapshot = tmp_path / "snapshots" / "test-revision"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"test-weight")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download",
                        lambda *_args, **_kwargs: str(snapshot / "config.json"))
    identity = _model_identity("synthetic/model", tmp_path)
    assert identity["snapshot"] == "test-revision"
    assert set(identity["files_sha256"]) == {"config.json", "model.safetensors"}

# Retrieval Evaluation Implementation Plan

> **For agentic workers:** Use subagent-driven-development for isolated testing work and independent review; parent implements the coupled dataset, metrics and runner tasks. User has approved this phase.

**Goal:** Establish reproducible retrieval evidence and reliable offline regression tests for interview preparation.

**Architecture:** A standalone evaluation package reuses production parsing, chunking, embeddings and final selection. A frozen synthetic corpus and evidence labels drive pure ranking metrics; CLI reports separate model startup and query timings without external APIs or business database writes.

**Tech Stack:** Python standard library, pytest, existing sentence-transformers / Torch / NumPy, existing application modules.

## Task 1 — test isolation
- [x] Reproduce the unmocked successful stream memory update under a network guard; fail even when application catches the connection error.
- [x] Set fake service environment before app imports in `tests/conftest.py`; patch outbound connections and assert zero attempted connections on teardown.
- [x] Replace only external memory boundary in `tests/test_chat_stream.py`; verify persistence when enabled and no call when disabled.
- [x] Run root virtualenv Python with `-m pytest -q` and a unique writable basetemp; inspect all failures.

## Task 2 — dataset and metric contracts
- [x] Write `tests/test_evaluation.py` first. Hand-calculated case: `ranking_metrics([9, 2, 3], {2, 3}, 3)` must yield recall=1, MRR=0.5 and nDCG=(1/log2(3)+1/log2(4))/(1+1/log2(3)). Empty gold returns null ranking metrics.
- [x] Verify missing module fails, then implement `evaluation/metrics.py`; validate positive K and de-duplicate retrievals.
- [x] Add `evaluation/dataset.py` with unique ID, known document, verbatim evidence, split consistency and chunk-level evidence validation. Duplicate ID or one group spanning dev/test raises ValueError.
- [x] Create `evaluation/data/synthetic_v1.json`: 12 original documents, 48 answerable queries, 12 negatives, balanced fixed split. Build chunks with `chunk_units(parse_file_units(title, text.encode('utf-8')))`.

## Task 3 — real offline baseline runner
- [x] Test `evaluate_query` with known vectors and a reranker that deliberately reverses top candidates; assert metrics and selected chunk IDs reflect the production threshold ordering.
- [x] Implement CLI with dataset, output, split, model-cache and k/threshold arguments; reject invalid parameter combinations before loading models.
- [x] Normalize embeddings and compute exact cosine candidate ordering, then invoke `ChatService._retrieve_kb` with no rewrite dependency. Dense and dense_rerank use the same fixed candidates.
- [x] Fail on unavailable reranker and malformed/nonfinite model outputs; never silently label fallback as reranking.
- [x] Write JSON and Markdown reports including per-query evidence IDs, metrics, timing scope, dataset/source fingerprints, versions and model snapshot identity. Exit nonzero on errors.
- [x] Run `python -m evaluation.run --model-cache <root>/.hf-cache --output evaluation/reports/baseline-v1`; inspect output and actual failure cases.

## Task 4 — interview evidence and review
- [x] Add `evaluation/README.md` explaining reproducibility, metric denominators and limitations; link from project README.
- [x] Add an interview workbook with a 90-second introduction, tiered follow-up questions, code anchors, honest resume wording, practical exercises and study order.
- [x] Run all backend tests, review independent findings, fix material issues, and record results. Frontend untouched; prior build and test baseline applies.
- [x] Commit focused changes on `codex/resume-evaluation`, then integrate verified changes into the local project without publishing remotely.

## Execution record — 2026-09-11

User redirected priority to orchestration and conversation workflows and requested no repetition of unaffected passing tests. The first real-model baseline completed before that redirection; it remains an explicitly historical, pre-workflow result. Workflow scope and implementation are recorded in ../specs/2026-09-11-workflow-design.md and ../../编排与会话工作流.md.

Validation was incremental: initial offline suite 78 passed; one model-identity regression passed after fixing optional-cache-file detection; new workflow 9 passed, storage 9 plus transaction-capture regression 1 passed, affected API/routing batch 36 passed, final snapshot/disconnect/API batch 12 passed, evaluator compatibility 2 passed, frontend stream 5 passed and final production build passed. These are overlapping runs, not a claim that a final full suite was executed. Existing AnyIO deprecation and frontend large-bundle warnings remain.

Independent review identified pre-task memory capture and HTTP disconnect cleanup gaps plus a history-loading UI race; all three were corrected and reviewed. No remote services, live business database changes, or remote publishing were required. PostgreSQL advisory-lock behavior under real concurrent deployment is not validated by SQLite tests.

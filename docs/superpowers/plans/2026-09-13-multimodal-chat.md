# Multimodal Chat Implementation Plan

> **For agentic workers:** Use subagent-driven-development for bounded implementation and review. The user approved the linked design on 2026-09-13.

**Goal:** Per-request model capabilities and private, durable conversation attachments with reusable ingestion and explicit knowledge-base promotion.

**Architecture:** Immutable model profiles feed request-local generation callbacks. Attachments own their session-authorized resource, task and chunks; shared parsing and lease utilities support both durable pipelines. Workflow accepts attachment evidence independently of KB routing. Frontend exposes actual options and attachment lifecycle.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL/pgvector, OpenAI-compatible SDK, Vue/ElementPlus.

## 1. Model capabilities
- [x] Add `app/model_profiles.py`; environment-defined model IDs, explicit reasoning on/off mappings, visual and context budgets. Reject unknown IDs and unsupported options.
- [x] Extend `app/llm.py` with optional request profile/options preserving fast auxiliary calls. Test independent concurrent payloads and content-only streaming in `tests/test_model_profiles.py`.
- [x] Add authenticated `/models` and ChatReq options in `app/main.py`; persist actual settings.

## 2. Attachment resources and durable processing
- [x] Add `app/attachments.py`, `app/attachment_routes.py`, shared `app/file_pipeline.py`; extend worker/migration/cleanup. Store owner/session, original, normalized image, parsed chunks, leased tasks and promotion mapping.
- [x] Validate 5 files, 20 MB/file, 50 MB/request, image decoding/pixels. Upload reads bounded blocks. Enforce owner and same conversation for every operation, fenced completion and tombstones.
- [x] Test queue expiry/stale claims, image vs OCR, retry/delete, ownership and idempotent promotion in isolated database tests.

## 3. Workflow and persistence
- [x] Add `app/attachment_context.py`, attachment evidence to ChatService, mixed-content generation callbacks, image/source labels. Short context direct, long QA scoped vector ranking, summaries bounded map/reduce with coverage counts and explicit maximum.
- [x] Save model/attachment metadata and mark attachments used in same session-locked exchange transaction. Recheck authorization immediately before generation and persistence.
- [x] Test attachment-only grounding, mixed citations, full coverage and oversized context errors.

## 4. User interface
- [x] Add model controls and attachment composer, chooser/drop/paste, polling, retry/remove/reuse, private originals and explicit save to editable KB. Persist preferences and show options in history.
- [x] Extend API and source drawer; verify affected frontend tests and production build once after final changes.

## 5. Completion
- [x] Review against approved design and security/concurrency boundaries. Run targeted new tests and impacted tests once; reuse earlier baseline results.
- [x] Document model configuration, additive migration, worker restart, limits and live-provider validation boundaries. Merge verified feature into user's checkout.

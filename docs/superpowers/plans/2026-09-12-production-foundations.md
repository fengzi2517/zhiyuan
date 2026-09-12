# Production foundations implementation plan

> Use subagent-driven-development for bounded implementation and independent review.

**Goal:** Deployable authenticated RAG with durable PostgreSQL ingestion and real concurrency evidence.
**Architecture:** Explicit SQLAlchemy migrations, database sessions and KB memberships, PostgreSQL leased queue and separate worker, credentialed Vue client.
**Stack:** FastAPI, SQLAlchemy, psycopg, pgvector, Vue.

## Tasks and ownership

- [x] Identity: `app/auth.py`, `app/auth_routes.py`, `app/admin.py`, `app/main.py`, scoped queries in `app/db.py`. Password hashing, expiring revocable sessions, CSRF, rate limits, account administration, owner/editor/reader checks across every business route and session claiming. First add focused `tests/test_auth.py`; run it with root `.venv/Scripts/python.exe -m pytest tests/test_auth.py -q`. Root handles queue integration after these files settle.
- [x] Queue: `app/jobs.py`, `app/worker.py`, `tests/test_jobs.py`. Add database model and leased claims with SKIP LOCKED, expiry fencing, retries, transactional chunk replacement, cancellation and guarded retry. Unit check validation, real PostgreSQL checks claim exclusion and stale completion. Root owns these new files.
- [x] Migrations and concurrency: `app/migrate.py`, `integration_tests/`, `compose.integration.yml`. Import all models before migration, lock migration execution, require current schema on web/worker startup. Dedicated test database rejects non-test names. Independent connections verify locks, rollback and worker recovery using deterministic vectors; never destroy business database.
- [x] Integration: replace upload BackgroundTasks with persisted original plus job transaction, add job state and retry API; connect queue cancellation to KB deletion with consistent locking. Stream upload max 20 MB. Frontend login, credentialed SSE/download, permission and retry UI.
- [x] Operations: Dockerfile, compose, environment template, CLI bootstrap/legacy adoption, health/readiness, cleanup dry-run and deployment guide. Execute only affected tests and frontend build, review spec then correctness, address findings, commit and fast-forward verified result.

## Acceptance commands

Run unit paths once as implemented: `python -m pytest tests/test_auth.py tests/test_jobs.py -q`.
Run dedicated integration suite with explicitly configured `TEST_DATABASE_URL`: `python -m pytest integration_tests -q`.
Run frontend `npm run build` and affected stream test once after final frontend modifications.
Record actual outcomes and unexecuted external-model smoke separately; no synthetic performance claims.

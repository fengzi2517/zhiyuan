"""Health endpoints and reference-aware operator maintenance."""
import argparse
import logging
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, text
from . import auth, db, jobs

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/health/live')
def live():
    return {'status': 'alive'}


@router.get('/health/ready')
def ready():
    from .migrate import require_schema
    try:
        require_schema()
        return {'status': 'ready'}
    except Exception as exc:
        raise HTTPException(503, '数据库尚未就绪') from exc


@router.get('/jobs/summary')
def summary(user=Depends(auth.current_user)):
    scopes = auth.allowed_kb_ids(user.id)
    with db.Session() as s:
        rows = s.query(jobs.IngestionJob.status, func.count()).filter(
            jobs.IngestionJob.kb_id.in_(scopes)).group_by(jobs.IngestionJob.status).all()
        expired = s.query(jobs.IngestionJob).filter(jobs.IngestionJob.kb_id.in_(scopes),
            jobs.IngestionJob.status == 'running', jobs.IngestionJob.lease_until <= func.now()).count()
        return {'counts': dict(rows), 'expired_running': expired}


async def request_log(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.monotonic()
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    logger.info('request_id=%s user_id=%s method=%s status=%s elapsed_ms=%s', request_id,
                getattr(request.state, 'user_id', '-'), request.method, response.status_code,
                round((time.monotonic() - started) * 1000))
    return response


def cleanup(*, apply=False, grace_hours=24):
    if grace_hours < 1:
        raise ValueError('Cleanup grace period must be at least one hour')
    root = Path(jobs.UPLOAD_DIR).resolve()
    if not root.is_dir():
        return []
    removed = []
    with db.Session.begin() as s:
        db._lock_session(s, 'file-maintenance')
        referenced = {Path(row[0]).resolve() for row in s.query(db.Document.storage_path) if row[0]}
        cutoff = time.time() - grace_hours * 3600
        for directory in root.iterdir():
            if not directory.is_dir() or directory.is_symlink() or directory.resolve().parent != root:
                continue
            for candidate in directory.iterdir():
                resolved = candidate.resolve()
                if candidate.is_symlink() or resolved.parent != directory.resolve() or not candidate.is_file():
                    continue
                if resolved not in referenced and candidate.stat().st_mtime < cutoff:
                    removed.append(str(candidate))
                    if apply:
                        candidate.unlink()
        # Retain unexpired sessions and the full active rate-limit window.
        if apply:
            from datetime import timedelta
            s.query(auth.LoginSession).filter(auth.LoginSession.expires_at < auth.now()).delete()
            s.query(auth.LoginAttempt).filter(auth.LoginAttempt.created_at < auth.now() - timedelta(seconds=auth.LOGIN_WINDOW)).delete()
    return removed


def resume_legacy(*, apply=False):
    """Recover old process-local pending uploads only if their original still exists."""
    result = []
    with db.Session.begin() as s:
        db._lock_session(s, 'legacy-jobs')
        docs = s.query(db.Document).filter(db.Document.status.in_(['pending', 'processing', 'failed']),
                 ~db.Document.id.in_(s.query(jobs.IngestionJob.doc_id))).with_for_update().all()
        for doc in docs:
            path = Path(doc.storage_path or '').resolve()
            eligible = doc.kb_id is not None and path.is_file() and path.parent == (Path(jobs.UPLOAD_DIR) / str(doc.id)).resolve()
            result.append({'doc_id': doc.id, 'action': 'queue' if eligible else 'reupload_required'})
            if apply and eligible:
                s.add(jobs.IngestionJob(doc_id=doc.id, kb_id=doc.kb_id))
                doc.status, doc.error_message = 'queued', ''
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['cleanup', 'resume-legacy'])
    parser.add_argument('--apply', action='store_true', help='Default is dry-run')
    parser.add_argument('--grace-hours', type=int, default=24)
    args = parser.parse_args()
    from .migrate import require_schema
    require_schema()
    result = cleanup(apply=args.apply, grace_hours=args.grace_hours) if args.command == 'cleanup' else resume_legacy(apply=args.apply)
    print(('APPLIED' if args.apply else 'DRY RUN'), result)


if __name__ == '__main__':
    main()

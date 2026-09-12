"""PostgreSQL leased queue. Expensive work happens outside database transactions."""
import logging
import math
import os
import secrets
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Column, Integer, String, DateTime, Text, Index, select, func, or_, and_
from . import db, config
from .config import UPLOAD_DIR

logger = logging.getLogger(__name__)
ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.md', '.png', '.jpg', '.jpeg', '.bmp', '.webp'}
LEASE_SECONDS = max(15, int(os.getenv('JOB_LEASE_SECONDS', '120')))
MAX_ATTEMPTS = max(1, int(os.getenv('JOB_MAX_ATTEMPTS', '3')))


class IngestionJob(db.Base):
    __tablename__ = 'ingestion_jobs'
    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, nullable=False, unique=True)
    kb_id = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False, default='queued')
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=MAX_ATTEMPTS)
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_until = Column(DateTime(timezone=True))
    claim_token = Column(String)
    worker_id = Column(String)
    error = Column(Text, default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


Index('ix_jobs_available', IngestionJob.status, IngestionJob.available_at, IngestionJob.lease_until)


def enqueue(kb_id: int, filename: str, data: bytes, *, user_id=None) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES or not data or len(data) > 20 * 1024 * 1024:
        raise ValueError('文件类型、内容或大小不合法')
    target = None
    try:
        with db.Session.begin() as s:
            if user_id is not None:
                from .auth import require_kb
                require_kb(user_id, kb_id, 'editor', session=s)
            # KB -> Job -> Document is the common mutation lock order.
            if s.execute(select(db.KnowledgeBase).where(db.KnowledgeBase.id == kb_id)
                         .with_for_update(read=True)).scalar_one_or_none() is None:
                raise ValueError('知识库不存在')
            doc = db.Document(kb_id=kb_id, filename=Path(filename).name, status='queued')
            s.add(doc)
            s.flush()
            directory = Path(UPLOAD_DIR).resolve() / str(doc.id)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / ('source' + suffix)
            temporary = directory / (secrets.token_hex(16) + '.tmp')
            try:
                with temporary.open('xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            doc.storage_path = str(target)
            job = IngestionJob(doc_id=doc.id, kb_id=kb_id)
            s.add(job)
            s.flush()
            result = {'doc_id': doc.id, 'job_id': job.id, 'kb_id': kb_id, 'status': 'queued'}
        logger.info('job_id=%s status=queued', result['job_id'])
        return result
    except BaseException:
        if target:
            target.unlink(missing_ok=True)
        raise


def _now(s):
    return s.execute(select(_clock(s))).scalar_one()


def _clock(s):
    return func.clock_timestamp() if s.bind.dialect.name == 'postgresql' else func.now()


def claim(worker_id: str) -> dict | None:
    with db.Session.begin() as s:
        now = _now(s)
        job = s.execute(select(IngestionJob).where(or_(
            and_(IngestionJob.status.in_(['queued', 'retry_wait']), IngestionJob.available_at <= now),
            and_(IngestionJob.status == 'running', IngestionJob.lease_until <= now),
        )).order_by(IngestionJob.available_at, IngestionJob.id)
            .with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
        if job is None:
            return None
        doc = s.get(db.Document, job.doc_id)
        if doc is None:
            job.status = 'cancelled'
            job.finished_at = now
            return None
        if job.attempts >= job.max_attempts:
            job.status = doc.status = 'failed'
            job.error = doc.error_message = '重试次数已耗尽，请检查 Worker 后手动重试'
            job.finished_at = job.updated_at = now
            return None
        job.attempts += 1
        job.status = doc.status = 'running'
        job.claim_token = secrets.token_hex(24)
        job.worker_id = worker_id
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.started_at = job.updated_at = now
        logger.info('job_id=%s worker_id=%s attempt=%s status=running', job.id, worker_id, job.attempts)
        return {'id': job.id, 'doc_id': job.doc_id, 'kb_id': job.kb_id, 'token': job.claim_token,
                'filename': doc.filename, 'storage_path': doc.storage_path, 'attempt': job.attempts}


def _owned(s, job_id, token):
    return s.execute(select(IngestionJob).where(
        IngestionJob.id == job_id, IngestionJob.status == 'running',
        IngestionJob.claim_token == token, IngestionJob.lease_until > _clock(s)
    ).with_for_update()).scalar_one_or_none()


def heartbeat(job_id, token) -> bool:
    with db.Session.begin() as s:
        job = _owned(s, job_id, token)
        if job is None:
            return False
        job.updated_at = _now(s)
        job.lease_until = job.updated_at + timedelta(seconds=LEASE_SECONDS)
        return True


def validate_vectors(chunks, embeddings):
    if not chunks or len(chunks) != len(embeddings):
        raise ValueError('分块与向量数量不一致或无有效文本')
    if any(len(v) != config.EMBEDDING_DIM or not all(math.isfinite(float(x)) for x in v)
           for v in embeddings):
        raise ValueError('向量维度或数值无效')


def complete(claimed, content, chunks, embeddings) -> bool:
    validate_vectors(chunks, embeddings)
    with db.Session.begin() as s:
        kb = s.execute(select(db.KnowledgeBase).where(db.KnowledgeBase.id == claimed['kb_id'])
                       .with_for_update()).scalar_one_or_none()
        if kb is None:
            return False
        job = _owned(s, claimed['id'], claimed['token'])
        if job is None:
            return False
        doc = s.get(db.Document, job.doc_id)
        if doc is None:
            return False
        s.query(db.Chunk).filter(db.Chunk.doc_id == doc.id).delete()
        for chunk, vector in zip(chunks, embeddings):
            fields = {} if isinstance(chunk, str) else {name: getattr(chunk, name, None) for name in
                ('page_start', 'page_end', 'section', 'start_char', 'end_char')}
            s.add(db.Chunk(doc_id=doc.id, kb_id=doc.kb_id, content=chunk if isinstance(chunk, str)
                          else chunk.content, embedding=vector, **fields))
        doc.content, doc.status, doc.error_message = content, 'done', ''
        job.status, job.error = 'succeeded', ''
        job.finished_at = job.updated_at = _now(s)
        job.lease_until = None
        logger.info('job_id=%s worker_id=%s attempt=%s status=succeeded', job.id, job.worker_id, job.attempts)
        return True


def fail(claimed, *, permanent=False, error_type='Error', stage='unknown') -> bool:
    with db.Session.begin() as s:
        job = _owned(s, claimed['id'], claimed['token'])
        if job is None:
            return False
        now = _now(s)
        terminal = permanent or job.attempts >= job.max_attempts
        job.status = 'failed' if terminal else 'retry_wait'
        job.error = '文件无法解析，请检查格式和内容' if permanent else '处理暂时失败，请查看服务日志'
        label = {'read': '读取原件', 'parse': '解析/OCR', 'chunk': '切块',
                 'embedding': '向量化/模型加载', 'commit': '数据库提交'}.get(stage)
        if label:
            job.error = f'{label}阶段失败：{job.error}'
        job.updated_at, job.lease_until = now, None
        job.finished_at = now if terminal else None
        job.available_at = now + timedelta(seconds=min(300, 5 * 2 ** min(job.attempts, 6)))
        doc = s.get(db.Document, job.doc_id)
        if doc:
            doc.status, doc.error_message = job.status, job.error
        logger.warning('job_id=%s worker_id=%s attempt=%s status=%s error_type=%s',
                       job.id, job.worker_id, job.attempts, job.status, error_type)
        return True


def retry(job_id, *, user_id=None) -> bool:
    with db.Session.begin() as s:
        if user_id is not None:
            row = s.get(IngestionJob, job_id)
            if row is None:
                return False
            from .auth import require_kb
            require_kb(user_id, row.kb_id, 'editor', session=s)
        job = s.execute(select(IngestionJob).where(IngestionJob.id == job_id)
                        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if job is None or job.status != 'failed' or s.get(db.Document, job.doc_id) is None:
            return False
        job.status, job.attempts, job.error = 'queued', 0, ''
        job.available_at = job.updated_at = _now(s)
        job.finished_at = job.lease_until = job.claim_token = None
        doc = s.get(db.Document, job.doc_id)
        doc.status, doc.error_message = 'queued', ''
        return True


def delete_knowledge_base(kb_id, *, user_id=None):
    with db.Session.begin() as s:
        if user_id is not None:
            from .auth import active_user
            active_user(s, user_id)
        kb = s.execute(select(db.KnowledgeBase).where(db.KnowledgeBase.id == kb_id)
                       .with_for_update()).scalar_one_or_none()
        if kb is None:
            return
        if user_id is not None:
            from .auth import require_kb
            require_kb(user_id, kb_id, 'owner', session=s)
        rows = s.execute(select(IngestionJob).where(IngestionJob.kb_id == kb_id)
                         .order_by(IngestionJob.id).with_for_update()).scalars().all()
        for job in rows:
            job.status, job.claim_token, job.lease_until = 'cancelled', None, None
            job.finished_at = job.updated_at = _now(s)
        s.query(db.Chunk).filter(db.Chunk.kb_id == kb_id).delete()
        s.query(db.Document).filter(db.Document.kb_id == kb_id).delete()
        from .auth import KBMembership
        s.query(KBMembership).filter(KBMembership.kb_id == kb_id).delete()
        # Original files are removed by reference-aware maintenance after a grace period.
        s.delete(kb)


def serialize(job):
    return {name: getattr(job, name) for name in ('id', 'doc_id', 'kb_id', 'status', 'attempts',
            'max_attempts', 'error', 'available_at', 'lease_until', 'updated_at', 'finished_at')}

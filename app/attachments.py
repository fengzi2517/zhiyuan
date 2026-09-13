"""Private conversation resources and their durable, fenced processing tasks."""
import logging
import secrets
from datetime import timedelta
from pathlib import Path
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, UniqueConstraint, select, func, or_, and_
from pgvector.sqlalchemy import Vector
from fastapi import HTTPException
from . import db, auth, jobs, config, queue_lease as lease
from .file_pipeline import (validate_upload, store_atomic, IMAGE_SUFFIXES,
                            MAX_FILES, MAX_BATCH_BYTES)

logger = logging.getLogger(__name__)


class Attachment(db.Base):
    __tablename__ = 'chat_attachments'
    id = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    is_image = Column(Boolean, default=False, nullable=False)
    storage_path = Column(Text, nullable=False)
    image_path = Column(Text, default='')
    content = Column(Text, default='')
    ocr_available = Column(Boolean, default=False)
    status = Column(String, default='queued', nullable=False)
    error = Column(Text, default='')
    used = Column(Boolean, default=False, nullable=False)
    deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AttachmentChunk(db.Base):
    __tablename__ = 'attachment_chunks'
    id = Column(Integer, primary_key=True)
    attachment_id = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    page_start = Column(Integer)
    page_end = Column(Integer)
    section = Column(String, default='')
    start_char = Column(Integer)
    end_char = Column(Integer)
    embedding = Column(Vector(config.EMBEDDING_DIM))


class AttachmentJob(db.Base):
    __tablename__ = 'attachment_jobs'
    id = Column(Integer, primary_key=True)
    attachment_id = Column(String, nullable=False, unique=True)
    status = Column(String, default='queued', nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    available_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lease_until = Column(DateTime(timezone=True))
    claim_token = Column(String)
    worker_id = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class AttachmentPromotion(db.Base):
    __tablename__ = 'attachment_promotions'
    id = Column(Integer, primary_key=True)
    attachment_id = Column(String, nullable=False)
    kb_id = Column(Integer, nullable=False)
    doc_id = Column(Integer, nullable=False)
    job_id = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('attachment_id', 'kb_id'),)


def serialize(item):
    return {key: getattr(item, key) for key in (
        'id', 'session_id', 'filename', 'size', 'is_image', 'status', 'error',
        'ocr_available', 'used', 'created_at')}


def require_items(s, user_id, session_id, ids, *, ready=False):
    auth.require_conversation(user_id, session_id, session=s)
    if len(ids) > MAX_FILES or len(set(ids)) != len(ids):
        raise HTTPException(400, '每次最多选择 5 个不重复附件')
    rows = {r.id: r for r in s.query(Attachment).filter(
        Attachment.id.in_(ids), Attachment.user_id == user_id,
        Attachment.session_id == session_id, Attachment.deleted.is_(False))}
    if len(rows) != len(ids):
        raise HTTPException(404, '附件不存在或不属于当前会话')
    items = [rows[i] for i in ids]
    if sum(i.size for i in items) > MAX_BATCH_BYTES:
        raise HTTPException(413, '本次附件总大小超过 50 MB')
    if ready and any(i.status != 'ready' for i in items):
        raise HTTPException(409, '请等待全部附件就绪，失败附件需要重试或移除')
    return items


def path_for(item, *, image=False):
    path = Path(item.image_path if image else item.storage_path).resolve()
    expected = (Path(jobs.UPLOAD_DIR) / ('attachment-' + item.id)).resolve()
    if path.parent != expected or not path.is_file():
        raise HTTPException(409, '附件原件不存在或路径无效，请重新上传')
    return path


def enqueue(user_id, session_id, files):
    if not files or len(files) > MAX_FILES or sum(len(data) for _, data in files) > MAX_BATCH_BYTES:
        raise ValueError('每次最多 5 个附件、总计 50 MB')
    for filename, data in files:
        validate_upload(filename, data)
    paths = []
    try:
        with db.Session.begin() as s:
            auth.require_conversation(user_id, session_id, claim=True, session=s)
            result = []
            for filename, data in files:
                ident = secrets.token_hex(16)
                suffix = Path(filename).suffix.lower()
                path = Path(jobs.UPLOAD_DIR).resolve() / ('attachment-' + ident) / ('source' + suffix)
                paths.append(path)
                store_atomic(path, data)
                item = Attachment(id=ident, user_id=user_id, session_id=session_id,
                    filename=Path(filename).name, size=len(data), is_image=suffix in IMAGE_SUFFIXES,
                    storage_path=str(path))
                s.add(item)
                s.add(AttachmentJob(attachment_id=ident))
                s.flush()
                result.append(serialize(item))
            return result
    except BaseException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def list_items(user_id, session_id):
    with db.Session() as s:
        # Listing a new, unclaimed conversation is read-only and must not claim its ID.
        auth.active_user(s, user_id)
        if not session_id or len(session_id) > 200:
            raise HTTPException(400, '会话标识无效')
        db._lock_session(s, session_id)
        if s.get(auth.ConversationOwner, session_id) is None:
            legacy = s.query(db.ChatMessage.id).filter_by(session_id=session_id).first()
            memory = s.query(db.SessionMemory.id).filter_by(session_id=session_id).first()
            if not legacy and not memory:
                return []
        auth.require_conversation(user_id, session_id, session=s)
        return [serialize(i) for i in s.query(Attachment).filter_by(
            user_id=user_id, session_id=session_id, deleted=False).order_by(Attachment.created_at, Attachment.id)]


def cancel_in_session(s, session_id, ids=None):
    query = s.query(Attachment).filter_by(session_id=session_id, deleted=False)
    if ids is not None:
        query = query.filter(Attachment.id.in_(ids))
    items = query.all()
    tasks = s.execute(select(AttachmentJob).where(AttachmentJob.attachment_id.in_([i.id for i in items]))
                      .order_by(AttachmentJob.id).with_for_update()).scalars().all()
    for task in tasks:
        task.status, task.claim_token, task.lease_until = 'cancelled', None, None
    for item in items:
        item.deleted, item.status = True, 'cancelled'
        s.query(AttachmentChunk).filter_by(attachment_id=item.id).delete()


def remove(user_id, session_id, ident):
    with db.Session.begin() as s:
        require_items(s, user_id, session_id, [ident])
        cancel_in_session(s, session_id, [ident])


def retry(user_id, session_id, ident):
    with db.Session.begin() as s:
        item = require_items(s, user_id, session_id, [ident])[0]
        job = s.execute(select(AttachmentJob).where(AttachmentJob.attachment_id == ident)
                        .with_for_update()).scalar_one()
        s.refresh(item)
        if job.status != 'failed':
            raise HTTPException(409, '仅失败附件可以重试')
        job.status, job.attempts, job.claim_token, job.lease_until = 'queued', 0, None, None
        job.available_at = job.updated_at = lease.now(s)
        item.status, item.error = 'queued', ''
        return serialize(item)


def claim(worker_id):
    with db.Session.begin() as s:
        now = lease.now(s)
        job = s.execute(select(AttachmentJob).where(or_(
            and_(AttachmentJob.status.in_(['queued', 'retry_wait']), AttachmentJob.available_at <= now),
            and_(AttachmentJob.status == 'running', AttachmentJob.lease_until <= now)))
            .order_by(AttachmentJob.available_at, AttachmentJob.id).with_for_update(skip_locked=True)
            .limit(1)).scalar_one_or_none()
        if job is None:
            return None
        item = s.get(Attachment, job.attachment_id)
        owner = s.get(auth.ConversationOwner, item.session_id) if item else None
        if not item or item.deleted or not owner or owner.deleted:
            job.status = 'cancelled'
            return None
        if job.attempts >= jobs.MAX_ATTEMPTS:
            job.status = item.status = 'failed'
            item.error = '重试次数已耗尽，请检查 Worker 后手动重试'
            return None
        job.attempts += 1
        job.status = item.status = 'running'
        job.claim_token = secrets.token_hex(24)
        job.worker_id = worker_id
        job.updated_at = now
        job.lease_until = now + timedelta(seconds=jobs.LEASE_SECONDS)
        logger.info('task=attachment job_id=%s attempt=%s status=running', job.id, job.attempts)
        return dict(id=job.id, token=job.claim_token, attachment_id=item.id,
                    user_id=item.user_id, session_id=item.session_id, filename=item.filename,
                    storage_path=item.storage_path, is_image=item.is_image)


def heartbeat(job_id, token):
    with db.Session.begin() as s:
        return lease.renew(s, AttachmentJob, job_id, token, jobs.LEASE_SECONDS)


def complete(claimed, content, chunks, vectors, image_path=''):
    with db.Session.begin() as s:
        db._lock_session(s, claimed['session_id'])
        job = lease.owned(s, AttachmentJob, claimed['id'], claimed['token'])
        item = s.get(Attachment, claimed['attachment_id'])
        owner = s.get(auth.ConversationOwner, claimed['session_id'])
        if job is None or not item or item.deleted or not owner or owner.deleted:
            return False
        if chunks:
            jobs.validate_vectors(chunks, vectors)
        elif not item.is_image or not image_path:
            raise ValueError('未提取到可用内容')
        s.query(AttachmentChunk).filter_by(attachment_id=item.id).delete()
        for chunk, vector in zip(chunks, vectors):
            fields = {name: getattr(chunk, name, None) for name in (
                'page_start', 'page_end', 'section', 'start_char', 'end_char')}
            s.add(AttachmentChunk(attachment_id=item.id, content=chunk.content, embedding=vector, **fields))
        item.content, item.image_path = content, image_path
        item.ocr_available = bool(content.strip())
        item.status, item.error = 'ready', ''
        job.status, job.claim_token, job.lease_until = 'succeeded', None, None
        job.updated_at = lease.now(s)
        return True


def fail(claimed, *, permanent=False, error_type='Error', stage='unknown'):
    with db.Session.begin() as s:
        job = lease.owned(s, AttachmentJob, claimed['id'], claimed['token'])
        if job is None:
            return False
        item = s.get(Attachment, claimed['attachment_id'])
        terminal = permanent or job.attempts >= jobs.MAX_ATTEMPTS
        job.status = item.status = 'failed' if terminal else 'retry_wait'
        item.error = f'{stage} 阶段处理失败，请检查文件或重试（{error_type}）'
        job.claim_token = job.lease_until = None
        job.updated_at = lease.now(s)
        job.available_at = job.updated_at + timedelta(seconds=min(300, 5 * 2 ** min(job.attempts, 6)))
        logger.warning('task=attachment job_id=%s stage=%s error_type=%s', job.id, stage, error_type)
        return True


def promote(user_id, session_id, ident, kb_id):
    target = None
    try:
        with db.Session.begin() as s:
            item = require_items(s, user_id, session_id, [ident], ready=True)[0]
            auth.require_kb(user_id, kb_id, 'editor', session=s)
            existing = s.query(AttachmentPromotion).filter_by(attachment_id=ident, kb_id=kb_id).first()
            if existing:
                doc = s.get(db.Document, existing.doc_id)
                if doc:
                    return dict(doc_id=doc.id, job_id=existing.job_id, kb_id=kb_id, status=doc.status)
                s.delete(existing)
                s.flush()
            data = path_for(item).read_bytes()
            result, target = jobs.enqueue_in_session(s, kb_id, item.filename, data)
            s.add(AttachmentPromotion(attachment_id=ident, kb_id=kb_id,
                                     doc_id=result['doc_id'], job_id=result['job_id']))
            return result
    except BaseException:
        if target:
            target.unlink(missing_ok=True)
        raise

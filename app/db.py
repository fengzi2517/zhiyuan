from sqlalchemy import JSON, create_engine, Column, Integer, String, DateTime, Text, text, Index, func
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from . import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
Session = sessionmaker(bind=engine)


def _lock_session(session, session_id: str) -> None:
    """Serialize conversation writers for the lifetime of this transaction."""
    bind = getattr(session, "bind", None)
    if getattr(getattr(bind, "dialect", None), "name", None) == "postgresql":
        key = int.from_bytes(hashlib.sha256(session_id.encode("utf-8")).digest()[:8],
                             byteorder="big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _assert_embedding_dimension(actual_type: str | None, expected_dim: int) -> None:
    expected_type = f"vector({expected_dim})"
    if actual_type and actual_type != expected_type:
        raise RuntimeError(
            f"数据库向量类型为 {actual_type}，配置要求 {expected_type}。"
            "请先备份数据并执行显式重建迁移；应用不会自动删除文档。"
        )

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    description = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, index=True)   # 所属向量库，NULL 表示未分类（检索全部时兼容）
    filename = Column(String)
    status = Column(String, default="pending")   # pending / done / failed
    content = Column(Text, default="")     # 提取的全文文本（供前端查看）
    storage_path = Column(Text, default="")
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, index=True)
    doc_id = Column(Integer, index=True)
    content = Column(Text)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    section = Column(String, default="")
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)
    embedding = Column(Vector(config.EMBEDDING_DIM))

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(String, index=True)
    role = Column(String)          # user / assistant
    content = Column(Text)
    semantic_intent = Column(String, default="")
    route = Column(String, default="")
    sources = Column(JSON, default=list)
    trace = Column(JSON, default=list)
    elapsed_ms = Column(Integer, nullable=True)
    status = Column(String, default="complete")
    model_options = Column(JSON, default=dict)
    attachments = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

Index("ix_chat_messages_session_created", ChatMessage.session_id, ChatMessage.created_at)


def metadata_migration_statements() -> list[str]:
    """Return additive migrations for installations created by earlier releases."""
    return [
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_path TEXT",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_start INTEGER",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_end INTEGER",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section VARCHAR",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS start_char INTEGER",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS end_char INTEGER",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS semantic_intent VARCHAR",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS route VARCHAR",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sources JSON",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS trace JSON",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS elapsed_ms INTEGER",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'complete'",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model_options JSON",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS attachments JSON",
    ]

def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    # 轻量迁移：为存量表补充 kb_id 列（幂等）
    with engine.connect() as conn:
        for table in ("documents", "chunks"):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS kb_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_kb_id ON documents (kb_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_kb_id ON chunks (kb_id)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT"))
        for statement in metadata_migration_statements():
            conn.execute(text(statement))
        conn.commit()
    # 向量维度安全检查：不匹配时拒绝启动，避免应用启动过程静默删除业务数据
    # 注意：pgvector 的 atttypmod 即维度本身（vector(1024) → typmod=1024），
    # 不能用 varchar 的 typmod-4 约定判断，否则每次重启都会误清库
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid=c.oid "
            "WHERE c.relname='chunks' AND a.attname='embedding' AND NOT a.attisdropped"
        )).first()
        _assert_embedding_dimension(row[0] if row else None, config.EMBEDDING_DIM)
    # HNSW 近似最近邻索引（余弦距离），数据量大时避免全表线性扫描
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"))
        conn.commit()

# ---------- 向量库管理 ----------
def create_kb(name: str, description: str = "", user_id: int | None = None) -> dict:
    with Session() as s:
        kb = KnowledgeBase(name=name, description=description)
        s.add(kb); s.flush()
        if user_id is not None:
            from .auth import KBMembership
            s.add(KBMembership(kb_id=kb.id, user_id=user_id, role="owner"))
        s.commit(); s.refresh(kb)
        return {"id": kb.id, "name": kb.name, "description": kb.description}

def list_kbs(allowed_kb_ids=None) -> list[dict]:
    with Session() as s:
        rows = (s.query(KnowledgeBase, func.count(Document.id))
                   .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
                   .filter(KnowledgeBase.id.in_(allowed_kb_ids) if allowed_kb_ids is not None else True)
                   .group_by(KnowledgeBase.id)
                   .order_by(KnowledgeBase.id.desc()).all())
        return [{"id": kb.id, "name": kb.name, "description": kb.description,
                 "doc_count": cnt} for kb, cnt in rows]

def delete_kb(kb_id: int):
    with Session() as s:
        s.query(Chunk).filter(Chunk.kb_id == kb_id).delete()
        s.query(Document).filter(Document.kb_id == kb_id).delete()
        kb = s.get(KnowledgeBase, kb_id)
        if kb:
            s.delete(kb)
        s.commit()

# ---------- 文档 ----------
def create_document(filename: str, kb_id: int | None = None) -> int:
    with Session() as s:
        d = Document(filename=filename, kb_id=kb_id)
        s.add(d); s.commit(); s.refresh(d)
        return d.id

def set_status(doc_id: int, status: str, error_message: str = ""):
    with Session() as s:
        doc = s.get(Document, doc_id)
        if doc:
            doc.status = status
            doc.error_message = error_message
            s.commit()

def save_chunks(doc_id: int, kb_id: int | None, chunks, embeddings: list[list[float]]):
    with Session() as s:
        rows = []
        for chunk, embedding in zip(chunks, embeddings):
            if isinstance(chunk, str):
                rows.append(Chunk(doc_id=doc_id, kb_id=kb_id, content=chunk, embedding=embedding))
            else:
                rows.append(Chunk(
                    doc_id=doc_id, kb_id=kb_id, content=chunk.content, embedding=embedding,
                    page_start=chunk.page_start, page_end=chunk.page_end,
                    section=chunk.section, start_char=chunk.start_char, end_char=chunk.end_char,
                ))
        s.add_all(rows)
        s.commit()


def save_document_storage_path(doc_id: int, storage_path: str):
    with Session() as s:
        document = s.get(Document, doc_id)
        if document:
            document.storage_path = storage_path
            s.commit()

def save_document_text(doc_id: int, text: str):
    """保存提取的全文文本（供前端查看）"""
    with Session() as s:
        d = s.get(Document, doc_id)
        if d:
            d.content = text
            s.commit()

def get_document_content(doc_id: int) -> dict | None:
    with Session() as s:
        d = s.get(Document, doc_id)
        if not d:
            return None
        return {"id": d.id, "filename": d.filename, "kb_id": d.kb_id,
                "content": d.content or "", "status": d.status,
                "error_message": d.error_message or ""}


def get_document_file_info(doc_id: int) -> dict | None:
    with Session() as s:
        document = s.get(Document, doc_id)
        if not document:
            return None
        return {
            "id": document.id, "filename": document.filename,
            "storage_path": document.storage_path or "", "status": document.status,
        }


def get_chunk_context(doc_id: int, chunk_id: int) -> dict | None:
    with Session() as s:
        row = (
            s.query(Chunk, Document)
            .join(Document, Document.id == Chunk.doc_id)
            .filter(Chunk.id == chunk_id, Chunk.doc_id == doc_id)
            .first()
        )
        if not row:
            return None
        chunk, document = row
        return {
            "document": {"id": document.id, "filename": document.filename},
            "chunk": {
                "id": chunk.id, "content": chunk.content,
                "page_start": chunk.page_start, "page_end": chunk.page_end,
                "section": chunk.section or "", "start_char": chunk.start_char,
                "end_char": chunk.end_char,
            },
        }

def get_kb_chunks_for_viz(kb_id: int | None, limit: int = 3000) -> list[dict]:
    """取库内向量块（含原文与文档名）供 PCA 可视化；大库按最新截断采样"""
    with Session() as s:
        q = (s.query(Chunk.id, Chunk.doc_id, Chunk.content, Chunk.embedding, Document.filename)
               .outerjoin(Document, Document.id == Chunk.doc_id))
        if kb_id is not None:
            q = q.filter(Chunk.kb_id == kb_id)
        rows = q.order_by(Chunk.id.desc()).limit(limit).all()
    return [{"chunk_id": r[0], "doc_id": r[1], "content": r[2],
             "embedding": r[3], "filename": r[4] or f"文档{r[1]}"} for r in rows]

def list_documents(kb_id: int | None = None, limit: int = 50, allowed_kb_ids=None) -> list[dict]:
    with Session() as s:
        q = s.query(Document)
        if allowed_kb_ids is not None:
            q = q.filter(Document.kb_id.in_(allowed_kb_ids))
        if kb_id is not None:
            q = q.filter(Document.kb_id == kb_id)
        return [{"id": d.id, "kb_id": d.kb_id, "filename": d.filename,
                 "status": d.status, "error_message": d.error_message or ""}
                for d in q.order_by(Document.id.desc()).limit(limit)]


def has_documents(kb_id: int | None = None, allowed_kb_ids=None) -> bool:
    with Session() as s:
        query = s.query(Document.id).filter(Document.status == "done")
        if allowed_kb_ids is not None:
            query = query.filter(Document.kb_id.in_(allowed_kb_ids))
        if kb_id is not None:
            query = query.filter(Document.kb_id == kb_id)
        return query.first() is not None

def search_chunks(question: str, kb_id: int | None = None, top_k: int = 4) -> list[str]:
    from .embeddings import embed_texts
    qe = embed_texts([question], is_query=True)[0]
    with Session() as s:
        q = s.query(Chunk.content)
        if kb_id is not None:
            q = q.filter(Chunk.kb_id == kb_id)
        rows = q.order_by(Chunk.embedding.cosine_distance(qe)).limit(top_k).all()
    return [r[0] for r in rows]

def search_chunks_with_scores(question: str, kb_id: int | None = None, top_k: int = 8) -> list[tuple[str, float]]:
    """向量召回，返回 (片段, 余弦相似度) 按相似度降序"""
    from .embeddings import embed_texts
    from sqlalchemy import text as _text
    qe = embed_texts([question], is_query=True)[0]
    with Session() as s:
        sql = ("SELECT content, 1 - (embedding <=> CAST(:qe AS vector)) AS sim "
               "FROM chunks")
        params = {"qe": str(qe), "k": top_k}
        if kb_id is not None:
            sql += " WHERE kb_id = :kb"
            params["kb"] = kb_id
        sql += " ORDER BY embedding <=> CAST(:qe AS vector) LIMIT :k"
        rows = s.execute(_text(sql), params).all()
    return [(r[0], float(r[1])) for r in rows]


def search_chunk_sources(question: str, kb_id: int | None = None, top_k: int = 8, allowed_kb_ids=None) -> list[dict]:
    """Vector retrieval with stable document and location metadata."""
    from .embeddings import embed_texts
    from sqlalchemy import text as _text

    if allowed_kb_ids is not None and not allowed_kb_ids:
        return []
    qe = embed_texts([question], is_query=True)[0]
    sql = (
        "SELECT c.id, c.doc_id, d.filename, c.content, c.page_start, c.page_end, "
        "c.section, c.start_char, c.end_char, "
        "1 - (c.embedding <=> CAST(:qe AS vector)) AS sim "
        "FROM chunks c LEFT JOIN documents d ON d.id = c.doc_id"
    )
    params = {"qe": str(qe), "k": top_k}
    conditions = []
    if kb_id is not None:
        conditions.append("c.kb_id = :kb")
        params["kb"] = kb_id
    if allowed_kb_ids is not None:
        conditions.append("c.kb_id IN (" + ",".join(":scope"+str(i) for i in range(len(allowed_kb_ids))) + ")")
        params.update({"scope"+str(i):value for i,value in enumerate(allowed_kb_ids)})
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.embedding <=> CAST(:qe AS vector) LIMIT :k"
    with Session() as session:
        rows = session.execute(_text(sql), params).all()

    results = []
    for row in rows:
        page_start, page_end = row[4], row[5]
        if page_start and page_end and page_start != page_end:
            location = f"第 {page_start}–{page_end} 页"
        elif page_start:
            location = f"第 {page_start} 页"
        elif row[6]:
            location = row[6]
        else:
            location = f"字符 {row[7] or 0}–{row[8] or 0}"
        results.append({
            "chunk_id": row[0], "document_id": row[1],
            "title": row[2] or f"文档 {row[1]}", "content": row[3],
            "page_start": page_start, "page_end": page_end, "section": row[6] or "",
            "start_char": row[7], "end_char": row[8],
            "location": location, "score": float(row[9]),
        })
    return results

# ---------- 会话长期记忆（分层记忆：摘要 + 事实要点） ----------
class SessionMemory(Base):
    __tablename__ = "session_memories"
    id = Column(Integer, primary_key=True)
    session_id = Column(String, unique=True, index=True)
    summary = Column(Text, default="")      # 全局对话摘要（连贯性）
    facts = Column(Text, default="")        # 关键事实/实体/决策要点（换行分隔）
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

def get_memory(session_id: str) -> dict | None:
    with Session() as s:
        m = s.query(SessionMemory).filter(SessionMemory.session_id == session_id).first()
        if not m:
            return None
        return {"summary": m.summary, "facts": m.facts, "updated_at": str(m.updated_at)}

def save_memory(session_id: str, summary: str, facts: str):
    with Session() as s:
        _lock_session(s, session_id)
        _store_memory(s, session_id, summary, facts)
        s.commit()


def _store_memory(s, session_id: str, summary: str, facts: str) -> None:
    m = s.query(SessionMemory).filter(SessionMemory.session_id == session_id).first()
    if m:
        m.summary, m.facts = summary, facts
    else:
        s.add(SessionMemory(session_id=session_id, summary=summary, facts=facts))


def _memory_snapshot(s, session_id: str) -> dict | None:
    rows = (s.query(ChatMessage.id, ChatMessage.role, ChatMessage.content)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc()).all())
    if not rows:
        return None
    memory = s.query(SessionMemory).filter(SessionMemory.session_id == session_id).first()
    serialized = None if memory is None else {
        "summary": memory.summary, "facts": memory.facts, "updated_at": str(memory.updated_at),
    }
    state = {"messages": [tuple(row) for row in rows], "memory": serialized}
    token = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"token": token, "memory": serialized, "last_message_id": rows[-1][0]}


def get_memory_snapshot(session_id: str) -> dict | None:
    """Return a revision token, releasing the lock before any model work."""
    with Session() as s:
        _lock_session(s, session_id)
        return _memory_snapshot(s, session_id)


def save_memory_if_current(session_id: str, token: str, summary: str, facts: str) -> bool:
    """Discard background output if messages or memory changed since its snapshot."""
    with Session() as s:
        _lock_session(s, session_id)
        snapshot = _memory_snapshot(s, session_id)
        if snapshot is None or snapshot["token"] != token:
            return False
        _store_memory(s, session_id, summary, facts)
        s.commit()
        return True

# ---------- 会话历史 ----------
def list_sessions(user_id=None) -> list[dict]:
    """会话列表：按最近活跃排序，含消息数与预览"""
    with Session() as s:
        from .auth import ConversationOwner
        rows = (s.query(ChatMessage.session_id, func.count(ChatMessage.id),
                        func.max(ChatMessage.created_at))
                   .filter(ChatMessage.session_id.in_(s.query(ConversationOwner.session_id).filter(ConversationOwner.user_id == user_id, ConversationOwner.deleted == False)) if user_id is not None else True)
                   .group_by(ChatMessage.session_id)
                   .order_by(func.max(ChatMessage.created_at).desc()).all())
        result = []
        for sid, cnt, last_at in rows:
            first = (s.query(ChatMessage.content)
                       .filter(ChatMessage.session_id == sid, ChatMessage.role == "user")
                       .order_by(ChatMessage.id.asc()).first())
            result.append({
                "session_id": sid,
                "message_count": cnt,
                "last_at": str(last_at),
                "preview": (first[0][:40] if first else "") or "（空会话）",
            })
        # Uploaded work must remain discoverable before the first successful answer.
        from .attachments import Attachment
        known = {row['session_id'] for row in result}
        pending = (s.query(Attachment.session_id, func.max(Attachment.created_at))
                   .join(ConversationOwner, ConversationOwner.session_id == Attachment.session_id)
                   .filter(Attachment.deleted.is_(False), ConversationOwner.deleted.is_(False),
                           ConversationOwner.user_id == Attachment.user_id)
                   .filter(Attachment.user_id == user_id if user_id is not None else True)
                   .group_by(Attachment.session_id).all())
        for sid, last_at in pending:
            if sid in known:
                continue
            first = s.query(Attachment.filename).filter_by(session_id=sid, deleted=False).order_by(Attachment.created_at, Attachment.id).first()
            if first is None:  # Another request removed the last attachment after the aggregate read.
                continue
            result.append(dict(session_id=sid, message_count=0, last_at=str(last_at),
                               preview=f'附件：{first[0][:35]}'))
        return sorted(result, key=lambda row: row['last_at'], reverse=True)

def get_session_messages(session_id: str) -> list[dict]:
    with Session() as s:
        rows = (s.query(ChatMessage)
                  .filter(ChatMessage.session_id == session_id)
                  .order_by(ChatMessage.id.asc()).all())
        return [serialize_message(m) for m in rows]


def serialize_message(message: ChatMessage) -> dict:
    outcome = next((step for step in reversed(message.trace or [])
                    if step.get("stage") == "outcome"), {})
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": str(message.created_at),
        "semantic_intent": message.semantic_intent or "",
        "route": message.route or "",
        "sources": message.sources or [],
        "trace": message.trace or [],
        "elapsed_ms": message.elapsed_ms,
        "status": message.status or "complete",
        "run_id": outcome.get("run_id", ""),
        "answer_mode": outcome.get("answer_mode", ""),
        "warnings": outcome.get("warnings", []),
        "model_options": message.model_options or {},
        "attachments": message.attachments or [],
    }

def update_message(msg_id: int, content: str) -> bool:
    with Session() as s:
        owner = s.query(ChatMessage.session_id).filter(ChatMessage.id == msg_id).first()
        if not owner:
            return False
        _lock_session(s, owner[0])
        m = s.get(ChatMessage, msg_id, populate_existing=True)
        if not m:
            return False
        m.content = content
        if m.role == "assistant":
            m.sources, m.trace = [], []
            m.semantic_intent, m.route = "", ""
            m.elapsed_ms = None
            m.status = "edited"
        s.query(SessionMemory).filter(SessionMemory.session_id == m.session_id).delete()
        s.commit()
        return True

def delete_session(session_id: str, user_id=None):
    with Session() as s:
        _lock_session(s, session_id)
        if user_id is not None:
            from .auth import require_conversation, ConversationOwner
            require_conversation(user_id, session_id, session=s)
            s.get(ConversationOwner, session_id).deleted = True
        from .attachments import cancel_in_session
        cancel_in_session(s, session_id)
        s.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        s.query(SessionMemory).filter(SessionMemory.session_id == session_id).delete()
        s.commit()

def save_message(session_id: str, role: str, content: str, metadata: dict | None = None) -> int:
    with Session() as s:
        _lock_session(s, session_id)
        message = _new_message(session_id, role, content, metadata)
        s.add(message)
        s.flush()
        message_id = message.id
        s.commit()
        return message_id


def save_exchange(session_id: str, question: str, answer: str,
                  metadata: dict | None = None, *, capture_memory: bool = False, user_id=None, allowed_kb_ids=None, login_hash=None) -> dict[str, Any]:
    """Persist a completed user/assistant pair atomically and in message order."""
    with Session() as s:
        _lock_session(s, session_id)
        if user_id is not None:
            from .auth import require_conversation, require_kb, active_user
            active_user(s, user_id)
            if login_hash is not None:
                from .auth import LoginSession, now
                from fastapi import HTTPException
                login = s.query(LoginSession).filter_by(token_hash=login_hash).with_for_update(read=True).first()
                if not login or login.user_id != user_id or login.revoked or login.expires_at <= now():
                    raise HTTPException(401, "登录会话已失效")
            require_conversation(user_id, session_id, session=s)
            for kb_id in allowed_kb_ids or []:
                require_kb(user_id, kb_id, session=s)
        metadata = dict(metadata or {})
        attachment_ids = metadata.pop('_attachment_ids', [])
        if attachment_ids:
            from .attachments import require_items, serialize
            items = require_items(s, user_id, session_id, attachment_ids, ready=True)
            for item in items:
                item.used = True
            metadata['attachments'] = [serialize(item) for item in items]
            for item in metadata['attachments']:
                item['created_at'] = str(item['created_at'])
        user = _new_message(session_id, "user", question, {
            'model_options': metadata.get('model_options', {}),
            'attachments': metadata.get('attachments', []),
        })
        s.add(user)
        s.flush()
        assistant = _new_message(session_id, "assistant", answer, metadata)
        s.add(assistant)
        s.flush()
        ids = {"user": user.id, "assistant": assistant.id}
        if capture_memory:
            ids["_memory_snapshot"] = _memory_snapshot(s, session_id)
        s.commit()
        return ids


def _new_message(session_id: str, role: str, content: str,
                 metadata: dict | None = None) -> ChatMessage:
    metadata = metadata or {}
    return ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        semantic_intent=metadata.get("semantic_intent", ""),
        route=metadata.get("route", ""),
        sources=metadata.get("sources", []),
        trace=metadata.get("trace", []),
        elapsed_ms=metadata.get("elapsed_ms"),
        status=metadata.get("status", "complete"),
        model_options=metadata.get('model_options', {}),
        attachments=metadata.get('attachments', []),
    )

def get_history(session_id: str, limit: int = 6) -> list[str]:
    """取最近 limit 条消息，格式化为 Q:/A: 行，按时间正序返回"""
    with Session() as s:
        rows = (s.query(ChatMessage.role, ChatMessage.content)
                  .filter(ChatMessage.session_id == session_id)
                  .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                  .limit(limit).all())
    lines = [f"{'Q' if r[0] == 'user' else 'A'}: {r[1]}" for r in reversed(rows)]
    return lines

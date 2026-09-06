from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, text, Index, func
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone
from . import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)


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
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, index=True)
    doc_id = Column(Integer, index=True)
    content = Column(Text)
    embedding = Column(Vector(config.EMBEDDING_DIM))

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(String, index=True)
    role = Column(String)          # user / assistant
    content = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

Index("ix_chat_messages_session_created", ChatMessage.session_id, ChatMessage.created_at)

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
def create_kb(name: str, description: str = "") -> dict:
    with Session() as s:
        kb = KnowledgeBase(name=name, description=description)
        s.add(kb); s.commit(); s.refresh(kb)
        return {"id": kb.id, "name": kb.name, "description": kb.description}

def list_kbs() -> list[dict]:
    with Session() as s:
        rows = (s.query(KnowledgeBase, func.count(Document.id))
                   .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
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

def save_chunks(doc_id: int, kb_id: int | None, chunks: list[str], embeddings: list[list[float]]):
    with Session() as s:
        s.add_all([Chunk(doc_id=doc_id, kb_id=kb_id, content=c, embedding=e)
                   for c, e in zip(chunks, embeddings)])
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

def list_documents(kb_id: int | None = None, limit: int = 50) -> list[dict]:
    with Session() as s:
        q = s.query(Document)
        if kb_id is not None:
            q = q.filter(Document.kb_id == kb_id)
        return [{"id": d.id, "kb_id": d.kb_id, "filename": d.filename,
                 "status": d.status, "error_message": d.error_message or ""}
                for d in q.order_by(Document.id.desc()).limit(limit)]

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
        m = s.query(SessionMemory).filter(SessionMemory.session_id == session_id).first()
        if m:
            m.summary, m.facts = summary, facts
        else:
            s.add(SessionMemory(session_id=session_id, summary=summary, facts=facts))
        s.commit()

# ---------- 会话历史 ----------
def list_sessions() -> list[dict]:
    """会话列表：按最近活跃排序，含消息数与预览"""
    with Session() as s:
        rows = (s.query(ChatMessage.session_id, func.count(ChatMessage.id),
                        func.max(ChatMessage.created_at))
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
        return result

def get_session_messages(session_id: str) -> list[dict]:
    with Session() as s:
        rows = (s.query(ChatMessage)
                  .filter(ChatMessage.session_id == session_id)
                  .order_by(ChatMessage.id.asc()).all())
        return [{"id": m.id, "role": m.role, "content": m.content,
                 "created_at": str(m.created_at)} for m in rows]

def update_message(msg_id: int, content: str) -> bool:
    with Session() as s:
        m = s.get(ChatMessage, msg_id)
        if not m:
            return False
        m.content = content
        s.commit()
        return True

def delete_session(session_id: str):
    with Session() as s:
        s.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        s.query(SessionMemory).filter(SessionMemory.session_id == session_id).delete()
        s.commit()

def save_message(session_id: str, role: str, content: str) -> int:
    with Session() as s:
        message = ChatMessage(session_id=session_id, role=role, content=content)
        s.add(message)
        s.commit()
        s.refresh(message)
        return message.id

def get_history(session_id: str, limit: int = 6) -> list[str]:
    """取最近 limit 条消息，格式化为 Q:/A: 行，按时间正序返回"""
    with Session() as s:
        rows = (s.query(ChatMessage.role, ChatMessage.content)
                  .filter(ChatMessage.session_id == session_id)
                  .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                  .limit(limit).all())
    lines = [f"{'Q' if r[0] == 'user' else 'A'}: {r[1]}" for r in reversed(rows)]
    return lines

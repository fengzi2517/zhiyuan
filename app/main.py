from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, BackgroundTasks, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import logging
from copy import copy
from . import auth
from . import jobs
from .auth_routes import router as auth_router

from .db import (init_db, create_document, list_documents, set_status, Document,
                 Session, get_history, save_message,
                 create_kb, list_kbs, delete_kb,
                 list_sessions, get_session_messages, update_message, delete_session,
                 get_memory, save_memory, has_documents, search_chunk_sources,
                 save_exchange, get_memory_snapshot, save_memory_if_current,
                 get_chunk_context, get_document_file_info)
from . import config
from .llm import (update_memory, understand_structured, rewrite_for_search,
                  chat as llm_chat, chat_stream as llm_chat_stream)
from .embeddings import rerank_sources
from .ingest import process_file
from .search import web_search
from .chat_service import ChatService, SYSTEM_POLICY, WorkflowError
from .sse import encode_sse, ClosingStreamingResponse
from .config import UPLOAD_DIR

logger = logging.getLogger(__name__)


def generation_messages(prompt):
    return [{"role": "system", "content": SYSTEM_POLICY}, {"role": "user", "content": prompt}]

chat_service = ChatService(
    understand=understand_structured,
    has_knowledge=has_documents,
    search_kb=search_chunk_sources,
    search_web=web_search,
    generate=lambda prompt: llm_chat(generation_messages(prompt)),
    stream_generate=lambda prompt: llm_chat_stream(generation_messages(prompt)),
    rerank_kb=rerank_sources,
    rewrite_query=rewrite_for_search,
    candidate_k=config.CANDIDATE_K,
    rerank_threshold=config.RERANK_THRESHOLD,
)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024   # 20MB

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        app_logger.addHandler(handler)
    app_logger.propagate = False
    from .migrate import require_schema
    require_schema()
    yield

app = FastAPI(title="RAG 知识库智能问答", lifespan=lifespan)

app.include_router(auth_router)
from .operations import router as operations_router, request_log
app.include_router(operations_router)
app.middleware('http')(request_log)
app.add_middleware(
    CORSMiddleware, allow_origins=auth.TRUSTED_ORIGINS,
    allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

def _uid(user):
    # Direct legacy unit callers have no HTTP dependency injection.
    return user.id if isinstance(user, auth.User) else None

# ---------- 向量库管理 ----------
class KbReq(BaseModel):
    name: str
    description: str = ""

@app.post("/kbs")
def api_create_kb(req: KbReq, user=Depends(auth.current_user)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="向量库名称不能为空")
    return create_kb(req.name.strip(), req.description.strip(), user_id=_uid(user))

@app.get("/kbs")
def api_list_kbs(user=Depends(auth.current_user)):
    with Session() as s:
        roles = {m.kb_id: m.role for m in s.query(auth.KBMembership).filter_by(user_id=user.id)}
    return [{**kb, 'role': roles[kb['id']]} for kb in list_kbs(allowed_kb_ids=list(roles))]

@app.delete("/kbs/{kb_id}")
def api_delete_kb(kb_id: int, user=Depends(auth.current_user)):
    auth.require_kb(user.id, kb_id, "owner")
    jobs.delete_knowledge_base(kb_id, user_id=user.id)
    return {"ok": True}

# ---------- 资料上传 ----------
@app.post("/upload", status_code=202)
async def upload(file: UploadFile, background: BackgroundTasks, kb_id: Optional[int] = None, user=Depends(auth.current_user)):
    auth.require_kb(user.id, kb_id, "editor")
    if Path(file.filename or '').suffix.lower() not in jobs.ALLOWED_SUFFIXES:
        raise HTTPException(400, '不支持的文件类型')
    data = bytearray()
    try:
        while block := await file.read(1024 * 1024):
            data.extend(block)
            if len(data) > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=413, detail="文件超过 20MB 上限")
    finally:
        await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    from starlette.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(jobs.enqueue, kb_id, file.filename, bytes(data), user_id=user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.get("/documents")
def api_list_docs(kb_id: Optional[int] = None, user=Depends(auth.current_user)):
    if kb_id is not None: auth.require_kb(user.id, kb_id)
    rows = list_documents(kb_id, allowed_kb_ids=auth.allowed_kb_ids(user.id))
    with Session() as s:
        states = {j.doc_id: jobs.serialize(j) for j in s.query(jobs.IngestionJob)
                  .filter(jobs.IngestionJob.doc_id.in_([r['id'] for r in rows]))}
    return [{**row, 'job': states.get(row['id'])} for row in rows]


@app.get('/documents/{doc_id}/job')
def document_job(doc_id: int, user=Depends(auth.current_user)):
    auth.require_document(user.id, doc_id)
    with Session() as s:
        job = s.query(jobs.IngestionJob).filter_by(doc_id=doc_id).first()
        if job is None:
            raise HTTPException(404, '旧文档没有任务记录，请重新上传')
        return jobs.serialize(job)


@app.post('/documents/{doc_id}/retry', status_code=202)
def retry_document(doc_id: int, user=Depends(auth.current_user)):
    auth.require_document(user.id, doc_id)
    with Session() as s:
        job = s.query(jobs.IngestionJob).filter_by(doc_id=doc_id).first()
        if job is None:
            raise HTTPException(409, '旧文档没有任务记录，请重新上传')
        auth.require_kb(user.id, job.kb_id, 'editor')
        job_id = job.id
    if not jobs.retry(job_id, user_id=user.id):
        raise HTTPException(409, '仅失败任务可以重试')
    return {'job_id': job_id, 'status': 'queued'}

@app.get("/documents/{doc_id}/content")
def api_doc_content(doc_id: int, user=Depends(auth.current_user)):
    if _uid(user) is not None: auth.require_document(user.id, doc_id)
    """查看上传资料的提取文本"""
    from .db import get_document_content
    content = get_document_content(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return content


@app.get("/documents/{doc_id}/chunks/{chunk_id}/context")
def api_chunk_context(doc_id: int, chunk_id: int, user=Depends(auth.current_user)):
    if _uid(user) is not None: auth.require_document(user.id, doc_id)
    context = get_chunk_context(doc_id, chunk_id)
    if context is None:
        raise HTTPException(status_code=404, detail="引用位置不存在")
    return context


def resolve_document_path(base_dir: str | Path, doc_id: int, stored_path: str) -> Path:
    expected_dir = (Path(base_dir) / str(doc_id)).resolve()
    candidate = Path(stored_path).resolve()
    if candidate.parent != expected_dir or not candidate.is_file():
        raise HTTPException(status_code=409, detail="文档原件路径无效，请重新入库")
    return candidate


@app.get("/documents/{doc_id}/original")
def api_document_original(doc_id: int, user=Depends(auth.current_user)):
    if _uid(user) is not None: auth.require_document(user.id, doc_id)
    info = get_document_file_info(doc_id)
    if info is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not info["storage_path"]:
        raise HTTPException(status_code=409, detail="旧文档没有原件定位信息，请重新入库")
    path = resolve_document_path(jobs.UPLOAD_DIR, doc_id, info["storage_path"])
    return FileResponse(path, filename=info["filename"])

@app.get("/kbs/{kb_id}/vectors")
def api_kb_vectors(kb_id: Optional[int] = None, user=Depends(auth.current_user)):
    if _uid(user) is not None: auth.require_kb(user.id, kb_id)
    """向量库可视化：PCA 降至二维，返回散点数据（按文档分组着色）。
    超过 3000 块时按最新截断采样，避免大库全量拉取拖垮内存。"""
    from .db import get_kb_chunks_for_viz
    try:
        rows = get_kb_chunks_for_viz(kb_id, limit=3000)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"读取向量数据失败：{type(e).__name__}: {e}")
    if not rows:
        return {"points": [], "docs": [], "variance": []}
    try:
        proj, var = _project_vectors([r["embedding"] for r in rows])
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"PCA 降维失败：{type(e).__name__}: {e}")
    doc_names = {r["doc_id"]: r["filename"] for r in rows}
    points = [{"x": round(float(p[0]), 3), "y": round(float(p[1]), 3),
               "doc_id": r["doc_id"], "doc": doc_names[r["doc_id"]],
               "chunk_id": r["chunk_id"], "preview": r["content"][:80]}
              for p, r in zip(proj, rows)]
    return {"points": points,
            "docs": [{"doc_id": k, "filename": v} for k, v in doc_names.items()],
            "variance": [round(float(v), 3) for v in var[:2]]}


def _project_vectors(vectors: list[list[float]]) -> tuple[list[list[float]], list[float]]:
    """将向量安全投影到二维；小样本和零方差数据也返回有限数值。"""
    import numpy as np

    if not vectors:
        return [], []
    X = np.asarray(vectors, dtype=np.float32)
    if len(X) == 1:
        return [[0.0, 0.0]], [0.0, 0.0]
    X = X - X.mean(axis=0)
    _, singular_values, components = np.linalg.svd(X, full_matrices=False)
    dimensions = min(2, components.shape[0])
    projection = X @ components[:dimensions].T
    if dimensions < 2:
        projection = np.pad(projection, ((0, 0), (0, 2 - dimensions)))
    total_variance = float((singular_values ** 2).sum())
    if total_variance == 0.0:
        variance = [0.0, 0.0]
    else:
        variance = ((singular_values ** 2) / total_variance)[:2].tolist()
        variance += [0.0] * (2 - len(variance))
    return projection[:, :2].tolist(), variance

# ---------- 问答 ----------
class ChatReq(BaseModel):
    question: str = Field(min_length=1)
    session_id: str = "default"
    kb_id: Optional[int] = None   # 指定向量库检索；None 检索全部
    top_k: int = Field(default=4, ge=1, le=10)  # 最终注入的片段数上限
    web_enabled: bool = True      # 知识库不足时是否联网搜索兜底
    sim_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    use_memory: bool = True       # 是否启用会话长期记忆

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value

def _refresh_memory(session_id: str, question: str, answer: str, snapshot: dict):
    """Run model work outside the transaction; discard obsolete background results."""
    try:
        current = get_memory_snapshot(session_id)
        if current is None or current["token"] != snapshot["token"]:
            logger.info("memory session_id=%s status=obsolete", session_id)
            return
        new = update_memory(snapshot["memory"], question, answer)
        if new:
            saved = save_memory_if_current(session_id, snapshot["token"], new["summary"], new["facts"])
            logger.info("memory session_id=%s status=%s", session_id, "saved" if saved else "obsolete")
    except Exception as exc:
        logger.warning("memory session_id=%s status=failed error_type=%s", session_id, type(exc).__name__)


def _chat_options(req):
    try:
        history = get_history(req.session_id, limit=6)
        memory = get_memory(req.session_id) if req.use_memory else None
    except Exception as exc:
        logger.warning("chat context unavailable error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="暂时无法读取会话，请稍后重试。") from exc
    return dict(history=history, memory=memory, kb_id=req.kb_id, top_k=req.top_k,
                web_enabled=req.web_enabled, sim_threshold=req.sim_threshold)


def _persist_result(req, result, background, user=None, scopes=None):
    capture_memory = req.use_memory and result.get("answer_mode") != "insufficient_evidence"
    kwargs = {} if _uid(user) is None else {"user_id": user.id, "allowed_kb_ids": scopes}
    if _uid(user) is not None:
        kwargs['login_hash'] = getattr(user, '_login_hash', None)
    ids = save_exchange(req.session_id, req.question, result["answer"], result,
                        capture_memory=capture_memory, **kwargs)
    snapshot = ids.pop("_memory_snapshot", None)
    if snapshot:
        background.add_task(_refresh_memory, req.session_id, req.question,
                            result["answer"], snapshot)
    return ids


def _authorized_chat(req, user):
    if _uid(user) is None: return chat_service, None
    auth.require_conversation(user.id, req.session_id, claim=True)
    if req.kb_id is not None: auth.require_kb(user.id, req.kb_id)
    scopes = [req.kb_id] if req.kb_id is not None else auth.allowed_kb_ids(user.id)
    service = copy(chat_service)
    service._has_knowledge = lambda kb_id: has_documents(kb_id, allowed_kb_ids=scopes)
    service._search_kb = lambda question, kb_id, top_k: search_chunk_sources(question, kb_id, top_k, allowed_kb_ids=scopes)
    return service, scopes


@app.post("/chat")
def chat(req: ChatReq, background: BackgroundTasks, user=Depends(auth.current_user)):
    service, scopes = _authorized_chat(req, user)
    options = _chat_options(req)
    try:
        result = service.run(req.question, **options).model_dump()
    except WorkflowError as exc:
        raise HTTPException(status_code=502, detail=exc.data) from exc
    except Exception as exc:
        logger.warning("chat workflow failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="问答处理失败，请稍后重试。") from exc
    try:
        result["message_ids"] = _persist_result(req, result, background, user, scopes)
    except Exception as exc:
        logger.warning("run_id=%s persistence failed error_type=%s",
                       result.get("run_id", ""), type(exc).__name__)
        raise HTTPException(status_code=503, detail="回答已生成，但会话保存失败，请稍后重试。") from exc
    return {**result, "intent": result["semantic_intent"]}


@app.post("/chat/stream")
def chat_stream(req: ChatReq, background: BackgroundTasks, user=Depends(auth.current_user)):
    service, scopes = _authorized_chat(req, user)
    options = _chat_options(req)

    def events():
        upstream = service.run_stream(req.question, **options)
        run_id, phase = "", "workflow"
        try:
            for event in upstream:
                if event["event"] in ("route", "done"):
                    run_id = event["data"].get("run_id", run_id)
                if event["event"] == "done":
                    phase = "persistence"
                    result = event["data"]
                    result["message_ids"] = _persist_result(req, result, background, user, scopes)
                yield encode_sse(event["event"], event["data"])
                if event["event"] in ("done", "error"):
                    return
            raise RuntimeError("upstream ended without terminal event")
        except Exception as exc:
            logger.warning("run_id=%s phase=%s error_type=%s", run_id, phase, type(exc).__name__)
            yield encode_sse("error", {
                "code": "persistence_failed" if phase == "persistence" else "stream_incomplete",
                "message": "会话保存失败，请稍后重试。" if phase == "persistence" else "回答意外中断，请重试。",
                "run_id": run_id, "status": "error",
            })
        finally:
            close = getattr(upstream, "close", None)
            if close:
                close()

    return ClosingStreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ---------- 会话历史管理 ----------
@app.get("/sessions")
def api_list_sessions(user=Depends(auth.current_user)):
    return list_sessions(user_id=user.id)

@app.get("/sessions/{session_id}/messages")
def api_session_messages(session_id: str, user=Depends(auth.current_user)):
    auth.require_conversation(user.id, session_id)
    return get_session_messages(session_id)

@app.delete("/sessions/{session_id}")
def api_delete_session(session_id: str, user=Depends(auth.current_user)):
    delete_session(session_id, user_id=user.id)
    return {"ok": True}

@app.get("/sessions/{session_id}/memory")
def api_session_memory(session_id: str, user=Depends(auth.current_user)):
    auth.require_conversation(user.id, session_id)
    return get_memory(session_id) or {"summary": "", "facts": ""}

class MessageEditReq(BaseModel):
    content: str

@app.put("/messages/{msg_id}")
def api_edit_message(msg_id: int, req: MessageEditReq, user=Depends(auth.current_user)):
    from .db import ChatMessage
    with Session() as s:
        message = s.get(ChatMessage, msg_id)
        if not message: raise HTTPException(404, "消息不存在")
        auth.require_conversation(user.id, message.session_id, session=s)
    if not update_message(msg_id, req.content):
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"ok": True}

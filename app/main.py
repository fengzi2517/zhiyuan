from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from .db import (init_db, create_document, list_documents, set_status, Document,
                 Session, get_history, save_message,
                 create_kb, list_kbs, delete_kb,
                 list_sessions, get_session_messages, update_message, delete_session,
                 get_memory, save_memory, has_documents, search_chunk_sources,
                 get_chunk_context, get_document_file_info)
from .llm import update_memory, understand_structured, chat as llm_chat, chat_stream as llm_chat_stream
from .ingest import process_file
from .search import web_search
from .chat_service import ChatService
from .sse import encode_sse
from .config import UPLOAD_DIR

chat_service = ChatService(
    understand=understand_structured,
    has_knowledge=has_documents,
    search_kb=search_chunk_sources,
    search_web=web_search,
    generate=lambda prompt: llm_chat([{"role": "user", "content": prompt}]),
    stream_generate=lambda prompt: llm_chat_stream([{"role": "user", "content": prompt}]),
)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024   # 20MB

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="RAG 知识库智能问答", lifespan=lifespan)

# 前端开发服务器跨域放行（Vite 端口不固定，放行本机任意端口）
import re
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 向量库管理 ----------
class KbReq(BaseModel):
    name: str
    description: str = ""

@app.post("/kbs")
def api_create_kb(req: KbReq):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="向量库名称不能为空")
    return create_kb(req.name.strip(), req.description.strip())

@app.get("/kbs")
def api_list_kbs():
    return list_kbs()

@app.delete("/kbs/{kb_id}")
def api_delete_kb(kb_id: int):
    delete_kb(kb_id)
    return {"ok": True}

# ---------- 资料上传 ----------
@app.post("/upload")
async def upload(file: UploadFile, background: BackgroundTasks, kb_id: Optional[int] = None):
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 20MB 上限")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    doc_id = create_document(file.filename, kb_id)
    background.add_task(process_file, doc_id, kb_id, file.filename, data)
    return {"doc_id": doc_id, "kb_id": kb_id, "status": "processing"}

@app.get("/documents")
def api_list_docs(kb_id: Optional[int] = None):
    return list_documents(kb_id)

@app.get("/documents/{doc_id}/content")
def api_doc_content(doc_id: int):
    """查看上传资料的提取文本"""
    from .db import get_document_content
    content = get_document_content(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return content


@app.get("/documents/{doc_id}/chunks/{chunk_id}/context")
def api_chunk_context(doc_id: int, chunk_id: int):
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
def api_document_original(doc_id: int):
    info = get_document_file_info(doc_id)
    if info is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not info["storage_path"]:
        raise HTTPException(status_code=409, detail="旧文档没有原件定位信息，请重新入库")
    path = resolve_document_path(UPLOAD_DIR, doc_id, info["storage_path"])
    return FileResponse(path, filename=info["filename"])

@app.get("/kbs/{kb_id}/vectors")
def api_kb_vectors(kb_id: Optional[int] = None):
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

def _refresh_memory(session_id: str, question: str, answer: str):
    """后台任务：增量更新会话长期记忆（不阻塞响应）"""
    try:
        old = get_memory(session_id)
        new = update_memory(old, question, answer)
        if new:
            save_memory(session_id, new["summary"], new["facts"])
        print(f"[memory] session={session_id} updated={bool(new)}", flush=True)
    except Exception as e:
        print(f"[memory] ERROR {type(e).__name__}: {e}", flush=True)

@app.post("/chat")
def chat(req: ChatReq, background: BackgroundTasks):
    # 1) 取会话历史与长期记忆
    history = get_history(req.session_id, limit=6)
    memory = get_memory(req.session_id) if req.use_memory else None

    # 2) 查询理解与执行路由在 ChatService 中集中完成
    try:
        out = chat_service.run(
            req.question, history=history, memory=memory, kb_id=req.kb_id,
            top_k=req.top_k, web_enabled=req.web_enabled,
            sim_threshold=req.sim_threshold,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"问答编排失败：{type(e).__name__}: {e}")
    answer = out.answer

    # 3) 回写会话历史，后台更新长期记忆
    user_message_id = save_message(req.session_id, "user", req.question)
    metadata = {
        "semantic_intent": out.semantic_intent, "route": out.route,
        "sources": [source.model_dump() for source in out.sources],
        "trace": out.trace, "elapsed_ms": out.elapsed_ms, "status": out.status,
    }
    assistant_message_id = save_message(req.session_id, "assistant", answer, metadata)
    if req.use_memory:
        background.add_task(_refresh_memory, req.session_id, req.question, answer)

    return {
        "answer": answer,
        "message_ids": {"user": user_message_id, "assistant": assistant_message_id},
        "intent": out.semantic_intent,
        "semantic_intent": out.semantic_intent,
        "route": out.route,
        "elapsed_ms": out.elapsed_ms,
        "trace": out.trace,
        "sources": metadata["sources"],
        "status": out.status,
    }


@app.post("/chat/stream")
def chat_stream(req: ChatReq, background: BackgroundTasks):
    history = get_history(req.session_id, limit=6)
    memory = get_memory(req.session_id) if req.use_memory else None

    def events():
        for event in chat_service.run_stream(
            req.question, history=history, memory=memory, kb_id=req.kb_id,
            top_k=req.top_k, web_enabled=req.web_enabled,
            sim_threshold=req.sim_threshold,
        ):
            if event["event"] == "done":
                result = event["data"]
                user_id = save_message(req.session_id, "user", req.question)
                assistant_id = save_message(req.session_id, "assistant", result["answer"], result)
                result["message_ids"] = {"user": user_id, "assistant": assistant_id}
                if req.use_memory:
                    background.add_task(_refresh_memory, req.session_id, req.question, result["answer"])
            yield encode_sse(event["event"], event["data"])

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ---------- 会话历史管理 ----------
@app.get("/sessions")
def api_list_sessions():
    return list_sessions()

@app.get("/sessions/{session_id}/messages")
def api_session_messages(session_id: str):
    return get_session_messages(session_id)

@app.delete("/sessions/{session_id}")
def api_delete_session(session_id: str):
    delete_session(session_id)
    return {"ok": True}

@app.get("/sessions/{session_id}/memory")
def api_session_memory(session_id: str):
    return get_memory(session_id) or {"summary": "", "facts": ""}

class MessageEditReq(BaseModel):
    content: str

@app.put("/messages/{msg_id}")
def api_edit_message(msg_id: int, req: MessageEditReq):
    if not update_message(msg_id, req.content):
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"ok": True}

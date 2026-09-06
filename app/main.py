from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from .db import (init_db, create_document, list_documents, set_status, Document,
                 Session, get_history, save_message,
                 create_kb, list_kbs, delete_kb,
                 list_sessions, get_session_messages, update_message, delete_session,
                 get_memory, save_memory)
from .llm import update_memory
from .ingest import process_file
from .graph import rag_graph

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

@app.get("/kbs/{kb_id}/vectors")
def api_kb_vectors(kb_id: Optional[int] = None):
    """向量库可视化：PCA 降至二维，返回散点数据（按文档分组着色）。
    超过 3000 块时按最新截断采样，避免大库全量拉取拖垮内存。"""
    import numpy as np
    from .db import get_kb_chunks_for_viz
    try:
        rows = get_kb_chunks_for_viz(kb_id, limit=3000)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"读取向量数据失败：{type(e).__name__}: {e}")
    if not rows:
        return {"points": [], "docs": [], "variance": []}
    try:
        X = np.array([r["embedding"] for r in rows], dtype=np.float32)
        X = X - X.mean(axis=0)
        # 截断 SVD 取前两主成分
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        proj = X @ Vt[:2].T
        var = (S ** 2) / (S ** 2).sum()
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

# ---------- 问答 ----------
class ChatReq(BaseModel):
    question: str
    session_id: str = "default"
    kb_id: Optional[int] = None   # 指定向量库检索；None 检索全部
    top_k: int = 4                # 最终注入的片段数上限
    web_enabled: bool = True      # 知识库不足时是否联网搜索兜底
    sim_threshold: float = 0.4    # 向量相似度粗筛阈值
    use_memory: bool = True       # 是否启用会话长期记忆

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
    import time as _time
    t0 = _time.perf_counter()
    # 1) 取会话历史与长期记忆
    history = get_history(req.session_id, limit=6)
    memory = get_memory(req.session_id) if req.use_memory else None

    # 2) RAG 编排：意图识别 → 查询改写 → 召回粗筛 → 精排 → 兜底 → 生成
    try:
        out = rag_graph.invoke({
            "question": req.question,
            "history": history,
            "memory": memory,
            "kb_id": req.kb_id,
            "top_k": req.top_k,
            "web_enabled": req.web_enabled,
            "sim_threshold": req.sim_threshold,
            "intent": "kb",
            "query": req.question,
            "candidates": [],
            "docs": [],
            "web_results": [],
            "retries": 0,
            "answer": "",
            "trace": [],
        })
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"问答编排失败：{type(e).__name__}: {e}")
    answer = out["answer"]

    # 3) 回写会话历史，后台更新长期记忆
    save_message(req.session_id, "user", req.question)
    save_message(req.session_id, "assistant", answer)
    if req.use_memory:
        background.add_task(_refresh_memory, req.session_id, req.question, answer)

    return {
        "answer": answer,
        "intent": out["intent"],
        "elapsed_ms": round((_time.perf_counter() - t0) * 1000),
        "trace": out.get("trace", []),
        "sources": {
            "kb": out["docs"],
            "web": [{"title": r["title"], "url": r["url"]}
                    for r in out["web_results"]],
        },
    }

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

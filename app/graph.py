from typing import TypedDict
import time
from langgraph.graph import StateGraph, START, END
from .db import search_chunks_with_scores
from .llm import chat, understand
from .embeddings import rerank
from . import config
from .search import web_search

MAX_RETRIES = 1   # 查询改写重试次数
MIN_DOCS = 1      # 精排后相关片段达到该阈值即直接生成

class RAGState(TypedDict):
    question: str            # 用户原始问题
    history: list[str]       # 会话历史（近期窗口）
    memory: dict | None      # 会话长期记忆 {summary, facts}
    kb_id: int | None        # 检索的向量库，None 检索全部
    top_k: int               # 最终注入 prompt 的片段数上限
    web_enabled: bool        # 知识库不足时是否允许联网搜索兜底
    sim_threshold: float     # 向量相似度粗筛阈值
    intent: str              # kb / web / chitchat
    query: str               # 改写后的检索 query
    candidates: list         # 粗筛后候选 [(片段, 相似度)]
    docs: list[str]          # 精排后相关知识库片段
    web_results: list[dict]  # 联网搜索结果 [{title, url, content}]
    retries: int
    answer: str
    trace: list              # 处理过程轨迹 [{stage, ...}] 供前端展示

def _timed(fn):
    """节点装饰器：记录执行耗时（ms）与时间戳，附加到 trace 条目"""
    def wrapper(state: RAGState) -> dict:
        t0 = time.perf_counter()
        out = fn(state)
        ms = round((time.perf_counter() - t0) * 1000)
        if out and "trace" in out and isinstance(out["trace"], list):
            # 更新本节点新增的 trace 条目（最后一条）
            idx = len(state.get("trace", []))
            for i, entry in enumerate(out["trace"][idx:], start=idx):
                out["trace"][i] = {**entry, "ms": ms if i == len(out["trace"]) - 1 else entry.get("ms")}
        return out
    return wrapper

def _trace(state, entry: dict):
    """向 trace 追加一步（不可变更新）"""
    return {"trace": state.get("trace", []) + [entry]}

# ---------- 节点 ----------
@_timed
def understand_node(state: RAGState) -> dict:
    """意图识别 + 查询改写（一次 LLM 调用）"""
    result = understand(state["question"], state["history"])
    route = {"kb": "检索知识库", "web": "联网搜索", "chitchat": "直接回答"}[result["intent"]]
    return {"intent": result["intent"], "query": result["query"],
            "trace": [{"stage": "understand", "intent": result["intent"],
                       "query": result["query"], "reason": result.get("reason", ""),
                       "rewritten": result["query"] != state["question"],
                       "route": route}]}

@_timed
def chitchat(state: RAGState) -> dict:
    """闲聊直接回答（带历史与记忆，不检索）"""
    hist = "\n".join(state["history"][-6:])
    mem = state.get("memory")
    mem_part = f"【会话记忆】\n{mem['summary']}\n{mem['facts']}\n" if mem else ""
    prompt = (f"你是 AI 知识库问答助手，友好简洁地回应用户。{mem_part}"
              f"对话历史：\n{hist}\n用户：{state['question']}")
    return {"answer": chat([{"role": "user", "content": prompt}]),
            **_trace(state, {"stage": "chitchat", "note": "非知识库问题，跳过检索直接回答"})}

@_timed
def retrieve(state: RAGState) -> dict:
    """向量召回 + 相似度粗筛"""
    rows = search_chunks_with_scores(state["query"], state["kb_id"], config.CANDIDATE_K)
    passed = [(c, s) for c, s in rows if s >= state["sim_threshold"]]
    return {"candidates": passed,
            **_trace(state, {"stage": "retrieve",
                             "candidates": [{"text": c[:60], "sim": round(s, 3)} for c, s in rows],
                             "passed": len(passed), "threshold": state["sim_threshold"]})}

@_timed
def rerank_node(state: RAGState) -> dict:
    """交叉编码器精排：本地 bge-reranker 打分，阈值过滤后取 top_k。
    模型不可用时降级为相似度排序。"""
    cands = state["candidates"]
    if not cands:
        return {"docs": [], "retries": state["retries"] + 1,
                **_trace(state, {"stage": "rerank", "note": "无候选片段通过粗筛"})}
    docs = [c for c, _ in cands]
    scores = rerank(state["query"], docs)
    if scores is None:   # 降级：相似度已降序，直接取前 top_k
        keep = docs[:state["top_k"]]
        return {"docs": keep,
                "retries": state["retries"] + (1 if not keep else 0),
                **_trace(state, {"stage": "rerank", "mode": "降级（相似度排序）", "kept": len(keep)})}
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    keep = [d for d, s in ranked
            if s >= config.RERANK_THRESHOLD][:state["top_k"]]
    if not keep:
        return {"docs": [], "retries": state["retries"] + 1,
                **_trace(state, {"stage": "rerank",
                                 "scores": [{"text": d[:60], "score": round(s, 3)} for d, s in ranked],
                                 "kept": 0})}
    return {"docs": keep,
            **_trace(state, {"stage": "rerank",
                             "scores": [{"text": d[:60], "score": round(s, 3)} for d, s in ranked],
                             "kept": len(keep)})}

@_timed
def rewrite(state: RAGState) -> dict:
    prompt = (f"将这个问题改写为更适合检索知识库的表述（换同义词、补全术语），只输出改写后的问题："
              f"{state['question']}")
    new_q = chat([{"role": "user", "content": prompt}]).strip()
    return {"query": new_q,
            **_trace(state, {"stage": "rewrite", "query": new_q})}

@_timed
def web_search_node(state: RAGState) -> dict:
    """联网搜索（主动路径或知识库不足的兜底路径）"""
    is_fallback = state.get("intent") == "kb"   # kb 意图走到这里说明是兜底
    results = web_search(state["query"], max_results=3)
    return {"web_results": results,
            **_trace(state, {"stage": "web_search", "query": state["query"],
                             "results": [{"title": r["title"][:40], "url": r["url"]} for r in results],
                             "fallback": is_fallback,
                             "note": "知识库检索不足，联网补充" if is_fallback else "需要实时信息，直接联网"})}

GEN_TMPL = """你是 AI 知识库问答助手。严格基于提供的资料回答，资料不足就说不知道，不要编造。
网络搜索结果仅供参考，请注意甄别其时效性与准确性。
{memory}【对话历史（近期）】
{history}
【知识库资料（已按相关性精排）】
{context}
【网络搜索结果】
{web}
用户问题：{question}"""

@_timed
def generate(state: RAGState) -> dict:
    hist = "\n".join(state["history"][-6:])
    mem = state.get("memory")
    mem_part = ""
    if mem and (mem.get("summary") or mem.get("facts")):
        mem_part = ("【会话长期记忆（本会话更早的关键信息）】\n"
                    f"摘要：{mem['summary']}\n要点：\n{mem['facts']}\n\n")
    ctx = "\n---\n".join(state["docs"]) if state["docs"] else "（未检索到相关资料）"
    web = "\n---\n".join(f"[{r['title']}]({r['url']})\n{r['content']}"
                         for r in state["web_results"]) or "（未使用联网搜索）"
    prompt = GEN_TMPL.format(memory=mem_part, history=hist, context=ctx,
                             web=web, question=state["question"])
    return {"answer": chat([{"role": "user", "content": prompt}]),
            **_trace(state, {"stage": "generate",
                             "kb_docs": len(state["docs"]),
                             "web_docs": len(state["web_results"]),
                             "memory_used": bool(mem)})}

# ---------- 路由 ----------
def _after_understand(state: RAGState) -> str:
    if state["intent"] == "chitchat":
        return "chitchat"
    if state["intent"] == "web":
        return "web_search" if state["web_enabled"] else "generate"
    return "retrieve"

def _after_rerank(state: RAGState) -> str:
    if len(state["docs"]) >= MIN_DOCS:
        return "generate"
    if state["retries"] <= MAX_RETRIES:
        return "rewrite"        # 换个表述重试检索
    if state["web_enabled"]:
        return "web_search"     # 知识库不足且重试用尽，联网补充
    return "generate"           # 联网被关闭，直接基于现有资料回答

def build_graph():
    g = StateGraph(RAGState)
    g.add_node("understand", understand_node)
    g.add_node("chitchat", chitchat)
    g.add_node("retrieve", retrieve)
    g.add_node("rerank", rerank_node)
    g.add_node("rewrite", rewrite)
    g.add_node("web_search", web_search_node)
    g.add_node("generate", generate)

    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", _after_understand,
                            {"chitchat": "chitchat", "web_search": "web_search",
                             "retrieve": "retrieve", "generate": "generate"})
    g.add_edge("retrieve", "rerank")
    g.add_conditional_edges("rerank", _after_rerank,
                            {"rewrite": "rewrite", "web_search": "web_search",
                             "generate": "generate"})
    g.add_edge("rewrite", "retrieve")   # 改写后重新召回精排
    g.add_edge("web_search", "generate")
    g.add_edge("chitchat", END)
    g.add_edge("generate", END)
    return g.compile()

rag_graph = build_graph()

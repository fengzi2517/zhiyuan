import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .query_understanding import QueryUnderstanding
from .routing import RouteContext, decide_route
from .sources import Source, number_sources, normalize_web_url, validate_answer_citations


class ChatResult(BaseModel):
    answer: str
    semantic_intent: str
    route: str
    sources: list[Source]
    trace: list[dict]
    elapsed_ms: int
    status: str = "complete"


class ChatService:
    def __init__(
        self,
        *,
        understand: Callable[..., QueryUnderstanding],
        has_knowledge: Callable[[int | None], bool],
        search_kb: Callable[..., list[dict]],
        search_web: Callable[..., list[dict]],
        generate: Callable[[str], str],
        stream_generate: Callable[[str], Any] | None = None,
        rerank_kb: Callable[[str, list[dict]], list[dict]] | None = None,
        rewrite_query: Callable[[str], str] | None = None,
        candidate_k: int = 8,
        rerank_threshold: float = 0.3,
    ):
        self._understand = understand
        self._has_knowledge = has_knowledge
        self._search_kb = search_kb
        self._search_web = search_web
        self._generate = generate
        self._stream_generate = stream_generate
        self._rerank_kb = rerank_kb
        self._rewrite_query = rewrite_query
        self._candidate_k = candidate_k
        self._rerank_threshold = rerank_threshold

    def run(
        self,
        question: str,
        *,
        history: list[str] | None = None,
        memory: dict | None = None,
        kb_id: int | None = None,
        top_k: int = 4,
        web_enabled: bool = True,
        sim_threshold: float = 0.4,
    ) -> ChatResult:
        started = time.perf_counter()
        trace: list[dict[str, Any]] = []
        result = self._understand(question, history or [])
        has_kb = self._has_knowledge(kb_id)
        decision = decide_route(result, RouteContext(has_kb, web_enabled))
        trace.append({
            "stage": "understand", "label": "理解问题",
            "intent": result.semantic_intent, "reason": result.reason,
        })
        trace.append({
            "stage": "route", "label": "选择处理方式",
            "route": decision.route, "reason": decision.reason,
        })

        sources: list[Source] = []
        if decision.needs_kb:
            rows = self._retrieve_kb(result.query, kb_id, top_k, sim_threshold, trace)
            sources.extend(_kb_sources(rows))
        if decision.needs_web:
            rows = self._search_web(result.query, max_results=3)
            sources.extend(_web_sources(rows))
            trace.append({"stage": "web_search", "label": "检索网络", "count": len(rows)})

        numbered = number_sources(sources)
        prompt = _build_prompt(question, history or [], memory, numbered)
        answer = self._generate(prompt)
        if numbered:
            answer, numbered = validate_answer_citations(answer, numbered)
        trace.append({"stage": "generate", "label": "生成回答"})
        return ChatResult(
            answer=answer,
            semantic_intent=result.semantic_intent,
            route=decision.route,
            sources=numbered,
            trace=trace,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )

    def run_stream(self, question: str, **options):
        """Yield protocol-neutral events while the upstream model emits tokens."""
        started = time.perf_counter()
        trace: list[dict[str, Any]] = []
        try:
            yield {"event": "status", "data": {"phase": "understanding", "label": "理解问题"}}
            history = options.get("history") or []
            result = self._understand(question, history)
            has_kb = self._has_knowledge(options.get("kb_id"))
            decision = decide_route(result, RouteContext(has_kb, options.get("web_enabled", True)))
            trace.extend([
                {"stage": "understand", "label": "理解问题", "intent": result.semantic_intent,
                 "reason": result.reason},
                {"stage": "route", "label": "选择处理方式", "route": decision.route,
                 "reason": decision.reason},
            ])
            yield {"event": "route", "data": {
                "semantic_intent": result.semantic_intent, "route": decision.route,
                "reason": decision.reason,
            }}

            sources: list[Source] = []
            top_k = options.get("top_k", 4)
            if decision.needs_kb:
                threshold = options.get("sim_threshold", 0.4)
                rows = self._retrieve_kb(result.query, options.get("kb_id"), top_k, threshold, trace)
                sources.extend(_kb_sources(rows))
            if decision.needs_web:
                rows = self._search_web(result.query, max_results=3)
                sources.extend(_web_sources(rows))
                trace.append({"stage": "web_search", "label": "检索网络", "count": len(rows)})

            numbered = number_sources(sources)
            prompt = _build_prompt(question, history, options.get("memory"), numbered)
            stream = self._stream_generate(prompt) if self._stream_generate else iter([self._generate(prompt)])
            tokens: list[str] = []
            try:
                for token in stream:
                    if not token:
                        continue
                    tokens.append(token)
                    yield {"event": "token", "data": {"text": token}}
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()

            answer = "".join(tokens)
            if numbered:
                answer, numbered = validate_answer_citations(answer, numbered)
            trace.append({"stage": "generate", "label": "生成回答"})
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            yield {"event": "sources", "data": [source.model_dump() for source in numbered]}
            yield {"event": "trace", "data": trace}
            yield {"event": "done", "data": {
                "answer": answer, "semantic_intent": result.semantic_intent,
                "route": decision.route, "sources": [source.model_dump() for source in numbered],
                "trace": trace, "elapsed_ms": elapsed_ms, "status": "complete",
            }}
        except GeneratorExit:
            raise
        except Exception as exc:
            yield {"event": "error", "data": {
                "message": f"回答生成失败：{type(exc).__name__}: {exc}", "status": "error",
            }}

    def _retrieve_kb(
        self,
        query: str,
        kb_id: int | None,
        top_k: int,
        sim_threshold: float,
        trace: list[dict[str, Any]],
    ) -> list[dict]:
        rows = self._search_kb(query, kb_id, max(top_k, self._candidate_k))
        rows = self._select_kb_rows(query, rows, top_k, sim_threshold, trace)
        trace.append({"stage": "retrieve", "label": "检索知识库", "query": query, "count": len(rows)})
        if rows or self._rewrite_query is None:
            return rows

        rewritten = self._rewrite_query(query).strip()
        if not rewritten or rewritten == query:
            return rows

        trace.append({"stage": "rewrite", "label": "改写检索词", "query": rewritten})
        rows = self._search_kb(rewritten, kb_id, max(top_k, self._candidate_k))
        rows = self._select_kb_rows(rewritten, rows, top_k, sim_threshold, trace)
        trace.append({"stage": "retrieve", "label": "重新检索知识库", "query": rewritten, "count": len(rows)})
        return rows

    def _select_kb_rows(
        self,
        query: str,
        rows: list[dict],
        top_k: int,
        sim_threshold: float,
        trace: list[dict[str, Any]],
    ) -> list[dict]:
        selected = [row for row in rows if row.get("score", 0) >= sim_threshold]
        rerank_applied = False
        if self._rerank_kb is not None and selected:
            try:
                selected = self._rerank_kb(query, selected)
                flags = [row.get("_rerank_applied") for row in selected if "_rerank_applied" in row]
                rerank_applied = any(flags) if flags else True
                trace.append({
                    "stage": "rerank", "label": "精排候选", "count": len(selected),
                    "mode": "交叉编码器" if rerank_applied else "降级为向量相似度",
                })
            except Exception as exc:
                trace.append({
                    "stage": "rerank", "label": "精排候选",
                    "mode": "降级为向量相似度", "error": type(exc).__name__,
                })
        threshold = self._rerank_threshold if rerank_applied else sim_threshold
        return [row for row in selected if row.get("score", 0) >= threshold][:top_k]


def _kb_sources(rows: list[dict]) -> list[Source]:
    return [Source(
        kind="kb", key=f"chunk:{row['chunk_id']}", title=row["title"],
        content=row.get("content", ""), document_id=row.get("document_id"),
        chunk_id=row.get("chunk_id"), location=row.get("location", ""),
        page_start=row.get("page_start"), page_end=row.get("page_end"),
        section=row.get("section", ""), start_char=row.get("start_char"),
        end_char=row.get("end_char"),
        score=row.get("score"),
    ) for row in rows]


def _web_sources(rows: list[dict]) -> list[Source]:
    sources = []
    for row in rows:
        url = normalize_web_url(row.get("url", ""))
        if not url:
            continue
        sources.append(Source(
            kind="web", key=url, title=row.get("title") or url,
            content=row.get("content", ""), url=url,
        ))
    return sources


def _build_prompt(question: str, history: list[str], memory: dict | None, sources: list[Source]) -> str:
    context = "\n\n".join(
        f"[{source.number}] {source.title}（{source.location}）\n{source.content}"
        for source in sources
    )
    citation_rule = (
        "引用资料中的事实时，在相关句末写对应编号，如[1]；同一资料始终使用同一编号。"
        if sources else "直接回答，不要虚构引用编号或声称使用了外部资料。"
    )
    memory_text = ""
    if memory:
        memory_text = f"\n会话记忆：{memory.get('summary', '')}\n{memory.get('facts', '')}"
    history_text = "\n".join(history[-6:]) or "（无）"
    return (
        "你是知识库问答助手。" + citation_rule + memory_text
        + f"\n近期对话：\n{history_text}"
        + f"\n参考资料：\n{context or '（无）'}\n用户问题：{question}"
    )

from app.chat_service import ChatService
from app.query_understanding import QueryUnderstanding


def understanding(intent):
    return QueryUnderstanding(
        semantic_intent=intent, query="检索词",
        needs_kb=intent in {"knowledge", "mixed"},
        needs_web=intent in {"current", "mixed"},
        confidence=0.9, reason="test",
    )


def kb_result():
    return [{
        "chunk_id": 8, "document_id": 2, "title": "制度", "content": "内部规定",
        "location": "第 2 页", "score": 0.9,
    }]


def make_service(intent, calls):
    return ChatService(
        understand=lambda *_: understanding(intent),
        has_knowledge=lambda _kb: True,
        search_kb=lambda *_args, **_kwargs: calls.append("kb") or kb_result(),
        search_web=lambda *_args, **_kwargs: calls.append("web") or [{
            "title": "新规", "url": "https://example.com/a#part", "content": "最新规定",
        }],
        generate=lambda prompt: calls.append("generate") or (
            "综合结论[1][2]" if "[2]" in prompt else "结论[1]" if "[1]" in prompt else "直接回答"
        ),
    )


def test_empty_kb_retrieval_rewrites_query_once():
    calls = []

    service = ChatService(
        understand=lambda *_: understanding("knowledge"),
        has_knowledge=lambda _kb: True,
        search_kb=lambda query, *_args, **_kwargs: calls.append(("kb", query)) or (
            [] if query == "检索词" else kb_result()
        ),
        search_web=lambda *_args, **_kwargs: [],
        generate=lambda prompt: calls.append(("generate", prompt)) or "结论[1]",
        rewrite_query=lambda query: calls.append(("rewrite", query)) or "改写检索词",
    )

    result = service.run("制度是什么", kb_id=1)

    assert result.sources[0].content == "内部规定"
    assert calls[:3] == [("kb", "检索词"), ("rewrite", "检索词"), ("kb", "改写检索词")]


def test_kb_retrieval_uses_reranker_before_numbering_sources():
    calls = []

    service = ChatService(
        understand=lambda *_: understanding("knowledge"),
        has_knowledge=lambda _kb: True,
        search_kb=lambda *_args, **_kwargs: [
            {"chunk_id": 1, "document_id": 1, "title": "弱相关", "content": "泛泛内容", "score": 0.8},
            {"chunk_id": 2, "document_id": 1, "title": "强相关", "content": "命中内容", "score": 0.7},
        ],
        search_web=lambda *_args, **_kwargs: [],
        generate=lambda prompt: calls.append(("generate", prompt)) or "答案[1]",
        rerank_kb=lambda query, rows: [
            {**rows[1], "score": 0.9},
            {**rows[0], "score": 0.1},
        ],
        rerank_threshold=0.3,
    )

    result = service.run("制度是什么", kb_id=1)

    assert [source.title for source in result.sources] == ["强相关"]


def test_vector_fallback_respects_similarity_threshold_only():
    service = ChatService(
        understand=lambda *_: understanding("knowledge"),
        has_knowledge=lambda _kb: True,
        search_kb=lambda *_args, **_kwargs: [
            {"chunk_id": 1, "document_id": 1, "title": "低相似但允许", "content": "内容", "score": 0.25},
        ],
        search_web=lambda *_args, **_kwargs: [],
        generate=lambda _prompt: "答案[1]",
    )

    result = service.run("制度是什么", kb_id=1, sim_threshold=0.2)

    assert [source.title for source in result.sources] == ["低相似但允许"]


def test_reranker_model_fallback_keeps_vector_ranked_rows():
    service = ChatService(
        understand=lambda *_: understanding("knowledge"),
        has_knowledge=lambda _kb: True,
        search_kb=lambda *_args, **_kwargs: [
            {"chunk_id": 1, "document_id": 1, "title": "向量命中", "content": "内容", "score": 0.25},
        ],
        search_web=lambda *_args, **_kwargs: [],
        generate=lambda _prompt: "答案[1]",
        rerank_kb=lambda _query, rows: [{**row, "_rerank_applied": False} for row in rows],
        rerank_threshold=0.3,
    )

    result = service.run("制度是什么", kb_id=1, sim_threshold=0.2)

    assert [source.title for source in result.sources] == ["向量命中"]


def test_direct_route_skips_both_retrievers():
    calls = []
    result = make_service("create", calls).run("写一段话", web_enabled=True)
    assert result.route == "direct"
    assert calls == ["generate"]
    assert result.sources == []


def test_kb_route_returns_numbered_source():
    calls = []
    result = make_service("knowledge", calls).run("制度是什么", kb_id=1)
    assert calls == ["kb", "generate"]
    assert result.route == "kb"
    assert result.sources[0].number == 1


def test_hybrid_route_calls_both_retrievers_and_deduplicates_citations():
    calls = []
    result = make_service("mixed", calls).run("结合资料和新规", kb_id=1, web_enabled=True)
    assert calls == ["kb", "web", "generate"]
    assert result.route == "hybrid"
    assert [source.number for source in result.sources] == [1, 2]

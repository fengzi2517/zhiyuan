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

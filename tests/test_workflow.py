import pytest

from app.chat_service import ChatService
from app.query_understanding import QueryUnderstanding, detect_explicit_intent


def make_service(intent="knowledge", **overrides):
    deps = dict(
        understand=lambda question, _: QueryUnderstanding(
            semantic_intent=intent, query=question, needs_kb=intent in ("knowledge", "mixed"),
            needs_web=intent in ("current", "mixed"), confidence=0.95, reason="test",
        ),
        has_knowledge=lambda _: True,
        search_kb=lambda *_: [{
            "chunk_id": 1, "document_id": 1, "title": "规定", "content": "假期三天。", "score": 0.9,
        }],
        search_web=lambda *_args, **_kwargs: [{
            "title": "公告", "url": "https://example.com/rule", "content": "最新说明。",
        }],
        generate=lambda _: "答复[1]",
        stream_generate=lambda _: iter(["答", "复[1]"]),
    )
    deps.update(overrides)
    return ChatService(**deps)


def test_empty_knowledge_is_an_explicit_outcome_without_generation():
    calls = []
    service = make_service(search_kb=lambda *_: [], generate=lambda _: calls.append("generate"))
    result = service.run("公司假期几天？", kb_id=1)
    assert result.answer_mode == "insufficient_evidence"
    assert "资料" in result.answer
    assert calls == []
    assert result.sources == []
    assert result.run_id


def test_time_sensitive_request_without_web_does_not_invent_current_facts():
    calls = []
    result = make_service(
        "current", has_knowledge=lambda _: False,
        generate=lambda _: calls.append("generate"),
    ).run("今天股价多少？", web_enabled=False)
    assert result.answer_mode == "insufficient_evidence"
    assert "联网" in result.answer
    assert calls == []


def test_hybrid_keeps_web_evidence_when_database_retrieval_fails():
    def unavailable(*_):
        raise RuntimeError("password=do-not-expose")
    result = make_service("mixed", search_kb=unavailable).run("结合公司规定和最新说明")
    assert result.sources[0].kind == "web"
    assert result.answer_mode == "grounded"
    assert result.warnings
    assert "do-not-expose" not in str(result.model_dump())


def test_nonstream_and_stream_share_sources_route_and_stage_contract():
    service = make_service()
    sync = service.run("假期几天？")
    events = list(service.run_stream("假期几天？"))
    done = events[-1]["data"]
    assert done["route"] == sync.route
    assert done["sources"] == [s.model_dump() for s in sync.sources]
    assert done["answer"] == sync.answer
    phases = [e["data"]["phase"] for e in events if e["event"] == "status"]
    assert "retrieving" in phases
    assert "generating" in phases
    assert all("elapsed_ms" in step for step in done["trace"])


def test_closing_stream_closes_upstream_and_does_not_finish():
    closed = []
    def upstream(_):
        try:
            yield "first"
            yield "second"
        finally:
            closed.append(True)
    stream = make_service("create", stream_generate=upstream).run_stream("写一句")
    while next(stream)["event"] != "token":
        pass
    stream.close()
    assert closed == [True]


def test_generation_failure_is_structured_and_hides_internal_details():
    def broken(_):
        raise RuntimeError("secret upstream URL")
    events = list(make_service("create", stream_generate=broken).run_stream("写一句"))
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "generation_failed"
    assert events[-1]["data"]["run_id"]
    assert "secret upstream URL" not in str(events)
    assert not any(e["event"] == "done" for e in events)


def test_direct_answer_removes_invented_citation_numbers():
    result = make_service("create").run("写一句")
    assert "[1]" not in result.answer
    assert result.sources == []


@pytest.mark.parametrize("question", ["你好，请解释向量数据库", "根据上传的文档写一段总结"])
def test_substantive_and_grounded_writing_requests_are_not_direct_shortcuts(question):
    assert detect_explicit_intent(question).semantic_intent == "knowledge"

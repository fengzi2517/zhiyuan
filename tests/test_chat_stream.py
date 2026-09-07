import json
from fastapi.testclient import TestClient

from app.chat_service import ChatService
from app.query_understanding import QueryUnderstanding
from app.sse import encode_sse


def direct_understanding(*_args):
    return QueryUnderstanding(
        semantic_intent="create", query="问题", needs_kb=False, needs_web=False,
        confidence=0.9, reason="test",
    )


def service(stream):
    return ChatService(
        understand=direct_understanding,
        has_knowledge=lambda _kb: False,
        search_kb=lambda *_args, **_kwargs: [],
        search_web=lambda *_args, **_kwargs: [],
        generate=lambda _prompt: "同步",
        stream_generate=lambda _prompt: stream(),
    )


def test_sse_encoder_preserves_unicode_and_event_name():
    encoded = encode_sse("token", {"text": "你好"})
    assert encoded.startswith("event: token\n")
    assert json.loads(encoded.split("data: ", 1)[1]) == {"text": "你好"}


def test_stream_event_order_contains_tokens_and_terminal_metadata():
    events = list(service(lambda: iter(["你", "好"])).run_stream("问题"))
    names = [event["event"] for event in events]
    assert names == ["status", "route", "token", "token", "sources", "trace", "done"]
    assert events[-1]["data"]["answer"] == "你好"


def test_stream_exception_ends_with_error_without_done():
    def broken():
        yield "开头"
        raise RuntimeError("upstream failed")

    events = list(service(broken).run_stream("问题"))
    assert events[-1]["event"] == "error"
    assert all(event["event"] != "done" for event in events)


def test_stream_route_is_registered():
    from app.main import app
    assert "/chat/stream" in {route.path for route in app.routes}


def test_stream_endpoint_persists_only_after_done(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.chat_service, "run_stream", lambda *_args, **_kwargs: iter([
        {"event": "token", "data": {"text": "答"}},
        {"event": "done", "data": {
            "answer": "答案", "semantic_intent": "create", "route": "direct",
            "sources": [], "trace": [], "elapsed_ms": 5, "status": "complete",
        }},
    ]))
    saved = []
    monkeypatch.setattr(main, "save_message", lambda *args: saved.append(args) or len(saved))

    response = TestClient(main.app).post("/chat/stream", json={"question": "写一段"})

    assert response.status_code == 200
    assert [row[1] for row in saved] == ["user", "assistant"]
    assert '"message_ids":{"user":1,"assistant":2}' in response.text


def test_stream_endpoint_does_not_persist_error(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.chat_service, "run_stream", lambda *_args, **_kwargs: iter([
        {"event": "error", "data": {"message": "failed", "status": "error"}},
    ]))
    saved = []
    monkeypatch.setattr(main, "save_message", lambda *args: saved.append(args))

    response = TestClient(main.app).post("/chat/stream", json={"question": "问题"})

    assert response.status_code == 200
    assert saved == []

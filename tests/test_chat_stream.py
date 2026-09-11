import json
from unittest.mock import Mock

import pytest
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
    assert names[0] == "status"
    assert [name for name in names if name not in ("status", "trace")] == [
        "route", "token", "token", "sources", "done",
    ]
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


@pytest.mark.parametrize("use_memory", [True, False], ids=["memory-enabled", "memory-disabled"])
def test_stream_endpoint_persists_only_after_done(monkeypatch, use_memory):
    from app import main

    old_memory = {"summary": "用户正在写项目介绍。", "facts": "- 使用中文"}
    updated_memory = {
        "summary": "用户正在写项目介绍，已生成一段答案。",
        "facts": "- 使用中文\n- 已完成首段草稿",
    }
    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    get_memory = Mock(return_value=old_memory)
    monkeypatch.setattr(main, "get_memory", get_memory)
    # Stub the external LLM boundary, while running the real background task.
    update_memory = Mock(return_value=updated_memory)
    monkeypatch.setattr(main, "update_memory", update_memory)
    saved_memories = []
    monkeypatch.setattr(main, "get_memory_snapshot", lambda _: {
        "last_message_id": 2, "token": "revision", "memory": old_memory,
    })
    monkeypatch.setattr(main, "save_memory_if_current", lambda *args: saved_memories.append(args) or True)
    monkeypatch.setattr(main.chat_service, "run_stream", lambda *_args, **_kwargs: iter([
        {"event": "token", "data": {"text": "答"}},
        {"event": "done", "data": {
            "answer": "答案", "semantic_intent": "create", "route": "direct",
            "sources": [], "trace": [], "elapsed_ms": 5, "status": "complete",
        }},
    ]))
    saved = []
    def save_exchange(*args, capture_memory=False):
        saved.append(args)
        ids = {"user": 1, "assistant": 2}
        if capture_memory:
            ids["_memory_snapshot"] = {"token": "revision", "memory": old_memory, "last_message_id": 2}
        return ids
    monkeypatch.setattr(main, "save_exchange", save_exchange)

    response = TestClient(main.app).post("/chat/stream", json={
        "question": "写一段", "session_id": "writing-session", "use_memory": use_memory,
    })

    assert response.status_code == 200
    assert saved[0][:3] == ("writing-session", "写一段", "答案")
    assert '"message_ids":{"user":1,"assistant":2}' in response.text
    if use_memory:
        update_memory.assert_called_once_with(old_memory, "写一段", "答案")
        assert saved_memories == [(
            "writing-session", "revision", updated_memory["summary"], updated_memory["facts"],
        )]
    else:
        get_memory.assert_not_called()
        update_memory.assert_not_called()
        assert saved_memories == []


def test_stream_endpoint_does_not_persist_error(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.chat_service, "run_stream", lambda *_args, **_kwargs: iter([
        {"event": "error", "data": {"message": "failed", "status": "error"}},
    ]))
    saved = []
    monkeypatch.setattr(main, "save_exchange", lambda *args: saved.append(args))

    response = TestClient(main.app).post("/chat/stream", json={"question": "问题"})

    assert response.status_code == 200
    assert saved == []

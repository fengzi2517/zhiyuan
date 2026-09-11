from unittest.mock import Mock

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
import anyio
import pytest
from starlette.requests import ClientDisconnect

from app import main


def test_stale_background_task_does_not_call_model(monkeypatch):
    monkeypatch.setattr(main, "get_memory_snapshot", lambda _: {
        "last_message_id": 9, "token": "newer", "memory": None,
    })
    update = Mock()
    monkeypatch.setattr(main, "update_memory", update)
    main._refresh_memory("s", "question", "answer", {"token": "old", "memory": None})
    update.assert_not_called()


def test_memory_update_passes_snapshot_token_to_conditional_save(monkeypatch):
    monkeypatch.setattr(main, "get_memory_snapshot", lambda _: {
        "last_message_id": 4, "token": "revision", "memory": None,
    })
    monkeypatch.setattr(main, "update_memory", lambda *_: {"summary": "summary", "facts": "facts"})
    save = Mock(return_value=False)
    monkeypatch.setattr(main, "save_memory_if_current", save)
    main._refresh_memory("s", "question", "answer", {"token": "revision", "memory": None})
    save.assert_called_once_with("s", "revision", "summary", "facts")


def test_stream_persistence_error_has_no_done_and_closes_iterator(monkeypatch):
    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    closed = []
    def output(*_args, **_kwargs):
        try:
            yield {"event": "done", "data": {
                "answer": "answer", "trace": [], "sources": [], "run_id": "run",
                "answer_mode": "direct", "semantic_intent": "create", "route": "direct",
                "elapsed_ms": 1, "status": "complete", "warnings": [],
            }}
        finally:
            closed.append(True)
    monkeypatch.setattr(main.chat_service, "run_stream", output)
    def fail(*_args, **_kwargs):
        raise RuntimeError("database-password-hidden")
    monkeypatch.setattr(main, "save_exchange", fail)
    response = TestClient(main.app).post("/chat/stream", json={"question": "写一句", "use_memory": False})
    assert "event: error" in response.text
    assert "event: done" not in response.text
    assert "persistence_failed" in response.text
    assert "database-password-hidden" not in response.text
    assert closed == [True]


def test_http_disconnect_closes_underlying_model_iterator(monkeypatch):
    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    closed = []
    def output(*_args, **_kwargs):
        try:
            yield {"event": "token", "data": {"text": "first"}}
            yield {"event": "token", "data": {"text": "second"}}
        finally:
            closed.append(True)
    monkeypatch.setattr(main.chat_service, "run_stream", output)
    response = main.chat_stream(main.ChatReq(question="写一句", use_memory=False), BackgroundTasks())
    async def disconnected():
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("disconnected client")
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        # Assert before the event loop tears down and implicitly closes generators.
        assert closed == [True]
    anyio.run(disconnected)

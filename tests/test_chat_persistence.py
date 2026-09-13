from fastapi import BackgroundTasks

from app import main
from app.chat_service import ChatResult


def test_chat_response_includes_persisted_message_ids(monkeypatch):
    monkeypatch.setattr(main, "get_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.chat_service, "run", lambda *_args, **_kwargs: ChatResult(
        answer="answer", semantic_intent="knowledge", route="kb", sources=[],
        trace=[], elapsed_ms=1,
    ))
    monkeypatch.setattr(main, "save_exchange", lambda *_args, **_kwargs: {"user": 41, "assistant": 42})

    response = main.chat(
        main.ChatReq(question="question", use_memory=False), BackgroundTasks()
    )

    assert response["message_ids"] == {"user": 41, "assistant": 42}


def test_delete_session_removes_messages_and_memory(monkeypatch):
    deleted_models = []

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *_args):
            return self

        def delete(self):
            deleted_models.append(self.model)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def query(self, model):
            return Query(model)

        def commit(self):
            pass

    from app import db
    from app import attachments

    monkeypatch.setattr(db, "Session", FakeSession)
    cancelled = []
    monkeypatch.setattr(attachments, 'cancel_in_session', lambda session, sid: cancelled.append((session, sid)))
    db.delete_session("session")

    assert deleted_models == [db.ChatMessage, db.SessionMemory]
    assert isinstance(cancelled[0][0], FakeSession) and cancelled[0][1] == 'session'


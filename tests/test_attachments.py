import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app import db, auth, jobs, attachments as a


@pytest.fixture
def store(monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'attachments.db'))
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, 'Session', sessionmaker(bind=engine))
    monkeypatch.setattr(jobs, 'UPLOAD_DIR', str(tmp_path / 'uploads'))
    with db.Session.begin() as s:
        s.add_all([auth.User(id=1, username='one', password_hash='unused'),
                   auth.User(id=2, username='two', password_hash='unused')])
    yield
    engine.dispose()


def test_scope_and_cancel_fence(store):
    item = a.enqueue(1, 'chat-a', [('a.txt', b'hello')])[0]
    with pytest.raises(HTTPException):
        a.list_items(2, 'chat-a')
    with db.Session() as s, pytest.raises(HTTPException):
        a.require_items(s, 1, 'chat-b', [item['id']])
    claim = a.claim('worker')
    a.remove(1, 'chat-a', item['id'])
    assert a.complete(claim, 'hello', [], []) is False
    assert a.list_items(1, 'chat-a') == []


def test_batch_atomic_validation(store):
    with pytest.raises(ValueError):
        a.enqueue(1, 'chat-a', [('a.txt', b'hello'), ('bad.exe', b'x')])
    with db.Session() as s:
        assert s.query(a.Attachment).count() == 0


def test_completion_and_session_delete(store):
    from app.chunker import ChunkData
    item = a.enqueue(1, 'chat-a', [('a.txt', b'hello')])[0]
    claim = a.claim('worker')
    assert a.complete(claim, 'hello', [ChunkData('hello', None, None, '', 0, 5)], [[1.0] * 1024])
    assert a.list_items(1, 'chat-a')[0]['status'] == 'ready'
    assert not a.complete(claim, 'hello', [], [])
    db.delete_session('chat-a', user_id=1)
    with pytest.raises(HTTPException):
        a.list_items(1, 'chat-a')

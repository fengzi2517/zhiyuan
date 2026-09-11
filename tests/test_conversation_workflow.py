import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import db


@pytest.fixture
def storage(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    db.Base.metadata.create_all(engine, tables=[db.ChatMessage.__table__, db.SessionMemory.__table__])
    monkeypatch.setattr(db, 'Session', sessionmaker(bind=engine))
    yield engine
    engine.dispose()


def test_exchange_persists_pair_and_assistant_metadata(storage):
    ids = db.save_exchange('s', 'question', 'answer', {'sources': [{'id': 1}], 'status': 'complete'})
    rows = db.get_session_messages('s')
    assert [row['id'] for row in rows] == [ids['user'], ids['assistant']]
    assert [row['role'] for row in rows] == ['user', 'assistant']
    assert rows[0]['sources'] == []
    assert rows[1]['sources'] == [{'id': 1}]


def test_exchange_rolls_back_user_when_assistant_insert_fails(storage):
    def fail_assistant(_mapper, _connection, target):
        if target.role == 'assistant':
            raise RuntimeError('assistant persistence failed')
    event.listen(db.ChatMessage, 'before_insert', fail_assistant)
    try:
        with pytest.raises(RuntimeError, match='assistant persistence failed'):
            db.save_exchange('s', 'question', 'answer')
    finally:
        event.remove(db.ChatMessage, 'before_insert', fail_assistant)
    assert db.get_session_messages('s') == []


def test_snapshot_happy_save_and_empty_session(storage):
    assert db.get_memory_snapshot('s') is None
    ids = db.save_exchange('s', 'question', 'answer')
    snapshot = db.get_memory_snapshot('s')
    assert snapshot['last_message_id'] == ids['assistant']
    assert snapshot['memory'] is None
    assert db.save_memory_if_current('s', snapshot['token'], 'summary', 'facts') is True
    assert db.get_memory('s')['summary'] == 'summary'
    assert db.get_memory_snapshot('s')['memory']['facts'] == 'facts'
    assert db.save_memory_if_current('s', snapshot['token'], 'stale', 'stale') is False


@pytest.mark.parametrize('mutation', ['edit', 'delete', 'exchange', 'message', 'memory'])
def test_stale_snapshot_cannot_replace_memory(storage, mutation):
    ids = db.save_exchange('s', 'question', 'answer')
    db.save_memory('s', 'original', 'facts')
    snapshot = db.get_memory_snapshot('s')
    if mutation == 'edit':
        assert db.update_message(ids['user'], 'corrected')
    elif mutation == 'delete':
        db.delete_session('s')
    elif mutation == 'exchange':
        db.save_exchange('s', 'next', 'reply')
    elif mutation == 'message':
        db.save_message('s', 'user', 'next')
    else:
        db.save_memory('s', 'newer', 'newer facts')
    assert db.save_memory_if_current('s', snapshot['token'], 'stale', 'stale') is False
    memory = db.get_memory('s')
    if mutation in ('edit', 'delete'):
        assert memory is None
    else:
        assert memory['summary'] == ('newer' if mutation == 'memory' else 'original')


def test_assistant_edit_invalidates_memory_and_answer_metadata(storage):
    message_id = db.save_message('s', 'assistant', 'answer', {
        'sources': [{'id': 1}], 'trace': [{'step': 'search'}],
        'route': 'rag', 'semantic_intent': 'lookup', 'elapsed_ms': 123,
    })
    db.save_memory('s', 'old', 'old')
    assert db.update_message(message_id, 'edited answer')
    row = db.get_session_messages('s')[0]
    assert row['content'] == 'edited answer'
    assert row['sources'] == row['trace'] == []
    assert row['route'] == row['semantic_intent'] == ''
    assert row['elapsed_ms'] is None
    assert row['status'] == 'edited'
    assert db.get_memory('s') is None


def test_exchange_captured_snapshot_rejects_edit_before_background_starts(storage):
    saved = db.save_exchange('s', 'original question', 'original answer', capture_memory=True)
    captured = saved['_memory_snapshot']
    assert captured['last_message_id'] == saved['assistant']
    assert captured == db.get_memory_snapshot('s')
    assert db.update_message(saved['user'], 'corrected question')
    assert db.get_memory_snapshot('s')['last_message_id'] == saved['assistant']
    assert db.save_memory_if_current('s', captured['token'], 'outdated summary', 'old facts') is False
    assert db.get_memory('s') is None

from fastapi.testclient import TestClient
import pytest
from app import db, auth, jobs

PASSWORD = 'integration password only'


@pytest.fixture
def browsers(monkeypatch):
    from app.main import app
    with db.Session.begin() as s:
        s.add_all([auth.User(username='alice', password_hash=auth.hash_password(PASSWORD), is_admin=True),
                   auth.User(username='bob', password_hash=auth.hash_password(PASSWORD))])
    alice, bob = TestClient(app), TestClient(app)
    for browser, name in [(alice, 'alice'), (bob, 'bob')]:
        browser.headers['Origin'] = 'http://localhost:5173'
        response = browser.post('/auth/login', json={'username': name, 'password': PASSWORD})
        assert response.status_code == 200
        browser.headers['X-CSRF-Token'] = response.json()['csrf_token']
    yield alice, bob
    alice.close()
    bob.close()


def test_anonymous_and_cross_user_routes(browsers):
    from app.main import app
    alice, bob = browsers
    assert TestClient(app).get('/kbs').status_code == 401
    kb = alice.post('/kbs', json={'name': 'private'}).json()['id']
    uploaded = alice.post(f'/upload?kb_id={kb}', files={'file': ('a.txt', b'private content')})
    assert uploaded.status_code == 202
    doc = uploaded.json()['doc_id']
    claimed = jobs.claim('test')
    assert jobs.complete(claimed, 'private', ['private'], [[1.0] + [0.0] * 1023])
    auth.require_conversation(1, 'alice-chat', claim=True)
    ids = db.save_exchange('alice-chat', 'secret q', 'secret a', user_id=1, allowed_kb_ids=[kb])
    assert bob.get('/kbs').json() == []
    assert bob.get('/documents').json() == []
    assert bob.get('/sessions').json() == []
    for url in [f'/documents/{doc}/content', f'/documents/{doc}/original',
                f'/documents/{doc}/chunks/1/context', f'/documents/{doc}/job',
                f'/kbs/{kb}/vectors', '/sessions/alice-chat/messages', '/sessions/alice-chat/memory']:
        assert bob.get(url).status_code == 404, url
    assert bob.post(f'/documents/{doc}/retry').status_code == 404
    assert bob.put(f'/messages/{ids["assistant"]}', json={'content': 'tamper'}).status_code == 404
    for route in ['/chat', '/chat/stream']:
        assert bob.post(route, json={'question': 'secret?', 'session_id': 'alice-chat'}).status_code == 404
    assert alice.get(f'/documents/{doc}/original').content == b'private content'
    assert alice.get('/documents').json()[0]['job']['status'] == 'succeeded'


def test_scoped_sql_retrieval_never_returns_other_kb(browsers, monkeypatch):
    from app import embeddings
    alice, bob = browsers
    ids = []
    for browser, name in [(alice, 'mine'), (bob, 'other')]:
        kb = browser.post('/kbs', json={'name': name}).json()['id']
        ids.append(kb)
        jobs.enqueue(kb, 'a.txt', name.encode())
        claimed = jobs.claim('test')
        jobs.complete(claimed, name, [name], [[1.0] + [0.0] * 1023])
    monkeypatch.setattr(embeddings, 'embed_texts', lambda *a, **kw: [[1.0] + [0.0] * 1023])
    assert [r['content'] for r in db.search_chunk_sources('query', allowed_kb_ids=[ids[0]])] == ['mine']
    assert db.search_chunk_sources('query', allowed_kb_ids=[]) == []
    assert db.search_chunk_sources('query', kb_id=ids[1], allowed_kb_ids=[ids[0]]) == []


def test_reader_cannot_mutate_and_logout_revokes(browsers):
    alice, bob = browsers
    kb = alice.post('/kbs', json={'name': 'shared'}).json()['id']
    assert alice.put(f'/kbs/{kb}/members', json={'user_id': 2, 'role': 'reader'}).status_code == 200
    assert bob.get('/kbs').json()[0]['role'] == 'reader'
    assert bob.post(f'/upload?kb_id={kb}', files={'file': ('a.txt', b'forbidden')}).status_code == 404
    assert bob.delete(f'/kbs/{kb}').status_code == 404
    assert bob.post('/auth/logout').status_code == 200
    assert bob.get('/kbs').status_code == 401


def test_retry_endpoint_uses_persisted_source(browsers):
    alice, _ = browsers
    kb = alice.post('/kbs', json={'name': 'retry'}).json()['id']
    doc = alice.post(f'/upload?kb_id={kb}', files={'file': ('a.txt', b'original')}).json()['doc_id']
    claimed = jobs.claim('test')
    jobs.fail(claimed, permanent=True)
    assert alice.post(f'/documents/{doc}/retry').status_code == 202
    assert alice.post(f'/documents/{doc}/retry').status_code == 409
    new = jobs.claim('restarted')
    assert jobs.Path(new['storage_path']).read_bytes() == b'original'


def test_deleting_one_kb_does_not_break_unscoped_chat(browsers):
    alice, _ = browsers
    removed = alice.post('/kbs', json={'name': 'removed'}).json()['id']
    kept = alice.post('/kbs', json={'name': 'kept'}).json()['id']
    assert alice.delete(f'/kbs/{removed}').status_code == 200
    assert auth.allowed_kb_ids(1) == [kept]
    auth.require_conversation(1, 'still-works', claim=True)
    assert db.save_exchange('still-works', 'q', 'a', user_id=1,
                            allowed_kb_ids=auth.allowed_kb_ids(1))['assistant'] > 0


def test_authenticated_sse_persists_and_rejects_logout_during_generation(browsers, monkeypatch):
    from app import main
    from app.chat_service import ChatService
    alice, _ = browsers
    from app.query_understanding import QueryUnderstanding
    def understand(question):
        return QueryUnderstanding(semantic_intent='chitchat', query=question, needs_kb=False, needs_web=False, confidence=1.0, reason='test')
    service = ChatService(understand=understand, has_knowledge=lambda _: False,
        search_kb=lambda *a: [], search_web=lambda *a: [], generate=lambda _: 'hello',
        stream_generate=lambda _: iter(['hello']))
    monkeypatch.setattr(main, 'chat_service', service)
    response = alice.post('/chat/stream', json={'question': '你好', 'session_id': 'sse-ok', 'use_memory': False})
    assert 'event: done' in response.text, response.text
    assert len(db.get_session_messages('sse-ok')) == 2
    def revoke_then_generate(_):
        with db.Session.begin() as s:
            auth.revoke_user(s, 1)
        yield 'hello'
    service._stream_generate = revoke_then_generate
    response = alice.post('/chat/stream', json={'question': '你好', 'session_id': 'sse-revoked', 'use_memory': False})
    assert 'event: error' in response.text and 'event: done' not in response.text
    assert db.get_session_messages('sse-revoked') == []


def test_concurrent_admin_disables_preserve_one_active_admin(browsers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    alice, bob = browsers
    with db.Session.begin() as s:
        s.get(auth.User, 2).is_admin = True
    barrier = Barrier(2)
    def disable(browser, target):
        barrier.wait(timeout=5)
        return browser.post(f'/admin/users/{target}/disable').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(disable, alice, 2), pool.submit(disable, bob, 1)]
        statuses = [future.result(timeout=10) for future in futures]
    assert statuses.count(200) == 1
    with db.Session() as s:
        assert s.query(auth.User).filter_by(is_admin=True, disabled=False).count() == 1

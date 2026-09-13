"""Real PostgreSQL and authenticated HTTP; fake only external model computation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
import json
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app import attachments as a, db, auth, jobs
from app.chunker import ChunkData
from integration_tests.test_http_security import browsers

VECTOR = [1.0] + [0.0] * 1023


def uploaded(browser, sid='private', name='a.txt', data=b'attachment evidence'):
    response = browser.post(f'/sessions/{sid}/attachments', files=[('files', (name, data))])
    assert response.status_code == 202, response.text
    return response.json()[0]


def finish(item, content='attachment evidence', image_path=''):
    claim = a.claim('test')
    assert claim['attachment_id'] == item['id']
    chunks = [ChunkData(content, 1, 1, '', 0, len(content))] if content else []
    assert a.complete(claim, content, chunks, [VECTOR] if chunks else [], image_path)
    return claim


def test_http_all_attachment_scopes_and_csrf(browsers):
    alice, bob = browsers
    item = uploaded(alice)
    ident = item['id']
    root = f'/sessions/private/attachments/{ident}'
    for suffix in ('/original', '/content'):
        assert bob.get(root + suffix).status_code == 404
        assert alice.get(root.replace('/private/', '/other/') + suffix).status_code == 404
    assert bob.get('/sessions/private/attachments').status_code == 404
    for route, body in [('/retry', None), ('/save-to-kb', {'kb_id': 1})]:
        assert bob.post(root + route, json=body).status_code == 404
    assert bob.delete(root).status_code == 404
    assert bob.post('/sessions/private/attachments', files={'files': ('x.txt', b'x')}).status_code == 404
    for route in ('/chat', '/chat/stream'):
        assert bob.post(route, json={'question': 'x', 'session_id': 'private', 'attachment_ids': [ident]}).status_code == 404
    token = alice.headers.pop('X-CSRF-Token')
    assert alice.delete(root).status_code == 403
    alice.headers['X-CSRF-Token'] = token
    assert alice.get(root + '/original').content == b'attachment evidence'


def test_claim_race_expiry_and_delete_fence(browsers):
    alice, _ = browsers
    item = uploaded(alice)
    barrier = Barrier(2)
    def take(name):
        barrier.wait(timeout=10)
        return a.claim(name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(take, ['one', 'two']))
    assert sum(r is not None for r in results) == 1
    old = next(r for r in results if r)
    with db.Session.begin() as s:
        s.get(a.AttachmentJob, old['id']).lease_until = auth.now() - timedelta(seconds=1)
    new = a.claim('recovered')
    assert new['token'] != old['token']
    assert not a.heartbeat(old['id'], old['token'])
    assert not a.fail(old, permanent=True)
    assert not a.complete(old, '', [], [])
    assert alice.delete('/sessions/private').status_code == 200
    assert not a.complete(new, '', [], [])
    assert not a.heartbeat(new['id'], new['token'])
    assert alice.get(f"/sessions/private/attachments/{item['id']}/original").status_code == 404


def test_skip_locked_and_retry_from_original(browsers):
    alice, _ = browsers
    first = uploaded(alice)
    second = uploaded(alice, 'second')
    with db.Session.begin() as s:
        s.execute(select(a.AttachmentJob).where(a.AttachmentJob.attachment_id == first['id']).with_for_update()).scalar_one()
        claim = a.claim('next')
        assert claim['attachment_id'] == second['id']
    assert a.fail(claim, permanent=True, stage='parse')
    response = alice.post(f"/sessions/second/attachments/{second['id']}/retry")
    assert response.status_code == 202
    with db.Session() as s:
        assert a.path_for(s.get(a.Attachment, second['id'])).read_bytes() == b'attachment evidence'


def test_promotion_is_atomic_idempotent_and_independent(browsers):
    alice, bob = browsers
    item = uploaded(alice)
    finish(item)
    kb = alice.post('/kbs', json={'name': 'promotion'}).json()['id']
    barrier = Barrier(2)
    def promote(_):
        barrier.wait(timeout=10)
        return a.promote(1, 'private', item['id'], kb)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(promote, range(2)))
    assert results[0]['doc_id'] == results[1]['doc_id']
    with db.Session() as s:
        assert s.query(db.Document).count() == s.query(jobs.IngestionJob).count() == 1
    bob_item = uploaded(bob, 'bob')
    finish(bob_item)
    alice.put(f'/kbs/{kb}/members', json={'user_id': 2, 'role': 'reader'})
    assert bob.post(f"/sessions/bob/attachments/{bob_item['id']}/save-to-kb", json={'kb_id': kb}).status_code == 404
    alice.delete('/sessions/private')
    assert alice.get(f"/documents/{results[0]['doc_id']}/original").content == b'attachment evidence'


@pytest.fixture
def generated(monkeypatch):
    import app.main as main
    from app.query_understanding import QueryUnderstanding
    monkeypatch.setattr(main.chat_service, '_understand', lambda q, h: QueryUnderstanding(
        semantic_intent='knowledge', query=q, reason='test', confidence=1))
    payloads = []
    def generate(messages, *, selection):
        payloads.append((messages, selection.public_metadata()))
        return '依据附件回答 [1]'
    monkeypatch.setattr(main, 'llm_chat', generate)
    monkeypatch.setattr(main, 'llm_chat_stream', lambda messages, *, selection: iter([generate(messages, selection=selection)]))
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([dict(
        id='vision', name='Test Vision', model='test-vision', vision=True,
        fast_options={'reasoning_effort': 'none'}, deep_options={'reasoning_effort': 'high'})]))
    return payloads


@pytest.mark.parametrize('stream', [False, True])
def test_attachment_only_grounding_and_metadata(browsers, generated, stream):
    alice, _ = browsers
    item = uploaded(alice)
    finish(item)
    response = alice.post('/chat/stream' if stream else '/chat', json=dict(
        question='', session_id='private', attachment_ids=[item['id']], model_id='vision',
        thinking_mode='deep', use_memory=False, web_enabled=False))
    assert response.status_code == 200, response.text
    if stream:
        assert 'event: done' in response.text, response.text
    else:
        assert response.json()['answer_mode'] == 'grounded'
        assert response.json()['sources'][0]['attachment_id'] == item['id']
    assert 'attachment evidence' in generated[0][0][1]['content']
    messages = alice.get('/sessions/private/messages').json()
    assert messages[0]['attachments'][0]['id'] == item['id']
    assert messages[1]['model_options']['thinking_mode'] == 'deep'
    with db.Session() as s:
        assert s.get(a.Attachment, item['id']).used


def test_real_image_worker_native_vs_ocr_payload(browsers, generated, monkeypatch):
    from PIL import Image
    from app import embeddings, worker, parser
    alice, _ = browsers
    data = BytesIO()
    Image.new('RGB', (40, 40), 'red').save(data, format='PNG')
    item = uploaded(alice, name='red.png', data=data.getvalue())
    monkeypatch.setattr(parser, 'parse_file_units', lambda *args: [parser.ParsedUnit('OCR image text')])
    monkeypatch.setattr(embeddings, 'embed_texts', lambda texts, **kwargs: [VECTOR for _ in texts])
    assert worker.run_one('test', task_type='attachment')
    for vision in (True, False):
        response = alice.post('/chat', json=dict(question='附件是什么？', session_id='private',
            attachment_ids=[item['id']], model_id='vision', vision_enabled=vision, use_memory=False, web_enabled=False))
        assert response.status_code == 200, response.text
        content = generated[-1][0][1]['content']
        if vision:
            assert any(c.get('type') == 'image_url' for c in content)
            assert content[-1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        else:
            assert isinstance(content, str) and 'OCR image text' in content


def test_generation_delete_prevents_persistence(browsers, generated, monkeypatch):
    import app.main as main
    alice, _ = browsers
    item = uploaded(alice)
    finish(item)
    def remove_during_generation(messages, *, selection):
        db.delete_session('private', user_id=1)
        return 'obsolete [1]'
    monkeypatch.setattr(main, 'llm_chat', remove_during_generation)
    response = alice.post('/chat', json=dict(question='问题', session_id='private', attachment_ids=[item['id']],
        use_memory=False, web_enabled=False))
    assert response.status_code == 503
    assert db.get_session_messages('private') == []


def test_long_qa_sql_scope(browsers, generated, monkeypatch):
    from app import embeddings
    alice, bob = browsers
    mine = uploaded(alice)
    finish(mine, '我的资料' * 9000)
    other = uploaded(bob, 'other')
    finish(other, 'SECRET OTHER USER')
    monkeypatch.setattr(embeddings, 'embed_texts', lambda *args, **kw: [VECTOR])
    # Use small, realistic chunks while keeping long original text.
    with db.Session.begin() as s:
        s.query(a.AttachmentChunk).filter_by(attachment_id=mine['id']).update({'content': '我的检索片段'})
    result = alice.post('/chat', json=dict(question='具体内容？', session_id='private', attachment_ids=[mine['id']],
        use_memory=False, web_enabled=False))
    assert result.status_code == 200, result.text
    prompt = generated[-1][0][1]['content']
    assert '我的检索片段' in prompt and 'SECRET OTHER USER' not in prompt


def test_orphan_cleanup_retains_sent_and_promoted(browsers):
    from app.operations import cleanup
    alice, _ = browsers
    orphan = uploaded(alice, 'orphan')
    used = uploaded(alice, 'used')
    with db.Session.begin() as s:
        for item in s.query(a.Attachment):
            item.created_at = auth.now() - timedelta(days=2)
        s.get(a.Attachment, used['id']).used = True
    cleanup(apply=True)
    with db.Session() as s:
        assert s.get(a.Attachment, orphan['id']).deleted
        assert not s.get(a.Attachment, used['id']).deleted


def test_uploaded_session_recoverable_before_first_message(browsers):
    alice, bob = browsers
    uploaded(alice, 'unfinished', name='pending.pdf', data=b'pending parse')
    rows = alice.get('/sessions').json()
    row = next(r for r in rows if r['session_id'] == 'unfinished')
    assert row['message_count'] == 0 and 'pending.pdf' in row['preview']
    assert bob.get('/sessions').json() == []
    assert alice.get('/sessions/unfinished/messages').json() == []
    assert len(alice.get('/sessions/unfinished/attachments').json()) == 1
    alice.delete('/sessions/unfinished')
    assert alice.get('/sessions').json() == []

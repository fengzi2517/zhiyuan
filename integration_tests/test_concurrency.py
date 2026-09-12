from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import pytest
from sqlalchemy import text
from app import db, jobs


def test_exchange_serializes_pairs_on_independent_connections():
    barrier = Barrier(6)
    def save(index):
        barrier.wait(timeout=10)
        return db.save_exchange('shared', f'q{index}', f'a{index}')
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(save, range(6)))
    messages = db.get_session_messages('shared')
    assert len(results) == 6 and len(messages) == 12
    for left, right in zip(messages[::2], messages[1::2]):
        assert left['role'] == 'user' and right['role'] == 'assistant'
        assert left['content'][1:] == right['content'][1:]


def test_unrelated_session_not_blocked():
    with db.Session() as s, ThreadPoolExecutor(max_workers=1) as pool:
        db._lock_session(s, 'held')
        result = pool.submit(db.save_exchange, 'other', 'q', 'a').result(timeout=5)
        assert result['assistant'] > result['user']


def test_exchange_failure_rolls_back_user(monkeypatch):
    original = db._new_message
    def broken(sid, role, content, metadata=None):
        if role == 'assistant':
            raise RuntimeError('injected failure')
        return original(sid, role, content, metadata)
    monkeypatch.setattr(db, '_new_message', broken)
    with pytest.raises(RuntimeError):
        db.save_exchange('failed', 'q', 'a')
    assert db.get_session_messages('failed') == []


def test_stale_memory_cannot_overwrite_or_resurrect():
    db.save_exchange('memory', 'q', 'a')
    snap = db.get_memory_snapshot('memory')
    db.save_exchange('memory', 'new q', 'new a')
    assert not db.save_memory_if_current('memory', snap['token'], 'stale', '')
    snap = db.get_memory_snapshot('memory')
    db.delete_session('memory')
    assert not db.save_memory_if_current('memory', snap['token'], 'resurrect', '')


def test_two_workers_only_one_claim(kb):
    jobs.enqueue(kb, 'a.txt', b'content')
    barrier = Barrier(2)
    def claim(name):
        barrier.wait(timeout=10)
        return jobs.claim(name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ['one', 'two']))
    assert sum(item is not None for item in results) == 1


def test_skip_locked_allows_next_job(kb):
    first = jobs.enqueue(kb, 'a.txt', b'first')
    second = jobs.enqueue(kb, 'b.txt', b'second')
    with db.Session() as s, ThreadPoolExecutor(max_workers=1) as pool:
        s.query(jobs.IngestionJob).filter_by(id=first['job_id']).with_for_update().one()
        claimed = pool.submit(jobs.claim, 'worker').result(timeout=5)
        assert claimed['id'] == second['job_id']


def test_expired_lease_recovery_fences_old_worker_and_is_idempotent(kb):
    created = jobs.enqueue(kb, 'a.txt', b'content')
    old = jobs.claim('crashed-worker')
    with db.Session.begin() as s:
        s.execute(text("UPDATE ingestion_jobs SET lease_until=now()-interval '1 second' WHERE id=:id"),
                  {'id': created['job_id']})
    new = jobs.claim('replacement')
    assert new['attempt'] == 2 and new['token'] != old['token']
    vector = [[1.0] + [0.0] * 1023]
    assert not jobs.heartbeat(old['id'], old['token'])
    assert not jobs.complete(old, 'stale', ['stale'], vector)
    assert jobs.complete(new, 'new', ['new'], vector)
    assert not jobs.complete(new, 'duplicate', ['new'], vector)
    with db.Session() as s:
        assert s.query(db.Chunk).count() == 1
        assert s.get(db.Document, created['doc_id']).content == 'new'
        assert s.get(jobs.IngestionJob, created['job_id']).status == 'succeeded'


def test_failure_retry_limits_and_deleted_kb(kb):
    created = jobs.enqueue(kb, 'a.txt', b'content')
    claimed = jobs.claim('worker')
    assert jobs.fail(claimed, permanent=True)
    assert jobs.retry(created['job_id'])
    claimed = jobs.claim('worker')
    jobs.delete_knowledge_base(kb)
    assert not jobs.complete(claimed, 'gone', ['gone'], [[0.0] * 1024])
    assert not jobs.retry(created['job_id'])
    with db.Session() as s:
        assert s.query(db.Document).count() == 0
        assert s.query(db.Chunk).count() == 0


def test_parallel_authorized_uploads_do_not_deadlock(kb):
    from app import auth
    with db.Session.begin() as s:
        user = auth.User(username='uploader', password_hash='unused')
        s.add(user); s.flush()
        uid = user.id
        s.add(auth.KBMembership(kb_id=kb, user_id=uid, role='editor'))
    barrier = Barrier(2)
    def upload(index):
        barrier.wait(timeout=5)
        return jobs.enqueue(kb, f'{index}.txt', b'content', user_id=uid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(upload, i) for i in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0]['doc_id'] != results[1]['doc_id']


def test_retry_exhaustion_and_expired_owner_cannot_fail_new_claim(kb):
    created = jobs.enqueue(kb, 'a.txt', b'content')
    old = jobs.claim('old')
    with db.Session.begin() as s:
        s.execute(text("UPDATE ingestion_jobs SET lease_until=now()-interval '1 second' WHERE id=:id"), {'id': created['job_id']})
    new = jobs.claim('new')
    assert not jobs.fail(old, permanent=True)
    with db.Session.begin() as s:
        s.execute(text("UPDATE ingestion_jobs SET attempts=max_attempts, lease_until=now()-interval '1 second' WHERE id=:id"), {'id': created['job_id']})
    assert jobs.claim('after-limit') is None
    with db.Session() as s:
        assert s.get(jobs.IngestionJob, created['job_id']).status == 'failed'

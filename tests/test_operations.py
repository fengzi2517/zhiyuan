import os
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest
from app import db, jobs, operations, worker


@pytest.fixture
def storage(monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'operations.db'))
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, 'Session', sessionmaker(bind=engine))
    monkeypatch.setattr(jobs, 'UPLOAD_DIR', str(tmp_path / 'uploads'))
    yield db.create_kb('maintenance')['id']
    engine.dispose()


def test_cleanup_keeps_referenced_original_and_dry_run_is_read_only(storage):
    created = jobs.enqueue(storage, 'a.txt', b'keep')
    with db.Session() as s:
        original = jobs.Path(s.get(db.Document, created['doc_id']).storage_path)
    orphan = original.parent / 'orphan.tmp'
    orphan.write_bytes(b'orphan')
    old = time.time() - 48 * 3600
    os.utime(original, (old, old)); os.utime(orphan, (old, old))
    assert operations.cleanup() == [str(orphan)]
    assert orphan.exists()
    operations.cleanup(apply=True)
    assert not orphan.exists() and original.read_bytes() == b'keep'


def test_resume_legacy_only_with_existing_original(storage):
    directory = jobs.Path(jobs.UPLOAD_DIR) / '1'
    directory.mkdir(parents=True)
    source = directory / 'source.txt'
    source.write_text('legacy')
    with db.Session.begin() as s:
        s.add(db.Document(kb_id=storage, filename='a.txt', storage_path=str(source), status='pending'))
        s.add(db.Document(kb_id=storage, filename='lost.txt', status='pending'))
    report = operations.resume_legacy()
    assert [r['action'] for r in report] == ['queue', 'reupload_required']
    with db.Session() as s:
        assert s.query(jobs.IngestionJob).count() == 0
    operations.resume_legacy(apply=True)
    operations.resume_legacy(apply=True)
    with db.Session() as s:
        assert s.query(jobs.IngestionJob).count() == 1


def test_worker_error_logs_do_not_include_document_body(monkeypatch, caplog):
    monkeypatch.setattr(jobs, 'claim', lambda _: {'id': 7, 'token': 'opaque'})
    monkeypatch.setattr(jobs, 'fail', lambda *a, **k: True)
    def fail(_):
        raise RuntimeError('PRIVATE DOCUMENT BODY')
    monkeypatch.setattr(worker, 'process', fail)
    assert worker.run_one('worker')
    assert 'RuntimeError' in caplog.text
    assert 'PRIVATE DOCUMENT BODY' not in caplog.text

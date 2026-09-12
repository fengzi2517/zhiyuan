import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import db, jobs


@pytest.fixture
def database(monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'jobs.db'))
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, 'Session', sessionmaker(bind=engine))
    monkeypatch.setattr(jobs, 'UPLOAD_DIR', str(tmp_path / 'uploads'))
    with db.Session.begin() as s:
        kb = db.KnowledgeBase(name='test')
        s.add(kb)
        s.flush()
        yield_id = kb.id
    yield yield_id
    engine.dispose()


def test_enqueue_persists_original_and_job(database):
    result = jobs.enqueue(database, 'a.txt', b'hello')
    with db.Session() as s:
        doc = s.get(db.Document, result['doc_id'])
        assert jobs.Path(doc.storage_path).read_bytes() == b'hello'
        assert s.get(jobs.IngestionJob, result['job_id']).status == 'queued'


def test_reject_unsupported_upload(database):
    with pytest.raises(ValueError):
        jobs.enqueue(database, 'a.exe', b'bad')
    with db.Session() as s:
        assert s.query(db.Document).count() == 0


def test_validate_does_not_silently_truncate_vectors():
    with pytest.raises(ValueError):
        jobs.validate_vectors(['one', 'two'], [[0.0] * 1024])
    with pytest.raises(ValueError):
        jobs.validate_vectors(['one'], [[float('nan')] * 1024])


def test_retry_requires_failed_terminal_job(database):
    result = jobs.enqueue(database, 'a.txt', b'hello')
    assert jobs.retry(result['job_id']) is False
    with db.Session.begin() as s:
        s.get(jobs.IngestionJob, result['job_id']).status = 'failed'
    assert jobs.retry(result['job_id']) is True
    assert jobs.retry(result['job_id']) is False

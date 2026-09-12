"""Opt-in real PostgreSQL tests, isolated from tests/ network prohibition."""
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = os.getenv('TEST_DATABASE_URL', '')
if url:
    parsed = make_url(url)
    if parsed.get_backend_name() != 'postgresql' or not (parsed.database or '').startswith('rag_test_'):
        raise RuntimeError('Integration suite refuses non rag_test_ PostgreSQL databases')
os.environ.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL=url or 'sqlite:///:memory:',
                  LLM_API_KEY='test-only', LLM_BASE_URL='https://llm.invalid/v1',
                  TAVILY_API_KEY='test-only', HF_HUB_OFFLINE='1')


@pytest.fixture(scope='session', autouse=True)
def migrated():
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a dedicated rag_test_ database')
    from app.migrate import migrate
    migrate()


@pytest.fixture(autouse=True)
def isolated_database(migrated, monkeypatch, tmp_path):
    from app import db, jobs
    # Static metadata table names, exclusively in guarded test database.
    with db.engine.begin() as conn:
        names = ', '.join('"' + table.name + '"' for table in db.Base.metadata.sorted_tables)
        conn.execute(text('TRUNCATE TABLE ' + names + ' RESTART IDENTITY CASCADE'))
    monkeypatch.setattr(jobs, 'UPLOAD_DIR', str(tmp_path / 'uploads'))
    yield


@pytest.fixture
def kb():
    from app import db
    return db.create_kb('integration')['id']

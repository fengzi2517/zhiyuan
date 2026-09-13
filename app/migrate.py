"""Explicit, serialized, additive migrations. Run before starting API/worker."""
from sqlalchemy import text
from . import db

VERSION = 2
LOCK_KEY = 724619330123


def migrate():
    from . import auth, jobs, attachments  # register all metadata before create_all
    if db.engine.dialect.name != 'postgresql':
        raise RuntimeError('部署迁移需要 PostgreSQL')
    with db.engine.connect() as lock:
        lock.execute(text('SELECT pg_advisory_lock(:key)'), {'key': LOCK_KEY})
        lock.commit()
        try:
            db.init_db()
            with db.engine.begin() as conn:
                conn.execute(text('CREATE TABLE IF NOT EXISTS schema_versions '
                                  '(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())'))
                conn.execute(text('INSERT INTO schema_versions(version) VALUES (:version) ON CONFLICT DO NOTHING'),
                             {'version': VERSION})
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_KEY})
            lock.commit()


def require_schema():
    try:
        with db.engine.connect() as conn:
            version = conn.execute(text('SELECT max(version) FROM schema_versions')).scalar()
            if version != VERSION:
                raise RuntimeError('数据库版本不匹配')
    except Exception as exc:
        raise RuntimeError('请先执行 python -m app.migrate，再启动 Web/Worker') from exc


if __name__ == '__main__':
    migrate()
    print(f'Database schema ready: {VERSION}')

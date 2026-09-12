"""Run with python -m app.worker; jobs survive process termination."""
import logging
import os
import signal
import socket
import threading
import uuid
import time
import traceback
from pathlib import Path
from . import jobs

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    def __init__(self, stage, cause):
        super().__init__(f'{stage}: {type(cause).__name__}')
        self.stage, self.cause = stage, cause


def _stage(claimed, name, operation):
    started = time.perf_counter()
    logger.info('job_id=%s stage=%s status=started', claimed['id'], name)
    try:
        result = operation()
    except Exception as exc:
        raise IngestionError(name, exc) from exc
    logger.info('job_id=%s stage=%s status=complete elapsed_ms=%s',
                claimed['id'], name, round((time.perf_counter()-started)*1000))
    return result


def process(claimed):
    from .parser import parse_file_units
    from .chunker import chunk_units
    from .embeddings import embed_texts
    path = Path(claimed['storage_path']).resolve()
    if path.parent != (Path(jobs.UPLOAD_DIR) / str(claimed['doc_id'])).resolve():
        raise ValueError('Invalid source location')
    data = _stage(claimed, 'read', path.read_bytes)
    units = _stage(claimed, 'parse', lambda: parse_file_units(claimed['filename'], data))
    def split():
        chunks = chunk_units(units)
        if not chunks:
            raise ValueError('No usable text')
        return chunks
    chunks = _stage(claimed, 'chunk', split)
    def progress(done, total):
        logger.info('job_id=%s stage=embedding progress=%s/%s', claimed['id'], done, total)
    vectors = _stage(claimed, 'embedding', lambda: embed_texts(
        [chunk.content for chunk in chunks], on_progress=progress))
    return _stage(claimed, 'commit', lambda: jobs.complete(
        claimed, '\n'.join(unit.text for unit in units), chunks, vectors))


def run_one(worker_id):
    claimed = jobs.claim(worker_id)
    if claimed is None:
        return False
    stop = threading.Event()

    def renew():
        while not stop.wait(jobs.LEASE_SECONDS / 3):
            try:
                if not jobs.heartbeat(claimed['id'], claimed['token']):
                    return
            except Exception:
                logger.exception('job_id=%s heartbeat failed', claimed['id'])
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        process(claimed)
    except Exception as exc:
        stage = exc.stage if isinstance(exc, IngestionError) else 'unknown'
        cause = exc.cause if isinstance(exc, IngestionError) else exc
        frames = ' > '.join(f'{Path(f.filename).name}:{f.name}:{f.lineno}'
                            for f in traceback.extract_tb(cause.__traceback__)[-6:])
        logger.error('job_id=%s worker_id=%s stage=%s error_type=%s frames=%s',
                     claimed['id'], worker_id, stage, type(cause).__name__, frames)
        permanent = stage in ('read', 'parse', 'chunk') and isinstance(cause, (ValueError, FileNotFoundError))
        jobs.fail(claimed, permanent=permanent, error_type=type(cause).__name__, stage=stage)
    finally:
        stop.set()
        thread.join(timeout=5)
    return True


def main():
    from .migrate import require_schema
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    require_schema()
    worker_id = os.getenv('WORKER_ID', f'{socket.gethostname()}-{uuid.uuid4().hex[:8]}')
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    while not stop.is_set():
        try:
            if run_one(worker_id):
                continue
        except Exception:
            logger.exception('worker_id=%s poll failed', worker_id)
        stop.wait(max(0.2, float(os.getenv('JOB_POLL_SECONDS', '2'))))


if __name__ == '__main__':
    main()

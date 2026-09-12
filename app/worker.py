"""Run with python -m app.worker; jobs survive process termination."""
import logging
import os
import signal
import socket
import threading
import uuid
from pathlib import Path
from . import jobs

logger = logging.getLogger(__name__)


def process(claimed):
    from .parser import parse_file_units
    from .chunker import chunk_units
    from .embeddings import embed_texts
    path = Path(claimed['storage_path']).resolve()
    if path.parent != (Path(jobs.UPLOAD_DIR) / str(claimed['doc_id'])).resolve():
        raise ValueError('Invalid source location')
    units = parse_file_units(claimed['filename'], path.read_bytes())
    chunks = chunk_units(units)
    if not chunks:
        raise ValueError('No usable text')
    vectors = embed_texts([chunk.content for chunk in chunks])
    return jobs.complete(claimed, '\n'.join(unit.text for unit in units), chunks, vectors)


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
        logger.error('job_id=%s worker_id=%s processing failed error_type=%s',
                     claimed['id'], worker_id, type(exc).__name__)
        jobs.fail(claimed, permanent=isinstance(exc, (ValueError, FileNotFoundError)),
                  error_type=type(exc).__name__)
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

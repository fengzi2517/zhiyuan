import os
import pytest
from app import db, jobs, worker


@pytest.mark.skipif(os.getenv('RUN_MODEL_SMOKE') != '1', reason='Opt-in real local embedding smoke')
def test_real_embedding_worker_and_retrieval(kb):
    document = jobs.enqueue(kb, 'smoke.txt', '知源恢复测试：入库任务通过租约续期和领取令牌防止旧 Worker 覆盖结果。'.encode('utf-8'))
    assert worker.run_one('real-model-smoke')
    with db.Session() as s:
        assert s.get(db.Document, document['doc_id']).status == 'done'
        assert s.query(db.Chunk).filter_by(doc_id=document['doc_id']).count() > 0
    matches = db.search_chunk_sources('如何防止旧 Worker 覆盖结果？', allowed_kb_ids=[kb])
    assert matches and matches[0]['document_id'] == document['doc_id']

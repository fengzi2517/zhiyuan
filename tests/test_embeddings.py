from app import embeddings


def test_rerank_sources_marks_vector_fallback(monkeypatch):
    monkeypatch.setattr(embeddings, "rerank", lambda *_args: None)

    rows = [{"chunk_id": 1, "content": "内容", "score": 0.25}]

    assert embeddings.rerank_sources("问题", rows)[0]["_rerank_applied"] is False

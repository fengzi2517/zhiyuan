from app import graph


def test_web_intent_respects_disabled_web_search():
    assert graph._after_understand({"intent": "web", "web_enabled": False}) == "generate"


def test_web_intent_uses_search_when_enabled():
    assert graph._after_understand({"intent": "web", "web_enabled": True}) == "web_search"


def test_rerank_fallback_with_empty_top_k_advances_retry(monkeypatch):
    monkeypatch.setattr(graph, "rerank", lambda query, docs: None)
    state = {
        "query": "q",
        "candidates": [("doc", 0.8)],
        "top_k": 0,
        "retries": 0,
        "trace": [],
    }
    result = graph.rerank_node(state)
    assert result["docs"] == []
    assert result["retries"] == 1


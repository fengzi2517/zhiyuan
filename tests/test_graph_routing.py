from app import graph


def test_web_intent_respects_disabled_web_search():
    assert graph._after_understand({"intent": "web", "web_enabled": False}) == "generate"


def test_web_intent_uses_search_when_enabled():
    assert graph._after_understand({"intent": "web", "web_enabled": True}) == "web_search"


def test_compiled_graph_generates_without_web_when_disabled(monkeypatch):
    monkeypatch.setattr(
        graph,
        "understand",
        lambda *_args: {"intent": "web", "query": "latest", "reason": "time-sensitive"},
    )
    monkeypatch.setattr(graph, "chat", lambda *_args: "offline answer")
    monkeypatch.setattr(
        graph,
        "web_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("web called")),
    )
    state = {
        "question": "latest",
        "history": [],
        "memory": None,
        "kb_id": None,
        "top_k": 4,
        "web_enabled": False,
        "sim_threshold": 0.4,
        "intent": "kb",
        "query": "latest",
        "candidates": [],
        "docs": [],
        "web_results": [],
        "retries": 0,
        "answer": "",
        "trace": [],
    }

    result = graph.rag_graph.invoke(state)

    assert result["answer"] == "offline answer"
    assert all(step["stage"] != "web_search" for step in result["trace"])


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

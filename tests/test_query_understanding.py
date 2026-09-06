import pytest

from app.query_understanding import (
    QueryUnderstanding,
    detect_explicit_intent,
    validate_or_fallback,
)


@pytest.mark.parametrize(
    "question,intent",
    [
        ("你好", "chitchat"),
        ("帮我润色这段话", "create"),
        ("解释一下向量数据库", "knowledge"),
        ("今天人民币汇率是多少", "current"),
        ("结合公司制度和最新法规给建议", "mixed"),
    ],
)
def test_deterministic_signals(question, intent):
    assert detect_explicit_intent(question).semantic_intent == intent


def test_invalid_structured_result_falls_back_without_scraping_json():
    result = validate_or_fallback(
        "原问题",
        {"semantic_intent": "future", "query": "", "confidence": 3},
    )

    assert result == QueryUnderstanding(
        semantic_intent="knowledge",
        query="原问题",
        needs_kb=True,
        needs_web=False,
        confidence=0.2,
        reason="结构化意图结果无效，使用安全降级",
    )

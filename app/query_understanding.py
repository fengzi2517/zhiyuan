from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


SemanticIntent = Literal["chitchat", "create", "knowledge", "current", "mixed"]


class QueryUnderstanding(BaseModel):
    semantic_intent: SemanticIntent
    query: str = Field(min_length=1)
    needs_kb: bool
    needs_web: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=100)


def _result(question: str, intent: SemanticIntent, reason: str) -> QueryUnderstanding:
    return QueryUnderstanding(
        semantic_intent=intent,
        query=question.strip(),
        needs_kb=intent in {"knowledge", "mixed"},
        needs_web=intent in {"current", "mixed"},
        confidence=0.95,
        reason=reason,
    )


def detect_explicit_intent(question: str) -> QueryUnderstanding:
    """Resolve strong user signals without spending an LLM call."""
    text = question.strip()
    lowered = text.lower()
    current = any(word in lowered for word in (
        "今天", "现在", "当前", "最新", "实时", "汇率", "天气", "股价", "新闻",
        "today", "latest", "current", "weather", "price",
    ))
    kb_signal = any(word in lowered for word in (
        "公司", "制度", "资料", "文档", "知识库", "手册", "合同", "报告",
    ))
    if current and kb_signal:
        return _result(text, "mixed", "同时包含内部资料与时效信息信号")
    if kb_signal and any(word in lowered for word in ("根据", "结合", "参考", "按照", "基于", "依据")):
        return _result(text, "knowledge", "明确要求引用资料完成任务")
    if any(word in lowered for word in ("润色", "改写", "写一", "创作", "起草", "翻译")):
        return _result(text, "create", "包含创作或改写指令")
    if current:
        return _result(text, "current", "包含明确时效信号")
    if lowered.rstrip("，,。.!！ ") in {"你好", "您好", "嗨", "hello", "hi", "谢谢", "谢谢你", "再见"}:
        return _result(text, "chitchat", "包含明确会话信号")
    return _result(text, "knowledge", "默认按知识解释处理")


def validate_or_fallback(question: str, payload: Any) -> QueryUnderstanding:
    try:
        return QueryUnderstanding.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return QueryUnderstanding(
            semantic_intent="knowledge",
            query=question.strip(),
            needs_kb=True,
            needs_web=False,
            confidence=0.2,
            reason="结构化意图结果无效，使用安全降级",
        )


def understand_query(
    question: str,
    classifier: Callable[[str], Any] | None = None,
) -> QueryUnderstanding:
    deterministic = detect_explicit_intent(question)
    if (deterministic.semantic_intent != "knowledge" or classifier is None
            or deterministic.reason == "明确要求引用资料完成任务"):
        return deterministic
    try:
        payload = classifier(question)
    except Exception:
        payload = None
    return validate_or_fallback(question, payload)

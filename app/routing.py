from typing import Literal
from dataclasses import dataclass

from pydantic import BaseModel

from .query_understanding import QueryUnderstanding


Route = Literal["direct", "kb", "web", "hybrid"]


@dataclass(frozen=True)
class RouteContext:
    has_kb: bool
    web_enabled: bool


class RouteDecision(BaseModel):
    route: Route
    needs_kb: bool
    needs_web: bool
    reason: str


def _decision(route: Route, reason: str) -> RouteDecision:
    return RouteDecision(
        route=route,
        needs_kb=route in {"kb", "hybrid"},
        needs_web=route in {"web", "hybrid"},
        reason=reason,
    )


def decide_route(result: QueryUnderstanding, context: RouteContext) -> RouteDecision:
    """Apply the complete network and knowledge-base policy in one pure function."""
    if result.confidence < 0.5 and context.has_kb:
        return _decision("kb", "低置信度时优先使用已选知识库")
    if result.semantic_intent in {"chitchat", "create"}:
        return _decision("direct", "会话或创作请求由模型直接回答")
    if result.semantic_intent == "mixed":
        if context.has_kb and context.web_enabled:
            return _decision("hybrid", "同时需要内部资料与联网信息")
        if context.has_kb:
            return _decision("kb", "联网已关闭，仅检索知识库")
        if context.web_enabled:
            return _decision("web", "没有可用知识库，使用联网信息")
        return _decision("direct", "无可用外部信息源")
    if result.semantic_intent == "current":
        if context.web_enabled:
            return _decision("web", "时效问题需要联网")
        return _decision("kb" if context.has_kb else "direct", "联网已关闭")
    if context.has_kb:
        return _decision("kb", "知识问题使用已选知识库")
    return _decision("direct", "没有可用资料且问题不具时效性，由模型直接回答")

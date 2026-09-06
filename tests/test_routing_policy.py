import pytest

from app.query_understanding import QueryUnderstanding
from app.routing import RouteContext, decide_route


def understood(intent, confidence=0.9):
    return QueryUnderstanding(
        semantic_intent=intent,
        query="问题",
        needs_kb=intent in {"knowledge", "mixed"},
        needs_web=intent in {"current", "mixed"},
        confidence=confidence,
        reason="test",
    )


@pytest.mark.parametrize("intent,route", [("chitchat", "direct"), ("create", "direct")])
def test_conversational_and_creative_requests_are_direct(intent, route):
    assert decide_route(understood(intent), RouteContext(True, True)).route == route


def test_current_information_uses_web_when_enabled():
    assert decide_route(understood("current"), RouteContext(False, True)).route == "web"


def test_mixed_request_uses_both_sources():
    assert decide_route(understood("mixed"), RouteContext(True, True)).route == "hybrid"


def test_web_switch_is_absolute():
    decision = decide_route(understood("mixed"), RouteContext(has_kb=True, web_enabled=False))
    assert decision.route == "kb"
    assert decision.needs_web is False


def test_knowledge_route_respects_available_context():
    assert decide_route(understood("knowledge"), RouteContext(True, True)).route == "kb"
    assert decide_route(understood("knowledge"), RouteContext(False, True)).route == "web"
    assert decide_route(understood("knowledge"), RouteContext(False, False)).route == "direct"


def test_low_confidence_prefers_selected_knowledge_base():
    decision = decide_route(understood("current", confidence=0.2), RouteContext(True, True))
    assert decision.route == "kb"

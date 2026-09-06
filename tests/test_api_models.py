import pytest
from pydantic import ValidationError

from app.main import ChatReq


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "top_k": 11},
        {"question": "ok", "sim_threshold": -0.1},
        {"question": "ok", "sim_threshold": 1.1},
    ],
)
def test_chat_request_rejects_invalid_input(kwargs):
    with pytest.raises(ValidationError):
        ChatReq(**kwargs)


def test_chat_request_strips_question():
    req = ChatReq(question="  什么是 RAG？  ")
    assert req.question == "什么是 RAG？"


"""Keep unit tests independent of developer credentials and external services."""

import os
from pathlib import Path
import socket
from threading import local

import pytest


# Set these during collection, before any test imports app.config or its clients.
os.environ.update({
    "PYTHON_DOTENV_DISABLED": "1",
    "LLM_BASE_URL": "https://llm.invalid/v1",
    "LLM_API_KEY": "unit-test-key",
    "LLM_MODEL": "unit-test-model",
    "TAVILY_API_KEY": "unit-test-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "HF_HUB_OFFLINE": "1",
})
_project = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(next(
    (parent / ".hf-cache" for parent in (_project, *_project.parents)
     if (parent / ".hf-cache").is_dir()),
    _project / ".hf-cache",
))
for _proxy in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ[_proxy] = ""
    os.environ[_proxy.lower()] = ""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail even when application fallbacks swallow the blocked connection error."""
    attempts = []
    internal = local()
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair

    def blocked(operation, address):
        attempts.append((operation, address))
        raise AssertionError(f"Network access forbidden in unit tests: {operation} {address!r}")

    def connect(sock, address):
        # Windows implements socketpair via a loopback TCP connection. Allow only
        # that synchronous internal call, not arbitrary localhost service access.
        if (getattr(internal, "socketpair", False)
                and isinstance(address, tuple)
                and address[0] in ("127.0.0.1", "::1")):
            return original_connect(sock, address)
        return blocked("connect", address)

    def socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False

    monkeypatch.setattr(socket, "socketpair", socketpair)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex",
                        lambda _sock, address: blocked("connect_ex", address))
    monkeypatch.setattr(socket, "create_connection",
                        lambda address, *args, **kwargs: blocked("create_connection", address))
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, *args, **kwargs: blocked("getaddrinfo", host))
    yield
    assert not attempts, f"Test attempted network access (including swallowed errors): {attempts!r}"

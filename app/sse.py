import json
from typing import Any
import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse


class ClosingStreamingResponse(StreamingResponse):
    """Own a synchronous event iterator through normal completion and disconnect."""

    def __init__(self, content, **kwargs):
        self._event_iterator = content
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette's thread-pool adapter does not close its underlying
            # synchronous iterator. Do so at the response boundary, not at GC.
            with anyio.CancelScope(shield=True):
                try:
                    close_adapter = getattr(self.body_iterator, "aclose", None)
                    if close_adapter:
                        await close_adapter()
                finally:
                    close_events = getattr(self._event_iterator, "close", None)
                    if close_events:
                        await run_in_threadpool(close_events)


def encode_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"

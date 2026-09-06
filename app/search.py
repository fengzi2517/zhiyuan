from typing import Any
from . import config

_client = None

def _get_client() -> Any | None:
    global _client
    if _client is None:
        if not config.TAVILY_API_KEY:
            return None   # 未配置 key，联网搜索降级为空结果
        from tavily import TavilyClient
        _client = TavilyClient(api_key=config.TAVILY_API_KEY)
    return _client

def web_search(query: str, max_results: int = 3) -> list[dict]:
    """联网搜索，返回 [{title, url, content}]；任何异常都不阻断主流程"""
    client = _get_client()
    if client is None:
        return []
    try:
        resp = client.search(query=query, max_results=max_results)
        return [{"title": r.get("title", ""),
                 "url": r.get("url", ""),
                 "content": r.get("content", "")}
                for r in resp.get("results", [])]
    except Exception:
        return []

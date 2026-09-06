import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field


class Source(BaseModel):
    kind: str
    key: str
    title: str
    content: str = ""
    url: str | None = None
    document_id: int | None = None
    chunk_id: int | None = None
    location: str = ""
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""
    start_char: int | None = None
    end_char: int | None = None
    score: float | None = None
    number: int | None = Field(default=None, ge=1)


def normalize_web_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    hostname = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    netloc = hostname + port
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def number_sources(sources: list[Source]) -> list[Source]:
    unique: list[Source] = []
    seen: set[str] = set()
    for source in sources:
        key = source.key
        if source.kind == "web" and source.url:
            key = normalize_web_url(source.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source.model_copy(update={"key": key, "number": len(unique) + 1}))
    return unique


def validate_answer_citations(answer: str, sources: list[Source]) -> tuple[str, list[Source]]:
    available = {source.number: source for source in sources if source.number is not None}
    used_numbers: list[int] = []

    def replace(match: re.Match) -> str:
        number = int(match.group(1))
        if number not in available:
            return ""
        if number not in used_numbers:
            used_numbers.append(number)
        return match.group(0)

    cleaned = re.sub(r"\[(\d+)\]", replace, answer)
    return cleaned, [available[number] for number in used_numbers]

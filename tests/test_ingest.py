from app import ingest


def test_empty_chunks_mark_document_failed(monkeypatch):
    events = []
    monkeypatch.setattr(ingest, "parse_file", lambda *_: "")
    monkeypatch.setattr(ingest, "set_status", lambda *args: events.append(args))

    ingest.process_file(7, None, "empty.txt", b"fixture")

    assert events[-1][1] == "failed"
    assert "未提取到" in events[-1][2]


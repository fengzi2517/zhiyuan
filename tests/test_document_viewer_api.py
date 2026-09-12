from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main


def test_document_location_routes_are_registered():
    paths = set(main.app.openapi()['paths'])
    assert "/documents/{doc_id}/chunks/{chunk_id}/context" in paths
    assert "/documents/{doc_id}/original" in paths


def test_original_path_must_stay_in_document_directory(tmp_path):
    allowed = tmp_path / "4" / "source.pdf"
    allowed.parent.mkdir()
    allowed.write_bytes(b"pdf")
    assert main.resolve_document_path(tmp_path, 4, str(allowed)) == allowed.resolve()

    outside = tmp_path / "other.pdf"
    outside.write_bytes(b"no")
    with pytest.raises(HTTPException) as exc:
        main.resolve_document_path(tmp_path, 4, str(outside))
    assert exc.value.status_code == 409


def test_chunk_context_404_when_location_does_not_exist(monkeypatch):
    monkeypatch.setattr(main, "get_chunk_context", lambda *_args: None)
    with pytest.raises(HTTPException) as exc:
        main.api_chunk_context(2, 99)
    assert exc.value.status_code == 404

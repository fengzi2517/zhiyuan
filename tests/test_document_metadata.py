from pathlib import Path

from app.chunker import chunk_units
from app.ingest import store_original_file
from app.parser import ParsedUnit, parse_file_units


def test_text_file_is_returned_as_a_locatable_unit():
    units = parse_file_units("guide.md", "# 标题\n正文内容".encode("utf-8"))

    assert units == [ParsedUnit(text="# 标题\n正文内容", page=None, start_char=0)]


def test_chunks_retain_page_section_and_character_location():
    chunks = chunk_units(
        [ParsedUnit(text="# 标题\n这是一段足够长的正文内容，用于保留定位元数据。", page=3, start_char=20)]
    )

    assert chunks[0].page_start == 3
    assert chunks[0].page_end == 3
    assert chunks[0].section == "标题"
    assert chunks[0].start_char == 20
    assert chunks[0].end_char > chunks[0].start_char


def test_original_upload_path_cannot_escape_document_directory(tmp_path):
    stored = Path(store_original_file(tmp_path, 17, "../../private/report.PDF", b"pdf"))

    assert stored == tmp_path / "17" / "source.pdf"
    assert stored.read_bytes() == b"pdf"

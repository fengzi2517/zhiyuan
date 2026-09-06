from app.sources import Source, number_sources, normalize_web_url, validate_answer_citations


def kb_source(chunk_id=3):
    return Source(
        kind="kb", key=f"chunk:{chunk_id}", title="操作手册", content="正文",
        document_id=2, chunk_id=chunk_id, location="第 3 页", score=0.8,
    )


def test_duplicate_source_reuses_one_number():
    numbered = number_sources([kb_source(), kb_source(), kb_source(4)])

    assert [item.number for item in numbered] == [1, 2]


def test_web_url_fragment_is_not_part_of_source_identity():
    assert normalize_web_url("HTTPS://Example.COM/path?q=1#section") == "https://example.com/path?q=1"


def test_invalid_citations_are_removed_and_unused_sources_are_hidden():
    answer, used = validate_answer_citations("依据[1]，补充[9]。", number_sources([kb_source(), kb_source(4)]))

    assert answer == "依据[1]，补充。"
    assert [source.number for source in used] == [1]

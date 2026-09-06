from app.chunker import chunk_text


def test_short_non_empty_document_is_kept():
    assert chunk_text("hello") == ["hello"]


def test_long_english_paragraph_is_bounded():
    chunks = chunk_text("This is a sentence. " * 100, size=200, overlap=40)
    assert len(chunks) > 1
    assert max(map(len, chunks)) <= 200


def test_single_unpunctuated_sentence_has_fallback_split():
    chunks = chunk_text("x" * 1000, size=200, overlap=40)
    assert len(chunks) > 1
    assert max(map(len, chunks)) <= 200
    assert len(chunks[-1]) > 40

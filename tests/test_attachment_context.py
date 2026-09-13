import pytest
from fastapi import HTTPException
from app.attachment_context import summarize_full_text, bounded_groups, build_messages


def test_summary_covers_tail_and_all_groups():
    calls = []
    def summarize(messages):
        calls.append(messages[-1]['content'])
        return '组摘要'
    result, covered = summarize_full_text('头' * 13000 + '文末唯一标记', 3000, summarize)
    assert covered == 2 and '文末唯一标记' in calls[-1]
    assert '组摘要' in result


def test_large_summary_refuses_without_partial_claim():
    with pytest.raises(HTTPException):
        bounded_groups('x' * 600001)


def test_mixed_image_payload_and_text_only():
    messages = build_messages('policy', 'question', [('图 [1]', b'jpeg')])
    assert messages[1]['content'][2]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert build_messages('policy', 'question', [])[1]['content'] == 'question'

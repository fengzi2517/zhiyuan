import pytest

from app.db import _assert_embedding_dimension


def test_matching_embedding_dimension_is_accepted():
    _assert_embedding_dimension("vector(1024)", 1024)


def test_mismatched_embedding_dimension_stops_without_migration():
    with pytest.raises(RuntimeError, match="不会自动删除文档"):
        _assert_embedding_dimension("vector(512)", 1024)


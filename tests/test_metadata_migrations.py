from app import db


def test_rich_response_columns_are_declared():
    assert hasattr(db.Document, "storage_path")
    assert hasattr(db.Chunk, "page_start")
    assert hasattr(db.Chunk, "page_end")
    assert hasattr(db.Chunk, "section")
    assert hasattr(db.Chunk, "start_char")
    assert hasattr(db.Chunk, "end_char")
    assert hasattr(db.ChatMessage, "semantic_intent")
    assert hasattr(db.ChatMessage, "route")
    assert hasattr(db.ChatMessage, "sources")
    assert hasattr(db.ChatMessage, "trace")
    assert hasattr(db.ChatMessage, "elapsed_ms")
    assert hasattr(db.ChatMessage, "status")


def test_metadata_migrations_are_additive_and_idempotent():
    statements = db.metadata_migration_statements()

    assert any("documents ADD COLUMN IF NOT EXISTS storage_path" in sql for sql in statements)
    assert any("chunks ADD COLUMN IF NOT EXISTS page_start" in sql for sql in statements)
    assert any("chat_messages ADD COLUMN IF NOT EXISTS sources" in sql for sql in statements)
    assert all("DROP " not in sql.upper() and "DELETE " not in sql.upper() for sql in statements)


def test_message_payload_keeps_response_metadata():
    class Message:
        id = 7
        role = "assistant"
        content = "答案[1]"
        created_at = "now"
        semantic_intent = "factual"
        route = "knowledge_base"
        sources = [{"id": 1, "title": "文档"}]
        trace = [{"step": "retrieve"}]
        elapsed_ms = 123
        status = "complete"
        model_options = None
        attachments = None

    payload = db.serialize_message(Message())

    assert payload["semantic_intent"] == "factual"
    assert payload["route"] == "knowledge_base"
    assert payload["sources"][0]["id"] == 1
    assert payload["trace"][0]["step"] == "retrieve"
    assert payload["elapsed_ms"] == 123
    assert payload["status"] == "complete"
    assert payload['model_options'] == {} and payload['attachments'] == []

import logging
from pathlib import Path

from .parser import parse_file_units
from .chunker import chunk_units
from .embeddings import embed_texts
from .db import save_chunks, set_status, save_document_text, save_document_storage_path
from .config import UPLOAD_DIR

logger = logging.getLogger(__name__)


def store_original_file(base_dir: str | Path, doc_id: int, filename: str, data: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if not extension or len(extension) > 10 or not extension[1:].isalnum():
        extension = ".bin"
    directory = Path(base_dir) / str(doc_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"source{extension}"
    target.write_bytes(data)
    return str(target)

def process_file(doc_id: int, kb_id: int | None, filename: str, data: bytes):
    try:
        storage_path = store_original_file(UPLOAD_DIR, doc_id, filename, data)
        save_document_storage_path(doc_id, storage_path)
        units = parse_file_units(filename, data)
        text = "\n".join(unit.text for unit in units)
        if not text.strip():
            raise ValueError("文件未提取到有效文本")
        save_document_text(doc_id, text)       # 保存全文，供前端查看
        chunks = chunk_units(units)
        if not chunks:
            raise ValueError("文件未生成有效文本块")
        embeddings = embed_texts([chunk.content for chunk in chunks])
        save_chunks(doc_id, kb_id, chunks, embeddings)
        set_status(doc_id, "done", "")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:500]
        set_status(doc_id, "failed", message)
        logger.exception("document ingestion failed doc_id=%s filename=%s", doc_id, filename)

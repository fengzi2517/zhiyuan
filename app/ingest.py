import logging

from .parser import parse_file
from .chunker import chunk_text
from .embeddings import embed_texts
from .db import save_chunks, set_status, save_document_text

logger = logging.getLogger(__name__)

def process_file(doc_id: int, kb_id: int | None, filename: str, data: bytes):
    try:
        text = parse_file(filename, data)      # 图片走 OCR，pdf/docx/txt 走文本提取
        if not text.strip():
            raise ValueError("文件未提取到有效文本")
        save_document_text(doc_id, text)       # 保存全文，供前端查看
        chunks = chunk_text(text)              # 400 字、80 字重叠切块
        if not chunks:
            raise ValueError("文件未生成有效文本块")
        embeddings = embed_texts(chunks)       # 批量向量化
        save_chunks(doc_id, kb_id, chunks, embeddings)
        set_status(doc_id, "done", "")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:500]
        set_status(doc_id, "failed", message)
        logger.exception("document ingestion failed doc_id=%s filename=%s", doc_id, filename)

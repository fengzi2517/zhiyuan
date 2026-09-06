from .parser import parse_file
from .chunker import chunk_text
from .embeddings import embed_texts
from .db import save_chunks, set_status, save_document_text

def process_file(doc_id: int, kb_id: int | None, filename: str, data: bytes):
    try:
        text = parse_file(filename, data)      # 图片走 OCR，pdf/docx/txt 走文本提取
        save_document_text(doc_id, text)       # 保存全文，供前端查看
        chunks = chunk_text(text)              # 400 字、80 字重叠切块
        embeddings = embed_texts(chunks)       # 批量向量化
        save_chunks(doc_id, kb_id, chunks, embeddings)
        set_status(doc_id, "done")
    except Exception:
        set_status(doc_id, "failed")
        raise

import io
from dataclasses import dataclass


def _ocr_image(data: bytes) -> str:
    from .ocr import ocr_image

    return ocr_image(data)

# 文本类文件编码探测顺序（utf-8 → gbk → utf-16，覆盖中英文常见编码）
_TEXT_ENCODINGS = ("utf-8", "gbk", "utf-16")


@dataclass(frozen=True)
class ParsedUnit:
    text: str
    page: int | None = None
    start_char: int = 0


def parse_file_units(filename: str, data: bytes) -> list[ParsedUnit]:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        return _parse_pdf_units(data)
    text = parse_file(filename, data)
    return [ParsedUnit(text=text, page=None, start_char=0)] if text.strip() else []

def parse_file(filename: str, data: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix in ("png", "jpg", "jpeg", "bmp", "webp"):
        return _ocr_image(data)
    if suffix == "pdf":
        return _parse_pdf(data)
    if suffix == "docx":
        return _parse_docx(data)
    if suffix in ("txt", "md"):
        return _decode_text(data)
    raise ValueError(f"不支持的文件类型: {suffix}")

def _decode_text(data: bytes) -> str:
    """编码自适应解码：先去 BOM，再依次尝试常见编码，全部失败则 utf-8 容错"""
    for enc in _TEXT_ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def _parse_pdf(data: bytes) -> str:
    """PDF 解析：优先文本层提取；文本过少的页（扫描页）渲染成图片走 OCR"""
    return "\n".join(unit.text for unit in _parse_pdf_units(data))


def _parse_pdf_units(data: bytes) -> list[ParsedUnit]:
    """Extract each PDF page separately so citations can reopen the matched page."""
    import fitz   # PyMuPDF
    doc = fitz.open(stream=data, filetype="pdf")
    units = []
    offset = 0
    for page_number, page in enumerate(doc, start=1):
        text = page.get_text().strip()
        if len(text) < 20:   # 该页基本无文本层，按扫描页处理
            pix = page.get_pixmap(dpi=200)
            text = _ocr_image(pix.tobytes("png")).strip()
        if text:
            units.append(ParsedUnit(text=text, page=page_number, start_char=offset))
            offset += len(text) + 1
    doc.close()
    if not units:
        raise ValueError("PDF 未提取到任何内容（文本与 OCR 均失败）")
    return units

def _parse_docx(data: bytes) -> str:
    """docx 解析：段落 + 表格（表格按行拼接为制表符分隔文本）"""
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append("\t".join(cells))
    return "\n".join(parts)

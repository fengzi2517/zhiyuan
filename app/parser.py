import io
import math
import zipfile
from dataclasses import dataclass


def _ocr_image(data: bytes) -> str:
    from .ocr import ocr_image

    return ocr_image(data)

# 文本类文件编码探测顺序（utf-8 → gbk → utf-16，覆盖中英文常见编码）
_TEXT_ENCODINGS = ("utf-8", "gbk", "utf-16")
MAX_DOCUMENT_CHARS = 1_000_000
MAX_PDF_PAGES = 300
MAX_RENDER_PIXELS = 25_000_000
MAX_RENDER_DIMENSION = 10_000
MAX_DOCX_INFLATED_BYTES = 100 * 1024 * 1024
MAX_DOCX_MEMBERS = 5000
MAX_DOCX_RATIO = 200


def _bounded_text(text):
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ValueError('文档提取文字超过 100 万字符，请拆分文档')
    return text


def _validate_docx_archive(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                raise ValueError('DOCX 压缩成员超过 5000 项，请拆分文档')
            if sum(member.file_size for member in members) > MAX_DOCX_INFLATED_BYTES:
                raise ValueError('DOCX 解压大小超过 100 MB，请拆分文档')
            if any(member.file_size > MAX_DOCX_RATIO * max(1, member.compress_size) for member in members):
                raise ValueError('DOCX 压缩比例过高，请重新导出或拆分文档')
    except zipfile.BadZipFile as exc:
        raise ValueError('DOCX 文件损坏或格式不合法') from exc


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
        return _bounded_text(_decode_text(data))
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
    import pymupdf as fitz
    units = []
    offset = 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        if len(doc) > MAX_PDF_PAGES:
            raise ValueError('PDF 超过 300 页，请拆分文档')
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if len(text) < 20:   # 该页基本无文本层，按扫描页处理
                # Compute the same integer pixel bounds as the renderer before allocation.
                rect = page.rect * fitz.Matrix(200 / 72, 200 / 72)
                if not all(math.isfinite(value) for value in rect):
                    raise ValueError('PDF 页面尺寸无效')
                width = math.ceil(rect.x1) - math.floor(rect.x0)
                height = math.ceil(rect.y1) - math.floor(rect.y0)
                if (width <= 0 or height <= 0 or max(width, height) > MAX_RENDER_DIMENSION
                        or width * height > MAX_RENDER_PIXELS):
                    raise ValueError('PDF 页面尺寸超过安全渲染上限，请缩小页面后上传')
                pix = page.get_pixmap(dpi=200)
                text = _ocr_image(pix.tobytes("png")).strip()
            if text:
                if offset + len(text) > MAX_DOCUMENT_CHARS:
                    raise ValueError('文档提取文字超过 100 万字符，请拆分文档')
                units.append(ParsedUnit(text=text, page=page_number, start_char=offset))
                offset += len(text) + 1
    if not units:
        raise ValueError("PDF 未提取到任何内容（文本与 OCR 均失败）")
    return units

def _parse_docx(data: bytes) -> str:
    """docx 解析：段落 + 表格（表格按行拼接为制表符分隔文本）"""
    import docx
    _validate_docx_archive(data)
    d = docx.Document(io.BytesIO(data))
    parts = []
    characters = 0
    def append(text):
        nonlocal characters
        if text.strip():
            characters += len(text) + (1 if parts else 0)
            if characters > MAX_DOCUMENT_CHARS:
                raise ValueError('文档提取文字超过 100 万字符，请拆分文档')
            parts.append(text)
    for paragraph in d.paragraphs:
        append(paragraph.text)
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                append("\t".join(cells))
    return "\n".join(parts)

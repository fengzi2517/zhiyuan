import re
from dataclasses import dataclass
from .parser import ParsedUnit

# 标题行特征：markdown 标题 / 中文章节（第一章、一、）/ 阿拉伯数字编号（1. / 1.2.3 / 第1条）
_HEADING_RE = re.compile(
    r"^(#{1,6}\s+\S"                      # markdown: # 标题
    r"|第[一二三四五六七八九十百\d]+[章节部分条][^\n]{0,40}$"   # 第一章 / 第1条
    r"|[一二三四五六七八九十]+、[^\n]{0,40}$"                  # 一、
    r"|[A-Z][、.\s][^\n]{0,40}$"                              # A. / A、
    r"|\d+(\.\d+)*[、.\s]\s*[^\n]{0,40}$"                     # 1. / 1.2. / 3、
    r")"
)
# 句末标点（用于长段落按句切分，避免拦腰截断）
_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")


@dataclass(frozen=True)
class ChunkData:
    content: str
    page_start: int | None
    page_end: int | None
    section: str
    start_char: int
    end_char: int


def chunk_units(units: list[ParsedUnit], size: int = 500, overlap: int = 120) -> list[ChunkData]:
    result: list[ChunkData] = []
    for unit in units:
        cursor = 0
        current_section = ""
        for content in chunk_text(unit.text, size=size, overlap=overlap):
            heading = _section_heading(content)
            if heading:
                current_section = heading
            local_start = unit.text.find(content, max(0, cursor - overlap))
            if local_start < 0:
                local_start = unit.text.find(content)
            if local_start < 0:
                local_start = cursor
            local_end = local_start + len(content)
            result.append(ChunkData(
                content=content,
                page_start=unit.page,
                page_end=unit.page,
                section=current_section,
                start_char=unit.start_char + local_start,
                end_char=unit.start_char + local_end,
            ))
            cursor = local_end
    return result


def _section_heading(content: str) -> str:
    first = content.splitlines()[0].strip() if content else ""
    if not _HEADING_RE.match(first):
        return ""
    return re.sub(r"^#{1,6}\s*", "", first).strip()

def chunk_text(text: str, size: int = 500, overlap: int = 120) -> list[str]:
    """语义感知切块：
    1) 空行分段，标题行强制开启新块（标题与其后内容保持同块）
    2) 相邻段落合并至目标长度，块间按句子边界重叠
    3) 超长段落按句子边界切分，不再字符硬切
    """
    # 规整：去行首尾空白、合并连续空白行为单个分隔
    lines = [ln.strip() for ln in text.splitlines()]
    paras, buf = [], []
    for ln in lines:
        if ln:
            buf.append(ln)
        elif buf:
            paras.append("\n".join(buf)); buf = []
    if buf:
        paras.append("\n".join(buf))

    # 按标题分段（标题归属其后的段落）
    sections, cur = [], []
    for p in paras:
        first = p.splitlines()[0] if p else ""
        if _HEADING_RE.match(first) and cur:
            sections.append(cur); cur = [p]
        else:
            cur.append(p)
    if cur:
        sections.append(cur)

    chunks = []
    # 过短的起始块（如孤立文档标题）并入下一节，避免无意义小向量
    if len(sections) > 1 and len("\n".join(sections[0])) < 50:
        sections[1] = sections[0] + sections[1]
        sections.pop(0)
    for sec in sections:
        buf = ""
        for p in sec:
            # 单段已超长：先按句切开再并入
            if len(p) > size:
                if buf:
                    chunks.append(buf); buf = ""
                chunks.extend(_split_long(p, size, overlap))
                continue
            if buf and len(buf) + len(p) + 1 > size:
                chunks.append(buf)
                # 与下一块保留句子级重叠，维持上下文连贯
                buf = _tail_sentences(buf, overlap) + "\n" + p
            else:
                buf = (buf + "\n" + p) if buf else p
        if buf.strip():
            chunks.append(buf)

    kept = [c for c in chunks if len(c.strip()) > 10]
    if not kept and text.strip():
        return [text.strip()]
    return kept

def _split_long(p: str, size: int, overlap: int) -> list[str]:
    """超长段落按句子边界切分"""
    sents = [s for s in _SENT_SPLIT.split(p) if s.strip()]
    out, buf = [], ""
    for s in sents:
        if len(s) > size:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_split_by_chars(s, size, overlap))
            continue
        if buf and len(buf) + len(s) > size:
            out.append(buf)
            buf = (_tail_sentences(buf, overlap) + s)[-size:]
        else:
            buf += s
    if buf.strip():
        out.append(buf)
    return out


def _split_by_chars(text: str, size: int, overlap: int) -> list[str]:
    """句子本身过长时的保底切分，确保任何块都不超过 size。"""
    step = max(1, size - min(overlap, size - 1))
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + size]
        if chunk.strip():
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks

def _tail_sentences(text: str, overlap: int) -> str:
    """取文本末尾约 overlap 字的完整句子，作为块间上下文重叠"""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    # 从第一个句末标点后开始，保证不截半句
    m = re.search(r"[。！？；!?;]", tail)
    return tail[m.end():] if m else tail

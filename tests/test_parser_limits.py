from io import BytesIO
import zipfile

import docx
import pymupdf
import pytest

from app import parser


def pdf_bytes(width=595, height=842, text=None, pages=1):
    with pymupdf.open() as document:
        for _ in range(pages):
            page = document.new_page(width=width, height=height)
            if text:
                page.insert_text((50, 70), text)
        return document.tobytes()


@pytest.mark.parametrize('width,height', [(10000, 10000), (4000, 100)])
def test_large_pdf_page_rejected_before_render(monkeypatch, width, height):
    data = pdf_bytes(width, height)
    monkeypatch.setattr(pymupdf.Page, 'get_pixmap', lambda *_args, **_kw: pytest.fail('unsafe render'))
    with pytest.raises(ValueError, match='页面尺寸'):
        parser.parse_file_units('large.pdf', data)


def test_pdf_page_count_rejected_before_read(monkeypatch):
    data = pdf_bytes(pages=301)
    monkeypatch.setattr(pymupdf.Page, 'get_text', lambda *_args, **_kw: pytest.fail('page read'))
    with pytest.raises(ValueError, match='300'):
        parser.parse_file_units('many.pdf', data)


def test_zip_bomb_rejected_before_docx_load(monkeypatch):
    data = BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', 'a' * 200000)
    monkeypatch.setattr(docx, 'Document', lambda *_: pytest.fail('unsafe decompression'))
    with pytest.raises(ValueError, match='压缩'):
        parser.parse_file('bomb.docx', data.getvalue())


def test_docx_member_count_rejected(monkeypatch):
    data = BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for i in range(5001):
            archive.writestr(str(i), '')
    monkeypatch.setattr(docx, 'Document', lambda *_: pytest.fail('unsafe decompression'))
    with pytest.raises(ValueError, match='成员'):
        parser.parse_file('many.docx', data.getvalue())


def test_text_limit_applies_to_plain_and_pdf(monkeypatch):
    with pytest.raises(ValueError, match='100 万'):
        parser.parse_file('large.txt', b'a' * 1000001)
    data = pdf_bytes(text='A normal paragraph long enough to avoid OCR.')
    monkeypatch.setattr(pymupdf.Page, 'get_text', lambda *_args, **_kw: 'x' * 1000001)
    with pytest.raises(ValueError, match='100 万'):
        parser.parse_file_units('large.pdf', data)


def test_normal_pdf_docx_and_scanned_pdf(monkeypatch):
    text = 'A normal paragraph long enough to avoid OCR.'
    assert text in parser.parse_file('normal.pdf', pdf_bytes(text=text))
    document = docx.Document()
    document.add_paragraph('正常文档')
    data = BytesIO()
    document.save(data)
    assert parser.parse_file('normal.docx', data.getvalue()) == '正常文档'
    monkeypatch.setattr(parser, '_ocr_image', lambda _: '扫描页识别文字')
    units = parser.parse_file_units('scan.pdf', pdf_bytes())
    assert units[0].page == 1 and units[0].text == '扫描页识别文字'

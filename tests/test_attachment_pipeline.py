from io import BytesIO
import pytest
from PIL import Image

from app.file_pipeline import normalize_image, validate_upload, parse_and_chunk


def test_image_decode_and_normalize():
    data = BytesIO()
    Image.new('RGBA', (24, 24), (255, 0, 0, 128)).save(data, format='PNG')
    result = normalize_image(data.getvalue())
    image = Image.open(BytesIO(result))
    assert image.format == 'JPEG' and image.size == (24, 24)
    with pytest.raises(ValueError):
        normalize_image(b'not an image')


def test_upload_and_text_parser_limits():
    with pytest.raises(ValueError):
        validate_upload('run.exe', b'x')
    with pytest.raises(ValueError):
        validate_upload('a.txt', b'')
    content, chunks = parse_and_chunk('a.txt', '附件资料用于回答问题。'.encode())
    assert content == '附件资料用于回答问题。'
    assert chunks[0].content == content


def test_pixel_limit_before_decode(monkeypatch):
    import app.file_pipeline as pipeline
    monkeypatch.setattr(pipeline, 'MAX_IMAGE_PIXELS', 10)
    data = BytesIO()
    Image.new('RGB', (4, 4)).save(data, format='PNG')
    with pytest.raises(ValueError, match='像素'):
        normalize_image(data.getvalue())


def test_transparent_image_retains_visible_black_text():
    data = BytesIO()
    original = Image.new('RGBA', (100, 50), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(original).rectangle((10, 10, 30, 30), fill=(0, 0, 0, 255))
    original.save(data, 'PNG')
    result = Image.open(BytesIO(normalize_image(data.getvalue())))
    assert min(result.getpixel((80, 25))) > 240
    assert max(result.getpixel((20, 20))) < 15

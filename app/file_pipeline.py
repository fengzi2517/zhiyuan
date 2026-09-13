"""Shared upload, original storage and parsing primitives for both resource types."""
import os
import secrets
import warnings
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.md', '.png', '.jpg', '.jpeg', '.bmp', '.webp'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 50 * 1024 * 1024
MAX_FILES = 5
MAX_IMAGE_PIXELS = 25_000_000


def validate_upload(filename, data):
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES or not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('文件类型、内容或大小不合法（单文件最多 20 MB）')


def store_atomic(target, data):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / (secrets.token_hex(16) + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as original:
                if original.format not in ('PNG', 'JPEG', 'WEBP', 'BMP'):
                    raise ValueError('不支持的图片格式')
                if original.width * original.height > MAX_IMAGE_PIXELS:
                    raise ValueError('图片像素超过 2500 万上限')
                original.load()
                oriented = ImageOps.exif_transpose(original).convert('RGBA')
                background = Image.new('RGBA', oriented.size, (255, 255, 255, 255))
                image = Image.alpha_composite(background, oriented).convert('RGB')
                image.thumbnail((2048, 2048))
                output = BytesIO()
                image.save(output, format='JPEG', quality=88)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('图片损坏或尺寸过大') from exc


def parse_and_chunk(filename, data):
    from .parser import parse_file_units
    from .chunker import chunk_units
    units = parse_file_units(filename, data)
    chunks = chunk_units(units)
    if not chunks:
        raise ValueError('未提取到可用文字')
    return '\n'.join(unit.text for unit in units), chunks

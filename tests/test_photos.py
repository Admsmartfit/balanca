"""Testes da recodificação/validação de fotos (app/photos.py — PRD v3 Etapa 1)."""

import io

import pytest
from PIL import Image

from app.photos import MAX_DIMENSIONS, THUMB_MAX_DIMENSION, InvalidImage, save_photo


def _fake_jpeg_bytes(size: tuple[int, int] = (100, 100)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(120, 60, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_save_photo_writes_jpeg_and_thumbnail(tmp_path):
    saved = save_photo(_fake_jpeg_bytes(), directory=tmp_path)

    assert saved.file_path.exists()
    assert saved.thumb_path.exists()
    assert saved.content_type == "image/jpeg"
    assert saved.file_path.suffix == ".jpg"

    with Image.open(saved.file_path) as img:
        assert img.format == "JPEG"


def test_save_photo_rejects_non_image_bytes(tmp_path):
    with pytest.raises(InvalidImage):
        save_photo(b"isto nao e uma imagem, so texto qualquer", directory=tmp_path)


def test_save_photo_rejects_truncated_or_corrupted_image(tmp_path):
    corrupted = _fake_jpeg_bytes()[:20]  # cabeçalho válido, dados cortados
    with pytest.raises(InvalidImage):
        save_photo(corrupted, directory=tmp_path)


def test_save_photo_resizes_large_images_to_max_dimensions(tmp_path):
    saved = save_photo(_fake_jpeg_bytes((3000, 4000)), directory=tmp_path)
    with Image.open(saved.file_path) as img:
        assert img.width <= MAX_DIMENSIONS[0]
        assert img.height <= MAX_DIMENSIONS[1]


def test_save_photo_thumbnail_is_small(tmp_path):
    saved = save_photo(_fake_jpeg_bytes((2000, 2000)), directory=tmp_path)
    with Image.open(saved.thumb_path) as img:
        assert img.width <= THUMB_MAX_DIMENSION
        assert img.height <= THUMB_MAX_DIMENSION


def test_save_photo_strips_exif_metadata(tmp_path):
    buffer = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=(10, 20, 30))
    exif = img.getexif()
    exif[0x9286] = "comentário com dado pessoal"  # UserComment
    img.save(buffer, format="JPEG", exif=exif)

    saved = save_photo(buffer.getvalue(), directory=tmp_path)
    with Image.open(saved.file_path) as out:
        assert out.getexif() == {} or 0x9286 not in out.getexif()


def test_save_photo_uses_given_basename(tmp_path):
    saved = save_photo(_fake_jpeg_bytes(), directory=tmp_path, basename="front")
    assert saved.file_path.name == "front.jpg"
    assert saved.thumb_path.name == "front-thumb.jpg"


def test_save_photo_creates_directory_if_missing(tmp_path):
    nested = tmp_path / "client-42" / "measurement-7"
    saved = save_photo(_fake_jpeg_bytes(), directory=nested)
    assert saved.file_path.exists()

"""Recodificação e validação de fotos — um único ponto de gravação em disco.

PRD v3 Etapa 1: só confiar no `content_type` que o navegador manda no upload
não impede que um arquivo qualquer (renomeado ou malicioso) seja salvo como
se fosse uma imagem. Este módulo abre o arquivo de verdade com o Pillow —
que só decodifica se o conteúdo for realmente uma imagem —, corrige a
orientação EXIF (fotos de celular/webcam vêm rotacionadas conforme o sensor),
descarta os metadados (EXIF pode conter GPS e outros dados pessoais — LGPD),
limita o tamanho máximo e gera uma miniatura para listagens/comparador.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DIMENSIONS = (1080, 1920)
THUMB_MAX_DIMENSION = 360
JPEG_QUALITY = 85


class InvalidImage(ValueError):
    """O conteúdo enviado não é uma imagem decodificável (ou está corrompido)."""


@dataclass(frozen=True, slots=True)
class SavedPhoto:
    file_path: Path
    thumb_path: Path
    content_type: str


def _load_and_normalize(raw_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()  # força a decodificação agora — arquivos truncados/falsos estouram aqui
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage("o arquivo enviado não é uma imagem válida") from exc

    image = ImageOps.exif_transpose(image)  # corrige a rotação antes de descartar o EXIF
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return image


def _fit_within(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    resized = image.copy()
    resized.thumbnail(max_size, Image.LANCZOS)
    return resized


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = image.convert("RGB") if image.mode != "RGB" else image
    rgb.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # sem parâmetro exif = sem metadados


def save_photo(raw_bytes: bytes, *, directory: Path, basename: str | None = None) -> SavedPhoto:
    """Valida, recodifica e salva uma foto + miniatura em `directory`.

    Levanta `InvalidImage` se `raw_bytes` não for uma imagem decodificável.
    """
    image = _load_and_normalize(raw_bytes)
    name = basename or uuid.uuid4().hex

    full = _fit_within(image, MAX_DIMENSIONS)
    file_path = directory / f"{name}.jpg"
    _save_jpeg(full, file_path)

    thumb = _fit_within(image, (THUMB_MAX_DIMENSION, THUMB_MAX_DIMENSION))
    thumb_path = directory / f"{name}-thumb.jpg"
    _save_jpeg(thumb, thumb_path)

    return SavedPhoto(file_path=file_path, thumb_path=thumb_path, content_type="image/jpeg")

import struct

from app.assisted.schemas import AssistedError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"


def validate_image(
    content: bytes,
    declared_media_type: str | None,
    *,
    max_bytes: int,
    max_pixels: int,
) -> str:
    if not content or len(content) > max_bytes:
        raise AssistedError("Изображение превышает допустимый размер.", code="IMAGE_SIZE")
    if content.startswith(PNG_SIGNATURE):
        media_type = "image/png"
        width, height = _png_dimensions(content)
    elif content.startswith(JPEG_SIGNATURE):
        media_type = "image/jpeg"
        width, height = _jpeg_dimensions(content)
    else:
        raise AssistedError("Поддерживаются только JPEG и PNG.", code="IMAGE_TYPE")
    if declared_media_type and declared_media_type not in {media_type, "application/octet-stream"}:
        raise AssistedError("Тип файла не совпадает с содержимым.", code="IMAGE_MIME")
    if width <= 0 or height <= 0 or width * height > max_pixels:
        raise AssistedError("Изображение имеет недопустимое разрешение.", code="IMAGE_PIXELS")
    return media_type


def _png_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 24 or content[12:16] != b"IHDR":
        raise AssistedError("PNG поврежден.", code="IMAGE_INVALID")
    return struct.unpack(">II", content[16:24])


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 9 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(content):
            break
        length = int.from_bytes(content[offset : offset + 2], "big")
        if length < 2 or offset + length > len(content):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            return width, height
        offset += length
    raise AssistedError("JPEG поврежден.", code="IMAGE_INVALID")

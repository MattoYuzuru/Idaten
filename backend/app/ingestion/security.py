import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath

from app.ingestion.schemas import ImportError

SUPPORTED_SUFFIXES = {".gpx", ".tcx", ".fit", ".csv"}
ALLOWED_MEDIA_TYPES: dict[str, set[str]] = {
    ".gpx": {"application/gpx+xml", "application/xml", "text/xml"},
    ".tcx": {"application/vnd.garmin.tcx+xml", "application/xml", "text/xml"},
    ".fit": {"application/vnd.ant.fit", "application/octet-stream"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}


@dataclass(frozen=True, slots=True)
class SafeUpload:
    parse_content: bytes
    parse_suffix: str
    raw_suffix: str
    display_filename: str


def validate_upload(
    filename: str,
    media_type: str | None,
    content: bytes,
    *,
    max_upload_bytes: int,
    max_archive_uncompressed_bytes: int,
    max_archive_entries: int,
    max_archive_ratio: int,
) -> SafeUpload:
    if not content:
        raise ImportError("Файл пуст.", code="EMPTY_UPLOAD")
    if len(content) > max_upload_bytes:
        raise ImportError("Файл превышает допустимый размер.", code="UPLOAD_TOO_LARGE")
    display_filename = _display_filename(filename)
    suffix = PurePath(display_filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES | {".zip"}:
        raise ImportError(
            "Поддерживаются только GPX, TCX, FIT, CSV и ZIP.", code="UNSUPPORTED_TYPE"
        )
    normalized_media_type = (media_type or "application/octet-stream").split(";", 1)[0].lower()
    allowed = ALLOWED_MEDIA_TYPES[suffix]
    if normalized_media_type != "application/octet-stream" and normalized_media_type not in allowed:
        raise ImportError("MIME type не соответствует расширению файла.", code="MIME_MISMATCH")
    if suffix != ".zip":
        return SafeUpload(content, suffix, suffix, display_filename)
    extracted, extracted_suffix = _extract_archive(
        content,
        max_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_entries=max_archive_entries,
        max_ratio=max_archive_ratio,
    )
    return SafeUpload(extracted, extracted_suffix, suffix, display_filename)


def _display_filename(filename: str) -> str:
    basename = PurePath(filename).name
    sanitized = "".join(character for character in basename if character.isprintable())
    return sanitized[:255] or "activity"


def _extract_archive(
    content: bytes, *, max_uncompressed_bytes: int, max_entries: int, max_ratio: int
) -> tuple[bytes, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise ImportError("ZIP-архив поврежден.", code="INVALID_ZIP") from error
    with archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if not entries or len(entries) > max_entries:
            raise ImportError("Недопустимое число файлов в ZIP.", code="ZIP_ENTRY_LIMIT")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ImportError("ZIP содержит небезопасный путь.", code="ZIP_PATH_TRAVERSAL")
            if entry.file_size > max_uncompressed_bytes:
                raise ImportError("ZIP превышает допустимый размер.", code="ZIP_SIZE_LIMIT")
            ratio = entry.file_size / max(entry.compress_size, 1)
            if ratio > max_ratio:
                raise ImportError("ZIP имеет опасную степень сжатия.", code="ZIP_BOMB")
        supported = [
            entry
            for entry in entries
            if PurePath(entry.filename).suffix.lower() in SUPPORTED_SUFFIXES
        ]
        if len(supported) != 1 or len(entries) != 1:
            raise ImportError(
                "ZIP должен содержать ровно один GPX, TCX, FIT или CSV.", code="ZIP_CONTENT"
            )
        selected = supported[0]
        if selected.file_size > max_uncompressed_bytes:
            raise ImportError("ZIP превышает допустимый размер.", code="ZIP_SIZE_LIMIT")
        try:
            extracted = archive.read(selected)
        except (RuntimeError, zipfile.BadZipFile) as error:
            raise ImportError("ZIP не удалось безопасно прочитать.", code="INVALID_ZIP") from error
        suffix = PurePath(selected.filename).suffix.lower()
        return extracted, suffix

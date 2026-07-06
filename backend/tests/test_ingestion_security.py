import io
import zipfile

import pytest

from app.ingestion.schemas import ImportError
from app.ingestion.security import validate_upload
from app.storage.service import LocalFilesystemStorage, StorageError


def _validate(filename: str, content: bytes, media_type: str = "application/octet-stream"):
    return validate_upload(
        filename,
        media_type,
        content,
        max_upload_bytes=1024 * 1024,
        max_archive_uncompressed_bytes=10_000,
        max_archive_entries=2,
        max_archive_ratio=10,
    )


def _zip(name: str, content: bytes, compression: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def test_zip_path_traversal_is_rejected() -> None:
    with pytest.raises(ImportError) as captured:
        _validate("upload.zip", _zip("../../activity.gpx", b"data"), "application/zip")
    assert captured.value.code == "ZIP_PATH_TRAVERSAL"


def test_zip_bomb_ratio_is_rejected() -> None:
    archive = _zip("activity.csv", b"0" * 5_000, zipfile.ZIP_DEFLATED)
    with pytest.raises(ImportError) as captured:
        _validate("upload.zip", archive, "application/zip")
    assert captured.value.code == "ZIP_BOMB"


def test_zip_must_contain_one_supported_file() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("first.csv", b"a")
        archive.writestr("second.gpx", b"b")
    with pytest.raises(ImportError) as captured:
        _validate("upload.zip", buffer.getvalue(), "application/zip")
    assert captured.value.code == "ZIP_CONTENT"


def test_size_and_mime_are_validated() -> None:
    with pytest.raises(ImportError, match="размер"):
        validate_upload(
            "activity.csv",
            "text/csv",
            b"x" * 11,
            max_upload_bytes=10,
            max_archive_uncompressed_bytes=100,
            max_archive_entries=1,
            max_archive_ratio=10,
        )
    with pytest.raises(ImportError) as captured:
        _validate("activity.gpx", b"xml", "text/csv")
    assert captured.value.code == "MIME_MISMATCH"


@pytest.mark.asyncio
async def test_storage_uses_generated_name_and_blocks_escape(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    stored = await storage.save("raw", b"private", ".gpx")

    assert "user-file" not in stored.uri
    assert await storage.read(stored.uri) == b"private"
    with pytest.raises(StorageError, match="escapes"):
        await storage.read("../secret")

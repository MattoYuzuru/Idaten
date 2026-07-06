import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


class StorageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    uri: str
    size_bytes: int
    sha256: str


class StorageService(Protocol):
    async def save(self, namespace: str, content: bytes, suffix: str) -> StoredObject: ...

    async def read(self, uri: str) -> bytes: ...

    async def delete(self, uri: str) -> None: ...


class LocalFilesystemStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    async def save(self, namespace: str, content: bytes, suffix: str) -> StoredObject:
        safe_namespace = self._safe_component(namespace)
        safe_suffix = self._safe_suffix(suffix)
        relative = PurePosixPath(safe_namespace) / f"{uuid.uuid4().hex}{safe_suffix}"
        destination = self._resolve_uri(relative.as_posix())
        await asyncio.to_thread(self._write_exclusive, destination, content)
        return StoredObject(
            uri=relative.as_posix(),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    async def read(self, uri: str) -> bytes:
        path = self._resolve_uri(uri)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as error:
            raise StorageError("Storage object is unavailable.") from error

    async def delete(self, uri: str) -> None:
        path = self._resolve_uri(uri)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as error:
            raise StorageError("Storage object could not be deleted.") from error

    def _resolve_uri(self, uri: str) -> Path:
        candidate = (self.root / PurePosixPath(uri)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError("Storage URI escapes configured root.")
        return candidate

    @staticmethod
    def _safe_component(value: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        if not value or any(character not in allowed for character in value):
            raise StorageError("Invalid storage namespace.")
        return value

    @staticmethod
    def _safe_suffix(value: str) -> str:
        normalized = value.lower()
        allowed = ".abcdefghijklmnopqrstuvwxyz0123456789"
        if normalized and (
            not normalized.startswith(".")
            or len(normalized) > 10
            or any(character not in allowed for character in normalized)
        ):
            raise StorageError("Invalid storage suffix.")
        return normalized

    @staticmethod
    def _write_exclusive(destination: Path, content: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)

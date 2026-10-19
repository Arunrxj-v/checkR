"""Local filesystem storage backend (development default)."""

from __future__ import annotations

from pathlib import Path

import aiofiles

from app.core.config import settings
from app.storage.base import StorageError, sanitize_key


class LocalStorage:
    name = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = sanitize_key(key)
        path = (self.root / safe).resolve()
        root = self.root.resolve()
        # Defence in depth: the resolved path must stay inside the root.
        if root not in path.parents and path != root:
            raise StorageError(f"Refusing to access path outside storage root: {key!r}")
        return path

    async def save(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiofiles.open(path, "wb") as fh:
                await fh.write(data)
        except OSError as exc:
            raise StorageError(f"Failed to write {key!r}: {exc}") from exc
        return sanitize_key(key)

    async def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError(f"Object not found: {key!r}")
        try:
            async with aiofiles.open(path, "rb") as fh:
                return await fh.read()
        except OSError as exc:
            raise StorageError(f"Failed to read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Failed to delete {key!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def health(self) -> dict:
        writable = False
        try:
            probe = self.root / ".checkr_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError:
            writable = False
        return {
            "provider": self.name,
            "ok": writable,
            "detail": f"root={self.root}",
        }

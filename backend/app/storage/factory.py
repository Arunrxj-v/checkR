"""Storage factory — the only place that knows the configured backend."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from app.storage.base import StorageBackend, StorageError, build_key, sanitize_key
from app.storage.local import LocalStorage

logger = get_logger(__name__)


def build_storage(provider: str | None = None) -> StorageBackend:
    name = (provider or settings.storage_provider or "local").lower()
    if name == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage()
    if name != "local":
        logger.warning("Unknown storage provider %r; falling back to local.", name)
    return LocalStorage()


@lru_cache
def get_storage() -> StorageBackend:
    return build_storage()


async def storage_health() -> dict:
    try:
        return await get_storage().health()
    except StorageError as exc:
        return {"provider": settings.storage_provider, "ok": False, "detail": str(exc)}


__all__ = [
    "StorageBackend",
    "StorageError",
    "LocalStorage",
    "get_storage",
    "build_storage",
    "build_key",
    "sanitize_key",
    "storage_health",
]

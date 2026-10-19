"""S3-compatible object storage backend (production).

``boto3`` is an optional dependency; install with ``pip install -e ".[s3]"``.
boto3 is synchronous, so calls are dispatched to a worker thread.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.storage.base import StorageError, sanitize_key


class S3Storage:
    name = "s3"

    def __init__(self) -> None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise StorageError(
                "STORAGE_PROVIDER=s3 requires boto3. Install with: pip install -e \".[s3]\""
            ) from exc

        if not settings.s3_bucket:
            raise StorageError("STORAGE_PROVIDER=s3 requires S3_BUCKET to be set.")

        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def save(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        safe = sanitize_key(key)
        extra = {"ContentType": content_type} if content_type else None
        try:
            await self._run(
                self._client.put_object,
                Bucket=self._bucket,
                Key=safe,
                Body=data,
                **(extra or {}),
            )
        except Exception as exc:  # boto3 raises botocore exceptions
            raise StorageError(f"Failed to upload {safe!r}: {exc}") from exc
        return safe

    async def read(self, key: str) -> bytes:
        safe = sanitize_key(key)
        try:
            resp = await self._run(
                self._client.get_object, Bucket=self._bucket, Key=safe
            )
            return await self._run(resp["Body"].read)
        except Exception as exc:
            raise StorageError(f"Failed to download {safe!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        safe = sanitize_key(key)
        try:
            await self._run(self._client.delete_object, Bucket=self._bucket, Key=safe)
        except Exception as exc:
            raise StorageError(f"Failed to delete {safe!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        safe = sanitize_key(key)
        try:
            await self._run(self._client.head_object, Bucket=self._bucket, Key=safe)
            return True
        except Exception:
            return False

    async def health(self) -> dict:
        try:
            await self._run(self._client.head_bucket, Bucket=self._bucket)
            return {"provider": self.name, "ok": True, "detail": f"bucket={self._bucket}"}
        except Exception as exc:
            return {"provider": self.name, "ok": False, "detail": str(exc)[:200]}

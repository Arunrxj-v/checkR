"""Storage key safety and the local backend."""

from __future__ import annotations

import pytest

from app.storage import LocalStorage, build_key, sanitize_key
from app.storage.base import StorageError


@pytest.mark.parametrize(
    "bad_key",
    [
        "../etc/passwd",
        "a/../../b",
        "/absolute/path",
        "..",
        "",
        "foo/../../bar",
        "windows\\..\\escape",
    ],
)
def test_sanitize_key_rejects_path_traversal(bad_key):
    with pytest.raises(ValueError):
        sanitize_key(bad_key)


@pytest.mark.parametrize(
    "good_key",
    ["a", "a/b", "originals/abc/source.pdf", "pages/x/page_001.png"],
)
def test_sanitize_key_accepts_safe_keys(good_key):
    assert sanitize_key(good_key) == good_key


def test_build_key_composes_and_strips():
    assert build_key("pages", "sub-1", "page_001.png") == "pages/sub-1/page_001.png"
    assert build_key("", "a", "b") == "a/b"


def test_build_key_rejects_traversal_segment():
    with pytest.raises(ValueError):
        build_key("pages", "../secrets")


async def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(root=tmp_path)
    key = "originals/abc/source.bin"
    await storage.save(key, b"payload", content_type="application/octet-stream")
    assert await storage.exists(key)
    assert await storage.read(key) == b"payload"
    await storage.delete(key)
    assert not await storage.exists(key)


async def test_local_storage_refuses_to_escape_root(tmp_path):
    storage = LocalStorage(root=tmp_path / "root")
    with pytest.raises(ValueError):
        await storage.save("../escape.bin", b"nope")


async def test_local_storage_missing_object_raises(tmp_path):
    storage = LocalStorage(root=tmp_path)
    with pytest.raises(StorageError):
        await storage.read("does/not/exist.bin")


async def test_local_storage_health(tmp_path):
    storage = LocalStorage(root=tmp_path)
    health = await storage.health()
    assert health["ok"] is True
    assert health["provider"] == "local"

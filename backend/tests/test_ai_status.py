"""Settings/health AI status: real checks, never fabricated success.

The system routes must report the configured provider's *actual* runtime
state — reachable, installed, inference verified — and must never claim
``ready`` without an inference request. HTTP is mocked with
``httpx.MockTransport`` here; the real-model tests live in
``test_ollama_integration.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.factory import AIProviderError, get_provider
from app.ai.ollama import OllamaProvider
from app.core.config import settings
from tests.conftest import auth_header, register_and_login


def make_ollama(handler) -> OllamaProvider:
    return OllamaProvider(
        base_url="http://ollama.test:11434",
        model="gemma3:4b",
        timeout=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


def tags_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "models": [
                {
                    "name": "gemma3:4b",
                    "model": "gemma3:4b",
                    "capabilities": ["completion", "vision"],
                    "details": {"families": ["gemma3", "clip"]},
                }
            ]
        },
    )


def chat_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": "gemma3:4b", "done": True,
              "message": {"role": "assistant", "content": "OK"}},
    )


@pytest.fixture
async def teacher_headers(client) -> dict:
    data = await register_and_login(client)
    return auth_header(data["access_token"])


# --------------------------------------------------------------------------- #
# GET /api/settings — capability + availability payload
# --------------------------------------------------------------------------- #
async def test_settings_reports_connected_but_not_ready_without_probe(
    client, monkeypatch, teacher_headers
):
    provider = make_ollama(tags_ok)
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.get("/api/settings", headers=teacher_headers)
    finally:
        await provider.aclose()

    assert resp.status_code == 200
    ai = resp.json()["ai"]
    assert ai["provider"] == "ollama"
    assert ai["model"] == "gemma3:4b"
    assert ai["display_name"] == "Gemma 3 4B · Local"
    assert ai["is_mock"] is False
    assert ai["status"] == "connected"
    assert ai["available"] is True
    assert ai["connected"] is True
    # Never claim verified inference when no request was made.
    assert ai["inference_ok"] is None
    assert ai["ocr_available"] is True
    assert ai["evaluation_available"] is True
    assert ai["vision_capable"] is True


async def test_settings_reports_unavailable_when_ollama_down(
    client, monkeypatch, teacher_headers
):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = make_ollama(down)
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.get("/api/settings", headers=teacher_headers)
    finally:
        await provider.aclose()

    ai = resp.json()["ai"]
    assert ai["status"] == "unavailable"
    assert ai["available"] is False
    assert ai["ocr_available"] is False
    assert ai["evaluation_available"] is False
    assert "Ollama is unavailable" in ai["detail"]


async def test_settings_reports_model_not_installed(
    client, monkeypatch, teacher_headers
):
    provider = make_ollama(
        lambda request: httpx.Response(200, json={"models": []})
    )
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.get("/api/settings", headers=teacher_headers)
    finally:
        await provider.aclose()

    ai = resp.json()["ai"]
    assert ai["status"] == "model_not_installed"
    assert ai["model_installed"] is False
    assert ai["ocr_available"] is False
    assert "ollama pull gemma3:4b" in ai["detail"]


async def test_settings_survives_a_broken_provider_factory(
    client, monkeypatch, teacher_headers
):
    """A config error must surface as a truthful failure, not a 500."""
    def boom() -> OllamaProvider:
        raise AIProviderError("AI_PROVIDER=mock is only allowed in tests.",
                              retryable=False, kind="config")

    monkeypatch.setattr("app.api.routes.system.get_provider", boom)
    resp = await client.get("/api/settings", headers=teacher_headers)

    assert resp.status_code == 200
    ai = resp.json()["ai"]
    assert ai["status"] == "error"
    assert ai["available"] is False
    assert ai["ocr_available"] is False
    assert "only allowed in tests" in ai["detail"]


# --------------------------------------------------------------------------- #
# POST /api/system/ai/probe — the only path to `ready`
# --------------------------------------------------------------------------- #
async def test_probe_runs_real_chat_and_reports_ready(
    client, monkeypatch, teacher_headers
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/chat":
            return chat_ok(request)
        return tags_ok(request)

    provider = make_ollama(handler)
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.post(
            "/api/system/ai/probe?force=true", headers=teacher_headers
        )
    finally:
        await provider.aclose()

    assert resp.status_code == 200
    ai = resp.json()["ai"]
    assert ai["status"] == "ready"
    assert ai["inference_ok"] is True
    assert isinstance(ai["inference_ms"], int)
    assert ai["ocr_available"] is True

    chat_requests = [r for r in seen if r.url.path == "/api/chat"]
    assert len(chat_requests) == 1
    body = json.loads(chat_requests[0].content)
    assert body["model"] == "gemma3:4b"
    assert body["stream"] is False


async def test_probe_reports_inference_error_when_chat_fails(
    client, monkeypatch, teacher_headers
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            return httpx.Response(500, text="runner crashed")
        return tags_ok(request)

    provider = make_ollama(handler)
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.post(
            "/api/system/ai/probe?force=true", headers=teacher_headers
        )
    finally:
        await provider.aclose()

    ai = resp.json()["ai"]
    assert ai["status"] == "inference_error"
    assert ai["inference_ok"] is False
    assert ai["available"] is False
    assert "HTTP 500" in ai["detail"]


async def test_health_never_claims_ready_from_existence(
    client, monkeypatch
):
    """GET /api/health uses the cheap check: connected, not ready."""
    provider = make_ollama(tags_ok)
    monkeypatch.setattr("app.api.routes.system.get_provider", lambda: provider)
    try:
        resp = await client.get("/api/health")
    finally:
        await provider.aclose()

    assert resp.status_code == 200
    ai = resp.json()["ai"]
    assert ai["status"] == "connected"
    assert ai["inference_ok"] is None


# --------------------------------------------------------------------------- #
# Factory: mock is refused outside the test suite
# --------------------------------------------------------------------------- #
def test_factory_refuses_mock_outside_tests(monkeypatch):
    get_provider.cache_clear()
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "ai_provider", "mock")
    try:
        with pytest.raises(AIProviderError) as excinfo:
            get_provider()
        assert excinfo.value.kind == "config"
        assert "only allowed in the test suite" in str(excinfo.value)
    finally:
        get_provider.cache_clear()


def test_settings_warns_about_mock_outside_tests(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "ai_provider", "mock")
    warnings = settings.warnings()
    assert any("AI_PROVIDER=mock" in w for w in warnings)

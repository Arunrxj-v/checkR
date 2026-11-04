"""Ollama provider: wire protocol, availability and error classification.

Every HTTP call is mocked with ``httpx.MockTransport`` — no real inference
happens here. The real-model tests live in ``test_ollama_integration.py``.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.ai.base import AIProviderError
from app.ai.ollama import (
    UNAVAILABLE_MESSAGE,
    OllamaProvider,
    display_name_for,
)
from app.ai.types import EvaluationContext
from app.core.config import settings

IMAGE = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def make_provider(handler, **kwargs) -> OllamaProvider:
    kwargs.setdefault("base_url", "http://ollama.test:11434")
    kwargs.setdefault("model", "gemma3:4b")
    kwargs.setdefault("timeout", 5)
    kwargs.setdefault("max_retries", 0)
    return OllamaProvider(transport=httpx.MockTransport(handler), **kwargs)


def tags_response(models: list[str]) -> httpx.Response:
    return httpx.Response(
        200, json={"models": [{"name": name, "model": name} for name in models]}
    )


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gemma3:4b",
            "done": True,
            "message": {"role": "assistant", "content": content},
        },
    )


OCR_JSON = json.dumps(
    {
        "page_number": 1,
        "transcription": "Q1. TCP is a connection oriented protocol.",
        "confidence": 0.87,
        "detected_answers": [
            {
                "question_number": "1",
                "transcription": "TCP is a connection oriented protocol.",
                "started_on_previous_page": False,
                "continues_on_next_page": False,
                "regions": [{"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3}],
                "uncertain_segments": [],
                "confidence": 0.87,
            }
        ],
        "diagrams": [],
        "unreadable_regions": [],
        "manual_review_required": False,
    }
)

EVAL_JSON = json.dumps(
    {
        "awarded_marks": 4,
        "confidence": 0.9,
        "reasoning": "Three steps are described in the correct order.",
        "criteria": [
            {"name": "SYN packet", "awarded_marks": 1, "satisfied": True, "comment": "ok"},
            {"name": "SYN-ACK packet", "awarded_marks": 1, "satisfied": True, "comment": "ok"},
            {"name": "ACK packet", "awarded_marks": 1, "satisfied": True, "comment": "ok"},
            {"name": "Correct sequence", "awarded_marks": 1, "satisfied": True, "comment": "ok"},
            {"name": "Purpose or explanation", "awarded_marks": 0, "satisfied": False, "comment": "missing"},
        ],
        "strengths": [],
        "gaps": ["purpose"],
        "contradictions": [],
        "flags": [],
    }
)


def evaluation_context() -> EvaluationContext:
    return EvaluationContext(
        question_label="Q1",
        question_text="Explain TCP three-way handshake.",
        question_type="explanation",
        max_marks=5,
        expected_answer="SYN, SYN-ACK, ACK.",
        guidance=None,
        keywords=["SYN", "ACK"],
        criteria=[
            {"name": "SYN packet", "description": None, "max_marks": 1},
            {"name": "SYN-ACK packet", "description": None, "max_marks": 1},
            {"name": "ACK packet", "description": None, "max_marks": 1},
            {"name": "Correct sequence", "description": None, "max_marks": 1},
            {"name": "Purpose or explanation", "description": None, "max_marks": 1},
        ],
        transcription="Client sends SYN, server replies SYN-ACK, client confirms ACK.",
        ocr_confidence=0.9,
        images=[IMAGE],
        submission_ref="deadbeef",
    )


# --------------------------------------------------------------------------- #
# Display name
# --------------------------------------------------------------------------- #
def test_display_name_is_human_readable():
    assert display_name_for("gemma3:4b") == "Gemma 3 4B · Local"
    assert display_name_for("llava") == "Llava · Local"


# --------------------------------------------------------------------------- #
# Availability: GET /api/tags
# --------------------------------------------------------------------------- #
async def test_health_ok_when_model_installed():
    provider = make_provider(lambda request: tags_response(["gemma3:4b"]))
    try:
        health = await provider.health()
    finally:
        await provider.aclose()

    assert health["ok"] is True
    assert health["status"] == "ok"
    assert health["provider"] == "ollama"
    assert health["model"] == "gemma3:4b"
    assert health["display_name"] == "Gemma 3 4B · Local"
    assert health["is_mock"] is False
    assert health["ocr_enabled"] is True
    assert health["evaluation_enabled"] is True


async def test_health_reports_missing_model_with_pull_command():
    provider = make_provider(lambda request: tags_response(["tinyllama:latest"]))
    try:
        health = await provider.health()
    finally:
        await provider.aclose()

    assert health["ok"] is False
    assert health["status"] == "model_missing"
    assert health["model_installed"] is False
    assert "ollama pull gemma3:4b" in health["detail"]


async def test_health_reports_unavailable_when_ollama_is_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    try:
        health = await provider.health()
    finally:
        await provider.aclose()

    assert health["ok"] is False
    assert health["status"] == "unavailable"
    assert "Ollama is unavailable" in health["detail"]
    assert "Start the local Ollama service" in health["detail"]


async def test_availability_is_cached_between_probes():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return tags_response(["gemma3:4b"])

    provider = make_provider(handler)
    try:
        await provider.availability()
        await provider.availability()
        assert calls["n"] == 1
        await provider.availability(refresh=True)
        assert calls["n"] == 2
    finally:
        await provider.aclose()


async def test_require_available_raises_actionable_errors():
    provider = make_provider(lambda request: tags_response([]))
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.require_available()
        assert excinfo.value.kind == "model_missing"
        assert "ollama pull gemma3:4b" in str(excinfo.value)
    finally:
        await provider.aclose()


# --------------------------------------------------------------------------- #
# Vision OCR: POST /api/chat with the real page image
# --------------------------------------------------------------------------- #
async def test_transcribe_page_sends_image_and_parses_structure():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return chat_response(OCR_JSON)

    provider = make_provider(handler)
    try:
        result = await provider.transcribe_page(IMAGE, page_number=1)
    finally:
        await provider.aclose()

    # Native Ollama API, not an OpenAI-compatible endpoint.
    assert captured["path"] == "/api/chat"
    body = captured["body"]
    assert body["model"] == "gemma3:4b"
    assert body["stream"] is False
    assert body["format"] == "json"

    # The actual page image travels with the request.
    user_message = body["messages"][1]
    assert len(user_message["images"]) == 1
    assert base64.b64decode(user_message["images"][0]) == IMAGE
    assert body["messages"][0]["role"] == "system"
    assert "handwriting" in body["messages"][0]["content"].lower()

    # Structured output survives into the provider-agnostic result.
    assert result.is_mock is False
    assert result.provider == "ollama"
    assert result.model == "gemma3:4b"
    assert result.prompt_version == "handwriting_v2"
    assert "connection oriented" in result.text
    assert result.confidence == pytest.approx(0.87)
    assert len(result.detected_answers) == 1
    assert result.detected_answers[0]["question_number"] == "1"
    assert result.detected_answers[0]["regions"][0]["x1"] == pytest.approx(0.9)
    assert result.manual_review_required is False


async def test_transcribe_page_passes_previous_page_context():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return chat_response(OCR_JSON)

    provider = make_provider(handler)
    try:
        await provider.transcribe_page(
            IMAGE, page_number=2, previous_context="...the client confirms with ACK."
        )
    finally:
        await provider.aclose()

    prompt = captured["body"]["messages"][1]["content"]
    assert "PREVIOUS page" in prompt
    assert "the client confirms with ACK" in prompt


async def test_transcribe_page_rejects_empty_image():
    provider = make_provider(lambda request: chat_response(OCR_JSON))
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(b"", page_number=1)
        assert excinfo.value.retryable is False
    finally:
        await provider.aclose()


async def test_transcribe_page_reports_unavailable_ollama():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(IMAGE, page_number=1)
        assert excinfo.value.kind == "unavailable"
        assert UNAVAILABLE_MESSAGE in str(excinfo.value)
    finally:
        await provider.aclose()


async def test_transcribe_page_reports_missing_model_without_retrying():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            404, json={"error": "model 'gemma3:4b' not found"}
        )

    provider = make_provider(handler, max_retries=2)
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(IMAGE, page_number=1)
        assert excinfo.value.kind == "model_missing"
        assert excinfo.value.retryable is False
        assert "ollama pull gemma3:4b" in str(excinfo.value)
        assert calls["n"] == 1  # configuration errors are never retried
    finally:
        await provider.aclose()


async def test_malformed_model_output_is_retried_then_failed():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return chat_response("sorry, I cannot read this page")

    provider = make_provider(handler, max_retries=2)
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(IMAGE, page_number=1)
        assert excinfo.value.kind == "bad_response"
        assert calls["n"] == 3  # initial attempt + OLLAMA_MAX_RETRIES
    finally:
        await provider.aclose()


async def test_schema_violating_output_is_retried():
    calls = {"n": 0}
    bad = json.dumps({"text": "hi", "detected_answers": ["not-a-dictionary"]})

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return chat_response(bad)

    provider = make_provider(handler, max_retries=1)
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(IMAGE, page_number=1)
        assert excinfo.value.kind == "bad_response"
        assert "validation" in str(excinfo.value).lower()
        assert calls["n"] == 2
    finally:
        await provider.aclose()


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
async def test_evaluate_answer_maps_criteria_and_provenance():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return chat_response(EVAL_JSON)

    provider = make_provider(handler)
    try:
        result = await provider.evaluate_answer(
            evaluation_context(), prompt_version="theory_v1"
        )
    finally:
        await provider.aclose()

    # The answer image accompanies the evaluation request.
    assert len(captured["body"]["messages"][1]["images"]) == 1

    assert result.provider == "ollama"
    assert result.model == "gemma3:4b"
    assert result.prompt_version == "theory_v1"
    assert result.is_mock is False
    assert len(result.criteria) == 5
    assert sum(c.awarded_marks for c in result.criteria) == pytest.approx(4)
    assert 0 <= result.awarded_marks <= 5


async def test_evaluate_answer_unavailable_is_actionable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.evaluate_answer(
                evaluation_context(), prompt_version="theory_v1"
            )
        assert excinfo.value.kind == "unavailable"
        assert "Ollama is unavailable" in str(excinfo.value)
    finally:
        await provider.aclose()


async def test_evaluate_answer_respects_evaluation_switch(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_enabled", False)
    provider = make_provider(lambda request: chat_response(EVAL_JSON))
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.evaluate_answer(
                evaluation_context(), prompt_version="theory_v1"
            )
        assert excinfo.value.kind == "config"
        assert "EVALUATION_ENABLED" in str(excinfo.value)
    finally:
        await provider.aclose()


async def test_transcribe_respects_ocr_switch(monkeypatch):
    monkeypatch.setattr(settings, "ocr_enabled", False)
    provider = make_provider(lambda request: chat_response(OCR_JSON))
    try:
        with pytest.raises(AIProviderError) as excinfo:
            await provider.transcribe_page(IMAGE, page_number=1)
        assert excinfo.value.kind == "config"
        assert "OCR_ENABLED" in str(excinfo.value)
    finally:
        await provider.aclose()

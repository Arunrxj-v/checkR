"""Failure paths: an unavailable or disabled AI runtime must fail loudly.

Nothing here ever falls back to fabricated results — a submission either gets
real inference or an actionable error message and a FAILED status. Covers:

* Ollama unreachable          -> "Ollama is unavailable. Start the local ..."
* model not installed         -> "Run: ollama pull <model>"
* OCR_ENABLED=false           -> fails before any provider call
* fatal runtime error mid-loop-> whole submission aborted, no OCR rows
* one bad page of many        -> batch continues, failure recorded per page
* EVALUATION_ENABLED=false    -> evaluation stage fails with the reason
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.ai.base import AIProviderError
from app.ai.ollama import OllamaProvider
from app.ai.types import OCRPageResult
from app.core.config import settings
from app.db.enums import JobType, PageStatus, SubmissionStatus
from app.models.answer import OCRResult
from app.models.submission import Submission, SubmissionPage
from app.services import processing_service
from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    pdf_bytes,
    png_bytes,
    register_and_login,
)
from tests.test_pipeline import FakeJob, _run_pipeline, _upload


async def _submission(client, *, files, student_data=None) -> dict:
    auth = await register_and_login(client)
    headers = auth_header(auth["access_token"])
    exam = await create_exam_with_questions(client, headers)
    return await _upload(client, headers, exam["id"], files=files, data=student_data or {})


async def _stage_one(db, submission_id, *, content_type="image/png"):
    await processing_service.process_submission(
        db,
        FakeJob(
            JobType.PROCESS_SUBMISSION,
            submission_id=uuid.UUID(str(submission_id)),
            payload={"content_type": content_type},
        ),
    )
    await db.flush()


async def _stage_one_and_segment(db, submission_id, *, content_type="image/png"):
    await _stage_one(db, submission_id, content_type=content_type)
    await processing_service.segment_answers_job(
        db, FakeJob(JobType.SEGMENT_ANSWERS, submission_id=uuid.UUID(str(submission_id)))
    )
    await db.flush()


async def _stage_three(db, submission_id):
    await processing_service.evaluate_submission(
        db,
        FakeJob(
            JobType.EVALUATE_SUBMISSION,
            submission_id=uuid.UUID(str(submission_id)),
            payload={"force": False},
        ),
    )
    await db.flush()


async def _row(db, submission_id) -> Submission:
    return (
        await db.execute(
            select(Submission).where(Submission.id == uuid.UUID(submission_id))
        )
    ).scalar_one()


class _FatalProvider:
    """Passes preflight, then reports the runtime as unusable on every page."""

    name = "ollama"
    model = "gemma3:4b"
    is_mock = False

    def __init__(self, *, kind: str = "unavailable", message: str | None = None):
        self.kind = kind
        self.message = message or (
            "Ollama is unavailable. Start the local Ollama service to process "
            "answer sheets."
        )
        self.calls = 0

    async def require_available(self) -> None:  # preflight passes
        return None

    async def transcribe_page(self, image_bytes, *, page_number, prompt_version="", previous_context=None):
        self.calls += 1
        raise AIProviderError(self.message, retryable=True, kind=self.kind)

    async def health(self) -> dict:
        return {}

    async def aclose(self) -> None:
        return None


class _OneBadPageProvider:
    """Page 1 returns unusable output; page 2 transcribes normally."""

    name = "ollama"
    model = "gemma3:4b"
    is_mock = False

    async def require_available(self) -> None:
        return None

    async def transcribe_page(self, image_bytes, *, page_number, prompt_version="", previous_context=None):
        if page_number == 1:
            raise AIProviderError(
                "Ollama returned unusable output after 2 attempts.",
                retryable=True,
                kind="bad_response",
            )
        return OCRPageResult(
            text="Q1. SYN SYN-ACK ACK",
            confidence=0.9,
            provider="ollama",
            model="gemma3:4b",
            prompt_version=prompt_version,
            is_mock=False,
            detected_answers=[
                {
                    "question_number": "1",
                    "transcription": "SYN SYN-ACK ACK",
                    "regions": [],
                    "uncertain_segments": [],
                    "confidence": 0.9,
                }
            ],
        )

    async def health(self) -> dict:
        return {}

    async def aclose(self) -> None:
        return None


async def test_unreachable_ollama_fails_the_submission_with_a_fix(client, db, monkeypatch):
    submission = await _submission(
        client, files={"files": ("s.png", png_bytes(700, 900, "Q1. hi"), "image/png")}
    )
    # Port 9 has nothing listening: the real provider reports "unavailable".
    down = OllamaProvider(base_url="http://127.0.0.1:9")
    monkeypatch.setattr(processing_service, "get_provider", lambda: down)
    try:
        with pytest.raises(processing_service.ProcessingError) as excinfo:
            await _stage_one(db, submission["id"])
    finally:
        await down.aclose()

    message = str(excinfo.value)
    assert "Ollama is unavailable" in message
    assert "Start the local Ollama service" in message

    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert "Ollama is unavailable" in (row.error_message or "")
    # Nothing was invented: no transcription exists for the page.
    assert (await db.execute(select(OCRResult))).scalars().all() == []


async def test_missing_model_fails_with_the_pull_command(client, db, monkeypatch):
    submission = await _submission(client, files={"files": ("s.png", png_bytes(), "image/png")})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "some-other:latest"}]})

    provider = OllamaProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(processing_service, "get_provider", lambda: provider)
    try:
        with pytest.raises(processing_service.ProcessingError) as excinfo:
            await _stage_one(db, submission["id"])
    finally:
        await provider.aclose()

    message = str(excinfo.value)
    assert f"ollama pull {settings.ocr_model}" in message
    assert f"ollama pull {settings.evaluation_model}" in message
    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert (await db.execute(select(OCRResult))).scalars().all() == []


async def test_disabled_ocr_fails_before_any_inference(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ocr_enabled", False)
    submission = await _submission(client, files={"files": ("s.png", png_bytes(), "image/png")})

    with pytest.raises(processing_service.ProcessingError, match="OCR_ENABLED=false"):
        await _stage_one(db, submission["id"])

    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert "OCR_ENABLED=false" in (row.error_message or "")
    assert (await db.execute(select(OCRResult))).scalars().all() == []


async def test_fatal_runtime_error_aborts_the_whole_submission(client, db, monkeypatch):
    submission = await _submission(client, files={"files": ("s.png", png_bytes(), "image/png")})
    provider = _FatalProvider()
    monkeypatch.setattr(processing_service, "get_provider", lambda: provider)

    with pytest.raises(processing_service.ProcessingError, match="Ollama is unavailable"):
        await _stage_one(db, submission["id"])

    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert "Ollama is unavailable" in (row.error_message or "")

    pages = (
        await db.execute(
            select(SubmissionPage).where(SubmissionPage.submission_id == row.id)
        )
    ).scalars().all()
    assert all(p.status == PageStatus.FAILED for p in pages)
    assert all("Ollama is unavailable" in (p.error_message or "") for p in pages)
    assert provider.calls == 1  # aborted, not retried page by page
    assert (await db.execute(select(OCRResult))).scalars().all() == []


async def test_one_bad_page_does_not_kill_the_batch(client, db, monkeypatch):
    submission = await _submission(
        client,
        files={
            "files": (
                "script.pdf",
                pdf_bytes(["Q1. page one answer", "Q2. page two answer"]),
                "application/pdf",
            )
        },
    )
    provider = _OneBadPageProvider()
    monkeypatch.setattr(processing_service, "get_provider", lambda: provider)

    await _stage_one(db, submission["id"], content_type="application/pdf")

    row = await _row(db, submission["id"])
    assert row.status != SubmissionStatus.FAILED
    assert row.processed_page_count == 1
    assert row.processing_meta["failed_pages"] == [1]
    # The chain continues: segmentation was queued for the surviving page.
    assert row.status == SubmissionStatus.OCR_PROCESSING

    pages = (
        await db.execute(
            select(SubmissionPage)
            .where(SubmissionPage.submission_id == row.id)
            .order_by(SubmissionPage.page_number)
        )
    ).scalars().all()
    assert [p.status for p in pages] == [PageStatus.FAILED, PageStatus.OCR_DONE]

    ocr_rows = (await db.execute(select(OCRResult))).scalars().all()
    assert len(ocr_rows) == 1
    # Only the page that produced usable output has a transcription.
    assert ocr_rows[0].text == "Q1. SYN SYN-ACK ACK"


async def test_disabled_evaluation_fails_the_submission(client, db, monkeypatch):
    submission = await _submission(client, files={"files": ("s.png", png_bytes(700, 900, "Q1. hi"), "image/png")})
    await _stage_one_and_segment(db, submission["id"])

    monkeypatch.setattr(settings, "evaluation_enabled", False)
    with pytest.raises(processing_service.ProcessingError, match="EVALUATION_ENABLED=false"):
        await _stage_three(db, submission["id"])

    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert "EVALUATION_ENABLED=false" in (row.error_message or "")


async def test_evaluation_preflight_reports_an_unreachable_runtime(client, db, monkeypatch):
    submission = await _submission(client, files={"files": ("s.png", png_bytes(700, 900, "Q1. hi"), "image/png")})
    await _stage_one_and_segment(db, submission["id"])

    down = OllamaProvider(base_url="http://127.0.0.1:9")
    monkeypatch.setattr(processing_service, "get_provider", lambda: down)
    try:
        with pytest.raises(processing_service.ProcessingError) as excinfo:
            await _stage_three(db, submission["id"])
    finally:
        await down.aclose()

    assert "Ollama is unavailable" in str(excinfo.value)
    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.FAILED
    assert "Start the local Ollama service" in (row.error_message or "")


async def test_unknown_provider_is_a_configuration_error_not_mock(client, db, monkeypatch):
    """AI_PROVIDER=nope must fail loudly — never silently become mock."""
    from app.ai.factory import build_provider

    monkeypatch.setattr(settings, "ai_provider", "nope")
    with pytest.raises(AIProviderError) as excinfo:
        build_provider()
    assert excinfo.value.kind == "config"
    assert "mock" in str(excinfo.value)


async def test_pipeline_still_runs_end_to_end_with_the_mock_only_when_explicit(client, db):
    """The deterministic mock remains available for tests — as an explicit opt-in."""
    submission = await _submission(client, files={"files": ("s.png", png_bytes(700, 900, "Q1. hi"), "image/png")})
    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()
    row = await _row(db, submission["id"])
    assert row.status == SubmissionStatus.READY_FOR_REVIEW
    ocr_rows = (await db.execute(select(OCRResult))).scalars().all()
    assert all(r.is_mock for r in ocr_rows)  # clearly marked, never passed off as real

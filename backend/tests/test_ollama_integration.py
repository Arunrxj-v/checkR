"""Real inference smoke test — exercises actual Ollama + ``gemma3:4b``.

The test generates a handwritten answer sheet (macOS handwriting font), runs
the real pipeline (OCR -> segmentation -> evaluation) against the local Ollama
server, and then walks the teacher through accept/override so provenance and
score separation are verified against genuine model output.

It is skipped automatically when Ollama is unreachable or the model is not
installed, so the normal suite stays offline and fast. Force-skip with::

    CHECKR_SKIP_OLLAMA_TESTS=1 pytest tests/test_ollama_integration.py

Run it explicitly (and print the model's output) with::

    pytest tests/test_ollama_integration.py -q -s
"""

from __future__ import annotations

import io
import os
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.ollama import OllamaProvider
from app.core.config import settings
from app.db.enums import SubmissionStatus
from app.models.answer import Answer, AnswerRegion, OCRResult
from app.models.evaluation import Evaluation
from app.models.submission import Submission
from app.services import evaluation_service, processing_service
from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    register_and_login,
)
from tests.test_pipeline import _run_pipeline, _upload


# --------------------------------------------------------------------------- #
# Skip logic: only run when a real local runtime is present
# --------------------------------------------------------------------------- #
def _runtime_ready() -> tuple[bool, str]:
    if os.environ.get("CHECKR_SKIP_OLLAMA_TESTS") == "1":
        return False, "CHECKR_SKIP_OLLAMA_TESTS=1"
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        resp.raise_for_status()
        names = [str(m.get("name", "")) for m in resp.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001 - any transport problem means "skip"
        return False, f"Ollama not reachable at {settings.ollama_base_url}: {exc}"
    model = settings.ollama_model
    if model not in names and f"{model}:latest" not in names:
        return False, f"{model} is not installed (run: ollama pull {model})"
    return True, ""


READY, SKIP_REASON = _runtime_ready()

pytestmark = pytest.mark.skipif(not READY, reason=SKIP_REASON or "Ollama unavailable")


# --------------------------------------------------------------------------- #
# Handwritten sample
# --------------------------------------------------------------------------- #
FONT_PATH = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"

SAMPLE_LINES = [
    "Q1. The three way handshake works like this:",
    "the client sends SYN, the server replies SYN-ACK,",
    "and the client sends ACK to establish the connection.",
    "Q2. A /26 has 64 addresses so 62 usable hosts.",
]


def handwritten_png() -> bytes:
    """Render the sample answers in a handwriting font on a white 'scan'."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1100, 560), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 40)
    y = 50
    for line in SAMPLE_LINES:
        draw.text((50, y), line, fill=(15, 15, 40), font=font)
        y += 90
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def live_provider():
    """A real Ollama provider wired into both pipeline stages."""
    if not READY:
        pytest.skip(SKIP_REASON or "Ollama unavailable")
    provider = OllamaProvider(max_retries=1)
    processing_get = processing_service.get_provider
    evaluation_get = evaluation_service.get_provider
    processing_service.get_provider = lambda: provider
    evaluation_service.get_provider = lambda: provider
    try:
        yield provider
    finally:
        processing_service.get_provider = processing_get
        evaluation_service.get_provider = evaluation_get
        await provider.aclose()


async def _submit(client, headers, exam_id) -> dict:
    return await _upload(
        client,
        headers,
        exam_id,
        files={"files": ("handwritten.png", handwritten_png(), "image/png")},
        data={"student_name": "Real Model Student", "student_roll": "2026-CS-REAL"},
    )


# --------------------------------------------------------------------------- #
# The test
# --------------------------------------------------------------------------- #
async def test_real_ocr_evaluation_and_teacher_review(client, db, live_provider):
    auth = await register_and_login(client)
    headers = auth_header(auth["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _submit(client, headers, exam["id"])
    submission_id = uuid.UUID(submission["id"])

    # --- Stage 1-3: real OCR, real segmentation, real evaluation ------------ #
    await _run_pipeline(db, submission_id)
    await db.commit()

    # --- OCR provenance: a genuine model result, never a mock --------------- #
    ocr = (await db.execute(select(OCRResult))).scalars().one()
    assert ocr.is_mock is False
    assert ocr.provider == "ollama"
    assert ocr.model == settings.ollama_model
    assert ocr.prompt_version.startswith("handwriting_v")
    assert 0.0 <= float(ocr.confidence) <= 1.0
    print("\n=== REAL OCR (gemma3:4b) ===")
    print(ocr.text)

    # The handwriting must actually have been read (loose: vision models vary).
    haystack = ocr.text.lower()
    assert "handshake" in haystack or "syn" in haystack, f"OCR missed the answer: {ocr.text!r}"

    # --- Answers: transcribed with page/region links for the workspace ------ #
    answers = (
        await db.execute(
            select(Answer)
            .where(Answer.submission_id == submission_id)
            .options(selectinload(Answer.question))
            .order_by(Answer.order_index)
        )
    ).scalars().all()
    assert len(answers) == 2
    q1 = answers[0]
    assert q1.transcription and len(q1.transcription) > 10
    regions = (
        await db.execute(select(AnswerRegion).where(AnswerRegion.answer_id == q1.id))
    ).scalars().all()
    assert regions, "the workspace needs a page/region link for the answer"
    assert all(0.0 <= float(r.x0) < float(r.x1) <= 1.0 for r in regions)

    # --- Evaluation: real model output, validated and in range -------------- #
    evaluations = (
        await db.execute(
            select(Evaluation)
            .where(Evaluation.answer_id.in_([a.id for a in answers]))
            .options(selectinload(Evaluation.criteria))
        )
    ).scalars().all()
    assert len(evaluations) == 2
    for evaluation in evaluations:
        assert evaluation.is_mock is False
        assert evaluation.provider == "ollama"
        assert evaluation.model == settings.ollama_model
        assert evaluation.prompt_version
        assert evaluation.engine_version
        assert 0.0 <= float(evaluation.awarded_marks) <= float(evaluation.max_marks)
        # Either the output validated, or it was flagged for the teacher.
        assert evaluation.status.value in ("valid", "invalid")
        if evaluation.status.value == "invalid":
            flagged = (
                await db.execute(
                    select(Answer).where(Answer.id == evaluation.answer_id)
                )
            ).scalar_one()
            assert flagged.is_flagged is True

    print("\n=== REAL EVALUATION (gemma3:4b) ===")
    for evaluation in evaluations:
        print(
            f"{evaluation.awarded_marks}/{evaluation.max_marks} "
            f"confidence={evaluation.confidence} status={evaluation.status.value}"
        )
        print(f"reasoning: {evaluation.reasoning[:400]}")
        for criterion in evaluation.criteria:
            print(f"  - {criterion.name}: {criterion.awarded_marks}/{criterion.max_marks}")

    assert q1.ai_score is not None
    assert 0.0 <= float(q1.ai_score) <= float(q1.max_marks)

    # --- Submission reaches the teacher, not an auto-finalised result ------- #
    row = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one()
    assert row.status == SubmissionStatus.READY_FOR_REVIEW
    # Nothing is final until a human says so: the AI totals stay provisional.
    assert row.status != SubmissionStatus.COMPLETED
    assert float(row.ai_total_marks) > 0

    # --- Teacher accepts: final score follows the AI score ------------------ #
    ai_score = float(q1.ai_score)
    accepted = await client.put(
        f"/api/answers/{q1.id}/review",
        json={"action": "accepted", "comment": "Matches the marking scheme."},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["ai_score"] == ai_score
    assert body["final_score"] == ai_score

    # --- Teacher overrides: the AI score is preserved ----------------------- #
    override_value = round(min(float(q1.max_marks), ai_score + 1.0), 1)
    overridden = await client.put(
        f"/api/answers/{q1.id}/review",
        json={
            "action": "overridden",
            "teacher_score": override_value,
            "reason": "Extra credit for the clear explanation.",
        },
        headers=headers,
    )
    assert overridden.status_code == 200, overridden.text
    body = overridden.json()
    assert body["teacher_score"] == override_value
    assert body["final_score"] == override_value
    assert body["ai_score"] == ai_score  # never overwritten by the teacher

    # --- Audit trail ties it together --------------------------------------- #
    logs = await client.get("/api/audit-logs", headers=headers)
    actions = [item["action"] for item in logs.json()["items"]]
    assert "answer.evaluated" in actions
    assert any("answer.review" in a for a in actions)


async def test_real_model_reports_its_identity(client, live_provider):
    """The settings/health payload names the real local model for the UI."""
    health = await live_provider.health()
    assert health["provider"] == "ollama"
    assert health["model"] == settings.ollama_model
    assert health["is_mock"] is False
    assert health["ok"] is True
    assert health["display_name"].endswith("· Local")
    assert health["ocr_enabled"] is True
    assert health["evaluation_enabled"] is True
    print(f"\n=== MODEL IDENTITY ===\n{health['display_name']} ({health['model']})")

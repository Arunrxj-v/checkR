"""Evaluation safety: what the model says never becomes the mark unchecked.

Covers the invariant `0 <= awarded <= max`, criteria/total reconciliation,
low-confidence flagging, provider failure handling and provenance — the
teacher's decision is always the final one, and every AI result is labelled.
"""

from __future__ import annotations

import math
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.base import AIProviderError
from app.ai.types import AnswerEvaluationResult, CriterionOutcome, OCRPageResult
from app.ai.validation import validate_evaluation
from app.core.config import settings
from app.db.enums import AnswerStatus, EvaluationStatus
from app.models.answer import Answer
from app.models.evaluation import Evaluation
from app.models.exam import Question
from app.services import evaluation_service, processing_service
from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    png_bytes,
    register_and_login,
)
from tests.test_pipeline import _run_pipeline, _upload

#: Q1's marking scheme in the shared fixture: five criteria of one mark each.
Q1_MAX = 5.0
Q1_CRITERIA = ["SYN packet", "SYN-ACK packet", "ACK packet", "Correct sequence", "Purpose or explanation"]

#: A clean, confident transcription — the state a successful real OCR pass
#: produces. The tests below are about *evaluation* safety, so the fixture
#: must not start out flagged/uncertain.
FIXTURE_TEXT = (
    "Q1. TCP is connection oriented; the three-way handshake is SYN, SYN-ACK, ACK.\n"
    "Q2. A /26 has 64 addresses, so 62 usable hosts."
)

FIXTURE_ANSWERS = [
    {
        "question_number": "1",
        "transcription": "TCP is connection oriented; the three-way handshake is SYN, SYN-ACK, ACK.",
        "regions": [{"x0": 0.1, "y0": 0.15, "x1": 0.9, "y1": 0.4}],
        "uncertain_segments": [],
        "confidence": 0.93,
        "started_on_previous_page": False,
        "continues_on_next_page": False,
    },
    {
        "question_number": "2",
        "transcription": "A /26 has 64 addresses, so 62 usable hosts.",
        "regions": [{"x0": 0.1, "y0": 0.45, "x1": 0.9, "y1": 0.7}],
        "uncertain_segments": [],
        "confidence": 0.91,
        "started_on_previous_page": False,
        "continues_on_next_page": False,
    },
]


def default_result(context) -> AnswerEvaluationResult:
    """Full marks, built from the question's own scheme (valid for any question)."""
    return AnswerEvaluationResult(
        awarded_marks=context.max_marks,
        max_marks=context.max_marks,
        confidence=0.93,
        reasoning="Every marking criterion is satisfied by the student's answer.",
        criteria=[
            CriterionOutcome(
                name=c["name"],
                max_marks=float(c["max_marks"]),
                awarded_marks=float(c["max_marks"]),
                satisfied=True,
                comment="Clearly addressed.",
            )
            for c in context.criteria
        ],
        provider="ollama",
        model="gemma3:4b",
        prompt_version="evaluation_v1",
        is_mock=False,
        raw={"awarded_marks": context.max_marks},
    )


class FixtureProvider:
    """Offline stand-in for Ollama: structured OCR + scripted evaluations.

    Used only to build fixture state (unit tests may mock the HTTP layer);
    production paths are covered by the Ollama provider itself.
    """

    name = "ollama"
    model = "gemma3:4b"
    is_mock = False

    def __init__(self, factory=None):
        self.factory = factory or default_result
        self.contexts: list[tuple[object, str]] = []

    async def require_available(self) -> None:
        return None

    async def transcribe_page(
        self, image_bytes, *, page_number, prompt_version="", previous_context=None
    ) -> OCRPageResult:
        detected = [dict(entry) for entry in FIXTURE_ANSWERS]
        return OCRPageResult(
            text=FIXTURE_TEXT,
            confidence=0.93,
            regions=[
                {"text": line, "x0": 0.1, "y0": 0.1 + i * 0.2, "x1": 0.9, "y1": 0.3 + i * 0.2}
                for i, line in enumerate(FIXTURE_TEXT.splitlines())
            ],
            raw={"detected_answers": detected, "manual_review_required": False},
            provider=self.name,
            model=self.model,
            prompt_version=prompt_version,
            is_mock=False,
            detected_answers=detected,
            manual_review_required=False,
        )

    async def evaluate_answer(self, context, *, prompt_version):
        self.contexts.append((context, prompt_version))
        return self.factory(context)

    async def health(self) -> dict:
        return {}

    async def aclose(self) -> None:
        return None


class ScriptedProvider:
    """Returns a canned evaluation (or raises) — the shape Ollama would return."""

    name = "ollama"
    model = "gemma3:4b"
    is_mock = False

    def __init__(self, result: AnswerEvaluationResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.contexts: list[tuple[object, str]] = []

    async def evaluate_answer(self, context, *, prompt_version):
        self.contexts.append((context, prompt_version))
        if self.error is not None:
            raise self.error
        return self.result

    async def health(self) -> dict:
        return {}

    async def aclose(self) -> None:
        return None


def make_result(
    *,
    awarded: float,
    confidence: float = 0.9,
    reasoning: str = "The answer matches the marking scheme step by step.",
    per_criterion: list[float] | None = None,
    flags: list[str] | None = None,
    contradictions: list[str] | None = None,
    include_criteria: bool = True,
    max_marks: float = Q1_MAX,
) -> AnswerEvaluationResult:
    criteria: list[CriterionOutcome] = []
    if include_criteria:
        values = per_criterion if per_criterion is not None else []
        if not values:
            # Distribute the awarded total across the scheme for convenience.
            values = [awarded / len(Q1_CRITERIA)] * len(Q1_CRITERIA)
        criteria = [
            CriterionOutcome(
                name=name,
                max_marks=1.0,
                awarded_marks=float(value),
                satisfied=value > 0,
                comment=None,
            )
            for name, value in zip(Q1_CRITERIA, values, strict=False)
        ]
    return AnswerEvaluationResult(
        awarded_marks=awarded,
        max_marks=max_marks,
        confidence=confidence,
        reasoning=reasoning,
        criteria=criteria,
        flags=list(flags or []),
        contradictions=list(contradictions or []),
        provider="ollama",
        model="gemma3:4b",
        prompt_version="evaluation_v1",
        is_mock=False,
        raw={"awarded_marks": awarded},
    )


async def _answers(client, db) -> tuple[dict, list[Answer]]:
    """Run the full pipeline with the fixture provider and return its answers."""
    auth = await register_and_login(client)
    headers = auth_header(auth["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={"files": ("s.png", png_bytes(700, 900, FIXTURE_TEXT), "image/png")},
    )
    provider = FixtureProvider()
    # Both stages resolve their provider through their own module namespace.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(processing_service, "get_provider", lambda: provider)
    monkey.setattr(evaluation_service, "get_provider", lambda: provider)
    try:
        await _run_pipeline(db, uuid.UUID(submission["id"]))
        await db.commit()
    finally:
        monkey.undo()

    answers = (
        await db.execute(
            select(Answer)
            .where(Answer.submission_id == uuid.UUID(submission["id"]))
            .options(selectinload(Answer.question).selectinload(Question.criteria))
            .order_by(Answer.order_index)
        )
    ).scalars().all()
    # Sanity: the fixture must start from a clean, confident state.
    assert all(a.transcription for a in answers)
    assert all(not a.is_handwriting_uncertain for a in answers)
    assert all(not a.is_flagged for a in answers)
    return submission, answers


async def _reevaluate(db, answer, provider, *, force=True) -> Evaluation | None:
    result = await evaluation_service.evaluate_answer(
        db, answer=answer, question=answer.question, force=force, provider=provider
    )
    await db.commit()
    if result is None:
        return None
    # Re-fetch with the criteria eagerly loaded (lazy IO is not allowed here).
    return (
        await db.execute(
            select(Evaluation)
            .where(Evaluation.id == result.id)
            .options(selectinload(Evaluation.criteria))
        )
    ).scalar_one()


async def _evaluations(db, answer_id) -> list[Evaluation]:
    return list(
        (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.answer_id == answer_id)
                .order_by(Evaluation.created_at)
            )
        ).scalars().all()
    )


# --------------------------------------------------------------------------- #
# Marks stay inside the marking scheme
# --------------------------------------------------------------------------- #
async def test_full_marks_are_recorded_as_valid(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=Q1_MAX, per_criterion=[1.0] * len(Q1_CRITERIA))
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert evaluation is not None
    assert evaluation.status == EvaluationStatus.VALID
    assert float(evaluation.awarded_marks) == Q1_MAX
    assert answer.ai_score == evaluation.awarded_marks
    assert answer.status == AnswerStatus.EVALUATED
    assert answer.is_flagged is False
    assert len(evaluation.criteria) == len(Q1_CRITERIA)


async def test_partial_marks_are_recorded_as_valid(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=3.0, per_criterion=[1.0, 1.0, 1.0, 0.0, 0.0])
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert float(evaluation.awarded_marks) == 3.0
    assert float(answer.ai_score) == 3.0
    assert evaluation.status == EvaluationStatus.VALID
    assert answer.is_flagged is False
    # Partial credit is visible criterion by criterion for the workspace.
    assert [float(c.awarded_marks) for c in evaluation.criteria] == [1.0, 1.0, 1.0, 0.0, 0.0]


async def test_zero_marks_are_a_valid_result_not_an_error(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(make_result(awarded=0.0, per_criterion=[0.0] * len(Q1_CRITERIA)))

    evaluation = await _reevaluate(db, answer, provider)

    assert float(evaluation.awarded_marks) == 0.0
    assert float(answer.ai_score) == 0.0
    assert evaluation.status == EvaluationStatus.VALID
    assert answer.is_flagged is False


async def test_marks_above_the_maximum_are_clamped_and_marked_invalid(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    # A model claiming 9/5 with no criterion breakdown cannot be trusted.
    provider = ScriptedProvider(
        make_result(awarded=9.0, include_criteria=False, reasoning="Generous.")
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert float(evaluation.awarded_marks) == Q1_MAX  # clamped, never over max
    assert evaluation.status == EvaluationStatus.INVALID
    assert any("exceeded the maximum" in note for note in evaluation.validation_notes)
    # An invalid result must reach the teacher flagged, not silently accepted.
    assert answer.is_flagged is True
    assert answer.status == AnswerStatus.FLAGGED


async def test_criterion_cannot_award_more_than_its_own_maximum(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=7.0, per_criterion=[3.0, 1.0, 1.0, 1.0, 1.0])
    )

    evaluation = await _reevaluate(db, answer, provider)

    first = evaluation.criteria[0]
    assert float(first.awarded_marks) == 1.0  # clamped to the criterion maximum
    assert any("exceeded its maximum" in note for note in evaluation.validation_notes)
    # The clamp repaired the total, so it stays inside the scheme — with a note.
    assert float(evaluation.awarded_marks) == Q1_MAX
    assert evaluation.status == EvaluationStatus.VALID
    assert evaluation.validation_notes


async def test_criteria_sum_wins_over_an_inconsistent_total(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=5.0, per_criterion=[1.0, 1.0, 1.0, 0.0, 0.0])  # says 5, sums to 3
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert float(evaluation.awarded_marks) == 3.0
    assert any("did not match the sum of criteria" in note for note in evaluation.validation_notes)
    # The stored total always equals the sum of its criteria.
    assert abs(
        sum(float(c.awarded_marks) for c in evaluation.criteria) - float(evaluation.awarded_marks)
    ) < 0.01


async def test_negative_marks_are_clamped_to_zero(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=-2.0, per_criterion=[-1.0, -0.5, 0.0, 0.0, 0.0])
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert float(evaluation.awarded_marks) == 0.0
    assert all(float(c.awarded_marks) >= 0 for c in evaluation.criteria)
    assert any("negative" in note.lower() for note in evaluation.validation_notes)


# --------------------------------------------------------------------------- #
# Confidence, flags and human review
# --------------------------------------------------------------------------- #
async def test_low_confidence_is_flagged_for_teacher_review(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=3.0, confidence=0.3, per_criterion=[1.0, 1.0, 1.0, 0.0, 0.0])
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert evaluation.confidence == 0.3
    assert evaluation.confidence_level.value in ("low", "medium")
    assert answer.is_flagged is True
    assert "Low AI confidence" in (answer.flag_reason or "")
    assert answer.status == AnswerStatus.FLAGGED


async def test_model_flags_reach_the_teacher(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(
            awarded=3.0,
            per_criterion=[1.0, 1.0, 1.0, 0.0, 0.0],
            flags=["The transcription looks incomplete."],
        )
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert "The transcription looks incomplete." in evaluation.flags
    assert answer.is_flagged is True
    assert "incomplete" in (answer.flag_reason or "")


async def test_missing_reasoning_makes_the_evaluation_invalid(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(
        make_result(awarded=3.0, reasoning="", per_criterion=[1.0, 1.0, 1.0, 0.0, 0.0])
    )

    evaluation = await _reevaluate(db, answer, provider)

    assert evaluation.status == EvaluationStatus.INVALID
    assert answer.is_flagged is True


# --------------------------------------------------------------------------- #
# Provider failures produce no result at all
# --------------------------------------------------------------------------- #
async def test_provider_failure_marks_the_answer_failed_without_an_evaluation(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    before = await _evaluations(db, answer.id)
    provider = ScriptedProvider(
        error=AIProviderError(
            "Ollama returned unusable output after 2 attempts.",
            retryable=True,
            kind="bad_response",
        )
    )

    result = await _reevaluate(db, answer, provider)

    assert result is None
    assert answer.status == AnswerStatus.FAILED
    assert "unusable output" in (answer.error_message or "")
    # No evaluation row was written and the previous one was not superseded.
    after = await _evaluations(db, answer.id)
    assert len(after) == len(before)
    assert all(e.status == EvaluationStatus.VALID for e in after)


async def test_evaluation_is_skipped_for_a_reviewed_answer(client, db):
    """A teacher's decision is never silently overwritten by a re-run."""
    _, answers = await _answers(client, db)
    answer = answers[0]
    answer.status = AnswerStatus.REVIEWED
    answer.is_reviewed = True
    await db.commit()
    provider = ScriptedProvider(make_result(awarded=1.0, per_criterion=[1.0, 0, 0, 0, 0]))

    result = await evaluation_service.evaluate_answer(
        db, answer=answer, question=answer.question, force=False, provider=provider
    )
    await db.commit()

    assert result is None
    assert float(answer.ai_score) != 1.0  # untouched
    assert not provider.contexts  # the provider was never even called


async def test_disabled_evaluation_is_refused_before_calling_the_provider(client, db, monkeypatch):
    _, answers = await _answers(client, db)
    monkeypatch.setattr(settings, "evaluation_enabled", False)

    with pytest.raises(evaluation_service.EvaluationError, match="EVALUATION_ENABLED"):
        await evaluation_service.evaluate_answer(
            db, answer=answers[0], question=answers[0].question, force=True, provider=None
        )


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
async def test_evaluation_records_model_provenance_and_audit(client, db):
    _, answers = await _answers(client, db)
    answer = answers[0]
    provider = ScriptedProvider(make_result(awarded=4.0, per_criterion=[1.0, 1.0, 1.0, 1.0, 0.0]))

    evaluation = await _reevaluate(db, answer, provider)

    assert evaluation.provider == "ollama"
    assert evaluation.model == "gemma3:4b"
    assert evaluation.model_version == "gemma3:4b"
    assert evaluation.prompt_version
    assert evaluation.engine_version
    assert evaluation.is_mock is False
    # The prompt actually received the transcription and the original images.
    context, prompt_version = provider.contexts[0]
    assert "SYN" in context.transcription
    assert context.images  # original page image travels with the prompt
    assert prompt_version

    from app.models.audit import AuditLog

    rows = (await db.execute(select(AuditLog).where(AuditLog.entity_id == answer.id))).scalars().all()
    actions = {r.action for r in rows}
    assert "answer.evaluated" in actions
    evaluated = next(r for r in rows if r.action == "answer.evaluated")
    assert evaluated.new_value["provider"] == "ollama"
    assert evaluated.new_value["is_mock"] is False


# --------------------------------------------------------------------------- #
# Pure validation rules (no database)
# --------------------------------------------------------------------------- #
def test_validation_clamps_confidence_into_range():
    hot = validate_evaluation(make_result(awarded=3.0, confidence=1.7), max_marks=5.0)
    assert hot.result.confidence == 1.0

    nan = validate_evaluation(make_result(awarded=3.0, confidence=float("nan")), max_marks=5.0)
    assert nan.result.confidence == 0.0
    assert nan.needs_review is True


def test_validation_requires_reasoning():
    missing = validate_evaluation(make_result(awarded=3.0, reasoning="  "), max_marks=5.0)
    assert missing.is_valid is False
    assert missing.needs_review is True


def test_validation_never_exceeds_the_maximum():
    over = validate_evaluation(
        make_result(awarded=12.0, include_criteria=False), max_marks=5.0
    )
    assert over.result.awarded_marks <= 5.0
    assert over.is_valid is False


def test_confidence_level_uses_configured_thresholds():
    low = validate_evaluation(make_result(awarded=3.0, confidence=0.2), max_marks=5.0)
    assert low.needs_review is True
    assert math.isclose(low.result.confidence, 0.2)

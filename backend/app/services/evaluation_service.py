"""The evaluation engine.

Ties together: the answer + question + marking scheme, the provider abstraction,
the versioned prompts, output validation, and persistence.

The original answer image(s) are always passed to the model alongside the OCR
text — text alone is never trusted. Every evaluation records its provenance so
it can be reproduced or deliberately re-run.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.base import AIProviderError
from app.ai.factory import get_provider
from app.ai.types import EvaluationContext
from app.ai.validation import level_for, validate_evaluation
from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import AnswerStatus, EvaluationStatus
from app.models.answer import Answer, AnswerRegion
from app.models.evaluation import Evaluation, EvaluationCriterion
from app.models.exam import Question
from app.models.submission import Submission, SubmissionPage
from app.models.user import User
from app.prompts.registry import (
    CURRENT_ENGINE_VERSION,
    build_evaluation_prompt,
)
from app.services import audit_service
from app.storage import get_storage

logger = get_logger(__name__)


class EvaluationError(Exception):
    """Raised when an answer cannot be evaluated."""


def build_context(
    answer: Answer,
    question: Question,
    *,
    page_numbers: list[int],
    images: list[bytes],
) -> EvaluationContext:
    return EvaluationContext(
        question_label=question.label,
        question_text=question.text,
        question_type=question.question_type.value,
        max_marks=float(question.max_marks),
        expected_answer=question.expected_answer,
        guidance=question.guidance,
        keywords=list(question.keywords or []),
        criteria=[
            {
                "name": c.name,
                "description": c.description,
                "max_marks": float(c.max_marks),
            }
            for c in question.criteria
        ],
        transcription=answer.transcription or "",
        ocr_confidence=answer.ocr_confidence,
        images=images,
        submission_ref=answer.submission_id.hex[:8],
    )


async def load_answer_images(
    db: AsyncSession, answer_id: uuid.UUID, *, max_images: int = 6
) -> tuple[list[bytes], list[int]]:
    """Read the processed page images covering an answer's regions.

    Returns ``(images, page_numbers)``. Media is streamed from storage and kept
    bounded so a long continuation answer cannot exhaust memory.
    """
    region_rows = (
        (
            await db.execute(
                select(AnswerRegion)
                .where(AnswerRegion.answer_id == answer_id)
                .order_by(AnswerRegion.y0)
            )
        )
        .scalars()
        .all()
    )
    page_ids: list[uuid.UUID] = []
    for region in region_rows:
        if region.page_id not in page_ids:
            page_ids.append(region.page_id)

    if not page_ids:
        return [], []

    pages = (
        (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.id.in_(page_ids))
                .order_by(SubmissionPage.page_number)
            )
        )
        .scalars()
        .all()
    )

    storage = get_storage()
    images: list[bytes] = []
    numbers: list[int] = []
    for page in pages[:max_images]:
        key = page.processed_storage_key or page.original_storage_key
        if not key:
            continue
        try:
            images.append(await storage.read(key))
            numbers.append(page.page_number)
        except Exception as exc:  # a missing derivative must not abort the run
            logger.warning("Could not read page %s image: %s", page.page_number, exc)
    return images, numbers


async def _supersede_previous(db: AsyncSession, answer_id: uuid.UUID) -> None:
    previous = (
        (
            await db.execute(
                select(Evaluation).where(
                    Evaluation.answer_id == answer_id,
                    Evaluation.status == EvaluationStatus.VALID,
                )
            )
        )
        .scalars()
        .all()
    )
    for evaluation in previous:
        evaluation.status = EvaluationStatus.SUPERSEDED


async def evaluate_answer(
    db: AsyncSession,
    *,
    answer: Answer,
    question: Question,
    force: bool = False,
    actor=None,
) -> Evaluation | None:
    """Evaluate a single answer and persist the result.

    Returns ``None`` (after marking the answer failed) if the provider could not
    produce a usable result — the caller/worker decides whether to retry.
    """
    if answer.status == AnswerStatus.EVALUATED and not force:
        return None
    if answer.status == AnswerStatus.REVIEWED and not force:
        # A human already decided; never silently overwrite their work.
        return None

    if actor is None:
        # Worker-initiated evaluations act on behalf of the teacher who owns the
        # submission, so the audit trail stays attributable to a person.
        owner_id = (
            await db.execute(
                select(Submission.created_by_id).where(Submission.id == answer.submission_id)
            )
        ).scalar_one_or_none()
        if owner_id is not None:
            actor = (
                await db.execute(select(User).where(User.id == owner_id))
            ).scalar_one_or_none()

    # Ensure the marking scheme is loaded.
    if "criteria" not in question.__dict__ or question.criteria is None:
        question = (
            await db.execute(
                select(Question)
                .where(Question.id == question.id)
                .options(selectinload(Question.criteria))
            )
        ).scalar_one()

    images, page_numbers = await load_answer_images(db, answer.id)
    context = build_context(answer, question, page_numbers=page_numbers, images=images)
    _, _, prompt_version = build_evaluation_prompt(context)

    provider = get_provider()
    answer.status = AnswerStatus.EVALUATING
    await db.flush()

    try:
        result = await provider.evaluate_answer(context, prompt_version=prompt_version)
    except AIProviderError as exc:
        answer.status = AnswerStatus.FAILED
        answer.error_message = str(exc)
        await db.flush()
        logger.warning("Evaluation failed for answer %s: %s", answer.id, exc)
        if not exc.retryable:
            await audit_service.record(
                db,
                action="answer.evaluation_failed",
                entity_type="answer",
                entity_id=answer.id,
                description=f"AI provider error: {exc}",
            )
        return None
    except Exception as exc:  # unexpected provider bug
        answer.status = AnswerStatus.FAILED
        answer.error_message = f"Unexpected evaluation error: {exc}"
        await db.flush()
        logger.exception("Unexpected evaluation error for answer %s", answer.id)
        return None

    validation = validate_evaluation(
        result,
        max_marks=float(question.max_marks),
        criteria_scheme=context.criteria,
    )
    sanitized = validation.result
    level = level_for(sanitized.confidence)

    await _supersede_previous(db, answer.id)

    evaluation = Evaluation(
        answer_id=answer.id,
        provider=sanitized.provider,
        model=sanitized.model,
        model_version=getattr(provider, "model", None),
        prompt_version=sanitized.prompt_version or prompt_version,
        engine_version=CURRENT_ENGINE_VERSION,
        is_mock=sanitized.is_mock,
        status=EvaluationStatus.VALID if validation.is_valid else EvaluationStatus.INVALID,
        awarded_marks=Decimal(str(sanitized.awarded_marks)),
        max_marks=Decimal(str(sanitized.max_marks)),
        confidence=sanitized.confidence,
        confidence_level=level,
        reasoning=sanitized.reasoning,
        strengths=sanitized.strengths,
        gaps=sanitized.gaps,
        contradictions=sanitized.contradictions,
        flags=sanitized.flags,
        raw_response=sanitized.raw if isinstance(sanitized.raw, dict) else {},
        validation_notes=validation.notes,
    )
    db.add(evaluation)
    await db.flush()

    for index, criterion in enumerate(sanitized.criteria):
        db.add(
            EvaluationCriterion(
                evaluation_id=evaluation.id,
                name=criterion.name,
                max_marks=Decimal(str(criterion.max_marks)),
                awarded_marks=Decimal(str(criterion.awarded_marks)),
                satisfied=criterion.satisfied,
                comment=criterion.comment,
                order_index=index,
            )
        )

    # Update the answer's provisional AI result (teacher fields untouched).
    answer.ai_score = Decimal(str(sanitized.awarded_marks))
    answer.max_marks = Decimal(str(question.max_marks))
    answer.ai_confidence = sanitized.confidence
    answer.ai_confidence_level = level
    answer.status = AnswerStatus.EVALUATED
    answer.error_message = None

    should_flag = (
        not validation.is_valid
        or sanitized.confidence < settings.ai_confidence_medium
        or bool(sanitized.contradictions)
        or bool(sanitized.flags)
        or answer.is_handwriting_uncertain
    )
    answer.is_flagged = should_flag
    if should_flag:
        reasons = list(sanitized.flags)
        if sanitized.confidence < settings.ai_confidence_medium:
            reasons.insert(0, f"Low AI confidence ({sanitized.confidence:.0%}).")
        if answer.is_handwriting_uncertain:
            reasons.insert(0, "Handwriting could not be read confidently.")
        reason_text = " ".join(r for r in reasons if r).strip()
        answer.flag_reason = reason_text[:1000] if reason_text else "Flagged for manual review."
        if answer.status == AnswerStatus.EVALUATED:
            answer.status = AnswerStatus.FLAGGED

    await db.flush()
    await audit_service.record(
        db,
        action="answer.evaluated",
        entity_type="answer",
        actor=actor,
        entity_id=answer.id,
        description=(
            f"{'Mock' if sanitized.is_mock else 'AI'} evaluation: "
            f"{sanitized.awarded_marks:g}/{float(question.max_marks):g} "
            f"({sanitized.confidence:.0%} confidence)."
        ),
        new_value={
            "awarded_marks": sanitized.awarded_marks,
            "max_marks": float(question.max_marks),
            "confidence": sanitized.confidence,
            "provider": sanitized.provider,
            "model": sanitized.model,
            "prompt_version": evaluation.prompt_version,
            "is_mock": sanitized.is_mock,
        },
    )
    return evaluation


async def latest_evaluation(db: AsyncSession, answer_id: uuid.UUID) -> Evaluation | None:
    return (
        await db.execute(
            select(Evaluation)
            .where(Evaluation.answer_id == answer_id)
            .options(selectinload(Evaluation.criteria))
            .order_by(Evaluation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def evaluation_history(db: AsyncSession, answer_id: uuid.UUID) -> list[Evaluation]:
    return list(
        (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.answer_id == answer_id)
                .options(selectinload(Evaluation.criteria))
                .order_by(Evaluation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

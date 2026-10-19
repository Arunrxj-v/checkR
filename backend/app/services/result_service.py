"""Result aggregation and finalisation.

A submission's totals are recomputed from its answers whenever anything changes.
Teacher scores take precedence over AI scores; the AI totals are retained
separately so both are always visible.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import AnswerStatus, SubmissionStatus
from app.models.answer import Answer
from app.models.submission import Submission
from app.models.user import User
from app.services import audit_service


class ResultError(Exception):
    """Raised when a result cannot be produced (e.g. nothing evaluated yet)."""


async def recompute_submission_totals(db: AsyncSession, submission: Submission) -> Submission:
    answers = list(
        (
            await db.execute(
                select(Answer)
                .where(Answer.submission_id == submission.id)
                .options(selectinload(Answer.question))
            )
        )
        .scalars()
        .all()
    )

    max_total = sum((Decimal(str(a.question.max_marks)) for a in answers), Decimal("0"))
    ai_total = sum((a.ai_score or Decimal("0") for a in answers), Decimal("0"))
    final_total = sum(
        (
            a.final_score if a.final_score is not None else (a.ai_score or Decimal("0"))
            for a in answers
        ),
        Decimal("0"),
    )
    confidences = [a.ai_confidence for a in answers if a.ai_confidence is not None]
    flagged = sum(1 for a in answers if a.is_flagged)

    submission.max_total_marks = max_total
    submission.ai_total_marks = ai_total
    submission.final_total_marks = final_total
    submission.ai_confidence = (
        round(sum(confidences) / len(confidences), 3) if confidences else None
    )
    submission.flagged_count = flagged

    # RFL0 - review-derived status transitions.
    if answers:
        all_reviewed = all(a.is_reviewed for a in answers)
        any_evaluated = any(a.ai_score is not None for a in answers)
        if all_reviewed and submission.status in (
            SubmissionStatus.READY_FOR_REVIEW,
            SubmissionStatus.REVIEWED,
        ):
            submission.status = SubmissionStatus.REVIEWED
        elif any_evaluated and submission.status in (
            SubmissionStatus.ANSWERS_DETECTED,
            SubmissionStatus.AI_EVALUATING,
            SubmissionStatus.PROCESSING,
            SubmissionStatus.OCR_PROCESSING,
        ):
            submission.status = SubmissionStatus.READY_FOR_REVIEW

    await db.flush()
    return submission


async def build_result(db: AsyncSession, submission: Submission) -> dict:
    """Row-by-row result for a submission (question-wise marks + totals)."""
    answers = list(
        (
            await db.execute(
                select(Answer)
                .where(Answer.submission_id == submission.id)
                .options(selectinload(Answer.question))
                .order_by(Answer.order_index)
            )
        )
        .scalars()
        .all()
    )

    rows = []
    for answer in answers:
        rows.append(
            {
                "answer_id": answer.id,
                "question_id": answer.question_id,
                "question_label": answer.question.label,
                "question_text": answer.question.text,
                "max_marks": float(answer.question.max_marks),
                "ai_score": float(answer.ai_score) if answer.ai_score is not None else None,
                "teacher_score": (
                    float(answer.teacher_score) if answer.teacher_score is not None else None
                ),
                "final_score": (
                    float(answer.final_score) if answer.final_score is not None else None
                ),
                "ai_confidence": answer.ai_confidence,
                "is_reviewed": answer.is_reviewed,
                "is_flagged": answer.is_flagged,
                "status": answer.status,
            }
        )

    max_total = float(submission.max_total_marks or 0)
    final_total = float(submission.final_total_marks or 0)
    percentage = round(final_total / max_total * 100, 2) if max_total else None

    return {
        "submission_id": submission.id,
        "exam_id": submission.exam_id,
        "student_name": submission.student_name,
        "student_roll": submission.student_roll,
        "status": submission.status.value,
        "max_total_marks": max_total,
        "ai_total_marks": float(submission.ai_total_marks or 0),
        "final_total_marks": final_total,
        "percentage": percentage,
        "reviewed_count": sum(1 for a in answers if a.is_reviewed),
        "flagged_count": sum(1 for a in answers if a.is_flagged),
        "total_answers": len(answers),
        "rows": rows,
        "generated_at": dt.datetime.now(dt.UTC),
    }


async def finalize_submission(
    db: AsyncSession, *, submission: Submission, actor: User
) -> Submission:
    answers = list(
        (
            await db.execute(select(Answer).where(Answer.submission_id == submission.id))
        )
        .scalars()
        .all()
    )
    if not answers:
        raise ResultError("This submission has no answers to finalise.")
    if not any(a.ai_score is not None or a.final_score is not None for a in answers):
        raise ResultError("No evaluations are available yet. Process and evaluate first.")

    unreviewed = [a for a in answers if not a.is_reviewed]
    if unreviewed:
        raise ResultError(
            f"{len(unreviewed)} answer(s) still need a teacher decision before "
            "the result can be finalised."
        )

    await recompute_submission_totals(db, submission)
    old_status = submission.status
    submission.status = SubmissionStatus.COMPLETED
    await db.flush()

    await audit_service.record(
        db,
        action="submission.finalized",
        entity_type="submission",
        actor=actor,
        entity_id=submission.id,
        description=(
            f"Finalised result: {float(submission.final_total_marks):g}/"
            f"{float(submission.max_total_marks):g}."
        ),
        old_value={"status": old_status.value},
        new_value={
            "status": submission.status.value,
            "final_total_marks": float(submission.final_total_marks),
            "max_total_marks": float(submission.max_total_marks),
        },
    )
    return submission


async def reopen_submission(
    db: AsyncSession, *, submission: Submission, actor: User
) -> Submission:
    """Allow a finalised result to be corrected."""
    old_status = submission.status
    submission.status = SubmissionStatus.REVIEWED
    await db.flush()
    await audit_service.record(
        db,
        action="submission.reopened",
        entity_type="submission",
        actor=actor,
        entity_id=submission.id,
        description="Reopened a finalised submission for correction.",
        old_value={"status": old_status.value},
        new_value={"status": submission.status.value},
    )
    return submission


async def exam_result_overview(db: AsyncSession, exam_id: uuid.UUID) -> dict:
    """Aggregate results across every submission of an exam."""
    submissions = list(
        (
            await db.execute(
                select(Submission)
                .where(Submission.exam_id == exam_id)
                .order_by(Submission.student_roll.asc().nulls_last(), Submission.created_at)
            )
        )
        .scalars()
        .all()
    )

    rows = []
    percentages = []
    for submission in submissions:
        max_total = float(submission.max_total_marks or 0)
        final_total = float(submission.final_total_marks or 0)
        pct = round(final_total / max_total * 100, 2) if max_total else None
        if pct is not None and submission.status == SubmissionStatus.COMPLETED:
            percentages.append(pct)
        rows.append(
            {
                "submission_id": submission.id,
                "student_name": submission.student_name,
                "student_roll": submission.student_roll,
                "status": submission.status.value,
                "max_total_marks": max_total,
                "ai_total_marks": float(submission.ai_total_marks or 0),
                "final_total_marks": final_total,
                "percentage": pct,
                "flagged_count": submission.flagged_count,
            }
        )

    return {
        "exam_id": exam_id,
        "submission_count": len(submissions),
        "completed_count": sum(1 for s in submissions if s.status == SubmissionStatus.COMPLETED),
        "average_percentage": round(sum(percentages) / len(percentages), 2) if percentages else None,
        "highest_percentage": max(percentages) if percentages else None,
        "lowest_percentage": min(percentages) if percentages else None,
        "rows": rows,
    }


async def answer_progress(db: AsyncSession, submission_id: uuid.UUID) -> dict:
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Answer).where(Answer.submission_id == submission_id)
            )
        ).scalar_one()
    )
    counts: dict[str, int] = {}
    for status in AnswerStatus:
        counts[status.value] = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Answer)
                    .where(Answer.submission_id == submission_id, Answer.status == status)
                )
            ).scalar_one()
        )
    return {"total": total, "by_status": counts}

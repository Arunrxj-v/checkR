"""Teacher review: accept, override and flag.

The AI score is never overwritten. A teacher decision is recorded both on the
answer (teacher_score / final_score) and as an immutable ``TeacherReview`` row,
plus an audit entry capturing the old and new values and the teacher's reason.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AnswerStatus, ReviewDecision
from app.models.answer import Answer
from app.models.evaluation import TeacherReview
from app.models.exam import Question
from app.models.user import User
from app.schemas.answer import ReviewRequest
from app.services import audit_service, evaluation_service


class ReviewError(Exception):
    """Raised when a review action is invalid."""


async def _question(db: AsyncSession, question_id) -> Question:
    return (
        await db.execute(select(Question).where(Question.id == question_id))
    ).scalar_one()


async def review_answer(
    db: AsyncSession,
    *,
    answer: Answer,
    actor: User,
    data: ReviewRequest,
) -> Answer:
    question = await _question(db, answer.question_id)
    max_marks = float(question.max_marks)
    evaluation = await evaluation_service.latest_evaluation(db, answer.id)

    old_state = {
        "ai_score": float(answer.ai_score) if answer.ai_score is not None else None,
        "teacher_score": float(answer.teacher_score) if answer.teacher_score is not None else None,
        "final_score": float(answer.final_score) if answer.final_score is not None else None,
        "is_flagged": answer.is_flagged,
        "status": answer.status.value,
    }

    teacher_score: Decimal | None = None
    if data.action == ReviewDecision.OVERRIDDEN:
        if data.teacher_score is None:
            raise ReviewError("A mark is required when overriding.")
        if data.teacher_score < 0 or data.teacher_score > max_marks:
            raise ReviewError(
                f"The mark must be between 0 and {max_marks:g} for {question.label}."
            )
        teacher_score = Decimal(str(round(float(data.teacher_score), 2)))
    elif data.action == ReviewDecision.ACCEPTED:
        if answer.ai_score is None:
            raise ReviewError(
                "There is no AI suggestion to accept for this answer; enter a mark instead."
            )
        teacher_score = Decimal(str(answer.ai_score))

    # Apply the decision.
    if data.action in (ReviewDecision.ACCEPTED, ReviewDecision.OVERRIDDEN):
        answer.teacher_score = teacher_score
        answer.final_score = teacher_score
        answer.is_reviewed = True
        answer.status = AnswerStatus.REVIEWED
        if data.action == ReviewDecision.ACCEPTED:
            answer.is_flagged = False
            answer.flag_reason = None
    elif data.action == ReviewDecision.FLAGGED:
        answer.is_flagged = True
        answer.flag_reason = data.reason or data.comment or "Flagged by examiner for review."
        if answer.is_reviewed:
            answer.status = AnswerStatus.REVIEWED
        else:
            answer.status = AnswerStatus.FLAGGED
    elif data.action == ReviewDecision.UNFLAGGED:
        answer.is_flagged = False
        answer.flag_reason = None
        if answer.is_reviewed:
            answer.status = AnswerStatus.REVIEWED
        elif answer.ai_score is not None:
            answer.status = AnswerStatus.EVALUATED

    if data.comment is not None:
        answer.teacher_comment = data.comment

    review = TeacherReview(
        answer_id=answer.id,
        evaluation_id=evaluation.id if evaluation else None,
        reviewer_id=actor.id,
        decision=data.action,
        ai_score=answer.ai_score,
        teacher_score=teacher_score if teacher_score is not None else answer.teacher_score,
        comment=data.comment,
        reason=data.reason,
    )
    db.add(review)
    await db.flush()

    await audit_service.record(
        db,
        action=f"answer.review.{data.action.value}",
        entity_type="answer",
        actor=actor,
        entity_id=answer.id,
        description=_describe(data, answer, old_state),
        old_value=old_state,
        new_value={
            "teacher_score": float(answer.teacher_score) if answer.teacher_score is not None else None,
            "final_score": float(answer.final_score) if answer.final_score is not None else None,
            "is_flagged": answer.is_flagged,
            "status": answer.status.value,
        },
        reason=data.reason,
    )
    return answer


def _describe(data: ReviewRequest, answer: Answer, old_state: dict) -> str:
    ai = old_state.get("ai_score")
    if data.action == ReviewDecision.ACCEPTED:
        return f"Accepted the AI suggestion of {ai:g}." if ai is not None else "Accepted."
    if data.action == ReviewDecision.OVERRIDDEN:
        return f"Overrode AI score {ai!r} with {data.teacher_score:g}."
    if data.action == ReviewDecision.FLAGGED:
        return "Flagged the answer for manual review."
    return "Cleared the review flag."


async def recent_reviews(db: AsyncSession, answer_id) -> list[TeacherReview]:
    return list(
        (
            await db.execute(
                select(TeacherReview)
                .where(TeacherReview.answer_id == answer_id)
                .order_by(TeacherReview.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

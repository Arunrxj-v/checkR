"""Exam, question and marking-scheme services."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import ExamStatus, SubmissionStatus
from app.models.answer import Answer
from app.models.exam import Exam, MarkingCriterion, Question
from app.models.submission import Submission
from app.models.user import User
from app.schemas.exam import ExamCreate, ExamUpdate, QuestionCreate, QuestionUpdate
from app.services import audit_service


class ExamError(Exception):
    """Domain error for exam operations."""


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def list_exams(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
    status: ExamStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Exam], int]:
    conditions = []
    if owner_id is not None:
        conditions.append(Exam.owner_id == owner_id)
    if status is not None:
        conditions.append(Exam.status == status)
    if search:
        like = f"%{search.strip().lower()}%"
        conditions.append(
            func.lower(Exam.title).like(like)
            | func.lower(Exam.subject).like(like)
            | func.lower(func.coalesce(Exam.subject_code, "")).like(like)
        )

    base = select(Exam)
    if conditions:
        base = base.where(*conditions)

    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        await db.execute(
            base.order_by(Exam.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_exam(
    db: AsyncSession, exam_id: uuid.UUID, *, with_questions: bool = True
) -> Exam | None:
    stmt = select(Exam).where(Exam.id == exam_id)
    if with_questions:
        stmt = stmt.options(selectinload(Exam.questions).selectinload(Question.criteria))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_question(
    db: AsyncSession, question_id: uuid.UUID
) -> Question | None:
    return (
        await db.execute(
            select(Question)
            .where(Question.id == question_id)
            .options(selectinload(Question.criteria))
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def _recompute_total(exam: Exam) -> None:
    exam.total_marks = sum(
        (Decimal(str(q.max_marks or 0)) for q in exam.questions), Decimal("0")
    )


async def create_exam(db: AsyncSession, *, owner: User, data: ExamCreate) -> Exam:
    exam = Exam(
        owner_id=owner.id,
        title=data.title.strip(),
        subject=data.subject.strip(),
        subject_code=data.subject_code,
        course=data.course,
        academic_year=data.academic_year,
        exam_date=data.exam_date,
        duration_minutes=data.duration_minutes,
        instructions=data.instructions,
        status=data.status,
    )
    db.add(exam)
    await db.flush()

    for index, q in enumerate(data.questions):
        await add_question(db, exam=exam, data=q, order_index=index)

    await db.refresh(exam, attribute_names=["questions"])
    _recompute_total(exam)
    await db.flush()
    await audit_service.record(
        db,
        action="exam.created",
        entity_type="exam",
        actor=owner,
        entity_id=exam.id,
        description=f"Created examination '{exam.title}' with {len(exam.questions)} question(s).",
        new_value={"title": exam.title, "total_marks": float(exam.total_marks)},
    )
    return exam


async def update_exam(
    db: AsyncSession, *, exam: Exam, actor: User, data: ExamUpdate
) -> Exam:
    old = {
        "title": exam.title,
        "subject": exam.subject,
        "status": exam.status.value,
    }
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        if value is not None:
            setattr(exam, field, value)
    await db.flush()
    await audit_service.record(
        db,
        action="exam.updated",
        entity_type="exam",
        actor=actor,
        entity_id=exam.id,
        description="Examination details updated.",
        old_value=old,
        new_value={k: (v.value if hasattr(v, "value") else v) for k, v in payload.items() if v is not None},
    )
    return exam


async def delete_exam(db: AsyncSession, *, exam: Exam, actor: User) -> None:
    await audit_service.record(
        db,
        action="exam.deleted",
        entity_type="exam",
        actor=actor,
        entity_id=exam.id,
        description=f"Deleted examination '{exam.title}'.",
        old_value={"title": exam.title, "subject": exam.subject},
    )
    await db.delete(exam)
    await db.flush()


async def add_question(
    db: AsyncSession,
    *,
    exam: Exam,
    data: QuestionCreate,
    order_index: int | None = None,
) -> Question:
    question = Question(
        exam_id=exam.id,
        number=data.number,
        label=data.label or f"Q{data.number}",
        text=data.text,
        max_marks=Decimal(str(data.max_marks)),
        question_type=data.question_type,
        expected_answer=data.expected_answer,
        keywords=list(data.keywords or []),
        guidance=data.guidance,
        order_index=data.order_index if order_index is None else order_index,
    )
    db.add(question)
    await db.flush()

    for idx, crit in enumerate(data.criteria or []):
        db.add(
            MarkingCriterion(
                question_id=question.id,
                name=crit.name,
                description=crit.description,
                max_marks=Decimal(str(crit.max_marks)),
                order_index=idx,
            )
        )
    await db.flush()
    return question


async def update_question(
    db: AsyncSession,
    *,
    exam: Exam,
    question: Question,
    actor: User,
    data: QuestionUpdate,
) -> Question:
    payload = data.model_dump(exclude_unset=True)
    criteria = payload.pop("criteria", None)

    for field, value in payload.items():
        if value is None:
            continue
        if field == "max_marks":
            setattr(question, field, Decimal(str(value)))
        else:
            setattr(question, field, value)

    if criteria is not None:
        # Replacing the scheme invalidates previous AI evaluations in spirit;
        # we keep them for audit but they are superseded on re-evaluation.
        for existing in list(question.criteria):
            await db.delete(existing)
        await db.flush()
        for idx, crit in enumerate(criteria):
            db.add(
                MarkingCriterion(
                    question_id=question.id,
                    name=crit["name"],
                    description=crit.get("description"),
                    max_marks=Decimal(str(crit["max_marks"])),
                    order_index=idx,
                )
            )

    await db.flush()
    await db.refresh(exam, attribute_names=["questions"])
    _recompute_total(exam)
    await db.flush()
    await db.refresh(question, attribute_names=["criteria"])
    await audit_service.record(
        db,
        action="question.updated",
        entity_type="question",
        actor=actor,
        entity_id=question.id,
        description=f"Updated {question.label}.",
        new_value={"max_marks": float(question.max_marks)},
    )
    return question


async def delete_question(
    db: AsyncSession, *, exam: Exam, question: Question, actor: User
) -> None:
    label = question.label
    await db.delete(question)
    await db.flush()
    await db.refresh(exam, attribute_names=["questions"])
    _recompute_total(exam)
    await db.flush()
    await audit_service.record(
        db,
        action="question.deleted",
        entity_type="question",
        actor=actor,
        entity_id=exam.id,
        description=f"Deleted question {label}.",
    )


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
async def exam_stats(db: AsyncSession, exam_id: uuid.UUID) -> dict:
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Submission)
                .where(Submission.exam_id == exam_id)
            )
        ).scalar_one()
    )

    async def count_statuses(statuses: list[SubmissionStatus]) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Submission)
                    .where(Submission.exam_id == exam_id, Submission.status.in_(statuses))
                )
            ).scalar_one()
        )

    processing = await count_statuses(
        [
            SubmissionStatus.UPLOADED,
            SubmissionStatus.PROCESSING,
            SubmissionStatus.OCR_PROCESSING,
            SubmissionStatus.ANSWERS_DETECTED,
            SubmissionStatus.AI_EVALUATING,
        ]
    )
    in_review = await count_statuses(
        [SubmissionStatus.READY_FOR_REVIEW, SubmissionStatus.REVIEWED]
    )
    completed = await count_statuses([SubmissionStatus.COMPLETED])
    failed = await count_statuses([SubmissionStatus.FAILED])

    flagged = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Answer)
                .join(Submission, Answer.submission_id == Submission.id)
                .where(Submission.exam_id == exam_id, Answer.is_flagged.is_(True))
            )
        ).scalar_one()
    )

    avg_pct = (
        await db.execute(
            select(
                func.avg(
                    Submission.final_total_marks
                    / func.nullif(Submission.max_total_marks, 0)
                    * 100
                )
            ).where(
                Submission.exam_id == exam_id,
                Submission.status == SubmissionStatus.COMPLETED,
                Submission.max_total_marks > 0,
            )
        )
    ).scalar_one()

    max_total = (
        await db.execute(select(func.max(Exam.total_marks)).where(Exam.id == exam_id))
    ).scalar_one()

    return {
        "exam_id": exam_id,
        "submission_count": total,
        "completed_count": completed,
        "in_review_count": in_review,
        "processing_count": processing,
        "failed_count": failed,
        "pending_review_count": in_review,
        "flagged_answer_count": flagged,
        "average_percentage": round(float(avg_pct), 2) if avg_pct is not None else None,
        "max_total_marks": float(max_total or 0),
    }

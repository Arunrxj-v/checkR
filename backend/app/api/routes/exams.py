"""Examination, question and marking-scheme routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OwnedExam, get_owned_exam
from app.core.config import settings
from app.db.enums import ExamStatus
from app.models.exam import Question
from app.schemas.common import Message, Page
from app.schemas.exam import (
    ExamCreate,
    ExamDetail,
    ExamOut,
    ExamStats,
    ExamUpdate,
    QuestionCreate,
    QuestionOut,
    QuestionUpdate,
)
from app.services import exam_service

router = APIRouter(tags=["exams"])


def _to_out(exam, *, question_count: int | None = None) -> ExamOut:
    data = ExamOut.model_validate(exam)
    data.question_count = question_count if question_count is not None else len(exam.questions or [])
    return data


@router.get("/exams", response_model=Page[ExamOut])
async def list_exams(
    db: DbSession,
    user: CurrentUser,
    status_filter: ExamStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ExamOut]:
    exams, total = await exam_service.list_exams(
        db,
        owner_id=user.id,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
    # Question counts in a single grouped query would be ideal; this is fine at
    # realistic list sizes and keeps the service simple.
    items = []
    for exam in exams:
        count = len(
            (
                await db.execute(select(Question.id).where(Question.exam_id == exam.id))
            ).scalars().all()
        )
        items.append(_to_out(exam, question_count=count))
    return Page[ExamOut](items=items, total=total, limit=limit, offset=offset)


@router.post("/exams", response_model=ExamDetail, status_code=status.HTTP_201_CREATED)
async def create_exam(payload: ExamCreate, db: DbSession, user: CurrentUser) -> ExamDetail:
    exam = await exam_service.create_exam(db, owner=user, data=payload)
    exam = await exam_service.get_exam(db, exam.id)
    return ExamDetail.model_validate(exam)


@router.get("/exams/{exam_id}", response_model=ExamDetail)
async def get_exam(exam: OwnedExam, db: DbSession) -> ExamDetail:
    full = await exam_service.get_exam(db, exam.id)
    return ExamDetail.model_validate(full)


@router.patch("/exams/{exam_id}", response_model=ExamDetail)
async def update_exam(
    payload: ExamUpdate, exam: OwnedExam, db: DbSession, user: CurrentUser
) -> ExamDetail:
    await exam_service.update_exam(db, exam=exam, actor=user, data=payload)
    full = await exam_service.get_exam(db, exam.id)
    return ExamDetail.model_validate(full)


@router.delete("/exams/{exam_id}", response_model=Message)
async def delete_exam(exam: OwnedExam, db: DbSession, user: CurrentUser) -> Message:
    await exam_service.delete_exam(db, exam=exam, actor=user)
    return Message(detail="Examination deleted.")


@router.get("/exams/{exam_id}/stats", response_model=ExamStats)
async def exam_stats(exam: OwnedExam, db: DbSession) -> ExamStats:
    stats = await exam_service.exam_stats(db, exam.id)
    return ExamStats.model_validate(stats)


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #
@router.get("/exams/{exam_id}/questions", response_model=list[QuestionOut])
async def list_questions(exam: OwnedExam, db: DbSession) -> list[QuestionOut]:
    full = await exam_service.get_exam(db, exam.id)
    return [QuestionOut.model_validate(q) for q in full.questions]


@router.post(
    "/exams/{exam_id}/questions",
    response_model=QuestionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    payload: QuestionCreate, exam: OwnedExam, db: DbSession, user: CurrentUser
) -> QuestionOut:
    full = await exam_service.get_exam(db, exam.id)
    if any(q.number == payload.number for q in full.questions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question {payload.number} already exists in this examination.",
        )
    next_index = len(full.questions)
    question = await exam_service.add_question(
        db, exam=full, data=payload, order_index=next_index
    )
    await db.flush()
    await db.refresh(full, attribute_names=["questions"])
    exam_service._recompute_total(full)
    await db.flush()
    refreshed = await exam_service.get_question(db, question.id)
    return QuestionOut.model_validate(refreshed)


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: uuid.UUID,
    payload: QuestionUpdate,
    db: DbSession,
    user: CurrentUser,
) -> QuestionOut:
    question = await exam_service.get_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")
    exam = await get_owned_exam(question.exam_id, db, user)
    await exam_service.update_question(
        db, exam=exam, question=question, actor=user, data=payload
    )
    refreshed = await exam_service.get_question(db, question_id)
    return QuestionOut.model_validate(refreshed)


@router.delete("/questions/{question_id}", response_model=Message)
async def delete_question(
    question_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Message:
    question = await exam_service.get_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")
    exam = await get_owned_exam(question.exam_id, db, user)
    await exam_service.delete_question(db, exam=exam, question=question, actor=user)
    return Message(detail="Question deleted.")


@router.get("/exam-limits")
async def exam_limits(user: CurrentUser) -> dict:
    """Small reference payload for the exam editor UI."""
    return {
        "max_submission_pages": settings.max_submission_pages,
        "max_upload_mb": settings.max_upload_mb,
    }

"""Exam, question and marking-scheme schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field, model_validator

from app.db.enums import ExamStatus, QuestionType
from app.schemas.common import ORMModel


# --------------------------------------------------------------------------- #
# Marking criteria
# --------------------------------------------------------------------------- #
class CriterionBase(ORMModel):
    name: str = Field(min_length=1, max_length=250)
    description: str | None = None
    max_marks: float = Field(ge=0)


class CriterionCreate(CriterionBase):
    pass


class CriterionUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = None
    max_marks: float | None = Field(default=None, ge=0)


class CriterionOut(CriterionBase):
    id: uuid.UUID
    order_index: int


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #
class QuestionBase(ORMModel):
    number: int = Field(ge=1, le=999)
    label: str | None = Field(default=None, max_length=20)
    text: str = Field(min_length=1)
    max_marks: float = Field(ge=0)
    question_type: QuestionType = QuestionType.SHORT_ANSWER
    expected_answer: str | None = None
    keywords: list[str] = Field(default_factory=list)
    guidance: str | None = None
    order_index: int = 0


class QuestionCreate(QuestionBase):
    criteria: list[CriterionCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_label(self):
        if not self.label:
            self.label = f"Q{self.number}"
        return self


class QuestionUpdate(ORMModel):
    number: int | None = Field(default=None, ge=1, le=999)
    label: str | None = Field(default=None, max_length=20)
    text: str | None = Field(default=None, min_length=1)
    max_marks: float | None = Field(default=None, ge=0)
    question_type: QuestionType | None = None
    expected_answer: str | None = None
    keywords: list[str] | None = None
    guidance: str | None = None
    order_index: int | None = None
    criteria: list[CriterionCreate] | None = None


class QuestionOut(QuestionBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    criteria: list[CriterionOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Exams
# --------------------------------------------------------------------------- #
class ExamBase(ORMModel):
    title: str = Field(min_length=1, max_length=250)
    subject: str = Field(min_length=1, max_length=150)
    subject_code: str | None = Field(default=None, max_length=50)
    course: str | None = Field(default=None, max_length=150)
    academic_year: str | None = Field(default=None, max_length=20)
    exam_date: dt.date | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    instructions: str | None = None


class ExamCreate(ExamBase):
    status: ExamStatus = ExamStatus.DRAFT
    questions: list[QuestionCreate] = Field(default_factory=list)


class ExamUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    subject: str | None = Field(default=None, min_length=1, max_length=150)
    subject_code: str | None = Field(default=None, max_length=50)
    course: str | None = Field(default=None, max_length=150)
    academic_year: str | None = Field(default=None, max_length=20)
    exam_date: dt.date | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    instructions: str | None = None
    status: ExamStatus | None = None


class ExamOut(ExamBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    status: ExamStatus
    total_marks: float
    question_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class ExamDetail(ExamOut):
    questions: list[QuestionOut] = Field(default_factory=list)


class ExamStats(ORMModel):
    exam_id: uuid.UUID
    submission_count: int = 0
    completed_count: int = 0
    in_review_count: int = 0
    processing_count: int = 0
    failed_count: int = 0
    pending_review_count: int = 0
    flagged_answer_count: int = 0
    average_percentage: float | None = None
    max_total_marks: float = 0

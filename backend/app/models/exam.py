"""Examinations, questions and the marking scheme."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import ExamStatus, QuestionType


class Exam(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exams"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    subject_code: Mapped[str | None] = mapped_column(String(50))
    course: Mapped[str | None] = mapped_column(String(150))          # class / programme
    academic_year: Mapped[str | None] = mapped_column(String(20))
    exam_date: Mapped[dt.date | None] = mapped_column(Date)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    total_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ExamStatus] = mapped_column(
        SAEnum(ExamStatus, native_enum=False, length=32),
        default=ExamStatus.DRAFT,
        nullable=False,
    )

    owner: Mapped[User] = relationship(back_populates="exams")  # noqa: F821
    questions: Mapped[list[Question]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )
    submissions: Mapped[list[Submission]] = relationship(  # noqa: F821
        back_populates="exam", cascade="all, delete-orphan"
    )


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)   # e.g. "Q1"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType, native_enum=False, length=32),
        default=QuestionType.SHORT_ANSWER,
        nullable=False,
    )
    expected_answer: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    guidance: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    exam: Mapped[Exam] = relationship(back_populates="questions")
    criteria: Mapped[list[MarkingCriterion]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="MarkingCriterion.order_index",
    )
    answers: Mapped[list[Answer]] = relationship(  # noqa: F821
        back_populates="question", cascade="all, delete-orphan"
    )


class MarkingCriterion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single awardable element of a marking scheme.

    Marks are allocated per criterion so that evaluation stays explainable and
    partial credit is possible.
    """

    __tablename__ = "marking_criteria"

    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    question: Mapped[Question] = relationship(back_populates="criteria")

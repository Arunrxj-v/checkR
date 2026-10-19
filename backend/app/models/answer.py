"""Detected answers, their page regions and raw OCR output."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Float,
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
from app.db.enums import AnswerStatus, ConfidenceLevel


class Answer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student's response to a single question.

    An answer may span several pages (continuation) and several regions; it
    holds both the AI score and the teacher's final score so the AI result is
    never overwritten.
    """

    __tablename__ = "answers"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[AnswerStatus] = mapped_column(
        SAEnum(AnswerStatus, native_enum=False, length=32),
        default=AnswerStatus.PENDING,
        nullable=False,
    )

    transcription: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    is_handwriting_uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0, nullable=False)
    ai_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_confidence_level: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, length=16)
    )

    teacher_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    teacher_comment: Mapped[str | None] = mapped_column(Text)

    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_reason: Mapped[str | None] = mapped_column(Text)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    detection_meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[Submission] = relationship(back_populates="answers")  # noqa: F821
    question: Mapped[Question] = relationship(back_populates="answers")  # noqa: F821
    regions: Mapped[list[AnswerRegion]] = relationship(
        back_populates="answer", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[Evaluation]] = relationship(  # noqa: F821
        back_populates="answer",
        cascade="all, delete-orphan",
        order_by="Evaluation.created_at.desc()",
    )
    reviews: Mapped[list[TeacherReview]] = relationship(  # noqa: F821
        back_populates="answer", cascade="all, delete-orphan"
    )

    @property
    def effective_score(self) -> Decimal | None:
        """Teacher score wins; otherwise the AI score (used for provisional totals)."""
        if self.teacher_score is not None:
            return self.teacher_score
        return self.ai_score


class AnswerRegion(UUIDPrimaryKeyMixin, Base):
    """A bounding box on a page that belongs to an answer.

    Coordinates are normalised to 0-1 relative to the processed page so the
    frontend can overlay them on any zoom level.
    """

    __tablename__ = "answer_regions"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("answers.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submission_pages.id", ondelete="CASCADE"), index=True
    )
    x0: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    y0: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    x1: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    y1: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)

    answer: Mapped[Answer] = relationship(back_populates="regions")
    page: Mapped[SubmissionPage] = relationship(back_populates="regions")  # noqa: F821


class OCRResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Raw handwriting-recognition output for a page.

    Kept verbatim (with provider/model/prompt provenance) so transcription can
    be re-derived and audited, and so an OCR pass is never needlessly repeated.
    """

    __tablename__ = "ocr_results"

    page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submission_pages.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    regions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    page: Mapped[SubmissionPage] = relationship(back_populates="ocr_results")  # noqa: F821

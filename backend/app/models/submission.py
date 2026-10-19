"""Submissions (uploaded answer-sheet booklets) and their scanned pages."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import PageStatus, SubmissionStatus


class Submission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One student's answer-sheet booklet for one exam.

    The original uploaded artefact is never overwritten; page derivatives are
    stored separately and linked from :class:`SubmissionPage`.
    """

    __tablename__ = "submissions"

    exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    student_name: Mapped[str | None] = mapped_column(String(200))
    student_roll: Mapped[str | None] = mapped_column(String(60), index=True)

    status: Mapped[SubmissionStatus] = mapped_column(
        SAEnum(SubmissionStatus, native_enum=False, length=32),
        default=SubmissionStatus.UPLOADED,
        nullable=False,
    )
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Original upload metadata (storage key never exposed directly to clients).
    original_filename: Mapped[str | None] = mapped_column(String(400))
    original_content_type: Mapped[str | None] = mapped_column(String(120))
    original_storage_key: Mapped[str | None] = mapped_column(String(600))
    original_size_bytes: Mapped[int | None] = mapped_column(Integer)

    # Aggregates (recomputed when answers change).
    max_total_marks: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    ai_total_marks: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    final_total_marks: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text)
    processing_meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    exam: Mapped[Exam] = relationship(back_populates="submissions")  # noqa: F821
    pages: Mapped[list[SubmissionPage]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionPage.page_number",
    )
    answers: Mapped[list[Answer]] = relationship(  # noqa: F821
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="Answer.order_index",
    )


class SubmissionPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single rendered/preprocessed page of an answer sheet.

    ``original_storage_key`` points at the untouched extracted page; the
    ``processed_storage_key`` and ``thumbnail_storage_key`` are non-destructive
    derivatives produced by the imaging pipeline.
    """

    __tablename__ = "submission_pages"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    original_storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    processed_storage_key: Mapped[str | None] = mapped_column(String(600))
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(600))

    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deskew_angle: Mapped[float | None] = mapped_column(Float)

    status: Mapped[PageStatus] = mapped_column(
        SAEnum(PageStatus, native_enum=False, length=32),
        default=PageStatus.UPLOADED,
        nullable=False,
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    preprocessing_meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="pages")
    regions: Mapped[list[AnswerRegion]] = relationship(  # noqa: F821
        back_populates="page", cascade="all, delete-orphan"
    )
    ocr_results: Mapped[list[OCRResult]] = relationship(  # noqa: F821
        back_populates="page", cascade="all, delete-orphan"
    )

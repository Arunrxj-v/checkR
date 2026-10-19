"""AI evaluations, per-criterion results and teacher reviews."""

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
from app.db.enums import (
    ConfidenceLevel,
    EvaluationStatus,
    ReviewDecision,
)


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI evaluation run for one answer.

    Provenance (provider/model/prompt/engine version) is stored so any result
    can be reproduced or invalidated deliberately when the model changes.
    Older evaluations are retained and marked ``superseded`` rather than
    deleted, preserving the audit trail.
    """

    __tablename__ = "evaluations"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("answers.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[EvaluationStatus] = mapped_column(
        SAEnum(EvaluationStatus, native_enum=False, length=20),
        default=EvaluationStatus.VALID,
        nullable=False,
    )

    awarded_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0, nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, length=16),
        default=ConfidenceLevel.LOW,
        nullable=False,
    )

    reasoning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    strengths: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    gaps: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    contradictions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    flags: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    validation_notes: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    answer: Mapped[Answer] = relationship(back_populates="evaluations")  # noqa: F821
    criteria: Mapped[list[EvaluationCriterion]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="EvaluationCriterion.order_index",
    )
    reviews: Mapped[list[TeacherReview]] = relationship(back_populates="evaluation")


class EvaluationCriterion(UUIDPrimaryKeyMixin, Base):
    """Per-criterion outcome of an evaluation (the explainable breakdown)."""

    __tablename__ = "evaluation_criteria"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    awarded_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0, nullable=False)
    satisfied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    evaluation: Mapped[Evaluation] = relationship(back_populates="criteria")


class TeacherReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An immutable record of a teacher decision on an AI evaluation."""

    __tablename__ = "teacher_reviews"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("answers.id", ondelete="CASCADE"), index=True
    )
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluations.id", ondelete="SET NULL")
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        SAEnum(ReviewDecision, native_enum=False, length=20), nullable=False
    )
    ai_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    teacher_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    comment: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)

    answer: Mapped[Answer] = relationship(back_populates="reviews")  # noqa: F821
    evaluation: Mapped[Evaluation | None] = relationship(back_populates="reviews")

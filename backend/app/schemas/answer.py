"""Answer, evaluation, review and result schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field, model_validator

from app.db.enums import (
    AnswerStatus,
    ConfidenceLevel,
    EvaluationStatus,
    QuestionType,
    ReviewDecision,
)
from app.schemas.common import ORMModel


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #
class AnswerRegionOut(ORMModel):
    id: uuid.UUID
    page_id: uuid.UUID
    x0: float
    y0: float
    x1: float
    y1: float
    label: str | None = None
    confidence: float | None = None


class AnswerPageOut(ORMModel):
    """One manuscript page an answer appears on, with the regions on it.

    ``uncertain`` marks a page association that could not be confirmed from
    detected regions, so the client can say so instead of implying certainty.
    """

    page_id: uuid.UUID
    page_number: int
    regions: list[AnswerRegionOut] = Field(default_factory=list)
    uncertain: bool = False


# --------------------------------------------------------------------------- #
# Evaluations
# --------------------------------------------------------------------------- #
class EvaluationCriterionOut(ORMModel):
    id: uuid.UUID
    name: str
    max_marks: float
    awarded_marks: float
    satisfied: bool
    comment: str | None = None
    order_index: int = 0
    #: Verbatim quotes from the student's answer justifying the award.
    evidence: list[str] = Field(default_factory=list)
    #: Rubric elements the answer did not cover.
    missing_elements: list[str] = Field(default_factory=list)
    #: True when the model asked a human to double-check this criterion.
    needs_human_review: bool = False


class EvaluationOut(ORMModel):
    id: uuid.UUID
    answer_id: uuid.UUID
    provider: str
    model: str
    model_version: str | None = None
    #: Which model transcribed the answer this evaluation graded.
    ocr_model: str | None = None
    #: When the OCR pass feeding this evaluation completed.
    ocr_completed_at: dt.datetime | None = None
    prompt_version: str
    engine_version: str
    is_mock: bool
    status: EvaluationStatus
    awarded_marks: float
    max_marks: float
    confidence: float
    confidence_level: ConfidenceLevel
    reasoning: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    criteria: list[EvaluationCriterionOut] = Field(default_factory=list)
    #: The evaluation model asked for a human check of this result.
    needs_human_review: bool = False
    #: Wall-clock inference time of the evaluation request.
    processing_duration_ms: int | None = None
    created_at: dt.datetime
    #: Alias of ``created_at`` — when the evaluation completed.
    evaluation_completed_at: dt.datetime | None = None


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
class ReviewRequest(ORMModel):
    """Teacher decision on an answer.

    ``teacher_score`` is required for an override; it is validated against the
    question maximum server-side.
    """

    action: ReviewDecision
    teacher_score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _validate_override(self):
        if self.action == ReviewDecision.OVERRIDDEN and self.teacher_score is None:
            raise ValueError("teacher_score is required when overriding a mark.")
        return self


class ReviewOut(ORMModel):
    id: uuid.UUID
    answer_id: uuid.UUID
    evaluation_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    decision: ReviewDecision
    ai_score: float | None = None
    teacher_score: float | None = None
    comment: str | None = None
    reason: str | None = None
    created_at: dt.datetime


# --------------------------------------------------------------------------- #
# Answers
# --------------------------------------------------------------------------- #
class AnswerOut(ORMModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    question_id: uuid.UUID
    order_index: int = 0
    status: AnswerStatus
    transcription: str | None = None
    ocr_confidence: float | None = None
    is_handwriting_uncertain: bool = False
    max_marks: float = 0
    ai_score: float | None = None
    ai_confidence: float | None = None
    ai_confidence_level: ConfidenceLevel | None = None
    teacher_score: float | None = None
    final_score: float | None = None
    teacher_comment: str | None = None
    is_flagged: bool = False
    flag_reason: str | None = None
    is_reviewed: bool = False
    error_message: str | None = None
    #: Manuscript pages this answer was detected on, ascending (1-based).
    #: Always derived from stored regions — never from list position.
    page_numbers: list[int] = Field(default_factory=list)
    #: True when the page association could not be confirmed from detection.
    page_mapping_uncertain: bool = False


class OCRProvenanceOut(ORMModel):
    """Provenance of the OCR pass that produced an answer's transcription."""

    model: str | None = None
    provider: str | None = None
    prompt_version: str | None = None
    confidence: float | None = None
    #: Wall-clock OCR inference time for the page (when measured).
    duration_ms: int | None = None
    #: The model's own report: completed | partial | unreadable | unknown.
    ocr_status: str | None = None
    is_mock: bool = False
    #: When the stored OCR result was written.
    completed_at: dt.datetime | None = None


class AnswerDetail(AnswerOut):
    """Everything the evaluation workspace needs for one answer."""

    regions: list[AnswerRegionOut] = Field(default_factory=list)
    #: Ordered page mapping the workspace drives the manuscript viewer with.
    pages: list[AnswerPageOut] = Field(default_factory=list)
    #: ``regions`` (observed) | ``detection_meta`` (best effort) |
    #: ``examiner`` (teacher-corrected) | ``unknown``.
    page_mapping_source: str | None = None
    #: OCR provenance for this answer's transcription (model, timing, status).
    ocr: OCRProvenanceOut | None = None
    question_label: str | None = None
    question_text: str | None = None
    question_type: QuestionType | None = None
    expected_answer: str | None = None
    guidance: str | None = None
    keywords: list[str] = Field(default_factory=list)
    marking_scheme: list[dict] = Field(default_factory=list)
    evaluation: EvaluationOut | None = None
    reviews: list[ReviewOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Examiner corrections
# --------------------------------------------------------------------------- #
class TranscriptionUpdate(ORMModel):
    """Examiner-corrected transcription for one answer.

    The AI suggestion is never rewritten by this call: the original stays in
    ``ocr_results``/``raw_response`` and only ``Answer.transcription`` changes,
    with the correction recorded in the audit trail.
    """

    transcription: str = Field(min_length=1, max_length=100_000)


class PageMappingUpdate(ORMModel):
    """Examiner-corrected set of manuscript pages an answer appears on.

    Question numbers are never assumed to equal page numbers: the examiner
    states the pages explicitly (1-based).
    """

    page_numbers: list[int] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _valid_numbers(self):
        cleaned = sorted({n for n in self.page_numbers if n > 0})
        if not cleaned:
            raise ValueError("page_numbers must contain at least one page > 0")
        self.page_numbers = cleaned
        return self


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
class ResultRow(ORMModel):
    answer_id: uuid.UUID
    question_id: uuid.UUID
    question_label: str
    question_text: str
    max_marks: float
    ai_score: float | None = None
    teacher_score: float | None = None
    final_score: float | None = None
    ai_confidence: float | None = None
    is_reviewed: bool
    is_flagged: bool
    status: AnswerStatus


class SubmissionResult(ORMModel):
    submission_id: uuid.UUID
    exam_id: uuid.UUID
    student_name: str | None = None
    student_roll: str | None = None
    status: str
    max_total_marks: float
    ai_total_marks: float
    final_total_marks: float
    percentage: float | None = None
    reviewed_count: int = 0
    flagged_count: int = 0
    total_answers: int = 0
    rows: list[ResultRow] = Field(default_factory=list)
    generated_at: dt.datetime

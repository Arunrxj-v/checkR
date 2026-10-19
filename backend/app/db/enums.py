"""Domain enumerations shared across models, schemas and services.

Stored as plain strings (``native_enum=False``) so the schema stays portable and
adding a value never requires a PostgreSQL ``ALTER TYPE`` migration.
"""

from __future__ import annotations

from enum import StrEnum as _StrEnum


class StrEnum(_StrEnum):
    """String enum whose ``str()`` is its value (kept as an alias so imports stay stable)."""

    def __str__(self) -> str:  # pragma: no cover - convenience
        return str(self.value)


class UserRole(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    EVALUATOR = "evaluator"
    STUDENT = "student"


class ExamStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class QuestionType(StrEnum):
    SHORT_ANSWER = "short_answer"
    LONG_ANSWER = "long_answer"
    DEFINITION = "definition"
    EXPLANATION = "explanation"
    NUMERICAL = "numerical"
    PROGRAMMING = "programming"
    DIAGRAM = "diagram"
    ESSAY = "essay"
    OTHER = "other"


#: The prompt template family each question type maps to.
PROMPT_FAMILY_BY_QUESTION_TYPE: dict[str, str] = {
    QuestionType.NUMERICAL.value: "numerical",
    QuestionType.PROGRAMMING.value: "programming",
    QuestionType.DIAGRAM.value: "diagram",
}


class SubmissionStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    OCR_PROCESSING = "ocr_processing"
    ANSWERS_DETECTED = "answers_detected"
    AI_EVALUATING = "ai_evaluating"
    READY_FOR_REVIEW = "ready_for_review"
    REVIEWED = "reviewed"
    COMPLETED = "completed"
    FAILED = "failed"


class PageStatus(StrEnum):
    UPLOADED = "uploaded"
    PREPROCESSED = "preprocessed"
    OCR_DONE = "ocr_done"
    FAILED = "failed"


class AnswerStatus(StrEnum):
    PENDING = "pending"            # detected, awaiting evaluation
    EVALUATING = "evaluating"
    EVALUATED = "evaluated"        # AI produced a result, awaiting teacher
    REVIEWED = "reviewed"          # teacher accepted/overrode
    FLAGGED = "flagged"            # low confidence / needs manual review
    FAILED = "failed"              # evaluation error


class EvaluationStatus(StrEnum):
    VALID = "valid"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    OVERRIDDEN = "overridden"
    FLAGGED = "flagged"
    UNFLAGGED = "unflagged"


class JobType(StrEnum):
    PROCESS_SUBMISSION = "process_submission"     # pages -> preprocess -> OCR -> segment
    PREPROCESS_PAGE = "preprocess_page"
    OCR_PAGE = "ocr_page"
    SEGMENT_ANSWERS = "segment_answers"
    EVALUATE_ANSWER = "evaluate_answer"
    EVALUATE_SUBMISSION = "evaluate_submission"
    GENERATE_RESULT = "generate_result"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def confidence_level_for(value: float | None, high: float, medium: float) -> ConfidenceLevel:
    """Classify a 0-1 confidence score into High / Medium / Low."""
    if value is None:
        return ConfidenceLevel.LOW
    if value >= high:
        return ConfidenceLevel.HIGH
    if value >= medium:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW

"""Provider-agnostic value objects returned by the AI layer.

These dataclasses are what the rest of the application depends on. Concrete
providers (mock, Gemini, OpenAI, Anthropic, local) translate their own wire
formats into these types, so no provider-specific shape leaks into services.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class OCRPageResult:
    """Handwriting recognition output for a single page."""

    text: str
    confidence: float | None = None
    regions: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    prompt_version: str = ""
    is_mock: bool = False


@dataclass(slots=True)
class CriterionOutcome:
    """Outcome for one marking-scheme criterion."""

    name: str
    max_marks: float
    awarded_marks: float
    satisfied: bool
    comment: str | None = None


@dataclass(slots=True)
class AnswerEvaluationResult:
    """Structured evaluation of one answer against one question's scheme."""

    awarded_marks: float
    max_marks: float
    confidence: float
    reasoning: str
    criteria: list[CriterionOutcome] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    is_mock: bool = False
    validation_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationContext:
    """Everything the model is allowed to see when grading one answer.

    The original answer image(s) are always included so the model can resolve
    OCR mistakes — text alone is never trusted.
    """

    question_label: str
    question_text: str
    question_type: str
    max_marks: float
    expected_answer: str | None
    guidance: str | None
    keywords: list[str]
    criteria: list[dict]  # [{name, description, max_marks}]
    transcription: str
    ocr_confidence: float | None
    images: list[bytes] = field(default_factory=list)
    submission_ref: str = ""

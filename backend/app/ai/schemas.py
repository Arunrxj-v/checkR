"""Strict wire schemas for AI model responses.

Model output is never trusted blindly: every response is parsed through these
Pydantic models before it can reach the database.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class RawCriterion(BaseModel):
    name: str = Field(default="", max_length=300)
    awarded_marks: float = Field(default=0.0)
    max_marks: float | None = None
    satisfied: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def _coerce_name(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("awarded_marks", mode="before")
    @classmethod
    def _coerce_marks(cls, v: object) -> float:
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0


class RawEvaluation(BaseModel):
    """The shape we ask every provider to return for one answer."""

    model_config = {"extra": "ignore"}

    awarded_marks: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    criteria: list[RawCriterion] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @field_validator("awarded_marks", "confidence", mode="before")
    @classmethod
    def _coerce_float(cls, v: object) -> float:
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    @field_validator("reasoning", mode="before")
    @classmethod
    def _coerce_str(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("strengths", "gaps", "contradictions", "flags", mode="before")
    @classmethod
    def _coerce_str_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v if x is not None]
        return [str(v)]


class RawOCRRegion(BaseModel):
    model_config = {"extra": "ignore"}
    text: str = ""
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None

    @field_validator("x0", "y0", "x1", "y1", mode="before")
    @classmethod
    def _coerce_coord(cls, v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


class RawDetectedAnswer(BaseModel):
    """One question block the model located on the page."""

    model_config = {"extra": "ignore"}

    question_number: str = ""
    transcription: str = ""
    started_on_previous_page: bool = False
    continues_on_next_page: bool = False
    regions: list[RawOCRRegion] = Field(default_factory=list)
    uncertain_segments: list[str] = Field(default_factory=list)
    confidence: float | None = None

    @field_validator("question_number", mode="before")
    @classmethod
    def _coerce_number(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("transcription", mode="before")
    @classmethod
    def _coerce_text(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_conf(cls, v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @field_validator("uncertain_segments", mode="before")
    @classmethod
    def _coerce_segments(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v if x is not None]
        return [str(v)]


class RawOCRDiagram(BaseModel):
    model_config = {"extra": "ignore"}

    caption: str = ""
    region: RawOCRRegion | None = None

    @field_validator("caption", mode="before")
    @classmethod
    def _coerce_caption(cls, v: object) -> str:
        return "" if v is None else str(v)


class RawUnreadableRegion(BaseModel):
    model_config = {"extra": "ignore"}

    reason: str = ""
    region: RawOCRRegion | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _coerce_reason(cls, v: object) -> str:
        return "" if v is None else str(v)


class RawOCR(BaseModel):
    """The structured shape we ask every vision provider to return per page."""

    model_config = {"extra": "ignore"}

    page_number: int | None = None
    text: str = ""
    confidence: float = 0.0
    regions: list[RawOCRRegion] = Field(default_factory=list)
    detected_answers: list[RawDetectedAnswer] = Field(default_factory=list)
    diagrams: list[RawOCRDiagram] = Field(default_factory=list)
    unreadable_regions: list[RawUnreadableRegion] = Field(default_factory=list)
    manual_review_required: bool = False

    @model_validator(mode="before")
    @classmethod
    def _accept_transcription_alias(cls, data: object) -> object:
        # The OCR prompt labels the page-level text ``transcription`` while
        # older prompts used ``text`` — accept both, prefer the explicit key.
        if isinstance(data, dict) and "text" not in data and "transcription" in data:
            return {**data, "text": data["transcription"]}
        return data

    @field_validator("text", mode="before")
    @classmethod
    def _coerce_text(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_conf(cls, v: object) -> float:
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    @field_validator("manual_review_required", mode="before")
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1")
        return bool(v)

    @field_validator("detected_answers", mode="before")
    @classmethod
    def _coerce_answers(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        if isinstance(v, (list, tuple)):
            return list(v)
        return []

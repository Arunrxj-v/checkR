"""Strict wire schemas for AI model responses.

Model output is never trusted blindly: every response is parsed through these
Pydantic models before it can reach the database.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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


class RawOCR(BaseModel):
    model_config = {"extra": "ignore"}

    text: str = ""
    confidence: float = 0.0
    regions: list[RawOCRRegion] = Field(default_factory=list)

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

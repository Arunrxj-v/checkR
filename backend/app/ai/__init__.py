"""Provider-agnostic AI layer: providers, factory, types and validation."""

from app.ai.base import AIProvider, AIProviderError
from app.ai.factory import build_provider, get_provider, shutdown_provider
from app.ai.types import (
    AnswerEvaluationResult,
    CriterionOutcome,
    EvaluationContext,
    OCRPageResult,
)
from app.ai.validation import validate_evaluation, validate_ocr

__all__ = [
    "AIProvider",
    "AIProviderError",
    "build_provider",
    "get_provider",
    "shutdown_provider",
    "AnswerEvaluationResult",
    "CriterionOutcome",
    "EvaluationContext",
    "OCRPageResult",
    "validate_evaluation",
    "validate_ocr",
]

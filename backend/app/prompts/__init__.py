"""Versioned prompt templates."""

from app.prompts.registry import (
    CURRENT_ENGINE_VERSION,
    CURRENT_OCR_PROMPT_VERSION,
    build_evaluation_prompt,
    evaluation_prompt,
    ocr_prompt,
    prompt_family_for,
)

__all__ = [
    "build_evaluation_prompt",
    "evaluation_prompt",
    "ocr_prompt",
    "prompt_family_for",
    "CURRENT_OCR_PROMPT_VERSION",
    "CURRENT_ENGINE_VERSION",
]

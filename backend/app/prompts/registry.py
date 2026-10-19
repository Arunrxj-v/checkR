"""Prompt registry.

Prompts live in dedicated versioned modules — never inline in services or
providers. This lets an evaluation record its exact ``prompt_version`` and be
reproduced later.
"""

from __future__ import annotations

from types import ModuleType

from app.ai.types import EvaluationContext
from app.db.enums import PROMPT_FAMILY_BY_QUESTION_TYPE
from app.prompts.answer_evaluation import (
    diagram_v1,
    numerical_v1,
    programming_v1,
    theory_v1,
)
from app.prompts.answer_evaluation.common import ENGINE_VERSION
from app.prompts.ocr import handwriting_v1

_OCR_PROMPTS: dict[str, ModuleType] = {
    handwriting_v1.PROMPT_VERSION: handwriting_v1,
}

_EVAL_PROMPTS: dict[str, ModuleType] = {
    theory_v1.FAMILY: theory_v1,
    numerical_v1.FAMILY: numerical_v1,
    programming_v1.FAMILY: programming_v1,
    diagram_v1.FAMILY: diagram_v1,
}

CURRENT_OCR_PROMPT_VERSION = handwriting_v1.PROMPT_VERSION
CURRENT_ENGINE_VERSION = ENGINE_VERSION


def prompt_family_for(question_type: str) -> str:
    """Map a question type to its prompt family (defaults to theory)."""
    return PROMPT_FAMILY_BY_QUESTION_TYPE.get(question_type, theory_v1.FAMILY)


def ocr_prompt(version: str | None = None) -> ModuleType:
    version = version or CURRENT_OCR_PROMPT_VERSION
    try:
        return _OCR_PROMPTS[version]
    except KeyError as exc:
        raise KeyError(f"Unknown OCR prompt version: {version}") from exc


def evaluation_prompt(family: str) -> ModuleType:
    try:
        return _EVAL_PROMPTS[family]
    except KeyError as exc:
        raise KeyError(f"Unknown evaluation prompt family: {family}") from exc


def build_evaluation_prompt(
    context: EvaluationContext, *, family: str | None = None
) -> tuple[str, str, str]:
    """Return ``(system_prompt, user_prompt, prompt_version)`` for a context."""
    family = family or prompt_family_for(context.question_type)
    module = evaluation_prompt(family)
    return module.SYSTEM, module.build(context), module.PROMPT_VERSION


__all__ = [
    "build_evaluation_prompt",
    "ocr_prompt",
    "evaluation_prompt",
    "prompt_family_for",
    "CURRENT_OCR_PROMPT_VERSION",
    "CURRENT_ENGINE_VERSION",
]

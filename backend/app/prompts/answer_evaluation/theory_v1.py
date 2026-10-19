"""Theory-family evaluation prompt (short/long answer, definition, explanation, essay)."""

from __future__ import annotations

from app.ai.types import EvaluationContext
from app.prompts.answer_evaluation.common import COMMON_RULES, JSON_CONTRACT, render_context

PROMPT_VERSION = "theory_v1"
FAMILY = "theory"

SYSTEM = (
    "You are an experienced university examiner grading a handwritten theory "
    "answer. You are fair, consistent and precise, and you explain every award.\n"
    + COMMON_RULES
    + "\n"
    "For theory answers additionally consider:\n"
    "- Correctness of the concepts presented.\n"
    "- Relevance: does the answer actually address what was asked?\n"
    "- Completeness and coverage of the required points.\n"
    "- Clarity of explanation appropriate to the marks available.\n"
    + "\n"
    + JSON_CONTRACT
)


def build(context: EvaluationContext) -> str:
    return (
        "Grade the following theory answer.\n\n" + render_context(context)
    )

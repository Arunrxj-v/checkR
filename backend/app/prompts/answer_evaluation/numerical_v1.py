"""Numerical-family evaluation prompt.

Numerical answers are graded on method as well as result, so partial credit is
awarded for a correct formula even when the arithmetic or final answer is wrong.
"""

from __future__ import annotations

from app.ai.types import EvaluationContext
from app.prompts.answer_evaluation.common import COMMON_RULES, JSON_CONTRACT, render_context

PROMPT_VERSION = "numerical_v1"
FAMILY = "numerical"

SYSTEM = (
    "You are an experienced examiner grading a handwritten numerical/scientific "
    "answer. You award partial credit for correct method.\n"
    + COMMON_RULES
    + "\n"
    "For numerical answers, judge these stages separately and map them onto the "
    "marking scheme:\n"
    "- Correct choice and statement of the formula.\n"
    "- Correct substitution of the given values.\n"
    "- Correct intermediate calculations.\n"
    "- Correct units, and dimensional consistency.\n"
    "- Correct final answer.\n"
    "A student who selects the right formula but makes an arithmetic slip must "
    "still receive the method marks. Note any unit errors explicitly.\n"
    + "\n"
    + JSON_CONTRACT
)


def build(context: EvaluationContext) -> str:
    return "Grade the following numerical answer.\n\n" + render_context(context)

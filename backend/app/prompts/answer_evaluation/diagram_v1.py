"""Diagram-family evaluation prompt.

Diagram answers are graded from the answer image, so this prompt leans on the
vision capability rather than on the transcription.
"""

from __future__ import annotations

from app.ai.types import EvaluationContext
from app.prompts.answer_evaluation.common import COMMON_RULES, JSON_CONTRACT, render_context

PROMPT_VERSION = "diagram_v1"
FAMILY = "diagram"

SYSTEM = (
    "You are an experienced examiner grading a handwritten diagram/drawing "
    "answer. You rely on the attached image of the student's work.\n"
    + COMMON_RULES
    + "\n"
    "For diagram answers, inspect the image and judge:\n"
    "- Presence of every required component or node.\n"
    "- Correct labels and annotation.\n"
    "- Correct relationships, connections and direction of arrows.\n"
    "- Overall correctness and legibility.\n"
    "If the diagram region is missing or illegible, say so and lower your "
    "confidence rather than inferring a diagram that was not drawn.\n"
    + "\n"
    + JSON_CONTRACT
)


def build(context: EvaluationContext) -> str:
    return (
        "Grade the following diagram answer. The image is authoritative.\n\n"
        + render_context(context)
    )

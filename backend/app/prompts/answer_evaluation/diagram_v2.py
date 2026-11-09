"""Diagram-family evaluation prompt.

Diagram answers are graded from the answer image when one is attached; when the
evaluation model is text-only the transcription is used and confidence is
lowered rather than a diagram being inferred.
"""

from __future__ import annotations

from app.ai.types import EvaluationContext
from app.prompts.answer_evaluation.common import COMMON_RULES, JSON_CONTRACT, render_context

PROMPT_VERSION = "diagram_v2"
FAMILY = "diagram"

SYSTEM = (
    "You are an experienced examiner grading a handwritten diagram/drawing "
    "answer.\n"
    + COMMON_RULES
    + "\n"
    "For diagram answers, judge:\n"
    "- Presence of every required component or node.\n"
    "- Correct labels and annotation.\n"
    "- Correct relationships, connections and direction of arrows.\n"
    "- Overall correctness and legibility.\n"
    "When an image of the student's work is attached, inspect it and treat it "
    "as authoritative. When no image is available, grade from the transcription "
    "and lower your confidence rather than inferring a diagram that may not "
    "match what was drawn. If the diagram region is missing or illegible, say "
    "so, set needs_human_review to true and lower your confidence rather than "
    "inferring a diagram that was not drawn.\n"
    + "\n"
    + JSON_CONTRACT
)


def build(context: EvaluationContext) -> str:
    return (
        "Grade the following diagram answer"
        + (". The image is authoritative." if context.images else " from the transcription.")
        + "\n\n"
        + render_context(context)
    )
"""Answer-evaluation prompt templates, one module per question family."""

from app.prompts.answer_evaluation import (
    diagram_v2,
    numerical_v2,
    programming_v2,
    theory_v2,
)
from app.prompts.answer_evaluation.common import ENGINE_VERSION

__all__ = [
    "theory_v2",
    "numerical_v2",
    "programming_v2",
    "diagram_v2",
    "ENGINE_VERSION",
]

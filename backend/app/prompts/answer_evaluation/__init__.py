"""Answer-evaluation prompt templates, one module per question family."""

from app.prompts.answer_evaluation import (
    diagram_v1,
    numerical_v1,
    programming_v1,
    theory_v1,
)
from app.prompts.answer_evaluation.common import ENGINE_VERSION

__all__ = [
    "theory_v1",
    "numerical_v1",
    "programming_v1",
    "diagram_v1",
    "ENGINE_VERSION",
]

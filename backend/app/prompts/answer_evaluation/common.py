"""Shared evaluation prompt scaffolding.

Each question-type family module defines ``PROMPT_VERSION``, ``SYSTEM`` and a
``build(context)`` function. They all share the JSON contract and the common
grading principles defined here.
"""

from __future__ import annotations

from app.ai.types import EvaluationContext

#: Version of the evaluation *engine* (validation + orchestration), distinct
#: from the prompt version. Bump when grading logic changes materially.
ENGINE_VERSION = "v2"

#: The single JSON shape every provider must return.
JSON_CONTRACT = """\
Return ONLY a single JSON object with this exact shape (no markdown, no prose):
{
  "awarded_marks": <number, the total marks awarded for this answer>,
  "confidence": <number between 0 and 1>,
  "reasoning": "<2-5 sentence explanation of the award>",
  "criteria": [
    {
      "name": "<exact criterion name from the marking scheme>",
      "awarded_marks": <number>,
      "satisfied": <true|false>,
      "comment": "<one short sentence>"
    }
  ],
  "strengths": ["<short point>"],
  "gaps": ["<short point>"],
  "contradictions": ["<factual error or contradiction, if any>"],
  "flags": ["<anything a teacher must double-check>"]
}
"""

#: Grading principles that apply to every question type.
COMMON_RULES = """\
Grading principles:
1. Evaluate ONLY the given question. Ignore anything unrelated to it.
2. Use the marking scheme exactly: award marks per criterion, never invent criteria.
3. Award partial marks. Never force a binary correct/incorrect decision.
4. Do not penalise a student for wording that differs from the expected answer.
   Reward semantic equivalence.
5. Never reward irrelevant text that merely mentions keywords.
6. Identify factual errors or contradictions explicitly in "contradictions".
7. The sum of the criteria's awarded_marks must equal "awarded_marks".
8. awarded_marks must be between 0 and the maximum marks (inclusive).
9. The provided OCR transcription may contain recognition errors. Any answer
   images are authoritative — use them to resolve discrepancies. If the images
   are unreadable, lower your confidence rather than guessing.
10. Set "confidence" honestly. Use a value below 0.6 when the handwriting is
    unclear or the answer is genuinely ambiguous.
"""


def render_context(context: EvaluationContext) -> str:
    """Render the question, answer and marking scheme as prompt text."""
    lines: list[str] = []
    lines.append(f"QUESTION ({context.question_label}) — maximum {context.max_marks:g} marks")
    lines.append(context.question_text.strip())
    lines.append("")

    if context.expected_answer:
        lines.append("EXPECTED / MODEL ANSWER:")
        lines.append(context.expected_answer.strip())
        lines.append("")

    if context.keywords:
        lines.append("KEY CONCEPTS: " + ", ".join(context.keywords))
        lines.append("")

    if context.guidance:
        lines.append("EXAMINER GUIDANCE:")
        lines.append(context.guidance.strip())
        lines.append("")

    lines.append("MARKING SCHEME (award marks per criterion):")
    for i, crit in enumerate(context.criteria, start=1):
        desc = crit.get("description")
        suffix = f" — {desc}" if desc else ""
        lines.append(
            f"  {i}. {crit.get('name')} "
            f"[max {float(crit.get('max_marks', 0)):g} marks]{suffix}"
        )
    lines.append("")

    lines.append("STUDENT'S ANSWER — OCR TRANSCRIPTION (may contain errors):")
    lines.append((context.transcription or "[no transcription available]").strip())
    lines.append("")

    if context.ocr_confidence is not None:
        lines.append(f"OCR confidence: {context.ocr_confidence:.2f}")
        lines.append("")

    if context.images:
        lines.append(
            f"{len(context.images)} image(s) of the student's handwritten answer "
            "are attached. Treat them as authoritative over the transcription."
        )
    else:
        lines.append(
            "No answer image is available; base your judgement on the transcription "
            "and lower your confidence accordingly."
        )

    return "\n".join(lines)

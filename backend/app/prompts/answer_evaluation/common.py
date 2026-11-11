"""Shared evaluation prompt scaffolding.

Each question-type family module defines ``PROMPT_VERSION``, ``SYSTEM`` and a
``build(context)`` function. They all share the JSON contract and the common
grading principles defined here.
"""

from __future__ import annotations

from app.ai.types import EvaluationContext

#: Version of the evaluation *engine* (validation + orchestration), distinct
#: from the prompt version. Bump when grading logic changes materially.
ENGINE_VERSION = "v3"

#: The single JSON shape every provider must return.
JSON_CONTRACT = """\
Return ONLY a single JSON object with this exact shape (no markdown, no prose):
{
  "awarded_marks": <number, the total marks awarded for this answer>,
  "confidence": <number between 0 and 1>,
  "reasoning": "<2-5 sentence explanation of the award>",
  "needs_human_review": <true|false — true when you are unsure and a human
                         should verify this evaluation>,
  "criteria": [
    {
      "name": "<exact criterion name from the marking scheme>",
      "awarded_marks": <number>,
      "satisfied": <true|false>,
      "comment": "<one short sentence>",
      "evidence": ["<short verbatim quote from the student's answer that
                   justifies this award — only when marks > 0>"],
      "missing_elements": ["<rubric element the answer did not cover —
                           only when marks < maximum>"],
      "needs_human_review": <true|false — true when this criterion is
                            ambiguous or you are unsure>
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
   Reward semantic equivalence: equivalent terminology, synonyms and
   notational variants earn the same marks as the expected wording.
5. Never reward irrelevant text that merely mentions keywords.
6. Identify factual errors or contradictions explicitly in "contradictions".
7. The sum of the criteria's awarded_marks must equal "awarded_marks".
8. awarded_marks must be between 0 and the maximum marks (inclusive), and a
   criterion's awarded_marks must never exceed that criterion's maximum.
9. Never award marks for content that is absent from the answer. If the
   student did not write it, it earns nothing — but if a required element is
   unreadable rather than absent, do not penalise it: note it under
   "missing_elements" only when it is genuinely missing, set
   "needs_human_review" and lower your confidence instead.
10. Do not deduct marks for spelling, grammar or handwriting quality unless
    the marking scheme explicitly says so.
11. Every award above 0 must cite at least one short verbatim quote from the
    student's answer under that criterion's "evidence". Never invent or
    paraphrase a quote; if you cannot quote anything, award 0 for that
    criterion or set needs_human_review.
12. The provided OCR transcription may contain recognition errors. Any answer
    images attached are authoritative — use them to resolve discrepancies.
    If no image is available, base your judgement on the transcription and
    lower your confidence accordingly; an illegible passage is not the same
    as an incorrect answer.
13. Set "confidence" honestly. Use a value below 0.6 when the handwriting is
    unclear or the answer is genuinely ambiguous.
14. Your marks are a suggestion for a human examiner, never a final decision.
    When the transcription is uncertain, a criterion is ambiguous, or two
    interpretations are both defensible, set "needs_human_review" to true
    rather than guessing confidently.
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
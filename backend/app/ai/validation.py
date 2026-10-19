"""Validation and repair of AI output before it can reach the database.

Rules enforced:
  * 0 <= awarded_marks <= max_marks
  * each criterion's awarded_marks is within its own maximum
  * sum(criteria awarded) == total awarded (the total is recomputed if not)
  * confidence is clamped to 0-1
  * contradictory / suspicious results are flagged for a human

We never fabricate content to "fix" a bad response — we clamp numbers, record a
validation note, and flag the answer for manual review.
"""

from __future__ import annotations

from dataclasses import replace

from app.ai.types import AnswerEvaluationResult, CriterionOutcome, OCRPageResult
from app.core.config import settings
from app.db.enums import ConfidenceLevel, confidence_level_for


class EvaluationValidation:
    def __init__(self, result: AnswerEvaluationResult, notes: list[str], is_valid: bool):
        self.result = result
        self.notes = notes
        self.is_valid = is_valid

    @property
    def needs_review(self) -> bool:
        return not self.is_valid or bool(self.result.flags) or self.result.confidence < settings.ai_confidence_medium


def validate_ocr(result: OCRPageResult) -> OCRPageResult:
    """Clamp OCR confidence and normalise region coordinates."""
    confidence = result.confidence
    if confidence is None:
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    clean_regions: list[dict] = []
    for region in result.regions or []:
        try:
            x0 = float(region.get("x0", 0.0))
            y0 = float(region.get("y0", 0.0))
            x1 = float(region.get("x1", 1.0))
            y1 = float(region.get("y1", 1.0))
        except (TypeError, ValueError):
            continue
        x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
        y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        clean_regions.append({"text": str(region.get("text", "")), "x0": x0, "y0": y0, "x1": x1, "y1": y1})

    return replace(result, confidence=confidence, regions=clean_regions)


def validate_evaluation(
    result: AnswerEvaluationResult,
    *,
    max_marks: float,
    criteria_scheme: list[dict] | None = None,
) -> EvaluationValidation:
    """Return a sanitised result plus any notes explaining the repairs made."""
    notes: list[str] = []
    is_valid = True

    # --- confidence --------------------------------------------------- #
    confidence = result.confidence
    if confidence is None or confidence != confidence:  # NaN guard
        confidence = 0.0
        notes.append("Confidence was missing; defaulted to 0.")
    confidence = max(0.0, min(1.0, float(confidence)))

    # --- criteria ----------------------------------------------------- #
    scheme = criteria_scheme or []
    scheme_by_name = {str(c.get("name", "")).strip().lower(): float(c.get("max_marks", 0) or 0) for c in scheme}

    clean_criteria: list[CriterionOutcome] = []
    for crit in result.criteria or []:
        key = crit.name.strip().lower()
        criterion_max = scheme_by_name.get(key, crit.max_marks)
        if criterion_max is None or criterion_max < 0:
            criterion_max = 0.0
        awarded = float(crit.awarded_marks or 0)
        if awarded < 0:
            notes.append(f"Criterion '{crit.name}' had negative marks; clamped to 0.")
            awarded = 0.0
        if awarded > criterion_max:
            notes.append(
                f"Criterion '{crit.name}' exceeded its maximum ({awarded:g} > "
                f"{criterion_max:g}); clamped."
            )
            awarded = criterion_max
        clean_criteria.append(
            CriterionOutcome(
                name=crit.name,
                max_marks=float(criterion_max),
                awarded_marks=float(awarded),
                satisfied=bool(crit.satisfied),
                comment=crit.comment,
            )
        )

    # --- totals ------------------------------------------------------- #
    awarded = float(result.awarded_marks or 0)
    if clean_criteria:
        criteria_sum = sum(c.awarded_marks for c in clean_criteria)
        if abs(criteria_sum - awarded) > 0.01:
            notes.append(
                f"Total ({awarded:g}) did not match the sum of criteria "
                f"({criteria_sum:g}); the criteria sum was used."
            )
            awarded = criteria_sum

    if awarded < 0:
        notes.append("Total was negative; clamped to 0.")
        awarded = 0.0
    if awarded > max_marks:
        notes.append(f"Total ({awarded:g}) exceeded the maximum ({max_marks:g}); clamped.")
        awarded = float(max_marks)
        is_valid = False

    # --- reasoning ---------------------------------------------------- #
    reasoning = (result.reasoning or "").strip()
    if not reasoning:
        notes.append("No reasoning was provided by the model.")
        is_valid = False

    if not clean_criteria and max_marks > 0:
        notes.append("The model returned no per-criterion breakdown.")

    # --- flags -------------------------------------------------------- #
    flags = list(dict.fromkeys(result.flags or []))
    if confidence < settings.ai_confidence_medium:
        flags.append("Low confidence evaluation — verify against the original script.")
    if result.contradictions:
        flags.append("The model identified possible factual errors or contradictions.")

    sanitized = replace(
        result,
        awarded_marks=round(awarded, 2),
        max_marks=float(max_marks),
        confidence=confidence,
        reasoning=reasoning,
        criteria=clean_criteria,
        flags=list(dict.fromkeys(flags)),
        validation_notes=notes,
    )
    return EvaluationValidation(sanitized, notes, is_valid)


def level_for(confidence: float) -> ConfidenceLevel:
    return confidence_level_for(
        confidence, settings.ai_confidence_high, settings.ai_confidence_medium
    )

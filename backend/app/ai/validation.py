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


def _clean_region(region: dict) -> dict | None:
    """Normalise one bounding box to 0-1 x0/y0/x1/y1. Returns None if unusable."""
    try:
        x0 = float(region.get("x0", 0.0))
        y0 = float(region.get("y0", 0.0))
        x1 = float(region.get("x1", 1.0))
        y1 = float(region.get("y1", 1.0))
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    out = {
        "text": str(region.get("text", "")),
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
    }
    conf = region.get("confidence")
    if conf is not None:
        try:
            out["confidence"] = max(0.0, min(1.0, float(conf)))
        except (TypeError, ValueError):
            pass
    return out


def validate_ocr(result: OCRPageResult) -> OCRPageResult:
    """Clamp OCR confidence and normalise region coordinates.

    Structure reported by the model (detected answers, diagrams, unreadable
    regions) is normalised the same way as page regions; anything unusable is
    dropped rather than repaired with invented geometry.
    """
    confidence = result.confidence
    if confidence is None:
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    clean_regions: list[dict] = []
    for region in result.regions or []:
        cleaned = _clean_region(region)
        if cleaned is not None:
            clean_regions.append(cleaned)

    clean_answers: list[dict] = []
    for answer in result.detected_answers or []:
        entry = dict(answer)
        entry["regions"] = [
            cleaned
            for r in (answer.get("regions") or [])
            if (cleaned := _clean_region(r)) is not None
        ]
        answer_conf = entry.get("confidence")
        if answer_conf is None:
            entry["confidence"] = confidence
        else:
            try:
                entry["confidence"] = max(0.0, min(1.0, float(answer_conf)))
            except (TypeError, ValueError):
                entry["confidence"] = confidence
        entry["transcription"] = str(entry.get("transcription") or "")
        entry["question_number"] = str(entry.get("question_number") or "").strip()
        entry["uncertain_segments"] = [
            str(s) for s in (entry.get("uncertain_segments") or []) if str(s).strip()
        ]
        clean_answers.append(entry)

    clean_diagrams: list[dict] = []
    for diagram in result.diagrams or []:
        entry = dict(diagram)
        region = entry.get("region")
        if isinstance(region, dict):
            cleaned = _clean_region(region)
            entry["region"] = cleaned
        clean_diagrams.append(entry)

    clean_unreadable: list[dict] = []
    for item in result.unreadable_regions or []:
        entry = dict(item)
        region = entry.get("region")
        if isinstance(region, dict):
            cleaned = _clean_region(region)
            entry["region"] = cleaned
        clean_unreadable.append(entry)

    return replace(
        result,
        confidence=confidence,
        regions=clean_regions,
        detected_answers=clean_answers,
        diagrams=clean_diagrams,
        unreadable_regions=clean_unreadable,
        manual_review_required=bool(result.manual_review_required),
    )


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
    evidence_flags: list[str] = []
    criteria_need_review = False
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

        evidence = [str(s).strip() for s in (crit.evidence or []) if str(s).strip()]
        missing = [str(s).strip() for s in (crit.missing_elements or []) if str(s).strip()]
        needs_review = bool(crit.needs_human_review)
        if needs_review:
            criteria_need_review = True
        # A partial award must be backed by quoted evidence from the answer.
        # Never invent evidence to satisfy the rule — flag it for a human.
        if 0 < awarded < criterion_max and not evidence:
            evidence_flags.append(
                f"Criterion '{crit.name}' received partial marks without cited "
                "evidence — verify manually."
            )

        clean_criteria.append(
            CriterionOutcome(
                name=crit.name,
                max_marks=float(criterion_max),
                awarded_marks=float(awarded),
                satisfied=bool(crit.satisfied),
                comment=crit.comment,
                evidence=evidence,
                missing_elements=missing,
                needs_human_review=needs_review,
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
    if result.needs_human_review:
        flags.append("The model asked for human review of this evaluation.")
    if criteria_need_review:
        flags.append("The model asked a human to double-check specific criteria.")
    flags.extend(evidence_flags)

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

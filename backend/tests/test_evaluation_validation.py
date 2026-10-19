"""Unit tests for the AI output validator and the mock provider."""

from __future__ import annotations

import pytest

from app.ai.mock import MockProvider
from app.ai.types import AnswerEvaluationResult, CriterionOutcome, EvaluationContext, OCRPageResult
from app.ai.validation import validate_evaluation, validate_ocr


def _result(**kwargs) -> AnswerEvaluationResult:
    base = dict(
        awarded_marks=5.0,
        max_marks=10.0,
        confidence=0.9,
        reasoning="Looks correct.",
        criteria=[
            CriterionOutcome(name="A", max_marks=3, awarded_marks=3, satisfied=True),
            CriterionOutcome(name="B", max_marks=3, awarded_marks=2, satisfied=True),
            CriterionOutcome(name="C", max_marks=4, awarded_marks=0, satisfied=False),
        ],
    )
    base.update(kwargs)
    return AnswerEvaluationResult(**base)


def test_valid_result_passes_through():
    validation = validate_evaluation(_result(), max_marks=10.0)
    assert validation.is_valid is True
    assert validation.result.awarded_marks == 5.0
    assert validation.notes == []


def test_awarded_marks_clamped_to_maximum():
    # No criteria returned, so the total is clamped directly to the maximum.
    validation = validate_evaluation(_result(awarded_marks=15.0, criteria=[]), max_marks=10.0)
    assert validation.result.awarded_marks == 10.0
    assert validation.is_valid is False
    assert any("exceeded the maximum" in n for n in validation.notes)


def test_total_corrected_to_criteria_sum_when_both_present():
    # With criteria present, the criteria sum is authoritative.
    validation = validate_evaluation(_result(awarded_marks=15.0), max_marks=10.0)
    assert validation.result.awarded_marks == 5.0
    assert any("did not match the sum" in n for n in validation.notes)


def test_criterion_marks_clamped_to_its_own_maximum():
    result = _result(
        awarded_marks=12.0,
        criteria=[
            CriterionOutcome(name="A", max_marks=3, awarded_marks=9, satisfied=True),
            CriterionOutcome(name="B", max_marks=3, awarded_marks=3, satisfied=True),
        ],
    )
    validation = validate_evaluation(result, max_marks=10.0)
    assert validation.result.criteria[0].awarded_marks == 3
    assert validation.result.awarded_marks == 6
    assert any("exceeded its maximum" in n for n in validation.notes)


def test_sum_mismatch_is_corrected_to_criteria_sum():
    validation = validate_evaluation(_result(awarded_marks=9.0), max_marks=10.0)
    # 3 + 2 + 0 == 5, so the total is corrected.
    assert validation.result.awarded_marks == 5.0
    assert any("did not match the sum" in n for n in validation.notes)


def test_negative_marks_are_clamped():
    result = _result(
        awarded_marks=-2.0,
        criteria=[CriterionOutcome(name="A", max_marks=3, awarded_marks=-1, satisfied=False)],
    )
    validation = validate_evaluation(result, max_marks=10.0)
    assert validation.result.awarded_marks == 0.0
    assert all(c.awarded_marks >= 0 for c in validation.result.criteria)


def test_low_confidence_is_flagged_for_review():
    validation = validate_evaluation(_result(confidence=0.3), max_marks=10.0)
    assert validation.result.confidence == 0.3
    assert validation.result.flags
    assert validation.needs_review is True


def test_missing_reasoning_marks_result_invalid():
    validation = validate_evaluation(_result(reasoning=""), max_marks=10.0)
    assert validation.is_valid is False
    assert any("No reasoning" in n for n in validation.notes)


def test_contradictions_add_a_flag():
    validation = validate_evaluation(
        _result(contradictions=["States TCP is connectionless"]), max_marks=10.0
    )
    assert any("factual errors" in f for f in validation.result.flags)


def test_confidence_is_clamped():
    validation = validate_evaluation(_result(confidence=1.7), max_marks=10.0)
    assert validation.result.confidence == 1.0


def test_ocr_validation_clamps_and_normalises_regions():
    result = OCRPageResult(
        text="hello",
        confidence=1.6,
        regions=[
            {"text": "a", "x0": -0.2, "y0": 0.1, "x1": 0.5, "y1": 0.9},
            {"text": "b", "x0": 0.5, "y0": 0.5, "x1": 0.5, "y1": 0.5},  # degenerate
            {"text": "c", "x0": "nonsense", "y0": 0, "x1": 1, "y1": 1},
        ],
    )
    cleaned = validate_ocr(result)
    assert cleaned.confidence == 1.0
    assert len(cleaned.regions) == 1
    assert cleaned.regions[0]["x0"] == 0.0


# --------------------------------------------------------------------------- #
# Mock provider
# --------------------------------------------------------------------------- #
def _context(criteria, transcription="A reasonable answer") -> EvaluationContext:
    return EvaluationContext(
        question_label="Q1",
        question_text="Explain the handshake.",
        question_type="explanation",
        max_marks=sum(c["max_marks"] for c in criteria),
        expected_answer="SYN, SYN-ACK, ACK",
        guidance=None,
        keywords=["SYN"],
        criteria=criteria,
        transcription=transcription,
        ocr_confidence=0.9,
        images=[b"fake-image"],
        submission_ref="abcd1234",
    )


CRITERIA = [
    {"name": "SYN packet", "description": None, "max_marks": 1},
    {"name": "SYN-ACK packet", "description": None, "max_marks": 1},
    {"name": "ACK packet", "description": None, "max_marks": 1},
]


async def test_mock_evaluation_is_deterministic():
    provider = MockProvider()
    context = _context(CRITERIA)
    first = await provider.evaluate_answer(context, prompt_version="theory_v1")
    second = await provider.evaluate_answer(context, prompt_version="theory_v1")

    assert first.awarded_marks == second.awarded_marks
    assert [c.awarded_marks for c in first.criteria] == [
        c.awarded_marks for c in second.criteria
    ]
    assert first.is_mock is True


async def test_mock_evaluation_respects_maximum():
    provider = MockProvider()
    result = await provider.evaluate_answer(_context(CRITERIA), prompt_version="theory_v1")
    assert 0 <= result.awarded_marks <= 3
    assert sum(c.awarded_marks for c in result.criteria) == pytest.approx(
        result.awarded_marks, abs=0.01
    )
    assert 0 <= result.confidence <= 1


async def test_mock_evaluation_produces_partial_marks_somewhere():
    """Across enough questions the mock must exercise partial credit."""
    provider = MockProvider()
    awarded_sets = set()
    for i in range(30):
        context = _context(
            [
                {"name": f"Concept {i}-{j}", "description": None, "max_marks": 2}
                for j in range(4)
            ],
            transcription=f"Answer variant {i} " * 20,
        )
        result = await provider.evaluate_answer(context, prompt_version="theory_v1")
        awarded_sets.add(tuple(c.awarded_marks for c in result.criteria))

    # At least one criterion was partially or zero awarded.
    assert any(any(a < 2 for a in combo) for combo in awarded_sets)
    # And at least one was fully awarded.
    assert any(all(a == 2 for a in combo) for combo in awarded_sets)


async def test_mock_ocr_is_deterministic_and_bounded():
    provider = MockProvider()
    image = b"\x89PNG\r\n\x1a\n" + b"x" * 500
    first = await provider.transcribe_page(image, page_number=1)
    second = await provider.transcribe_page(image, page_number=1)
    assert first.text == second.text
    assert 0 <= first.confidence <= 1
    assert first.is_mock is True

    # Different pages yield potentially different content but stay valid.
    other = await provider.transcribe_page(image, page_number=4)
    assert other.text

"""Question detection, multi-page answer segmentation and OCR validation.

Covers both sources of structure: the vision model's ``detected_answers``
(preferred) and the line-scan heuristic (fallback), including the continuation
cases where one answer spans several pages.
"""

from __future__ import annotations

import pytest

from app.ai.types import OCRPageResult
from app.ai.validation import validate_ocr
from app.segmentation.segmenter import parse_model_question_number, segment_answers


def page(page_number: int, text: str, *, detected=None, confidence=0.9, page_id=None) -> dict:
    return {
        "page_id": page_id or f"p{page_number}",
        "page_number": page_number,
        "text": text,
        "regions": [],
        "confidence": confidence,
        "detected_answers": detected or [],
    }


# --------------------------------------------------------------------------- #
# Model-reported question numbers
# --------------------------------------------------------------------------- #
def test_parse_model_question_number_accepts_common_formats():
    assert parse_model_question_number("1") == (1, "")
    assert parse_model_question_number("Q2") == (2, "")
    assert parse_model_question_number("Question 3") == (3, "")
    assert parse_model_question_number("1(a)") == (1, "a")
    assert parse_model_question_number("Q4(b)") == (4, "b")
    assert parse_model_question_number("2. c") == (2, "c")
    assert parse_model_question_number("5(i)") == (5, "i")


def test_parse_model_question_number_rejects_junk():
    assert parse_model_question_number("") == (None, "")
    assert parse_model_question_number(None) == (None, "")
    assert parse_model_question_number("192.168.10.0/26") == (None, "")
    assert parse_model_question_number("see the next page") == (None, "")
    assert parse_model_question_number("12345") == (None, "")


# --------------------------------------------------------------------------- #
# Model-detected structure
# --------------------------------------------------------------------------- #
def test_model_detected_answers_are_used_directly():
    pages = [
        page(
            1,
            "Q1. TCP is connection oriented.",
            detected=[
                {
                    "question_number": "1",
                    "transcription": "TCP is connection oriented.",
                    "regions": [{"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2}],
                    "confidence": 0.93,
                }
            ],
        )
    ]
    result = segment_answers(pages, known_question_numbers=[1, 2])

    answer = result["answers"][1]
    assert answer.detected_by_model is True
    assert "connection oriented" in answer.transcription
    assert answer.page_numbers == [1]
    assert answer.confidence == pytest.approx(0.93)
    # Question 2 was never written: guaranteed an explicit empty entry.
    assert result["answers"][2].has_content is False
    assert result["answers"][2].boundary_uncertain is True


def test_multi_page_answer_is_associated_with_both_pages():
    """Q1 starts on page 1 and continues on page 2 — one answer, two pages."""
    pages = [
        page(
            1,
            "Q1. The three way handshake:",
            detected=[
                {
                    "question_number": "1",
                    "transcription": "The three way handshake: the client sends SYN.",
                    "continues_on_next_page": True,
                    "regions": [{"x0": 0.1, "y0": 0.5, "x1": 0.9, "y1": 0.9}],
                    "confidence": 0.9,
                }
            ],
        ),
        page(
            2,
            "the server replies SYN-ACK and the client ACK.\nQ2. 62 hosts",
            detected=[
                {
                    "question_number": "1",
                    "started_on_previous_page": True,
                    "transcription": "the server replies SYN-ACK and the client ACK.",
                    "continues_on_next_page": False,
                    "regions": [{"x0": 0.1, "y0": 0.05, "x1": 0.9, "y1": 0.2}],
                    "confidence": 0.88,
                },
                {
                    "question_number": "2",
                    "transcription": "62 hosts",
                    "confidence": 0.95,
                },
            ],
        ),
    ]
    result = segment_answers(pages, known_question_numbers=[1, 2])

    q1 = result["answers"][1]
    assert q1.page_numbers == [1, 2]
    assert "client sends SYN" in q1.transcription
    assert "SYN-ACK" in q1.transcription
    assert len(q1.regions) == 2
    assert {r["page_number"] for r in q1.regions} == {1, 2}
    # Continuation resolved on both sides: not uncertain.
    assert q1.unresolved_continuation is False
    assert q1.started_on_previous_page is False
    assert q1.boundary_uncertain is False

    q2 = result["answers"][2]
    assert q2.page_numbers == [2]
    assert q2.transcription == "62 hosts"


def test_unresolved_continuation_is_flagged_for_the_teacher():
    pages = [
        page(
            1,
            "Q1. starts here",
            detected=[
                {
                    "question_number": "1",
                    "transcription": "starts here",
                    "continues_on_next_page": True,
                    "confidence": 0.9,
                }
            ],
        ),
        page(2, "unrelated text", detected=[]),
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert answer.unresolved_continuation is True
    assert answer.boundary_uncertain is True


def test_answer_claimed_to_start_earlier_is_flagged():
    pages = [
        page(
            1,
            "Q2. tail end of an answer",
            detected=[
                {
                    "question_number": "2",
                    "started_on_previous_page": True,
                    "transcription": "tail end of an answer",
                    "confidence": 0.8,
                }
            ],
        )
    ]
    result = segment_answers(pages, known_question_numbers=[2])
    answer = result["answers"][2]
    assert answer.started_on_previous_page is True
    assert answer.boundary_uncertain is True


def test_sub_questions_roll_up_to_their_parent_question():
    pages = [
        page(
            1,
            "Q1(a) one\nQ1(b) two",
            detected=[
                {"question_number": "1(a)", "transcription": "one", "confidence": 0.9},
                {"question_number": "1(b)", "transcription": "two", "confidence": 0.9},
            ],
        )
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert answer.sub_labels == ["a", "b"]
    assert "one" in answer.transcription and "two" in answer.transcription


def test_unparsable_question_numbers_are_never_guessed():
    pages = [
        page(
            1,
            "some prose",
            detected=[
                {"question_number": "maybe 3?", "transcription": "prose", "confidence": 0.9}
            ],
        )
    ]
    result = segment_answers(pages, known_question_numbers=[1, 2])
    # Nothing was attributed to a question the model could not identify.
    assert result["answers"][1].has_content is False
    assert result["answers"][2].has_content is False


def test_page_without_model_structure_falls_back_to_the_line_scan():
    """A page whose model output has no structure is still segmented."""
    pages = [
        page(
            1,
            "Q1. first part",
            detected=[
                {
                    "question_number": "1",
                    "transcription": "first part",
                    "continues_on_next_page": True,
                    "confidence": 0.9,
                }
            ],
        ),
        page(2, "continued without a heading here"),
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    # The continuation page attached to the still-open answer.
    assert "continued without a heading" in answer.transcription
    assert answer.page_numbers == [1, 2]


def test_low_confidence_model_output_flags_uncertain_segments():
    pages = [
        page(
            1,
            "Q1. unreadable mess",
            detected=[
                {
                    "question_number": "1",
                    "transcription": "unreadable [illegible] mess",
                    "uncertain_segments": ["illegible"],
                    "confidence": 0.4,
                }
            ],
        )
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert answer.uncertain_segments == ["illegible"]
    assert answer.boundary_uncertain is True
    assert answer.confidence == 0.4


# --------------------------------------------------------------------------- #
# Heuristic fallback (no model structure at all)
# --------------------------------------------------------------------------- #
def test_heuristic_still_works_without_model_structure():
    pages = [
        page(1, "Q1. alpha\nQ2. beta"),
        page(2, "gamma under Q2"),
    ]
    result = segment_answers(pages, known_question_numbers=[1, 2])
    assert "alpha" in result["answers"][1].transcription
    assert "beta" in result["answers"][2].transcription
    assert "gamma" in result["answers"][2].transcription
    assert result["answers"][2].page_numbers == [1, 2]


# --------------------------------------------------------------------------- #
# OCR output validation
# --------------------------------------------------------------------------- #
def test_validate_ocr_normalises_detected_answer_structure():
    raw = OCRPageResult(
        text="Q1. hi",
        confidence=1.7,  # out of range: clamped
        regions=[{"text": "Q1. hi", "x0": 1.2, "y0": -0.3, "x1": 0.8, "y1": 0.4}],
        detected_answers=[
            {
                "question_number": " 1 ",
                "transcription": "hi",
                "confidence": 2.0,
                "regions": [{"x0": 0.2, "y0": 0.2, "x1": 0.5, "y1": 0.5}],
                "uncertain_segments": ["", "hard to read"],
            },
            {
                "question_number": "2",
                "transcription": "",
                "confidence": None,
                "regions": [{"x0": 9, "y0": 9, "x1": 9, "y1": 9}],  # degenerate
                "uncertain_segments": None,
            },
        ],
        diagrams=[{"caption": "tree", "region": {"x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.4}}],
        unreadable_regions=[{"reason": "smudge", "region": {"x0": 0.9, "y0": 0.9, "x1": 2, "y1": 2}}],
        manual_review_required=True,
    )
    clean = validate_ocr(raw)

    assert clean.confidence == 1.0
    # Out-of-range coordinates are clamped into [0, 1].
    assert 0.0 <= clean.regions[0]["x0"] <= 1.0
    assert 0.0 <= clean.regions[0]["x1"] <= 1.0

    first, second = clean.detected_answers
    assert first["question_number"] == "1"
    assert first["confidence"] == 1.0
    assert first["uncertain_segments"] == ["hard to read"]
    assert second["confidence"] == clean.confidence  # falls back to page confidence
    assert second["regions"] == []  # degenerate box dropped, not invented
    assert second["uncertain_segments"] == []
    assert clean.manual_review_required is True
    assert clean.diagrams[0]["region"]["x1"] == 0.4
    assert clean.unreadable_regions[0]["region"]["x1"] == 1.0


def test_validate_ocr_drops_unusable_regions():
    raw = OCRPageResult(
        text="x",
        regions=[
            {"text": "ok", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5},
            {"text": "zero size", "x0": 0.5, "y0": 0.5, "x1": 0.5, "y1": 0.5},
            {"text": "garbage", "x0": "abc", "y0": 0.1, "x1": 0.5, "y1": 0.5},
        ],
    )
    clean = validate_ocr(raw)
    assert len(clean.regions) == 1
    assert clean.regions[0]["text"] == "ok"

"""Question ↔ answer segmentation heuristics."""

from __future__ import annotations

from app.segmentation import segment_answers


def _page(number: int, text: str, regions=None, confidence=0.9):
    return {
        "page_id": str(number),
        "page_number": number,
        "text": text,
        "regions": regions or [],
        "confidence": confidence,
    }


def test_basic_segmentation_by_question_heading():
    pages = [_page(1, "Q1. First answer here\nQ2. Second answer here")]
    result = segment_answers(pages, known_question_numbers=[1, 2])
    answers = result["answers"]
    assert set(answers) == {1, 2}
    assert "First answer" in answers[1].transcription
    assert "Second answer" in answers[2].transcription


def test_answer_continues_across_pages():
    pages = [
        _page(1, "Q1. This answer starts on page one"),
        _page(2, "and it continues onto page two."),
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert "starts on page one" in answer.transcription
    assert "continues onto page two" in answer.transcription
    assert answer.page_numbers == [1, 2]
    assert len(answer.page_ids) == 2


def test_second_question_starts_mid_page():
    pages = [_page(1, "Q1. First\nQ2. Second\nQ2 continued")]
    result = segment_answers(pages, known_question_numbers=[1, 2])
    assert "First" in result["answers"][1].transcription
    assert "Second" in result["answers"][2].transcription
    assert result["answers"][2].page_numbers == [1]


def test_skipped_question_is_still_represented():
    pages = [_page(1, "Q1. Answered\nQ3. Also answered")]
    result = segment_answers(pages, known_question_numbers=[1, 2, 3])
    assert set(result["answers"]) == {1, 2, 3}
    assert not result["answers"][2].has_content
    assert result["answers"][2].boundary_uncertain is True


def test_heading_variations_are_recognised():
    variants = [
        "Q1. text a",
        "Q.1 text b",
        "Question 1 text c",
        "1. text d",
        "1) text e",
        "Ans 1 text f",
        "Answer 1: text g",
    ]
    for variant in variants:
        result = segment_answers([_page(1, variant)], known_question_numbers=[1])
        assert result["answers"][1].has_content, f"failed for {variant!r}"


def test_subquestion_markers_attach_to_parent():
    pages = [_page(1, "Q1. Main answer\nQ1(a) sub part a\nQ1(b) sub part b")]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert "Main answer" in answer.transcription
    assert "sub part a" in answer.transcription
    assert "sub part b" in answer.transcription
    # Only one parent answer is produced.
    assert set(result["answers"]) == {1}


def test_content_before_first_heading_is_unassigned():
    pages = [_page(1, "Name: Jane Doe\nRoll: 123\nQ1. The answer")]
    result = segment_answers(pages, known_question_numbers=[1])
    assert result["answers"][1].transcription.strip() == "The answer"
    unassigned_text = " ".join(u["text"] for u in result["unassigned"])
    assert "Jane Doe" in unassigned_text


def test_low_confidence_pages_mark_boundaries_uncertain():
    pages = [_page(1, "Q1. Some answer", confidence=0.4)]
    result = segment_answers(pages, known_question_numbers=[1])
    assert result["answers"][1].boundary_uncertain is True


def test_regions_are_preserved_with_coordinates():
    regions = [
        {"text": "Q1. Some answer", "x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
    ]
    pages = [_page(1, "Q1. Some answer", regions=regions)]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    # The heading line itself is not content, so no region is captured for it.
    assert isinstance(answer.regions, list)


def test_regions_carry_their_page_reference():
    """Each region records the page it was read from, for the page mapping."""
    regions = [
        {"text": "first line", "x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
        {"text": "second line", "x0": 0.1, "y0": 0.4, "x1": 0.9, "y1": 0.5},
    ]
    pages = [_page(2, "Q1. first line\nsecond line", regions=regions)]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert len(answer.regions) == 2
    assert all(region["page_id"] == "2" for region in answer.regions)
    assert all(region["page_number"] == 2 for region in answer.regions)
    assert all(region["y0"] < region["y1"] for region in answer.regions)


def test_multi_page_answer_records_regions_on_each_page():
    page_one = [{"text": "starts", "x0": 0.1, "y0": 0.7, "x1": 0.9, "y1": 0.8}]
    page_two = [{"text": "continues", "x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2}]
    pages = [
        _page(1, "Q1. starts here", regions=page_one),
        _page(2, "continues here", regions=page_two),
    ]
    result = segment_answers(pages, known_question_numbers=[1])
    answer = result["answers"][1]
    assert answer.page_numbers == [1, 2]
    assert sorted({region["page_number"] for region in answer.regions}) == [1, 2]


def test_prose_containing_numbers_is_not_treated_as_a_heading():
    long_line = (
        "1. " + "This is a very long explanatory sentence that continues well beyond the "
        "heading threshold and therefore must not be mistaken for a question marker. " * 2
    )
    pages = [_page(1, f"Q1. Real answer\n{long_line}")]
    result = segment_answers(pages, known_question_numbers=[1])
    # The long line belongs to Q1, no spurious Q heading was created.
    assert set(result["answers"]) == {1}

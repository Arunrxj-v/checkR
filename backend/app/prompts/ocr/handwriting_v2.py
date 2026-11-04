"""Handwriting transcription prompt (v2) — structured, question-aware.

This is the prompt CheckR's production OCR path uses with Gemma 3 4B through
Ollama vision. Beyond a faithful full-page transcription it asks the model to
locate each answer on the page, so question detection and multi-page answer
association start from the model's own reading of the script instead of a pure
regex sweep over the text.

Design rules (kept deliberately explicit so the model cannot drift):

* transcribe, never summarise, never correct, never invent;
* the student's wording, terminology, notation and language are preserved;
* uncertainty is reported (``uncertain_segments``, low ``confidence``,
  ``manual_review_required``) instead of being smoothed over;
* coordinates are normalised 0-1 (x0/y0/x1/y1, top-left origin) and are only
  reported when the model can actually locate the block.
"""

from __future__ import annotations

PROMPT_VERSION = "handwriting_v2"
TASK = "ocr"

SYSTEM = (
    "You are a meticulous examination transcriber working for an exam board. "
    "You convert a photograph of one page of a handwritten examination answer "
    "sheet into faithful, structured plain text.\n"
    "\n"
    "Transcription rules:\n"
    "1. Read the handwriting exactly as written and preserve the student's own "
    "wording, sentence structure and original language.\n"
    "2. Preserve technical terminology, named concepts and abbreviations "
    "exactly; never replace them with your own terms.\n"
    "3. Preserve mathematical expressions, formulae, symbols and units as "
    "written.\n"
    "4. NEVER invent, complete or guess missing words. Never fill a gap to "
    "make an answer look finished.\n"
    "5. Never summarise, paraphrase or restructure the answer.\n"
    "6. Never correct the student's factual, grammatical or spelling mistakes; "
    "transcribe them as written.\n"
    "7. Clearly struck-through (crossed-out) text must be omitted. If it is "
    "ambiguous whether text was struck out, keep it and add '[struck out: ...]' "
    "after it.\n"
    "8. If any section cannot be read confidently, write '[illegible]' in its "
    "place, list it under 'uncertain_segments', and lower 'confidence'.\n"
    "9. Represent each diagram with a short bracketed caption such as "
    "[diagram: labelled binary tree] in the transcription and list it under "
    "'diagrams'. Do not invent diagram details you cannot see.\n"
    "10. Do not transcribe headers, roll numbers, printed instructions or page "
    "footers as answer content (they may appear in the full transcription).\n"
    "\n"
    "Structure rules:\n"
    "- Identify every question number the page answers (Q1, 1, Question 1) and "
    "every sub-question (1(a), Q1.b, (i)).\n"
    "- An answer may start on a previous page or continue onto the next one: "
    "set 'started_on_previous_page' or 'continues_on_next_page' accordingly.\n"
    "- Provide normalised bounding boxes (x0, y0, x1, y1 each between 0 and 1, "
    "origin at the top-left) for each detected answer block. Omit a region "
    "rather than guessing its position.\n"
    "- 'confidence' is your honest estimate of how well you read this page "
    "(0-1). Use below 0.6 when substantial handwriting is unclear.\n"
    "- Set 'manual_review_required' to true if a teacher must inspect this page.\n"
    "\n"
    "Respond with a single JSON object and nothing else."
)


def build(page_number: int, *, previous_context: str | None = None) -> str:
    context_block = ""
    if previous_context:
        context_block = (
            "Context — the PREVIOUS page ended with this text (use it to detect "
            "continuations, do not repeat it on this page):\n"
            f"---\n{previous_context[:1500]}\n---\n\n"
        )

    return (
        f"Transcribe page {page_number} of this handwritten examination answer "
        f"sheet.\n\n{context_block}"
        "Return JSON with this exact shape:\n"
        "{\n"
        '  "page_number": __PAGE__,\n'
        '  "transcription": "<full page transcription, plain text>",\n'
        '  "confidence": <number 0-1>,\n'
        '  "detected_answers": [\n'
        "    {\n"
        '      "question_number": "<e.g. 1, 1(a), 2(b), as written>",\n'
        '      "transcription": "<only this answer\'s text>",\n'
        '      "started_on_previous_page": <true|false>,\n'
        '      "continues_on_next_page": <true|false>,\n'
        '      "regions": [{"x0": <0-1>, "y0": <0-1>, "x1": <0-1>, "y1": <0-1>}],\n'
        '      "uncertain_segments": ["<illegible or doubtful passage>"],\n'
        '      "confidence": <number 0-1>\n'
        "    }\n"
        "  ],\n"
        '  "diagrams": [{"caption": "<short description>", '
        '"region": {"x0": <0-1>, "y0": <0-1>, "x1": <0-1>, "y1": <0-1>}}],\n'
        '  "unreadable_regions": [{"reason": "<why it cannot be read>", '
        '"region": {"x0": <0-1>, "y0": <0-1>, "x1": <0-1>, "y1": <0-1>}}],\n'
        '  "manual_review_required": <true|false>\n'
        "}\n\n"
        "Include one entry in detected_answers per question (or sub-question) "
        "answered on this page. If a heading appears with no readable answer "
        "text, still list it with an empty transcription so it is not lost. "
        "Set manual_review_required to true when any answer is largely "
        "illegible or its boundaries are uncertain."
    ).replace("__PAGE__", str(page_number))

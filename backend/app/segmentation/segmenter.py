"""Question ↔ answer segmentation.

Handwritten scripts do not line up with page boundaries: an answer can start on
one page, continue on the next, be interleaved with a diagram, or be skipped
entirely. This module reconstructs which written content belongs to which
question.

Two sources of structure are combined, in order of trust:

1. **Model-detected answers** — when the vision model returned
   ``detected_answers`` for a page (question numbers, sub-questions,
   continuation flags, regions, uncertain segments), that reading is used
   directly and merged across pages: a block flagged
   ``continues_on_next_page`` on page N is joined to the block flagged
   ``started_on_previous_page`` on page N+1, so one answer spans the pages it
   was actually written on.
2. **Heuristic line scan** — for pages where the model reported no structure
   (or as a complete fallback when no page has any), question headings are
   detected with common handwritten numbering conventions (``Q1``, ``Q.1``,
   ``Question 1``, ``Ans 1``, ``1.``, ``1)``) and consecutive lines are grouped
   under the preceding heading, across pages.

The result is deliberately conservative: uncertain boundaries, unresolved
continuations and empty answers are flagged for the teacher instead of being
silently resolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches a question heading; captures the question number and an optional part.
_HEADING_PATTERNS = [
    re.compile(
        r"^\s*(?:q(?:uestion)?|ans(?:wer)?|प्र)\s*[.:\-)]?\s*(\d{1,2})\s*(?:\(([a-zA-Z])\)|([a-zA-Z])[.)])?\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(\d{1,2})\s*[.)]\s+", re.IGNORECASE),
    re.compile(r"^\s*\(\s*(\d{1,2})\s*\)\s+", re.IGNORECASE),
]
# A heading line should be short; long lines merely *containing* "1." are prose.
_MAX_HEADING_LENGTH = 90

#: Strict parser for a model-reported question number ("1", "Q1", "Question
#: 2(b)", "3."). Rejects anything with trailing junk (an IP address is not a
#: question number).
_MODEL_QUESTION_RE = re.compile(
    r"(?:q(?:uestion)?|ans(?:wer)?)?\s*[.:\-)]*\s*(\d{1,2})"
    r"(?:\s*[.]\s*|\s+)?"
    r"(?:\(\s*([a-zA-Z]|\d{1,2}|[ivxIVX]+)\s*\)|([a-zA-Z])(?:[.)])?)?"
    r"\s*$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Line:
    page_id: str
    page_number: int
    text: str
    region: dict | None = None


@dataclass(slots=True)
class DetectedAnswer:
    question_number: int
    label: str
    transcriptions: list[str] = field(default_factory=list)
    page_ids: list[str] = field(default_factory=list)
    page_numbers: list[int] = field(default_factory=list)
    regions: list[dict] = field(default_factory=list)   # incl. page_id
    confidences: list[float] = field(default_factory=list)
    boundary_uncertain: bool = False
    #: Sub-question labels seen for this question ("a", "b", "i", …).
    sub_labels: list[str] = field(default_factory=list)
    #: The model said this answer began on an earlier page but no earlier
    #: block was found — part of the answer may be missing.
    started_on_previous_page: bool = False
    #: The model said this answer continues, but no continuation arrived.
    unresolved_continuation: bool = False
    uncertain_segments: list[str] = field(default_factory=list)
    #: True when the structure came from the model rather than the heuristic.
    detected_by_model: bool = False

    @property
    def transcription(self) -> str:
        return "\n".join(t for t in self.transcriptions if t.strip()).strip()

    @property
    def confidence(self) -> float | None:
        vals = [c for c in self.confidences if c is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    @property
    def has_content(self) -> bool:
        return bool(self.transcription.strip())


@dataclass(slots=True)
class HeadingMatch:
    number: int
    remainder: str


def _match_heading(line: str) -> HeadingMatch | None:
    """Return a heading match (question number + any trailing content) or None."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LENGTH:
        return None
    for pattern in _HEADING_PATTERNS:
        m = pattern.match(stripped)
        if m:
            try:
                num = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= num <= 99:
                remainder = stripped[m.end():].strip()
                # Drop a separator the heading pattern did not consume (e.g. the
                # "." in "Q1. The answer") so answer text starts clean.
                remainder = re.sub(r"^[.:;,\-)\]}]+[\s]*", "", remainder).strip()
                return HeadingMatch(number=num, remainder=remainder)
    return None


def parse_model_question_number(raw: object) -> tuple[int | None, str]:
    """Parse a model-reported question number.

    Returns ``(number, sub_label)`` — e.g. ``"Q2(b)"`` → ``(2, "b")``. Returns
    ``(None, "")`` when the value is not a plausible question number.
    """
    if raw is None:
        return None, ""
    text = str(raw).strip()
    if not text or len(text) > 40:
        return None, ""
    m = _MODEL_QUESTION_RE.match(text)
    if not m:
        return None, ""
    try:
        number = int(m.group(1))
    except (TypeError, ValueError):
        return None, ""
    if not 1 <= number <= 99:
        return None, ""
    sub = (m.group(2) or m.group(3) or "").strip().lower()
    return number, sub


def flatten_pages(pages: list[dict]) -> list[Line]:
    """Turn per-page OCR output into an ordered list of lines.

    ``pages`` items: ``{page_id, page_number, text, regions, confidence}``.
    """
    lines: list[Line] = []
    for page in sorted(pages, key=lambda p: p.get("page_number", 0)):
        page_id = str(page.get("page_id"))
        page_number = int(page.get("page_number", 0))
        regions = page.get("regions") or []
        raw_lines = [ln for ln in str(page.get("text", "")).splitlines()]
        for idx, raw in enumerate(raw_lines):
            region = None
            if idx < len(regions) and isinstance(regions[idx], dict):
                region = regions[idx]
            else:
                # Fall back to a region whose recorded text starts with this line.
                for candidate in regions:
                    ctext = str(candidate.get("text", "")).strip()
                    if ctext and (ctext.startswith(raw.strip()) or raw.strip().startswith(ctext)):
                        region = candidate
                        break
            lines.append(Line(page_id=page_id, page_number=page_number, text=raw, region=region))
    return lines


def _attach_region(answer: DetectedAnswer, region: dict, *, page_id: str, page_number: int, text: str) -> None:
    answer.regions.append(
        {
            "page_id": page_id,
            # Carried alongside the id so the page association survives
            # persistence without re-deriving it from line order.
            "page_number": page_number,
            "x0": float(region.get("x0", 0.0) or 0.0),
            "y0": float(region.get("y0", 0.0) or 0.0),
            "x1": float(region.get("x1", 1.0) or 1.0),
            "y1": float(region.get("y1", 1.0) or 1.0),
            "text": text.strip(),
            "confidence": region.get("confidence"),
        }
    )


def _get_answer(answers: dict[int, DetectedAnswer], number: int) -> DetectedAnswer:
    answer = answers.get(number)
    if answer is None:
        answer = DetectedAnswer(question_number=number, label=f"Q{number}")
        answers[number] = answer
    return answer


def _finalise(answers: dict[int, DetectedAnswer], page_confidence: dict[int, float | None]) -> dict[int, DetectedAnswer]:
    for answer in answers.values():
        # Per-block model confidences win; otherwise average the page's.
        if not answer.confidences:
            answer.confidences = [
                page_confidence.get(pn)
                for pn in answer.page_numbers
                if page_confidence.get(pn) is not None
            ]
        # Flag when an answer spans pages whose OCR confidence is weak.
        low = [c for c in answer.confidences if c is not None and c < 0.65]
        if low:
            answer.boundary_uncertain = True
        if not answer.transcriptions:
            answer.boundary_uncertain = True
        if answer.started_on_previous_page or answer.unresolved_continuation:
            answer.boundary_uncertain = True
        if answer.uncertain_segments:
            answer.boundary_uncertain = True
    return answers


def _segment_heuristic(
    pages: list[dict],
    answers: dict[int, DetectedAnswer],
    current: DetectedAnswer | None,
    unassigned: list[Line],
    page_confidence: dict[int, float | None],
) -> tuple[DetectedAnswer | None, list[Line]]:
    """Line-scan the pages (stateful across calls) under ``current``."""
    for line in flatten_pages(pages):
        heading = _match_heading(line.text)
        if heading is not None:
            current = _get_answer(answers, heading.number)
            # Record the page even when the heading line carries no content.
            if line.page_id not in current.page_ids:
                current.page_ids.append(line.page_id)
                current.page_numbers.append(line.page_number)
            # Any text after the marker on the same line is real answer content.
            if heading.remainder:
                current.transcriptions.append(heading.remainder)
                if line.page_id not in current.page_ids:
                    current.page_ids.append(line.page_id)
                    current.page_numbers.append(line.page_number)
                if line.region:
                    _attach_region(
                        current, line.region, page_id=line.page_id,
                        page_number=line.page_number, text=heading.remainder,
                    )
            continue

        if current is None:
            if line.text.strip():
                unassigned.append(line)
            continue

        if line.text.strip():
            current.transcriptions.append(line.text)
            if line.page_id not in current.page_ids:
                current.page_ids.append(line.page_id)
                current.page_numbers.append(line.page_number)
            if line.region:
                _attach_region(
                    current, line.region, page_id=line.page_id,
                    page_number=line.page_number, text=line.text,
                )
    return current, unassigned


def _segment_model(
    pages: list[dict],
    answers: dict[int, DetectedAnswer],
    unassigned: list[Line],
    page_confidence: dict[int, float | None],
) -> tuple[DetectedAnswer | None, list[Line]]:
    """Use the vision model's own question detection, per page in order.

    Pages without model structure fall back to the line scan, seeded with the
    currently open answer so a continuation page without a detected block still
    attaches to the answer it continues.
    """
    current: DetectedAnswer | None = None
    continuation_open: dict[int, bool] = {}

    for page in sorted(pages, key=lambda p: p.get("page_number", 0)):
        page_id = str(page.get("page_id"))
        page_number = int(page.get("page_number", 0))
        detected = page.get("detected_answers") or []

        if not detected:
            # No structure from the model on this page: line-scan it, keeping
            # any answer that was still open from the previous page.
            current, unassigned = _segment_heuristic(
                [page], answers, current, unassigned, page_confidence
            )
            continue

        for block in detected:
            number, sub = parse_model_question_number(block.get("question_number"))
            if number is None:
                # Unparsable question label: never guess which question it is.
                continue

            existed = number in answers
            answer = _get_answer(answers, number)
            answer.detected_by_model = True

            if sub and sub not in answer.sub_labels:
                answer.sub_labels.append(sub)

            text = str(block.get("transcription") or "").strip()
            if text:
                answer.transcriptions.append(text)

            if page_id not in answer.page_ids:
                answer.page_ids.append(page_id)
                answer.page_numbers.append(page_number)

            for region in block.get("regions") or []:
                if not isinstance(region, dict):
                    continue
                _attach_region(
                    answer, region, page_id=page_id, page_number=page_number,
                    text=text or str(region.get("text", "")),
                )

            conf = block.get("confidence")
            if conf is None:
                conf = page_confidence.get(page_number)
            if conf is not None:
                try:
                    answer.confidences.append(float(conf))
                except (TypeError, ValueError):
                    pass

            for segment in block.get("uncertain_segments") or []:
                segment = str(segment).strip()
                if segment and segment not in answer.uncertain_segments:
                    answer.uncertain_segments.append(segment)

            if block.get("started_on_previous_page") and not existed:
                # The model says the answer began on an earlier page, but no
                # earlier block was found: part of the answer may be missing.
                answer.started_on_previous_page = True

            # A block arriving after an open continuation resolves it.
            if continuation_open.get(number):
                continuation_open[number] = False
            continuation_open[number] = bool(block.get("continues_on_next_page"))

            current = answer

    # Unresolved continuations: an answer that says "continues" but whose
    # continuation never arrived.
    for number, open_flag in continuation_open.items():
        if open_flag and number in answers:
            answers[number].unresolved_continuation = True

    return current, unassigned


def segment_answers(pages: list[dict], *, known_question_numbers: list[int] | None = None) -> dict:
    """Segment page OCR into per-question blocks.

    Returns ``{"answers": {question_number: DetectedAnswer}, "unassigned": [...]}``.
    Uses the model's ``detected_answers`` when any page provided them, with the
    line-scan heuristic covering pages that did not.
    """
    answers: dict[int, DetectedAnswer] = {}
    unassigned: list[Line] = []
    page_confidence = {int(p.get("page_number", 0)): p.get("confidence") for p in pages}

    has_model_structure = any(p.get("detected_answers") for p in pages)
    if has_model_structure:
        _segment_model(pages, answers, unassigned, page_confidence)
    else:
        _segment_heuristic(pages, answers, None, unassigned, page_confidence)

    answers = _finalise(answers, page_confidence)

    # Guarantee an entry for every question the exam actually defines, so skipped
    # questions surface as explicit "not attempted" answers rather than vanishing.
    for number in known_question_numbers or []:
        if number not in answers:
            answers[number] = DetectedAnswer(
                question_number=number, label=f"Q{number}", boundary_uncertain=True
            )

    return {
        "answers": dict(sorted(answers.items())),
        "unassigned": [
            {"page_id": line.page_id, "page_number": line.page_number, "text": line.text}
            for line in unassigned
        ],
    }

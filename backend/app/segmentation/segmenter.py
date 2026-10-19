"""Question ↔ answer segmentation.

Handwritten scripts do not line up with page boundaries: an answer can start on
one page, continue on the next, be interleaved with a diagram, or be skipped
entirely. This module reconstructs which written content belongs to which
question using the per-page OCR output.

The strategy is deliberately explainable rather than clever:

1. Flatten every page's transcription into ordered lines, each carrying the
   page it came from and, where the vision provider gave one, a bounding box.
2. Detect question headings using a set of common handwritten numbering
   conventions (``Q1``, ``Q.1``, ``Question 1``, ``Ans 1``, ``1.``, ``1)``).
3. Group consecutive lines under the heading that precedes them, across pages.
4. Sub-question markers (``Q1(a)``) attach to their parent question.
5. Anything written before the first heading is recorded as unassigned.

The result is intentionally conservative: uncertain boundaries and empty
answers are flagged for the teacher instead of being silently resolved.
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


def segment_answers(pages: list[dict], *, known_question_numbers: list[int] | None = None) -> dict:
    """Segment page OCR into per-question blocks.

    Returns ``{"answers": {question_number: DetectedAnswer}, "unassigned": [...]}``.
    """
    lines = flatten_pages(pages)
    answers: dict[int, DetectedAnswer] = {}
    unassigned: list[Line] = []
    current: DetectedAnswer | None = None
    page_confidence = {int(p.get("page_number", 0)): p.get("confidence") for p in pages}

    def add_content(answer: DetectedAnswer, text: str, line: Line) -> None:
        answer.transcriptions.append(text)
        if line.page_id not in answer.page_ids:
            answer.page_ids.append(line.page_id)
            answer.page_numbers.append(line.page_number)
        if line.region:
            answer.regions.append(
                {
                    "page_id": line.page_id,
                    # Carried alongside the id so the page association survives
                    # persistence without re-deriving it from line order.
                    "page_number": line.page_number,
                    "x0": float(line.region.get("x0", 0.0) or 0.0),
                    "y0": float(line.region.get("y0", 0.0) or 0.0),
                    "x1": float(line.region.get("x1", 1.0) or 1.0),
                    "y1": float(line.region.get("y1", 1.0) or 1.0),
                    "text": text.strip(),
                    "confidence": line.region.get("confidence"),
                }
            )

    for line in lines:
        heading = _match_heading(line.text)
        if heading is not None:
            current = answers.get(heading.number)
            if current is None:
                current = DetectedAnswer(question_number=heading.number, label=f"Q{heading.number}")
                answers[heading.number] = current
            # Record the page even when the heading line carries no content.
            if line.page_id not in current.page_ids:
                current.page_ids.append(line.page_id)
                current.page_numbers.append(line.page_number)
            # Any text after the marker on the same line is real answer content.
            if heading.remainder:
                add_content(current, heading.remainder, line)
            continue

        if current is None:
            if line.text.strip():
                unassigned.append(line)
            continue

        if line.text.strip():
            add_content(current, line.text, line)

    for answer in answers.values():
        answer.confidences = [
            page_confidence.get(pn) for pn in answer.page_numbers if page_confidence.get(pn) is not None
        ]
        # Flag when an answer spans pages whose OCR confidence is weak.
        low = [c for c in answer.confidences if c is not None and c < 0.65]
        answer.boundary_uncertain = bool(low)
        if not answer.transcriptions:
            answer.boundary_uncertain = True

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

"""Answer ↔ page mapping.

The association between a detected answer and the manuscript pages it appears
on is *stored data*, derived from where the handwriting was actually found — it
is never guessed by the client and never invented by the server.

Two directions are needed:

Write path
    :func:`resolve_region_page` — when segmentation output is persisted, each
    region is pinned to the page it was detected on using the region's own page
    reference. If neither a ``page_id`` nor a ``page_number`` resolves, the
    region is dropped rather than attributed to the first page.

Read path
    :func:`build_answer_page_mapping` — rebuilds the ordered, page-by-page view
    the evaluation workspace consumes, and distinguishes a mapping that came
    from observed regions from a best-effort fallback that must be surfaced to
    the teacher as *uncertain*.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The mapping came from regions we actually detected on pages.
SOURCE_REGIONS = "regions"
#: No usable regions; pages taken from what detection recorded, and flagged.
SOURCE_DETECTION = "detection_meta"
#: Nothing to go on at all — the client must not claim a page.
SOURCE_UNKNOWN = "unknown"


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _as_page_number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@dataclass(frozen=True, slots=True)
class MappedPage:
    """One page an answer touches, with the regions detected on it."""

    page_id: Any
    page_number: int
    regions: tuple[Any, ...]
    uncertain: bool


@dataclass(frozen=True, slots=True)
class AnswerPageMapping:
    """The full, ordered page mapping for a single answer."""

    pages: tuple[MappedPage, ...]
    page_numbers: tuple[int, ...]
    uncertain: bool
    source: str


def resolve_region_page(
    region: Mapping[str, Any],
    *,
    pages_by_id: Mapping[str, Any],
    pages_by_number: Mapping[int, Any],
) -> Any | None:
    """Resolve a segmentation region to the page it was detected on.

    ``page_id`` is authoritative and matched exactly; ``page_number`` is a
    secondary hint. Returns ``None`` when neither resolves — callers must skip
    the region instead of defaulting to the first page.
    """
    page_id = _as_uuid(region.get("page_id"))
    if page_id is not None:
        page = pages_by_id.get(str(page_id))
        if page is not None:
            return page

    number = _as_page_number(region.get("page_number"))
    if number is not None:
        return pages_by_number.get(number)
    return None


def _region_sort_key(region: Any) -> tuple[float, float]:
    return (
        float(getattr(region, "y0", 0.0) or 0.0),
        float(getattr(region, "x0", 0.0) or 0.0),
    )


def build_answer_page_mapping(
    *,
    regions: Iterable[Any],
    pages: Sequence[Any],
    detection_meta: Mapping[str, Any] | None = None,
) -> AnswerPageMapping:
    """Rebuild an answer's page mapping from its stored regions.

    ``regions`` are ``AnswerRegion`` rows and ``pages`` are the submission's
    ``SubmissionPage`` rows (duck-typed: ``.id`` / ``.page_number``). Every
    returned page carries the regions that landed on it so the workspace can
    focus the right part of the page.

    When no region can be attributed, the mapping falls back to what detection
    recorded and is marked *uncertain*; when there is nothing to fall back to,
    no page is claimed at all.
    """
    pages_by_id = {str(page.id): page for page in pages}
    pages_by_number = {page.page_number: page for page in pages}

    grouped: dict[str, list[Any]] = {}
    unmapped = 0
    for region in regions:
        page = pages_by_id.get(str(getattr(region, "page_id", "")))
        if page is None:
            unmapped += 1
            continue
        grouped.setdefault(str(page.id), []).append(region)

    if grouped:
        ordered = sorted(grouped.values(), key=lambda group: pages_by_id[str(group[0].page_id)].page_number)
        mapped = tuple(
            MappedPage(
                page_id=pages_by_id[str(group[0].page_id)].id,
                page_number=pages_by_id[str(group[0].page_id)].page_number,
                regions=tuple(sorted(group, key=_region_sort_key)),
                uncertain=False,
            )
            for group in ordered
        )
        return AnswerPageMapping(
            pages=mapped,
            page_numbers=tuple(page.page_number for page in mapped),
            # A region we could not attribute means the mapping is incomplete.
            uncertain=unmapped > 0,
            source=SOURCE_REGIONS,
        )

    detected = (detection_meta or {}).get("source_pages") or []
    fallback: list[MappedPage] = []
    for number in sorted({n for n in (_as_page_number(v) for v in detected) if n is not None}):
        page = pages_by_number.get(number)
        if page is None:
            continue
        fallback.append(
            MappedPage(page_id=page.id, page_number=page.page_number, regions=(), uncertain=True)
        )

    if fallback:
        return AnswerPageMapping(
            pages=tuple(fallback),
            page_numbers=tuple(page.page_number for page in fallback),
            uncertain=True,
            source=SOURCE_DETECTION,
        )

    return AnswerPageMapping(
        pages=(),
        page_numbers=(),
        uncertain=True,
        source=SOURCE_UNKNOWN,
    )

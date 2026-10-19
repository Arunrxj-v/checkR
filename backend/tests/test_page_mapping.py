"""Answer → manuscript-page mapping (pure logic).

The mapping is what drives the evaluation workspace viewer, so the rules are
pinned here directly: pages come from *detected regions*, never from list
position, and an unknown mapping is reported as uncertain rather than guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.page_mapping import (
    SOURCE_DETECTION,
    SOURCE_REGIONS,
    SOURCE_UNKNOWN,
    build_answer_page_mapping,
    resolve_region_page,
)


@dataclass
class StubPage:
    id: uuid.UUID
    page_number: int


@dataclass
class StubRegion:
    page_id: uuid.UUID
    x0: float = 0.1
    y0: float = 0.1
    x1: float = 0.9
    y1: float = 0.2


def _pages(count: int) -> list[StubPage]:
    return [StubPage(id=uuid.uuid4(), page_number=n) for n in range(1, count + 1)]


# --------------------------------------------------------------------------- #
# Write path: resolving a region to a page
# --------------------------------------------------------------------------- #
def test_resolve_region_page_prefers_page_id_over_page_number():
    pages = _pages(3)
    by_id = {str(p.id): p for p in pages}
    by_number = {p.page_number: p for p in pages}

    # page_id says 3, the (stale) page_number says 1: the id wins.
    page = resolve_region_page(
        {"page_id": str(pages[2].id), "page_number": 1},
        pages_by_id=by_id,
        pages_by_number=by_number,
    )
    assert page is pages[2]


def test_resolve_region_page_falls_back_to_page_number():
    pages = _pages(3)
    page = resolve_region_page(
        {"page_number": 2},
        pages_by_id={str(p.id): p for p in pages},
        pages_by_number={p.page_number: p for p in pages},
    )
    assert page is pages[1]


def test_resolve_region_page_never_defaults_to_the_first_page():
    """An unresolvable reference must not silently become page 1."""
    pages = _pages(3)
    lookup = dict(
        pages_by_id={str(p.id): p for p in pages},
        pages_by_number={p.page_number: p for p in pages},
    )
    assert resolve_region_page({}, **lookup) is None
    assert resolve_region_page({"page_number": 99}, **lookup) is None
    assert resolve_region_page({"page_id": str(uuid.uuid4())}, **lookup) is None
    assert resolve_region_page({"page_number": "not-a-number"}, **lookup) is None


# --------------------------------------------------------------------------- #
# Read path: rebuilding the viewer mapping
# --------------------------------------------------------------------------- #
def test_mapping_groups_regions_by_page_and_orders_them():
    pages = _pages(3)
    regions = [
        StubRegion(page_id=pages[2].id, y0=0.30),
        StubRegion(page_id=pages[0].id, y0=0.20),
        StubRegion(page_id=pages[2].id, y0=0.10),
    ]
    mapping = build_answer_page_mapping(regions=regions, pages=pages)

    assert mapping.source == SOURCE_REGIONS
    assert mapping.uncertain is False
    assert mapping.page_numbers == (1, 3)
    # Pages ascend by page number; regions ascend by their position on the page.
    assert [page.page_number for page in mapping.pages] == [1, 3]
    assert [region.y0 for region in mapping.pages[1].regions] == [0.10, 0.30]
    assert all(page.uncertain is False for page in mapping.pages)


def test_mapping_spans_multiple_pages_for_one_answer():
    pages = _pages(4)
    regions = [
        StubRegion(page_id=pages[0].id, y0=0.8),
        StubRegion(page_id=pages[1].id, y0=0.1),
    ]
    mapping = build_answer_page_mapping(regions=regions, pages=pages)
    assert mapping.page_numbers == (1, 2)
    assert len(mapping.pages) == 2


def test_mapping_is_unknown_without_regions_or_detection():
    mapping = build_answer_page_mapping(regions=[], pages=_pages(3))
    assert mapping.pages == ()
    assert mapping.page_numbers == ()
    assert mapping.uncertain is True
    assert mapping.source == SOURCE_UNKNOWN


def test_mapping_falls_back_to_detection_meta_and_flags_it_uncertain():
    mapping = build_answer_page_mapping(
        regions=[],
        pages=_pages(3),
        detection_meta={"source_pages": [2, 3]},
    )
    assert mapping.page_numbers == (2, 3)
    assert mapping.source == SOURCE_DETECTION
    assert mapping.uncertain is True
    assert all(page.uncertain for page in mapping.pages)


def test_mapping_ignores_undetectable_pages_in_detection_meta():
    mapping = build_answer_page_mapping(
        regions=[],
        pages=_pages(3),
        detection_meta={"source_pages": [2, 99, None, "x"]},
    )
    assert mapping.page_numbers == (2,)


def test_mapping_ignores_regions_pointing_at_foreign_pages():
    """A stray page id is dropped — and makes the mapping honestly uncertain."""
    pages = _pages(3)
    mapping = build_answer_page_mapping(
        regions=[StubRegion(page_id=uuid.uuid4())],
        pages=pages,
    )
    assert mapping.page_numbers == ()
    assert mapping.source == SOURCE_UNKNOWN


def test_partially_attributable_regions_keep_known_pages_but_flag_uncertainty():
    pages = _pages(3)
    mapping = build_answer_page_mapping(
        regions=[
            StubRegion(page_id=pages[1].id),
            StubRegion(page_id=uuid.uuid4()),  # orphaned
        ],
        pages=pages,
    )
    assert mapping.page_numbers == (2,)
    assert mapping.uncertain is True

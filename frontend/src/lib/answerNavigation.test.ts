/**
 * Question → manuscript viewer synchronisation.
 *
 * The scenarios mirror the acceptance list for the workspace: selecting a
 * question must drive the viewer to the page(s) that question was actually
 * detected on, keyboard N/P must keep roster, rubric and viewer in step, and an
 * unknown location must never be papered over with a plausible page number.
 */

import { describe, expect, it } from "vitest";

import {
  answerPageChip,
  answerPageNumbers,
  compactPageNumbers,
  formatPageNumbers,
  regionBounds,
  resolveViewerTarget,
  stepViewerPage,
  viewerPagePosition,
} from "./answerNavigation";
import type { AnswerPage, AnswerRegion } from "./types";

function region(overrides: Partial<AnswerRegion> = {}): AnswerRegion {
  return {
    id: "region",
    page_id: "page",
    x0: 0.1,
    y0: 0.1,
    x1: 0.5,
    y1: 0.2,
    label: null,
    confidence: 0.9,
    ...overrides,
  };
}

function page(page_number: number, regions: AnswerRegion[] = []): AnswerPage {
  return {
    page_id: `page-${page_number}`,
    page_number,
    regions: regions.map((r, index) => ({ ...r, id: `page-${page_number}-r${index}` })),
    uncertain: false,
  };
}

/**
 * A faithful stand-in for the workspace's viewer state: it applies the same
 * pure rules the component does, so the scenarios below exercise the real
 * behaviour rather than a restatement of it.
 */
class Viewer {
  private currentPage: number | null;
  private readonly remembered: Record<string, number> = {};

  constructor(private readonly allPages: number[]) {
    this.currentPage = allPages[0] ?? null;
  }

  get page(): number | null {
    return this.currentPage;
  }

  /** Pages the pager is allowed to walk for this answer. */
  allowed(answer: { pages: AnswerPage[] }): number[] {
    const mapped = answerPageNumbers(answer.pages);
    return mapped.length > 1 ? mapped : this.allPages;
  }

  /** Select a question in the roster → sync the manuscript viewer. */
  select(answer: { id: string; pages: AnswerPage[] }) {
    const target = resolveViewerTarget({
      pageNumbers: answerPageNumbers(answer.pages),
      rememberedPage: this.remembered[answer.id] ?? null,
      currentPage: this.currentPage,
    });
    if (target.reason !== "unchanged" && target.pageNumber != null) {
      this.currentPage = target.pageNumber;
    }
    return target;
  }

  /** Page-nav buttons (and manual navigation): never selects another question. */
  step(direction: 1 | -1, answer: { id: string; pages: AnswerPage[] }): number | null {
    const next = stepViewerPage({
      pageNumbers: this.allowed(answer),
      currentPage: this.currentPage,
      direction,
    });
    if (next != null) {
      this.currentPage = next;
      this.remembered[answer.id] = next;
    }
    return next;
  }
}

const ALL_PAGES = [1, 2, 3, 4, 5, 6, 7, 8, 9];
const Q1 = { id: "q1", pages: [page(2)] };
const Q2 = { id: "q2", pages: [page(3), page(4)] };
const Q3 = { id: "q3", pages: [page(5)] };
const Q4 = { id: "q4", pages: [page(6), page(7)] };
const UNMAPPED = { id: "q9", pages: [] };

// --------------------------------------------------------------------------- //
// Selecting a question drives the viewer
// --------------------------------------------------------------------------- //
describe("question selection", () => {
  it("moves the viewer to Q1's detected page, not the first page", () => {
    const viewer = new Viewer(ALL_PAGES);
    expect(viewer.page).toBe(1); // starts on page 1
    const target = viewer.select(Q1);
    expect(target).toEqual({ pageNumber: 2, reason: "first" });
    expect(viewer.page).toBe(2);
  });

  it("moves the viewer from an unrelated page to the selected question's page", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q1); // page 2
    viewer.select(Q3); // page 5 — the reported bug left this on page 1/2
    expect(viewer.page).toBe(5);

    viewer.select(Q4); // multi-page: opens on the first page it appears on
    expect(viewer.page).toBe(6);
  });

  it("opens a multi-page answer on its first page", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2);
    expect(viewer.page).toBe(3);
  });

  it("does not map questions to pages by roster order", () => {
    // Q2 is the second question but lives on pages 3–4, not page 2.
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2);
    expect(viewer.page).toBe(3);
    expect(viewer.allowed(Q2)).toEqual([3, 4]);
  });
});

// --------------------------------------------------------------------------- //
// Multi-page answers
// --------------------------------------------------------------------------- //
describe("multi-page answers", () => {
  it("steps only through the pages belonging to the answer", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2); // pages 3–4
    expect(viewer.step(1, Q2)).toBe(4);
    // Clamped at the end of the answer, and never jumps to another question.
    expect(viewer.step(1, Q2)).toBe(4);
    expect(viewer.step(-1, Q2)).toBe(3);
    expect(viewer.step(-1, Q2)).toBe(3);
  });

  it("reports the answer-scoped position, e.g. current answer page 1 / 2", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2);
    const first = viewerPagePosition({ pageNumbers: viewer.allowed(Q2), currentPage: viewer.page });
    expect(first).toEqual({ index: 0, total: 2, canPrev: false, canNext: true });

    viewer.step(1, Q2);
    const second = viewerPagePosition({ pageNumbers: viewer.allowed(Q2), currentPage: viewer.page });
    expect(second).toEqual({ index: 1, total: 2, canPrev: true, canNext: false });
  });

  it("lets a single-page answer fall back to whole-document navigation", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q1); // page 2, only one page for this answer
    expect(viewer.allowed(Q1)).toEqual(ALL_PAGES);
    expect(viewer.step(1, Q1)).toBe(3);
  });
});

// --------------------------------------------------------------------------- //
// Keyboard navigation
// --------------------------------------------------------------------------- //
describe("keyboard navigation", () => {
  it("keeps roster, rubric and viewer in step on [N] and [P]", () => {
    const roster = [Q1, Q2, Q3];
    const viewer = new Viewer(ALL_PAGES);

    // [N] Next Question
    viewer.select(roster[0]);
    expect(viewer.page).toBe(2);
    viewer.select(roster[1]);
    expect(viewer.page).toBe(3);
    viewer.select(roster[2]);
    expect(viewer.page).toBe(5);

    // [P] Previous Question — the inverse.
    viewer.select(roster[1]);
    expect(viewer.page).toBe(3);
    viewer.select(roster[0]);
    expect(viewer.page).toBe(2);
  });
});

// --------------------------------------------------------------------------- //
// Manual navigation must not change the selected question
// --------------------------------------------------------------------------- //
describe("manual page navigation", () => {
  it("moves the viewer without changing the evaluated question", () => {
    const viewer = new Viewer(ALL_PAGES);
    const selected = Q1;
    viewer.select(selected); // page 2
    viewer.step(1, selected); // page 3 — same question, different page
    expect(viewer.page).toBe(3);
    expect(selected.id).toBe("q1");
  });

  it("cannot be used to step out of a multi-page answer", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2); // page 3
    viewer.step(-1, Q2);
    expect(viewer.page).toBe(3); // confined to pages 3–4
  });
});

// --------------------------------------------------------------------------- //
// Missing / uncertain mapping
// --------------------------------------------------------------------------- //
describe("uncertain page mapping", () => {
  it("leaves the viewer untouched when an answer has no detected page", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q1); // page 2
    const target = viewer.select(UNMAPPED);
    expect(target).toEqual({ pageNumber: 2, reason: "unchanged" });
    expect(viewer.page).toBe(2);
    expect(viewer.allowed(UNMAPPED)).toEqual(ALL_PAGES); // manual navigation allowed
  });

  it("states the uncertainty instead of naming a page", () => {
    expect(answerPageChip({ label: "Q9", pageNumbers: [], uncertain: true })).toBe(
      "Q9 · page map uncertain",
    );
  });

  it("flags a best-effort mapping as uncertain", () => {
    expect(answerPageChip({ label: "Q3", pageNumbers: [2], uncertain: true })).toBe(
      "Q3 · Page 2 (uncertain)",
    );
    expect(answerPageChip({ label: "Q3", pageNumbers: [2, 3], uncertain: false })).toBe(
      "Q3 · Pages 2–3",
    );
  });
});

// --------------------------------------------------------------------------- //
// Returning to a previously reviewed question
// --------------------------------------------------------------------------- //
describe("returning to a question", () => {
  it("restores the last page viewed for that answer", () => {
    const viewer = new Viewer(ALL_PAGES);
    viewer.select(Q2); // page 3
    viewer.step(1, Q2); // page 4 — the evaluator's last position for Q2
    viewer.select(Q3); // away to page 5
    expect(viewer.page).toBe(5);

    const target = viewer.select(Q2);
    expect(target).toEqual({ pageNumber: 4, reason: "remembered" });
    expect(viewer.page).toBe(4);
  });

  it("ignores a remembered page that does not belong to the answer", () => {
    // Q1 is only on page 2; a stale memory of page 3 must not win.
    expect(
      resolveViewerTarget({ pageNumbers: [2], rememberedPage: 3, currentPage: 7 }),
    ).toEqual({ pageNumber: 2, reason: "first" });
  });
});

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
describe("page helpers", () => {
  it("de-duplicates and sorts detected pages", () => {
    expect(answerPageNumbers([page(3), page(2), page(3)])).toEqual([2, 3]);
    expect(answerPageNumbers(undefined)).toEqual([]);
  });

  it("formats page ranges", () => {
    expect(formatPageNumbers([5])).toBe("Page 5");
    expect(formatPageNumbers([5, 6])).toBe("Pages 5–6");
    expect(formatPageNumbers([5, 7])).toBe("Pages 5, 7");
    expect(compactPageNumbers([5])).toBe("p.5");
    expect(compactPageNumbers([5, 6])).toBe("pp.5–6");
  });

  it("unions an answer's regions on a page", () => {
    const bounds = regionBounds([
      region({ x0: 0.2, y0: 0.3, x1: 0.6, y1: 0.4 }),
      region({ x0: 0.1, y0: 0.5, x1: 0.9, y1: 0.6 }),
    ]);
    expect(bounds).toEqual({ x0: 0.1, y0: 0.3, x1: 0.9, y1: 0.6 });
    expect(regionBounds([])).toBeNull();
    expect(regionBounds(undefined)).toBeNull();
  });

  it("clamps the pager at the ends of its page set", () => {
    expect(stepViewerPage({ pageNumbers: [2, 3], currentPage: 2, direction: 1 })).toBe(3);
    expect(stepViewerPage({ pageNumbers: [2, 3], currentPage: 3, direction: 1 })).toBe(3);
    expect(stepViewerPage({ pageNumbers: [2, 3], currentPage: 2, direction: -1 })).toBe(2);
    expect(stepViewerPage({ pageNumbers: [], currentPage: 2, direction: 1 })).toBeNull();
  });
});

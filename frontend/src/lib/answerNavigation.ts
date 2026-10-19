/**
 * Question → manuscript-page navigation rules.
 *
 * The evaluation workspace keeps the Question Roster, the selected question and
 * the manuscript viewer in lock-step. The rules live here — free of React — so
 * they can be tested directly and so the viewer never invents a page for an
 * answer whose location was not detected.
 */

import type { AnswerPage, AnswerRegion } from "./types";

export type ViewerTargetReason =
  /** The answer was seen before; its last viewed page wins. */
  | "remembered"
  /** First page the answer was detected on. */
  | "first"
  /** No usable mapping: the viewer stays where it is. */
  | "unchanged";

export interface ViewerTarget {
  /** 1-based page number to display, or null when nothing can be shown. */
  pageNumber: number | null;
  reason: ViewerTargetReason;
}

/** Page numbers an answer was detected on, ascending and deduplicated. */
export function answerPageNumbers(answerPages: AnswerPage[] | null | undefined): number[] {
  const seen = new Set<number>();
  for (const page of answerPages ?? []) {
    if (Number.isFinite(page.page_number)) seen.add(page.page_number);
  }
  return [...seen].sort((a, b) => a - b);
}

/**
 * Which page the viewer should show for a newly selected answer.
 *
 * - A mapped answer opens on its remembered page, else on the first page it was
 *   detected on.
 * - An unmapped answer restores its remembered page when there is one, but
 *   otherwise leaves the viewer untouched — an unknown mapping is never
 *   resolved by guessing a page.
 */
export function resolveViewerTarget(input: {
  pageNumbers: number[];
  rememberedPage?: number | null;
  currentPage?: number | null;
}): ViewerTarget {
  const { pageNumbers, currentPage } = input;
  const remembered = input.rememberedPage ?? null;

  if (pageNumbers.length === 0) {
    return remembered != null
      ? { pageNumber: remembered, reason: "remembered" }
      : { pageNumber: currentPage ?? null, reason: "unchanged" };
  }

  if (remembered != null && pageNumbers.includes(remembered)) {
    return { pageNumber: remembered, reason: "remembered" };
  }
  return { pageNumber: pageNumbers[0], reason: "first" };
}

/**
 * Step the viewer one page within the pages it is allowed to show.
 *
 * `pageNumbers` is the answer's own pages when the mapping is known, and every
 * page of the script otherwise (manual navigation). The selected question is
 * never affected: this only moves the viewer.
 */
export function stepViewerPage(input: {
  pageNumbers: number[];
  currentPage?: number | null;
  direction: 1 | -1;
}): number | null {
  const { pageNumbers, currentPage, direction } = input;
  if (pageNumbers.length === 0) return null;

  const index = currentPage == null ? -1 : pageNumbers.indexOf(currentPage);
  if (index < 0) {
    return direction > 0 ? pageNumbers[0] : pageNumbers[pageNumbers.length - 1];
  }
  return pageNumbers[index + direction] ?? pageNumbers[index];
}

/** Position of the current page inside a set of navigable pages. */
export function viewerPagePosition(input: {
  pageNumbers: number[];
  currentPage?: number | null;
}): { index: number; total: number; canPrev: boolean; canNext: boolean } | null {
  const { pageNumbers, currentPage } = input;
  if (pageNumbers.length === 0) return null;

  const found = currentPage == null ? -1 : pageNumbers.indexOf(currentPage);
  const index = found < 0 ? 0 : found;
  return {
    index,
    total: pageNumbers.length,
    canPrev: found > 0,
    canNext: found >= 0 && found < pageNumbers.length - 1,
  };
}

/** "Page 5" | "Pages 5–6" | "Pages 5, 7" — always 1-based page numbers. */
export function formatPageNumbers(pageNumbers: number[]): string {
  if (pageNumbers.length === 0) return "no page";
  if (pageNumbers.length === 1) return `Page ${pageNumbers[0]}`;

  if (isContiguous(pageNumbers)) {
    return `Pages ${pageNumbers[0]}–${pageNumbers[pageNumbers.length - 1]}`;
  }
  return `Pages ${pageNumbers.join(", ")}`;
}

/** Compact page hint for the roster: "p.2" | "pp.2–3" | "pp.2, 4". */
export function compactPageNumbers(pageNumbers: number[]): string {
  if (pageNumbers.length === 0) return "";
  if (pageNumbers.length === 1) return `p.${pageNumbers[0]}`;
  if (isContiguous(pageNumbers)) {
    return `pp.${pageNumbers[0]}–${pageNumbers[pageNumbers.length - 1]}`;
  }
  return `pp.${pageNumbers.join(", ")}`;
}

function isContiguous(pageNumbers: number[]): boolean {
  return pageNumbers.every((number, index) => index === 0 || number === pageNumbers[index - 1] + 1);
}

/**
 * Toolbar chip text, e.g. `Q3 · Pages 5–6` or `Q3 · page map uncertain`.
 * Uncertainty is always stated rather than hidden behind a plausible number.
 */
export function answerPageChip(input: {
  label: string;
  pageNumbers: number[];
  uncertain: boolean;
}): string {
  const { label, pageNumbers, uncertain } = input;
  if (pageNumbers.length === 0) return `${label} · page map uncertain`;
  const pages = formatPageNumbers(pageNumbers);
  return uncertain ? `${label} · ${pages} (uncertain)` : `${label} · ${pages}`;
}

/** Union of an answer's regions on one page, in normalised page coordinates. */
export function regionBounds(
  regions: AnswerRegion[] | null | undefined,
): { x0: number; y0: number; x1: number; y1: number } | null {
  if (!regions || regions.length === 0) return null;

  return regions.reduce(
    (box, region) => ({
      x0: Math.min(box.x0, region.x0),
      y0: Math.min(box.y0, region.y0),
      x1: Math.max(box.x1, region.x1),
      y1: Math.max(box.y1, region.y1),
    }),
    { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity },
  );
}

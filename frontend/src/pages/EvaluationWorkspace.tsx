import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { AuthImage } from "@/components/ui/AuthImage";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { useToast } from "@/components/ui/Toaster";
import { answerApi, examApi, resultApi, submissionApi } from "@/lib/api";
import {
  answerPageChip,
  answerPageNumbers,
  compactPageNumbers,
  regionBounds,
  resolveViewerTarget,
  stepViewerPage,
  viewerPagePosition,
} from "@/lib/answerNavigation";
import { clamp, formatConfidence, formatMarks, roundTo, titleCase } from "@/lib/format";
import {
  answerLabel,
  answerTone,
  confidenceLabel,
  confidenceTone,
} from "@/lib/status";
import type { Answer, AnswerDetail, Evaluation, Review } from "@/lib/types";

import { errorText } from "./ExamsPage";

const ZOOM_MIN = 60;
const ZOOM_MAX = 180;
const ZOOM_STEP = 10;

export function EvaluationWorkspace() {
  const { submissionId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [showOcr, setShowOcr] = useState(true);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [viewPage, setViewPage] = useState(0);
  const [awarded, setAwarded] = useState("0.0");
  const [note, setNote] = useState("");
  const [overrideMode, setOverrideMode] = useState(false);

  // Viewer plumbing for question → manuscript synchronisation.
  const viewerScrollRef = useRef<HTMLDivElement | null>(null);
  const pageImageWrapRef = useRef<HTMLDivElement | null>(null);
  // Last manuscript page the evaluator chose per answer, so returning to a
  // question restores the page they were last looking at.
  const lastPageByAnswer = useRef<Record<string, number>>({});

  const submissionQuery = useQuery({
    queryKey: ["submission", submissionId],
    queryFn: () => submissionApi.get(submissionId),
    enabled: Boolean(submissionId),
  });
  const submission = submissionQuery.data;

  const examQuery = useQuery({
    queryKey: ["exam", submission?.exam_id],
    queryFn: () => examApi.get(submission!.exam_id),
    enabled: Boolean(submission?.exam_id),
  });

  const answersQuery = useQuery({
    queryKey: ["answers", submissionId],
    queryFn: () => answerApi.list(submissionId),
    enabled: Boolean(submissionId),
  });
  const answers = useMemo(
    () => (answersQuery.data ?? []).slice().sort((a, b) => a.order_index - b.order_index),
    [answersQuery.data],
  );

  const siblingsQuery = useQuery({
    queryKey: ["submissions", "siblings", submission?.exam_id],
    queryFn: () => submissionApi.list({ exam_id: submission!.exam_id, limit: 200 }),
    enabled: Boolean(submission?.exam_id),
  });

  // Active answer selection, kept in the URL so deep links and refreshes work.
  const activeFromUrl = searchParams.get("answer");
  const activeIndex = Math.max(
    0,
    answers.findIndex((a) => a.id === activeFromUrl),
  );
  const activeAnswer: Answer | undefined = answers[activeIndex];

  const detailQuery = useQuery({
    queryKey: ["answer", activeAnswer?.id],
    queryFn: () => answerApi.get(activeAnswer!.id),
    enabled: Boolean(activeAnswer?.id),
  });
  const detail = detailQuery.data;

  // --- Question → manuscript-page synchronisation ------------------------- #
  // Everything the viewer needs is derived from server data (the answer's
  // detected page mapping); nothing is inferred from list position.
  const submissionPages = submission?.pages ?? [];
  const currentPage = submissionPages[viewPage];
  const answerPages = detail?.pages ?? [];
  const answerPageList = answerPageNumbers(answerPages);
  // A multi-page answer is navigated within its own pages; a single-page or
  // unmapped answer falls back to whole-document navigation.
  const viewerPageNumbers =
    answerPageList.length > 1 ? answerPageList : submissionPages.map((p) => p.page_number);
  const activeAnswerPage = answerPages.find((p) => p.page_number === currentPage?.page_number);
  const regionBoundsForPage = useMemo(
    () => regionBounds(activeAnswerPage?.regions),
    [activeAnswerPage],
  );
  const pagePosition = viewerPagePosition({
    pageNumbers: viewerPageNumbers,
    currentPage: currentPage?.page_number ?? null,
  });
  const mappingUncertain =
    Boolean(detail?.page_mapping_uncertain) || Boolean(activeAnswerPage?.uncertain);
  const pageChip = detail
    ? answerPageChip({
        label: detail.question_label ?? `Q${activeIndex + 1}`,
        pageNumbers: answerPageList,
        uncertain: mappingUncertain,
      })
    : null;

  /** Move the viewer so a region of the current page is centred. */
  const focusRegion = useCallback((bounds: { x0: number; y0: number; x1: number; y1: number } | null) => {
    const container = viewerScrollRef.current;
    const image = pageImageWrapRef.current?.querySelector("img");
    if (!container || !image || !bounds) return;

    const containerRect = container.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    if (imageRect.height <= 0) return;

    const regionTop =
      imageRect.top - containerRect.top + container.scrollTop + bounds.y0 * imageRect.height;
    const regionHeight = Math.max(1, (bounds.y1 - bounds.y0) * imageRect.height);
    const target = regionTop - Math.max(0, (container.clientHeight - regionHeight) / 2);
    container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  }, []);

  // Prefetch neighbours so N/P feels instant.
  useEffect(() => {
    const next = answers[activeIndex + 1];
    const prev = answers[activeIndex - 1];
    for (const neighbour of [next, prev]) {
      if (neighbour) {
        void queryClient.prefetchQuery({
          queryKey: ["answer", neighbour.id],
          queryFn: () => answerApi.get(neighbour.id),
          staleTime: 30_000,
        });
      }
    }
  }, [answers, activeIndex, queryClient]);

  useCrumbs(
    [
      { label: "Evaluation", to: "/evaluation" },
      { label: submission?.student_name ?? "Script" },
    ],
    [submission?.student_name],
  );

  // Seed the mark input + note whenever the active answer changes.
  useEffect(() => {
    if (!detail) return;
    const basis = detail.teacher_score ?? detail.ai_score ?? 0;
    setAwarded(basis.toFixed(1));
    setNote(detail.teacher_comment ?? detail.reviews[0]?.comment ?? "");
    setOverrideMode(detail.is_reviewed);
  }, [detail?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Synchronise the manuscript viewer with the selected question: open the
  // first page the answer was detected on (or the page last viewed for it), and
  // never fabricate a page when the mapping is unknown.
  useEffect(() => {
    if (!detail || !submission) return;
    const target = resolveViewerTarget({
      pageNumbers: answerPageNumbers(detail.pages),
      rememberedPage: lastPageByAnswer.current[detail.id] ?? null,
      currentPage: submission.pages[viewPage]?.page_number ?? null,
    });
    if (target.reason === "unchanged" || target.pageNumber == null) return;
    const index = submission.pages.findIndex((p) => p.page_number === target.pageNumber);
    if (index >= 0) setViewPage(index);
  }, [detail?.id, detail?.pages, submission?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Bring the answer's detected region into view once the page is laid out.
  // Skipped when the current page is not one the answer was found on — the
  // synchronisation effect above is about to move the viewer there anyway.
  useEffect(() => {
    if (!detail || !currentPage) return;
    const mapped = answerPageNumbers(detail.pages);
    if (mapped.length === 0 || !mapped.includes(currentPage.page_number)) return;
    const frame = window.requestAnimationFrame(() => focusRegion(regionBoundsForPage));
    return () => window.cancelAnimationFrame(frame);
  }, [detail?.id, currentPage?.page_number, regionBoundsForPage, focusRegion, detail]);

  const selectAnswer = useCallback(
    (index: number) => {
      const target = answers[index];
      if (!target) return;
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("answer", target.id);
        return next;
      });
    },
    [answers, setSearchParams],
  );

  const reviewMutation = useMutation({
    mutationFn: (payload: { action: string; teacher_score?: number; comment?: string; reason?: string }) =>
      answerApi.review(activeAnswer!.id, payload),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["answers", submissionId] });
      void queryClient.invalidateQueries({ queryKey: ["answer", updated.id] });
      void queryClient.invalidateQueries({ queryKey: ["submission", submissionId] });
      void queryClient.invalidateQueries({ queryKey: ["result", submissionId] });

      const remaining = answers.filter((a) => !a.is_reviewed && a.id !== updated.id);
      if (remaining.length > 0) {
        const nextIndex = answers.findIndex((a) => a.id === remaining[0].id);
        selectAnswer(nextIndex);
      }
    },
    onError: (err) => notify("Could not record decision", { tone: "critical", detail: errorText(err) }),
  });

  const evaluateMutation = useMutation({
    mutationFn: () => answerApi.evaluate(activeAnswer!.id, true),
    onSuccess: () => {
      notify("Re-evaluation queued", { tone: "verified" });
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["answer", activeAnswer?.id] });
        void queryClient.invalidateQueries({ queryKey: ["answers", submissionId] });
      }, 2500);
    },
    onError: (err) => notify("Could not re-evaluate", { tone: "critical", detail: errorText(err) }),
  });

  const finalizeMutation = useMutation({
    mutationFn: () => resultApi.finalize(submissionId),
    onSuccess: (result) => {
      notify("Sheet finalised", {
        tone: "verified",
        detail: `${result.final_total_marks.toFixed(1)} / ${result.max_total_marks.toFixed(0)} (${result.reviewed_count}/${result.total_answers} reviewed).`,
      });
      void queryClient.invalidateQueries({ queryKey: ["submission", submissionId] });
      navigate(`/submissions/${submissionId}`);
    },
    onError: (err) => notify("Cannot finalise yet", { tone: "review", detail: errorText(err) }),
  });

  const accept = useCallback(() => {
    if (!detail) return;
    if (detail.ai_score === null) {
      notify("No AI suggestion to accept", { tone: "review", detail: "Use Override to award a mark manually." });
      setOverrideMode(true);
      return;
    }
    reviewMutation.mutate({ action: "accepted", comment: note.trim() || undefined });
  }, [detail, note, reviewMutation, notify]);

  const override = useCallback(() => {
    if (!detail) return;
    const value = Number(awarded);
    if (!Number.isFinite(value) || value < 0 || value > detail.max_marks) {
      notify("Mark out of range", { tone: "critical", detail: `Enter a value between 0 and ${detail.max_marks}.` });
      return;
    }
    reviewMutation.mutate({
      action: "overridden",
      teacher_score: value,
      comment: note.trim() || undefined,
      reason: note.trim() || undefined,
    });
  }, [detail, awarded, note, reviewMutation, notify]);

  const flag = useCallback(() => {
    if (!detail) return;
    reviewMutation.mutate({ action: "flagged", comment: note.trim() || "Flagged for moderation." });
  }, [detail, note, reviewMutation]);

  const goNext = useCallback(() => selectAnswer(Math.min(answers.length - 1, activeIndex + 1)), [answers.length, activeIndex, selectAnswer]);
  const goPrev = useCallback(() => selectAnswer(Math.max(0, activeIndex - 1)), [activeIndex, selectAnswer]);

  // Keyboard shortcuts, matching the legend in the workspace chrome.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "n") {
        e.preventDefault();
        goNext();
      } else if (key === "p") {
        e.preventDefault();
        goPrev();
      } else if (key === "a") {
        e.preventDefault();
        accept();
      } else if (key === "e") {
        e.preventDefault();
        setOverrideMode(true);
        document.getElementById("awarded-mark-input")?.focus();
      } else if (key === "f") {
        e.preventDefault();
        flag();
      } else if (key === "+" || key === "=") {
        e.preventDefault();
        setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP));
      } else if (key === "-" || key === "_") {
        e.preventDefault();
        setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [accept, flag, goNext, goPrev]);

  const reviewedCount = answers.filter((a) => a.is_reviewed).length;
  const roster = useMemo(
    () => (reviewOnly ? answers.filter((a) => a.is_flagged || !a.is_reviewed) : answers),
    [answers, reviewOnly],
  );

  const runningTotal = useMemo(
    () => answers.reduce((sum, a) => sum + (a.final_score ?? a.ai_score ?? 0), 0),
    [answers],
  );
  const maxTotal = useMemo(() => answers.reduce((sum, a) => sum + a.max_marks, 0), [answers]);

  if (submissionQuery.isLoading || answersQuery.isLoading) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center bg-surface">
        <div className="flex flex-col items-center gap-space-sm text-on-surface-variant">
          <Spinner className="h-5 w-5" />
          <span className=" text-body-sm">Preparing workspace…</span>
        </div>
      </div>
    );
  }

  if (submissionQuery.isError || !submission) {
    return (
      <div className="p-margin">
        <EmptyState icon="error" title="Submission unavailable" description={errorText(submissionQuery.error)} />
      </div>
    );
  }

  if (answers.length === 0) {
    return (
      <div className="p-margin">
        <EmptyState
          icon="hourglass_top"
          title="Nothing to evaluate yet"
          description="This script has no detected answers. It may still be processing, or the handwriting could not be segmented."
          action={
            <Link to={`/submissions/${submissionId}`} className="btn-secondary px-space-md py-1.5  text-label-md">
              View submission status
            </Link>
          }
        />
      </div>
    );
  }

  const siblingList = siblingsQuery.data?.items ?? [];
  const siblingIndex = siblingList.findIndex((s) => s.id === submissionId);

  /** Move the viewer one page within the allowed pages; the question stays. */
  const goPage = (direction: 1 | -1) => {
    const next = stepViewerPage({
      pageNumbers: viewerPageNumbers,
      currentPage: currentPage?.page_number ?? null,
      direction,
    });
    if (next == null) return;
    if (detail) lastPageByAnswer.current[detail.id] = next;
    const index = submissionPages.findIndex((p) => p.page_number === next);
    if (index >= 0) setViewPage(index);
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] w-full select-none flex-col overflow-hidden bg-surface">
      {/* Top operations bar */}
      <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-space-md bg-surface-container-lowest px-gutter shadow-sm">
        <div className="flex min-w-0 items-center gap-space-sm">
          <nav className="flex items-center gap-1.5  text-body-sm text-on-surface-variant">
            <Link to="/evaluation" className="hover:text-on-surface">
              Evaluation
            </Link>
            <span className="text-outline">/</span>
            <Link to={`/exams/${submission.exam_id}`} className="font-medium text-on-surface hover:text-secondary">
              {examQuery.data?.title ?? "Examination"}
            </Link>
            <span className="text-outline">/</span>
          </nav>
          <div className="flex items-center gap-space-xs rounded bg-surface-container px-2 py-0.5 shadow-sm">
            <Icon name="person" className="text-[16px] text-secondary" />
            <span className="font-display text-label-md font-semibold text-primary">
              {submission.student_name ?? "Unnamed candidate"}
            </span>
            <span className="rounded bg-surface-container-lowest px-1 font-mono text-label-sm font-medium text-on-surface-variant">
              {submission.student_roll ?? "no roll"}
            </span>
            <span className="px-1  text-label-sm text-outline">
              Sheet {siblingIndex >= 0 ? siblingIndex + 1 : 1}/{siblingList.length || 1}
            </span>
          </div>
          <div className="ml-space-xs flex items-center gap-1">
            <button
              type="button"
              title="Previous candidate"
              disabled={siblingIndex <= 0}
              onClick={() => navigate(`/submissions/${siblingList[siblingIndex - 1].id}/evaluate`)}
              className="flex h-7 items-center gap-0.5 rounded bg-surface-container-low px-2  text-label-sm text-on-surface shadow-sm transition-colors hover:bg-surface-container-high disabled:opacity-40"
            >
              <Icon name="chevron_left" className="text-[14px]" /> Prev
            </button>
            <button
              type="button"
              title="Next candidate"
              disabled={siblingIndex < 0 || siblingIndex >= siblingList.length - 1}
              onClick={() => navigate(`/submissions/${siblingList[siblingIndex + 1].id}/evaluate`)}
              className="flex h-7 items-center gap-0.5 rounded bg-surface-container-low px-2  text-label-sm text-on-surface shadow-sm transition-colors hover:bg-surface-container-high disabled:opacity-40"
            >
              Next <Icon name="chevron_right" className="text-[14px]" />
            </button>
          </div>
        </div>

        <div className="hidden items-center gap-3 rounded bg-surface-container-low px-3 py-1 xl:flex">
          {[
            ["N", "Next Q"],
            ["P", "Prev Q"],
            ["A", "Accept"],
            ["E", "Edit"],
            ["F", "Flag"],
          ].map(([key, label]) => (
            <div key={key} className="flex items-center gap-1 whitespace-nowrap text-label-sm text-on-surface-variant">
              <kbd className="rounded bg-surface-container-lowest px-1 py-0.5 font-mono text-[10px] text-on-surface shadow-sm">{key}</kbd>
              <span>{label}</span>
            </div>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-space-md">
          <div className="flex items-center gap-2 rounded bg-surface-container-high px-2.5 py-1">
            <span className=" text-label-sm font-medium uppercase tracking-wide text-on-surface-variant">
              Running Total
            </span>
            <div className="flex items-baseline gap-1">
              <span className="font-mono text-headline-sm font-semibold tnum text-primary">{runningTotal.toFixed(1)}</span>
              <span className="font-mono text-label-sm text-outline">/ {maxTotal.toFixed(1)}</span>
            </div>
            <span className="rounded px-1 py-0.2  text-[10px] font-medium bg-review-bg text-review-fg">
              Tentative
            </span>
          </div>
          <button
            type="button"
            onClick={() => finalizeMutation.mutate()}
            disabled={finalizeMutation.isPending || reviewedCount < answers.length}
            className="btn-primary flex h-8 items-center gap-1.5 px-3.5  text-body-sm font-semibold"
            title={reviewedCount < answers.length ? "Every answer needs a teacher decision first" : "Finalise this sheet"}
          >
            {finalizeMutation.isPending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : <Icon name="task_alt" className="text-[16px]" />}
            Finalise Sheet
          </button>
        </div>
      </header>

      <div className="relative flex flex-1 overflow-hidden">
        {/* Panel 1 — question roster */}
        <aside className="z-10 flex w-64 shrink-0 flex-col overflow-hidden bg-surface-container-lowest shadow-sm">
          <div className="flex flex-col gap-1.5 bg-surface-container-low p-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Icon name="list_alt" className="text-[16px] text-primary" />
                <span className="font-display text-label-md font-semibold uppercase tracking-wider text-primary">
                  Question Roster
                </span>
              </div>
              <span className="rounded bg-surface-container px-1.5 py-0.5 font-mono text-label-sm font-semibold text-on-surface-variant">
                {answers.length} Total
              </span>
            </div>
            <label className="flex cursor-pointer items-center gap-2 pt-1  text-label-sm text-on-surface-variant">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary"
                checked={reviewOnly}
                onChange={(e) => setReviewOnly(e.target.checked)}
              />
              Review needed only
            </label>
          </div>
          <div className="flex flex-1 flex-col gap-1 overflow-y-auto p-1.5">
            {roster.map((answer) => {
              const index = answers.findIndex((a) => a.id === answer.id);
              const isActive = answer.id === activeAnswer?.id;
              const tone = answerTone(answer.status, answer.is_flagged);
              return (
                <button
                  key={answer.id}
                  type="button"
                  onClick={() => selectAnswer(index)}
                  className={`flex items-center justify-between rounded px-3 py-2.5 text-left transition-colors ${
                    isActive
                      ? "border-l-2 border-secondary bg-surface-container-low"
                      : "hover:bg-surface-container-low"
                  }`}
                >
                  <div className="flex min-w-0 flex-col pr-2">
                    <div className="flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        tone === "verified" ? "bg-verified" : tone === "review" ? "bg-review" : tone === "critical" ? "bg-critical" : tone === "info" ? "bg-secondary" : "bg-outline"
                      }`} />
                      <span className={`truncate  text-body-sm ${isActive ? "font-semibold text-primary" : "font-medium text-on-surface"}`}>
                        Q{index + 1} {shortTitle(answer)}
                      </span>
                    </div>
                    <span className={`flex items-center gap-1 pl-3  text-[11px] ${
                      tone === "review" ? "font-medium text-review-fg" : tone === "critical" ? "text-critical-fg" : "text-outline"
                    }`}>
                      <span>{answerLabel(answer.status)}</span>
                      {answer.page_numbers.length > 0 ? (
                        <span
                          className="text-outline"
                          title={
                            answer.page_mapping_uncertain
                              ? "Detected on this page, but the location could not be confirmed."
                              : "Manuscript pages this answer was detected on."
                          }
                        >
                          · {compactPageNumbers(answer.page_numbers)}
                          {answer.page_mapping_uncertain ? "?" : ""}
                        </span>
                      ) : (
                        <span className="text-outline" title="Page mapping uncertain — navigate manually.">
                          · p.?
                        </span>
                      )}
                    </span>
                  </div>
                  <span className={`shrink-0 font-mono tnum text-body-sm ${isActive ? "font-semibold text-primary" : "font-medium text-on-surface"}`}>
                    {answer.final_score ?? answer.ai_score ?? "—"} / {answer.max_marks}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="flex flex-col gap-1 bg-surface-container-low p-space-sm">
            <div className="flex items-center justify-between  text-label-sm text-on-surface-variant">
              <span>
                Evaluated: {reviewedCount} / {answers.length}
              </span>
              <span className="font-semibold text-primary">
                {answers.length ? Math.round((reviewedCount / answers.length) * 100) : 0}% Complete
              </span>
            </div>
            <ProgressBar value={answers.length ? (reviewedCount / answers.length) * 100 : 0} tone="info" height="h-1.5" />
            <div className="flex items-center justify-between pt-1 text-[10px] text-outline">
              <span>Changes saved on decision</span>
              <Icon name="cloud_done" className="text-[14px] text-verified" />
            </div>
          </div>
        </aside>

        {/* Panel 2 — document viewer */}
        <main className="relative flex flex-1 flex-col overflow-hidden bg-surface">
          <div className="z-10 flex h-11 shrink-0 items-center justify-between gap-space-md bg-surface-container-lowest px-gutter shadow-sm">
            <div className="flex shrink-0 items-center gap-1 text-on-surface-variant">
              <button
                type="button"
                title="Zoom out"
                className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-surface-container hover:text-on-surface"
                onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))}
              >
                <Icon name="remove" className="text-[16px]" />
              </button>
              <span className="px-2 font-mono text-label-sm font-medium text-on-surface">{zoom}%</span>
              <button
                type="button"
                title="Zoom in"
                className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-surface-container hover:text-on-surface"
                onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))}
              >
                <Icon name="add" className="text-[16px]" />
              </button>
              <div className="mx-1.5 h-3.5 w-px bg-outline-variant" />
              <button
                type="button"
                title="Fit to page"
                className="flex h-7 items-center gap-1 rounded px-2.5  text-label-sm text-on-surface transition-colors hover:bg-surface-container"
                onClick={() => setZoom(100)}
              >
                <Icon name="crop_free" className="text-[15px]" /> Fit
              </button>
              <button
                type="button"
                title="Rotate manuscript"
                className="flex h-7 w-7 items-center justify-center rounded text-on-surface transition-colors hover:bg-surface-container"
                onClick={() => setRotation((r) => (r + 90) % 360)}
              >
                <Icon name="rotate_right" className="text-[16px]" />
              </button>
              <button
                type="button"
                onClick={() => setShowOcr((v) => !v)}
                className={`flex h-7 items-center gap-1 whitespace-nowrap rounded px-2  text-label-sm font-medium transition-colors ${
                  showOcr ? "bg-secondary-fixed text-on-secondary-fixed-variant" : "text-on-surface-variant hover:bg-surface-container"
                }`}
              >
                <Icon name="document_scanner" className="text-[16px]" /> OCR Overlay [{showOcr ? "On" : "Off"}]
              </button>
            </div>

            <div className="flex min-w-0 items-center gap-2  text-label-sm text-outline">
              <span className="truncate">
                {examQuery.data?.title ?? "Manuscript"} • Page {currentPage ? currentPage.page_number : 0} of{" "}
                {submissionPages.length}
              </span>
              {pageChip ? (
                <span
                  className={`shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-label-sm ${
                    mappingUncertain
                      ? "bg-review-bg text-review-fg"
                      : "bg-surface-container text-on-surface-variant"
                  }`}
                  title={
                    mappingUncertain
                      ? "Location on the manuscript could not be confirmed — navigate manually."
                      : "Manuscript pages this answer was detected on."
                  }
                >
                  {pageChip}
                </span>
              ) : null}
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                title={
                  answerPageList.length > 1 ? "Previous page of this answer" : "Previous manuscript page"
                }
                className="flex h-7 items-center gap-1 whitespace-nowrap rounded px-2  text-label-sm text-on-surface transition-colors hover:bg-surface-container disabled:opacity-40"
                disabled={!pagePosition?.canPrev}
                onClick={() => goPage(-1)}
              >
                <Icon name="arrow_back" className="text-[14px]" /> Prev
              </button>
              <span
                className="px-1.5 font-mono text-label-sm font-semibold text-on-surface"
                title={answerPageList.length > 1 ? "Current answer page" : "Current manuscript page"}
              >
                {pagePosition ? pagePosition.index + 1 : viewPage + 1} /{" "}
                {pagePosition ? pagePosition.total : submissionPages.length || 0}
              </span>
              <button
                type="button"
                title={answerPageList.length > 1 ? "Next page of this answer" : "Next manuscript page"}
                className="flex h-7 items-center gap-1 whitespace-nowrap rounded px-2  text-label-sm text-on-surface transition-colors hover:bg-surface-container disabled:opacity-40"
                disabled={!pagePosition?.canNext}
                onClick={() => goPage(1)}
              >
                Next <Icon name="arrow_forward" className="text-[14px]" />
              </button>
            </div>
          </div>

          <div
            ref={viewerScrollRef}
            className="flex flex-1 items-start justify-center overflow-auto bg-surface-container-low p-space-md"
          >
            {currentPage ? (
              <div className="flex flex-col gap-space-md" style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}>
                <div
                  ref={pageImageWrapRef}
                  className="relative w-[780px] transition-transform"
                  style={{ transform: `rotate(${rotation}deg)` }}
                >
                  <AuthImage
                    path={`/pages/${currentPage.id}/image?variant=processed`}
                    alt={`Page ${currentPage.page_number}`}
                    className="w-full rounded bg-white shadow-paper"
                    onLoad={() => focusRegion(regionBoundsForPage)}
                  />
                  {showOcr && activeAnswerPage
                    ? activeAnswerPage.regions.map((region) => (
                        <div
                          key={region.id}
                          className="pointer-events-none absolute rounded-sm border border-secondary/60 bg-secondary/10"
                          style={{
                            left: `${region.x0 * 100}%`,
                            top: `${region.y0 * 100}%`,
                            width: `${(region.x1 - region.x0) * 100}%`,
                            height: `${(region.y1 - region.y0) * 100}%`,
                          }}
                        />
                      ))
                    : null}
                </div>
                {showOcr && detail?.transcription ? (
                  <div className="w-[780px] rounded border border-outline-variant bg-[#fffdf5] p-6 shadow-paper">
                    <div className="mb-space-sm flex items-center justify-between border-b border-outline-variant pb-2">
                      <span className=" text-label-sm font-semibold uppercase tracking-wider text-outline">
                        OCR Transcript — {detail.question_label ?? `Q${activeIndex + 1}`} · Page{" "}
                        {currentPage.page_number}
                      </span>
                      <span className="font-mono text-label-sm text-outline">
                        {detail.ocr_confidence !== null ? `${formatConfidence(detail.ocr_confidence)} confidence` : ""}
                      </span>
                    </div>
                    <pre className="whitespace-pre-wrap font-mono text-[13px] leading-6 text-[#1e293b]">
                      {detail.transcription}
                    </pre>
                    {detail.is_handwriting_uncertain ? (
                      <p className="mt-space-sm flex items-center gap-1 rounded border border-review-border bg-review-bg px-2 py-1  text-label-sm text-review-fg">
                        <Icon name="warning" className="text-[14px]" /> Handwriting flagged as uncertain — verify
                        against the image.
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-on-surface-variant">
                <span className=" text-body-sm">No page image available yet.</span>
              </div>
            )}
          </div>
        </main>

        {/* Panel 3 — scoring deck */}
        <aside className="z-20 flex w-[390px] shrink-0 flex-col overflow-hidden bg-surface-container-lowest shadow-sm">
          <div className="flex shrink-0 items-center justify-between border-b border-outline-variant px-4 py-3">
            <div className="min-w-0">
              <h2 className="truncate font-display text-headline-sm font-semibold leading-tight text-primary">
                {detail ? `Question ${activeIndex + 1}: ${shortTitle(detail)}` : `Question ${activeIndex + 1}`}
              </h2>
              <div className="mt-0.5  text-label-sm text-outline">
                {detail?.question_type ? titleCase(detail.question_type) : "—"}
                {activeAnswer ? ` · ${answerLabel(activeAnswer.status)}` : ""}
              </div>
            </div>
            <span className="shrink-0 rounded border border-outline-variant bg-surface-container-low px-2 py-0.5 font-mono text-label-md font-semibold text-primary">
              Max: {(detail?.max_marks ?? activeAnswer?.max_marks ?? 0).toFixed(1)}
            </span>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
            {detailQuery.isLoading || !detail ? (
              <div className="flex flex-col gap-space-sm">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-32 w-full" />
              </div>
            ) : (
              <>
                {/* Question prompt */}
                {detail.question_text ? (
                  <div className="space-y-1 pb-3 border-b border-outline-variant">
                    <div className="label-overline">Question</div>
                    <p className=" text-body-sm leading-relaxed text-on-surface-variant">{detail.question_text}</p>
                  </div>
                ) : null}

                {/* Marking scheme */}
                <div className="space-y-1.5 border-b border-outline-variant pb-3">
                  <div className="label-overline">Marking Scheme</div>
                  {detail.marking_scheme.length > 0 ? (
                    <ul className="space-y-1  text-body-sm text-on-surface-variant">
                      {detail.marking_scheme.map((entry) => (
                        <li key={entry.id} className="flex items-center justify-between">
                          <span>• {entry.name}</span>
                          <span className="font-mono font-medium text-on-surface">{entry.max_marks.toFixed(1)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className=" text-body-sm text-on-surface-variant">
                      No criteria defined — scored holistically.
                    </p>
                  )}
                </div>

                {/* Suggested mark */}
                <div className="flex items-center justify-between rounded border border-outline-variant bg-surface-container-low p-2.5">
                  <div className="flex flex-col">
                    <span className=" text-label-sm text-outline">Suggested Mark</span>
                    <span
                      className={` text-[11px] font-medium ${
                        confidenceTone(detail.evaluation?.confidence_level, detail.evaluation?.confidence) === "verified"
                          ? "text-verified-fg"
                          : confidenceTone(detail.evaluation?.confidence_level, detail.evaluation?.confidence) === "review"
                            ? "text-review-fg"
                            : "text-critical-fg"
                      }`}
                    >
                      {detail.evaluation ? confidenceLabel(detail.evaluation.confidence_level) : "No AI suggestion"}
                    </span>
                  </div>
                  <div className="font-mono text-headline-lg font-bold tnum text-primary">
                    {detail.ai_score !== null ? detail.ai_score.toFixed(1) : "—"}
                    <span className=" font-normal text-outline"> / {detail.max_marks.toFixed(0)}</span>
                  </div>
                </div>

                {/* AI assessment */}
                {detail.evaluation ? (
                  <AiAssessment evaluation={detail.evaluation} />
                ) : (
                  <div className="space-y-2 border-b border-outline-variant pb-3">
                    <div className="label-overline">AI Assessment</div>
                    <p className=" text-body-sm text-on-surface-variant">
                      This answer has not been evaluated by the AI yet. You can award a mark directly, or queue a
                      re-evaluation.
                    </p>
                    <button
                      type="button"
                      className="btn-secondary w-full px-space-md py-1.5  text-label-md"
                      onClick={() => evaluateMutation.mutate()}
                      disabled={evaluateMutation.isPending}
                    >
                      {evaluateMutation.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="smart_toy" className="text-[16px]" />}
                      Run AI evaluation
                    </button>
                  </div>
                )}

                {/* Awarded marks */}
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <label htmlFor="awarded-mark-input" className=" text-label-md font-semibold text-primary">
                      Awarded Marks
                    </label>
                    <span className=" text-label-sm text-outline">0.0 – {detail.max_marks.toFixed(1)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      id="awarded-mark-input"
                      type="number"
                      min={0}
                      max={detail.max_marks}
                      step={0.5}
                      value={awarded}
                      onFocus={() => setOverrideMode(true)}
                      onChange={(e) => setAwarded(e.target.value)}
                      className="h-11 flex-1 rounded border border-outline-variant bg-surface-container-low px-3 text-center font-mono text-headline-sm font-bold tnum text-primary transition-all focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
                    />
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        aria-label="Increase mark"
                        className="flex h-5 w-8 items-center justify-center rounded border border-outline-variant bg-surface-container text-on-surface transition-colors hover:bg-surface-container-high"
                        onClick={() => setAwarded((v) => clamp(roundTo((Number(v) || 0) + 0.5, 0.5), 0, detail.max_marks).toFixed(1))}
                      >
                        <Icon name="expand_less" className="text-[14px]" />
                      </button>
                      <button
                        type="button"
                        aria-label="Decrease mark"
                        className="flex h-5 w-8 items-center justify-center rounded border border-outline-variant bg-surface-container text-on-surface transition-colors hover:bg-surface-container-high"
                        onClick={() => setAwarded((v) => clamp(roundTo((Number(v) || 0) - 0.5, 0.5), 0, detail.max_marks).toFixed(1))}
                      >
                        <Icon name="expand_more" className="text-[14px]" />
                      </button>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 pt-1">
                    <button
                      type="button"
                      onClick={accept}
                      disabled={reviewMutation.isPending}
                      className="flex h-9 w-full items-center justify-center gap-1.5 rounded bg-primary-container  text-body-sm font-semibold text-on-primary shadow-sm transition-colors hover:bg-secondary disabled:opacity-50"
                    >
                      {reviewMutation.isPending && reviewMutation.variables?.action === "accepted" ? (
                        <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" />
                      ) : (
                        <Icon name="check" className="text-[16px]" />
                      )}
                      Accept Suggestion (A)
                      {detail.ai_score !== null ? <span className="font-mono">· {detail.ai_score.toFixed(1)}</span> : null}
                    </button>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={override}
                        disabled={!overrideMode || reviewMutation.isPending}
                        className="flex h-8 items-center justify-center gap-1 rounded border border-outline-variant bg-surface-container-lowest  text-label-md font-medium text-on-surface transition-colors hover:bg-surface-container disabled:opacity-50"
                      >
                        <Icon name="edit" className="text-[14px]" /> Override (E)
                      </button>
                      <button
                        type="button"
                        onClick={flag}
                        disabled={reviewMutation.isPending}
                        className="flex h-8 items-center justify-center gap-1 rounded border border-outline-variant bg-surface-container-lowest  text-label-md font-medium text-critical-fg transition-colors hover:bg-critical-bg disabled:opacity-50"
                      >
                        <Icon name="flag" className="text-[14px]" /> Flag (F)
                      </button>
                    </div>
                  </div>
                </div>

                {/* Examiner note */}
                <div className="space-y-1 pt-1">
                  <label htmlFor="examiner-note" className=" text-label-sm font-medium text-outline">
                    Examiner Note
                  </label>
                  <textarea
                    id="examiner-note"
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Optional rationale, attached to your decision…"
                    className="w-full resize-none rounded border border-outline-variant bg-surface-container-low p-2  text-body-sm text-on-surface focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
                  />
                </div>

                {/* Decision history + provenance */}
                {detail.reviews.length > 0 ? (
                  <div className="space-y-1 border-t border-outline-variant pt-3">
                    <div className="label-overline">Decision History</div>
                    <ul className="space-y-1.5">
                      {detail.reviews.slice(0, 3).map((review) => (
                        <HistoryRow key={review.id} review={review} />
                      ))}
                    </ul>
                  </div>
                ) : null}

                {detail.evaluation ? <Provenance evaluation={detail.evaluation} /> : null}
              </>
            )}
          </div>

          {/* Shortcut footer */}
          <div className="flex shrink-0 items-center justify-between border-t border-outline-variant bg-surface-container-low px-3 py-2 font-mono text-[11px] text-on-surface-variant">
            <div className="flex items-center gap-2">
              <span>
                <strong className="text-primary">[A]</strong> Accept
              </span>
              <span>
                <strong className="text-primary">[E]</strong> Override
              </span>
              <span>
                <strong className="text-primary">[F]</strong> Flag
              </span>
              <span>
                <strong className="text-primary">[N]</strong> Next
              </span>
              <span>
                <strong className="text-primary">[P]</strong> Prev
              </span>
            </div>
            <button
              type="button"
              onClick={goNext}
              disabled={activeIndex >= answers.length - 1}
              className="flex h-7 items-center gap-1 rounded bg-primary px-2.5  font-medium text-on-primary transition-colors hover:bg-secondary disabled:opacity-50"
            >
              Next <Icon name="arrow_forward" className="text-[14px]" />
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function shortTitle(answer: Answer | AnswerDetail): string {
  const title = (answer as AnswerDetail).question_text;
  if (!title) return "";
  return title.trim().split(/\s+/).slice(0, 3).join(" ");
}

function AiAssessment({ evaluation }: { evaluation: Evaluation }) {
  const positives = evaluation.criteria.filter((c) => c.satisfied);
  const negatives = evaluation.criteria.filter((c) => !c.satisfied);
  return (
    <div className="space-y-2 border-b border-outline-variant pb-3">
      <div className="label-overline">AI Assessment</div>
      <p className=" text-body-sm leading-relaxed text-on-surface-variant">{evaluation.reasoning}</p>

      {evaluation.criteria.length > 0 ? (
        <div className="space-y-1 pt-1  text-body-sm">
          {evaluation.criteria.map((criterion) => (
            <div
              key={criterion.id}
              className={`flex items-center justify-between ${criterion.satisfied ? "text-verified-fg" : "text-critical-fg"}`}
              title={criterion.comment ?? undefined}
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="font-bold">{criterion.satisfied ? "✓" : "×"}</span>
                <span className="truncate">{criterion.name}</span>
              </span>
              <span className="shrink-0 font-mono font-medium">
                {criterion.satisfied ? `+${criterion.awarded_marks.toFixed(1)}` : `−${criterion.max_marks.toFixed(1)}`}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {evaluation.contradictions.length > 0 ? (
        <div className="rounded border border-critical-border bg-critical-bg px-2 py-1  text-label-sm text-critical-fg">
          <strong>Contradiction:</strong> {evaluation.contradictions.join("; ")}
        </div>
      ) : null}
      {positives.length === 0 && negatives.length === 0 && evaluation.gaps.length > 0 ? (
        <ul className="space-y-0.5  text-body-sm text-on-surface-variant">
          {evaluation.gaps.map((gap, i) => (
            <li key={i} className="flex items-center gap-1.5 text-critical-fg">
              <span className="font-bold">×</span> {gap}
            </li>
          ))}
        </ul>
      ) : null}
      {evaluation.flags.length > 0 ? (
        <ul className="space-y-0.5  text-label-sm text-review-fg">
          {evaluation.flags.map((flag, i) => (
            <li key={i} className="flex items-center gap-1">
              <Icon name="flag" className="text-[13px]" /> {flag}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function HistoryRow({ review }: { review: Review }) {
  return (
    <li className="flex items-start justify-between gap-space-sm rounded border border-outline-variant bg-surface-container-low px-2 py-1.5">
      <div className="min-w-0">
        <div className=" text-label-sm font-medium text-on-surface">
          {titleCase(review.decision)}
          {review.teacher_score !== null ? (
            <span className="ml-1 font-mono text-on-surface-variant">→ {review.teacher_score.toFixed(1)}</span>
          ) : null}
        </div>
        {review.reason ? (
          <p className="truncate  text-[11px] text-on-surface-variant">{review.reason}</p>
        ) : null}
      </div>
      <span className="shrink-0 font-mono text-[10px] text-outline">
        {formatMarks(review.ai_score)} → {formatMarks(review.teacher_score)}
      </span>
    </li>
  );
}

function Provenance({ evaluation }: { evaluation: Evaluation }) {
  return (
    <div className="space-y-1 border-t border-outline-variant pt-3">
      <div className="label-overline">Evaluation Provenance</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px] text-on-surface-variant">
        <span className="text-outline">provider</span>
        <span className="text-right">
          {evaluation.provider}
          {evaluation.is_mock ? " (mock)" : ""}
        </span>
        <span className="text-outline">model</span>
        <span className="truncate text-right">{evaluation.model}</span>
        <span className="text-outline">prompt</span>
        <span className="text-right">{evaluation.prompt_version}</span>
        <span className="text-outline">engine</span>
        <span className="text-right">{evaluation.engine_version}</span>
        <span className="text-outline">confidence</span>
        <span className="text-right">{formatConfidence(evaluation.confidence)}</span>
      </div>
      {evaluation.is_mock ? (
        <p className="rounded border border-review-border bg-review-bg px-2 py-1  text-[11px] text-review-fg">
          Mock provider — this score is deterministic and for demonstration only.
        </p>
      ) : null}
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { AuthImage } from "@/components/ui/AuthImage";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
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
import {
  clamp,
  formatConfidence,
  formatMarks,
  formatTimeAgo,
  roundTo,
  titleCase,
} from "@/lib/format";
import {
  answerLabel,
  answerTone,
  confidenceLabel,
  confidenceTone,
  decisionLabel,
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
      notify("Decision recorded", { tone: "verified" });
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

  const recordDecision = useCallback(() => {
    if (!detail) return;
    const value = Number(awarded);
    if (!Number.isFinite(value) || value < 0 || value > detail.max_marks) {
      notify("Mark out of range", { tone: "critical", detail: `Enter a value between 0 and ${detail.max_marks}.` });
      return;
    }
    const matchesSuggestion = detail.ai_score !== null && Math.abs(value - detail.ai_score) < 0.05;
    reviewMutation.mutate({
      action: matchesSuggestion ? "accepted" : "overridden",
      teacher_score: matchesSuggestion ? undefined : value,
      comment: note.trim() || undefined,
      reason: matchesSuggestion ? undefined : note.trim() || undefined,
    });
  }, [awarded, detail, note, notify, reviewMutation]);

  const useSuggestion = useCallback(() => {
    if (detail?.ai_score == null) return;
    setAwarded(detail.ai_score.toFixed(1));
  }, [detail]);

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
        recordDecision();
      } else if (key === "e") {
        e.preventDefault();
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
  }, [flag, goNext, goPrev, recordDecision]);

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
      <div className="flex h-[calc(100dvh-3.5rem)] items-center justify-center bg-desk">
        <div className="flex flex-col items-center gap-space-sm text-desk-muted">
          <Spinner className="h-5 w-5" />
          <span className="text-body-sm">Preparing workspace…</span>
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

  const awardedValue = Number(awarded);
  const markIsValid =
    Number.isFinite(awardedValue) && awardedValue >= 0 && awardedValue <= (detail?.max_marks ?? 0);
  const matchesSuggestion =
    detail?.ai_score != null && Number.isFinite(awardedValue)
      ? Math.abs(awardedValue - detail.ai_score) < 0.05
      : false;
  const markDelta = detail?.ai_score != null ? awardedValue - detail.ai_score : null;

  return (
    <>
      <div className="on-desk flex h-[calc(100dvh-3.5rem)] flex-col overflow-y-auto bg-desk px-4 py-8 text-desk-text md:hidden">
        <div className="mx-auto flex w-full max-w-sm flex-col gap-6">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-desk-muted">
              Marking workspace
            </div>
            <h1 className="mt-3 font-reading text-[32px] font-medium leading-[1.12] tracking-tight">
              This desk needs a wider screen.
            </h1>
            <p className="mt-3 text-body-md leading-6 text-desk-muted">
              Reviewing handwriting against a marking scheme needs the manuscript and decision dock side by
              side. Open this script on a tablet or desktop to mark it. You can still inspect the submission
              record here.
            </p>
          </div>

          <div className="border-y border-desk-line py-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-desk-muted">
              Candidate
            </div>
            <div className="mt-1 text-headline-sm font-semibold text-desk-text">
              {submission.student_name ?? "Unnamed candidate"}
            </div>
            <div className="mt-1 font-mono text-label-sm text-desk-muted">
              {submission.student_roll ?? "No roll"} · Sheet{" "}
              {siblingIndex >= 0 ? siblingIndex + 1 : 1}/{siblingList.length || 1}
            </div>
            <div className="mt-3 text-body-sm text-desk-muted">
              {examQuery.data?.title ?? "Examination"}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Link
              to={`/submissions/${submissionId}`}
              className="inline-flex min-h-[2.75rem] items-center justify-center rounded bg-primary-fixed px-4 text-body-sm font-semibold text-on-primary-fixed"
            >
              Open submission record
            </Link>
            <Link
              to="/evaluation"
              className="inline-flex min-h-[2.75rem] items-center justify-center rounded border border-desk-line px-4 text-body-sm text-desk-text"
            >
              Back to evaluation queue
            </Link>
          </div>
        </div>
      </div>

      <div className="on-desk hidden h-[calc(100dvh-3.5rem)] min-h-0 w-full flex-col overflow-hidden bg-desk md:flex">
        <header className="z-30 flex min-h-[3.5rem] shrink-0 flex-wrap items-center justify-between gap-space-sm border-b border-desk-line bg-desk px-gutter py-2">
          <div className="flex min-w-0 items-center gap-space-sm">
            <nav className="hidden items-center gap-1.5 text-body-sm text-desk-muted xl:flex">
              <Link to="/evaluation" className="rounded transition-colors hover:text-desk-text">
                Evaluation
              </Link>
              <span className="text-desk-line">/</span>
              <Link
                to={`/exams/${submission.exam_id}`}
                className="max-w-[12rem] truncate font-medium text-desk-text transition-colors hover:text-primary-fixed-dim"
              >
                {examQuery.data?.title ?? "Examination"}
              </Link>
              <span className="text-desk-line">/</span>
            </nav>
            <div className="flex min-w-0 items-center gap-2 rounded border border-desk-line bg-desk-raised px-2 py-1">
              <Icon name="person" className="shrink-0 text-[16px] text-desk-muted" />
              <span className="max-w-[11rem] truncate text-label-md font-medium text-desk-text">
                {submission.student_name ?? "Unnamed candidate"}
              </span>
              <span className="shrink-0 border-l border-desk-line pl-2 font-mono text-[10px] text-desk-muted">
                {submission.student_roll ?? "no roll"}
              </span>
              <span className="hidden shrink-0 font-mono text-[10px] text-desk-muted sm:inline">
                Sheet {siblingIndex >= 0 ? siblingIndex + 1 : 1}/{siblingList.length || 1}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                title="Previous candidate"
                disabled={siblingIndex <= 0}
                onClick={() => navigate(`/submissions/${siblingList[siblingIndex - 1].id}/evaluate`)}
                className="flex h-8 items-center gap-0.5 rounded border border-desk-line px-2 text-label-sm text-desk-text transition-colors hover:bg-desk-raised disabled:opacity-35 lg:px-2.5"
              >
                <Icon name="chevron_left" className="text-[14px]" />
                <span className="hidden lg:inline">Prev</span>
              </button>
              <button
                type="button"
                title="Next candidate"
                disabled={siblingIndex < 0 || siblingIndex >= siblingList.length - 1}
                onClick={() => navigate(`/submissions/${siblingList[siblingIndex + 1].id}/evaluate`)}
                className="flex h-8 items-center gap-0.5 rounded border border-desk-line px-2 text-label-sm text-desk-text transition-colors hover:bg-desk-raised disabled:opacity-35 lg:px-2.5"
              >
                <span className="hidden lg:inline">Next</span>
                <Icon name="chevron_right" className="text-[14px]" />
              </button>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-space-sm">
            <label className="flex items-center gap-1.5 2xl:hidden">
              <span className="sr-only">Question</span>
              <Icon name="list_alt" className="text-[16px] text-desk-muted" />
              <select
                value={activeIndex}
                onChange={(e) => selectAnswer(Number(e.target.value))}
                className="h-8 max-w-[190px] rounded border border-desk-line bg-desk-raised px-2 font-mono text-[11px] text-desk-text"
              >
                {answers.map((answer, index) => (
                  <option key={answer.id} value={index}>
                    Q{index + 1} · {answerLabel(answer.status)}
                  </option>
                ))}
              </select>
            </label>
            <div
              className="hidden items-center gap-1.5 border-l border-desk-line pl-3 md:flex"
              title={`${reviewedCount} of ${answers.length} answers have a teacher decision.`}
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-desk-muted">
                Reviewed
              </span>
              <span className="font-mono text-label-sm font-semibold tnum text-desk-text">
                {reviewedCount}/{answers.length}
              </span>
            </div>
            <div
              className="hidden items-center gap-2 border-l border-desk-line pl-3 xl:flex"
              title="Includes AI suggestions for answers that have not been reviewed yet."
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-desk-muted">
                Provisional
              </span>
              <span className="font-mono text-headline-sm font-semibold tnum text-desk-text">
                {runningTotal.toFixed(1)}
              </span>
              <span className="font-mono text-label-sm text-desk-muted">/ {maxTotal.toFixed(1)}</span>
            </div>
            <button
              type="button"
              onClick={() => finalizeMutation.mutate()}
              disabled={finalizeMutation.isPending || reviewedCount < answers.length}
              className="flex min-h-[2rem] items-center gap-1.5 rounded bg-primary-fixed px-3 text-body-sm font-semibold text-on-primary-fixed transition-colors hover:bg-primary-fixed-dim disabled:cursor-not-allowed disabled:opacity-45"
              title={
                reviewedCount < answers.length
                  ? `${answers.length - reviewedCount} answers still need a teacher decision`
                  : "Finalise this sheet"
              }
            >
              {finalizeMutation.isPending ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <Icon name="task_alt" className="text-[16px]" />
              )}
              Finalise
            </button>
          </div>
        </header>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {/* Panel 1 — question roster */}
        <aside className="z-10 hidden w-60 shrink-0 flex-col overflow-hidden border-r border-desk-line bg-desk 2xl:flex">
          <div className="flex flex-col gap-2 border-b border-desk-line p-space-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Icon name="list_alt" className="text-[16px] text-desk-muted" />
                <span className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-desk-text">
                  Question roster
                </span>
              </div>
              <span className="rounded border border-desk-line px-1.5 py-0.5 font-mono text-[10px] text-desk-muted">
                {answers.length}
              </span>
            </div>
            <label className="flex min-h-[1.75rem] cursor-pointer items-center gap-2 text-label-sm text-desk-muted">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary-fixed-dim"
                checked={reviewOnly}
                onChange={(e) => setReviewOnly(e.target.checked)}
              />
              Review needed only
            </label>
          </div>
          <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-1.5">
            {roster.map((answer) => {
              const index = answers.findIndex((a) => a.id === answer.id);
              const isActive = answer.id === activeAnswer?.id;
              const tone = answerTone(answer.status, answer.is_flagged);
              const toneClass =
                tone === "review"
                  ? "text-review-border"
                  : tone === "critical"
                    ? "text-critical-border"
                    : tone === "verified"
                      ? "text-verified-border"
                      : tone === "info"
                        ? "text-primary-fixed-dim"
                        : "text-desk-muted";
              return (
                <button
                  key={answer.id}
                  type="button"
                  onClick={() => selectAnswer(index)}
                  className={`flex min-h-[3rem] items-center justify-between gap-2 rounded px-2.5 py-2 text-left transition-colors ${
                    isActive ? "bg-desk-high" : "hover:bg-desk-raised"
                  }`}
                >
                  <div className="flex min-w-0 flex-col">
                    <span
                      className={`truncate text-body-sm ${
                        isActive ? "font-semibold text-desk-text" : "font-medium text-desk-text/90"
                      }`}
                    >
                      Q{index + 1} {shortTitle(answer)}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1 font-mono text-[10px]">
                      <span className={`uppercase tracking-[0.06em] ${toneClass}`}>
                        {answerLabel(answer.status)}
                      </span>
                      {answer.page_numbers.length > 0 ? (
                        <span
                          className="text-desk-muted"
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
                        <span className="text-desk-muted" title="Page mapping uncertain — navigate manually.">
                          · p.?
                        </span>
                      )}
                    </span>
                  </div>
                  <span className="shrink-0 font-mono text-body-sm font-medium tnum text-desk-text">
                    {answer.final_score ?? answer.ai_score ?? "—"} / {answer.max_marks}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="flex flex-col gap-1.5 border-t border-desk-line p-space-sm">
            <div className="flex items-center justify-between text-label-sm text-desk-muted">
              <span>
                Reviewed {reviewedCount} / {answers.length}
              </span>
              <span className="font-mono text-[10px] text-desk-text">
                {answers.length ? Math.round((reviewedCount / answers.length) * 100) : 0}%
              </span>
            </div>
            <ProgressBar
              value={answers.length ? (reviewedCount / answers.length) * 100 : 0}
              tone="info"
              height="h-1.5"
            />
            <div className="flex items-center justify-between pt-1 font-mono text-[10px] text-desk-muted">
              <span>Saved on each decision</span>
              <Icon name="cloud_done" className="text-[14px] text-verified-border" />
            </div>
          </div>
        </aside>

        {/* Panel 2 — document viewer */}
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-desk">
          <div className="z-10 flex min-h-[2.75rem] shrink-0 flex-wrap items-center justify-between gap-2 border-b border-desk-line bg-desk-raised px-gutter py-1.5">
            <div className="flex shrink-0 items-center gap-1 text-desk-muted">
              <button
                type="button"
                title="Zoom out"
                className="flex h-8 w-8 items-center justify-center rounded transition-colors hover:bg-desk-high hover:text-desk-text"
                onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))}
              >
                <Icon name="remove" className="text-[16px]" />
              </button>
              <span className="px-1 font-mono text-label-sm font-medium text-desk-text">{zoom}%</span>
              <button
                type="button"
                title="Zoom in"
                className="flex h-8 w-8 items-center justify-center rounded transition-colors hover:bg-desk-high hover:text-desk-text"
                onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))}
              >
                <Icon name="add" className="text-[16px]" />
              </button>
              <div className="mx-1.5 h-3.5 w-px bg-desk-line" />
              <button
                type="button"
                title="Reset zoom to 100%"
                className="flex h-8 items-center gap-1 rounded px-2 text-label-sm text-desk-text transition-colors hover:bg-desk-high"
                onClick={() => setZoom(100)}
              >
                <Icon name="crop_free" className="text-[15px]" /> Reset
              </button>
              <button
                type="button"
                title="Rotate manuscript"
                className="flex h-8 w-8 items-center justify-center rounded text-desk-text transition-colors hover:bg-desk-high"
                onClick={() => setRotation((r) => (r + 90) % 360)}
              >
                <Icon name="rotate_right" className="text-[16px]" />
              </button>
              <button
                type="button"
                aria-pressed={showOcr}
                onClick={() => setShowOcr((v) => !v)}
                className={`flex h-8 items-center gap-1 whitespace-nowrap rounded px-2 text-label-sm font-medium transition-colors ${
                  showOcr
                    ? "bg-primary-fixed text-on-primary-fixed"
                    : "text-desk-muted hover:bg-desk-high hover:text-desk-text"
                }`}
              >
                <Icon name="document_scanner" className="text-[16px]" /> OCR {showOcr ? "on" : "off"}
              </button>
            </div>

            <div className="flex min-w-0 items-center gap-2 text-label-sm text-desk-muted">
              <span className="truncate">
                Page {currentPage ? currentPage.page_number : 0} of {submissionPages.length}
              </span>
              {pageChip ? (
                <span
                  className={`shrink-0 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                    mappingUncertain
                      ? "border-review-border/60 bg-desk-high text-review-border"
                      : "border-desk-line text-desk-muted"
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
                className="flex h-8 items-center gap-1 whitespace-nowrap rounded px-2 text-label-sm text-desk-text transition-colors hover:bg-desk-high disabled:opacity-35"
                disabled={!pagePosition?.canPrev}
                onClick={() => goPage(-1)}
              >
                <Icon name="arrow_back" className="text-[14px]" /> <span className="hidden lg:inline">Prev</span>
              </button>
              <span
                className="px-1.5 font-mono text-label-sm font-semibold text-desk-text"
                title={answerPageList.length > 1 ? "Current answer page" : "Current manuscript page"}
              >
                {pagePosition ? pagePosition.index + 1 : viewPage + 1} /{" "}
                {pagePosition ? pagePosition.total : submissionPages.length || 0}
              </span>
              <button
                type="button"
                title={answerPageList.length > 1 ? "Next page of this answer" : "Next manuscript page"}
                className="flex h-8 items-center gap-1 whitespace-nowrap rounded px-2 text-label-sm text-desk-text transition-colors hover:bg-desk-high disabled:opacity-35"
                disabled={!pagePosition?.canNext}
                onClick={() => goPage(1)}
              >
                <span className="hidden lg:inline">Next</span>{" "}
                <Icon name="arrow_forward" className="text-[14px]" />
              </button>
            </div>
          </div>

          <div
            ref={viewerScrollRef}
            className="flex flex-1 items-start justify-center overflow-auto bg-desk p-space-md"
          >
            {currentPage ? (
              <div
                className="flex w-full min-w-0 max-w-[820px] flex-col gap-space-md"
                style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
              >
                <div
                  ref={pageImageWrapRef}
                  className="relative w-full transition-transform"
                  style={{ transform: `rotate(${rotation}deg)` }}
                >
                  <AuthImage
                    path={`/pages/${currentPage.id}/image?variant=processed`}
                    alt={`Page ${currentPage.page_number}`}
                    className="w-full rounded-sm border border-outline-variant bg-surface-container-lowest shadow-paper"
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
                  <div className="w-full rounded-sm border border-outline-variant bg-surface-container-lowest p-5 shadow-paper sm:p-6">
                    <div className="mb-space-sm flex flex-wrap items-center justify-between gap-2 border-b border-outline-variant pb-2">
                      <span className="font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-outline">
                        Transcript — {detail.question_label ?? `Q${activeIndex + 1}`} · Page{" "}
                        {currentPage.page_number}
                      </span>
                      <span className="font-mono text-[10px] text-outline">
                        {detail.ocr_confidence !== null
                          ? `${formatConfidence(detail.ocr_confidence)} confidence`
                          : ""}
                      </span>
                    </div>
                    <pre className="whitespace-pre-wrap font-reading text-reading-md text-on-surface">
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
              <div className="flex h-full items-center justify-center text-desk-muted">
                <span className="text-body-sm">No page image available yet.</span>
              </div>
            )}
          </div>
        </main>

        {/* Panel 3 — scoring deck */}
        <aside className="z-20 hidden w-[360px] shrink-0 flex-col overflow-hidden border-l border-desk-line bg-surface-container-lowest md:flex xl:w-[390px]">
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-outline-variant px-4 py-3">
            <div className="min-w-0">
              <div className="label-overline">Question {activeIndex + 1}</div>
              <h2 className="mt-1 truncate font-reading text-[23px] font-medium leading-tight text-primary">
                {detail?.question_label ?? `Question ${activeIndex + 1}`}
              </h2>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-label-sm text-on-surface-variant">
                <span>{detail?.question_type ? titleCase(detail.question_type) : "—"}</span>
                {activeAnswer ? (
                  <StatusBadge
                    tone={answerTone(activeAnswer.status, activeAnswer.is_flagged)}
                    label={answerLabel(activeAnswer.status)}
                    dot
                  />
                ) : null}
              </div>
            </div>
            <span className="shrink-0 rounded border border-outline-variant px-2 py-1 font-mono text-[10px] text-on-surface-variant">
              Max{" "}
              <strong className="font-medium text-primary">
                {(detail?.max_marks ?? activeAnswer?.max_marks ?? 0).toFixed(1)}
              </strong>
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4">
            {detailQuery.isLoading || !detail ? (
              <div className="flex flex-col gap-space-sm py-4">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-32 w-full" />
              </div>
            ) : (
              <>
                {detail.question_text ? (
                  <section className="space-y-1 border-b border-outline-variant py-3">
                    <div className="label-overline">Question</div>
                    <p className="font-reading text-reading-md leading-snug text-on-surface">
                      {detail.question_text}
                    </p>
                  </section>
                ) : null}

                <section className="space-y-2 border-b border-outline-variant py-3">
                  <div className="label-overline">Marking scheme</div>
                  {detail.marking_scheme.length > 0 ? (
                    <ul className="text-body-sm text-on-surface-variant">
                      {detail.marking_scheme.map((entry, index) => (
                        <li
                          key={entry.id}
                          className="flex items-baseline justify-between gap-2 border-b border-outline-variant/60 py-1.5 last:border-0"
                        >
                          <span className="flex min-w-0 items-baseline gap-2">
                            <span className="font-mono text-[10px] text-outline">
                              {String(index + 1).padStart(2, "0")}
                            </span>
                            <span>{entry.name}</span>
                          </span>
                          <span className="shrink-0 font-mono font-medium text-on-surface">
                            {entry.max_marks.toFixed(1)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-body-sm text-on-surface-variant">
                      No criteria defined — scored holistically.
                    </p>
                  )}
                </section>

                <section className="flex items-end justify-between gap-3 border-b border-outline-variant py-3">
                  <div className="flex flex-col">
                    <span className="label-overline">AI suggestion</span>
                    <span
                      className={`mt-1 text-[11px] font-medium ${
                        confidenceTone(
                          detail.evaluation?.confidence_level,
                          detail.evaluation?.confidence,
                        ) === "verified"
                          ? "text-verified-fg"
                          : confidenceTone(
                                detail.evaluation?.confidence_level,
                                detail.evaluation?.confidence,
                              ) === "review"
                            ? "text-review-fg"
                            : "text-critical-fg"
                      }`}
                    >
                      {detail.evaluation
                        ? confidenceLabel(detail.evaluation.confidence_level)
                        : "No AI suggestion"}
                    </span>
                  </div>
                  <div className="font-mono text-[30px] font-medium leading-none tnum text-primary">
                    {detail.ai_score !== null ? detail.ai_score.toFixed(1) : "—"}
                    <span className="font-normal text-outline"> / {detail.max_marks.toFixed(0)}</span>
                  </div>
                </section>

                {detail.evaluation ? (
                  <AiAssessment evaluation={detail.evaluation} />
                ) : (
                  <section className="space-y-2 border-b border-outline-variant py-3">
                    <div className="label-overline">AI assessment</div>
                    <p className="text-body-sm text-on-surface-variant">
                      This answer has not been evaluated by the AI yet. You can award a mark directly, or
                      queue a re-evaluation.
                    </p>
                    <button
                      type="button"
                      className="btn-secondary w-full px-space-md py-2 text-label-md"
                      onClick={() => evaluateMutation.mutate()}
                      disabled={evaluateMutation.isPending}
                    >
                      {evaluateMutation.isPending ? (
                        <Spinner className="h-3.5 w-3.5" />
                      ) : (
                        <Icon name="smart_toy" className="text-[16px]" />
                      )}
                      Run AI evaluation
                    </button>
                  </section>
                )}

                <section className="space-y-1.5 border-b border-outline-variant py-3">
                  <div className="label-overline">Decision ledger</div>
                  {detail.reviews.length > 0 ? (
                    <ul>
                      {detail.reviews.slice(0, 5).map((review) => (
                        <HistoryRow key={review.id} review={review} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-body-sm text-on-surface-variant">
                      No decisions recorded yet.
                    </p>
                  )}
                </section>

                {detail.evaluation ? <Provenance evaluation={detail.evaluation} /> : null}
              </>
            )}
          </div>

          {detail ? (
            <div className="shrink-0 border-t border-outline-variant bg-surface-container-low px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <label htmlFor="awarded-mark-input" className="text-label-md font-semibold text-primary">
                  Mark awarded
                </label>
                <span className="font-mono text-[10px] text-outline">0.0 – {detail.max_marks.toFixed(1)}</span>
              </div>
              <div className="mt-2 flex items-stretch gap-2">
                <input
                  id="awarded-mark-input"
                  type="number"
                  min={0}
                  max={detail.max_marks}
                  step={0.5}
                  value={awarded}
                  onChange={(e) => setAwarded(e.target.value)}
                  aria-invalid={!markIsValid}
                  className={`h-12 min-w-0 flex-1 rounded border bg-surface-container-lowest px-3 text-center font-mono text-[24px] font-semibold tnum text-primary transition-colors focus:outline-none focus:ring-2 ${
                    markIsValid
                      ? "border-outline-variant focus:border-secondary focus:ring-secondary/35"
                      : "border-critical focus:border-critical focus:ring-critical/35"
                  }`}
                />
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    aria-label="Increase mark"
                    className="flex h-[22px] w-9 items-center justify-center rounded border border-outline-variant bg-surface-container-lowest text-on-surface transition-colors hover:bg-surface-container"
                    onClick={() =>
                      setAwarded((v) =>
                        clamp(roundTo((Number(v) || 0) + 0.5, 0.5), 0, detail.max_marks).toFixed(1),
                      )
                    }
                  >
                    <Icon name="expand_less" className="text-[14px]" />
                  </button>
                  <button
                    type="button"
                    aria-label="Decrease mark"
                    className="flex h-[22px] w-9 items-center justify-center rounded border border-outline-variant bg-surface-container-lowest text-on-surface transition-colors hover:bg-surface-container"
                    onClick={() =>
                      setAwarded((v) =>
                        clamp(roundTo((Number(v) || 0) - 0.5, 0.5), 0, detail.max_marks).toFixed(1),
                      )
                    }
                  >
                    <Icon name="expand_more" className="text-[14px]" />
                  </button>
                </div>
              </div>

              <div className="mt-1.5 flex min-h-[1.25rem] items-center justify-between gap-2">
                <span
                  className={`font-mono text-[10px] ${
                    !markIsValid
                      ? "text-critical-fg"
                      : matchesSuggestion
                        ? "text-verified-fg"
                        : "text-review-fg"
                  }`}
                >
                  {!markIsValid
                    ? `Enter a mark between 0 and ${detail.max_marks}`
                    : detail.ai_score === null
                      ? "No AI suggestion — record a teacher mark"
                      : matchesSuggestion
                        ? "Matches the AI suggestion"
                        : `Overrides the AI by ${markDelta! >= 0 ? "+" : ""}${markDelta!.toFixed(1)}`}
                </span>
                {detail.ai_score !== null && !matchesSuggestion ? (
                  <button
                    type="button"
                    onClick={useSuggestion}
                    className="shrink-0 rounded px-1 font-mono text-[10px] text-secondary hover:underline"
                  >
                    Use {detail.ai_score.toFixed(1)}
                  </button>
                ) : null}
              </div>

              <div className="mt-2">
                <label htmlFor="examiner-note" className="text-label-sm font-medium text-on-surface-variant">
                  Decision note <span className="font-normal text-outline">(optional)</span>
                </label>
                <textarea
                  id="examiner-note"
                  rows={2}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Why this mark?"
                  className="mt-1 w-full resize-none rounded border border-outline-variant bg-surface-container-lowest px-2.5 py-2 text-body-sm text-on-surface placeholder:text-on-surface-variant/60 focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/35"
                />
              </div>

              <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                <button
                  type="button"
                  onClick={recordDecision}
                  disabled={!markIsValid || reviewMutation.isPending}
                  className="btn-primary h-10 px-3 text-body-sm font-semibold"
                >
                  {reviewMutation.isPending ? (
                    <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" />
                  ) : (
                    <Icon name="check" className="text-[16px]" />
                  )}
                  {reviewMutation.isPending
                    ? "Recording…"
                    : activeAnswer?.is_reviewed
                      ? `Update to ${awardedValue.toFixed(1)}`
                      : matchesSuggestion
                        ? `Accept ${awardedValue.toFixed(1)}`
                        : `Record ${awardedValue.toFixed(1)}`}
                </button>
                <button
                  type="button"
                  onClick={flag}
                  disabled={reviewMutation.isPending}
                  className="flex h-10 items-center justify-center gap-1 rounded border border-critical-border px-3 text-label-md font-medium text-critical-fg transition-colors hover:bg-critical-bg disabled:opacity-50"
                >
                  <Icon name="flag" className="text-[14px]" /> Flag
                </button>
              </div>

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-outline-variant pt-2 font-mono text-[10px] text-on-surface-variant">
                <span>
                  <strong className="text-primary">[A]</strong> record ·{" "}
                  <strong className="text-primary">[E]</strong> edit ·{" "}
                  <strong className="text-primary">[F]</strong> flag ·{" "}
                  <strong className="text-primary">[N]</strong> next ·{" "}
                  <strong className="text-primary">[P]</strong> previous
                </span>
                <button
                  type="button"
                  onClick={goNext}
                  disabled={activeIndex >= answers.length - 1}
                  className="flex min-h-[1.75rem] items-center gap-1 rounded px-1.5 text-primary transition-colors hover:bg-surface-container disabled:opacity-40"
                >
                  Next <Icon name="arrow_forward" className="text-[14px]" />
                </button>
              </div>
            </div>
          ) : null}
        </aside>
      </div>
      </div>
    </>
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
    <section className="space-y-2 border-b border-outline-variant py-3">
      <div className="label-overline">AI assessment</div>
      <p className="font-reading text-[16px] leading-6 text-on-surface-variant">
        {evaluation.reasoning}
      </p>

      {evaluation.criteria.length > 0 ? (
        <div className="text-body-sm">
          {evaluation.criteria.map((criterion) => (
            <div
              key={criterion.id}
              className={`flex items-center justify-between gap-2 border-b border-outline-variant/60 py-1.5 last:border-0 ${
                criterion.satisfied ? "text-verified-fg" : "text-critical-fg"
              }`}
              title={criterion.comment ?? undefined}
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="font-mono font-medium">
                  {criterion.satisfied ? "✓" : "×"}
                </span>
                <span className="truncate">{criterion.name}</span>
              </span>
              <span className="shrink-0 font-mono font-medium">
                {criterion.satisfied
                  ? `+${criterion.awarded_marks.toFixed(1)}`
                  : `−${criterion.max_marks.toFixed(1)}`}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {evaluation.contradictions.length > 0 ? (
        <div className="border-y border-critical-border bg-critical-bg px-2 py-1.5 text-label-sm text-critical-fg">
          <strong>Contradiction:</strong> {evaluation.contradictions.join("; ")}
        </div>
      ) : null}
      {positives.length === 0 && negatives.length === 0 && evaluation.gaps.length > 0 ? (
        <ul className="space-y-1 text-body-sm text-on-surface-variant">
          {evaluation.gaps.map((gap, i) => (
            <li key={i} className="flex items-start gap-1.5 text-critical-fg">
              <span className="font-mono">×</span> {gap}
            </li>
          ))}
        </ul>
      ) : null}
      {evaluation.flags.length > 0 ? (
        <ul className="space-y-1 text-label-sm text-review-fg">
          {evaluation.flags.map((flag, i) => (
            <li key={i} className="flex items-start gap-1">
              <Icon name="flag" className="mt-0.5 text-[13px]" /> {flag}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function HistoryRow({ review }: { review: Review }) {
  return (
    <li className="flex items-start justify-between gap-space-sm border-b border-outline-variant/70 py-2 last:border-0">
      <div className="min-w-0">
        <div className="text-body-sm font-medium text-on-surface">
          {decisionLabel(review.decision)}
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-outline">
          {formatTimeAgo(review.created_at)}
        </div>
        {review.reason ? (
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-on-surface-variant">
            {review.reason}
          </p>
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
    <section className="space-y-2 border-b border-outline-variant py-3">
      <div className="label-overline">Evaluation provenance</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] text-on-surface-variant">
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
        <p className="border-y border-review-border bg-review-bg px-2 py-1.5 text-[11px] leading-4 text-review-fg">
          Mock provider — this score is deterministic and for demonstration only.
        </p>
      ) : null}
    </section>
  );
}

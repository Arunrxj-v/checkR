import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { useCrumbs } from "@/components/layout/AppShell";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { examApi, submissionApi } from "@/lib/api";
import { formatDate, formatPercent, pluralize } from "@/lib/format";
import { isProcessing, submissionLabel, submissionTone } from "@/lib/status";
import type { Exam, ExamStats, Page, Submission } from "@/lib/types";

function examProgress(stats: ExamStats | undefined) {
  if (!stats || stats.submission_count === 0) return { pct: 0, done: 0, total: 0 };
  const done = stats.completed_count;
  return {
    pct: Math.round((done / stats.submission_count) * 100),
    done,
    total: stats.submission_count,
  };
}

function examStatusBadge(stats: ExamStats | undefined) {
  if (!stats || stats.submission_count === 0) return { tone: "neutral" as const, label: "No sheets" };
  if (stats.failed_count > 0) return { tone: "critical" as const, label: "Attention" };
  if (stats.processing_count > 0) return { tone: "info" as const, label: "Processing" };
  if (stats.pending_review_count > 0 || stats.in_review_count > 0)
    return { tone: "review" as const, label: "In Review" };
  if (stats.completed_count === stats.submission_count) return { tone: "verified" as const, label: "Completed" };
  return { tone: "neutral" as const, label: "Draft" };
}

function actionFor(stats: ExamStats | undefined): { label: string; to: string } {
  if (!stats || stats.submission_count === 0) return { label: "Open", to: "exam" };
  if (stats.pending_review_count > 0 || stats.in_review_count > 0) return { label: "Evaluate", to: "evaluation" };
  if (stats.completed_count === stats.submission_count) return { label: "Results", to: "results" };
  return { label: "Open", to: "exam" };
}

export function DashboardPage() {
  useCrumbs([{ label: "Dashboard" }]);
  const navigate = useNavigate();

  const examsQuery = useQuery({
    queryKey: ["exams", "dashboard"],
    queryFn: () => examApi.list({ limit: 8 }),
  });

  const submissionsQuery = useQuery({
    queryKey: ["submissions", "dashboard"],
    queryFn: () => submissionApi.list({ limit: 200 }),
  });

  const examList = examsQuery.data?.items ?? [];

  const statQueries = useQueries({
    queries: examList.map((exam: Exam) => ({
      queryKey: ["exam-stats", exam.id],
      queryFn: () => examApi.stats(exam.id),
      staleTime: 30_000,
    })),
  });

  const statsById = useMemo(() => {
    const map = new Map<string, ExamStats>();
    examList.forEach((exam, index) => {
      const data = statQueries[index]?.data;
      if (data) map.set(exam.id, data);
    });
    return map;
  }, [examList, statQueries]);

  const metrics = useMemo(() => {
    const items = submissionsQuery.data?.items ?? [];
    const pending = items.filter((s) => s.status === "ready_for_review").length;
    const processing = items.filter((s) => isProcessing(s.status)).length;
    const completed = items.filter((s) => s.status === "completed").length;
    const scored = items.filter((s) => s.status === "completed" && s.max_total_marks > 0);
    const avg =
      scored.length > 0
        ? scored.reduce((acc, s) => acc + (s.final_total_marks / s.max_total_marks) * 100, 0) / scored.length
        : null;
    return { pending, processing, completed, avg };
  }, [submissionsQuery.data]);

  const needsAttention = useMemo(() => {
    const items = submissionsQuery.data?.items ?? [];
    return items
      .filter((s) => s.flagged_count > 0 || s.status === "failed")
      .slice(0, 5);
  }, [submissionsQuery.data]);

  const loadingExams = examsQuery.isLoading;
  const loadingSubs = submissionsQuery.isLoading;

  return (
    <PageContainer>
      <PageHeader
        title="Examination operations"
        description="Active papers, review queues, and finalisation status across the desk."
        actions={
          <>
            <Link to="/answer-sheets" className="btn-secondary h-8 px-space-md  text-label-md">
              <Icon name="upload_file" className="text-[16px]" />
              Import
            </Link>
            <Link to="/exams" className="btn-primary h-8 px-space-md  text-label-md">
              <Icon name="add" className="text-[16px]" />
              New Examination
            </Link>
          </>
        }
      />

      {/* Quiet, flat metric row */}
      <div className="grid grid-cols-2 divide-y divide-outline-variant rounded border border-outline-variant bg-surface-container-lowest lg:grid-cols-4 lg:divide-x lg:divide-y-0">
        <Metric label="Pending Review" value={loadingSubs ? null : metrics.pending} />
        <Metric label="Processing" value={loadingSubs ? null : metrics.processing} />
        <Metric label="Completed" value={loadingSubs ? null : metrics.completed} />
        <Metric
          label="Average Score"
          value={loadingSubs ? null : metrics.avg === null ? "—" : formatPercent(metrics.avg)}
        />
      </div>

      {/* Examination table */}
      <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
        <div className="flex flex-wrap items-center justify-between gap-space-sm border-b border-outline-variant px-space-md py-space-sm">
          <div className="flex items-center gap-space-sm">
            <h2 className="font-display text-headline-sm font-semibold text-primary">
              Active examinations
            </h2>
            <span className="rounded border border-outline-variant bg-surface-container-low px-1.5 py-0.5 font-mono text-[10px] text-on-surface-variant">
              {examList.length}
            </span>
          </div>
          <span className="text-label-sm text-outline">
            {examsQuery.data ? `${examsQuery.data.total} total` : "Loading"}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                <th className="px-space-md py-2.5 font-medium">Examination Name</th>
                <th className="px-space-md py-2.5 font-medium">Subject</th>
                <th className="px-space-md py-2.5 font-medium">Date</th>
                <th className="px-space-md py-2.5 text-right font-medium">Sheets</th>
                <th className="w-48 px-space-md py-2.5 font-medium">Progress</th>
                <th className="px-space-md py-2.5 font-medium">Status</th>
                <th className="px-space-md py-2.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant  text-body-sm">
              {loadingExams ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-space-md py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))
              ) : examList.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-space-md py-10 text-center text-on-surface-variant">
                    No examinations yet.{" "}
                    <Link to="/exams" className="text-secondary hover:underline">
                      Create your first examination
                    </Link>
                    .
                  </td>
                </tr>
              ) : (
                examList.map((exam) => {
                  const stats = statsById.get(exam.id);
                  const progress = examProgress(stats);
                  const status = examStatusBadge(stats);
                  const action = actionFor(stats);
                  return (
                    <tr key={exam.id} className="transition-colors hover:bg-surface-container-low/40">
                      <td className="px-space-md py-3 font-medium text-on-surface">
                        <Link to={`/exams/${exam.id}`} className="hover:text-secondary hover:underline">
                          {exam.title}
                        </Link>
                      </td>
                      <td className="px-space-md py-3 font-mono text-on-surface-variant">
                        {exam.subject_code ?? exam.subject}
                      </td>
                      <td className="whitespace-nowrap px-space-md py-3 text-on-surface-variant">
                        {formatDate(exam.exam_date)}
                      </td>
                      <td className="px-space-md py-3 text-right font-mono tnum text-on-surface">
                        {stats ? stats.submission_count : "—"}
                      </td>
                      <td className="px-space-md py-3">
                        <div className="flex w-full flex-col gap-1">
                          <div className="flex justify-between font-mono text-label-sm text-on-surface-variant">
                            <span>{progress.pct}%</span>
                            <span>
                              {progress.done} / {progress.total}
                            </span>
                          </div>
                          <ProgressBar value={progress.pct} tone={status.tone} />
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-space-md py-3">
                        <StatusBadge tone={status.tone} label={status.label} dot />
                      </td>
                      <td className="whitespace-nowrap px-space-md py-3 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            if (action.to === "results") navigate(`/results/${exam.id}`);
                            else if (action.to === "evaluation") navigate(`/evaluation?exam=${exam.id}`);
                            else navigate(`/exams/${exam.id}`);
                          }}
                          className="btn-secondary px-space-sm py-1  text-label-md"
                        >
                          {action.label}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Needs attention */}
      <div className="flex flex-col gap-space-sm rounded border border-outline-variant bg-surface-container-lowest p-space-md">
        <div className="flex items-center justify-between border-b border-outline-variant pb-space-xs">
          <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
            Needs Attention ({needsAttention.length} {needsAttention.length === 1 ? "sheet" : "sheets"})
          </h2>
          <span className=" text-label-sm text-on-surface-variant">
            Manual verification required
          </span>
        </div>
        {loadingSubs ? (
          <Skeleton className="h-16 w-full" />
        ) : needsAttention.length === 0 ? (
          <p className="py-3  text-body-sm text-on-surface-variant">
            Nothing needs attention — every flagged sheet has been resolved.
          </p>
        ) : (
          <div className="divide-y divide-outline-variant  text-body-sm">
            {needsAttention.map((submission) => (
              <div key={submission.id} className="flex items-center justify-between gap-space-sm py-2">
                <div className="flex min-w-0 items-center gap-space-sm text-on-surface">
                  <StatusBadge
                    tone={submission.status === "failed" ? "critical" : "review"}
                    label={
                      submission.status === "failed"
                        ? "Processing failed"
                        : pluralize(submission.flagged_count, "flagged answer")
                    }
                    dot
                  />
                  <span className="truncate font-mono text-label-sm text-outline">
                    {submission.student_roll ?? "no roll"} · {submission.original_filename ?? "script"}
                  </span>
                </div>
                <Link
                  to={`/submissions/${submission.id}`}
                  className="shrink-0  text-label-sm font-medium text-primary hover:underline"
                >
                  Inspect
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent submissions strip */}
      <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
        <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
          <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
            Recent Answer Sheets
          </h2>
          <Link to="/answer-sheets" className=" text-label-sm text-secondary hover:underline">
            View all
          </Link>
        </div>
        <SubmissionMiniTable query={submissionsQuery} />
      </div>
    </PageContainer>
  );
}

function Metric({ label, value }: { label: string; value: number | string | null }) {
  return (
    <div className="flex flex-col p-space-md">
      <span className=" text-label-sm uppercase tracking-wider text-outline">{label}</span>
      {value === null ? (
        <Skeleton className="mt-1 h-7 w-14" />
      ) : (
        <span className="mt-1 font-mono text-headline-lg font-semibold tnum text-primary">{value}</span>
      )}
    </div>
  );
}

function SubmissionMiniTable({ query }: { query: { data?: Page<Submission>; isLoading: boolean } }) {
  const items = (query.data?.items ?? []).slice(0, 6);
  if (query.isLoading) return <Skeleton className="m-space-md h-24" />;
  if (items.length === 0)
    return (
      <p className="px-space-md py-6 text-center  text-body-sm text-on-surface-variant">
        No answer sheets uploaded yet.
      </p>
    );
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-outline-variant  text-label-sm uppercase tracking-wider text-on-surface-variant">
            <th className="px-space-md py-2 font-medium">Candidate</th>
            <th className="px-space-md py-2 font-medium">Roll</th>
            <th className="px-space-md py-2 font-medium">Status</th>
            <th className="px-space-md py-2 text-right font-medium">Score</th>
            <th className="px-space-md py-2 text-right font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-outline-variant  text-body-sm">
          {items.map((s) => (
            <tr key={s.id} className="transition-colors hover:bg-surface-container-low/40">
              <td className="px-space-md py-2 font-medium text-on-surface">
                {s.student_name ?? "Unnamed candidate"}
              </td>
              <td className="px-space-md py-2 font-mono text-on-surface-variant">{s.student_roll ?? "—"}</td>
              <td className="px-space-md py-2">
                <StatusBadge tone={submissionTone(s.status)} label={submissionLabel(s.status)} dot />
              </td>
              <td className="px-space-md py-2 text-right font-mono tnum text-on-surface">
                {s.final_total_marks.toFixed(1)} / {s.max_total_marks.toFixed(0)}
              </td>
              <td className="px-space-md py-2 text-right">
                <Link
                  to={s.status === "ready_for_review" || s.status === "reviewed" ? `/submissions/${s.id}/evaluate` : `/submissions/${s.id}`}
                  className=" text-label-sm font-medium text-primary hover:underline"
                >
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

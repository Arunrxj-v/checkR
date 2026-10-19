import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { examApi, resultApi } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import { submissionLabel, submissionTone } from "@/lib/status";
import type { ExamResultOverview } from "@/lib/types";

import { errorText } from "./ExamsPage";

function downloadCsv(filename: string, rows: ExamResultOverview["rows"]) {
  const header = ["Rank", "Candidate", "Roll", "Status", "AI Total", "Final Total", "Max", "Percentage", "Flagged"];
  const sorted = [...rows].sort((a, b) => (b.percentage ?? -1) - (a.percentage ?? -1));
  const lines = sorted.map((row, index) =>
    [
      index + 1,
      row.student_name ?? "",
      row.student_roll ?? "",
      row.status,
      row.ai_total_marks.toFixed(2),
      row.final_total_marks.toFixed(2),
      row.max_total_marks.toFixed(2),
      row.percentage === null ? "" : row.percentage.toFixed(2),
      row.flagged_count,
    ]
      .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
      .join(","),
  );
  const csv = [header.join(","), ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function ExamResultsPage() {
  const { examId = "" } = useParams();
  const { notify } = useToast();

  const examQuery = useQuery({ queryKey: ["exam", examId], queryFn: () => examApi.get(examId), enabled: Boolean(examId) });

  const resultsQuery = useQuery({
    queryKey: ["exam-results", examId],
    queryFn: () => resultApi.forExam(examId),
    enabled: Boolean(examId),
  });

  useCrumbs(
    [
      { label: "Results", to: "/results" },
      { label: examQuery.data?.title ?? "Examination" },
    ],
    [examQuery.data?.title],
  );

  const overview = resultsQuery.data;
  const exam = examQuery.data;
  const ranked = overview ? [...overview.rows].sort((a, b) => (b.percentage ?? -1) - (a.percentage ?? -1)) : [];

  return (
    <PageContainer>
      <PageHeader
        title={exam ? `Results · ${exam.title}` : "Results"}
        description="Aggregated candidate performance for this examination."
        actions={
          <button
            type="button"
            className="btn-secondary h-8 px-space-md  text-label-md"
            disabled={!overview || ranked.length === 0}
            onClick={() => {
              if (!overview || !exam) return;
              downloadCsv(`${exam.subject_code ?? "exam"}-results.csv`, overview.rows);
              notify("Results exported", { tone: "verified", detail: "CSV downloaded." });
            }}
          >
            <Icon name="download" className="text-[16px]" /> Export CSV
          </button>
        }
      />

      {resultsQuery.isLoading ? (
        <>
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-64 w-full" />
        </>
      ) : resultsQuery.isError || !overview ? (
        <EmptyState icon="error" title="Results unavailable" description={errorText(resultsQuery.error)} />
      ) : (
        <>
          <div className="grid grid-cols-2 divide-y divide-outline-variant rounded border border-outline-variant bg-surface-container-lowest lg:grid-cols-4 lg:divide-x lg:divide-y-0">
            <Metric label="Scripts" value={String(overview.submission_count)} />
            <Metric label="Completed" value={String(overview.completed_count)} />
            <Metric label="Average" value={overview.average_percentage === null ? "—" : formatPercent(overview.average_percentage)} />
            <Metric
              label="Range"
              value={
                overview.highest_percentage === null
                  ? "—"
                  : `${formatPercent(overview.lowest_percentage ?? 0, 0)} – ${formatPercent(overview.highest_percentage, 0)}`
              }
            />
          </div>

          {ranked.length === 0 ? (
            <EmptyState
              icon="bar_chart"
              title="No results yet"
              description="Once candidate scripts are reviewed and finalised they will appear here."
            />
          ) : (
            <div className="overflow-hidden rounded border border-outline-variant bg-surface-container-lowest">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                      <th className="w-14 px-space-md py-2.5 font-medium">Rank</th>
                      <th className="px-space-md py-2.5 font-medium">Candidate</th>
                      <th className="px-space-md py-2.5 font-medium">Roll</th>
                      <th className="px-space-md py-2.5 font-medium">Status</th>
                      <th className="px-space-md py-2.5 text-right font-medium">AI</th>
                      <th className="px-space-md py-2.5 text-right font-medium">Final</th>
                      <th className="px-space-md py-2.5 text-right font-medium">%</th>
                      <th className="px-space-md py-2.5 text-right font-medium">Flagged</th>
                      <th className="px-space-md py-2.5 text-right font-medium" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant  text-body-sm">
                    {ranked.map((row, index) => (
                      <tr key={row.submission_id} className="transition-colors hover:bg-surface-container-low/40">
                        <td className="px-space-md py-2.5 font-mono tnum text-outline">{index + 1}</td>
                        <td className="px-space-md py-2.5 font-medium text-on-surface">{row.student_name ?? "Unnamed candidate"}</td>
                        <td className="px-space-md py-2.5 font-mono text-on-surface-variant">{row.student_roll ?? "—"}</td>
                        <td className="px-space-md py-2.5">
                          <StatusBadge tone={submissionTone(row.status)} label={submissionLabel(row.status)} dot />
                        </td>
                        <td className="px-space-md py-2.5 text-right font-mono tnum text-on-surface-variant">
                          {row.ai_total_marks.toFixed(1)}
                        </td>
                        <td className="px-space-md py-2.5 text-right font-mono tnum font-medium text-on-surface">
                          {row.final_total_marks.toFixed(1)}
                          <span className="text-outline"> / {row.max_total_marks.toFixed(0)}</span>
                        </td>
                        <td className="px-space-md py-2.5 text-right font-mono tnum text-secondary">
                          {formatPercent(row.percentage)}
                        </td>
                        <td className={`px-space-md py-2.5 text-right font-mono tnum ${row.flagged_count ? "text-review-fg" : "text-outline"}`}>
                          {row.flagged_count || "—"}
                        </td>
                        <td className="px-space-md py-2.5 text-right">
                          <Link to={`/submissions/${row.submission_id}`} className=" text-label-sm font-medium text-primary hover:underline">
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </PageContainer>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col p-space-md">
      <span className=" text-label-sm uppercase tracking-wider text-outline">{label}</span>
      <span className="mt-1 font-mono text-headline-lg font-semibold tnum text-primary">{value}</span>
    </div>
  );
}

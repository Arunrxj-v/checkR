import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { examApi, submissionApi } from "@/lib/api";
import { pluralize, titleCase } from "@/lib/format";
import { submissionLabel, submissionTone } from "@/lib/status";
import type { SubmissionStatus } from "@/lib/types";

type QueueFilter = "ready_for_review" | "reviewed" | "all";

const FILTER_LABELS: Record<QueueFilter, string> = {
  ready_for_review: "Awaiting review",
  reviewed: "Reviewed · not finalised",
  all: "All active scripts",
};

export function EvaluationQueuePage() {
  useCrumbs([{ label: "Evaluation" }]);
  const [searchParams, setSearchParams] = useSearchParams();
  const examFilter = searchParams.get("exam") ?? "";
  const [filter, setFilter] = useState<QueueFilter>("ready_for_review");

  const examsQuery = useQuery({ queryKey: ["exams", "picker"], queryFn: () => examApi.list({ limit: 100 }) });

  const submissionsQuery = useQuery({
    queryKey: ["submissions", "queue", { exam: examFilter, filter }],
    queryFn: () =>
      submissionApi.list({
        exam_id: examFilter || undefined,
        status: filter === "all" ? undefined : (filter as SubmissionStatus),
        limit: 100,
      }),
  });

  const items = submissionsQuery.data?.items ?? [];
  const activeItems = filter === "all" ? items.filter((s) => s.status !== "completed") : items;

  return (
    <PageContainer>
      <PageHeader
        title="Evaluation Queue"
        description="Scripts processed by the AI and waiting for an examiner's decision."
        actions={
          <select className="field w-64" value={examFilter} onChange={(e) => setSearchParams(e.target.value ? { exam: e.target.value } : {})}>
            <option value="">All examinations</option>
            {(examsQuery.data?.items ?? []).map((exam) => (
              <option key={exam.id} value={exam.id}>
                {exam.title}
              </option>
            ))}
          </select>
        }
      />

      <div className="flex items-center gap-space-md border-b border-outline-variant  text-label-md">
        {(Object.keys(FILTER_LABELS) as QueueFilter[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={
              filter === key
                ? "border-b-2 border-primary pb-1 font-semibold text-primary"
                : "pb-1 text-on-surface-variant transition-colors hover:text-on-surface"
            }
          >
            {FILTER_LABELS[key]}
          </button>
        ))}
      </div>

      {submissionsQuery.isLoading ? (
        <div className="flex flex-col gap-space-sm">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : activeItems.length === 0 ? (
        <EmptyState
          icon="task_alt"
          title={filter === "ready_for_review" ? "The queue is clear" : "Nothing here yet"}
          description={
            filter === "ready_for_review"
              ? "No scripts are waiting for review. Newly processed sheets appear here automatically."
              : "Upload and process answer sheets, then return here to review them."
          }
          action={
            <Link to="/answer-sheets" className="btn-secondary px-space-md py-1.5  text-label-md">
              Go to answer sheets
            </Link>
          }
        />
      ) : (
        <div className="overflow-hidden rounded border border-outline-variant bg-surface-container-lowest">
          <ul className="divide-y divide-outline-variant">
            {activeItems.map((s) => {
              const reviewed = s.status === "reviewed" || s.status === "completed";
              return (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-space-md p-space-md transition-colors hover:bg-surface-container-low/40">
                  <div className="flex min-w-0 items-center gap-space-md">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-outline-variant bg-surface-container-low font-mono text-label-sm font-semibold text-primary">
                      {pluralize(s.flagged_count, "flag")}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate  text-body-md font-medium text-on-surface">
                        {s.student_name ?? "Unnamed candidate"}
                        <span className="ml-2 font-mono text-label-sm text-outline">{s.student_roll ?? "no roll"}</span>
                      </div>
                      <div className="flex items-center gap-space-sm  text-label-sm text-on-surface-variant">
                        <StatusBadge tone={submissionTone(s.status)} label={submissionLabel(s.status)} dot />
                        <span>·</span>
                        <span>
                          {s.flagged_count > 0
                            ? `${s.flagged_count} answer${s.flagged_count === 1 ? "" : "s"} flagged for manual review`
                            : "No flags — quick verification"}
                        </span>
                        {s.ai_confidence !== null ? (
                          <>
                            <span>·</span>
                            <span className="font-mono">OCR {Math.round((s.ai_confidence ?? 0) * 100)}%</span>
                          </>
                        ) : null}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-space-md">
                    <div className="text-right">
                      <div className="font-mono tnum text-headline-sm text-primary">
                        {s.final_total_marks.toFixed(1)}
                        <span className="text-label-sm text-outline"> / {s.max_total_marks.toFixed(0)}</span>
                      </div>
                      <div className=" text-label-sm text-outline">{reviewed ? "Reviewed total" : "Provisional total"}</div>
                    </div>
                    <Link to={`/submissions/${s.id}/evaluate`} className="btn-primary px-space-md py-1.5  text-label-md">
                      <Icon name="edit_note" className="text-[16px]" />
                      {reviewed ? "Reopen" : "Start review"}
                    </Link>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <p className=" text-body-sm text-on-surface-variant">
        <Icon name="info" className="mr-1 text-[14px] align-[-2px]" />
        {titleCase(filter)} · {activeItems.length} script{activeItems.length === 1 ? "" : "s"}. Every mark is
        provisional until a teacher accepts or overrides it.
      </p>
    </PageContainer>
  );
}

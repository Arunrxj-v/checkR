import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { UploadModal } from "@/components/submissions/UploadModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { examApi, submissionApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { isProcessing, submissionLabel, submissionTone } from "@/lib/status";
import type { SubmissionStatus } from "@/lib/types";

const STATUS_OPTIONS: Array<{ value: "" | SubmissionStatus; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "uploaded", label: "Queued" },
  { value: "processing", label: "Processing" },
  { value: "ready_for_review", label: "In review" },
  { value: "reviewed", label: "Reviewed" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

export function AnswerSheetsPage() {
  useCrumbs([{ label: "Answer Sheets" }]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | SubmissionStatus>("");
  const [examId, setExamId] = useState("");
  const [uploadExam, setUploadExam] = useState("");

  const examsQuery = useQuery({ queryKey: ["exams", "picker"], queryFn: () => examApi.list({ limit: 100 }) });

  const submissionsQuery = useQuery({
    queryKey: ["submissions", { search, status, examId }],
    queryFn: () =>
      submissionApi.list({
        search: search || undefined,
        status: status || undefined,
        exam_id: examId || undefined,
        limit: 100,
      }),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((s) => isProcessing(s.status)) ? 5_000 : false;
    },
  });

  const examsById = useMemo(() => {
    const map = new Map<string, string>();
    (examsQuery.data?.items ?? []).forEach((e) => map.set(e.id, e.title));
    return map;
  }, [examsQuery.data]);

  const items = submissionsQuery.data?.items ?? [];
  const hasProcessing = items.some((s) => isProcessing(s.status));

  const openUpload = () => {
    const target = examId || examsQuery.data?.items[0]?.id || "";
    if (!target) {
      notify("Create an examination first", { tone: "review", detail: "Scripts are always uploaded against an examination." });
      navigate("/exams");
      return;
    }
    setUploadExam(target);
  };

  return (
    <PageContainer>
      <PageHeader
        title="Answer Sheets"
        description="Every candidate script, its processing state and review progress."
        actions={
          <button type="button" className="btn-primary h-8 px-space-md  text-label-md" onClick={openUpload}>
            <Icon name="upload_file" className="text-[16px]" /> Upload scripts
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-space-sm">
        <div className="relative min-w-[220px] flex-1">
          <Icon name="search" className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[18px] text-outline" />
          <input className="field pl-8" placeholder="Search candidate or roll number…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="field w-56" value={examId} onChange={(e) => setExamId(e.target.value)}>
          <option value="">All examinations</option>
          {(examsQuery.data?.items ?? []).map((exam) => (
            <option key={exam.id} value={exam.id}>
              {exam.title}
            </option>
          ))}
        </select>
        <select className="field w-40" value={status} onChange={(e) => setStatus(e.target.value as SubmissionStatus | "")}>
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {hasProcessing ? (
          <span className="flex items-center gap-space-xs rounded border border-secondary-fixed-dim bg-secondary-fixed px-space-sm py-1  text-label-sm text-on-secondary-fixed-variant">
            <Icon name="autorenew" className="animate-spin text-[14px]" /> Live processing
          </span>
        ) : null}
      </div>

      <div className="overflow-hidden rounded border border-outline-variant bg-surface-container-lowest">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                <th className="px-space-md py-2.5 font-medium">Candidate</th>
                <th className="px-space-md py-2.5 font-medium">Examination</th>
                <th className="px-space-md py-2.5 text-right font-medium">Pages</th>
                <th className="w-44 px-space-md py-2.5 font-medium">Processing</th>
                <th className="px-space-md py-2.5 font-medium">Status</th>
                <th className="px-space-md py-2.5 font-medium">Uploaded</th>
                <th className="px-space-md py-2.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant  text-body-sm">
              {submissionsQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-space-md py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-space-md py-10">
                    <EmptyState
                      icon="description"
                      title="No answer sheets"
                      description="Upload candidate scripts against an examination to start processing."
                      action={
                        <button type="button" className="btn-primary px-space-md py-1.5  text-label-md" onClick={openUpload}>
                          Upload scripts
                        </button>
                      }
                    />
                  </td>
                </tr>
              ) : (
                items.map((s) => {
                  const canReview = s.status === "ready_for_review" || s.status === "reviewed";
                  return (
                    <tr key={s.id} className="transition-colors hover:bg-surface-container-low/40">
                      <td className="px-space-md py-3">
                        <Link to={`/submissions/${s.id}`} className="font-medium text-on-surface hover:text-secondary hover:underline">
                          {s.student_name ?? "Unnamed candidate"}
                        </Link>
                        <div className="font-mono text-label-sm text-outline">{s.student_roll ?? "no roll"}</div>
                      </td>
                      <td className="px-space-md py-3 text-on-surface-variant">{examsById.get(s.exam_id) ?? "—"}</td>
                      <td className="px-space-md py-3 text-right font-mono tnum text-on-surface">
                        {s.processed_page_count}/{s.page_count}
                      </td>
                      <td className="px-space-md py-3">
                        {isProcessing(s.status) ? (
                          <ProgressBar value={s.page_count ? (s.processed_page_count / s.page_count) * 100 : 0} tone="info" />
                        ) : (
                          <div className="flex items-center gap-space-sm">
                            <ProgressBar value={s.max_total_marks ? (s.final_total_marks / s.max_total_marks) * 100 : 0} tone={s.flagged_count ? "review" : "verified"} />
                            <span className="shrink-0 font-mono tnum text-label-sm text-on-surface-variant">
                              {s.final_total_marks.toFixed(1)}/{s.max_total_marks.toFixed(0)}
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-space-md py-3">
                        <StatusBadge tone={submissionTone(s.status)} label={submissionLabel(s.status)} dot />
                      </td>
                      <td className="whitespace-nowrap px-space-md py-3 text-on-surface-variant">{formatDateTime(s.created_at)}</td>
                      <td className="whitespace-nowrap px-space-md py-3 text-right">
                        <Link to={canReview ? `/submissions/${s.id}/evaluate` : `/submissions/${s.id}`} className="btn-secondary px-space-sm py-1  text-label-md">
                          {canReview ? "Evaluate" : "Open"}
                        </Link>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <UploadModal
        open={Boolean(uploadExam)}
        onClose={() => setUploadExam("")}
        examId={uploadExam}
        examTitle={examsById.get(uploadExam)}
        onUploaded={(created) => {
          void queryClient.invalidateQueries({ queryKey: ["submissions"] });
          notify(`Queued ${created.length} script${created.length === 1 ? "" : "s"} for processing`, { tone: "verified" });
          if (created.length === 1) navigate(`/submissions/${created[0].id}`);
        }}
      />
    </PageContainer>
  );
}

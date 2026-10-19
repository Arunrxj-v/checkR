import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer } from "@/components/layout/PageHeader";
import { AuthImage } from "@/components/ui/AuthImage";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar, ScoreSpan } from "@/components/ui/ProgressBar";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { answerApi, examApi, resultApi, submissionApi } from "@/lib/api";
import { formatConfidence, formatDateTime, formatPercent } from "@/lib/format";
import { answerLabel, answerTone, confidenceTone, pageLabel, pageTone, submissionLabel, submissionTone, isAwaitingReview, isProcessing } from "@/lib/status";
import type { Answer } from "@/lib/types";

import { errorText } from "./ExamsPage";

export function SubmissionDetailPage() {
  const { submissionId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const submissionQuery = useQuery({
    queryKey: ["submission", submissionId],
    queryFn: () => submissionApi.get(submissionId),
    enabled: Boolean(submissionId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isProcessing(status) ? 3_000 : false;
    },
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
    enabled: Boolean(submissionId) && Boolean(submission) && isAwaitingReview(submission!.status),
  });

  const resultQuery = useQuery({
    queryKey: ["result", submissionId],
    queryFn: () => resultApi.forSubmission(submissionId),
    enabled: Boolean(submissionId) && Boolean(submission) && isAwaitingReview(submission!.status),
  });

  useCrumbs(
    [
      { label: "Answer Sheets", to: "/answer-sheets" },
      { label: submission?.student_name ?? "Submission" },
    ],
    [submission?.student_name],
  );

  const processMutation = useMutation({
    mutationFn: () => submissionApi.process(submissionId, true),
    onSuccess: () => {
      notify("Re-evaluation queued", { tone: "verified", detail: "The worker will refresh every answer." });
      void queryClient.invalidateQueries({ queryKey: ["submission", submissionId] });
    },
    onError: (err) => notify("Could not queue re-evaluation", { tone: "critical", detail: errorText(err) }),
  });

  const finalizeMutation = useMutation({
    mutationFn: () => resultApi.finalize(submissionId),
    onSuccess: (result) => {
      notify("Result finalised", { tone: "verified", detail: `${result.final_total_marks.toFixed(1)} / ${result.max_total_marks.toFixed(0)} recorded.` });
      void queryClient.invalidateQueries({ queryKey: ["submission", submissionId] });
      void queryClient.invalidateQueries({ queryKey: ["result", submissionId] });
    },
    onError: (err) => notify("Cannot finalise yet", { tone: "review", detail: errorText(err) }),
  });

  const reopenMutation = useMutation({
    mutationFn: () => resultApi.reopen(submissionId),
    onSuccess: () => {
      notify("Result reopened", { tone: "neutral", detail: "You can now adjust individual answers." });
      void queryClient.invalidateQueries({ queryKey: ["submission", submissionId] });
      void queryClient.invalidateQueries({ queryKey: ["result", submissionId] });
    },
    onError: (err) => notify("Could not reopen", { tone: "critical", detail: errorText(err) }),
  });

  if (submissionQuery.isLoading) {
    return (
      <PageContainer>
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-64 w-full" />
      </PageContainer>
    );
  }

  if (submissionQuery.isError || !submission) {
    return (
      <PageContainer>
        <EmptyState icon="error" title="Submission unavailable" description={errorText(submissionQuery.error)} />
      </PageContainer>
    );
  }

  const answers = answersQuery.data ?? [];
  const result = resultQuery.data;
  const processing = isProcessing(submission.status);
  const canReview = isAwaitingReview(submission.status);

  const reviewedCount = answers.filter((a) => a.is_reviewed).length;

  return (
    <PageContainer>
      {/* Header */}
      <div className="flex flex-col gap-space-md border-b border-outline-variant pb-space-md lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-space-sm">
            <h1 className="font-display text-headline-lg font-semibold tracking-tight text-primary">
              {submission.student_name ?? "Unnamed candidate"}
            </h1>
            <span className="rounded border border-outline-variant bg-surface-container-low px-1.5 py-0.5 font-mono text-label-sm font-medium text-on-surface-variant">
              {submission.student_roll ?? "no roll"}
            </span>
            <StatusBadge tone={submissionTone(submission.status)} label={submissionLabel(submission.status)} />
            {submission.flagged_count > 0 ? (
              <StatusBadge tone="review" label={`${submission.flagged_count} flagged`} />
            ) : null}
          </div>
          <p className="mt-0.5  text-body-md text-on-surface-variant">
            {examQuery.data ? (
              <Link to={`/exams/${submission.exam_id}`} className="hover:text-secondary hover:underline">
                {examQuery.data.title}
              </Link>
            ) : (
              "Examination"
            )}
            {" · "}
            <span className="font-mono">{submission.original_filename ?? "script"}</span>
            {" · "}
            {formatDateTime(submission.created_at)}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-space-sm">
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => processMutation.mutate()} disabled={processMutation.isPending || processing}>
            {processMutation.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="refresh" className="text-[16px]" />}
            Re-evaluate
          </button>
          {canReview ? (
            <>
              {submission.status === "completed" ? (
                <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => reopenMutation.mutate()} disabled={reopenMutation.isPending}>
                  <Icon name="lock_open" className="text-[16px]" /> Reopen
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-secondary px-space-md py-1.5  text-label-md"
                  onClick={() => finalizeMutation.mutate()}
                  disabled={finalizeMutation.isPending || reviewedCount < answers.length}
                >
                  {finalizeMutation.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="task_alt" className="text-[16px]" />}
                  Finalise ({reviewedCount}/{answers.length})
                </button>
              )}
              <button type="button" className="btn-primary px-space-md py-1.5  text-label-md" onClick={() => navigate(`/submissions/${submission.id}/evaluate`)}>
                <Icon name="edit_note" className="text-[16px]" /> Open workspace
              </button>
            </>
          ) : null}
        </div>
      </div>

      {processing ? (
        <ProcessingPanel
          status={submission.status}
          processed={submission.processed_page_count}
          total={submission.page_count}
          error={submission.error_message}
        />
      ) : null}

      {submission.status === "failed" ? (
        <div className="flex items-start gap-space-sm rounded border border-critical-border bg-critical-bg px-space-md py-2  text-body-sm text-critical-fg">
          <Icon name="report" className="text-[18px]" />
          <div>
            <p className="font-medium">Processing failed.</p>
            <p>{submission.error_message ?? "An unexpected error occurred while processing this script."}</p>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-space-lg xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-space-lg">
          {/* Answers */}
          <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
            <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
              <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
                Detected Answers
              </h2>
              <span className=" text-label-sm text-outline">
                {answers.length > 0 ? `${reviewedCount}/${answers.length} reviewed` : "Awaiting processing"}
              </span>
            </div>
            {!canReview ? (
              <p className="px-space-md py-6 text-center  text-body-sm text-on-surface-variant">
                Answers will appear once handwriting transcription and matching complete.
              </p>
            ) : answers.length === 0 ? (
              <p className="px-space-md py-6 text-center  text-body-sm text-on-surface-variant">
                No answers were detected in this script.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                      <th className="px-space-md py-2 font-medium">Question</th>
                      <th className="px-space-md py-2 font-medium">Status</th>
                      <th className="px-space-md py-2 text-right font-medium">AI</th>
                      <th className="px-space-md py-2 text-right font-medium">Teacher</th>
                      <th className="px-space-md py-2 text-right font-medium">Final</th>
                      <th className="px-space-md py-2 font-medium">Confidence</th>
                      <th className="px-space-md py-2 text-right font-medium" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant  text-body-sm">
                    {answers
                      .slice()
                      .sort((a, b) => a.order_index - b.order_index)
                      .map((answer, index) => (
                        <tr key={answer.id} className="transition-colors hover:bg-surface-container-low/40">
                          <td className="px-space-md py-2.5 font-medium text-on-surface">Q{index + 1}</td>
                          <td className="px-space-md py-2.5">
                            <StatusBadge tone={answerTone(answer.status, answer.is_flagged)} label={answerLabel(answer.status)} dot />
                          </td>
                          <AnswerMarks answer={answer} />
                          <td className="px-space-md py-2.5">
                            <span className={`font-mono text-label-sm ${confidenceTone(answer.ai_confidence_level, answer.ai_confidence) === "critical" ? "text-critical-fg" : "text-on-surface-variant"}`}>
                              {formatConfidence(answer.ai_confidence)}
                            </span>
                          </td>
                          <td className="px-space-md py-2.5 text-right">
                            <button
                              type="button"
                              onClick={() => navigate(`/submissions/${submission.id}/evaluate?answer=${answer.id}`)}
                              className=" text-label-sm font-medium text-primary hover:underline"
                            >
                              Review
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Pages */}
          <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
            <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
              <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
                Manuscript Pages
              </h2>
              <span className=" text-label-sm text-outline">
                {submission.processed_page_count}/{submission.page_count} processed
              </span>
            </div>
            {submission.pages.length === 0 ? (
              <p className="px-space-md py-6 text-center  text-body-sm text-on-surface-variant">
                No pages extracted yet.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-space-md p-space-md sm:grid-cols-3 lg:grid-cols-4">
                {submission.pages.map((page) => (
                  <figure key={page.id} className="flex flex-col gap-space-xs">
                    <div className="relative aspect-[3/4] overflow-hidden rounded border border-outline-variant bg-surface-container-low">
                      {page.status === "uploaded" ? (
                        <div className="flex h-full items-center justify-center text-outline">
                          <Icon name="hourglass_empty" className="text-[24px]" />
                        </div>
                      ) : (
                        <AuthImage
                          path={submissionApi.pageImageUrl(page.id, "thumbnail").replace("/api", "")}
                          alt={`Page ${page.page_number}`}
                          className="h-full w-full object-cover"
                        />
                      )}
                      <span className="absolute left-1 top-1 rounded bg-inverse-surface/80 px-1 py-0.5 font-mono text-[10px] text-inverse-on-surface">
                        p{page.page_number}
                      </span>
                    </div>
                    <figcaption className="flex items-center justify-between">
                      <StatusBadge tone={pageTone(page.status)} label={pageLabel(page.status)} />
                      {page.ocr_confidence !== null ? (
                        <span className="font-mono text-label-sm text-outline">{formatConfidence(page.ocr_confidence)}</span>
                      ) : null}
                    </figcaption>
                    {page.error_message ? (
                      <p className=" text-label-sm text-critical-fg">{page.error_message}</p>
                    ) : null}
                  </figure>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Result summary */}
        <div className="flex h-fit flex-col rounded border border-outline-variant bg-surface-container-lowest">
          <div className="border-b border-outline-variant px-space-md py-space-sm">
            <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
              Result Summary
            </h2>
          </div>
          {resultQuery.isLoading || !canReview ? (
            <div className="flex flex-col gap-space-sm p-space-md">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : result ? (
            <div className="flex flex-col gap-space-md p-space-md">
              <div className="flex items-end justify-between">
                <div>
                  <div className=" text-label-sm uppercase tracking-wider text-outline">Final Total</div>
                  <div className="font-mono text-headline-xl font-semibold tnum text-primary">
                    {result.final_total_marks.toFixed(1)}
                    <span className="text-headline-sm text-outline"> / {result.max_total_marks.toFixed(0)}</span>
                  </div>
                </div>
                <span className="font-mono text-headline-sm text-secondary">{formatPercent(result.percentage)}</span>
              </div>
              <ProgressBar value={result.percentage ?? 0} tone={result.flagged_count ? "review" : "verified"} height="h-1.5" />
              <dl className="grid grid-cols-2 gap-space-sm border-t border-outline-variant pt-space-sm  text-body-sm">
                <Stat label="AI total" value={`${result.ai_total_marks.toFixed(1)}`} />
                <Stat label="Reviewed" value={`${result.reviewed_count}/${result.total_answers}`} />
                <Stat label="Flagged" value={`${result.flagged_count}`} tone={result.flagged_count ? "review" : undefined} />
                <Stat label="Status" value={submissionLabel(submission.status)} />
              </dl>

              {result.reviewed_count < result.total_answers ? (
                <p className="rounded border border-review-border bg-review-bg px-space-sm py-1.5  text-body-sm text-review-fg">
                  <Icon name="warning" className="mr-1 text-[14px] align-[-2px]" />
                  {result.total_answers - result.reviewed_count} answer(s) still need a teacher decision before
                  finalising.
                </p>
              ) : null}

              {submission.status === "completed" ? (
                <div className="rounded border border-verified-border bg-verified-bg px-space-sm py-2  text-body-sm text-verified-fg">
                  <Icon name="verified" className="mr-1 text-[14px] align-[-2px]" />
                  Result finalised on {formatDateTime(submission.updated_at)}.
                </div>
              ) : null}
            </div>
          ) : (
            <p className="p-space-md  text-body-sm text-on-surface-variant">
              Result will be available after processing.
            </p>
          )}
        </div>
      </div>
    </PageContainer>
  );
}

function AnswerMarks({ answer }: { answer: Answer }) {
  return (
    <>
      <td className="px-space-md py-2.5 text-right">
        <ScoreSpan value={answer.ai_score} max={answer.max_marks} className="text-on-surface-variant" />
      </td>
      <td className="px-space-md py-2.5 text-right">
        <ScoreSpan value={answer.teacher_score} max={answer.max_marks} className="text-on-surface-variant" />
      </td>
      <td className="px-space-md py-2.5 text-right">
        <ScoreSpan value={answer.final_score} max={answer.max_marks} className="font-medium text-primary" />
      </td>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "review" }) {
  return (
    <div>
      <dt className=" text-label-sm uppercase tracking-wide text-outline">{label}</dt>
      <dd className={`font-mono tnum ${tone === "review" ? "text-review-fg" : "text-on-surface"}`}>{value}</dd>
    </div>
  );
}

function ProcessingPanel({
  status,
  processed,
  total,
  error,
}: {
  status: string;
  processed: number;
  total: number;
  error: string | null;
}) {
  const stages: Array<{ key: string; label: string }> = [
    { key: "processing", label: "Extract & prepare pages" },
    { key: "ocr_processing", label: "Read handwriting (OCR)" },
    { key: "answers_detected", label: "Match answers to questions" },
    { key: "ai_evaluating", label: "Score against marking scheme" },
  ];
  const order = ["uploaded", "processing", "ocr_processing", "answers_detected", "ai_evaluating", "ready_for_review"];
  const currentIndex = order.indexOf(status);

  return (
    <div className="flex flex-col gap-space-md rounded border border-outline-variant bg-surface-container-lowest p-space-md">
      <div className="flex items-center gap-space-sm">
        <Spinner />
        <span className=" text-body-md text-on-surface">
          Processing script… {total > 0 ? `(${processed}/${total} pages)` : ""}
        </span>
      </div>
      <ProgressBar value={total > 0 ? (processed / total) * 100 : 12} tone="info" height="h-1.5" />
      <ol className="grid grid-cols-2 gap-space-sm lg:grid-cols-4">
        {stages.map((stage) => {
          const index = order.indexOf(stage.key);
          const done = currentIndex > index;
          const active = currentIndex === index;
          return (
            <li key={stage.key} className="flex items-center gap-space-sm rounded border border-outline-variant px-space-sm py-1.5">
              <span className={`flex h-5 w-5 items-center justify-center rounded-full border text-[12px] ${done ? "border-verified bg-verified-bg text-verified-fg" : active ? "border-secondary text-secondary" : "border-outline-variant text-outline"}`}>
                {done ? <Icon name="check" className="text-[14px]" /> : index + 1}
              </span>
              <span className={` text-label-sm ${active ? "text-primary" : "text-on-surface-variant"}`}>{stage.label}</span>
            </li>
          );
        })}
      </ol>
      {error ? <p className=" text-body-sm text-critical-fg">{error}</p> : null}
    </div>
  );
}

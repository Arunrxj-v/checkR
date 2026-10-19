import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer } from "@/components/layout/PageHeader";
import { QuestionFormModal, type QuestionFormValues } from "@/components/exams/QuestionForm";
import { UploadModal } from "@/components/submissions/UploadModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { examApi, submissionApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { examLabel, examTone, isProcessing, submissionLabel, submissionTone } from "@/lib/status";
import type { Exam, ExamStatus, Question, Submission } from "@/lib/types";

import { errorText } from "./ExamsPage";

export function ExamDetailPage() {
  const { examId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const [editing, setEditing] = useState<Question | null>(null);
  const [questionModalOpen, setQuestionModalOpen] = useState(false);
  const [editDetailsOpen, setEditDetailsOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Question | null>(null);

  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => examApi.get(examId),
    enabled: Boolean(examId),
  });

  const statsQuery = useQuery({
    queryKey: ["exam-stats", examId],
    queryFn: () => examApi.stats(examId),
    enabled: Boolean(examId),
    refetchInterval: 10_000,
  });

  const submissionsQuery = useQuery({
    queryKey: ["submissions", { examId }],
    queryFn: () => submissionApi.list({ exam_id: examId, limit: 100 }),
    enabled: Boolean(examId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((s: Submission) => isProcessing(s.status)) ? 4_000 : false;
    },
  });

  const exam = examQuery.data;

  useCrumbs([{ label: "Examinations", to: "/exams" }, { label: exam?.title ?? "Examination" }], [exam?.title]);

  const saveQuestion = useMutation({
    mutationFn: async (values: QuestionFormValues) => {
      if (editing) return examApi.updateQuestion(editing.id, values);
      return examApi.createQuestion(examId, { ...values, order_index: exam?.questions.length ?? 0 });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["exam", examId] });
      void queryClient.invalidateQueries({ queryKey: ["exam-stats", examId] });
      notify(editing ? "Question updated" : "Question added", { tone: "verified" });
      setQuestionModalOpen(false);
      setEditing(null);
    },
    onError: (err) => notify("Could not save question", { tone: "critical", detail: errorText(err) }),
  });

  const deleteQuestion = useMutation({
    mutationFn: (questionId: string) => examApi.removeQuestion(questionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["exam", examId] });
      void queryClient.invalidateQueries({ queryKey: ["exam-stats", examId] });
      notify("Question removed", { tone: "neutral" });
      setDeleteTarget(null);
    },
    onError: (err) => notify("Could not remove question", { tone: "critical", detail: errorText(err) }),
  });

  const updateExam = useMutation({
    mutationFn: (payload: Parameters<typeof examApi.update>[1]) => examApi.update(examId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["exam", examId] });
      void queryClient.invalidateQueries({ queryKey: ["exams"] });
      notify("Examination updated", { tone: "verified" });
      setEditDetailsOpen(false);
    },
    onError: (err) => notify("Could not update examination", { tone: "critical", detail: errorText(err) }),
  });

  const totalCriteriaMarks = useMemo(
    () => (exam?.questions ?? []).reduce((sum, q) => sum + q.criteria.reduce((s, c) => s + c.max_marks, 0), 0),
    [exam],
  );

  if (examQuery.isLoading) {
    return (
      <PageContainer>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-96 w-full" />
      </PageContainer>
    );
  }

  if (examQuery.isError || !exam) {
    return (
      <PageContainer>
        <EmptyState
          icon="error"
          title="Examination unavailable"
          description={errorText(examQuery.error)}
          action={
            <Link to="/exams" className="btn-secondary px-space-md py-1.5  text-label-md">
              Back to examinations
            </Link>
          }
        />
      </PageContainer>
    );
  }

  const stats = statsQuery.data;
  const submissions = submissionsQuery.data?.items ?? [];

  return (
    <PageContainer>
      {/* Header */}
      <div className="flex flex-col gap-space-md border-b border-outline-variant pb-space-md lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-space-sm">
            <h1 className="truncate font-display text-headline-lg font-semibold tracking-tight text-primary">
              {exam.title}
            </h1>
            <StatusBadge tone={examTone(exam.status)} label={examLabel(exam.status)} />
          </div>
          <p className="mt-0.5  text-body-md text-on-surface-variant">
            {exam.subject}
            {exam.subject_code ? <span className="font-mono"> · {exam.subject_code}</span> : null}
            {exam.exam_date ? ` · ${formatDate(exam.exam_date)}` : ""}
            {exam.duration_minutes ? ` · ${exam.duration_minutes} min` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-space-sm">
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => setEditDetailsOpen(true)}>
            <Icon name="edit" className="text-[16px]" /> Edit details
          </button>
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => setUploadOpen(true)} disabled={exam.questions.length === 0}>
            <Icon name="upload_file" className="text-[16px]" /> Upload scripts
          </button>
          <button
            type="button"
            className="btn-primary px-space-md py-1.5  text-label-md"
            onClick={() => navigate(`/evaluation?exam=${exam.id}`)}
            disabled={(stats?.pending_review_count ?? 0) === 0 && (stats?.in_review_count ?? 0) === 0}
          >
            <Icon name="check_box" className="text-[16px]" /> Start evaluation
          </button>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 divide-y divide-outline-variant rounded border border-outline-variant bg-surface-container-lowest lg:grid-cols-4 lg:divide-x lg:divide-y-0">
        <Metric label="Questions" value={exam.questions.length} />
        <Metric label="Total Marks" value={exam.total_marks.toFixed(0)} />
        <Metric label="Scripts" value={stats?.submission_count ?? 0} />
        <Metric label="Pending Review" value={stats?.pending_review_count ?? 0} />
      </div>

      {totalCriteriaMarks !== exam.total_marks && exam.questions.length > 0 ? (
        <div className="flex items-center gap-space-sm rounded border border-review-border bg-review-bg px-space-md py-2  text-body-sm text-review-fg">
          <Icon name="warning" className="text-[16px]" />
          Marking criteria total ({totalCriteriaMarks.toFixed(1)}) does not match the examination total (
          {exam.total_marks.toFixed(1)}). Review the scheme before evaluating.
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-space-lg xl:grid-cols-[minmax(0,1fr)_420px]">
        {/* Questions & marking scheme */}
        <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
          <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
            <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
              Questions &amp; Marking Scheme
            </h2>
            <button
              type="button"
              className="btn-secondary px-space-sm py-1  text-label-md"
              onClick={() => {
                setEditing(null);
                setQuestionModalOpen(true);
              }}
            >
              <Icon name="add" className="text-[16px]" /> Add question
            </button>
          </div>

          {exam.questions.length === 0 ? (
            <div className="p-space-md">
              <EmptyState
                icon="quiz"
                title="No questions yet"
                description="Add the paper's questions and the criteria the AI should score against."
                action={
                  <button
                    type="button"
                    className="btn-primary px-space-md py-1.5  text-label-md"
                    onClick={() => {
                      setEditing(null);
                      setQuestionModalOpen(true);
                    }}
                  >
                    Add first question
                  </button>
                }
              />
            </div>
          ) : (
            <ul className="divide-y divide-outline-variant">
              {[...exam.questions]
                .sort((a, b) => a.order_index - b.order_index || a.number - b.number)
                .map((question) => {
                  const criteriaTotal = question.criteria.reduce((s, c) => s + c.max_marks, 0);
                  const mismatch = Math.abs(criteriaTotal - question.max_marks) > 0.01;
                  return (
                    <li key={question.id} className="flex flex-col gap-space-sm p-space-md">
                      <div className="flex items-start justify-between gap-space-md">
                        <div className="min-w-0">
                          <div className="flex items-center gap-space-sm">
                            <span className="rounded border border-outline-variant bg-surface-container-low px-1.5 py-0.5 font-mono text-label-sm font-semibold text-primary">
                              {question.label ?? `Q${question.number}`}
                            </span>
                            <span className=" text-label-sm uppercase tracking-wide text-outline">
                              {question.question_type.replace(/_/g, " ")}
                            </span>
                          </div>
                          <p className="mt-1  text-body-md text-on-surface">{question.text}</p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-space-xs">
                          <span className="font-mono tnum text-label-md text-primary">Max {question.max_marks.toFixed(1)}</span>
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              aria-label="Edit question"
                              className="rounded p-1 text-outline transition-colors hover:bg-surface-container-low hover:text-on-surface"
                              onClick={() => {
                                setEditing(question);
                                setQuestionModalOpen(true);
                              }}
                            >
                              <Icon name="edit" className="text-[16px]" />
                            </button>
                            <button
                              type="button"
                              aria-label="Delete question"
                              className="rounded p-1 text-outline transition-colors hover:bg-critical-bg hover:text-critical"
                              onClick={() => setDeleteTarget(question)}
                            >
                              <Icon name="delete" className="text-[16px]" />
                            </button>
                          </div>
                        </div>
                      </div>

                      {question.criteria.length > 0 ? (
                        <div className="rounded border border-outline-variant">
                          <div className="flex items-center justify-between border-b border-outline-variant bg-surface-container-low px-space-sm py-1">
                            <span className=" text-label-sm font-semibold uppercase tracking-wider text-outline">
                              Criteria
                            </span>
                            <span className={`font-mono text-label-sm ${mismatch ? "text-review-fg" : "text-verified-fg"}`}>
                              Σ {criteriaTotal.toFixed(1)} / {question.max_marks.toFixed(1)}
                            </span>
                          </div>
                          <ul className="divide-y divide-outline-variant">
                            {question.criteria.map((criterion) => (
                              <li key={criterion.id} className="flex items-center justify-between gap-space-sm px-space-sm py-1.5">
                                <span className="min-w-0 truncate  text-body-sm text-on-surface-variant">
                                  {criterion.name}
                                  {criterion.description ? (
                                    <span className="text-outline"> — {criterion.description}</span>
                                  ) : null}
                                </span>
                                <span className="shrink-0 font-mono tnum text-label-sm text-on-surface">
                                  {criterion.max_marks.toFixed(1)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : (
                        <p className="rounded border border-review-border bg-review-bg px-space-sm py-1.5  text-body-sm text-review-fg">
                          <Icon name="warning" className="mr-1 text-[14px] align-[-2px]" />
                          No criteria defined — the AI will score against the question alone. Add criteria for
                          precise, auditable marks.
                        </p>
                      )}
                    </li>
                  );
                })}
            </ul>
          )}
        </div>

        {/* Answer sheets */}
        <div className="flex flex-col rounded border border-outline-variant bg-surface-container-lowest">
          <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
            <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">
              Answer Sheets
            </h2>
            <button type="button" className="btn-secondary px-space-sm py-1  text-label-md" onClick={() => setUploadOpen(true)} disabled={exam.questions.length === 0}>
              <Icon name="add" className="text-[16px]" /> Upload
            </button>
          </div>

          {submissionsQuery.isLoading ? (
            <div className="flex flex-col gap-space-sm p-space-md">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : submissions.length === 0 ? (
            <div className="p-space-md">
              <EmptyState
                icon="description"
                title="No scripts uploaded"
                description={
                  exam.questions.length === 0
                    ? "Add at least one question before uploading scripts."
                    : "Upload candidate answer sheets to begin automated processing."
                }
              />
            </div>
          ) : (
            <ul className="divide-y divide-outline-variant">
              {submissions.map((submission) => {
                const progress =
                  submission.max_total_marks > 0
                    ? Math.round((submission.final_total_marks / submission.max_total_marks) * 100)
                    : 0;
                return (
                  <li key={submission.id} className="flex flex-col gap-space-xs p-space-md">
                    <div className="flex items-center justify-between gap-space-sm">
                      <Link
                        to={submission.status === "ready_for_review" || submission.status === "reviewed" ? `/submissions/${submission.id}/evaluate` : `/submissions/${submission.id}`}
                        className="min-w-0 truncate  text-body-sm font-medium text-on-surface hover:text-secondary hover:underline"
                      >
                        {submission.student_name ?? "Unnamed candidate"}
                      </Link>
                      <StatusBadge tone={submissionTone(submission.status)} label={submissionLabel(submission.status)} dot />
                    </div>
                    <div className="flex items-center gap-space-sm font-mono text-label-sm text-outline">
                      <span>{submission.student_roll ?? "no roll"}</span>
                      <span>·</span>
                      <span>
                        {submission.processed_page_count}/{submission.page_count} pages
                      </span>
                    </div>
                    {isProcessing(submission.status) ? (
                      <ProgressBar
                        value={submission.page_count ? (submission.processed_page_count / submission.page_count) * 100 : 0}
                        tone="info"
                      />
                    ) : (
                      <div className="flex items-center gap-space-sm">
                        <ProgressBar value={progress} tone={submission.flagged_count ? "review" : "verified"} />
                        <span className="shrink-0 font-mono tnum text-label-sm text-on-surface-variant">
                          {submission.final_total_marks.toFixed(1)}/{submission.max_total_marks.toFixed(0)}
                        </span>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      <QuestionFormModal
        open={questionModalOpen}
        onClose={() => {
          setQuestionModalOpen(false);
          setEditing(null);
        }}
        initial={editing}
        defaultNumber={exam.questions.length + 1}
        pending={saveQuestion.isPending}
        onSubmit={(values) => saveQuestion.mutate(values)}
      />

      <EditDetailsModal
        open={editDetailsOpen}
        exam={exam}
        pending={updateExam.isPending}
        onClose={() => setEditDetailsOpen(false)}
        onSubmit={(payload) => updateExam.mutate(payload)}
      />

      <UploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        examId={exam.id}
        examTitle={exam.title}
        onUploaded={(created) => {
          void queryClient.invalidateQueries({ queryKey: ["submissions", { examId }] });
          void queryClient.invalidateQueries({ queryKey: ["exam-stats", examId] });
          notify(`Queued ${created.length} script${created.length === 1 ? "" : "s"} for processing`, {
            tone: "verified",
            detail: "Processing starts automatically in the background worker.",
          });
          if (created.length === 1) navigate(`/submissions/${created[0].id}`);
        }}
      />

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Remove question"
        description="This also removes its marking criteria. Answers already evaluated against it are kept for audit."
        footer={
          <>
            <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => setDeleteTarget(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-destructive px-space-md py-1.5  text-label-md"
              onClick={() => deleteTarget && deleteQuestion.mutate(deleteTarget.id)}
              disabled={deleteQuestion.isPending}
            >
              {deleteQuestion.isPending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
              Remove question
            </button>
          </>
        }
      />
    </PageContainer>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex flex-col p-space-md">
      <span className=" text-label-sm uppercase tracking-wider text-outline">{label}</span>
      <span className="mt-1 font-mono text-headline-lg font-semibold tnum text-primary">{value}</span>
    </div>
  );
}

function EditDetailsModal({
  open,
  exam,
  pending,
  onClose,
  onSubmit,
}: {
  open: boolean;
  exam: Exam;
  pending: boolean;
  onClose: () => void;
  onSubmit: (payload: Parameters<typeof examApi.update>[1]) => void;
}) {
  const [form, setForm] = useState({
    title: exam.title,
    subject: exam.subject,
    subject_code: exam.subject_code ?? "",
    course: exam.course ?? "",
    academic_year: exam.academic_year ?? "",
    exam_date: exam.exam_date ?? "",
    duration_minutes: exam.duration_minutes ? String(exam.duration_minutes) : "",
    instructions: exam.instructions ?? "",
    status: exam.status as ExamStatus,
  });

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit examination"
      width="max-w-2xl"
      footer={
        <>
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary px-space-md py-1.5  text-label-md"
            disabled={pending}
            onClick={() =>
              onSubmit({
                title: form.title.trim(),
                subject: form.subject.trim(),
                subject_code: form.subject_code.trim() || null,
                course: form.course.trim() || null,
                academic_year: form.academic_year.trim() || null,
                exam_date: form.exam_date || null,
                duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null,
                instructions: form.instructions.trim() || null,
                status: form.status,
              })
            }
          >
            {pending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
            Save changes
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-space-md">
        <label className="col-span-2 flex flex-col gap-1  text-label-md text-on-surface-variant">
          Title
          <input className="field" value={form.title} onChange={set("title")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Subject
          <input className="field" value={form.subject} onChange={set("subject")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Subject code
          <input className="field font-mono" value={form.subject_code} onChange={set("subject_code")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Course
          <input className="field" value={form.course} onChange={set("course")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Academic year
          <input className="field" value={form.academic_year} onChange={set("academic_year")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Exam date
          <input type="date" className="field" value={form.exam_date} onChange={set("exam_date")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Duration (minutes)
          <input type="number" className="field font-mono" value={form.duration_minutes} onChange={set("duration_minutes")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Status
          <select className="field" value={form.status} onChange={set("status")}>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <label className="col-span-2 flex flex-col gap-1  text-label-md text-on-surface-variant">
          Instructions
          <textarea className="field" rows={2} value={form.instructions} onChange={set("instructions")} />
        </label>
      </div>
    </Modal>
  );
}

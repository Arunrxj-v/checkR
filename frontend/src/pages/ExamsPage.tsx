import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { ApiError, examApi } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { examLabel, examTone } from "@/lib/status";
import type { ExamStatus } from "@/lib/types";

const STATUS_FILTERS: Array<{ value: "" | ExamStatus; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
];

export function ExamsPage() {
  useCrumbs([{ label: "Examinations" }]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | ExamStatus>("");
  const [createOpen, setCreateOpen] = useState(false);

  const examsQuery = useQuery({
    queryKey: ["exams", { search, status }],
    queryFn: () => examApi.list({ search: search || undefined, status: status || undefined, limit: 100 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof examApi.create>[0]) => examApi.create(payload),
    onSuccess: (exam) => {
      void queryClient.invalidateQueries({ queryKey: ["exams"] });
      notify("Examination created", { tone: "verified", detail: exam.title });
      setCreateOpen(false);
      navigate(`/exams/${exam.id}`);
    },
    onError: (err) => notify("Could not create examination", { tone: "critical", detail: errorText(err) }),
  });

  const exams = examsQuery.data?.items ?? [];

  return (
    <PageContainer>
      <PageHeader
        title="Examinations"
        description="Define papers, marking schemes and question-level criteria before uploading scripts."
        actions={
          <button type="button" className="btn-primary h-8 px-space-md  text-label-md" onClick={() => setCreateOpen(true)}>
            <Icon name="add" className="text-[16px]" />
            New Examination
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-space-sm">
        <div className="relative flex-1 min-w-[220px]">
          <Icon name="search" className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[18px] text-outline" />
          <input
            className="field pl-8"
            placeholder="Search title, subject or code…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="field w-40" value={status} onChange={(e) => setStatus(e.target.value as ExamStatus | "")}>
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      <div className="overflow-hidden rounded border border-outline-variant bg-surface-container-lowest">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                <th className="px-space-md py-2.5 font-medium">Examination</th>
                <th className="px-space-md py-2.5 font-medium">Subject</th>
                <th className="px-space-md py-2.5 text-right font-medium">Questions</th>
                <th className="px-space-md py-2.5 text-right font-medium">Total Marks</th>
                <th className="px-space-md py-2.5 font-medium">Status</th>
                <th className="px-space-md py-2.5 font-medium">Created</th>
                <th className="px-space-md py-2.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant  text-body-sm">
              {examsQuery.isLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-space-md py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))
              ) : examsQuery.isError ? (
                <tr>
                  <td colSpan={7} className="px-space-md py-10 text-center text-critical-fg">
                    Could not load examinations. {errorText(examsQuery.error)}
                  </td>
                </tr>
              ) : exams.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-space-md py-12">
                    <EmptyState
                      icon="menu_book"
                      title="No examinations found"
                      description="Create an examination to define its questions and marking scheme, then upload candidate scripts."
                      action={
                        <button type="button" className="btn-primary px-space-md py-1.5  text-label-md" onClick={() => setCreateOpen(true)}>
                          New Examination
                        </button>
                      }
                    />
                  </td>
                </tr>
              ) : (
                exams.map((exam) => (
                  <tr key={exam.id} className="transition-colors hover:bg-surface-container-low/40">
                    <td className="px-space-md py-3">
                      <Link to={`/exams/${exam.id}`} className="font-medium text-on-surface hover:text-secondary hover:underline">
                        {exam.title}
                      </Link>
                      <div className=" text-label-sm text-outline">
                        {exam.course ?? exam.academic_year ?? "—"}
                      </div>
                    </td>
                    <td className="px-space-md py-3">
                      <div className="text-on-surface-variant">{exam.subject}</div>
                      <div className="font-mono text-label-sm text-outline">{exam.subject_code ?? "—"}</div>
                    </td>
                    <td className="px-space-md py-3 text-right font-mono tnum text-on-surface">{exam.question_count}</td>
                    <td className="px-space-md py-3 text-right font-mono tnum text-on-surface">
                      {exam.total_marks.toFixed(0)}
                    </td>
                    <td className="px-space-md py-3">
                      <StatusBadge tone={examTone(exam.status)} label={examLabel(exam.status)} dot />
                    </td>
                    <td className="whitespace-nowrap px-space-md py-3 text-on-surface-variant">
                      {formatDateTime(exam.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-space-md py-3 text-right">
                      <Link to={`/exams/${exam.id}`} className="btn-secondary px-space-sm py-1  text-label-md">
                        Open
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <CreateExamModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={(payload, done) => createMutation.mutate(payload, { onSettled: done })}
        pending={createMutation.isPending}
      />
    </PageContainer>
  );
}

export function CreateExamModal({
  open,
  onClose,
  onSubmit,
  pending,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: Parameters<typeof examApi.create>[0], done: () => void) => void;
  pending: boolean;
}) {
  const [form, setForm] = useState({
    title: "",
    subject: "",
    subject_code: "",
    course: "",
    academic_year: "2026",
    exam_date: "",
    duration_minutes: "180",
    instructions: "",
  });

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(
      {
        title: form.title.trim(),
        subject: form.subject.trim(),
        subject_code: form.subject_code.trim() || null,
        course: form.course.trim() || null,
        academic_year: form.academic_year.trim() || null,
        exam_date: form.exam_date || null,
        duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null,
        instructions: form.instructions.trim() || null,
      },
      () => undefined,
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New examination"
      description="Set up the paper. Questions and marking criteria are added next."
      width="max-w-2xl"
      footer={
        <>
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="create-exam-form" className="btn-primary px-space-md py-1.5  text-label-md" disabled={pending}>
            {pending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
            Create examination
          </button>
        </>
      }
    >
      <form id="create-exam-form" onSubmit={submit} className="grid grid-cols-2 gap-space-md">
        <label className="col-span-2 flex flex-col gap-1  text-label-md text-on-surface-variant">
          Title
          <input className="field" value={form.title} onChange={set("title")} required placeholder="Data Structures & Algorithms Midterm" />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Subject
          <input className="field" value={form.subject} onChange={set("subject")} required placeholder="Computer Science" />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Subject code
          <input className="field font-mono" value={form.subject_code} onChange={set("subject_code")} placeholder="CS201" />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Course
          <input className="field" value={form.course} onChange={set("course")} placeholder="B.Sc. Computer Science" />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Academic year
          <input className="field" value={form.academic_year} onChange={set("academic_year")} placeholder="2026" />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Exam date
          <input type="date" className="field" value={form.exam_date} onChange={set("exam_date")} />
        </label>
        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Duration (minutes)
          <input type="number" min={0} max={1440} className="field font-mono" value={form.duration_minutes} onChange={set("duration_minutes")} />
        </label>
        <label className="col-span-2 flex flex-col gap-1  text-label-md text-on-surface-variant">
          Instructions
          <textarea className="field" rows={2} value={form.instructions} onChange={set("instructions")} placeholder="Answer all questions. Marks are shown against each part." />
        </label>
      </form>
    </Modal>
  );
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error.";
}

export function examDateLabel(examDate: string | null): string {
  return formatDate(examDate);
}

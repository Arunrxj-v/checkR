import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Spinner";
import { examApi, resultApi } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { ExamResultOverview } from "@/lib/types";

import { errorText } from "./ExamsPage";

export function ResultsPage() {
  useCrumbs([{ label: "Results" }]);

  const examsQuery = useQuery({ queryKey: ["exams", "picker"], queryFn: () => examApi.list({ limit: 100 }) });
  const exams = examsQuery.data?.items ?? [];

  return (
    <PageContainer>
      <PageHeader
        title="Results"
        description="Finalised and in-progress outcomes, per examination."
      />

      {examsQuery.isLoading ? (
        <div className="grid grid-cols-1 gap-space-md lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : examsQuery.isError ? (
        <EmptyState icon="error" title="Could not load examinations" description={errorText(examsQuery.error)} />
      ) : exams.length === 0 ? (
        <EmptyState icon="bar_chart" title="No examinations yet" description="Create an examination and evaluate scripts to see results here." />
      ) : (
        <div className="grid grid-cols-1 gap-space-md lg:grid-cols-2">
          {exams.map((exam) => (
            <ResultCard key={exam.id} examId={exam.id} title={exam.title} subject={exam.subject} code={exam.subject_code} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}

function ResultCard({
  examId,
  title,
  subject,
  code,
}: {
  examId: string;
  title: string;
  subject: string;
  code: string | null;
}) {
  const resultsQuery = useQuery<ExamResultOverview>({
    queryKey: ["exam-results", examId],
    queryFn: () => resultApi.forExam(examId),
    staleTime: 30_000,
  });

  const overview = resultsQuery.data;
  const pct = overview && overview.submission_count > 0 ? (overview.completed_count / overview.submission_count) * 100 : 0;

  return (
    <Link
      to={`/results/${examId}`}
      className="flex flex-col gap-space-sm rounded border border-outline-variant bg-surface-container-lowest p-space-md transition-colors hover:border-outline"
    >
      <div className="flex items-start justify-between gap-space-sm">
        <div className="min-w-0">
          <h2 className="truncate font-display text-headline-sm font-semibold text-primary">{title}</h2>
          <p className=" text-body-sm text-on-surface-variant">
            {subject}
            {code ? <span className="font-mono"> · {code}</span> : null}
          </p>
        </div>
        <Icon name="chevron_right" className="text-outline" />
      </div>

      {resultsQuery.isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : !overview || overview.submission_count === 0 ? (
        <p className=" text-body-sm text-on-surface-variant">No scripts uploaded for this examination.</p>
      ) : (
        <>
          <div className="flex items-center justify-between font-mono text-label-sm text-on-surface-variant">
            <span>
              {overview.completed_count}/{overview.submission_count} finalised
            </span>
            <span className="text-secondary">
              {overview.average_percentage === null ? "—" : `avg ${formatPercent(overview.average_percentage)}`}
            </span>
          </div>
          <ProgressBar value={pct} tone={overview.completed_count === overview.submission_count ? "verified" : "info"} />
        </>
      )}
    </Link>
  );
}

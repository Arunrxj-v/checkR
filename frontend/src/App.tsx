import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui/Spinner";
import { AnswerSheetsPage } from "@/pages/AnswerSheetsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { EvaluationQueuePage } from "@/pages/EvaluationQueuePage";
import { EvaluationWorkspace } from "@/pages/EvaluationWorkspace";
import { ExamDetailPage } from "@/pages/ExamDetailPage";
import { ExamResultsPage } from "@/pages/ExamResultsPage";
import { ExamsPage } from "@/pages/ExamsPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ResultsPage } from "@/pages/ResultsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SubmissionDetailPage } from "@/pages/SubmissionDetailPage";

function FullScreenLoader() {
  return (
    <div className="flex h-screen items-center justify-center gap-space-sm bg-background text-on-surface-variant">
      <Spinner className="h-5 w-5" />
      <span className=" text-body-md">Restoring session…</span>
    </div>
  );
}

function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <FullScreenLoader />;
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <AppShell />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<DashboardPage />} />
        <Route path="exams" element={<ExamsPage />} />
        <Route path="exams/:examId" element={<ExamDetailPage />} />
        <Route path="answer-sheets" element={<AnswerSheetsPage />} />
        <Route path="evaluation" element={<EvaluationQueuePage />} />
        <Route path="submissions/:submissionId" element={<SubmissionDetailPage />} />
        <Route path="submissions/:submissionId/evaluate" element={<EvaluationWorkspace />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="results/:examId" element={<ExamResultsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

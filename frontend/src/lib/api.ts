// Single HTTP entry point for the SPA. Handles auth headers, one-shot refresh
// on 401, JSON parsing and uniform error shapes.

import type {
  Answer,
  AnswerDetail,
  AppSettings,
  AuditLogEntry,
  AuthEnvironment,
  Evaluation,
  Exam,
  ExamDetail,
  ExamResultOverview,
  ExamStats,
  Health,
  Job,
  Page,
  Question,
  Review,
  Submission,
  SubmissionDetail,
  SubmissionResult,
  SubmissionStatusOut,
  TokenResponse,
  User,
} from "./types";

type ApiQuery = Record<string, string | number | boolean | undefined | null>;

/** True when the API base names a host, so the URL must keep its origin. */
const HAS_ORIGIN = /^(?:[a-z][a-z0-9+.-]*:)?\/\//i;

/**
 * Normalise `VITE_API_BASE_URL` into the API root.
 *
 * Accepts `""`/`/` (same origin, relying on the proxy), an origin such as
 * `http://127.0.0.1:8000`, or an origin that already includes `/api`. The
 * result always ends in exactly one `/api` — `.../api` is never doubled, which
 * would silently turn every route into a 404.
 */
export function normalizeApiBase(raw: string | undefined): string {
  let base = (raw ?? "").trim().replace(/\/+$/, "");
  if (!base) return "/api";
  if (!base.startsWith("/") && !HAS_ORIGIN.test(base)) base = `/${base}`;
  return base.endsWith("/api") ? base : `${base}/api`;
}

/**
 * Build the request URL for a route path (which must not include `/api`).
 *
 * Same-origin bases stay relative so the dev-server/reverse proxy handles
 * them. An absolute base keeps its origin: dropping it was the bug that made a
 * configured `VITE_API_BASE_URL` send `/api/...` to the SPA host, which answers
 * 404 because it serves no API.
 */
export function buildApiUrl(
  apiBase: string,
  path: string,
  query?: ApiQuery,
  origin = "http://localhost",
): string {
  const url = new URL(`${apiBase}${path}`, origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return HAS_ORIGIN.test(apiBase) ? url.toString() : url.pathname + url.search;
}

const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE_URL as string | undefined);
const PREFIX = API_BASE;

export function apiUrl(path: string, query?: ApiQuery): string {
  return buildApiUrl(PREFIX, path, query, window.location.origin);
}

const ACCESS_KEY = "checkr.access_token";
const REFRESH_KEY = "checkr.refresh_token";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// --------------------------------------------------------------------------- //
// Token store
// --------------------------------------------------------------------------- //
export const tokens = {
  access(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  },
  refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

//: Emitted when the session cannot be recovered; the app listens and redirects.
export const SESSION_EXPIRED_EVENT = "checkr:session-expired";

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const refresh = tokens.refresh();
  if (!refresh) return false;
  if (!refreshInFlight) {
    refreshInFlight = fetch(apiUrl("/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = (await res.json()) as TokenResponse;
        tokens.set(data.access_token, data.refresh_token);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  /** Skip the refresh-and-retry dance (used by the refresh call itself). */
  noRetry?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  return apiUrl(path, query);
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = res.statusText;
  let message = `Request failed (${res.status})`;
  try {
    const data = await res.json();
    if (data && typeof data === "object" && "detail" in data) {
      detail = (data as { detail: unknown }).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail) && detail.length) {
        // FastAPI validation errors: surface the first human-readable message.
        const first = detail[0] as { msg?: string; loc?: unknown[] };
        message = first.msg ?? message;
      }
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message, detail);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, query, signal, noRetry } = options;

  const headers: Record<string, string> = {};
  const access = tokens.access();
  if (access) headers.Authorization = `Bearer ${access}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
    signal,
  });

  if (res.status === 401 && !noRetry) {
    const refreshed = await refreshSession();
    if (refreshed) {
      return apiRequest<T>(path, { ...options, noRetry: true });
    }
    tokens.clear();
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }

  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //
export const authApi = {
  /** Public: read before anyone signs in (demo hint + registration policy). */
  environment: (signal?: AbortSignal) =>
    apiRequest<AuthEnvironment>("/auth/environment", { signal, noRetry: true }),
  login: (email: string, password: string) =>
    apiRequest<TokenResponse>("/auth/login", { method: "POST", body: { email, password }, noRetry: true }),
  register: (payload: {
    email: string;
    full_name: string;
    password: string;
    department?: string;
    institution?: string;
  }) => apiRequest<TokenResponse>("/auth/register", { method: "POST", body: payload, noRetry: true }),
  me: (signal?: AbortSignal) => apiRequest<User>("/auth/me", { signal }),
  updateMe: (payload: Partial<Pick<User, "full_name" | "department" | "institution">>) =>
    apiRequest<User>("/auth/me", { method: "PATCH", body: payload }),
  changePassword: (current_password: string, new_password: string) =>
    apiRequest<{ detail: string }>("/auth/password", {
      method: "POST",
      body: { current_password, new_password },
    }),
  logout: () => apiRequest<{ detail: string }>("/auth/logout", { method: "POST" }),
};

// --------------------------------------------------------------------------- //
// System
// --------------------------------------------------------------------------- //
export const systemApi = {
  health: (signal?: AbortSignal) => apiRequest<Health>("/health", { signal }),
  settings: (signal?: AbortSignal) => apiRequest<AppSettings>("/settings", { signal }),
  auditLogs: (params?: { entity_type?: string; entity_id?: string; action?: string; limit?: number; offset?: number }) =>
    apiRequest<Page<AuditLogEntry>>("/audit-logs", { query: params }),
};

// --------------------------------------------------------------------------- //
// Exams & questions
// --------------------------------------------------------------------------- //
export interface ExamInput {
  title: string;
  subject: string;
  subject_code?: string | null;
  course?: string | null;
  academic_year?: string | null;
  exam_date?: string | null;
  duration_minutes?: number | null;
  instructions?: string | null;
  status?: Exam["status"];
}

export const examApi = {
  list: (params?: { status?: string; search?: string; limit?: number; offset?: number }) =>
    apiRequest<Page<Exam>>("/exams", { query: params }),
  get: (id: string, signal?: AbortSignal) => apiRequest<ExamDetail>(`/exams/${id}`, { signal }),
  create: (payload: ExamInput & { questions?: unknown[] }) =>
    apiRequest<ExamDetail>("/exams", { method: "POST", body: payload }),
  update: (id: string, payload: Partial<ExamInput>) =>
    apiRequest<ExamDetail>(`/exams/${id}`, { method: "PATCH", body: payload }),
  remove: (id: string) => apiRequest<{ detail: string }>(`/exams/${id}`, { method: "DELETE" }),
  stats: (id: string, signal?: AbortSignal) => apiRequest<ExamStats>(`/exams/${id}/stats`, { signal }),
  questions: (id: string) => apiRequest<Question[]>(`/exams/${id}/questions`),

  createQuestion: (examId: string, payload: QuestionPayload) =>
    apiRequest<Question>(`/exams/${examId}/questions`, { method: "POST", body: payload }),
  updateQuestion: (questionId: string, payload: Partial<QuestionPayload>) =>
    apiRequest<Question>(`/questions/${questionId}`, { method: "PATCH", body: payload }),
  removeQuestion: (questionId: string) =>
    apiRequest<{ detail: string }>(`/questions/${questionId}`, { method: "DELETE" }),
};

export interface QuestionPayload {
  number: number;
  label?: string | null;
  text: string;
  max_marks: number;
  question_type: string;
  expected_answer?: string | null;
  keywords?: string[];
  guidance?: string | null;
  order_index?: number;
  criteria?: Array<{ name: string; description?: string | null; max_marks: number }>;
}

// --------------------------------------------------------------------------- //
// Submissions
// --------------------------------------------------------------------------- //
export const submissionApi = {
  upload: (
    examId: string,
    files: File[],
    meta?: { student_name?: string; student_roll?: string },
    onProgress?: (percent: number) => void,
  ) =>
    new Promise<Submission[]>((resolve, reject) => {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      if (meta?.student_name) form.append("student_name", meta.student_name);
      if (meta?.student_roll) form.append("student_roll", meta.student_roll);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", apiUrl(`/exams/${examId}/submissions`));
      const access = tokens.access();
      if (access) xhr.setRequestHeader("Authorization", `Bearer ${access}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as Submission[]);
        } else {
          let message = `Upload failed (${xhr.status})`;
          try {
            const parsed = JSON.parse(xhr.responseText) as { detail?: string };
            if (parsed.detail) message = parsed.detail;
          } catch {
            /* ignore */
          }
          reject(new ApiError(xhr.status, message));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Network error during upload."));
      xhr.send(form);
    }),

  list: (params?: { exam_id?: string; status?: string; search?: string; limit?: number; offset?: number }) =>
    apiRequest<Page<Submission>>("/submissions", { query: params }),
  get: (id: string, signal?: AbortSignal) => apiRequest<SubmissionDetail>(`/submissions/${id}`, { signal }),
  status: (id: string, signal?: AbortSignal) =>
    apiRequest<SubmissionStatusOut>(`/submissions/${id}/status`, { signal }),
  update: (id: string, payload: { student_name?: string; student_roll?: string }) =>
    apiRequest<Submission>(`/submissions/${id}`, { method: "PATCH", body: payload }),
  remove: (id: string) => apiRequest<{ detail: string }>(`/submissions/${id}`, { method: "DELETE" }),
  pages: (id: string) => apiRequest<SubmissionDetail["pages"]>(`/submissions/${id}/pages`),
  process: (id: string, force = false) =>
    apiRequest<Job>(`/submissions/${id}/process`, { method: "POST", query: { force } }),
  retryPage: (pageId: string, mode: "full" | "ocr" = "full") =>
    apiRequest<Job>(`/pages/${pageId}/retry`, { method: "POST", query: { mode } }),
  jobs: (id: string) => apiRequest<Job[]>(`/submissions/${id}/jobs`),
  pageImageUrl: (pageId: string, variant: "processed" | "original" | "thumbnail" = "processed") =>
    `/pages/${pageId}/image?variant=${variant}`,
};

// --------------------------------------------------------------------------- //
// Answers, evaluation & review
// --------------------------------------------------------------------------- //
export const answerApi = {
  list: (submissionId: string) => apiRequest<Answer[]>(`/submissions/${submissionId}/answers`),
  get: (answerId: string, signal?: AbortSignal) =>
    apiRequest<AnswerDetail>(`/answers/${answerId}`, { signal }),
  evaluation: (answerId: string) => apiRequest<Evaluation>(`/answers/${answerId}/evaluation`),
  evaluations: (answerId: string) => apiRequest<Evaluation[]>(`/answers/${answerId}/evaluations`),
  reviews: (answerId: string) => apiRequest<Review[]>(`/answers/${answerId}/reviews`),
  evaluate: (answerId: string, force = true) =>
    apiRequest<Job>(`/answers/${answerId}/evaluate`, { method: "POST", query: { force } }),
  review: (
    answerId: string,
    payload: { action: string; teacher_score?: number; comment?: string; reason?: string },
  ) => apiRequest<AnswerDetail>(`/answers/${answerId}/review`, { method: "PUT", body: payload }),
};

// --------------------------------------------------------------------------- //
// Results
// --------------------------------------------------------------------------- //
export const resultApi = {
  forSubmission: (id: string, signal?: AbortSignal) =>
    apiRequest<SubmissionResult>(`/submissions/${id}/result`, { signal }),
  finalize: (id: string) =>
    apiRequest<SubmissionResult>(`/submissions/${id}/finalize`, { method: "POST" }),
  reopen: (id: string) => apiRequest<SubmissionResult>(`/submissions/${id}/reopen`, { method: "POST" }),
  forExam: (examId: string, signal?: AbortSignal) =>
    apiRequest<ExamResultOverview>(`/exams/${examId}/results`, { signal }),
};

/** AuthImage path for a page scan (resolved through `apiUrl` when fetched). */
export const pageImageUrl = submissionApi.pageImageUrl;

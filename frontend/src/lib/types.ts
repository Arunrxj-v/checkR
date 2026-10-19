// Types mirroring the FastAPI schemas exactly. Kept hand-written (rather than
// generated) so the workspace can reason about every field the UI renders.

export type UserRole = "admin" | "teacher" | "evaluator" | "student";

export type ExamStatus = "draft" | "active" | "archived";

export type QuestionType =
  | "short_answer"
  | "long_answer"
  | "definition"
  | "explanation"
  | "numerical"
  | "programming"
  | "diagram"
  | "essay"
  | "other";

export type SubmissionStatus =
  | "uploaded"
  | "processing"
  | "ocr_processing"
  | "answers_detected"
  | "ai_evaluating"
  | "ready_for_review"
  | "reviewed"
  | "completed"
  | "failed";

export type AnswerStatus =
  | "pending"
  | "evaluating"
  | "evaluated"
  | "reviewed"
  | "flagged"
  | "failed";

export type PageStatus = "uploaded" | "preprocessed" | "ocr_done" | "failed";

export type EvaluationStatus = "valid" | "superseded" | "invalid";

export type ConfidenceLevel = "high" | "medium" | "low";

export type ReviewDecision = "accepted" | "overridden" | "flagged" | "unflagged";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  department: string | null;
  institution: string | null;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

/** Public sign-in configuration served by `GET /api/auth/environment`. */
export interface AuthEnvironment {
  environment: string;
  self_registration_enabled: boolean;
  /** Development-only. The server returns `null` in production, always. */
  demo_credentials: { email: string; password: string } | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Criterion {
  id: string;
  name: string;
  description: string | null;
  max_marks: number;
  order_index: number;
}

export interface Question {
  id: string;
  exam_id: string;
  number: number;
  label: string | null;
  text: string;
  max_marks: number;
  question_type: QuestionType;
  expected_answer: string | null;
  keywords: string[];
  guidance: string | null;
  order_index: number;
  criteria: Criterion[];
}

export interface Exam {
  id: string;
  owner_id: string;
  title: string;
  subject: string;
  subject_code: string | null;
  course: string | null;
  academic_year: string | null;
  exam_date: string | null;
  duration_minutes: number | null;
  instructions: string | null;
  status: ExamStatus;
  total_marks: number;
  question_count: number;
  created_at: string;
  updated_at: string;
}

export interface ExamDetail extends Exam {
  questions: Question[];
}

export interface ExamStats {
  exam_id: string;
  submission_count: number;
  completed_count: number;
  in_review_count: number;
  processing_count: number;
  failed_count: number;
  pending_review_count: number;
  flagged_answer_count: number;
  average_percentage: number | null;
  max_total_marks: number;
}

export interface SubmissionPage {
  id: string;
  page_number: number;
  width: number | null;
  height: number | null;
  status: PageStatus;
  ocr_confidence: number | null;
  rotation_degrees: number;
  deskew_angle: number | null;
  error_message: string | null;
  has_thumbnail: boolean;
}

export interface Submission {
  id: string;
  exam_id: string;
  student_name: string | null;
  student_roll: string | null;
  status: SubmissionStatus;
  page_count: number;
  processed_page_count: number;
  max_total_marks: number;
  ai_total_marks: number;
  final_total_marks: number;
  ai_confidence: number | null;
  flagged_count: number;
  original_filename: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmissionDetail extends Submission {
  pages: SubmissionPage[];
  answer_count: number;
  evaluated_count: number;
  reviewed_count: number;
}

export interface SubmissionStatusOut {
  id: string;
  status: SubmissionStatus;
  page_count: number;
  processed_page_count: number;
  answer_count: number;
  evaluated_count: number;
  flagged_count: number;
  error_message: string | null;
  stage_message: string | null;
}

export interface Answer {
  id: string;
  submission_id: string;
  question_id: string;
  order_index: number;
  status: AnswerStatus;
  transcription: string | null;
  ocr_confidence: number | null;
  is_handwriting_uncertain: boolean;
  max_marks: number;
  ai_score: number | null;
  ai_confidence: number | null;
  ai_confidence_level: ConfidenceLevel | null;
  teacher_score: number | null;
  final_score: number | null;
  teacher_comment: string | null;
  is_flagged: boolean;
  flag_reason: string | null;
  is_reviewed: boolean;
  error_message: string | null;
  /** Manuscript pages this answer was detected on, ascending (1-based). */
  page_numbers: number[];
  /** True when the page association could not be confirmed from detection. */
  page_mapping_uncertain: boolean;
}

export interface AnswerRegion {
  id: string;
  page_id: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  label: string | null;
  confidence: number | null;
}

/** One manuscript page an answer appears on, with the regions detected on it. */
export interface AnswerPage {
  page_id: string;
  page_number: number;
  regions: AnswerRegion[];
  uncertain: boolean;
}

export interface EvaluationCriterion {
  id: string;
  name: string;
  max_marks: number;
  awarded_marks: number;
  satisfied: boolean;
  comment: string | null;
  order_index: number;
}

export interface Evaluation {
  id: string;
  answer_id: string;
  provider: string;
  model: string;
  model_version: string | null;
  prompt_version: string;
  engine_version: string;
  is_mock: boolean;
  status: EvaluationStatus;
  awarded_marks: number;
  max_marks: number;
  confidence: number;
  confidence_level: ConfidenceLevel;
  reasoning: string;
  strengths: string[];
  gaps: string[];
  contradictions: string[];
  flags: string[];
  validation_notes: string[];
  criteria: EvaluationCriterion[];
  created_at: string;
}

export interface Review {
  id: string;
  answer_id: string;
  evaluation_id: string | null;
  reviewer_id: string | null;
  decision: ReviewDecision;
  ai_score: number | null;
  teacher_score: number | null;
  comment: string | null;
  reason: string | null;
  created_at: string;
}

export interface MarkingSchemeEntry {
  id: string;
  name: string;
  description: string | null;
  max_marks: number;
  order_index: number;
}

export interface AnswerDetail extends Answer {
  regions: AnswerRegion[];
  /** Ordered page mapping the workspace drives the manuscript viewer with. */
  pages: AnswerPage[];
  /** `regions` (observed) | `detection_meta` (best effort) | `unknown`. */
  page_mapping_source: string | null;
  question_label: string | null;
  question_text: string | null;
  question_type: QuestionType | null;
  expected_answer: string | null;
  guidance: string | null;
  keywords: string[];
  marking_scheme: MarkingSchemeEntry[];
  evaluation: Evaluation | null;
  reviews: Review[];
}

export interface ResultRow {
  answer_id: string;
  question_id: string;
  question_label: string;
  question_text: string;
  max_marks: number;
  ai_score: number | null;
  teacher_score: number | null;
  final_score: number | null;
  ai_confidence: number | null;
  is_reviewed: boolean;
  is_flagged: boolean;
  status: AnswerStatus;
}

export interface SubmissionResult {
  submission_id: string;
  exam_id: string;
  student_name: string | null;
  student_roll: string | null;
  status: string;
  max_total_marks: number;
  ai_total_marks: number;
  final_total_marks: number;
  percentage: number | null;
  reviewed_count: number;
  flagged_count: number;
  total_answers: number;
  rows: ResultRow[];
  generated_at: string;
}

export interface ExamResultOverview {
  exam_id: string;
  submission_count: number;
  completed_count: number;
  average_percentage: number | null;
  highest_percentage: number | null;
  lowest_percentage: number | null;
  rows: Array<{
    submission_id: string;
    student_name: string | null;
    student_roll: string | null;
    status: SubmissionStatus;
    max_total_marks: number;
    ai_total_marks: number;
    final_total_marks: number;
    percentage: number | null;
    flagged_count: number;
  }>;
}

export interface Job {
  id: string;
  job_type: string;
  status: string;
  submission_id: string | null;
  answer_id: string | null;
  page_id: string | null;
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_email: string | null;
  actor_role: string | null;
  description: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  created_at: string;
}

export interface AppSettings {
  app_name: string;
  environment: string;
  version: string;
  ai: {
    provider: string;
    model: string;
    is_mock: boolean;
    confidence_high: number;
    confidence_medium: number;
  };
  storage: { provider: string };
  uploads: {
    max_upload_mb: number;
    max_submission_pages: number;
    accepted_types: string[];
  };
  question_types: string[];
}

export interface Health {
  status: string;
  app: string;
  version: string;
  environment: string;
  database: string;
  storage: Record<string, unknown>;
  ai: Record<string, unknown>;
  warnings: string[];
}

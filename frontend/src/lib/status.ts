// Status → semantic tone mapping. The interface only ever uses the restrained
// tone set defined in the design system: verified, review, critical, neutral
// and a single informational cobalt for in-flight states.

import type {
  AnswerStatus,
  ConfidenceLevel,
  ExamStatus,
  PageStatus,
  ReviewDecision,
  SubmissionStatus,
} from "./types";

export type Tone = "verified" | "review" | "critical" | "neutral" | "info";

export const TONE_BADGE: Record<Tone, string> = {
  verified: "bg-verified-bg text-verified-fg border-verified-border",
  review: "bg-review-bg text-review-fg border-review-border",
  critical: "bg-critical-bg text-critical-fg border-critical-border",
  neutral: "bg-neutral-bg text-neutral-fg border-neutral-border",
  info: "bg-secondary-fixed text-on-secondary-fixed-variant border-secondary-fixed-dim",
};

export const TONE_DOT: Record<Tone, string> = {
  verified: "bg-verified",
  review: "bg-review",
  critical: "bg-critical",
  neutral: "bg-outline",
  info: "bg-secondary",
};

export const TONE_TEXT: Record<Tone, string> = {
  verified: "text-verified-fg",
  review: "text-review-fg",
  critical: "text-critical-fg",
  neutral: "text-on-surface-variant",
  info: "text-on-secondary-fixed-variant",
};

export const TONE_BAR: Record<Tone, string> = {
  verified: "bg-verified",
  review: "bg-review",
  critical: "bg-critical",
  neutral: "bg-outline",
  info: "bg-secondary",
};

const SUBMISSION_TONES: Record<SubmissionStatus, Tone> = {
  uploaded: "neutral",
  processing: "info",
  ocr_processing: "info",
  answers_detected: "info",
  ai_evaluating: "info",
  ready_for_review: "review",
  reviewed: "review",
  completed: "verified",
  failed: "critical",
};

const SUBMISSION_LABELS: Record<SubmissionStatus, string> = {
  uploaded: "Queued",
  processing: "Processing",
  ocr_processing: "Reading Handwriting",
  answers_detected: "Matching Answers",
  ai_evaluating: "AI Evaluating",
  ready_for_review: "In Review",
  reviewed: "Reviewed",
  completed: "Completed",
  failed: "Failed",
};

export function submissionTone(status: SubmissionStatus): Tone {
  return SUBMISSION_TONES[status] ?? "neutral";
}

export function submissionLabel(status: SubmissionStatus): string {
  return SUBMISSION_LABELS[status] ?? status;
}

export function isProcessing(status: SubmissionStatus): boolean {
  return (
    status === "uploaded" ||
    status === "processing" ||
    status === "ocr_processing" ||
    status === "answers_detected" ||
    status === "ai_evaluating"
  );
}

/** Was this status reached before the teacher can start reviewing? */
export function isAwaitingReview(status: SubmissionStatus): boolean {
  return status === "ready_for_review" || status === "reviewed" || status === "completed";
}

const ANSWER_TONES: Record<AnswerStatus, Tone> = {
  pending: "neutral",
  evaluating: "info",
  evaluated: "verified",
  reviewed: "verified",
  flagged: "review",
  failed: "critical",
};

const ANSWER_LABELS: Record<AnswerStatus, string> = {
  pending: "Pending",
  evaluating: "Evaluating",
  evaluated: "AI Evaluated",
  reviewed: "Reviewed",
  flagged: "Needs Review",
  failed: "Failed",
};

export function answerTone(status: AnswerStatus, isFlagged = false): Tone {
  if (isFlagged && status !== "reviewed") return "review";
  return ANSWER_TONES[status] ?? "neutral";
}

export function answerLabel(status: AnswerStatus): string {
  return ANSWER_LABELS[status] ?? status;
}

const EXAM_LABELS: Record<ExamStatus, string> = {
  draft: "Draft",
  active: "Active",
  archived: "Archived",
};

const EXAM_TONES: Record<ExamStatus, Tone> = {
  draft: "neutral",
  active: "info",
  archived: "neutral",
};

export function examLabel(status: ExamStatus): string {
  return EXAM_LABELS[status] ?? status;
}

export function examTone(status: ExamStatus): Tone {
  return EXAM_TONES[status] ?? "neutral";
}

const PAGE_LABELS: Record<PageStatus, string> = {
  uploaded: "Uploaded",
  preprocessed: "Prepared",
  ocr_done: "Transcribed",
  failed: "Failed",
};

export function pageLabel(status: PageStatus): string {
  return PAGE_LABELS[status] ?? status;
}

export function pageTone(status: PageStatus): Tone {
  if (status === "ocr_done") return "verified";
  if (status === "failed") return "critical";
  if (status === "preprocessed") return "info";
  return "neutral";
}

export function confidenceTone(level: ConfidenceLevel | null | undefined, value?: number | null): Tone {
  if (level === "high") return "verified";
  if (level === "medium") return "review";
  if (level === "low") return "critical";
  if (typeof value === "number") {
    if (value >= 0.85) return "verified";
    if (value >= 0.6) return "review";
    return "critical";
  }
  return "neutral";
}

export function confidenceLabel(level: ConfidenceLevel | null | undefined): string {
  if (level === "high") return "High confidence";
  if (level === "medium") return "Medium confidence";
  if (level === "low") return "Low confidence";
  return "Unrated";
}

const DECISION_LABELS: Record<ReviewDecision, string> = {
  accepted: "Accepted AI mark",
  overridden: "Overrode mark",
  flagged: "Flagged for moderation",
  unflagged: "Cleared flag",
};

export function decisionLabel(decision: ReviewDecision): string {
  return DECISION_LABELS[decision] ?? decision;
}

export function decisionTone(decision: ReviewDecision): Tone {
  if (decision === "accepted") return "verified";
  if (decision === "overridden") return "info";
  if (decision === "flagged") return "review";
  return "neutral";
}

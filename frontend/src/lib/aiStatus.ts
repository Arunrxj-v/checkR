/**
 * AI runtime status vocabulary — mirrors the backend's health check
 * (`backend/app/ai/ollama.py` + `app/api/routes/system.py`).
 *
 * Every value shown to the user derives from the backend Settings/health API;
 * nothing here is hardcoded per provider or model.
 */

export type AiStatusTone = "healthy" | "pending" | "critical";

export interface AiStatusMeta {
  /** Short label for badges and chips. */
  label: string;
  /** "healthy" = can serve work, "pending" = transient, "critical" = broken. */
  tone: AiStatusTone;
  /** Whether the runtime may accept submissions right now. */
  usable: boolean;
}

const META: Record<string, AiStatusMeta> = {
  ready: { label: "Ready", tone: "healthy", usable: true },
  connected: { label: "Connected", tone: "healthy", usable: true },
  processing: { label: "Processing", tone: "pending", usable: false },
  model_loading: { label: "Model loading", tone: "pending", usable: false },
  inference_error: { label: "Inference failed", tone: "critical", usable: false },
  model_not_installed: { label: "Model not installed", tone: "critical", usable: false },
  unavailable: { label: "Unavailable", tone: "critical", usable: false },
  error: { label: "Error", tone: "critical", usable: false },
};

const UNKNOWN: AiStatusMeta = {
  label: "Unknown",
  tone: "critical",
  usable: false,
};

/** Label + severity for a backend status string. */
export function aiStatusMeta(status: string | null | undefined): AiStatusMeta {
  if (!status) return UNKNOWN;
  return META[status] ?? UNKNOWN;
}

/** Whether the status means Ollama can be reached at all. */
export function aiConnected(status: string): boolean {
  const tone = aiStatusMeta(status).tone;
  // `processing` is busy-but-reachable: a job holds the inference slot.
  return tone === "healthy" || status === "model_loading" || status === "processing";
}

/** Whether the status reflects a fully verified local runtime. */
export function aiHealthy(status: string): boolean {
  return aiStatusMeta(status).tone === "healthy";
}

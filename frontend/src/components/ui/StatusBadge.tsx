import { TONE_BADGE, TONE_DOT, type Tone } from "@/lib/status";

interface StatusBadgeProps {
  tone: Tone;
  label: string;
  /** Render a leading status dot instead of a full chip background. */
  dot?: boolean;
  className?: string;
}

export function StatusBadge({ tone, label, dot = false, className = "" }: StatusBadgeProps) {
  if (dot) {
    return (
      <span className={`inline-flex items-center gap-1.5  text-label-sm ${className}`}>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[tone]}`} aria-hidden />
        <span className="text-on-surface-variant">{label}</span>
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5  text-label-sm font-medium ${TONE_BADGE[tone]} ${className}`}
    >
      {label}
    </span>
  );
}

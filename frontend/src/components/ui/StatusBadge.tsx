import { TONE_BADGE, type Tone } from "@/lib/status";

interface StatusBadgeProps {
  tone: Tone;
  label: string;
  /** Render the compact stamp used inside dense lists and tables. */
  dot?: boolean;
  className?: string;
}

export function StatusBadge({ tone, label, dot = false, className = "" }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded border ${TONE_BADGE[tone]} ${
        dot
          ? "px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em]"
          : "px-2 py-0.5 text-label-sm font-medium"
      } ${className}`}
    >
      {label}
    </span>
  );
}

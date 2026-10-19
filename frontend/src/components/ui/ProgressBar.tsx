import { TONE_BAR, type Tone } from "@/lib/status";

interface ProgressBarProps {
  value: number;
  tone?: Tone;
  className?: string;
  height?: string;
}

export function ProgressBar({ value, tone = "info", className = "", height = "h-1" }: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={`w-full overflow-hidden rounded-full bg-surface-container ${height} ${className}`}>
      <div className={`h-full rounded-full ${TONE_BAR[tone]}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

interface ScoreSpanProps {
  value: number | null | undefined;
  max: number | null | undefined;
  className?: string;
  size?: "sm" | "md" | "lg";
}

/** The signature "7.0 / 10" mark pair — always monospaced and tabular. */
export function ScoreSpan({ value, max, className = "", size = "sm" }: ScoreSpanProps) {
  const sizes = {
    sm: "text-body-sm",
    md: "text-label-md",
    lg: "text-headline-sm font-semibold",
  } as const;
  const digits = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : v.toFixed(1);
  return (
    <span className={`font-mono tnum ${sizes[size]} ${className}`}>
      {digits(value)}
      <span className="text-outline"> / {max === null || max === undefined ? "—" : max.toFixed(max % 1 === 0 ? 0 : 1)}</span>
    </span>
  );
}

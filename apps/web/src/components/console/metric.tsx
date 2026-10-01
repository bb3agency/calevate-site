"use client";

import type { ReactNode } from "react";

import { FlashValue } from "./valueFlash";

const VALUE_TONES = {
  default: "text-ink",
  warn: "text-warn",
  danger: "text-danger",
} as const;

/**
 * One figure with its label and a one-line hint — the unit of a KPI strip.
 *
 * No icon medallion: the label says what the number is, and a row of identical pastel
 * icons adds nothing a reader uses. When the screen polls, pass the raw wire value as
 * `flashValue` and the figure marks itself only when that value actually changes.
 * A tone is never the only signal: the hint says what the colour means (WCAG 1.4.1).
 */
export function Metric({
  label,
  value,
  flashValue,
  hint,
  tone = "default",
  className = "",
}: {
  label: string;
  value: ReactNode;
  flashValue?: string | null;
  hint?: ReactNode;
  tone?: keyof typeof VALUE_TONES;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <p className="text-[13px] font-medium text-ink-muted">{label}</p>
      <p className={`mt-1 truncate text-[26px] font-semibold leading-tight tracking-tight tabular-nums ${VALUE_TONES[tone]}`}>
        {flashValue === undefined ? value : <FlashValue value={flashValue}>{value}</FlashValue>}
      </p>
      {hint && <div className="mt-1 text-[12px] leading-snug text-ink-muted">{hint}</div>}
    </div>
  );
}

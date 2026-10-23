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
 *
 * This is the kit's metric card too: uiarc's `metric-card` was reviewed against it and
 * lost (number-only values, en-US grouping, colour by sign). What it had worth keeping is
 * here as `delta` and `trend`. A delta's colour comes from `delta.good`, not from its
 * sign, because fewer failed calls is a fall that is good news.
 */
export type MetricDelta = {
  /** The change as the screen words it: "+12%", "−₹420.00", "3 more than last week". */
  text: string;
  direction: "up" | "down" | "flat";
  /** Whether this change is good news; omitted means neither. */
  good?: boolean;
  /** Spoken after the change: "vs last week". */
  context?: string;
};

const DELTA_TONE = { good: "text-brand-strong", bad: "text-danger", neutral: "text-ink-muted" } as const;
const ARROW = { up: "↑", down: "↓", flat: "→" } as const;

export function Metric({
  label,
  value,
  flashValue,
  hint,
  tone = "default",
  delta,
  trend,
  className = "",
}: {
  label: string;
  value: ReactNode;
  flashValue?: string | null;
  hint?: ReactNode;
  tone?: keyof typeof VALUE_TONES;
  delta?: MetricDelta;
  /** A `Sparkline` (or any small figure) beside the value. */
  trend?: ReactNode;
  className?: string;
}) {
  // A figure that is plain text marks itself when it changes without the caller passing
  // anything (D-774: every figure on a live screen updates in place). `flashValue` still
  // wins when the shown text is formatted from a wire value that can move without it.
  const compared =
    flashValue !== undefined
      ? flashValue
      : typeof value === "string" || typeof value === "number"
        ? String(value)
        : undefined;
  return (
    <div className={`min-w-0 ${className}`}>
      <p className="text-[13px] font-medium text-ink-muted">{label}</p>
      <div className="mt-1 flex flex-wrap items-end gap-x-3 gap-y-1">
        <p className={`text-figure tabular-nums [overflow-wrap:anywhere] ${VALUE_TONES[tone]}`}>
          {compared === undefined ? value : <FlashValue value={compared}>{value}</FlashValue>}
        </p>
        {trend ? <div className="mb-1.5 shrink-0">{trend}</div> : null}
      </div>
      {delta ? (
        <p
          className={`mt-0.5 text-[12px] font-medium tabular-nums ${
            DELTA_TONE[delta.good === undefined ? "neutral" : delta.good ? "good" : "bad"]
          }`}
        >
          <span aria-hidden>{ARROW[delta.direction]} </span>
          {delta.text}
          {delta.context ? <span className="font-normal text-ink-muted"> {delta.context}</span> : null}
        </p>
      ) : null}
      {hint && <div className="mt-1 text-[12px] leading-snug text-ink-muted">{hint}</div>}
    </div>
  );
}

/**
 * Figures across the top of a page, separated from what follows by one hairline, in both
 * consoles. Pass `label` when the strip is a region of its own (a dashboard's "Today at a
 * glance"); it then renders as a named section.
 */
export function MetricRow({
  children,
  label,
  className = "",
}: {
  children: ReactNode;
  label?: string;
  className?: string;
}) {
  const cls = `grid grid-cols-2 gap-x-6 gap-y-6 border-b border-line pb-8 md:grid-cols-4 ${className}`;
  return label ? (
    <section aria-label={label} className={cls}>
      {children}
    </section>
  ) : (
    <div className={cls}>{children}</div>
  );
}

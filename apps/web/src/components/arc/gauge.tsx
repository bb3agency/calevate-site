"use client";

/**
 * The AGENT READINESS SCORE (founder, f7d9f716 item 2): a 0–100 ring with the band it
 * falls in, and beside it what to fix to raise it. Shown on each agent and on the
 * dashboard. The score and the fixes are the server's; this component only presents them.
 *
 * Adapted from uiarc's `gauge` (MIT, see ./LICENSE): the 270° ring is kept; the count-up
 * on view and the blurred caption swap are not. The band is always written in words beside
 * the ring, so the colour is never the only thing that says "needs work" (WCAG 1.4.1).
 * A score not yet computed renders as "—" with its reason, never as 0.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import clsx from "clsx";

export type GaugeBand = {
  /** The band applies from this score upward (inclusive). */
  from: number;
  label: string;
  tone: "danger" | "warn" | "good";
};

export type ReadinessFix = {
  id: string;
  /** What to do, as an instruction: "Answer the 3 questions callers asked this week". */
  label: string;
  /** Why it matters, or how many points it is worth. */
  detail?: string;
  /** Points it would add, when the server says. */
  points?: number;
  href?: string;
  /** A control instead of a link (an ActionButton, a toggle). */
  action?: ReactNode;
};

/** Default bands for readiness; a screen may pass its own. */
export const READINESS_BANDS: GaugeBand[] = [
  { from: 0, label: "Needs work", tone: "danger" },
  { from: 50, label: "Nearly ready", tone: "warn" },
  { from: 80, label: "Ready", tone: "good" },
];

const TONE_STROKE = { danger: "var(--danger)", warn: "var(--chart-warn)", good: "var(--brand)" } as const;
const TONE_TEXT = { danger: "text-danger", warn: "text-warn", good: "text-brand-strong" } as const;

export type GaugeProps = {
  /** 0–100; `null` while there is no score yet. */
  value: number | null;
  /** What the score is: "Readiness". Also the meter's accessible name. */
  label: string;
  bands?: GaugeBand[];
  /** Said under the ring when `value` is null: "Run a practice test to get a score". */
  pendingText?: string;
  fixes?: ReadinessFix[];
  fixesTitle?: string;
  /** Said when the score has nothing left to fix. */
  allDoneText?: string;
  pointsLabel?: (points: number) => string;
  size?: number;
  className?: string;
};

function bandFor(value: number, bands: GaugeBand[]): GaugeBand | undefined {
  return [...bands].sort((a, b) => b.from - a.from).find((b) => value >= b.from);
}

export function Gauge({
  value,
  label,
  bands = READINESS_BANDS,
  pendingText = "No score yet",
  fixes,
  fixesTitle = "What to fix",
  allDoneText = "Nothing left to fix.",
  pointsLabel = (p) => `+${p}`,
  size = 132,
  className,
}: GaugeProps) {
  const score = value === null ? null : Math.max(0, Math.min(100, Math.round(value)));
  const band = score === null ? undefined : bandFor(score, bands);
  const r = size / 2 - 9;
  const sweep = 270;
  const arc = (2 * Math.PI * r * sweep) / 360;
  const filled = score === null ? 0 : (arc * score) / 100;
  return (
    <div className={clsx("flex flex-wrap items-start gap-x-6 gap-y-4", className)}>
      <div
        // No score yet is not a meter reading (a meter must carry a value), so it is an
        // image named by the reason there is no score.
        {...(score === null
          ? { role: "img", "aria-label": `${label}: ${pendingText}` }
          : {
              role: "meter",
              "aria-label": label,
              "aria-valuemin": 0,
              "aria-valuemax": 100,
              "aria-valuenow": score,
              "aria-valuetext": `${score} out of 100, ${band?.label ?? ""}`,
            })}
        className="relative shrink-0"
        style={{ width: size, height: size }}
      >
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="rotate-[135deg]">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--surface-muted)"
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={`${arc} ${2 * Math.PI * r}`}
          />
          {score !== null && score > 0 ? (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={band ? TONE_STROKE[band.tone] : "var(--brand)"}
              strokeWidth={10}
              strokeLinecap="round"
              strokeDasharray={`${filled} ${2 * Math.PI * r}`}
              className="motion-safe:transition-[stroke-dasharray] motion-safe:duration-(--duration-slow) motion-safe:ease-out"
            />
          ) : null}
        </svg>
        <div aria-hidden className="absolute inset-0 grid place-content-center text-center">
          <span className="text-figure tabular-nums text-ink">{score ?? "—"}</span>
          <span className={clsx("text-meta font-medium", band ? TONE_TEXT[band.tone] : "text-ink-muted")}>
            {band?.label ?? label}
          </span>
        </div>
      </div>
      <div className="min-w-0 flex-1 basis-56">
        {score === null ? <p className="text-body text-ink-muted">{pendingText}</p> : null}
        {fixes ? (
          <>
            <h3 className="text-body font-semibold text-ink">{fixesTitle}</h3>
            {fixes.length === 0 ? (
              <p className="mt-1 text-body text-ink-muted">{allDoneText}</p>
            ) : (
              <ul className="mt-1 divide-y divide-line">
                {fixes.map((fix) => (
                  <FixRow key={fix.id} fix={fix} pointsLabel={pointsLabel} />
                ))}
              </ul>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

function FixRow({ fix, pointsLabel }: { fix: ReadinessFix; pointsLabel: (p: number) => string }) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block text-body text-ink">{fix.label}</span>
        {fix.detail ? <span className="block text-meta text-ink-muted">{fix.detail}</span> : null}
      </span>
      {fix.points !== undefined ? (
        <span className="shrink-0 text-meta font-semibold tabular-nums text-brand-strong">{pointsLabel(fix.points)}</span>
      ) : null}
    </>
  );
  if (fix.href) {
    return (
      <li>
        <Link
          href={fix.href}
          className="-mx-2 flex min-h-11 items-center gap-3 rounded-md px-2 py-2 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {body}
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
        </Link>
      </li>
    );
  }
  return (
    <li className="flex min-h-11 flex-wrap items-center gap-3 py-2">
      {body}
      {fix.action}
    </li>
  );
}

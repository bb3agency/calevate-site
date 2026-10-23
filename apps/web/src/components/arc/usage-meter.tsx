"use client";

/**
 * How much of an allowance is used: free trial minutes, the month's spending cap, the room
 * left in an agent's instructions.
 *
 * Adapted from uiarc's `usage-meter` (MIT, see ./LICENSE). The geometry takes numbers; every
 * figure a person READS is the caller's own string (minutes and rupees arrive as decimal
 * strings and are shown as sent, through `formatINR` or `formatCount` — hard rule 7), so
 * the meter never re-derives a billed quantity in the browser.
 *
 * Going past the limit is not always a fault: overage minutes on a plan that allows them
 * are billed, not refused. So the tone past the limit is the caller's (`overTone`), and the
 * words beside the bar always say what the state means. A limit of zero or less is "no
 * limit" and draws no bar at all.
 */

import type { ReactNode } from "react";
import clsx from "clsx";

import { seriesColor } from "./chart-core";

export type UsageSegment = { label: string; value: number };

export type UsageMeterProps = {
  /** Accessible name and visible title: "Free minutes". */
  label: string;
  /** For the bar's length only. */
  used: number;
  limit: number;
  /** What a person reads for `used`: "42", "₹1,240.00". */
  usedText: string;
  /** What a person reads for the limit: "60 minutes", "₹5,000.00". */
  limitText?: string;
  /** The sentence beside the bar; default "<used> of <limit> used". */
  caption?: ReactNode;
  /** Spoken value text; default mirrors the caption. */
  valueText?: string;
  /** Share used at which the bar turns amber (default 0.9). */
  warnAt?: number;
  /** How "over the limit" is painted: billed overage is `warn`, a hard stop is `danger`. */
  overTone?: "warn" | "danger";
  /** Up to four parts of `used`, shown as a split bar with a legend (e.g. by agent). */
  segments?: UsageSegment[];
  /** One line under the bar: what happens at the limit. */
  hint?: ReactNode;
  /** `inline`: a short bar and the caption on one line, for toolbars. */
  variant?: "block" | "inline";
  noLimitText?: string;
  className?: string;
};

export function UsageMeter({
  label,
  used,
  limit,
  usedText,
  limitText,
  caption,
  valueText,
  warnAt = 0.9,
  overTone = "danger",
  segments,
  hint,
  variant = "block",
  noLimitText = "No limit",
  className,
}: UsageMeterProps) {
  const unlimited = !(limit > 0);
  const share = unlimited ? 0 : Math.max(0, used) / limit;
  const over = !unlimited && share > 1;
  const fill = over
    ? overTone === "danger"
      ? "bg-danger"
      : "bg-chart-warn"
    : share >= warnAt
      ? "bg-chart-warn"
      : "bg-brand";
  const words =
    caption ??
    (unlimited ? `${usedText} used · ${noLimitText}` : limitText ? `${usedText} of ${limitText} used` : `${usedText} used`);
  const spoken = valueText ?? (typeof words === "string" ? words : `${usedText} used`);
  const parts = segments?.filter((s) => s.value > 0).slice(0, 4) ?? [];
  const partsTotal = parts.reduce((sum, s) => sum + s.value, 0);

  const bar = unlimited ? null : (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={limit}
      aria-valuenow={Math.min(Math.max(0, used), limit)}
      aria-valuetext={spoken}
      className={clsx(
        "relative overflow-hidden rounded-full bg-ink/[0.08]",
        variant === "inline" ? "h-1.5 w-24 shrink-0" : "h-2 w-full",
      )}
    >
      {parts.length > 1 && !over ? (
        <div className="flex h-full gap-[2px]" style={{ width: `${Math.min(1, share) * 100}%` }}>
          {parts.map((p, i) => (
            <span key={p.label} className="h-full first:rounded-s-full last:rounded-e-full" style={{ width: `${(p.value / partsTotal) * 100}%`, background: seriesColor(i) }} />
          ))}
        </div>
      ) : (
        <div className={clsx("h-full rounded-full", fill)} style={{ width: `${Math.min(1, share) * 100}%` }} />
      )}
    </div>
  );

  if (variant === "inline") {
    return (
      <div className={clsx("flex min-w-0 items-center gap-2", className)}>
        {bar}
        <span className={clsx("text-meta tabular-nums", over ? (overTone === "danger" ? "text-danger" : "text-warn") : "text-ink-muted")}>
          {words}
        </span>
      </div>
    );
  }

  return (
    <div className={clsx("min-w-0 space-y-2", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <p className="text-body font-medium text-ink">{label}</p>
        <p className={clsx("text-meta tabular-nums", over ? (overTone === "danger" ? "font-medium text-danger" : "font-medium text-warn") : "text-ink-muted")}>
          {words}
        </p>
      </div>
      {bar}
      {parts.length > 1 ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-muted">
          {parts.map((p, i) => (
            <li key={p.label} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: seriesColor(i) }} />
              {p.label}
            </li>
          ))}
        </ul>
      ) : null}
      {hint ? <p className="text-meta text-ink-faint">{hint}</p> : null}
    </div>
  );
}

"use client";

import { EmptyState } from "@/components/ui";
import type { Dashboard } from "@/lib/api/client";

/**
 * The seven-day stacked column chart from the design, drawn from `daily_7d`.
 *
 * The four classes PARTITION `calls.status` — the API guarantees
 * `completed + no_answer + failed + in_flight === total` on every bucket — so the
 * stack always fills its column exactly and a reader can add the segments up. The
 * colours are the ones `StatusBadge` already paints for the same statuses, so a bar
 * and a badge on the same screen never disagree about what a call was.
 *
 * Heights are relative to the busiest day rather than to a fixed "1K" axis, which is
 * what the mock drew: a client doing 20 calls a week would have seen seven invisible
 * stubs under a scale nobody told them was arbitrary. The tallest column is full
 * height and every column is labelled with its own total, so the shape is readable
 * and the numbers are checkable without a tooltip.
 *
 * Zero-height columns still render their baseline: a day with no calls is a FACT
 * about that day, and the API zero-fills for the same reason.
 */
const DAY_CLASSES = [
  { key: "completed", label: "Completed", fill: "bg-brand" },
  { key: "no_answer", label: "No answer", fill: "bg-amber-400" },
  { key: "failed", label: "Failed", fill: "bg-rose-500" },
  {
    key: "in_flight",
    label: "Still running",
    fill: "bg-slate-300 dark:bg-slate-600",
  },
] as const;

export function DailyCalls({ days }: { days: Dashboard["daily_7d"] }) {
  if (!days.length) {
    return (
      <EmptyState
        title="No call history yet"
        hint="Each day appears here as it happens."
      />
    );
  }
  const busiest = Math.max(...days.map((day) => day.total));
  return (
    <div>
      {/* The four-way split existed ONLY in the bars' `title` tooltips — mouse users
          got it, keyboard and screen-reader users got nothing (ux-audit D1). The
          rendered chart is aria-hidden and this table is its text alternative; the
          numbers are the same `daily_7d` rows, not a second computation. */}
      <table className="sr-only">
        <caption>Calls each day for the last 7 days, by outcome</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Total</th>
            {DAY_CLASSES.map((cls) => (
              <th key={cls.key} scope="col">
                {cls.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.ist_date}>
              <th scope="row">{formatDayLabel(day.ist_date)}</th>
              <td>{day.total}</td>
              {DAY_CLASSES.map((cls) => (
                <td key={cls.key}>{day[cls.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div aria-hidden="true">
        <div className="mb-6 flex flex-wrap items-center gap-4 text-xs font-medium text-ink-muted">
          {DAY_CLASSES.map((cls) => (
            <span key={cls.key} className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${cls.fill}`} />
              {cls.label}
            </span>
          ))}
        </div>

        <div className="flex h-[240px] items-end justify-between gap-2">
          {days.map((day) => (
            <div
              key={day.ist_date}
              className="flex h-full min-w-0 flex-1 flex-col items-center gap-2"
            >
              <span className="text-[11px] font-semibold tabular-nums text-ink">
                {day.total}
              </span>
              <div
                className="flex w-full max-w-[44px] flex-col-reverse overflow-hidden rounded-t-md bg-black/[0.03] dark:bg-white/5"
                style={{
                  height: `${busiest > 0 ? Math.max(2, Math.round((day.total / busiest) * 100)) : 2}%`,
                }}
                title={`${day.ist_date}: ${day.total} calls`}
              >
                {DAY_CLASSES.map((cls) => (
                  <span
                    key={cls.key}
                    className={`w-full ${cls.fill}`}
                    style={{ flexGrow: day[cls.key], flexBasis: 0 }}
                  />
                ))}
              </div>
              <span className="w-full truncate text-center text-[11px] font-medium text-ink-muted">
                {formatDayLabel(day.ist_date)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * "13 Aug" from the API's `YYYY-MM-DD`, WITHOUT constructing a Date.
 *
 * `new Date("2026-08-13")` parses as midnight UTC and then renders in the browser's
 * zone, so a client in IST sees the previous day's label over the correct day's bar.
 * The string is already an IST calendar date — the server did that work — so the only
 * correct thing to do with it is read it.
 */
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function formatDayLabel(istDate: string): string {
  const [, month, day] = istDate.split("-");
  const index = Number(month) - 1;
  return `${Number(day)} ${MONTHS[index] ?? month}`;
}

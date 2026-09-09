"use client";

import { EmptyState, ScrollRegion, formatCount } from "@/components/ui";
import type { Performance } from "@/lib/api/performance";

/**
 * The four readings under the tiles — a rate, a funnel, an outcome list and the hour
 * histogram — with the two label helpers the histogram needs. One subject: how this
 * period's numbers are DRAWN, kept out of the screen that decides which period to ask for.
 */

/**
 * A whole-number percentage, or null when the server said there is nothing to measure.
 *
 * `=== null` alone would let an `undefined` — a field the response omitted — render as
 * "undefined%", which is the one output worse than a wrong number.
 */
export function ratePct(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${value}%`;
}

/** Said, rather than left for the reader to notice numbers moving under them. */
export function Updating({ busy }: { busy: boolean }) {
  if (!busy) return null;
  return <span className="text-[11px] font-medium text-ink-faint">Updating…</span>;
}

/**
 * Calls → answered → interested, as three bars against the top of the funnel.
 *
 * Widths are a share of `calls`, so the bars are read against each other rather than
 * against an axis nobody drew — and each prints its own count, so the shape can be
 * checked without hovering anything. A non-zero stage keeps a 2% floor: "3 of 900" must
 * still be visible, and a stage that exists must not render as one that does not.
 */
const FUNNEL_SHADES = ["bg-brand-strong", "bg-brand", "bg-brand-bright"] as const;

export function Funnel({ funnel }: { funnel: Performance["funnel"] }) {
  if (funnel.calls === 0) {
    return (
      <EmptyState
        title="No calls in this period"
        hint="Once your agent starts taking or making calls, you will see them here."
      />
    );
  }
  const stages = [
    { label: "Calls", count: funnel.calls },
    { label: "Answered", count: funnel.connected },
    { label: "Interested", count: funnel.qualified },
  ];
  return (
    <div className="space-y-3">
      {stages.map((stage, index) => (
        <div key={stage.label} className="flex items-center gap-3">
          <div className="w-20 shrink-0 text-sm text-ink-muted">{stage.label}</div>
          <div className="h-6 flex-1 overflow-hidden rounded-md bg-black/[0.04] dark:bg-white/10">
            <div
              className={`h-full rounded-md ${FUNNEL_SHADES[index]}`}
              style={{
                width: `${stage.count > 0 ? Math.max((stage.count / funnel.calls) * 100, 2) : 0}%`,
              }}
              title={`${stage.label}: ${stage.count}`}
            />
          </div>
          <div className="w-14 shrink-0 text-right text-sm font-semibold tabular-nums text-ink">
            {formatCount(stage.count)}
          </div>
        </div>
      ))}
      <p className="text-xs text-ink-muted">
        Answered means the call reached a real conversation — not voicemail or a missed
        call. Interested counts customers, not calls: three calls to the same person count
        once.
      </p>
    </div>
  );
}

/**
 * Outcome → count, busiest first.
 *
 * The key is the agent's outcome tag where it set one and the call's own status where it
 * did not (`COALESCE(outcome_tag, status)` in crm/performance.py), which is why the
 * caption says so: a reader who thinks these are all tags will read "no_answer" as an
 * outcome someone chose.
 *
 * No `lookup()` needed — these keys are printed, never used to index a copy table, which
 * is the read `src/lib/lookup.ts` exists to make safe.
 */
export function Outcomes({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort(([, a], [, b]) => b - a);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing to show yet"
        hint="Call results will appear here after your first calls."
      />
    );
  }
  const busiest = Math.max(...rows.map(([, count]) => count));
  return (
    <div className="space-y-2.5">
      {rows.map(([outcome, count]) => (
        <div key={outcome}>
          <div className="flex items-baseline justify-between gap-3">
            {/* An outcome tag comes from the agent's own extraction schema, so its
                length is the client's choice and nothing else on this screen repeats it. */}
            <span
              title={outcome.replace(/_/g, " ")}
              className="truncate text-[13px] capitalize text-ink-muted"
            >
              {outcome.replace(/_/g, " ")}
            </span>
            <span className="text-[13px] font-semibold tabular-nums text-ink">
              {formatCount(count)}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/[0.04] dark:bg-white/10">
            <div
              className="h-full rounded-full bg-brand"
              style={{ width: `${busiest > 0 ? Math.max((count / busiest) * 100, 2) : 0}%` }}
            />
          </div>
        </div>
      ))}
      <p className="pt-1 text-xs text-ink-muted">
        The tag your agent recorded, or how the call ended when it recorded none.
      </p>
    </div>
  );
}

/** "9 am", "12 midnight" — plain words beat "0900 IST" for this reader. */
function hourLabel(hour: number): string {
  if (hour === 0) return "12 midnight";
  if (hour === 12) return "12 noon";
  return hour < 12 ? `${hour} am` : `${hour - 12} pm`;
}

/** The axis form: "12a", "3p". */
function shortHourLabel(hour: number): string {
  if (hour === 0) return "12a";
  if (hour === 12) return "12p";
  return hour < 12 ? `${hour}a` : `${hour - 12}p`;
}

/**
 * 24 vertical bars, one per IST hour, each printing its own count.
 *
 * All 24 always render: the server guarantees 24 buckets and zero-fills the silent ones
 * (`PerformanceOut.busiest_hours_ist`), and a chart that omits them reads as data loss to
 * the one reader who would notice 3am missing. A zero hour keeps a baseline stub and
 * prints its 0 in the faint ink, so "nothing happened" and "nothing was measured" cannot
 * be confused.
 *
 * Heights are relative to the busiest hour, never to a fixed axis — a clinic doing 20
 * calls a week would otherwise see 24 invisible stubs under a scale nobody told them was
 * arbitrary. The axis labels sit INSIDE each bar's own column (every third hour), so they
 * are aligned by construction rather than by four equal-width cells that happen to line
 * up with a 24-bar row.
 *
 * `calls` is the funnel's total for the same period, and it is here to explain a gap the
 * chart would otherwise be blamed for: the API counts only calls that have a start time,
 * so a dial that never reached the network is in the funnel and not in these bars.
 */
export function HourHistogram({ hours, calls }: { hours: number[]; calls: number }) {
  const busiest = Math.max(...hours, 0);
  const started = hours.reduce((sum, count) => sum + count, 0);
  return (
    <div>
      {/* Text alternative (ux-audit D1): the visual chart associates each count with its
          hour by position alone, which a screen reader cannot follow. Same
          `busiest_hours_ist` numbers, no second computation. */}
      <table className="sr-only">
        <caption>Calls by hour of day (IST)</caption>
        <thead>
          <tr>
            <th scope="col">Hour</th>
            <th scope="col">Calls</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((count, hour) => (
            <tr key={hour}>
              <th scope="row">{hourLabel(hour)}</th>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ScrollRegion label="Calls by hour of day">
        <div aria-hidden="true" className="flex min-w-[620px] items-end gap-1">
          {hours.map((count, hour) => (
            <div
              key={hour}
              className="flex min-w-0 flex-1 flex-col items-center gap-1.5"
              title={`${hourLabel(hour)}: ${count} ${count === 1 ? "call" : "calls"}`}
            >
              <span
                className={`text-[10px] tabular-nums ${
                  count > 0 ? "font-semibold text-ink" : "text-ink-faint"
                }`}
              >
                {count}
              </span>
              <div className="flex h-[120px] w-full items-end">
                <div
                  className={`w-full rounded-t-sm ${
                    count > 0 ? "bg-brand" : "bg-black/[0.06] dark:bg-white/10"
                  }`}
                  // Relative to the busiest hour; a silent hour keeps a 2px baseline so
                  // the axis stays legible on an all-zero day.
                  style={{
                    height: count > 0 ? `${Math.max((count / busiest) * 100, 4)}%` : "2px",
                  }}
                />
              </div>
              <span className="h-3 text-[10px] font-medium text-ink-faint">
                {hour % 3 === 0 ? shortHourLabel(hour) : ""}
              </span>
            </div>
          ))}
        </div>
      </ScrollRegion>
      <p className="mt-2 text-xs text-ink-muted">
        Each bar counts the calls that STARTED in that hour, Indian Standard Time.
        {started < calls && (
          <>
            {" "}
            {formatCount(started)} of {formatCount(calls)} calls in this period have a
            start time; the rest never reached the network, so they are not in this chart.
          </>
        )}
      </p>
    </div>
  );
}

"use client";

import { useState } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, StatTile, formatDuration } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { usePerformance } from "@/lib/api/performance";

const DAY_OPTIONS = [7, 30, 90] as const;

/**
 * How the phone agent is doing (SURFACES §2).
 *
 * Copy is for a shop or clinic owner, not an analyst: "calls answered", not
 * "connect rate KPI". Charts are pure CSS bars — the CSP and bundle discipline
 * forbid a chart library, and two single-series bar charts do not need one.
 */
export default function PerformancePage() {
  const session = useClientSession();
  const [days, setDays] = useState<number>(30);
  const perf = usePerformance(session, days);

  if (perf.isLoading) return <Skeleton rows={6} />;
  if (perf.error) return <ProblemNotice error={perf.error} onRetry={() => perf.refetch()} />;
  if (!perf.data) return null;

  const data = perf.data;
  const { calls, connected, qualified } = data.funnel;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Performance</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            How your phone agent did over the last {data.days} days.
          </p>
        </div>
        <div
          role="group"
          aria-label="Time period"
          className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-800"
        >
          {DAY_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={days === option}
              onClick={() => setDays(option)}
              className={
                days === option
                  ? "rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-slate-100 dark:text-slate-900"
                  : "rounded-md px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
              }
            >
              {option} days
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {/* null vs 0% is a real distinction the server makes on purpose: 0% means
            calls happened and none turned into conversations (bad news worth
            showing); null means there were no calls at all (nothing to grade).
            Collapsing both into "0%" would tell a new client their agent is
            failing before it has rung once. */}
        <StatTile
          label="Calls answered"
          value={data.connect_rate_pct !== null ? `${data.connect_rate_pct}%` : "—"}
          hint={data.connect_rate_pct !== null ? "reached a real conversation" : "no calls yet"}
        />
        <StatTile
          label="Turned into leads"
          value={data.qualify_rate_pct !== null ? `${data.qualify_rate_pct}%` : "—"}
          hint={
            data.qualify_rate_pct !== null
              ? "of answered calls became interested customers"
              : "no answered calls yet"
          }
        />
        <StatTile
          label="Average call length"
          value={formatDuration(data.avg_duration_s)}
          hint="minutes:seconds"
        />
        <StatTile
          label="Incoming / outgoing"
          value={`${data.inbound} / ${data.outbound}`}
          hint="calls received vs calls made"
        />
      </div>

      <Card title="From calls to customers">
        {calls === 0 ? (
          <EmptyState
            title="No calls in this period"
            hint="Once your agent starts taking or making calls, you will see them here."
          />
        ) : (
          <div className="space-y-3">
            <FunnelBar label="Calls" count={calls} max={calls} shade="bg-sky-600 dark:bg-sky-500" />
            <FunnelBar
              label="Answered"
              count={connected}
              max={calls}
              shade="bg-sky-500 dark:bg-sky-600"
            />
            <FunnelBar
              label="Interested"
              count={qualified}
              max={calls}
              shade="bg-sky-400 dark:bg-sky-700"
            />
            <p className="text-xs text-slate-500">
              Answered means the call reached a real conversation — not voicemail or a
              missed call. Interested counts customers, not calls: three calls to the
              same person count once.
            </p>
          </div>
        )}
      </Card>

      <Card title="Busiest hours (IST)">
        <HourHistogram hours={data.busiest_hours_ist} />
        <p className="mt-2 text-xs text-slate-500">
          When your phone rings the most. Useful for staffing the counter and picking
          the best time for outgoing calls.
        </p>
      </Card>

      <Card title="How calls ended">
        <OutcomeList outcomes={data.outcomes} />
      </Card>
    </div>
  );
}

/**
 * One funnel stage: a label, a proportional bar, and the number at the end.
 * Widths are plain CSS percentages of the top of the funnel — no chart library,
 * per bundle/CSP discipline. Non-zero counts get a 2% floor so "3 of 900" still
 * renders a visible sliver instead of disappearing.
 */
function FunnelBar({
  label,
  count,
  max,
  shade,
}: {
  label: string;
  count: number;
  max: number;
  shade: string;
}) {
  const pct = max > 0 ? (count / max) * 100 : 0;
  const width = count > 0 ? Math.max(pct, 2) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-20 shrink-0 text-sm text-slate-600 dark:text-slate-400">{label}</div>
      <div className="h-6 flex-1 overflow-hidden rounded-md bg-slate-100 dark:bg-slate-800">
        <div
          className={`h-full rounded-md ${shade}`}
          style={{ width: `${width}%` }}
          title={`${label}: ${count}`}
        />
      </div>
      <div className="w-12 shrink-0 text-right text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-50">
        {count}
      </div>
    </div>
  );
}

/** "9 am", "12 midnight" — plain words beat "0900 IST" for this reader. */
function hourLabel(hour: number): string {
  if (hour === 0) return "12 midnight";
  if (hour === 12) return "12 noon";
  return hour < 12 ? `${hour} am` : `${hour - 12} pm`;
}

/**
 * 24 vertical CSS bars, one per IST hour. All 24 always render — a silent 3am
 * still shows as an empty slot, because a chart that omits quiet hours reads as
 * missing data (the server guarantees 24 buckets for the same reason). Each slot
 * keeps a faint baseline stub so the axis is legible even on an all-zero day.
 */
function HourHistogram({ hours }: { hours: number[] }) {
  const max = Math.max(...hours, 1);
  return (
    <div>
      <div className="flex h-28 items-end gap-px sm:gap-0.5">
        {hours.map((count, hour) => (
          <div
            key={hour}
            className="flex flex-1 flex-col justify-end self-stretch"
            title={`${hourLabel(hour)}: ${count} ${count === 1 ? "call" : "calls"}`}
          >
            <div
              className={
                count > 0
                  ? "rounded-t-sm bg-sky-500 dark:bg-sky-600"
                  : "rounded-t-sm bg-slate-100 dark:bg-slate-800"
              }
              // Zero hours get a 2px stub, busy hours scale to the tallest bar.
              style={{ height: count > 0 ? `${Math.max((count / max) * 100, 4)}%` : "2px" }}
            />
          </div>
        ))}
      </div>
      {/* Axis labels at the quarter marks: each label sits under the bar it names
          (12a under hour 0, 6a under hour 6, ...), so four equal flex cells with
          left-aligned text line up with bars 0/6/12/18 of the 24-bar row. */}
      <div className="mt-1 flex border-t border-slate-200 pt-1 text-[11px] text-slate-500 dark:border-slate-800">
        <span className="flex-1">12a</span>
        <span className="flex-1">6a</span>
        <span className="flex-1">12p</span>
        <span className="flex-1">6p</span>
      </div>
    </div>
  );
}

/** Outcome → count, busiest first, in the owner's words (no snake_case on screen). */
function OutcomeList({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort(([, a], [, b]) => b - a);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing to show yet"
        hint="Call results will appear here after your first calls."
      />
    );
  }
  return (
    <dl className="space-y-2 text-sm">
      {rows.map(([outcome, count]) => (
        <div key={outcome} className="flex justify-between">
          <dt className="text-slate-600 capitalize dark:text-slate-400">
            {outcome.replace(/_/g, " ")}
          </dt>
          <dd className="font-semibold tabular-nums text-slate-900 dark:text-slate-50">{count}</dd>
        </div>
      ))}
    </dl>
  );
}

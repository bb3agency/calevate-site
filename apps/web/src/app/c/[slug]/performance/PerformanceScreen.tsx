"use client";

import { useState } from "react";

import { ActivityHeatmap } from "@/components/arc/activity-heatmap";
import { BrushChart } from "@/components/arc/brush-chart";
import { DateRangePicker, type DateRange } from "@/components/arc/calendar";
import {
  addDays,
  compareDates,
  daysBetween,
  formatDateShort,
  formatDateRange,
  isISODate,
  todayIST,
} from "@/components/arc/ist-dates";
import { Ridgeline } from "@/components/arc/ridgeline";
import { StatsBand } from "@/components/arc/stats-band";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  ToggleSwitch,
  formatCount,
} from "@/components/ui";
import {
  useActivityHeatmap,
  useActivityTimeline,
  useAnalyticsStats,
  useCallDurations,
  type AnalyticsRange,
} from "@/lib/api/analytics";
import { useMe } from "@/lib/api/hooks";
import { usePerformance } from "@/lib/api/performance";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { istDayLabel, statItems } from "../analyticsFigures";
import { chartError } from "../ChartRetry";
import {
  DURATIONS_NOTE,
  FUNNEL_NOTE,
  Funnel,
  HEATMAP_NOTE,
  OUTCOMES_NOTE,
  Outcomes,
  Updating,
  durationAxisEnd,
  durationRows,
} from "./PerformanceCharts";

/**
 * How the agents are doing over a range of IST days the owner picks (SURFACES §2).
 *
 * Every figure is the server's. The range drives the analytics reads (`days` ending on
 * `to`, D-869); the funnel and the outcome list come from `/v1/performance`, which only
 * measures the last N days ending today, so for a range that ends earlier those two panels
 * say so instead of showing figures for a different period.
 *
 * The activity timeline reads a longer stretch than the range (at least 90 days) so the
 * brush has context, and opens on the chosen range.
 */

const MAX_DAYS = 366;
/** `/v1/performance` caps `days` at 365. */
const PERFORMANCE_MAX_DAYS = 365;
const TIMELINE_MIN_DAYS = 90;

function defaultRange(): DateRange {
  const today = todayIST();
  return { start: addDays(today, -29), end: today };
}

export function PerformanceScreen() {
  const session = useClientSession();
  const me = useMe(session);
  const [range, setRange] = useState<DateRange>(defaultRange);
  const [testCalls, setTestCalls] = useState(true);
  const [heatmapMetric, setHeatmapMetric] = useState<"calls" | "leads">("calls");
  const [groupBy, setGroupBy] = useState<"agent" | "outcome">("agent");

  const today = todayIST();
  const days = Math.min(MAX_DAYS, daysBetween(range.start, range.end));
  const endsToday = range.end === today;
  const window: AnalyticsRange = { days, to: range.end, testCalls };

  const stats = useAnalyticsStats(session, window);
  const heatmap = useActivityHeatmap(session, { ...window, metric: heatmapMetric });
  const durations = useCallDurations(session, { ...window, groupBy, binSeconds: 30 });
  const timelineDays = Math.min(MAX_DAYS, Math.max(days, TIMELINE_MIN_DAYS));
  const timeline = useActivityTimeline(session, { days: timelineDays, to: range.end, testCalls });
  const perfDays = Math.min(PERFORMANCE_MAX_DAYS, days);
  const perf = usePerformance(session, perfDays);
  // A stretch with no calls at all is the chart's empty state, not a flat line to drag along.
  const drawnDays = timeline.data && timeline.data.calls > 0 ? timeline.data.days : [];

  const refused = me.data !== undefined && !me.data.permissions.includes("calls:read");
  const rangeWords = formatDateRange(range.start, range.end);

  useCopilotSurface({
    route: "/c/{slug}/performance",
    title: "How your agent is doing",
    realm: "client",
    saves: "view",
    fields: [
      { id: "performance-from", label: "First day of the period (IST)", type: "date", value: range.start },
      { id: "performance-to", label: "Last day of the period (IST)", type: "date", value: range.end },
      { id: "performance-test-calls", label: "Include your own test calls", type: "bool", value: testCalls ? "true" : "false" },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: refused
          ? "a refusal — this session may not read call records, so no figure is shown"
          : stats.data
            ? "the figures below have loaded"
            : stats.error
              ? "the figures failed to load"
              : "still loading",
      },
      { key: "period", label: "Period the figures cover (IST)", value: rangeWords },
      ...(stats.data
        ? stats.data.metrics.map((metric) => ({
            key: `stat_${metric.key}`,
            label: `${metric.key.replace(/_/g, " ")} (this period, then the period before)`,
            value: `${metric.value ?? "nothing to measure"}; before: ${metric.previous ?? "nothing to measure"}`,
          }))
        : []),
      ...(perf.data && endsToday
        ? [
            { key: "calls", label: "Calls in the period", value: String(perf.data.funnel.calls) },
            { key: "connected", label: "Of those, answered", value: String(perf.data.funnel.connected) },
            { key: "qualified", label: "Leads interested (lead-level, not call-level)", value: String(perf.data.funnel.qualified) },
            {
              key: "outcomes",
              label: "How calls ended",
              value:
                Object.entries(perf.data.outcomes)
                  .map(([outcome, count]) => `${outcome}: ${count}`)
                  .join(", ") || "nothing recorded",
            },
          ]
        : []),
    ],
    apply: (items) => {
      let start = range.start;
      let end = range.end;
      for (const item of items) {
        const wanted = asText(item.value);
        if (item.field_id === "performance-from" && isISODate(wanted)) start = wanted;
        if (item.field_id === "performance-to" && isISODate(wanted)) end = wanted;
        if (item.field_id === "performance-test-calls") setTestCalls(wanted === "true");
      }
      if (compareDates(end, today) > 0) end = today;
      if (compareDates(start, end) <= 0 && daysBetween(start, end) <= MAX_DAYS) setRange({ start, end });
    },
  });

  if (refused) {
    return (
      <RestrictionNote reason="Call reports need permission to read call records, which this account does not have. Ask your account owner for access." />
    );
  }

  const busy =
    (stats.isFetching && stats.data !== undefined) || (perf.isFetching && perf.data !== undefined);

  return (
    <div className="space-y-10 pb-12">
      <PageHeader
        description={`How your agents did, ${rangeWords}.`}
        actions={<Updating busy={busy} />}
      />

      <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
        <DateRangePicker
          label="Dates"
          value={range}
          onChange={(next) => setRange(next ?? defaultRange())}
          max={today}
          min={addDays(today, -(MAX_DAYS * 2))}
          className="w-full max-w-80 sm:w-80"
        />
        <ToggleSwitch
          label="Include my test calls"
          checked={testCalls}
          onChange={setTestCalls}
          className="pb-2"
        />
      </div>

      {stats.error ? (
        <ProblemNotice error={stats.error} onRetry={() => void stats.refetch()} />
      ) : !stats.data ? (
        <Skeleton rows={2} label="Loading the figures" />
      ) : (
        <StatsBand
          label="This period at a glance"
          items={statItems(stats.data, ["calls", "answer_rate_pct", "leads", "avg_duration_s"], {
            context: `vs the previous ${formatCount(stats.data.window.days)} days`,
          })}
        />
      )}

      <Section title="Activity over time" description="Calls each day. Drag the window below the chart to look closer.">
        <BrushChart
          // A new range, or the data arriving, opens a new window on the chosen days; the
          // brush keeps its selection in state from its first render.
          key={`${range.end}:${timelineDays}:${days}:${drawnDays.length}`}
          title="Calls each day"
          description="India time"
          seriesLabel="Calls"
          // The year only when the stretch crosses one, where "24 Oct" would name two days.
          labels={drawnDays.map((day) =>
            drawnDays[0]?.ist_date.slice(0, 4) === drawnDays[drawnDays.length - 1]?.ist_date.slice(0, 4)
              ? istDayLabel(day.ist_date)
              : formatDateShort(day.ist_date),
          )}
          values={drawnDays.map((day) => day.calls)}
          defaultRange={
            drawnDays.length > 1
              ? [Math.max(0, drawnDays.length - days), drawnDays.length - 1]
              : undefined
          }
          // Not arrived and not failed is still waiting (a paused query offline included), never "no calls".
          loading={!timeline.data && !timeline.error}
          error={chartError(timeline.error, "We could not load your calls over time.", () => void timeline.refetch())}
          empty="No calls in this stretch yet."
        />
      </Section>

      <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-12">
        <Section title="From calls to customers" info={FUNNEL_NOTE} className="lg:col-span-7">
          <PerformancePanel perf={perf} endsToday={endsToday} testCalls={testCalls} kind="funnel" />
        </Section>
        <Section title="How calls ended" info={OUTCOMES_NOTE} className="lg:col-span-5">
          <PerformancePanel perf={perf} endsToday={endsToday} testCalls={testCalls} kind="outcomes" />
        </Section>
      </div>

      <Section
        title="When it gets busy"
        info={HEATMAP_NOTE}
        action={
          <SegmentedControl
            label="Show"
            value={heatmapMetric}
            onValueChange={(next) => setHeatmapMetric(next === "leads" ? "leads" : "calls")}
            options={[
              { value: "calls", label: "Calls" },
              { value: "leads", label: "New leads" },
            ]}
          />
        }
      >
        <ActivityHeatmap
          title={heatmapMetric === "calls" ? "Calls by day and hour" : "New leads by day and hour"}
          hideTitle
          description={`${rangeWords}, India time`}
          unit={heatmapMetric === "calls" ? "calls" : "leads"}
          // The server numbers weekdays 1 (Monday) to 7; the chart counts from 0.
          cells={heatmap.data ? heatmap.data.cells.map((cell) => ({ weekday: cell.weekday - 1, hour: cell.hour, count: cell.count })) : []}
          loading={!heatmap.data && !heatmap.error}
          error={chartError(heatmap.error, "We could not load when your calls happen.", () => void heatmap.refetch())}
          empty={heatmapMetric === "calls" ? "No calls in this period." : "No new leads in this period."}
        />
      </Section>

      <Section
        title="How long calls last"
        info={DURATIONS_NOTE}
        action={
          <SegmentedControl
            label="Compare by"
            value={groupBy}
            onValueChange={(next) => setGroupBy(next === "outcome" ? "outcome" : "agent")}
            options={[
              { value: "agent", label: "Agent" },
              { value: "outcome", label: "Outcome" },
            ]}
          />
        }
      >
        <Ridgeline
          title={groupBy === "agent" ? "Call length by agent" : "Call length by outcome"}
          hideTitle
          description={
            durations.data && durations.data.other_calls > 0
              ? `${rangeWords}. ${formatCountOfCalls(durations.data.other_calls)} from other ${groupBy === "agent" ? "agents" : "outcomes"} are not shown.`
              : rangeWords
          }
          series={durations.data ? durationRows(durations.data) : []}
          maxValue={durations.data ? durationAxisEnd(durations.data) : undefined}
          labelColumn={groupBy === "agent" ? "Agent" : "Outcome"}
          medianColumn="Middle call"
          p90Column="9 in 10 under"
          loading={!durations.data && !durations.error}
          error={chartError(durations.error, "We could not load how long your calls last.", () => void durations.refetch())}
          empty="No completed calls in this period."
        />
      </Section>
    </div>
  );
}

function formatCountOfCalls(n: number): string {
  return `${formatCount(n)} ${n === 1 ? "call" : "calls"}`;
}

/** The two `/v1/performance` panels, with its own loading and failure arms. */
function PerformancePanel({
  perf,
  endsToday,
  testCalls,
  kind,
}: {
  perf: ReturnType<typeof usePerformance>;
  endsToday: boolean;
  testCalls: boolean;
  kind: "funnel" | "outcomes";
}) {
  if (!endsToday) {
    return (
      <p className="text-body text-ink-muted [text-wrap:pretty]">
        This part is counted up to today only. Choose dates that end today to see it.
      </p>
    );
  }
  if (perf.error && !perf.data) {
    return <ProblemNotice error={perf.error} onRetry={() => void perf.refetch()} />;
  }
  if (!perf.data) return <Skeleton rows={3} />;
  // `perf.data.days` is the period the server measured, which can trail the control while a
  // new range loads.
  // This read cannot leave test calls out; say so rather than let the toggle imply it did.
  const testNote = testCalls ? null : (
    <p className="text-meta text-ink-muted">Your test calls are counted here.</p>
  );
  return kind === "funnel" ? (
    <div className="space-y-3">
      <Funnel funnel={perf.data.funnel} days={perf.data.days} />
      {perf.data.funnel.calls > 0 ? (
        <p className="text-meta text-ink-muted">
          {formatCount(perf.data.inbound)} incoming, {formatCount(perf.data.outbound)} outgoing
        </p>
      ) : null}
      {testNote}
    </div>
  ) : (
    <div className="space-y-3">
      <Outcomes outcomes={perf.data.outcomes} days={perf.data.days} />
      {testNote}
    </div>
  );
}

"use client";

import { useState } from "react";

import { BrushChart } from "@/components/arc/brush-chart";
import { istShortDay } from "@/components/arc/chart-core";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { formatCount, istDateStamp, istDateToInstant } from "@/components/ui";
import { useCampaignTimelines } from "@/lib/api/analytics";
import { useClientSession } from "@/lib/api/session";

type Measure = "dials" | "connected" | "leads";

const MEASURES: { value: Measure; label: string; series: string }[] = [
  { value: "dials", label: "Calls made", series: "Calls made" },
  { value: "connected", label: "Answered", series: "Answered calls" },
  { value: "leads", label: "Leads", series: "New leads" },
];

/** The server keeps at most a year of daily buckets per read. */
const MAX_DAYS = 366;
/** A shorter campaign still gets a week of days, so the line has a shape to read. */
const MIN_DAYS = 7;
/** Days the window opens on when the campaign has run longer than this. */
const OPEN_WINDOW = 30;

/**
 * The days worth drawing: from the launch day on, but at least the last week. The read
 * asks for the server's whole year and is cut here, so its address does not move with
 * the date.
 */
export function sinceLaunch<T extends { ist_date: string }>(days: T[], launchedAt: string | null | undefined): T[] {
  const launchDay = launchedAt ? istDateStamp(new Date(launchedAt)) : null;
  const first = launchDay ? days.findIndex((day) => day.ist_date >= launchDay) : -1;
  const start = first < 0 ? Math.max(0, days.length - MIN_DAYS) : Math.min(first, Math.max(0, days.length - MIN_DAYS));
  return days.slice(start);
}

/**
 * DAY BY DAY: calls made, answered and the leads they produced, per IST day since the
 * campaign launched (`GET /v1/analytics/campaigns?campaign_id=`, zero-filled by the server).
 *
 * The brush chart draws one series, so the measure is chosen above it and the other two are
 * not dropped: the sentence under it gives all three for the days the window covers. A
 * failed read is said in words, never drawn as a flat line of zeros.
 */
export function CampaignTimeline({ campaignId, launchedAt }: { campaignId: string; launchedAt: string | null | undefined }) {
  const session = useClientSession();
  const timelines = useCampaignTimelines(session, { campaignId, days: MAX_DAYS });
  const [measure, setMeasure] = useState<Measure>("dials");

  const series = timelines.data?.campaigns.find((c) => c.campaign_id === campaignId) ?? null;
  const buckets = sinceLaunch(series?.days ?? [], launchedAt);
  const last = Math.max(0, buckets.length - 1);
  const opening: [number, number] = [Math.max(0, buckets.length - OPEN_WINDOW), last];
  const [range, setRange] = useState<[number, number] | null>(null);
  const [from, to] = range ?? opening;
  const shownDays = buckets.slice(from, to + 1);
  const sum = (key: Measure) => shownDays.reduce((total, day) => total + day[key], 0);

  const chosen = MEASURES.find((m) => m.value === measure) ?? MEASURES[0];
  const labels = buckets.map((day) => istShortDay(istDateToInstant(day.ist_date) ?? day.ist_date));
  const values = buckets.map((day) => day[measure]);
  const allZero = buckets.every((day) => day.dials === 0 && day.connected === 0 && day.leads === 0);

  // Loaded and nothing dialled: a sentence, not a flat line at zero.
  if (timelines.data && (series === null || allZero)) {
    return <p className="text-body text-ink-muted">No calls have gone out yet. Each day&rsquo;s calls show here once they do.</p>;
  }

  return (
    <div className="space-y-3">
      <SegmentedControl
        label="Show per day"
        value={measure}
        onValueChange={(next) => setMeasure(next as Measure)}
        options={MEASURES.map((m) => ({ value: m.value, label: m.label }))}
      />
      <BrushChart
        // The window is read once on mount, so the chart starts again when the days arrive.
        key={buckets.length}
        title={`${chosen.series} per day`}
        description="India time. Drag the window under the chart, or its edges, to choose the days."
        seriesLabel={chosen.series}
        labels={labels}
        values={values}
        display={values.map((v) => formatCount(v))}
        defaultRange={opening}
        onRangeChange={setRange}
        rangeText={(a, b) => `${a} to ${b}`}
        loading={timelines.isLoading}
        loadingLabel="Loading this campaign's days"
        error={
          timelines.error
            ? "We could not load this campaign's day-by-day figures. The totals above are unaffected."
            : undefined
        }
      />
      {series ? (
        <p className="text-meta text-ink-muted">
          In the days shown: <span className="tabular-nums text-ink">{formatCount(sum("dials"))}</span> calls made,{" "}
          <span className="tabular-nums text-ink">{formatCount(sum("connected"))}</span> answered,{" "}
          <span className="tabular-nums text-ink">{formatCount(sum("leads"))}</span>{" "}
          {sum("leads") === 1 ? "new lead" : "new leads"}.
        </p>
      ) : null}
    </div>
  );
}

"use client";

import { BarChart } from "@/components/arc/bar-chart";
import type { RidgeSeries } from "@/components/arc/ridgeline";
import { formatCount } from "@/components/ui";
import type { Durations } from "@/lib/api/analytics";
import type { Performance } from "@/lib/api/performance";
import { endingLabel } from "@/lib/callReview";

import { outcomeFill } from "../OutcomeSplit";
import { callersWord, useBusinessCapabilities } from "@/lib/businessCapabilities";

import { PERFORMANCE_COPY as COPY, funnelTitle } from "./copy";

/**
 * How the report's server figures become chart props. One subject: how the numbers are
 * DRAWN, kept out of the screen that decides which period to ask for.
 */

/** What each panel's figures mean, behind the panel's ⓘ. */
export const FUNNEL_NOTE =
  "Answered means the call reached a real conversation — not voicemail or a missed call. " +
  "Interested counts people, not calls: three calls to the same person count once.";
export const OUTCOMES_NOTE =
  "The tag your agent recorded, or how the call ended when it recorded none.";
export const HEATMAP_NOTE =
  "Each square counts what started in that hour on that day of the week, Indian Standard Time.";
export const DURATIONS_NOTE =
  "Completed calls only. Typical length is the middle call, marked by the tick: half were " +
  "shorter, half longer. Most calls under: 9 in 10 calls were shorter than this. The " +
  "right-hand edge holds every call that ran longer.";
/** The ridgeline's headings for the median and the 90th percentile, as `DURATIONS_NOTE` defines them. */
export const TYPICAL_LENGTH = "Typical length";
export const MOST_CALLS_UNDER = "Most calls under";

/** Said, rather than left for the reader to notice numbers moving under them. */
export function Updating({ busy }: { busy: boolean }) {
  if (!busy) return null;
  return (
    <span role="status" className="text-meta text-ink-faint">
      Updating…
    </span>
  );
}

/** Calls → answered → interested, each a bar against the top of the funnel. */
export function Funnel({ funnel, period }: { funnel: Performance["funnel"]; period: string }) {
  const callers = callersWord(useBusinessCapabilities(), "customers");
  const stages = [
    { label: "Calls", count: funnel.calls },
    { label: "Answered", count: funnel.connected },
    { label: "Interested", count: funnel.qualified },
  ];
  return (
    <BarChart
      title={funnelTitle(callers)}
      hideTitle
      description={period}
      orientation="horizontal"
      showValues
      labelColumn="Stage"
      categories={stages.map((stage) => stage.label)}
      series={[
        {
          label: "Count",
          values: stages.map((stage) => stage.count),
          display: stages.map((stage) => formatCount(stage.count)),
        },
      ]}
      empty={COPY.funnelEmpty}
    />
  );
}

/** Outcome → count, busiest first. */
export function Outcomes({ outcomes, period }: { outcomes: Record<string, number>; period: string }) {
  const rows = Object.entries(outcomes)
    .filter(([, count]) => count > 0)
    .sort(([, a], [, b]) => b - a);
  return (
    <BarChart
      title={COPY.outcomesTitle}
      hideTitle
      description={period}
      orientation="horizontal"
      showValues
      labelColumn="Outcome"
      categories={rows.map(([outcome]) => endingLabel(outcome))}
      categoryFills={rows.map(([outcome]) => outcomeFill(outcome))}
      series={[
        {
          label: "Calls",
          values: rows.map(([, count]) => count),
          display: rows.map(([, count]) => formatCount(count)),
        },
      ]}
      empty={COPY.outcomesEmpty}
    />
  );
}

/**
 * The most calls a row is redrawn from. The server sends counts per bin; the ridgeline
 * smooths a sample, and a year of calls expanded one value per call would make the
 * smoothing cost scale with the account's size. Above this the bins are scaled down in
 * proportion (a non-empty bin keeps at least one point), which keeps the shape, while the
 * median, 90th percentile and count shown are always the server's exact figures.
 */
const DRAWN_PER_ROW = 1500;

/** The durations read as ridgeline rows: one point per call at its bin's middle. */
export function durationRows(data: Durations): RidgeSeries[] {
  const half = data.bin_s / 2;
  return data.groups.map((group) => {
    const scale = group.calls > DRAWN_PER_ROW ? DRAWN_PER_ROW / group.calls : 1;
    const values: number[] = [];
    group.counts.forEach((count, i) => {
      const drawn = count === 0 ? 0 : Math.max(1, Math.round(count * scale));
      const at = (data.bin_edges_s[i] ?? i * data.bin_s) + half;
      for (let k = 0; k < drawn; k += 1) values.push(at);
    });
    // An outcome arrives as its key; the words are the call log's.
    const label = data.group_by === "outcome" ? endingLabel(group.key) : group.label;
    return { label, values, median: group.median_s, p90: group.p90_s, count: group.calls };
  });
}

/** Where the shared axis ends: the top of the last, open-ended bin. */
export function durationAxisEnd(data: Durations): number {
  const last = data.bin_edges_s[data.bin_edges_s.length - 1] ?? 0;
  return last + data.bin_s;
}

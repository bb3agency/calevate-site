"use client";

import { BarChart } from "@/components/arc/bar-chart";
import { Section } from "@/components/console/section";
import { formatCount } from "@/components/ui";

/** "needs_follow_up" → "Needs follow up", the words the call log's outcome tag prints. */
export function outcomeWords(outcome: string): string {
  const words = outcome.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * HOW CALLS ENDED, last 7 days — the dashboard's split (founder, REDESIGN-2: one
 * calls-per-day chart and one outcome split). A ranked horizontal bar list, longest first,
 * each bar with its count at the tip, so it reads without a legend. The keys are the
 * server's tags (`booked`, `needs_follow_up` …).
 */
export function OutcomeSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  return (
    <Section title="How calls ended">
      <BarChart
        title="How calls ended"
        hideTitle
        description="Last 7 days"
        orientation="horizontal"
        showValues
        labelColumn="Outcome"
        categories={rows.map(([outcome]) => outcomeWords(outcome))}
        series={[
          { label: "Calls", values: rows.map(([, count]) => count), display: rows.map(([, count]) => formatCount(count)) },
        ]}
        empty="No outcomes recorded in the last 7 days yet."
      />
    </Section>
  );
}

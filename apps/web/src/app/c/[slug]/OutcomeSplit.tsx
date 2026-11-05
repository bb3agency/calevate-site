"use client";

import { BarChart } from "@/components/arc/bar-chart";
import { Section } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import { OUTCOME_ORDER, callOutcome, endingLabel } from "@/lib/callReview";

import { OUTCOME_DOT } from "./calls/callColumns";

/** "needs_follow_up" → "Needs follow up": a server key in sentence case. */
export function outcomeWords(outcome: string): string {
  const words = outcome.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * The call log's dot colour for a call that ended with this key, so both screens agree. A
 * key that is not an outcome tag is a call status (`COALESCE(outcome_tag, status)`).
 */
export function outcomeFill(key: string): string {
  const tag = OUTCOME_ORDER.find((known) => known === key);
  const call: Parameters<typeof callOutcome>[0] = tag
    ? { status: "completed", outcome_tag: tag, summary_state: "ready" }
    : { status: key, outcome_tag: null, summary_state: "ready" };
  return OUTCOME_DOT[callOutcome(call).kind];
}

/**
 * HOW CALLS ENDED, last 7 days — the dashboard's split (founder, REDESIGN-2: one
 * calls-per-day chart and one outcome split). A ranked horizontal bar list, longest first,
 * each bar with its count at the tip, so it reads without a legend. The keys are the
 * server's tags (`call_back_booked`, `missed` …), named and coloured as the call log names
 * and colours them, so "Missed" is the same word and the same red on both screens.
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
        categories={rows.map(([outcome]) => endingLabel(outcome))}
        categoryFills={rows.map(([outcome]) => outcomeFill(outcome))}
        series={[
          { label: "Calls", values: rows.map(([, count]) => count), display: rows.map(([, count]) => formatCount(count)) },
        ]}
        empty="No outcomes recorded in the last 7 days yet."
      />
    </Section>
  );
}

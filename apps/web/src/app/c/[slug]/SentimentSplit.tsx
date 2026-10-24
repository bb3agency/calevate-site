"use client";

import { DonutChart } from "@/components/arc/donut-chart";
import { formatCount } from "@/components/ui";

import { outcomeWords } from "./OutcomeSplit";

/**
 * HOW CALLERS SOUNDED in the last 7 days: the counts the server scored, as parts of the
 * calls it scored. Nothing guessed: with nothing scored the chart says so.
 */
export function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  return (
    <DonutChart
      title="How callers sounded"
      hideTitle
      description="Calls we rated in the last 7 days"
      labelColumn="Caller mood"
      segments={rows.map(([mood, count]) => ({ label: outcomeWords(mood), value: count }))}
      centerValue={formatCount(total)}
      centerLabel={total === 1 ? "call rated" : "calls rated"}
      size={140}
      empty="We haven't rated how callers sounded in the last 7 days yet."
    />
  );
}

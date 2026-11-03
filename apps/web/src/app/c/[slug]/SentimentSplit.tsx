"use client";

import { DonutChart } from "@/components/arc/donut-chart";
import { formatCount } from "@/components/ui";

import { lookup } from "@/lib/lookup";

import { outcomeWords } from "./OutcomeSplit";

/**
 * Each mood in the colour of what it means, whichever is largest this week: green for
 * pleased (the brand's own good news), grey for neutral, red for upset. By rank, the
 * series palette would paint "Negative" green in a week when most callers were unhappy.
 * Grey is the faint ink, not the chart's pale slate, which is 1.5:1 on white.
 */
const MOOD_COLOR: Record<string, string> = {
  positive: "var(--series-1)",
  neutral: "var(--text-faint)",
  negative: "var(--chart-danger)",
};

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
      segments={rows.map(([mood, count]) => ({ label: outcomeWords(mood), value: count, color: lookup(MOOD_COLOR, mood) }))}
      centerValue={formatCount(total)}
      centerLabel={total === 1 ? "call rated" : "calls rated"}
      size={140}
      empty="No calls rated in the last 7 days."
    />
  );
}

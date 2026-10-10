"use client";

import { formatCount } from "@/components/ui";

/**
 * HOW CALLERS SOUNDED, as plain numbers (founder, REDESIGN-2: the dashboard keeps one
 * split chart, and that is how calls ended). The counts the server scored, one line,
 * nothing guessed: an empty split says so rather than showing zeros.
 */
export function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split).filter(([, count]) => count > 0);
  if (rows.length === 0) {
    return <p className="text-meta text-ink-muted">We haven&apos;t rated how callers sounded in the last 7 days yet.</p>;
  }
  return (
    <p className="text-meta text-ink-muted">
      Callers sounded{" "}
      {rows.map(([mood, count], i) => (
        <span key={mood}>
          {i > 0 ? " · " : ""}
          <span className="font-semibold tabular-nums text-ink">{formatCount(count)}</span> {mood}
        </span>
      ))}
    </p>
  );
}

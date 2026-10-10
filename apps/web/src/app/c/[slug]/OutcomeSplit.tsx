"use client";

import { Section } from "@/components/console/section";
import { formatCount } from "@/components/ui";

/**
 * HOW CALLS ENDED, last 7 days — the dashboard's one split chart (founder, REDESIGN-2:
 * one calls-per-day chart and one outcome split; everything else a plain number).
 *
 * Horizontal bars in one colour, longest first, each labelled with its words and its count,
 * so the chart reads without a legend and the bar only adds the proportion. The outcome
 * keys are the server's tags (`booked`, `needs_follow_up` …) shown in sentence case, the
 * same words the call log's outcome tag prints.
 */
export function OutcomeSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const top = rows[0]?.[1] ?? 0;
  return (
    <Section title="How calls ended">
      {rows.length === 0 ? (
        <p className="text-meta text-ink-muted">No outcomes recorded in the last 7 days yet.</p>
      ) : (
        <ul className="space-y-3" aria-label="How calls ended, last 7 days">
          {rows.map(([outcome, count]) => {
            const words = outcome.replace(/_/g, " ");
            return (
              <li key={outcome}>
                <div className="flex items-baseline justify-between gap-3 text-meta">
                  <span className="text-ink">{words.charAt(0).toUpperCase() + words.slice(1)}</span>
                  <span className="font-semibold tabular-nums text-ink">{formatCount(count)}</span>
                </div>
                <div aria-hidden className="mt-1 h-1.5 rounded-full bg-ink/[0.05]">
                  <div
                    className="h-1.5 rounded-full bg-brand"
                    style={{ width: `${top === 0 ? 0 : Math.max(4, Math.round((count / top) * 100))}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

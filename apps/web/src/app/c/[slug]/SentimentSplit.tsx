"use client";

import { Section } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import { lookup } from "@/lib/lookup";

const SENTIMENT_TONES: Record<string, string> = {
  positive: "bg-brand",
  neutral: "bg-chart-neutral",
  negative: "bg-chart-danger",
};
const FALLBACK = "bg-ink/40";

/**
 * How callers sounded over the last 7 days — one bar split by the server's counts, with
 * each count printed beside its label so nothing depends on reading the colours.
 */
export function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  return (
    <Section title="How callers sounded">
      {total === 0 ? (
        <p className="text-[13px] text-ink-muted">
          We haven&apos;t rated any calls in the last 7 days yet.
        </p>
      ) : (
        <div className="space-y-3">
          <div aria-hidden className="flex h-2 gap-0.5 overflow-hidden rounded-full">
            {rows.map(([mood, count]) => (
              <span
                key={mood}
                className={lookup(SENTIMENT_TONES, mood) ?? FALLBACK}
                style={{ flexGrow: count, flexBasis: 0 }}
              />
            ))}
          </div>
          <ul className="space-y-1.5">
            {rows.map(([mood, count]) => (
              <li key={mood} className="flex items-center gap-2.5 text-[13px]">
                {/* `lookup`: `mood` is a server-chosen string (src/lib/lookup.ts). */}
                <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${lookup(SENTIMENT_TONES, mood) ?? FALLBACK}`} />
                <span className="flex-1 capitalize text-ink-muted">{mood}</span>
                <span className="font-semibold tabular-nums text-ink">{formatCount(count)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}

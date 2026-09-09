"use client";

import { Card, formatCount } from "@/components/ui";
import { lookup } from "@/lib/lookup";

const SENTIMENT_TONES: Record<string, string> = {
  positive: "bg-brand",
  neutral: "bg-slate-300 dark:bg-slate-600",
  negative: "bg-rose-500",
};

export function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  return (
    <Card title="How callers sounded" bodyClassName="p-4 sm:p-5">
      {total === 0 ? (
        <p className="text-[13px] text-ink-muted">
          We haven&apos;t rated any calls in the last 7 days yet.
        </p>
      ) : (
        <div className="space-y-2">
          {rows.map(([mood, count]) => (
            <div key={mood} className="flex items-center gap-3">
              {/* `lookup`, not `SENTIMENT_TONES[mood]`: `mood` is a server-chosen
                  string, and a bare index reaches Object.prototype (src/lib/lookup.ts).
                  The type-aware guard in tests/wireLookupGuard.test.ts failed this line
                  as written, which is the guard doing its job on new code. */}
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${lookup(SENTIMENT_TONES, mood) ?? "bg-slate-300"}`}
              />
              <span className="flex-1 text-[13px] capitalize text-ink-muted">
                {mood}
              </span>
              <span className="text-[13px] font-semibold tabular-nums text-ink">
                {formatCount(count)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

"use client";

import { Sparkline } from "@/components/arc/sparkline";
import { formatCount } from "@/components/ui";
import { useLastHour, type AnalyticsRange } from "@/lib/api/analytics";
import type { Session } from "@/lib/api/client";

export const LAST_HOUR_COPY = {
  live: (n: number) => `${formatCount(n)} on a call now`,
  hour: (n: number) => `${formatCount(n)} ${n === 1 ? "call" : "calls"} in the last hour`,
  line: "Calls in each five minutes of the last hour",
} as const;

/**
 * "Last hour" (W8.2): drawn only while a call is live, so a quiet evening shows nothing
 * rather than a flat line. Polled every 30 s by `useLastHour`; follows the page's agent,
 * campaign or line, and direction, and never counts the owner's own test calls.
 */
export function LastHour({ session, range }: { session: Session; range: AnalyticsRange }) {
  const hour = useLastHour(session, range);
  const data = hour.data;
  if (!data || data.live_now === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card border border-line px-4 py-3" aria-live="polite">
      <p className="text-sm font-semibold text-ink">{LAST_HOUR_COPY.live(data.live_now)}</p>
      <p className="text-meta text-ink-muted">{LAST_HOUR_COPY.hour(data.calls)}</p>
      <Sparkline
        values={data.slots.map((slot) => slot.calls)}
        label={LAST_HOUR_COPY.line}
        tone="neutral"
        className="h-7 w-32"
      />
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";

import { formatDuration } from "@/components/ui";

import { LiveDot } from "./liveCalls";

/** Whole seconds since `startedAt`, ticking once a second while mounted. */
function useElapsedSeconds(startedAt: string | null | undefined): number | null {
  const started = startedAt ? Date.parse(startedAt) : Number.NaN;
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (now === null || Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((now - started) / 1000));
}

/**
 * A CALL THAT IS HAPPENING NOW — shown at the top of a call's screen while its status is
 * `in_progress`.
 *
 * The elapsed time is counted in the browser from the server's `started_at`; it renders
 * nothing until mounted so the server and first client render agree. The figure is
 * not announced (it changes every second); the "Live" heading is.
 */
export function LiveCallPanel({
  startedAt,
  agentName,
}: {
  startedAt: string | null | undefined;
  agentName: string | null;
}) {
  const elapsed = useElapsedSeconds(startedAt);
  return (
    <section
      aria-labelledby="live-call-heading"
      className="rounded-card border border-line bg-surface p-4 sm:p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="live-call-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
          <LiveDot />
          Live call{agentName ? ` with ${agentName}` : ""}
        </h2>
        {elapsed !== null && (
          <span className="text-[13px] tabular-nums text-ink-muted">
            <span className="sr-only">Running for </span>
            {formatDuration(elapsed)}
          </span>
        )}
      </div>
    </section>
  );
}

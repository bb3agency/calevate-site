"use client";

/**
 * LIVE ROWS IN THE CALL LOG (D-886). A call has its row from the moment it is dialled; while
 * it runs the row says so in words ("Live", "Ringing…", "On the call", "Call in progress"),
 * counts its length up from when the person picked up, and carries a slow sheen. When the
 * call ends the same row turns into the ended call in place.
 *
 * What a live row reads from: the log's own `live_state` (the server's verdict, with the
 * stale bound) and, for an outbound call whose row is silent until the end, the engine's
 * status from `GET /v1/calls/live`.
 */

import { useEffect, useState } from "react";

import { formatDuration } from "@/components/ui";
import type { CallSummary } from "@/lib/api/client";
import type { CallLive } from "@/lib/api/liveCalls";

/** How a running call reads right now. */
export type LiveView = {
  /** `live` while it runs; `unreported` once it has run past the longest a call can with no end heard. */
  state: "live" | "unreported";
  status: string;
  /** When the person picked up, if they have; the length counts from here. */
  startedAt: string | null;
};

/**
 * A row of the log. `live` is set while the call runs or its end is overdue; `opens` is
 * false while the call's own page would have nothing true to say (a call still ringing,
 * or one whose details have not arrived), so the row is not a link until then.
 */
export type LogCall = CallSummary & { live?: LiveView | null; opens?: boolean };

/** Rows still ringing or dialling on OUR row have no call page to show yet. */
const SILENT_ROW = new Set(["queued", "ringing"]);

const TERMINAL = new Set(["completed", "failed", "no_answer", "busy", "voicemail"]);

/** The rows the live read should ask about: the ones the server calls live. */
export function liveIds(rows: readonly CallSummary[]): string[] {
  return rows.filter((call) => call.live_state === "live").map((call) => call.id);
}

/**
 * Each row as the log shows it, with the live read laid over the ones still running. A
 * live read that has heard the end before our row has (`live_state` null with an ended
 * status) shows the ended status at once; the row's own details follow when the log
 * re-reads it.
 */
export function withLive(rows: readonly CallSummary[], reads: readonly CallLive[] | undefined): LogCall[] {
  const byId = new Map((reads ?? []).map((read) => [read.id, read]));
  return rows.map((call) => {
    const silent = SILENT_ROW.has(call.status);
    if (!call.live_state) return call;
    if (call.live_state === "unreported") {
      return { ...call, live: { state: "unreported", status: call.status, startedAt: call.started_at ?? null }, opens: !silent };
    }
    const read = byId.get(call.id);
    if (read && read.live_state !== "live" && TERMINAL.has(read.status)) {
      return { ...call, status: read.status, live_state: null, live: null, opens: false };
    }
    if (read?.live_state === "unreported") {
      return { ...call, live: { state: "unreported", status: read.status, startedAt: read.started_at ?? null }, opens: !silent };
    }
    const status = read?.status ?? call.status;
    const startedAt = read?.started_at ?? call.started_at ?? null;
    return { ...call, live: { state: "live", status, startedAt }, opens: !silent };
  });
}

/**
 * Reads that say a call is no longer running: it ended, or ran past the longest a call can.
 * The log keeps them (so the row stays ended while the log re-reads), stops asking about
 * those ids, and re-reads the log once for each.
 */
export function endedReads(reads: readonly CallLive[] | undefined): CallLive[] {
  return (reads ?? []).filter((read) => read.live_state !== "live");
}

/** The outcome cell's words while the call runs. */
export function liveWords(live: LiveView): string {
  if (live.state === "unreported") return "Ended — details coming";
  if (live.status === "in_progress") return "On the call";
  if (live.status === "ringing") return "Ringing…";
  return "Dialling…";
}

/** The second line of a live row. */
export function liveLine(live: LiveView): string {
  return live.state === "unreported" ? "Details are on their way" : "Call in progress";
}

/** Seconds since `from`, never negative (a clock a little behind the server's). */
function secondsSince(from: string, now: number): number | null {
  const at = Date.parse(from);
  return Number.isFinite(at) ? Math.max(0, Math.floor((now - at) / 1000)) : null;
}

/**
 * How long the call has run, counting up once a second from when it was answered; a dash
 * before that. A number changing is not motion, so it counts under reduced motion too.
 */
export function LiveLength({ startedAt }: { startedAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  return <>{startedAt ? formatDuration(secondsSince(startedAt, now)) : "—"}</>;
}

/** "Live", said in words beside the pulsing dot, so the row reads without the motion. */
export function LiveMark() {
  return (
    <span className="shrink-0 whitespace-nowrap text-meta font-medium text-brand-strong dark:text-brand-bright">Live</span>
  );
}

/**
 * A slow band of light crossing the whole row while the call runs. It is a child of the
 * row's first cell positioned against the row (`relative isolate` on the row), behind the
 * row's content, and moves on transform alone. Reduced motion and forced colours draw
 * nothing; the "Live" mark and the words carry the state.
 */
export function LiveSheen() {
  return (
    <span aria-hidden data-live-sheen className="pointer-events-none absolute inset-0 z-below overflow-hidden">
      <span className="live-sheen absolute inset-y-0 -left-1/2 w-1/2" />
    </span>
  );
}

"use client";

import Link from "next/link";

import { formatDuration, formatIST, formatPhone } from "@/components/ui";
import type { DataColumn } from "@/components/console/dataTable";
import { LIVE_STATUS, LiveDot } from "@/components/console/liveCalls";
import type { CallSummary } from "@/lib/api/client";
import { callResultWords, callRowLine, callTitle, callbackOverdue, needsAttention } from "@/lib/callReview";

export function isLive(call: Pick<CallSummary, "status">): boolean {
  return call.status === LIVE_STATUS;
}

/**
 * How a call ended, as words. Plain ink for everything except the two things that ask
 * the owner to act — "Needs you" and a call back that is late — which take the warning
 * tone. No pill: in a list of calls the words are the fact, and a coloured chip on every
 * row would make every row shout.
 */
export function CallResult({
  call,
}: {
  call: Pick<CallSummary, "status" | "outcome_tag" | "callback" | "summary_state">;
}) {
  const overdue = callbackOverdue(call.callback);
  const warn = needsAttention(call);
  return (
    <span className={`whitespace-nowrap text-meta ${warn ? "font-medium text-warn" : "text-ink-muted"}`}>
      {overdue ? "Call back overdue" : callResultWords(call)}
    </span>
  );
}

/** A free-trial test call, said once beside the caller so it is never mistaken for a lead. */
export function TestCallTag() {
  return (
    <span className="shrink-0 whitespace-nowrap rounded-full bg-ink/[0.05] px-2 py-px text-meta text-ink-muted">
      Test call
    </span>
  );
}

/** How the caller sounded, in a word; a dash until the call has been read. */
export function sentimentWord(value: string | null | undefined): string {
  if (!value) return "—";
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");
}

/**
 * The columns of a call row, shared by the call log and the dashboard's latest calls so
 * the two read a call the same way.
 *
 * The row says WHO (the lead's name, or the number when there is none), WHAT the call was
 * about (the one-line headline written after the call, never the last thing said), how it
 * ENDED, how LONG and WHEN. The number is printed in full (D-436) and is never in an
 * `href`; the row's one link carries the call id. Below `md` the result, length and time
 * fold under the headline, so a phone reads a row as three short lines and never scrolls
 * sideways.
 */
export function callColumns({
  callHref,
  compact = false,
}: {
  callHref: (id: string) => string;
  /** The dashboard's short list: adds how the caller sounded, no sorting. */
  compact?: boolean;
}): DataColumn<CallSummary>[] {
  const caller: DataColumn<CallSummary> = {
    id: "caller",
    header: "Caller",
    className: "max-w-0 w-full",
    cell: (call) => {
      const line = callRowLine(call);
      const named = Boolean(call.lead_name?.trim());
      return (
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            {isLive(call) && <LiveDot />}
            <Link
              href={callHref(call.id)}
              className="truncate rounded-sm font-medium text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
            >
              {callTitle(call)}
            </Link>
            {named && call.caller_e164 && (
              <span className="hidden whitespace-nowrap text-meta tabular-nums text-ink-faint sm:inline">
                {formatPhone(call.caller_e164)}
              </span>
            )}
            {call.test_call && <TestCallTag />}
          </div>
          <p
            title={line.pending ? undefined : line.text}
            className={`mt-0.5 truncate text-meta ${line.pending ? "italic text-ink-faint" : "text-ink-muted"}`}
          >
            {line.text}
          </p>
          <p className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-meta text-ink-faint md:hidden">
            <CallResult call={call} />
            <span aria-hidden>·</span>
            <span className="tabular-nums">{formatDuration(call.duration_s)}</span>
            <span aria-hidden>·</span>
            <span className="tabular-nums">{formatIST(call.started_at)}</span>
          </p>
        </div>
      );
    },
  };
  const result: DataColumn<CallSummary> = {
    id: "status",
    header: "Outcome",
    hideBelow: "md",
    flash: (call) => `${call.status}|${call.outcome_tag ?? ""}|${call.callback?.status ?? ""}`,
    sort: compact ? undefined : { value: (call) => callResultWords(call) },
    cell: (call) => <CallResult call={call} />,
  };
  const duration: DataColumn<CallSummary> = {
    id: "duration",
    header: "Length",
    align: "right",
    hideBelow: "md",
    flash: (call) => (call.duration_s === null ? null : String(call.duration_s)),
    sort: compact ? undefined : { value: (call) => call.duration_s, kind: "number", first: "desc" },
    cell: (call) => (
      <span className="whitespace-nowrap text-meta tabular-nums text-ink-muted">
        {formatDuration(call.duration_s)}
      </span>
    ),
  };
  const started: DataColumn<CallSummary> = {
    id: "started",
    header: "When",
    align: "right",
    hideBelow: "md",
    sort: compact ? undefined : { value: (call) => call.started_at, kind: "time", first: "desc" },
    cell: (call) => (
      <span className="whitespace-nowrap text-meta tabular-nums text-ink-faint">
        {formatIST(call.started_at)}
      </span>
    ),
  };
  const sentiment: DataColumn<CallSummary> = {
    id: "sentiment",
    header: "Caller sounded",
    hideBelow: "md",
    cell: (call) => (
      <span className="whitespace-nowrap text-meta text-ink-muted">{sentimentWord(call.sentiment)}</span>
    ),
  };
  return compact ? [caller, result, sentiment, duration, started] : [caller, result, duration, started];
}

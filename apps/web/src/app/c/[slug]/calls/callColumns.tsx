"use client";

import Link from "next/link";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";

import { StatusBadge, formatDuration, formatIST } from "@/components/ui";
import type { DataColumn } from "@/components/console/dataTable";
import { LIVE_STATUS, LiveDot } from "@/components/console/liveCalls";
import type { CallSummary } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

export function isLive(call: CallSummary): boolean {
  return call.status === LIVE_STATUS;
}

function Direction({ value }: { value: string }) {
  const Icon = value === "outbound" ? ArrowUpRight : ArrowDownLeft;
  return (
    <span className="inline-flex items-center gap-1 capitalize">
      <Icon aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
      {value}
    </span>
  );
}

/** Outcomes that ask the owner to do something wear the warning tone. */
const OUTCOME_TONES: Record<string, string> = {
  needs_follow_up: "bg-warn-soft text-warn",
  transferred: "bg-ink/[0.05] text-ink-muted",
  dropped: "bg-ink/[0.05] text-ink-muted",
};

export function OutcomeTag({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const words = value.replace(/_/g, " ");
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-medium ${
        lookup(OUTCOME_TONES, value) ?? "bg-brand-soft text-brand-strong"
      }`}
    >
      {words.charAt(0).toUpperCase() + words.slice(1)}
    </span>
  );
}

/**
 * How a call ended, in one chip or two. A completed call is described by its outcome
 * ("Resolved"); any other status is itself the fact worth reading.
 */
export function CallState({ call }: { call: Pick<CallSummary, "status" | "outcome_tag"> }) {
  if (call.status === "completed" && call.outcome_tag) return <OutcomeTag value={call.outcome_tag} />;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <StatusBadge value={call.status} kind="call" />
      <OutcomeTag value={call.outcome_tag} />
    </span>
  );
}

/**
 * The columns of a call row, shared by the call log and the dashboard's latest calls so
 * the two read the same call the same way.
 *
 * The number is printed IN FULL (D-436) and is the row's one link, stretched over the
 * whole row; the URL carries the call id and never the number (hard rule 6). The summary
 * is the API's redacted text. Below `md` the status, agent and time fold under the
 * number, so a phone reads one row as two short lines rather than a scrolling table.
 */
export function callColumns({
  callHref,
  compact = false,
}: {
  callHref: (id: string) => string;
  /** The dashboard's short list: no agent or direction column, no sorting. */
  compact?: boolean;
}): DataColumn<CallSummary>[] {
  const caller: DataColumn<CallSummary> = {
    id: "caller",
    header: "Caller",
    className: "max-w-0 w-full",
    cell: (call) => (
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {isLive(call) && <LiveDot />}
          <Link
            href={callHref(call.id)}
            className="whitespace-nowrap rounded-sm font-medium tabular-nums text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
          >
            {call.caller_e164 ?? "Unknown number"}
          </Link>
          <span className="md:hidden">
            <CallState call={call} />
          </span>
        </div>
        <p title={call.summary ?? undefined} className="mt-0.5 truncate text-[13px] text-ink-muted">
          {call.summary ?? (isLive(call) ? "On the line now" : "No summary yet")}
        </p>
        <p className="mt-0.5 truncate text-[12px] text-ink-faint md:hidden">
          {call.agent_name ?? "—"} · {formatDuration(call.duration_s)} · {formatIST(call.started_at)}
        </p>
      </div>
    ),
  };
  const status: DataColumn<CallSummary> = {
    id: "status",
    header: "Outcome",
    hideBelow: "md",
    flash: (call) => `${call.status}|${call.outcome_tag ?? ""}`,
    sort: compact ? undefined : { value: (call) => call.status },
    cell: (call) => <CallState call={call} />,
  };
  const agent: DataColumn<CallSummary> = {
    id: "agent",
    header: "Agent",
    hideBelow: "lg",
    sort: { value: (call) => call.agent_name },
    cell: (call) => (
      <span className="whitespace-nowrap text-[13px] text-ink-muted">
        {call.agent_name ?? "—"}
        <span className="block text-[12px] text-ink-faint">
          <Direction value={call.direction} />
        </span>
      </span>
    ),
  };
  const duration: DataColumn<CallSummary> = {
    id: "duration",
    header: "Length",
    align: "right",
    hideBelow: "md",
    flash: (call) => (call.duration_s === null ? null : String(call.duration_s)),
    sort: compact ? undefined : { value: (call) => call.duration_s, kind: "number", first: "desc" },
    cell: (call) => (
      <span className="whitespace-nowrap text-[13px] tabular-nums text-ink-muted">
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
      <span className="whitespace-nowrap text-[13px] tabular-nums text-ink-faint">
        {formatIST(call.started_at)}
      </span>
    ),
  };
  return compact ? [caller, status, duration, started] : [caller, status, agent, duration, started];
}

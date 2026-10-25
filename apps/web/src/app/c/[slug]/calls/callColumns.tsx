"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { CircleAlert, CircleCheck } from "lucide-react";

import { HoverCard } from "@/components/arc/hover-card";

import { formatDuration, formatINR, formatIST, formatPhone } from "@/components/ui";
import type { DataColumn } from "@/components/console/dataTable";
import { LIVE_STATUS, LiveDot } from "@/components/console/liveCalls";
import { NOTICE_DOT } from "@/components/console/statusPill";
import type { CallSummary } from "@/lib/api/client";
import { type OutcomeKind, callOutcome, callRowLine, callTitle, callbackOverdue } from "@/lib/callReview";

export function isLive(call: Pick<CallSummary, "status">): boolean {
  return call.status === LIVE_STATUS;
}

/**
 * The mark for each kind of ending, from the kit's status dots so "good" and "stopped" read
 * the same here as on every other state in the console. Calls add one kind the kit has no
 * tone for, a follow-up that is arranged, and it takes the charts' blue (`--series-2`)
 * because brand green already means a likely lead.
 */
export const OUTCOME_DOT: Record<OutcomeKind, string> = {
  lead: NOTICE_DOT.ok,
  follow_up: "bg-series-2",
  neutral: NOTICE_DOT.neutral,
  caution: NOTICE_DOT.warn,
  failed: NOTICE_DOT.stop,
};

type OutcomeCall = Pick<
  CallSummary,
  "status" | "outcome_tag" | "summary_state" | "business_outcome" | "business_outcome_label" | "business_outcome_lead_status"
>;

/** The kind-of-ending dot alone, for a line that already says the outcome in words. */
export function OutcomeDot({ kind }: { kind: OutcomeKind }) {
  return <span aria-hidden data-kind={kind} className={`size-1.5 shrink-0 rounded-full ${OUTCOME_DOT[kind]}`} />;
}

/**
 * How a call ended: a small dot for the kind of ending (`callOutcome`) and the words. The
 * words are the fact and the dot is a mark beside them, so a scan down the list finds the
 * likely leads by colour while every row still reads without it.
 *
 * A dot rather than a filled pill per row: forty tinted capsules make every row equally
 * loud and read as buttons (the reason `StatusPill` dropped its capsule, D-771). The words
 * stay in muted ink; urgency is said once, by `NeedsYouMark`, never by the outcome.
 */
export function CallResult({
  call,
  truncate = false,
}: {
  call: OutcomeCall;
  /** Cut long words with an ellipsis (the phone list's narrow right column); else never wrap. */
  truncate?: boolean;
}) {
  const { words, kind } = callOutcome(call);
  return (
    <span className={`inline-flex items-center gap-1.5 text-meta text-ink-muted ${truncate ? "min-w-0 max-w-full" : ""}`}>
      <OutcomeDot kind={kind} />
      <span className={truncate ? "truncate" : "whitespace-nowrap"}>{words}</span>
    </span>
  );
}

/**
 * The request for a person, said beside the outcome rather than in its place: the server's
 * "needs you", or a booked call back that is now late. A person's own mark on the call
 * (`FollowUpMark`) is the later word, so once someone has marked it the server's "needs
 * you" is not repeated; a late call back is still said, because the mark does not ring
 * anyone.
 */
export function NeedsYouMark({
  call,
}: {
  call: Pick<CallSummary, "outcome_tag" | "callback" | "follow_up_state">;
}) {
  const overdue = callbackOverdue(call.callback);
  const asked = call.outcome_tag === "needs_you" && !call.follow_up_state;
  if (!overdue && !asked) return null;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap text-meta font-medium text-warn">
      <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {overdue ? "Call back overdue" : "Needs you"}
    </span>
  );
}

/**
 * A PERSON'S MARK on the call (D-869), said apart from how the call ended: the outcome is
 * what happened on the line, the mark is what the team decided about it afterwards.
 */
export function FollowUpMark({ state }: { state: string | null | undefined }) {
  if (state === "resolved") {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap text-meta text-ink-muted">
        <CircleCheck aria-hidden className="h-3.5 w-3.5 shrink-0 text-brand-strong" />
        Marked done
      </span>
    );
  }
  if (state === "needs_you") {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap text-meta font-medium text-warn">
        <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" />
        Marked: needs you
      </span>
    );
  }
  return null;
}

/**
 * What a resting pointer sees of a call before opening it. Read-only, and every fact here
 * is also on the call's own screen: a preview is never the only place something is said.
 */
export function CallPreview({ call }: { call: CallSummary }) {
  const line = callRowLine(call);
  const chips = call.captured_preview ?? [];
  return (
    <div className="space-y-2">
      <div>
        <p className="font-semibold text-ink">{callTitle(call)}</p>
        {call.lead_name?.trim() && call.caller_e164 ? (
          <p className="tabular-nums text-ink-muted">{formatPhone(call.caller_e164)}</p>
        ) : null}
      </div>
      <p className={line.pending ? "italic text-ink-faint" : "text-ink"}>{line.text}</p>
      {chips.length > 0 ? (
        <dl className="space-y-0.5">
          {chips.map((chip) => (
            <div key={chip.label} className="flex gap-1.5">
              <dt className="shrink-0 text-ink-muted">{chip.label}:</dt>
              <dd className="min-w-0 break-words">{chip.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p className="text-ink-muted">
        {[call.direction === "outbound" ? "Outgoing" : "Incoming", call.agent_name ?? null, formatIST(call.started_at)]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <FollowUpMark state={call.follow_up_state} />
    </div>
  );
}

/** A free-trial test call, said once beside the caller so it is never mistaken for a lead. */
export function TestCallTag() {
  return (
    <span className="shrink-0 whitespace-nowrap text-meta text-ink-muted">
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
/**
 * The details the caller gave, as one quiet line ("What they want: rice · Preferred time:
 * Saturday"). Plain text rather than chips: a row of pills on every call would shout, and
 * the line is there to be glanced at. The server picks at most three and never a number.
 */
export function CapturedLine({ call }: { call: Pick<CallSummary, "captured_preview"> }) {
  const chips = call.captured_preview ?? [];
  if (!chips.length) return null;
  const text = chips.map((chip) => `${chip.label}: ${chip.value}`).join(" · ");
  return (
    <p title={text} className="mt-0.5 truncate text-meta text-ink-faint">
      {text}
    </p>
  );
}

export function callColumns({
  callHref,
  compact = false,
  showCost = false,
  menu,
}: {
  callHref: (id: string) => string;
  /** The dashboard's short list: adds how the caller sounded and what was captured, no sorting. */
  compact?: boolean;
  /** Adds what each call took from the credit balance. The server sends it only to a role
   * that may see billing, so the caller passes whether any row carries it. */
  showCost?: boolean;
  /** The row's ⋯ menu (the call log's follow-up actions), as a last column. */
  menu?: (call: CallSummary) => ReactNode;
}): DataColumn<CallSummary>[] {
  const caller: DataColumn<CallSummary> = {
    id: "caller",
    header: "Caller",
    className: "max-w-0 w-full",
    cell: (call) => {
      const line = callRowLine(call);
      const named = Boolean(call.lead_name?.trim());
      const rowLink = (
        <Link
          href={callHref(call.id)}
          className="truncate rounded-sm font-medium text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
        >
          {callTitle(call)}
        </Link>
      );
      return (
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            {isLive(call) && <LiveDot />}
            {compact ? (
              rowLink
            ) : (
              <HoverCard trigger={rowLink} label={`Preview of the call with ${callTitle(call)}`}>
                <CallPreview call={call} />
              </HoverCard>
            )}
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
          {compact && <CapturedLine call={call} />}
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-meta text-ink-faint md:hidden">
            <CallResult call={call} />
            <NeedsYouMark call={call} />
            {call.follow_up_state ? (
              <>
                <span aria-hidden>·</span>
                <FollowUpMark state={call.follow_up_state} />
              </>
            ) : null}
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
    flash: (call) =>
      `${call.status}|${call.outcome_tag ?? ""}|${call.business_outcome_label ?? ""}|${call.business_outcome_lead_status ?? ""}|${call.callback?.status ?? ""}|${call.follow_up_state ?? ""}`,
    sort: compact ? undefined : { value: (call) => callOutcome(call).words },
    cell: (call) => (
      <span className="flex flex-col items-start gap-0.5">
        <CallResult call={call} />
        <NeedsYouMark call={call} />
        <FollowUpMark state={call.follow_up_state} />
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
  const cost: DataColumn<CallSummary> = {
    id: "cost",
    header: "Cost",
    align: "right",
    hideBelow: "md",
    cell: (call) => (
      <span className="whitespace-nowrap text-meta tabular-nums text-ink-muted">
        {call.credits_used_inr ? formatINR(call.credits_used_inr) : "—"}
      </span>
    ),
  };
  const more: DataColumn<CallSummary>[] = menu
    ? [
        {
          id: "more",
          header: "More actions",
          renderHeader: () => null,
          className: "relative z-raised w-10 text-right",
          cell: (call) => menu(call),
        },
      ]
    : [];
  if (!compact) return [caller, result, duration, started, ...more];
  return showCost
    ? [caller, result, sentiment, duration, cost, started]
    : [caller, result, sentiment, duration, started];
}

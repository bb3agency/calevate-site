"use client";

import Link from "next/link";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { MonoValue, ProblemNotice, Skeleton, formatDuration, formatINR, formatIST, formatPhone } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { LiveDot } from "@/components/console/liveCalls";
import { useEnterClass } from "@/components/live/arrivals";
import type { CallSummary } from "@/lib/api/client";
import { usePrefetchCall, type useCalls } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { callOutcome, callRowLine, callTitle } from "@/lib/callReview";
import { useReadAhead, type ReadAheadProps } from "@/lib/readAhead";

import { FollowUpMark, NeedsYouMark, OutcomeDot, TestCallTag, callAt, isLive } from "./calls/callColumns";

/**
 * The six most recent calls — the fastest route from "somebody rang" to ringing them
 * back, which is why the number is printed in full (D-436).
 *
 * A list of rows rather than the call log's table. The tile is two thirds of the page at
 * most, and the log's six columns there left the caller column a few characters wide
 * ("+91 934…") while the outcome column took the room and the table scrolled sideways. Here
 * the facts a row answers sit in two content-sized columns on the right and the caller
 * takes everything else, wrapping instead of being cut: nothing is truncated and nothing
 * scrolls at any width. Below `sm` the same nodes re-place into a two-line row (who and
 * when, then outcome and length), so a phone reads each call without a card of labels.
 *
 * No outcome wash on the row: the dot beside the outcome's words already says the kind,
 * and six tinted rows made every call equally loud.
 */
export function LatestCalls({
  recent,
  allHref,
  callHref,
  headingLevel = 2,
}: {
  recent: ReturnType<typeof useCalls>;
  allHref: string;
  callHref: (id: string) => string;
  /** 3 where it sits under a tab whose own heading is the h2 (an agent's Overview). */
  headingLevel?: 2 | 3;
}) {
  const { session } = useClientRealm();
  const readAhead = useReadAhead(usePrefetchCall(session));
  const enter = useEnterClass(recent.data ? recent.data.map((call) => call.id) : null);
  return (
    <Section
      title="Latest calls"
      headingLevel={headingLevel}
      action={
        <Link href={allHref} className={TEXT_ACTION}>
          View all
        </Link>
      }
    >
      {recent.isLoading ? (
        <Skeleton rows={5} />
      ) : recent.error || !recent.data ? (
        /* Both non-answers — a refusal and a paused (offline) query — are this arm, so
           "No calls yet" is only ever printed over a list the server sent (§52). */
        <ProblemNotice
          error={recent.error ?? new Error("The latest calls did not load.")}
          onRetry={() => void recent.refetch()}
        />
      ) : !recent.data.length ? (
        <EmptyState
          illustration={<EmptySketch kind="calls" />}
          message="No calls yet."
          hint="Calls show here a few minutes after they end."
        />
      ) : (
        <ol aria-label="Latest calls" className="-mx-2 divide-y divide-line border-y border-line">
          {recent.data.map((call) => (
            <CallRow
              key={call.id}
              call={call}
              href={callHref(call.id)}
              readAhead={readAhead}
              className={enter(call.id)}
            />
          ))}
        </ol>
      )}
    </Section>
  );
}

/*
 * One grid, placed twice. Every fact is ONE node in reading order (who, what, outcome,
 * length, cost, when), so a screen reader and a test meet each once; only its cell moves.
 *
 *   phone   | who ................ when |      sm+ | who        | outcome   | when        |
 *           | outcome ...... len · ₹  |           | headline   | needs you | len · ₹     |
 *                                                  | captured   |           |             |
 */
const ROW =
  "relative grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1 rounded-md px-2 py-3 transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.03] sm:grid-cols-[minmax(0,1fr)_auto_auto]";
const WHO = "col-start-1 row-start-1 min-w-0";
const HEADLINE = "hidden sm:col-start-1 sm:row-start-2 sm:block";
const CAPTURED = "hidden sm:col-start-1 sm:row-start-3 sm:block";
const OUTCOME = "col-start-1 row-start-2 min-w-0 sm:col-start-2 sm:row-start-1 sm:row-span-2 sm:max-w-56";
const WHEN = "col-start-2 row-start-1 text-right sm:col-start-3";
const MEASURES = "col-start-2 row-start-2 text-right sm:col-start-3";

function CallRow({
  call,
  href,
  readAhead,
  className,
}: {
  call: CallSummary;
  href: string;
  readAhead: (id: string) => ReadAheadProps;
  className: string;
}) {
  const line = callRowLine(call);
  const { words, kind } = callOutcome(call);
  const live = isLive(call);
  const named = Boolean(call.lead_name?.trim());
  const captured = (call.captured_preview ?? []).map((chip) => `${chip.label}: ${chip.value}`).join(" · ");
  const hasCost = call.credits_used_inr !== null && call.credits_used_inr !== undefined;
  return (
    <li className={`${ROW} ${className}`}>
      <div className={`${WHO} flex flex-wrap items-center gap-x-2 gap-y-0.5`}>
        {live && <LiveDot />}
        {/* The row's one link, stretched over the whole row; its id is the call's, never
            the number (hard rule 6). */}
        <Link
          href={href}
          {...readAhead(call.id)}
          className="min-w-0 break-words rounded-sm font-medium text-ink after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
        >
          {callTitle(call)}
        </Link>
        {named && call.caller_e164 && (
          <MonoValue className="hidden whitespace-nowrap text-meta tabular-nums text-ink-faint sm:inline">
            {formatPhone(call.caller_e164)}
          </MonoValue>
        )}
        {call.test_call && <TestCallTag />}
      </div>
      <p className={`${HEADLINE} break-words text-meta ${line.pending ? "italic text-ink-faint" : "text-ink-muted"}`}>
        {line.text}
      </p>
      {captured ? <p className={`${CAPTURED} break-words text-meta text-ink-faint`}>{captured}</p> : null}
      <div className={`${OUTCOME} flex flex-wrap items-center gap-x-2 gap-y-0.5 sm:flex-col sm:items-start`}>
        <span className="inline-flex min-w-0 items-baseline gap-1.5 text-meta text-ink-muted">
          <span className="self-center">
            <OutcomeDot kind={kind} />
          </span>
          <span className="break-words">{words}</span>
        </span>
        <NeedsYouMark call={call} />
        <FollowUpMark state={call.follow_up_state} />
      </div>
      <p className={`${WHEN} whitespace-nowrap text-meta tabular-nums text-ink-faint`}>{formatIST(callAt(call))}</p>
      <p className={`${MEASURES} whitespace-nowrap text-meta tabular-nums text-ink-muted`}>
        <span className="sr-only">Length </span>
        {formatDuration(call.duration_s)}
        {hasCost ? (
          <>
            <span aria-hidden> · </span>
            <span className="sr-only">Cost </span>
            <span>{call.credits_used_inr ? formatINR(call.credits_used_inr) : "—"}</span>
          </>
        ) : null}
      </p>
    </li>
  );
}

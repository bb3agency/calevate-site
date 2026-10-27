"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { SwipeActions } from "@/components/arc/swipe-actions";
import { LiveDot } from "@/components/console/liveCalls";
import type { FollowUpActions, FollowUpTarget } from "@/components/calls/followUpActions";
import { formatDuration, formatIST } from "@/components/ui";
import { callRowLine, callTitle } from "@/lib/callReview";

import {
  CallResult,
  FollowUpMark,
  NeedsYouMark,
  OutcomeDot,
  TestCallTag,
  callAt,
  isLive,
  outcomeRowClass,
} from "./callColumns";
import { type LogCall, LiveLength, LiveMark, LiveSheen, liveLine, liveWords } from "./liveRows";

const ROW = "relative isolate block min-w-0 px-4 py-3";

/**
 * The call log on a phone, laid out like the leads list (founder, 24 Oct 2026): who and what
 * on the left (the number or name, then what the call was about), how it ended and when on
 * the right (with "Needs you" under the outcome, never instead of it), and the follow-up actions a swipe away (right: call back; left: mark, call back
 * later, WhatsApp). The row fits the screen, so a sideways swipe only ever means the actions;
 * the same actions are in each row's ⋯ menu where there is a mouse. A length or a time the
 * call does not have is left out rather than shown as a dash.
 *
 * A call still running (D-886) has no swipe: there is nothing to follow up yet. It is not a
 * link while its own page would have nothing to show (`LogCall.opens`).
 */
export function CallsPhoneList({
  rows,
  callHref,
  actions,
  targetOf,
}: {
  rows: LogCall[];
  callHref: (id: string) => string;
  actions: FollowUpActions;
  targetOf: (call: LogCall) => FollowUpTarget;
}) {
  return (
    <ul aria-label="Calls, newest first" className="divide-y divide-line">
      {rows.map((call) => {
        const live = call.live ?? null;
        const running = live?.state === "live";
        const line = live ? { text: liveLine(live), pending: live.state === "unreported" } : callRowLine(call);
        // Muted, not faint, under the live sheen: faint ink drops below 4.5:1 as the band passes.
        const quiet = running ? "text-ink-muted" : "text-ink-faint";
        const at = callAt(call);
        const when = at ? formatIST(at) : null;
        const length = live?.state === "live" ? (
          live.startedAt ? <LiveLength startedAt={live.startedAt} /> : null
        ) : call.duration_s ? (
          formatDuration(call.duration_s)
        ) : null;
        const body = (
          <>
            {running && <LiveSheen />}
            <span className="flex min-w-0 items-start justify-between gap-3">
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-2">
                  {(live ? running : isLive(call)) && <LiveDot />}
                  <span className="truncate font-medium text-ink">{callTitle(call)}</span>
                  {running && <LiveMark />}
                  {call.test_call && <TestCallTag />}
                </span>
                <span
                  className={`mt-0.5 block line-clamp-2 text-meta ${line.pending ? "italic text-ink-faint" : "text-ink-muted"}`}
                >
                  {line.text}
                </span>
                {!live && call.follow_up_state ? (
                  <span className="mt-1 block">
                    <FollowUpMark state={call.follow_up_state} />
                  </span>
                ) : null}
              </span>
              <span className="flex max-w-[42%] shrink-0 flex-col items-end gap-0.5 text-right">
                <span className="flex max-w-full justify-end">
                  {live ? (
                    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 text-meta text-ink-muted">
                      {live.state === "unreported" ? <OutcomeDot kind="neutral" /> : null}
                      <span className="truncate">{liveWords(live)}</span>
                    </span>
                  ) : (
                    <CallResult call={call} truncate />
                  )}
                </span>
                {!live && <NeedsYouMark call={call} />}
                {when ? <span className={`text-meta tabular-nums ${quiet}`}>{when}</span> : null}
                {length ? <span className={`text-meta tabular-nums ${quiet}`}>{length}</span> : null}
              </span>
            </span>
          </>
        );
        const opens = call.opens ?? true;
        // A running call keeps the live sheen; every other row is washed in its outcome.
        const wash = live ? "" : outcomeRowClass(call);
        const row: ReactNode = opens ? (
          <Link
            href={callHref(call.id)}
            className={`${ROW} ${wash} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand`}
          >
            {body}
          </Link>
        ) : (
          <div className={`${ROW} ${wash}`}>{body}</div>
        );
        if (running) {
          return <li key={call.id} className="bg-brand-soft/40 dark:bg-brand-strong/10">{row}</li>;
        }
        const target = targetOf(call);
        const { primary, secondary } = actions.actionsFor(target);
        return (
          <li key={call.id}>
            <SwipeActions label={target.name} primary={primary} secondary={secondary}>
              {row}
            </SwipeActions>
          </li>
        );
      })}
    </ul>
  );
}

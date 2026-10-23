"use client";

import Link from "next/link";

import { SwipeActions } from "@/components/arc/swipe-actions";
import { LiveDot } from "@/components/console/liveCalls";
import type { FollowUpActions, FollowUpTarget } from "@/components/calls/followUpActions";
import { formatDuration, formatIST } from "@/components/ui";
import type { CallSummary } from "@/lib/api/client";
import { callRowLine, callTitle } from "@/lib/callReview";

import { CallResult, FollowUpMark, TestCallTag, isLive } from "./callColumns";

/**
 * The call log on a phone: one row per call, three short lines, and the follow-up actions a
 * swipe away (right: call back; left: mark, call back later, WhatsApp). A table would scroll
 * sideways under the thumb and fight the swipe, so a phone gets this list instead; the same
 * actions are in each row's ⋯ menu where there is a mouse.
 */
export function CallsPhoneList({
  rows,
  callHref,
  actions,
  targetOf,
}: {
  rows: CallSummary[];
  callHref: (id: string) => string;
  actions: FollowUpActions;
  targetOf: (call: CallSummary) => FollowUpTarget;
}) {
  return (
    <ul aria-label="Calls, newest first" className="divide-y divide-line">
      {rows.map((call) => {
        const target = targetOf(call);
        const { primary, secondary } = actions.actionsFor(target);
        const line = callRowLine(call);
        return (
          <li key={call.id}>
            <SwipeActions label={target.name} primary={primary} secondary={secondary}>
              <Link
                href={callHref(call.id)}
                className="block min-w-0 px-1 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
              >
                <span className="flex min-w-0 items-center gap-2">
                  {isLive(call) && <LiveDot />}
                  <span className="truncate font-medium text-ink">{callTitle(call)}</span>
                  {call.test_call && <TestCallTag />}
                </span>
                <span className={`mt-0.5 block truncate text-meta ${line.pending ? "italic text-ink-faint" : "text-ink-muted"}`}>
                  {line.text}
                </span>
                <span className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-meta text-ink-faint">
                  <CallResult call={call} />
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
                </span>
              </Link>
            </SwipeActions>
          </li>
        );
      })}
    </ul>
  );
}

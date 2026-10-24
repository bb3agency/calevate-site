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
 * The call log on a phone, laid out like the leads list (founder, 24 Oct 2026): who and what
 * on the left (the number or name, then what the call was about), how it ended and when on
 * the right, and the follow-up actions a swipe away (right: call back; left: mark, call back
 * later, WhatsApp). The row fits the screen, so a sideways swipe only ever means the actions;
 * the same actions are in each row's ⋯ menu where there is a mouse. A length or a time the
 * call does not have is left out rather than shown as a dash.
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
        const at = call.started_at ?? call.created_at;
        const when = at ? formatIST(at) : null;
        const length = call.duration_s ? formatDuration(call.duration_s) : null;
        return (
          <li key={call.id}>
            <SwipeActions label={target.name} primary={primary} secondary={secondary}>
              <Link
                href={callHref(call.id)}
                className="block min-w-0 px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
              >
                <span className="flex min-w-0 items-start justify-between gap-3">
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-2">
                      {isLive(call) && <LiveDot />}
                      <span className="truncate font-medium text-ink">{callTitle(call)}</span>
                      {call.test_call && <TestCallTag />}
                    </span>
                    <span
                      className={`mt-0.5 block line-clamp-2 text-meta ${line.pending ? "italic text-ink-faint" : "text-ink-muted"}`}
                    >
                      {line.text}
                    </span>
                    {call.follow_up_state ? (
                      <span className="mt-1 block">
                        <FollowUpMark state={call.follow_up_state} />
                      </span>
                    ) : null}
                  </span>
                  <span className="flex max-w-[42%] shrink-0 flex-col items-end gap-0.5 text-right">
                    <span className="block max-w-full truncate">
                      <CallResult call={call} />
                    </span>
                    {when ? <span className="text-meta tabular-nums text-ink-faint">{when}</span> : null}
                    {length ? <span className="text-meta tabular-nums text-ink-faint">{length}</span> : null}
                  </span>
                </span>
              </Link>
            </SwipeActions>
          </li>
        );
      })}
    </ul>
  );
}

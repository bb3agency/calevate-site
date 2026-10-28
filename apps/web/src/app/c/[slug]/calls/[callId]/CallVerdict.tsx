"use client";

import type { ReactNode } from "react";

import type { CallDetail } from "@/lib/api/client";
import {
  businessOutcomeAside,
  callOutcome,
  callbackLine,
  langAttr,
  needsAttention,
  outcomeReason,
  outcomeWords,
} from "@/lib/callReview";

import { OutcomeDot, isLive } from "../callColumns";

/**
 * THE VERDICT — the screen's primary surface (UX-DOCTRINE §1): how the call ended and
 * why, what was said in a few sentences, what happens next, and the one action.
 *
 * Everything an owner opens a call to learn sits here, above the recording and the
 * transcript, so a phone shows the answer and the action without a scroll. The summary is
 * in English whichever language the Conversation is read in; the outcome is
 * the founder's vocabulary with a one-line reason (decision 6). The warning tone is used
 * only when the call needs a person. The call log's kind-of-ending dot sits beside
 * whichever line here says the same words as the call's row, so a colour seen in the list
 * is found again on the call.
 */
export function CallVerdict({ detail, action }: { detail: CallDetail; action: ReactNode }) {
  const label = outcomeWords(detail);
  const aside = businessOutcomeAside(detail);
  const warn = needsAttention(detail);
  const heading = label ?? (isLive(detail) ? "On the line now" : detail.status === "completed" ? "Reading this call" : "No conversation");
  const ended = callOutcome(detail);
  return (
    // The action follows the reason in the DOM, so on a phone it is above the fold and is
    // the first thing a keyboard reaches; from `sm` it is drawn after the summary and the
    // next steps it acts on, where a wide screen has room for all of them.
    <section aria-labelledby="call-verdict" className="flex flex-col gap-5">
      <div>
        <h2
          id="call-verdict"
          className={`flex items-center gap-2 text-heading ${warn ? "text-warn" : "text-ink"}`}
        >
          {heading === ended.words && <OutcomeDot kind={ended.kind} />}
          {heading}
        </h2>
        <p className="mt-1 max-w-prose text-body text-ink-muted [text-wrap:pretty]">{outcomeReason(detail)}</p>
        {aside && (
          <p className="mt-1 text-meta text-ink-muted">
            For your business:{" "}
            <span className="inline-flex items-center gap-1.5 align-middle font-medium text-ink">
              {aside === ended.words && heading !== ended.words && <OutcomeDot kind={ended.kind} />}
              {aside}
            </span>
          </p>
        )}
      </div>

      <div className="sm:order-last">{action}</div>

      <div className="empty:hidden">
        <Summary detail={detail} />
      </div>

      <div className="empty:hidden">
        <NextSteps detail={detail} />
      </div>
    </section>
  );
}

/**
 * The summary, in English: the owner reads the call's gist in English while the
 * Conversation opens as spoken (founder, 25 Oct 2026). The call-language summary stands in
 * only when no English one exists, rather than a blank. Four states
 * the server tells apart (`summary_state`), each said in words — "still writing" is never
 * shown as "there is none", and "there is none" never as a blank.
 */
function Summary({ detail }: { detail: CallDetail }) {
  if (isLive(detail)) {
    return <p className="text-body text-ink-muted">The summary is written when the call ends.</p>;
  }
  if (detail.status !== "completed") return null;

  if (detail.summary_state === "pending" && !detail.summary) {
    return (
      <div role="status" aria-live="polite" className="max-w-prose space-y-2">
        <p className="text-body text-ink-muted"><span className="text-shimmer">Writing the summary…</span></p>
        <div aria-hidden className="space-y-2">
          <div className="h-4 w-full animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none" />
        </div>
      </div>
    );
  }
  if (detail.summary_state === "failed" && !detail.summary) {
    return (
      <p className="max-w-prose text-body text-ink-muted">
        Couldn&apos;t write a summary.
        {detail.transcript?.length ? " The full chat is below." : ""}
      </p>
    );
  }
  if (!detail.summary && !detail.summary_local) {
    return <p className="text-body text-ink-muted">Nothing was said, so no summary.</p>;
  }

  const showLocal = !detail.summary;
  return (
    <div className="max-w-prose rounded-md bg-surface-muted px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Summary</p>
      <p
        lang={showLocal ? langAttr(detail.summary_language) : "en"}
        className="mt-1 text-transcript text-ink [text-wrap:pretty]"
      >
        {showLocal ? detail.summary_local : detail.summary}
      </p>
    </div>
  );
}

/**
 * What happens next: the step the reading suggests, and the call back booked on this call
 * with its state. A stopped call back carries the server's own sentence for why, word for
 * word (a trial account, the do-not-call list, calling hours).
 */
function NextSteps({ detail }: { detail: CallDetail }) {
  const callback = detail.callback ? callbackLine(detail.callback) : null;
  if (!detail.next_step && !callback) return null;
  return (
    <dl className="max-w-2xl divide-y divide-line border-y border-line">
      {detail.next_step && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-0.5 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-body text-ink-muted">Next step</dt>
          <dd className="text-body text-ink [text-wrap:pretty]">{detail.next_step}</dd>
        </div>
      )}
      {callback && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-0.5 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-body text-ink-muted">Call back</dt>
          <dd className="text-body text-ink">
            <span className="tabular-nums">{callback.when}</span>
            <span aria-hidden> · </span>
            <span className={callback.overdue ? "font-medium text-warn" : ""}>{callback.state}</span>
            {callback.reason && (
              <span className="mt-0.5 block text-meta text-ink-muted [text-wrap:pretty]">{callback.reason}</span>
            )}
          </dd>
        </div>
      )}
    </dl>
  );
}

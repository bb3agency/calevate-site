"use client";

import { useState, type ReactNode } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import type { CallDetail } from "@/lib/api/client";
import { callbackLine, langAttr, languageName, needsAttention, outcomeLabel, outcomeReason } from "@/lib/callReview";

import { isLive } from "../callColumns";

/**
 * THE VERDICT — the screen's primary surface (UX-DOCTRINE §1): how the call ended and
 * why, what was said in a few sentences, what happens next, and the one action.
 *
 * Everything an owner opens a call to learn sits here, above the recording and the
 * transcript, so a phone shows the answer and the action without a scroll. The summary is
 * English with a switch to the call's own language (founder decision 4); the outcome is
 * the founder's vocabulary with a one-line reason (decision 6). The warning tone is used
 * only when the call needs a person.
 */
export function CallVerdict({ detail, action }: { detail: CallDetail; action: ReactNode }) {
  const label = outcomeLabel(detail.outcome_tag);
  const warn = needsAttention(detail);
  const heading = label ?? (isLive(detail) ? "On the line now" : detail.status === "completed" ? "Reading this call" : "No conversation");
  return (
    // The action follows the reason in the DOM, so on a phone it is above the fold and is
    // the first thing a keyboard reaches; from `sm` it is drawn after the summary and the
    // next steps it acts on, where a wide screen has room for all of them.
    <section aria-labelledby="call-verdict" className="flex flex-col gap-5">
      <div>
        <h2 id="call-verdict" className={`text-heading ${warn ? "text-warn" : "text-ink"}`}>
          {heading}
        </h2>
        <p className="mt-1 max-w-prose text-body text-ink-muted [text-wrap:pretty]">{outcomeReason(detail)}</p>
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
 * The summary, in English by default and in the call's language on request. Four states
 * the server tells apart (`summary_state`), each said in words — "still writing" is never
 * shown as "there is none", and "there is none" never as a blank.
 */
function Summary({ detail }: { detail: CallDetail }) {
  const [local, setLocal] = useState(false);
  if (isLive(detail)) {
    return <p className="text-body text-ink-muted">The summary is written when the call ends.</p>;
  }
  if (detail.status !== "completed") return null;

  if (detail.summary_state === "pending" && !detail.summary) {
    return (
      <div role="status" aria-live="polite" className="max-w-prose space-y-2">
        <p className="text-body text-ink-muted">Writing the summary…</p>
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
        The summary could not be written for this call. The conversation below is complete.
      </p>
    );
  }
  if (!detail.summary) {
    return <p className="text-body text-ink-muted">Nothing was said on this call, so there is no summary.</p>;
  }

  const language = languageName(detail.summary_language);
  const showLocal = local && Boolean(detail.summary_local);
  return (
    <div className="max-w-prose space-y-2">
      <p
        lang={showLocal ? langAttr(detail.summary_language) : "en"}
        className="text-transcript text-ink [text-wrap:pretty]"
      >
        {showLocal ? detail.summary_local : detail.summary}
      </p>
      {detail.summary_local && language && (
        <button
          type="button"
          className={`${TEXT_ACTION} text-meta`}
          aria-pressed={showLocal}
          onClick={() => setLocal((v) => !v)}
        >
          {showLocal ? "Read it in English" : `Read it in ${language}`}
        </button>
      )}
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
        <div className="grid gap-x-6 gap-y-0.5 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-body text-ink-muted">Next step</dt>
          <dd className="text-body text-ink [text-wrap:pretty]">{detail.next_step}</dd>
        </div>
      )}
      {callback && (
        <div className="grid gap-x-6 gap-y-0.5 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
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

"use client";

import type { ReactNode } from "react";

import type { CallDetail } from "@/lib/api/client";
import {
  businessOutcomeAside,
  callbackLine,
  isEnglishCall,
  langAttr,
  languageName,
  needsAttention,
  outcomeReason,
  outcomeWords,
} from "@/lib/callReview";

import { isLive } from "../callColumns";

import type { CallView } from "./callEnglish";

/**
 * THE VERDICT — the screen's primary surface (UX-DOCTRINE §1): how the call ended and
 * why, what was said in a few sentences, what happens next, and the one action.
 *
 * Everything an owner opens a call to learn sits here, above the recording and the
 * transcript, so a phone shows the answer and the action without a scroll. The summary is
 * shown in the language the page's one switch chooses (the Conversation's); the outcome is
 * the founder's vocabulary with a one-line reason (decision 6). The warning tone is used
 * only when the call needs a person.
 */
export function CallVerdict({ detail, action, view }: { detail: CallDetail; action: ReactNode; view: CallView }) {
  const label = outcomeWords(detail);
  const aside = businessOutcomeAside(detail);
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
        {aside && (
          <p className="mt-1 text-meta text-ink-muted">
            For your business: <span className="font-medium text-ink">{aside}</span>
          </p>
        )}
      </div>

      <div className="sm:order-last">{action}</div>

      <div className="empty:hidden">
        <Summary detail={detail} view={view} />
      </div>

      <div className="empty:hidden">
        <NextSteps detail={detail} />
      </div>
    </section>
  );
}

/**
 * The summary, in the language the page's switch chose. Four states
 * the server tells apart (`summary_state`), each said in words — "still writing" is never
 * shown as "there is none", and "there is none" never as a blank.
 */
function Summary({ detail, view }: { detail: CallDetail; view: CallView }) {
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
        The summary could not be written for this call.
        {detail.transcript?.length ? " The conversation below is complete." : ""}
      </p>
    );
  }
  if (!detail.summary && !detail.summary_local) {
    return <p className="text-body text-ink-muted">Nothing was said on this call, so there is no summary.</p>;
  }

  const showLocal = Boolean(detail.summary_local) && (view === "original" || !detail.summary);
  // Asked for the call's language and there is no summary in it: the English one, said as
  // such, rather than nothing.
  const onlyEnglish = view === "original" && !showLocal && !isEnglishCall(detail.language);
  return (
    <div className="max-w-prose space-y-1.5">
      <p
        lang={showLocal ? langAttr(detail.summary_language) : "en"}
        className="text-transcript text-ink [text-wrap:pretty]"
      >
        {showLocal ? detail.summary_local : detail.summary}
      </p>
      {onlyEnglish && (
        <p className="text-meta text-ink-faint">
          The summary is in English; it has not been written in {languageName(detail.language) ?? "the call's language"} yet.
        </p>
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

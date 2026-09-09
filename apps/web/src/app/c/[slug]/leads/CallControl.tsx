"use client";

import { type ReactNode } from "react";
import { CheckCircle2, PhoneOutgoing, ShieldAlert } from "lucide-react";

import { type CallLeadResult } from "@/lib/api/client";

/**
 * CALL THIS LEAD — the dispatch control, and the one thing a refusal adds to the
 * server's own sentence.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). The refusal copy below is a compliance
 * surface: `result.blocked_reason` is the SERVER's wording and is rendered as-is
 * (UX-DOCTRINE §8 — "a paraphrase is a second implementation of a compliance rule"), and
 * `blockedRemedy` adds only the destination the server cannot know.
 */
/**
 * D-21 dispatch, per lead — the one control shared by the table and the board.
 *
 * The shape it has to respect: `POST /v1/leads/{id}/call` answers **200** with
 * `status: "blocked"` when the compliance gate refuses, because a refusal is a decision
 * this screen should explain, not an exception to swallow. Falling through to the
 * enabled button on that answer would look like the click did nothing, and the client
 * would press it again — so a blocked row shows the reason and offers no second attempt
 * (the server has already recorded its answer for this lead).
 *
 * A refusal is amber, not rose: the gate working is not a fault, and painting it like an
 * error is what teaches a client to report their own compliance rules as bugs.
 */
/**
 * The one thing a refused dial's rule NAME was ever worth to a client: where the refusal
 * is cleared.
 *
 * Only the two money gates have a destination on this screen's side of the product, and
 * they are the two a prepaid account meets — which is now nearly every account. Every
 * other rule (consent, do-not-call, calling hours, the DLT registrations) already carries
 * its own remedy inside the server's sentence, and a second link would be a worse version
 * of it. An unknown rule adds nothing rather than printing itself.
 */
function blockedRemedy(rule: string | null | undefined): ReactNode {
  // BOTH SCREENS ARE ONE SCREEN NOW (D-525). This used to name "Calling credit" and
  // "Usage", which were two of the four money screens; they are tabs of Credits & billing,
  // so the destination is the same in both arms and only the tab differs. The tab is not
  // named here on purpose — a client who lands on the screen sees the balance and the
  // limit without being told which tab to press, and a tab name is one more thing that
  // goes stale on a screen this sentence cannot see.
  // ⚠ THIS USED TO OPEN "People ringing you still get through", which D-551 made false:
  // an empty wallet now silences answering as well as dialling. The server's own sentence
  // (`compliance.service.NO_CREDITS_REASON`) already says both halves stopped, so this
  // adds only what it cannot know — where the button is, and that one payment undoes both.
  if (rule === "no_credits") {
    return (
      <>
        {" "}
        Add credit on the Credits &amp; billing screen and both start again straight away.
      </>
    );
  }
  if (rule === "spend_cap") {
    return (
      <>
        {" "}
        People ringing you still get through. Your monthly limit is on Credits &amp;
        billing.
      </>
    );
  }
  return null;
}

export function CallControl({
  result,
  pending,
  onCall,
}: {
  result: CallLeadResult | undefined;
  pending: boolean;
  onCall: () => void;
}) {
  if (result?.status === "queued") {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-brand-strong dark:text-brand-bright">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        Calling now
      </span>
    );
  }
  if (result?.status === "blocked") {
    return (
      <span className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          {result.blocked_reason ?? "This call was not allowed."}
          {/* THE RULE NAME USED TO BE PRINTED HERE, in brackets, to the client: a refused
              dial read "This account has no calling credit left. (no_credits)". That is
              the platform's own vocabulary handed to the person it refused, and it tells
              them nothing they can act on — the founder's standard for client-facing copy
              bans it, and `tests/plainLanguageGuard.test.ts` now enforces the literal
              half of that rule (this one was a variable, which is why it survived).
              What replaces it is the thing the name was standing in for: WHERE the two
              money refusals are fixed. Everything else keeps the server's sentence
              alone, which already names its own remedy. */}
          {blockedRemedy(result.blocked_rule)}
        </span>
      </span>
    );
  }
  return (
    <button
      type="button"
      disabled={pending}
      onClick={onCall}
      className="flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs font-semibold text-ink-muted hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/5"
    >
      <PhoneOutgoing className="h-3.5 w-3.5 shrink-0" />
      {pending ? "Calling…" : "Call with AI"}
    </button>
  );
}

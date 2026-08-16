"use client";

import { useRef } from "react";

import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, formatCount, formatINR } from "./ui";
import type { AiQuota } from "@/lib/api/aiQuota";
import { useFocusTrap } from "@/lib/focusTrap";

/**
 * G-5's acceptance dialog — the ONE thing in this console that debits a wallet, and
 * therefore the one dialog there may only be one of.
 *
 * It lived inside `c/[slug]/ai-assist/page.tsx` while that screen was the only place a
 * client could meet the ceiling. It is here now because the ceiling is reachable from
 * anywhere the assistant can be used — the call detail screen's "Re-summarise" is the
 * second — and a second dialog is not a duplicated component, it is a second statement
 * about what a client's money buys. The two would drift on the sentence that matters
 * most: that the unused part is not refunded.
 *
 * Both callers pass the SERVER's `AiQuota`, so neither of them computes an amount.
 */

/**
 * The dialog, unchanged in behaviour from the day it shipped on the AI-help screen.
 *
 * Four sentences are load-bearing and each is here because leaving it out would make the
 * dialog a worse bargain than the one being offered:
 *
 * 1. the exact amount, as the server sent it — `formatINR` groups the digits and never
 *    parses them;
 * 2. what it buys, as a count the server derived, with "about";
 * 3. that the unused part is NOT refunded and does NOT carry over — the honest cost of
 *    selling a block rather than metering per use;
 * 4. that nothing has been charged yet, which is the whole promise of the dialog.
 *
 * ACCESSIBILITY. `role="dialog"` + `aria-modal` + a heading it is labelled by, and the
 * full APG focus contract via `useFocusTrap`. The two buttons are real buttons in DOM
 * order, so a keyboard reaches "Not now" first — the safe answer should not be the one
 * that takes more keystrokes.
 *
 * This dialog used to move focus on open and handle Escape and NOTHING ELSE, which is
 * half of `aria-modal="true"`'s promise and the wrong half: the first Tab left the panel
 * and landed on the page behind it, and Escape dropped focus onto `<body>`. On the one
 * control in this console that debits a wallet, a keyboard user could be typing into a
 * page they believed was covered by a modal. `navDrawer` had had the trap since it
 * shipped and said in its own header that the next modal should borrow it; the borrowing
 * is now a hook both call (src/lib/focusTrap.ts), so there is one implementation.
 */
export function AcceptChargeDialog({
  quota,
  pending,
  error,
  onCancel,
  onAccept,
}: {
  quota: AiQuota;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onAccept: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);

  /*
   * Always `true`: this component only exists while the dialog is open — both callers
   * render it inside a `{showing && …}` — so mounting IS opening, and unmounting is what
   * hands focus back to the button that opened it.
   *
   * The Escape listener that used to live here (on `document`, not on a wrapper's
   * `onKeyDown`, because a React handler only fires for keys pressed inside its own
   * subtree and Escape has to work when focus has left the dialog) is inside the hook,
   * for that same reason and one more: the hook needs the document listener anyway to
   * pull focus back when Tab tries to leave.
   */
  useFocusTrap(panel, true, onCancel, "container");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-extra-title"
        aria-describedby="ai-extra-body"
        tabIndex={-1}
        className="w-full max-w-md rounded-card border border-line bg-surface p-6 shadow-lg outline-none"
      >
        <h2 id="ai-extra-title" className="text-[17px] font-semibold text-ink">
          Add more AI help this month
        </h2>

        <div id="ai-extra-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          <p>
            <strong className="font-semibold tabular-nums text-ink">
              {formatINR(quota.extra_block_inr)}
            </strong>{" "}
            will be taken from your calling credit. It covers about{" "}
            {formatCount(quota.extra_block_requests)} more uses of AI help for the rest of{" "}
            {quota.month}.
          </p>
          <p>
            Anything you do not use is not refunded and does not carry into next month.
            You can add this once per month.
          </p>
          <p className="font-medium text-ink">Nothing has been charged yet.</p>
        </div>

        {/* A refusal INSIDE the dialog, because that is where the decision is being
            made: closing the dialog to show it elsewhere would leave a person unsure
            whether the money moved. */}
        {error != null && (
          <div className="mt-3">
            <ProblemNotice error={error} />
          </div>
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" className={SECONDARY_BUTTON} onClick={onCancel} disabled={pending}>
            Not now
          </button>
          <button type="button" className={PRIMARY_BUTTON} onClick={onAccept} disabled={pending}>
            {pending ? "Adding…" : `Add ${formatINR(quota.extra_block_inr)}`}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Why the block is not on offer — the SERVER's reason, mapped to a sentence.
 *
 * The mapping is exhaustive and its fallback is deliberately vague rather than
 * confident: a reason this build does not know is a reason it must not paraphrase, and
 * "talk to your account manager" is true whatever it turns out to be.
 *
 * Shared with the dialog for the same reason the dialog is shared: two screens can offer
 * the block, so two screens can have to explain why it is not there, and two copies of
 * this switch is where one of them keeps saying "you have already added extra" after the
 * server started saying something else.
 */
export function extraUnavailableSentence(quota: AiQuota): string {
  switch (quota.extra_unavailable_reason) {
    case "not_prepaid":
      return "More AI help for this month is arranged with your account manager — it goes on your invoice rather than coming out of a balance.";
    case "already_purchased":
      return "You have already added extra AI help this month.";
    case "not_at_ceiling":
      return "There is still included AI help left this month.";
    // The block expires with the billing month, so within the last hour of one there is
    // nothing left to sell: the server refuses the purchase (`ai_extra_month_ending`)
    // and this is that refusal said BEFORE the click rather than after it.
    case "month_ending":
      return "This month is nearly over, so there is nothing worth adding to it — your included AI help comes back within the hour, and it is larger than what you would be buying.";
    default:
      return "More AI help cannot be added from here right now — talk to your account manager.";
  }
}

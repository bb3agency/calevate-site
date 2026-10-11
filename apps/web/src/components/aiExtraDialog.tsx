"use client";

import { ModalDialog } from "./modalDialog";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  formatCount,
  formatINR,
} from "./ui";
import type { AiQuota } from "@/lib/api/aiQuota";

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
 * ACCESSIBILITY. Built on `ModalDialog`: labelled by its title, the full APG focus
 * contract, and portalled so it shows above the assistant panel it is opened from. The
 * two buttons are real buttons in DOM order, so a keyboard reaches "Not now" first — the
 * safe answer should not be the one that takes more keystrokes.
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
  return (
    <ModalDialog
      title="Add more AI help this month"
      onClose={onCancel}
      description={
        <>
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
        </>
      }
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onCancel} disabled={pending}>
            Not now
          </button>
          <button type="button" className={PRIMARY_BUTTON} onClick={onAccept} disabled={pending}>
            {pending ? "Adding…" : `Add ${formatINR(quota.extra_block_inr)}`}
          </button>
        </>
      }
    >
      {/* A refusal INSIDE the dialog, because that is where the decision is being
          made: closing the dialog to show it elsewhere would leave a person unsure
          whether the money moved. */}
      {error != null && (
        <div className="mt-3">
          <ProblemNotice error={error} />
        </div>
      )}
    </ModalDialog>
  );
}

/**
 * Why the block is not on offer — the SERVER's reason, mapped to a sentence.
 *
 * The mapping is exhaustive and its fallback is deliberately vague rather than
 * confident: a reason this build does not know is a reason it must not paraphrase, and
 * "talk to us" is true whatever it turns out to be.
 *
 * Shared with the dialog for the same reason the dialog is shared: two screens can offer
 * the block, so two screens can have to explain why it is not there, and two copies of
 * this switch is where one of them keeps saying "you have already added extra" after the
 * server started saying something else.
 */
export function extraUnavailableSentence(quota: AiQuota): string {
  switch (quota.extra_unavailable_reason) {
    case "not_prepaid":
      return "More AI help cannot be bought for this account yet — talk to us.";
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
      return "More AI help cannot be added from here right now — talk to us.";
  }
}

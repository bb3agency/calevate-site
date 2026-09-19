"use client";

/**
 * REFUNDS — money going back OUT, at the payment provider, with a compensating ledger
 * entry behind it.
 *
 * `POST /v1/admin/tenants/{id}/refunds` shipped with a claim table, a provider call, a
 * ceiling enforced by a committed row and a migration arguing why no lock can span a
 * vendor call — and NO caller anywhere in this console. A client owed money could only
 * be refunded by an operator hand-assembling the request against production, or by
 * reaching into the provider's dashboard where no ledger entry follows.
 *
 * ## Why it is its own module and not a fourth write in `credits.ts`
 *
 * `credits.ts` documents "three writes, three different confirmation rules", and all
 * three share one property this does not have: **nothing outside our database moves.**
 * A top-up, an adjustment and a restatement are ledger appends, wholly ours, reversible
 * by a further append. A refund calls Razorpay FIRST, outside any transaction, and money
 * leaves. That difference is the whole of the failure model below, so it gets its own
 * file rather than diluting a module whose header is an argument about ledger writes.
 * It reuses `credits.ts`'s money predicates rather than restating them — one shape check
 * for rupees in this console, as that module already insists.
 *
 * ## `recorded` IS THE UI, and getting it wrong costs the client twice
 *
 * Both outcomes are 200:
 *
 * - `recorded: true` — the provider reported the refund already PROCESSED, so the
 *   compensating `credit_ledger` entry was written in the same request and
 *   `balance_inr` is the wallet after it.
 * - `recorded: false` — **the refund was ACCEPTED and is in flight.** The provider has
 *   it; the ledger entry lands when the `refund.processed` webhook arrives, deduped on
 *   the same refund id so it can only be written once.
 *
 * `false` is NOT a failure, and an operator who reads it as one issues the refund again.
 * The second attempt is idempotent at the provider on `(payment_id, amount)` and the
 * claim table refuses a total past the payment, so the platform survives it — but the
 * operator does not learn that, and the next thing they try is the provider's own
 * dashboard, where a second refund for a slightly different amount is one click and no
 * ledger entry follows it at all. So `recorded: false` renders as ACCEPTED, with the
 * processing window, and never as a refusal.
 *
 * ## WHICH PAYMENTS CAN ACTUALLY BE REFUNDED — a trap this module states rather than hides
 *
 * The route resolves the payment by looking for a top-up on the ledger with that
 * reference, then asks the PROVIDER to refund it. A wallet top-up recorded from a BANK
 * TRANSFER (`credits/page.tsx` — the operator types a UTR off a statement) has a
 * reference the provider has never seen, so the provider call fails with
 * `refund_rejected` and nothing moves. There is no field on `PaymentOut` saying which
 * kind a payment is, so this console does NOT guess: the screen says plainly that a
 * bank transfer is refunded by a bank transfer plus a compensating adjustment, and the
 * provider's refusal, when it comes, is rendered as the provider's own sentence.
 * (Recorded for whoever owns the API: a `source` discriminator on `PaymentOut` would let
 * this be a disabled control with a reason instead of a round trip.)
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { formatRupeeRate } from "@/components/ui";

import { apiRequest, type Session } from "./client";
import { creditsKey, rupeeFault, type Payment } from "./credits";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The request. `amount_inr` absent = refund the whole top-up recorded for this payment. */
export type RefundIn = Schemas["RefundIn"];
/** The answer. `recorded` separates "already on the ledger" from "in flight". */
export type RefundResult = Schemas["RefundOut"];

export function refundsPath(tenantId: string): string {
  return `/v1/admin/tenants/${encodeURIComponent(tenantId)}/refunds`;
}

/**
 * What the operator submits. Money is a STRING throughout (hard rule 7) — nothing here
 * calls `Number()` on it, and the route refuses a JSON float outright.
 */
export interface RefundDraft {
  /** The payment being refunded — chosen from the wallet's own list, never typed. */
  payment: Payment;
  /** Blank = the whole payment. Otherwise a positive magnitude, as DIGITS. */
  amountInr: string;
  /** Required, 1–280 characters. Reaches the audit summary verbatim. */
  reason: string;
}

/**
 * The typed confirmation this console asks a human for.
 *
 * **The API asks for none**, and that is exactly why the console must: a refund cannot
 * be taken back — the money has left, and `credit_ledger` is append-only, so the repair
 * for a wrong one is a fresh payment from the client. Per the friction rule, ceremony
 * belongs on the irreversible act. It is deliberately the opposite call from
 * `set_tenant_plan_tier` and the carrier decision, which carry none because both of
 * their directions are reversible.
 *
 * The word is the PAYMENT'S OWN REFERENCE, for `credits/page.tsx`'s reason: a fixed word
 * becomes muscle memory within a week, a reference is different every time, and typing
 * it is simultaneously the check that the operator is refunding the payment they think
 * they are. It is not sent anywhere — no header exists for it — so this file is the only
 * place the rule lives and `tests/adminRefund.test.tsx` is what keeps it there.
 */
export function refundConfirmationWord(payment: Payment): string {
  return payment.payment_ref.trim();
}

/**
 * The amount as the API wants it, or `undefined` for "the whole payment".
 *
 * Blank means absent, not zero: `RefundIn.amount_inr` is optional and the route reads
 * the recorded top-up itself, so the operator need not retype a figure they could
 * fat-finger. `"0"` would be `invalid_refund_amount`, which is a different request.
 */
export function refundAmount(draft: RefundDraft): string | undefined {
  const typed = draft.amountInr.trim();
  return typed === "" ? undefined : typed;
}

/**
 * Why this refund cannot be issued yet, or `null`.
 *
 * A PREVIEW of the route's own refusals, asked where the operator is typing:
 * `invalid_refund_amount`, the `reason` bounds, and `refund_exceeds_payment` — the last
 * measured against what this reference has CREDITED, which is the same figure the
 * server's claim table bounds the total by. The server refuses all three again, and the
 * ceiling in particular is enforced there by a committed claim rather than by a read,
 * because two operators refunding at the same instant is the case this preview cannot
 * see.
 */
export function refundBlockReason(draft: RefundDraft): string | null {
  const typed = draft.amountInr.trim();
  if (typed !== "") {
    switch (rupeeFault(typed)) {
      case "shape":
        return (
          "Digits only, with at most two decimal places — no commas, no ₹ sign, no " +
          "spaces (so 2500.10, not ₹2,500.10). Leave it empty to refund the whole payment."
        );
      case "zero":
        return "A refund has to move money. Leave the amount empty to refund the whole payment.";
      default:
        break;
    }
    if (exceedsPayment(typed, draft.payment.credited_inr)) {
      return (
        `That is more than the ${formatRupeeRate(draft.payment.credited_inr)} this ` +
        `payment credited. A ` +
        "refund cannot exceed the payment it is against — check the figure, and check " +
        "you are on the right payment."
      );
    }
  }
  const reason = draft.reason.trim();
  if (reason.length < 3) {
    return (
      "Say why this money is going back, in your own words. It is written to the audit " +
      "trail and it is what a later review of an unexplained refund is looking for."
    );
  }
  if (reason.length > 280) {
    return "Keep the reason under 280 characters — the route refuses a longer one.";
  }
  return null;
}

/**
 * Is `amount` greater than `credited`, comparing exact DIGITS?
 *
 * Integer PAISE on both sides, read out of the digit groups — never `Number("2500.10")`,
 * which is the binary float hard rule 7 exists to keep away from money. This is the
 * idiom `lib/api/rateCard.ts::rateToTenThousandths` already uses on this site and it is
 * exact here for the same reason: `RUPEES` bounds the input at eight digits before the
 * point, so the largest value this can produce is 9,999,999,999 paise — three orders of
 * magnitude inside `Number.MAX_SAFE_INTEGER`, and every intermediate is an integer.
 *
 * A value that is not money-shaped never reaches this: `rupeeFault` has already refused
 * it, and the caller returns that refusal first.
 */
function exceedsPayment(amount: string, credited: string): boolean {
  return toPaise(amount) > toPaise(credited);
}

function toPaise(value: string): number {
  const [whole = "0", fraction = ""] = value.trim().split(".");
  return Number(whole || "0") * 100 + Number(`${fraction}00`.slice(0, 2));
}

/** Did the refund land on the ledger, or is it with the provider? */
export type RefundOutcome = "credited" | "accepted";

/**
 * The outcome as a NAMED state rather than a boolean at the call site.
 *
 * Two readers get this wrong in opposite directions — `recorded: false` as a failure, or
 * `recorded: true` assumed — so the screen switches on a word that cannot be misread,
 * and `tests/adminRefund.test.tsx` asserts both branches say the right thing.
 */
export function refundOutcome(result: RefundResult): RefundOutcome {
  return result.recorded ? "credited" : "accepted";
}

/**
 * Issue one refund.
 *
 * `admin:tenants` on the ADMIN session with the tenant in the PATH — the permission is
 * in `MUTATING_PERMISSIONS`, so D-22 would correctly refuse an impersonating one.
 *
 * **No `confirmAction`**, because the route accepts no confirmation header and a header
 * the API ignores is a confirmation of nothing (`credits.ts` states the rule). The human
 * confirmation this act does need is the re-keyed payment reference on the screen.
 *
 * It invalidates the wallet whichever outcome came back — `credited` moved the balance,
 * and `accepted` moved nothing YET but leaves a refund the next reader must see
 * reflected the moment the webhook lands.
 */
export function useIssueRefund(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: RefundDraft) => {
      const body: RefundIn = {
        payment_id: draft.payment.payment_ref,
        reason: draft.reason.trim(),
      };
      const amount = refundAmount(draft);
      // OMITTED, not `null`: absent means "the whole top-up recorded for this payment",
      // which the route reads off the ledger itself.
      if (amount !== undefined) body.amount_inr = amount;
      return apiRequest<RefundResult>(session, refundsPath(tenantId), {
        method: "POST",
        body,
      });
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: creditsKey(tenantId) }),
  });
}

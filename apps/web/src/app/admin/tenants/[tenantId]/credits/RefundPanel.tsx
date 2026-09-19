"use client";

import { useState } from "react";
import { CheckCircle2, Clock, Info, TriangleAlert } from "lucide-react";

import {
  Card,
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import type { Credits, Payment } from "@/lib/api/credits";
import {
  refundBlockReason,
  refundConfirmationWord,
  refundOutcome,
  useIssueRefund,
  type RefundResult,
} from "@/lib/api/refunds";

import { Field, describedBy } from "./fields";

/**
 * REFUNDS — the one control on this screen where money leaves the building.
 *
 * `POST /v1/admin/tenants/{id}/refunds` shipped complete — a claim table, a provider
 * call outside any transaction, a ceiling enforced by a committed row, a migration
 * arguing why no lock can span a vendor call — with NO caller. A client owed money could
 * be refunded only by a hand-assembled request against production, or in the provider's
 * own dashboard, where no ledger entry follows and the wallet quietly disagrees with the
 * bank for ever.
 *
 * ## THE OUTCOME HAS TWO SHAPES AND BOTH ARE SUCCESS
 *
 * `recorded: true` — the provider reported it already PROCESSED, so the compensating
 * ledger entry is written and the balance below is the wallet after it.
 * `recorded: false` — **accepted and in flight.** The provider has it; the entry lands
 * when the `refund.processed` webhook arrives, deduped on the refund id so it can only
 * be written once.
 *
 * Rendering the second as a failure is the expensive defect and it is the reason this
 * panel exists in the shape it does: an operator who reads "not recorded" as "did not
 * work" issues the refund again, and when that also says "not recorded" they go to the
 * provider's dashboard, where a second refund for a slightly different amount is one
 * click and lands on no ledger at all. So `false` reads as ACCEPTED, with the processing
 * window, and the words "did not" appear nowhere near it.
 *
 * ## THE CONFIRMATION IS THE PAYMENT'S REFERENCE, AND THE API DID NOT ASK FOR IT
 *
 * The route carries no step-up. This panel adds one anyway, which is the opposite call
 * from the billing motion and the carrier decision — and for the opposite reason. Those
 * are reversible by the same control; this is not reversible at all: the money has left,
 * `credit_ledger` is append-only, and the repair for a wrong refund is asking the client
 * to pay again. Ceremony belongs on the act that cannot be taken back.
 *
 * The typed word is the payment's own reference rather than a fixed word, for the reason
 * the top-up form on this screen already states: `REFUND` becomes muscle memory within a
 * week, a reference is different every time, and re-keying it is simultaneously the check
 * that this is the payment the operator meant.
 *
 * ## WHAT THIS CANNOT REFUND, SAID OUT LOUD
 *
 * The refund goes to the PAYMENT PROVIDER. A wallet credited from a bank transfer — the
 * form above this one, where an operator types a UTR off a statement — has a reference
 * the provider has never seen, so the provider refuses it and nothing moves. `PaymentOut`
 * carries no field saying which kind a payment is, so this panel does not guess: it says
 * which payments it can move, and renders the provider's own refusal when one comes.
 */
export function RefundPanel({
  clientName,
  wallet,
  tenantId,
  session,
}: {
  clientName: string;
  wallet: Credits;
  tenantId: string;
  session: Parameters<typeof useIssueRefund>[0];
}) {
  const refund = useIssueRefund(session, tenantId);
  const write = useAdminAccess("admin:tenants", "refund a payment");
  const [paymentRef, setPaymentRef] = useState("");
  const [amountInr, setAmountInr] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const payment = wallet.payments.find((row) => row.payment_ref === paymentRef) ?? null;

  if (wallet.payments.length === 0) {
    // Not a disabled form. There is genuinely no payment on this wallet to refund, and a
    // form over none reads as though a refund were something one invents — the same call
    // the restatement panel makes, for the same reason.
    return (
      <Card title="Refund a payment">
        <p className="text-sm text-ink-muted">
          {/* Deliberately NOT the restatement panel's opening clause, which says the same
              thing about the same wallet: two cards leading with one identical sentence
              read as a rendering fault, and a screen reader hears it twice in a row. */}
          There is nothing here to refund — no payment has reached this wallet. A refund
          always names a payment we already hold; it cannot create one. Credit given as a
          gesture is taken back with a compensating adjustment instead.
        </p>
      </Card>
    );
  }

  const draft = payment ? { payment, amountInr, reason } : null;
  const blocked = draft ? refundBlockReason(draft) : null;
  const confirmWord = payment ? refundConfirmationWord(payment) : "";
  const confirmed = payment !== null && confirm.trim() === confirmWord;
  const ready =
    write.allowed && draft !== null && blocked === null && confirmed && !refund.isPending;

  return (
    <Card title="Refund a payment">
      <p className="-mt-2 text-xs text-ink-muted">
        Sends money back to {clientName} at the payment provider AND records the matching
        entry on this wallet, so the ledger and the bank keep agreeing.{" "}
        <span className="font-semibold">This cannot be undone</span> — the money leaves,
        and the ledger is append-only. It is recorded against your name.
      </p>

      <NoticeBox
        tone="neutral"
        icon={<Info className="h-5 w-5" />}
        title="Only a payment the provider captured"
        className="mt-3"
      >
        <p className="mt-1 text-xs opacity-90">
          A wallet credited from a BANK TRANSFER — a UTR typed off a statement — has a
          reference the payment provider has never seen, and it will refuse the refund.
          Send that money back by bank transfer and record a compensating adjustment
          instead, so the ledger still matches what left the account.
        </p>
      </NoticeBox>

      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready || draft === null) return;
          refund.mutate(draft, {
            onSuccess: () => {
              // Cleared on success only: a form still holding the refund the server has
              // answered for invites a second click, and the second click of a refund is
              // the mistake this whole panel is arranged around.
              setPaymentRef("");
              setAmountInr("");
              setReason("");
              setConfirm("");
            },
          });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <Field
          label="Payment to refund"
          id="refund-payment"
          hint="One line per payment, with what it has credited so far. Chosen from the wallet, never typed."
          error={null}
        >
          <select
            id="refund-payment"
            value={paymentRef}
            disabled={!write.allowed}
            onChange={(event) => {
              setPaymentRef(event.target.value);
              // The confirmation names the payment. Changing the payment must invalidate
              // it, or a refund is issued against one payment under a word typed for
              // another — which is precisely the mistake the re-keying exists to catch.
              setConfirm("");
              refund.reset();
            }}
            aria-describedby={describedBy("refund-payment", false)}
            className={FIELD}
          >
            <option value="">— choose a payment —</option>
            {wallet.payments.map((option: Payment) => (
              <option key={option.payment_ref} value={option.payment_ref}>
                {option.payment_ref} · {formatINR(option.credited_inr)} ·{" "}
                {formatIST(option.first_at)}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="How much to refund"
          id="refund-amount"
          hint={
            payment
              ? `Leave empty to refund the whole ${formatINR(payment.credited_inr)}. Digits only for a partial refund — no commas, no ₹ sign.`
              : "Leave empty to refund the whole payment; digits only for part of it."
          }
          error={null}
        >
          <input
            id="refund-amount"
            type="text"
            inputMode="decimal"
            value={amountInr}
            disabled={!write.allowed || payment === null}
            onChange={(event) => {
              setAmountInr(event.target.value);
              refund.reset();
            }}
            aria-describedby={describedBy("refund-amount", false)}
            className={FIELD}
          />
        </Field>

        <Field
          label="Why"
          id="refund-reason"
          hint="Your own words, up to 280 characters. Written to the audit trail — it is what a later review of money leaving is looking for."
          error={null}
        >
          <textarea
            id="refund-reason"
            rows={2}
            maxLength={280}
            value={reason}
            disabled={!write.allowed || payment === null}
            onChange={(event) => {
              setReason(event.target.value);
              refund.reset();
            }}
            aria-describedby={describedBy("refund-reason", false)}
            className={FIELD}
          />
        </Field>

        <Field
          label="Type the payment reference again to confirm"
          id="refund-confirm"
          hint={
            payment
              ? `Type ${confirmWord}. Money leaves when you press the button and it cannot be recalled.`
              : "Choose a payment above first; this field confirms that payment."
          }
          error={null}
        >
          <input
            id="refund-confirm"
            type="text"
            value={confirm}
            disabled={!write.allowed || payment === null}
            onChange={(event) => setConfirm(event.target.value)}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            aria-describedby={describedBy("refund-confirm", false)}
            className={FIELD}
          />
        </Field>

        {blocked && (
          <NoticeBox tone="warn" icon={<TriangleAlert className="h-5 w-5" />}>
            <p className="text-xs">{blocked}</p>
          </NoticeBox>
        )}

        <button type="submit" className={PRIMARY_BUTTON} disabled={!ready}>
          {refund.isPending ? "Refunding…" : "Refund this payment"}
        </button>
      </form>

      {refund.error != null && <ProblemNotice error={refund.error} />}
      {refund.data && <Refunded result={refund.data} clientName={clientName} />}
    </Card>
  );
}

/**
 * What happened — switched on a NAMED outcome, never on a raw boolean at the call site.
 *
 * Both arms are success. The difference is only WHERE the refund currently is, and each
 * arm says what the operator should do next, which in both cases is "nothing".
 */
function Refunded({ result, clientName }: { result: RefundResult; clientName: string }) {
  switch (refundOutcome(result)) {
    case "credited":
      return (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 className="h-5 w-5" />}
          title={`${formatINR(result.amount_inr)} refunded to ${clientName}`}
          className="mt-4"
        >
          <p className="mt-1 text-xs opacity-90">
            The provider has processed it and the matching entry is on this wallet.
            {result.balance_inr !== null
              ? ` Balance is now ${formatINR(result.balance_inr)}.`
              : // A STATED ABSENCE, never ₹0.00: the route returns a balance only when
                // the ledger entry was written in this request, and "we did not derive
                // it" is a different fact from "the wallet is empty".
                " The wallet balance was not reported with this answer — the ledger below is the figure to read."}{" "}
            Their bank typically shows it within {result.processing_days} days. Nothing
            further to do; do not issue it again.
          </p>
          <p className="mt-2 text-xs opacity-90">
            Provider reference <span className="font-mono">{result.refund_id}</span>.
          </p>
        </NoticeBox>
      );
    case "accepted":
      return (
        <NoticeBox
          tone="ok"
          icon={<Clock className="h-5 w-5" />}
          title={`${formatINR(result.amount_inr)} accepted by the provider`}
          className="mt-4"
        >
          <p className="mt-1 text-xs opacity-90">
            {/* THE SENTENCE THIS WHOLE PANEL IS ARRANGED AROUND. It is not a failure and
                it is not a partial success: the refund is issued and in flight, and the
                wallet entry is written automatically when the provider confirms it. */}
            The refund is issued and on its way — it has not settled yet, so this wallet
            does not show it. The entry appears by itself when the provider confirms,
            usually within {result.processing_days} days.{" "}
            <span className="font-semibold">Do not issue it again</span>: a second refund
            is a second amount out of our account for the same payment.
          </p>
          <p className="mt-2 text-xs opacity-90">
            Provider reference <span className="font-mono">{result.refund_id}</span> — quote
            it if you have to ask them where the money is.
          </p>
        </NoticeBox>
      );
  }
}

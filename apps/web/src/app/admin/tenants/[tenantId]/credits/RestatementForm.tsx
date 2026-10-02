"use client";

import { useState } from "react";
import { CheckCircle2, Info, Lock, TriangleAlert } from "lucide-react";

import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatINR,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import type { useAdminAccess } from "@/app/admin/access";
import {
  restatementAmountProblem,
  type Credits,
  type RestatementResult,
  type useRecordRestatement,
} from "@/lib/api/credits";

import { Field, describedBy } from "./fields";
import { LotRestatementReceipt } from "./lots";

/**
 * PUT RIGHT A PAYMENT RECORDED FOR LESS THAN THE BANK MOVED (D-89).
 *
 * Re-recording the reference is refused as a conflict, which is right — that refusal stops
 * one transfer being credited twice. The workaround this replaces was a second top-up under
 * an invented reference like `UTR-123-part2`, which breaks reconciliation because the wallet
 * then shows two payments where the bank shows one.
 *
 * - **It picks a PAYMENT, not a ledger entry**, from `wallet.payments`, the server's
 *   one-line-per-bank-transfer view.
 * - **The operator types the TOTAL the bank moved, never the difference.** A difference is a
 *   subtraction a human does at 2am, and one done wrong lands as a real credit that reads
 *   correct for ever; a total is transcribed. The label, the hint, the notice and the
 *   outstanding-step line all say "total" for that reason.
 * - **The confirmation goes on the wire for every restatement and carries the amount.**
 */

interface Restatement {
  paymentRef: string;
  /** THE TOTAL THE BANK MOVED. Never the difference; the server works that out. */
  total: string;
  /** Typed a second time. Double keying, on the field that decides how much appears. */
  confirm: string;
  reason: string;
}

const NO_RESTATEMENT: Restatement = { paymentRef: "", total: "", confirm: "", reason: "" };

export function RestatementForm({
  clientName,
  wallet,
  restate,
  write,
  initialPaymentRef,
}: {
  clientName: string;
  wallet: Credits;
  restate: ReturnType<typeof useRecordRestatement>;
  write: ReturnType<typeof useAdminAccess>;
  /** Pre-selected from a payment row's menu. Still visible and changeable in the select. */
  initialPaymentRef?: string;
}) {
  const [draft, setDraft] = useState<Restatement>(() => ({
    ...NO_RESTATEMENT,
    paymentRef: initialPaymentRef ?? "",
  }));
  const set = (key: keyof Restatement, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    restate.reset();
  };

  const payment = wallet.payments.find((p) => p.payment_ref === draft.paymentRef) ?? null;
  const total = draft.total.trim();
  const totalProblem = total === "" ? null : restatementAmountProblem(draft.total);
  const totalReady = total !== "" && totalProblem === null;
  const confirmed = totalReady && draft.confirm.trim() === total;
  const reason = draft.reason.trim();
  const reasonReady = reason.length >= 3;
  const ready =
    write.allowed && payment !== null && confirmed && reasonReady && !restate.isPending;

  if (wallet.payments.length === 0) {
    // A restatement always names a payment we have already recorded — it cannot create one.
    return (
      <p className="text-sm text-ink-muted">
        No payment has been recorded on this wallet, so there is none to restate. This
        repairs a payment we entered for too little; it never creates one.
      </p>
    );
  }

  return (
    <div>
      <p className="text-xs text-ink-muted">
        For a bank transfer entered for less than it actually moved — ₹5,000 typed for a
        ₹50,000 UTR. The difference is credited against the SAME reference, so the wallet
        still shows one payment and the ledger still matches the statement.
      </p>

      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (payment === null) return;
          restate.mutate(
            { payment, correctedAmountInr: total, reason },
            { onSuccess: () => setDraft(NO_RESTATEMENT) },
          );
        }}
      >
        <Field
          label="Payment to restate"
          id="restate-payment"
          hint="One line per bank transfer, with what it has credited so far. Chosen from the wallet, never typed — this repairs a payment we already recorded and cannot invent one."
          error={null}
        >
          <select
            id="restate-payment"
            value={draft.paymentRef}
            disabled={!write.allowed}
            onChange={(event) => set("paymentRef", event.target.value)}
            aria-describedby={describedBy("restate-payment", false)}
            className={FIELD}
          >
            <option value="">Choose the payment that was under-recorded…</option>
            {wallet.payments.map((option) => (
              <option key={option.payment_ref} value={option.payment_ref}>
                {`${option.payment_ref} · ${formatINR(option.credited_inr)} credited · ${formatIST(
                  option.first_at,
                )}`}
              </option>
            ))}
          </select>
        </Field>

        {payment && (
          <NoticeBox
            tone="neutral"
            icon={<Info aria-hidden className="h-5 w-5" />}
            title={`${payment.payment_ref} credits ${formatINR(payment.credited_inr)} today`}
          >
            <p className="mt-1 text-xs">
              Enter the <span className="font-semibold">total the bank moved</span>, not
              the difference — the amount to credit is worked out on the server, from
              this figure. Recorded on {formatIST(payment.first_at)}
              {payment.entries > 1 ? (
                <>
                  {" "}
                  across <span className="font-semibold">{payment.entries} ledger
                  entries</span>, because it has been restated before
                </>
              ) : null}
              .
            </p>
          </NoticeBox>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Total the bank moved (₹)"
            id="restate-total"
            hint="The whole amount on the statement line — 50000.00, not the 45000.00 that is missing. Digits only; it reaches the API as the exact string you type."
            error={totalProblem}
          >
            <input
              id="restate-total"
              value={draft.total}
              disabled={!write.allowed}
              onChange={(event) => set("total", event.target.value)}
              inputMode="decimal"
              autoComplete="off"
              aria-describedby={describedBy("restate-total", totalProblem !== null)}
              aria-invalid={totalProblem !== null}
              className={FIELD}
            />
          </Field>

          <Field
            label="Type the total again"
            id="restate-total-confirm"
            hint="Typed twice because this figure decides how much money appears on the client's wallet, and it also travels in the confirmation the API demands."
            error={
              draft.confirm.trim() !== "" && totalReady && !confirmed
                ? "These two do not match. Read the total off the statement rather than pasting one into the other."
                : null
            }
          >
            <input
              id="restate-total-confirm"
              value={draft.confirm}
              disabled={!write.allowed}
              onChange={(event) => set("confirm", event.target.value)}
              inputMode="decimal"
              autoComplete="off"
              aria-describedby={describedBy(
                "restate-total-confirm",
                draft.confirm.trim() !== "" && totalReady && !confirmed,
              )}
              className={FIELD}
            />
          </Field>
        </div>

        <Field
          label="Why this was under-recorded (required)"
          id="restate-reason"
          hint="Stored on the entry and on the audit record, in your words. A credit that appears on a client's wallet with no explanation is the one nobody ever complains about — write the sentence that answers it months later."
          error={
            draft.reason.trim() !== "" && !reasonReady
              ? "Say why in at least a few words."
              : null
          }
        >
          <input
            id="restate-reason"
            value={draft.reason}
            disabled={!write.allowed}
            onChange={(event) => set("reason", event.target.value)}
            maxLength={500}
            aria-describedby={describedBy(
              "restate-reason",
              draft.reason.trim() !== "" && !reasonReady,
            )}
            aria-invalid={draft.reason.trim() !== "" && !reasonReady}
            className={FIELD}
          />
        </Field>

        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON: the act, that it cannot be undone, the
            mistake this control admits and how it is recovered, then that it is recorded. */}
        <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div className="min-w-0">
            <p className="font-semibold text-ink">
              {payment && totalReady
                ? `This makes ${payment.payment_ref} credit ${formatINR(total)} on ${clientName}'s wallet`
                : `This puts more real money on ${clientName}'s wallet`}
            </p>
            <p className="mt-1 text-ink-muted">
              The difference between the total you type and what the payment credits today
              is credited as a second entry against the same reference. It is spendable on
              their very next call.
            </p>
            <p className="mt-1 text-ink-muted">
              <span className="font-semibold">This one cannot be undone either.</span> If
              you type the DIFFERENCE instead of the total, or overshoot, the ledger keeps
              the entry — the repair is to take the excess back with “Correct a wrong
              entry” above, which is bounded by what this entry put in.
            </p>
            <p className="mt-1 text-xs text-ink-faint">
              Recorded in the audit log against your admin account with the reason you type
              above, in the same transaction as the money. The confirmation the route
              demands carries the exact total, so it cannot be reused for a different one.
            </p>
          </div>
        </div>

        {restate.error != null && (
          <WriteFailure error={restate.error} actionLabel="Restate this payment" />
        )}
        {restate.data && <RestatementOutcome result={restate.data} clientName={clientName} />}

        <button
          type="submit"
          title={write.reason ?? undefined}
          disabled={!ready}
          className={PRIMARY_BUTTON}
        >
          {restate.isPending
            ? "Restating…"
            : payment && totalReady
              ? `Restate ${payment.payment_ref} to ${formatINR(total)}`
              : "Restate this payment"}
        </button>

        <RestrictionNote reason={write.reason} />

        {write.allowed && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {!payment
              ? "Pick the payment that was under-recorded — a restatement always names one bank transfer."
              : !totalReady
                ? "Enter the TOTAL the bank moved, not the difference."
                : !confirmed
                  ? "Type the total a second time to confirm. The two have to match exactly."
                  : !reasonReady
                    ? "Say why. It is stored on the entry and on the audit record."
                    : "Ready. This cannot be taken back once it is written."}
          </p>
        )}
      </form>
    </div>
  );
}

/**
 * What the restatement did. `credited_inr` is the assertion this control exists to make
 * true — ONE reference, ONE figure, comparable by eye against the statement line.
 */
function RestatementOutcome({
  result,
  clientName,
}: {
  result: RestatementResult;
  clientName: string;
}) {
  if (!result.recorded) {
    return (
      <NoticeBox
        tone="neutral"
        icon={<Info aria-hidden className="h-5 w-5" />}
        title="Already restated — nothing was credited"
      >
        <p className="mt-1 text-xs">
          <span className="font-mono">{result.payment_ref}</span> was already restated to{" "}
          {formatINR(result.credited_inr)}, so no second entry was written and the balance
          did not move. It stands at {formatINR(result.balance_inr)}.{" "}
          <span className="font-semibold">
            This client has not been credited twice — this is the restatement&apos;s own
            reference doing its job.
          </span>
        </p>
        <p className="mt-2 text-xs">
          The entry that already existed:{" "}
          <span className="font-mono">{result.entry_id}</span>. If the statement shows
          MORE again, restate it to that higher total; the amounts never add up twice.
        </p>
      </NoticeBox>
    );
  }
  return (
    <NoticeBox
      tone="ok"
      icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
      title={`Restated — ${formatINR(result.added_inr)} credited to ${clientName}`}
    >
      <p className="mt-1 text-xs">
        <span className="font-mono">{result.payment_ref}</span> now credits{" "}
        {formatINR(result.credited_inr)} — one bank transfer, whatever it took on the
        ledger to record it. The wallet holds {formatINR(result.balance_inr)}
        {result.is_low ? ", which is still under the low-balance line." : "."}
      </p>
      <p className="mt-2 text-xs">
        The second entry is <span className="font-mono">{result.entry_id}</span>, on the
        ledger below as <span className="font-mono">{result.ref}</span> and there
        permanently. The entry it completes is still there too.
      </p>
      <LotRestatementReceipt result={result} />
    </NoticeBox>
  );
}

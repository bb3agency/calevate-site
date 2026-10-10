"use client";

import { useState } from "react";
import { CheckCircle2, Info, Lock, TriangleAlert } from "lucide-react";

import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  formatINR,
  formatIST,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  normalizeReference,
  referenceCaution,
  referenceProblem,
  rupeeProblem,
  type Credits,
  type TopUpResult,
  type useRecordTopUp,
} from "@/lib/api/credits";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { Field, describedBy } from "./fields";
import { LotReceipt } from "./lots";

/**
 * RECORD A PAYMENT — money that has already arrived by bank transfer, read off a statement.
 *
 * ## THE UTR IS THE IDEMPOTENCY KEY, AND A HUMAN TRANSCRIBES IT
 *
 * The server keys on the exact string (`find_topup`, scoped to `reason = 'topup'`, under the
 * per-tenant advisory lock), so:
 *
 * - **Repeating one is SAFE and is said so.** A second submission of a reference already on
 *   the wallet returns 200 with `recorded: false` and moves nothing. Rendering it as a
 *   failure makes the operator retry by another route; rendering it as a credit makes them
 *   believe they paid twice. It gets its own outcome panel.
 * - **MISTYPING one is the real double-credit path.** A wrong reference is credited happily,
 *   and the right one is then credited on top. Three guards, in the order they bite: the
 *   reference is typed TWICE (double keying, the standard for hand-entered bank
 *   identifiers); a reference already visible on the ledger is called out before the click;
 *   and an internal space raises a caution rather than being normalized away, because
 *   normalizing it here would make the console's key differ from the ledger's.
 *
 * The typed confirmation is the reference itself rather than a fixed word: `CREDIT` becomes
 * muscle memory, a reference is different every time. No `X-Confirm-Action` is sent because
 * the route accepts none; admin-realm MFA (D-68) answers WHO, this answers WHICH payment.
 *
 * The form opens EMPTY: a prefilled amount or reference would be a payment nobody read off a
 * statement.
 */

interface Draft {
  amount: string;
  reference: string;
  /** Typed a second time. Double keying. */
  confirm: string;
  note: string;
}

const EMPTY: Draft = { amount: "", reference: "", confirm: "", note: "" };

export function RecordForm({
  clientName,
  wallet,
  save,
  write,
}: {
  clientName: string;
  wallet: Credits;
  save: ReturnType<typeof useRecordTopUp>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const set = (key: keyof Draft, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    // The last result described a request that is no longer the one in the form.
    save.reset();
  };

  /*
   * THE TOP-UP FORM, DECLARED TO THE SCREEN ASSISTANT while this drawer is open — and
   * three of its four controls are deliberately NOT fillable. An assistant that could type
   * the amount and the bank reference would defeat the double keying (a machine filling
   * both makes them agree by construction). It can still READ them ("this reference is
   * already on the ledger"); `useCopilotConversation` drops a fill naming a read-only
   * field. The note is fillable because it is prose about the payment, not the payment.
   * The bank reference identifies a TRANSACTION, not a person, so it is not redacted.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/credits",
    title: "Record a credit top-up",
    realm: "admin",
    fields: [
      {
        id: "topup-ref",
        label: "Bank reference",
        type: "text",
        value: draft.reference,
        writable: false,
        help: "Transcribed from the bank statement by a human. Never machine-filled.",
      },
      {
        id: "topup-ref-confirm",
        label: "Bank reference (typed again)",
        type: "text",
        value: draft.confirm,
        writable: false,
        help: "Double keying. Filling this from anything but a second reading would defeat it.",
      },
      {
        id: "topup-amount",
        label: "Amount (₹)",
        type: "text",
        value: draft.amount,
        writable: false,
        help: "Transcribed from the statement by a human. Never machine-filled.",
      },
      { id: "topup-note", label: "Note", type: "textarea", value: draft.note },
    ],
    facts: [
      { key: "client", label: "Client", value: clientName },
      { key: "balance_inr", label: "Calling credit on the ledger now (₹)", value: wallet.balance_inr },
    ],
    apply: (items) => {
      const note = items.find((item) => item.field_id === "topup-note");
      if (note !== undefined) setDraft((previous) => ({ ...previous, note: asText(note.value) }));
    },
  });

  const reference = normalizeReference(draft.reference);
  const amount = draft.amount.trim();
  // Field problems are shown only once there is something to be wrong about.
  const amountProblem = amount === "" ? null : rupeeProblem(draft.amount);
  const referenceIssue = reference === "" ? null : referenceProblem(draft.reference);
  const caution = referenceCaution(draft.reference);
  const amountReady = amount !== "" && amountProblem === null;
  const referenceReady = reference !== "" && referenceIssue === null;
  const confirmed = referenceReady && normalizeReference(draft.confirm) === reference;

  // Already on the ledger we can SEE — a preview, never the enforcement. One-directional:
  // the list is the newest entries and the server checks the whole ledger, so this warns
  // and never reassures, and never blocks (a repeat is harmless and is how one finds out).
  const alreadyOnLedger = referenceReady
    ? wallet.entries.find((entry) => entry.reason === "topup" && entry.ref === reference)
    : undefined;

  const ready = write.allowed && amountReady && confirmed && !save.isPending;

  // Which step is outstanding, beside the button. The permission case is absent because
  // `RestrictionNote` renders it directly under the button.
  const outstanding = !write.allowed
    ? null
    : !referenceReady
      ? "Type the bank's reference for this payment first — it is what stops the same payment being credited twice."
      : !confirmed
        ? "Type the reference a second time to confirm. The two have to match exactly."
        : !amountReady
          ? "Enter the amount to credit."
          : null;

  return (
    <div>
      <p className="text-meta text-ink-muted">
        For money that has already arrived — a NEFT or UPI transfer read off the bank
        statement. This does not take a payment; it records one.
      </p>

      <form
        className="mt-4 space-y-4"
        // Our own refusals are written beside each control; `noValidate` so a rule added
        // later cannot be answered in the browser's language.
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(
            {
              amountInr: amount,
              paymentRef: reference,
              note: draft.note.trim() === "" ? null : draft.note.trim(),
            },
            // The result panel carries everything that was sent: a form still holding a
            // reference the server has answered for invites a second click that can only
            // be a replay.
            { onSuccess: () => setDraft(EMPTY) },
          );
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Bank reference (UTR / RRN)"
            id="topup-ref"
            hint="Exactly as the statement prints it. This is what the ledger keys on: the same reference twice credits nothing, and the same reference for a different amount is refused."
            error={referenceIssue}
          >
            <input
              id="topup-ref"
              value={draft.reference}
              disabled={!write.allowed}
              onChange={(event) => set("reference", event.target.value)}
              maxLength={120}
              autoComplete="off"
              spellCheck={false}
              aria-describedby={describedBy("topup-ref", referenceIssue !== null)}
              aria-invalid={referenceIssue !== null}
              className={`${FIELD} font-mono`}
            />
          </Field>

          <Field
            label="Type the reference again"
            id="topup-ref-confirm"
            hint="Typed twice because it is transcribed by hand: a reference entered wrongly is credited anyway, and the correct one is then credited on top of it."
            error={
              draft.confirm.trim() !== "" && !confirmed
                ? "These two do not match. Compare them against the statement rather than pasting one into the other."
                : null
            }
          >
            <input
              id="topup-ref-confirm"
              value={draft.confirm}
              disabled={!write.allowed}
              onChange={(event) => set("confirm", event.target.value)}
              maxLength={120}
              autoComplete="off"
              spellCheck={false}
              aria-describedby={describedBy(
                "topup-ref-confirm",
                draft.confirm.trim() !== "" && !confirmed,
              )}
              className={`${FIELD} font-mono`}
            />
          </Field>

          <Field
            label="Amount received (₹)"
            id="topup-amount"
            hint="Rupees and paise, as digits — 2500.10. Never rounded and never parsed on the way out: it reaches the API as the exact string you type."
            error={amountProblem}
          >
            <input
              id="topup-amount"
              value={draft.amount}
              disabled={!write.allowed}
              onChange={(event) => set("amount", event.target.value)}
              inputMode="decimal"
              autoComplete="off"
              aria-describedby={describedBy("topup-amount", amountProblem !== null)}
              aria-invalid={amountProblem !== null}
              className={FIELD}
            />
          </Field>

          <Field
            label="Note (optional)"
            id="topup-note"
            hint="Stored on the entry. The statement date, or which of two transfers this was — whatever the next person reading this ledger will wish you had written."
            error={null}
          >
            <input
              id="topup-note"
              value={draft.note}
              disabled={!write.allowed}
              onChange={(event) => set("note", event.target.value)}
              maxLength={500}
              aria-describedby={describedBy("topup-note", false)}
              className={FIELD}
            />
          </Field>
        </div>

        {caution && (
          <NoticeBox tone="warn" icon={<TriangleAlert aria-hidden className="h-4 w-4" />}>
            <p className="text-meta">{caution}</p>
          </NoticeBox>
        )}

        {alreadyOnLedger && (
          <NoticeBox
            tone="warn"
            icon={<Info aria-hidden className="h-5 w-5" />}
            title="That reference is already on this ledger"
          >
            <p className="mt-1">
              It credited {formatINR(alreadyOnLedger.delta_inr)} on{" "}
              {formatIST(alreadyOnLedger.occurred_at)}. Sending it again credits nothing —
              the server returns the entry that already exists. If this is a second,
              genuine payment it has its own reference; reusing this one for a different
              amount is refused as a conflict.
            </p>
          </NoticeBox>
        )}

        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON: the act, then that it cannot be undone,
            then that it is recorded — an operator who reads only the first line has read
            the part that matters. */}
        <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div className="min-w-0">
            <p className="font-semibold text-ink">
              {amountReady
                ? `This puts ${formatINR(amount)} of real money on ${clientName}'s wallet`
                : `This puts real money on ${clientName}'s wallet`}
            </p>
            <p className="mt-1 text-ink-muted">
              It is spendable on their very next call. It is not a quote, a reservation or
              an invoice line — it is the balance their dialling is checked against.
            </p>
            <p className="mt-1 text-ink-muted">
              <span className="font-semibold">There is no undo.</span> This ledger only
              ever grows — the database refuses any edit or deletion — so a credit to the
              wrong client or for the wrong amount is corrected by ADDING a compensating
              entry — “Correct a wrong entry”, below. That is a repair, not an undo: both
              lines stay on the ledger for ever, and the client may already have spent the
              money.
            </p>
            <p className="mt-1 text-meta text-ink-muted">
              Recorded in the audit log against your admin account, in the same
              transaction as the money: a credit with no audit row is not a possible
              state.
            </p>
          </div>
        </div>

        {save.error != null && <ProblemNotice error={save.error} />}
        {save.data && <Outcome result={save.data} />}

        <button
          type="submit"
          title={write.reason ?? undefined}
          disabled={!ready}
          className={PRIMARY_BUTTON}
        >
          {save.isPending
            ? "Recording…"
            : amountReady
              ? `Credit ${formatINR(amount)} to ${clientName}`
              : "Credit this payment"}
        </button>

        <RestrictionNote reason={write.reason} />

        {outstanding && (
          <p className="flex items-start gap-2 text-meta text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {outstanding}
          </p>
        )}
      </form>
    </div>
  );
}

/**
 * What the server did. `recorded` is the whole message: both outcomes are 200, so a screen
 * that rendered one panel for both would leave the operator to work out from a balance
 * whether they had just credited a client twice.
 */
function Outcome({ result }: { result: TopUpResult }) {
  if (!result.recorded) {
    return (
      <NoticeBox
        tone="neutral"
        icon={<Info aria-hidden className="h-5 w-5" />}
        title="Already recorded — nothing was credited"
      >
        <p className="mt-1">
          <span className="font-mono">{result.payment_ref}</span> was already on this
          wallet for {formatINR(result.amount_inr)}, so no second entry was written and
          the balance did not move. It stands at {formatINR(result.balance_inr)}.{" "}
          <span className="font-semibold">
            This client has not been credited twice — this is the reference doing its job.
          </span>
        </p>
        <p className="mt-2 text-meta">
          The entry that already existed:{" "}
          <span className="font-mono">{result.entry_id}</span>. If you expected a NEW
          payment here, the two transfers share a reference on your statement — check it
          before recording anything else.
        </p>
      </NoticeBox>
    );
  }
  return (
    <NoticeBox
      tone="ok"
      icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
      title={`Recorded — ${formatINR(result.amount_inr)} credited`}
    >
      <p className="mt-1">
        Against <span className="font-mono">{result.payment_ref}</span>. The wallet now
        holds {formatINR(result.balance_inr)}
        {result.is_low ? ", which is still under the low-balance line." : "."}
      </p>
      <p className="mt-2 text-meta">
        Entry <span className="font-mono">{result.entry_id}</span>, on the ledger below
        and there permanently.
      </p>
      <LotReceipt lot={result.lot} lead="It opened lot" />
    </NoticeBox>
  );
}

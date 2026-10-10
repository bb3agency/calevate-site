"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Info, Lock, TriangleAlert } from "lucide-react";

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
  adjustmentAmountProblem,
  correctableEntries,
  creditReasonLabel,
  takesCreditAway,
  type AdjustmentResult,
  type Credits,
  type useRecordAdjustment,
} from "@/lib/api/credits";

import { Field, describedBy } from "./fields";
import { LotReceipt } from "./lots";

/**
 * TAKE A WRONG ENTRY BACK — by APPENDING a compensating `adjustment`, never by editing.
 *
 * `credit_ledger` is append-only (hard rule 4, a database trigger). The act is more
 * dangerous than the top-up, in three ways the top-up does not need:
 *
 * - **The target is CHOSEN, never typed.** Entry ids are uuids; picking from the ledger this
 *   screen already read removes a transcription error the server could only catch as a 404,
 *   and lets the panel show what is left to take back. Only entries with something left are
 *   offered — a fully corrected entry is a dead option.
 * - **The amount is double-keyed.** The ceiling beside it is the SERVER's `reversible_inr`;
 *   the console does no decimal arithmetic on money, so it cannot preview the resulting
 *   balance and does not pretend to.
 * - **The confirmation goes on the WIRE**, but only for the direction that takes credit
 *   away — the route's rule. `useRecordAdjustment` builds it.
 *
 * A correction may leave the balance BELOW zero, which stops every client but a managed one
 * both dialling and answering (D-551). That is stated as a CONDITION above the button and
 * answered as a FACT by the server (`stops_dialling`) underneath it.
 */

interface Correction {
  entryId: string;
  amount: string;
  /** Typed a second time. Double keying, on the field that decides how much moves. */
  confirm: string;
  reason: string;
}

const NO_CORRECTION: Correction = { entryId: "", amount: "", confirm: "", reason: "" };

export function CorrectionForm({
  clientName,
  wallet,
  correct,
  write,
  initialEntryId,
}: {
  clientName: string;
  wallet: Credits;
  correct: ReturnType<typeof useRecordAdjustment>;
  write: ReturnType<typeof useAdminAccess>;
  /** Pre-selected from a ledger row's menu. Still visible and changeable in the select. */
  initialEntryId?: string;
}) {
  const [draft, setDraft] = useState<Correction>(() => ({
    ...NO_CORRECTION,
    entryId: initialEntryId ?? "",
  }));
  const set = (key: keyof Correction, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    // The last result described a correction that is no longer the one in the form.
    correct.reset();
  };

  const options = correctableEntries(wallet.entries);
  const entry = options.find((candidate) => candidate.id === draft.entryId) ?? null;
  const amount = draft.amount.trim();
  const amountProblem = amount === "" ? null : adjustmentAmountProblem(draft.amount);
  const amountReady = amount !== "" && amountProblem === null;
  const confirmed = amountReady && draft.confirm.trim() === amount;
  const reason = draft.reason.trim();
  const reasonReady = reason.length >= 3;
  const ready =
    write.allowed && entry !== null && confirmed && reasonReady && !correct.isPending;
  // The DIRECTION, read off the entry exactly as the route derives it.
  const debit = entry !== null && takesCreditAway(entry);

  if (wallet.entries.length === 0) {
    // Not a disabled form: a form over an empty ledger reads as "a correction is a thing
    // you make up".
    return (
      <p className="text-body text-ink-muted">
        Nothing has been written to this ledger, so there is nothing to correct. A
        correction always names the entry it cancels.
      </p>
    );
  }

  return (
    <div>
      <p className="text-meta text-ink-muted">
        For an entry that should not have been made — a payment credited to the wrong
        client, or for more than arrived. The entry stays on the ledger; a new one with
        the opposite sign cancels it.
      </p>

      {options.length === 0 ? (
        <p className="mt-4 text-body text-ink-muted">
          Every entry on this wallet has already been taken back in full, so there is
          nothing left to correct here.
        </p>
      ) : (
        <form
          className="mt-4 space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (entry === null) return;
            correct.mutate(
              { entry, amountInr: amount, reason },
              // Cleared on success only: a form still holding the correction the server
              // has answered for invites a second click that can only be a replay.
              { onSuccess: () => setDraft(NO_CORRECTION) },
            );
          }}
        >
          <Field
            label="Entry to correct"
            id="adjust-entry"
            hint="Chosen from the ledger below, never typed — an entry is identified by a uuid, and a mistyped one is a correction made against nothing. Only entries with something left to take back are listed."
            error={null}
          >
            <select
              id="adjust-entry"
              value={draft.entryId}
              disabled={!write.allowed}
              onChange={(event) => set("entryId", event.target.value)}
              aria-describedby={describedBy("adjust-entry", false)}
              className={FIELD}
            >
              <option value="">Choose the entry that was wrong…</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {`${formatIST(option.occurred_at)} · ${creditReasonLabel(option.reason)} · ${
                    option.delta_inr.startsWith("-") ? "" : "+"
                  }${formatINR(option.delta_inr)}${option.ref ? ` · ${option.ref}` : ""}`}
                </option>
              ))}
            </select>
          </Field>

          {entry && (
            <NoticeBox
              tone="neutral"
              icon={<Info aria-hidden className="h-5 w-5" />}
              title={`${formatINR(entry.reversible_inr)} of this entry can still be taken back`}
            >
              <p className="mt-1">
                It moved {entry.delta_inr.startsWith("-") ? "" : "+"}
                {formatINR(entry.delta_inr)} on {formatIST(entry.occurred_at)}
                {entry.ref ? (
                  <>
                    {" "}
                    against <span className="font-mono">{entry.ref}</span>
                  </>
                ) : null}
                . Correcting it{" "}
                {debit
                  ? "takes credit off this wallet"
                  : "puts credit back on this wallet"}{" "}
                — the direction comes from the entry, so there is no sign for you to get
                right.
              </p>
            </NoticeBox>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Amount to take back (₹)"
              id="adjust-amount"
              hint="Rupees and paise, as digits — 50000.00. Never more than what is left of the entry, and never signed. It reaches the API as the exact string you type."
              error={amountProblem}
            >
              <input
                id="adjust-amount"
                value={draft.amount}
                disabled={!write.allowed}
                onChange={(event) => set("amount", event.target.value)}
                inputMode="decimal"
                autoComplete="off"
                aria-describedby={describedBy("adjust-amount", amountProblem !== null)}
                aria-invalid={amountProblem !== null}
                className={FIELD}
              />
            </Field>

            <Field
              label="Type the amount again"
              id="adjust-amount-confirm"
              hint="Typed twice because this is the field that decides how much money moves, and no entry on this ledger can be taken back."
              error={
                draft.confirm.trim() !== "" && amountReady && !confirmed
                  ? "These two do not match. Read the amount off the entry above rather than pasting one into the other."
                  : null
              }
            >
              <input
                id="adjust-amount-confirm"
                value={draft.confirm}
                disabled={!write.allowed}
                onChange={(event) => set("confirm", event.target.value)}
                inputMode="decimal"
                autoComplete="off"
                aria-describedby={describedBy(
                  "adjust-amount-confirm",
                  draft.confirm.trim() !== "" && amountReady && !confirmed,
                )}
                className={FIELD}
              />
            </Field>
          </div>

          <Field
            label="Why (required)"
            id="adjust-reason"
            hint="Stored on the entry and on the audit record, in your words. “Who took this off the client, and why” is the question this answers months later — write the sentence you would want to find."
            error={
              draft.reason.trim() !== "" && !reasonReady
                ? "Say why in at least a few words."
                : null
            }
          >
            <input
              id="adjust-reason"
              value={draft.reason}
              disabled={!write.allowed}
              onChange={(event) => set("reason", event.target.value)}
              maxLength={500}
              aria-describedby={describedBy(
                "adjust-reason",
                draft.reason.trim() !== "" && !reasonReady,
              )}
              aria-invalid={draft.reason.trim() !== "" && !reasonReady}
              className={FIELD}
            />
          </Field>

          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON: the act, that it cannot be undone, the
              consequence nobody can preview, then that it is recorded. */}
          <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${debit ? "text-danger" : "text-ink-faint"}`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                {!entry
                  ? `This corrects one entry on ${clientName}'s wallet`
                  : debit
                    ? `This takes ${amountReady ? formatINR(amount) : "credit"} back off ${clientName}'s wallet`
                    : `This puts ${amountReady ? formatINR(amount) : "credit"} back on ${clientName}'s wallet`}
              </p>
              <p className="mt-1 text-ink-muted">
                <span className="font-semibold">There is no undo, here either.</span> The
                correction is a new line on the same append-only ledger — the entry it
                cancels stays where it is, because it is the evidence, and correcting the
                correction is another line again.
              </p>
              {/* Every client (D-707: one pricing model), and both directions; `prepaid` is the default tier
                  and is in `PREPAID_TIERS`, and inbound answering stops too (D-551).
                  Guarded by `tests/credit_stop_copy_test.py`. */}
              <p className="mt-1 text-ink-muted">
                A correction may take the balance <span className="font-semibold">below
                zero</span> — a wrong credit that has already been spent cannot be fully
                taken back any other way. That stops the client&apos;s
                their outgoing calls immediately and stops their agents answering incoming
                ones, exactly as an empty wallet does, until you add credit back. The
                answer comes back with the result rather than being guessed here.
              </p>
              <p className="mt-1 text-meta text-ink-muted">
                Recorded in the audit log against your admin account with the reason you
                type above, in the same transaction as the money.
                {debit
                  ? " Taking credit away also sends the confirmation header the route demands for this direction."
                  : ""}
              </p>
            </div>
          </div>

          {correct.error != null && (
            <WriteFailure error={correct.error} actionLabel="Correct this entry" />
          )}
          {correct.data && <CorrectionOutcome result={correct.data} clientName={clientName} />}

          <button
            type="submit"
            title={write.reason ?? undefined}
            disabled={!ready}
            className={PRIMARY_BUTTON}
          >
            {correct.isPending
              ? "Correcting…"
              : entry && amountReady
                ? debit
                  ? `Take ${formatINR(amount)} back off ${clientName}'s wallet`
                  : `Put ${formatINR(amount)} back on ${clientName}'s wallet`
                : "Correct this entry"}
          </button>

          <RestrictionNote reason={write.reason} />

          {write.allowed && (
            <p className="flex items-start gap-2 text-meta text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {!entry
                ? "Pick the entry that was wrong — a correction always cancels a specific line."
                : !amountReady
                  ? "Enter how much of that entry to take back."
                  : !confirmed
                    ? "Type the amount a second time to confirm. The two have to match exactly."
                    : !reasonReady
                      ? "Say why. It is stored on the entry and on the audit record."
                      : "Ready. This cannot be taken back once it is written."}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

/**
 * What the correction did. `recorded` separates "we have just taken ₹50,000 off this
 * client" from "that correction was already made", both 200. `stops_dialling` is the dial
 * gate's own verdict on the balance this write produced.
 */
function CorrectionOutcome({
  result,
  clientName,
}: {
  result: AdjustmentResult;
  clientName: string;
}) {
  const tookCredit = result.delta_inr.startsWith("-");
  return (
    <div className="space-y-3">
      <NoticeBox
        tone={result.recorded ? "ok" : "neutral"}
        icon={
          result.recorded ? (
            <CheckCircle2 aria-hidden className="h-5 w-5" />
          ) : (
            <Info aria-hidden className="h-5 w-5" />
          )
        }
        title={
          result.recorded
            ? `Corrected — ${formatINR(result.delta_inr)} ${tookCredit ? "taken back" : "credited back"}`
            : "Already corrected — nothing moved"
        }
      >
        {result.recorded ? (
          <>
            <p className="mt-1">
              Against entry <span className="font-mono">{result.corrects_entry_id}</span>.
              The wallet now holds {formatINR(result.balance_inr)}
              {result.is_low ? ", which is under the low-balance line." : "."}
            </p>
            <p className="mt-2 text-meta">
              The compensating entry is{" "}
              <span className="font-mono">{result.entry_id}</span>, on the ledger below
              and there permanently. The entry it cancels is still there too.
            </p>
            {/* A correction that CREDITS BACK opens a lot at the list rates (plan §0 Q4);
                one that takes credit away restates the corrected entry's own lot. */}
            <LotReceipt lot={result.lot} lead="It opened lot" />
          </>
        ) : (
          <p className="mt-1">
            A correction of exactly this amount against this entry was already on the
            ledger (<span className="font-mono">{result.entry_id}</span>), so no second
            one was written and the balance did not move. It stands at{" "}
            {formatINR(result.balance_inr)}.{" "}
            <span className="font-semibold">
              This client has not been debited twice — this is the correction&apos;s own
              reference doing its job.
            </span>{" "}
            If a FURTHER correction is genuinely needed, it is for a different amount.
          </p>
        )}
      </NoticeBox>

      {result.stops_dialling && (
        <NoticeBox
          tone="stop"
          icon={<CircleAlert aria-hidden className="h-5 w-5" />}
          title={`${clientName} cannot place or answer calls until this wallet is topped up`}
        >
          {/* Inbound is NOT unaffected: at or below zero every answering agent is silenced
              at the engine and callers hear a short apology
              (`agents/service.py::reconcile_inbound_answering`, D-551). */}
          <p className="mt-1">
            The balance is at or below zero and this account pays from a wallet, so the
            compliance gate refuses every outbound call and their agents have stopped
            answering incoming ones — callers hear a short apology that gives no reason and
            says nothing about the account. If the credit was genuinely theirs, record the
            payment above and both start again straight away; if it was not, this is the
            correct state and they need to pay.
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

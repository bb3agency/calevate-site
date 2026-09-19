"use client";

import { useState } from "react";
import { CheckCircle2, Gift, Info } from "lucide-react";

import {
  Card,
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import {
  MAX_GRANT_INR,
  MIN_GRANT_INR,
  grantAmountProblem,
  grantCeilingProblem,
  mintGrantRef,
  toTwoDecimals,
  useGrantCredits,
  type Credits,
  type GrantResult,
} from "@/lib/api/credits";

import { Field, describedBy } from "./fields";

/**
 * GOODWILL CREDIT — the fourth write on this wallet, and the only one with no payment
 * behind it (D-535).
 *
 * `POST /v1/admin/tenants/{id}/credits/grants` shipped with a ceiling, a mandatory
 * reason, an unconditional step-up and an append-only audit row written in the same
 * transaction as the money — and nothing in this console called it. The one act the
 * founder asked for by name (*"the admin should be able to add any no.of credits without
 * any payments record to any client but it is audited"*) could only be performed by hand
 * against production.
 *
 * ## IT IS NOT A PAYMENT, AND THE SCREEN NEVER LETS THE TWO BLUR
 *
 * That is the founder's own guardrail and it is why this is its own panel rather than a
 * "no payment received" checkbox on the top-up form. A grant lands under its own ledger
 * reason, every statement reports it separately from credit the client bought, and the
 * two lifetime figures — what this wallet has been PAID for and what it has been GIVEN —
 * are printed together at the moment an operator adds to the second. An operator granting
 * the fifth ₹5,000 of the month sees the running total while they do it, not on a screen
 * they might not open.
 *
 * ## The confirmation is the AMOUNT, re-keyed, every time
 *
 * The route's rule, not this screen's: `grant_credits` requires
 * `X-Confirm-Action: grant_credits:<amount to 2dp>` unconditionally. The direction is one
 * way, nothing bounds it but `MAX_GRANT_INR`, and it moves money towards the party who
 * will never report an error in their favour — so the danger scales with the NUMBER and
 * the confirmation carries it. A header captured while granting ₹5,000 cannot be replayed
 * to grant ₹50,000, and an operator who changes the figure has to key it twice.
 *
 * It is also standing in for a control we do not have. The accounting standard for
 * issuing credit out of nothing is segregation of duties; the founder is the only holder
 * of `admin:tenants` today and waived a second approver, so the gap is real and recorded
 * (`credit_routes.credit_grant_confirmation` carries the sources). What is left is the
 * ceiling, the reason, the re-keying and the audit row — and this panel is where three of
 * those four meet a human.
 *
 * ## The reference is minted here, once per opened form
 *
 * A grant has no external identifier, and the route refuses to content-address one:
 * two genuine gifts of ₹5,000 to one client two months apart are ordinary, and collapsing
 * them would report the second as delivered when the client never received it. So a
 * second CLICK converges on one reference and a second DECISION does not — the form mints
 * a fresh one after a successful grant.
 */
export function GrantPanel({
  clientName,
  wallet,
  tenantId,
  session,
}: {
  clientName: string;
  wallet: Credits;
  tenantId: string;
  session: Parameters<typeof useGrantCredits>[0];
}) {
  const grant = useGrantCredits(session, tenantId);
  const write = useAdminAccess("admin:tenants", "give a client credit");
  const [amountInr, setAmountInr] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [grantRef, setGrantRef] = useState(mintGrantRef);

  const amount = amountInr.trim();
  const shape = amount === "" ? null : grantAmountProblem(amountInr);
  const ceiling = shape === null && amount !== "" ? grantCeilingProblem(amount) : null;
  const amountProblem = shape ?? ceiling;
  const amountReady = amount !== "" && amountProblem === null;
  // THE CONFIRMATION IS THE FIGURE AT TWO DECIMALS, which is also what the header
  // carries: `5000` and `5000.00` are the same grant and must confirm the same way, or
  // the ceremony would refuse the calls it exists to permit.
  const confirmWord = amountReady ? toTwoDecimals(amount) : "";
  const confirmed = amountReady && confirm.trim() === confirmWord;
  const reasonReady = reason.trim().length >= 3;
  const ready = write.allowed && amountReady && confirmed && reasonReady && !grant.isPending;

  return (
    <Card title="Give this client credit">
      <p className="-mt-2 text-xs text-ink-muted">
        Credit with <span className="font-semibold">no payment behind it</span> — an
        apology, a pilot, a gesture. It is not a top-up and it is not a correction: it
        lands under its own ledger reason and every statement reports it separately from
        credit {clientName} has bought. It cannot be removed afterwards; a grant made in
        error is taken back with a compensating adjustment.
      </p>

      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        {/* THE TWO LIFETIME FIGURES, SIDE BY SIDE, at the moment one of them is about to
            move. The founder's guardrail is that paid and given never blur; printing only
            the balance here would be exactly that blur. */}
        <div className="text-xs">
          <dt className="text-ink-muted">Paid for, lifetime</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-ink">
            {formatINR(wallet.paid_inr)}
          </dd>
        </div>
        <div className="text-xs">
          <dt className="text-ink-muted">Given, lifetime</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-ink">
            {formatINR(wallet.granted_inr)}
          </dd>
        </div>
      </dl>

      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) return;
          grant.mutate(
            { amountInr: amount, reason: reason.trim(), grantRef },
            {
              onSuccess: () => {
                setAmountInr("");
                setReason("");
                setConfirm("");
                // A NEW REFERENCE FOR A NEW DECISION. Keeping the old one would make the
                // next genuine gift to this client a replay of this one — credited to
                // nobody, reported as recorded.
                setGrantRef(mintGrantRef());
              },
            },
          );
        }}
      >
        <RestrictionNote reason={write.reason} />

        <Field
          label="How much to give"
          id="grant-amount"
          hint={`Digits only, in rupees — between ${formatRupeeRate(MIN_GRANT_INR)} and ${formatRupeeRate(MAX_GRANT_INR)} per grant. A larger gift is granted in parts, each separately confirmed and separately audited.`}
          error={amountProblem}
        >
          <input
            id="grant-amount"
            type="text"
            inputMode="decimal"
            value={amountInr}
            disabled={!write.allowed}
            onChange={(event) => {
              setAmountInr(event.target.value);
              // The confirmation named the OLD figure. Leaving it matched would let a
              // corrected amount be granted under a confirmation typed for another one —
              // and the header the API checks carries the amount, so it would be refused
              // anyway, with a message about ceremony instead of about the typo.
              setConfirm("");
              grant.reset();
            }}
            aria-describedby={describedBy("grant-amount", amountProblem !== null)}
            className={FIELD}
          />
        </Field>

        <Field
          label="Why"
          id="grant-reason"
          hint="Your own words, on the ledger entry and in the audit trail. This is the field a later review of an unexplained credit is looking for."
          error={null}
        >
          <textarea
            id="grant-reason"
            rows={2}
            maxLength={500}
            value={reason}
            disabled={!write.allowed}
            onChange={(event) => {
              setReason(event.target.value);
              grant.reset();
            }}
            aria-describedby={describedBy("grant-reason", false)}
            className={FIELD}
          />
        </Field>

        <Field
          // "Type the GRANT amount" and not "the amount": the correction panel on this
          // same screen already asks an operator to re-key "the amount", and two controls
          // on one page whose labels differ by nothing are two controls a screen reader
          // cannot tell apart.
          label="Type the grant amount again"
          id="grant-confirm"
          hint={
            amountReady
              ? `Type ${confirmWord} — the same figure, to two decimal places.`
              : "Enter a valid amount above first; this field confirms that figure."
          }
          error={null}
        >
          <input
            id="grant-confirm"
            type="text"
            inputMode="decimal"
            value={confirm}
            disabled={!write.allowed || !amountReady}
            onChange={(event) => setConfirm(event.target.value)}
            aria-describedby={describedBy("grant-confirm", false)}
            className={FIELD}
          />
        </Field>

        <button type="submit" className={PRIMARY_BUTTON} disabled={!ready}>
          {grant.isPending ? "Granting…" : "Give this credit"}
        </button>
      </form>

      {grant.error != null && <ProblemNotice error={grant.error} />}
      {grant.data && <Granted result={grant.data} clientName={clientName} />}
    </Card>
  );
}

/** What the grant did — and, when it did nothing, that it did nothing. */
function Granted({ result, clientName }: { result: GrantResult; clientName: string }) {
  if (!result.recorded) {
    return (
      <NoticeBox
        tone="neutral"
        icon={<Info className="h-5 w-5" />}
        title="That grant was already on this wallet"
        className="mt-4"
      >
        <p className="mt-1 text-xs opacity-90">
          {/* A REPLAY, AND IT MOVED NOTHING. Rendering it as a fresh grant would have an
              operator believe they had given the money twice; rendering it as a failure
              would have them give it again for real. */}
          Nothing moved. This is the same grant under the same reference — the balance
          below is what it already was, and {clientName} has not been credited a second
          time.
        </p>
      </NoticeBox>
    );
  }
  return (
    <NoticeBox
      tone="ok"
      icon={<CheckCircle2 className="h-5 w-5" />}
      title={`${formatINR(result.amount_inr)} given to ${clientName}`}
      className="mt-4"
    >
      <p className="mt-1 text-xs opacity-90">
        <Gift aria-hidden className="mr-1 inline h-3.5 w-3.5" />
        Balance is now {formatINR(result.balance_inr)}. Lifetime: paid{" "}
        {formatINR(result.paid_inr)}, given {formatINR(result.granted_inr)}. The entry is
        on the ledger under its own reason, and the audit row carries your words.
        {result.is_low && " The wallet is still below the low-balance threshold."}
      </p>
    </NoticeBox>
  );
}

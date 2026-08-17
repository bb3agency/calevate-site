"use client";

import Link from "next/link";
import { use, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  Info,
  Lock,
  TriangleAlert,
} from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { adminSession, useTenant } from "@/lib/api/admin";
import {
  LEDGER_LIMIT,
  adjustmentAmountProblem,
  correctableEntries,
  creditReasonLabel,
  isFullyReversed,
  normalizeReference,
  referenceCaution,
  referenceProblem,
  restatementAmountProblem,
  rupeeProblem,
  takesCreditAway,
  useCredits,
  useRecordAdjustment,
  useRecordRestatement,
  useRecordTopUp,
  type AdjustmentResult,
  type Credits,
  type LedgerEntry,
  type Payment,
  type RestatementResult,
  type TopUpResult,
} from "@/lib/api/credits";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Credits — the wallet an Indian SMB pays into by bank transfer, and the only screen
 * that puts money on it.
 *
 * `POST /v1/admin/tenants/{id}/credits` has been complete since M1 and had NO caller:
 * `runbooks/topup-payments.md` §3 instructed the operator to hand-assemble the request
 * against production from a bank statement. So the money-in path was a human reading a
 * UTR off a PDF and typing it into a curl. This is that request, with the two things a
 * curl cannot have — the ledger it is about to be appended to, and a confirmation.
 *
 * ## THE UTR IS THE IDEMPOTENCY KEY, AND A HUMAN TRANSCRIBES IT
 *
 * That single fact shapes every control here. The server keys on the exact string
 * (`find_topup`, scoped to `reason = 'topup'`, under the per-tenant advisory lock), so:
 *
 * - **Repeating one is SAFE and is said so.** A second submission of a reference already
 *   on the wallet returns 200 with `recorded: false` and moves nothing. That is neither
 *   a failure nor a fresh credit, and rendering it as either is the defect that matters
 *   most on this screen — one reads as "it did not work" (so the operator does it again
 *   by another route), the other as "I have just credited them twice". It gets its own
 *   panel that says the money did not move and names the entry that already exists.
 * - **MISTYPING one is the real double-credit path**, and it is not obvious: a wrong
 *   reference is credited happily, and when the operator notices and enters the right
 *   one, THAT is credited too — the client now holds twice the money and neither entry
 *   can be removed. Three guards, in the order they bite: the reference is typed TWICE
 *   (double keying, the standard for hand-entered bank identifiers, and the only guard
 *   that catches a transcription error before the write); a reference already visible on
 *   the ledger below is called out before the click; and an internal space — which makes
 *   "ABC 123" and "ABC123" two payments — raises a caution rather than being silently
 *   normalized away, because normalizing it here would make the console's key differ
 *   from the ledger's.
 *
 * ## WHY THE CONFIRMATION IS THE REFERENCE ITSELF
 *
 * The house idiom is a typed confirmation that names the ACT (`HALT`, the target
 * load-shed mode, the tenant id in `spendCapConfirmation`) — see `admin/ops/page.tsx`
 * property 3. Here the act is "credit THIS payment", so the typed word is the payment's
 * own reference, which buys something a fixed word cannot: `CREDIT` becomes muscle
 * memory within a week, and a reference is different every time, so it cannot be typed
 * past. It is simultaneously the double-keying check on the one field where an error is
 * unrecoverable. No `X-Confirm-Action` is sent, because the route accepts none — a
 * header the API ignores is a confirmation of nothing — and admin-realm MFA is already
 * enforced on every admin token in `core/auth.py::verify_token` (D-68). MFA answers WHO
 * holds this session for the next twelve hours; this answers WHICH payment they meant on
 * this click, which is exactly the question a fully verified operator gets wrong.
 *
 * The blast radius is stated ABOVE the control, in the ops order: what it does, then
 * that it cannot be undone, then that it is recorded.
 *
 * ## THE FORM IS WITHHELD WHEN THE LEDGER CANNOT BE READ
 *
 * §52 with money on it. A read that failed must not render as "nothing on this wallet" —
 * that is also a REAL state, and it is the state an operator acts on by crediting. Worse,
 * a write form over a ledger nobody can see removes the one check that catches a payment
 * already recorded by a colleague ten minutes ago. So `unreadable` withholds the form
 * rather than merely leaving it unpopulated, exactly as `/commercials` withholds its own.
 *
 * ## THERE IS NO UNDO — THERE IS A COMPENSATING ENTRY, AND IT IS ON THIS SCREEN
 *
 * `credit_ledger` is append-only (hard rule 4, enforced by a database trigger). A wrong
 * credit is corrected by APPENDING a compensating `adjustment` entry; the wrong row
 * stays, because it is the evidence. This console used to say that and then stop,
 * because no endpoint appended one — "escalate instead of improvising" was the whole
 * remedy for crediting the wrong client. `CorrectionPanel` is that endpoint's control,
 * and its shape follows from the act being MORE dangerous than the top-up above it, in
 * three ways the top-up does not need:
 *
 * - **The target is CHOSEN, never typed.** A correction names a `credit_ledger` row, and
 *   the ids are uuids. Picking from the ledger this screen has already read removes a
 *   transcription error that the server could only catch as a 404 — and it is what lets
 *   the screen show what is left to take back beside the choice.
 * - **The amount is double-keyed, like the reference above**, because it is the field
 *   that decides how much money moves and it is different every time. The ceiling is
 *   the server's (`reversible_inr`), stated next to the field rather than enforced by
 *   arithmetic this console must not do.
 * - **The confirmation goes on the WIRE.** Unlike the top-up, this route takes an
 *   `X-Confirm-Action` — but only for the direction that takes credit away, which is
 *   the route's rule and not this screen's opinion. `useRecordAdjustment` builds it.
 *
 * The consequence stated above the button is the one an operator cannot otherwise see
 * coming: a correction may leave the balance BELOW zero, and for a self-serve or trial
 * client that stops outbound dialling. The server answers whether it did — `stops_dialling`
 * is the dial gate's own predicate — and the outcome panel says so in those words.
 *
 * ## AND THE OPPOSITE MISTAKE HAS ITS OWN CONTROL — `RestatementPanel` (D-89)
 *
 * `CorrectionPanel` can only take credit AWAY. A payment recorded for TOO LITTLE —
 * ₹5,000 typed for a UTR the bank moved ₹50,000 on — had no control at all: re-recording
 * the reference is refused as a conflict (which is right; that refusal is what stops one
 * transfer being credited twice) and the workaround was a second top-up under an invented
 * reference like `UTR-123-part2`. That invention is what breaks reconciliation, because
 * the wallet then shows two payments where the bank shows one.
 *
 * The panel therefore looks NOTHING like the correction panel above it, and each
 * difference is the point:
 *
 * - **It picks a PAYMENT, not a ledger entry.** `wallet.payments` is the server's
 *   reconciliation view — one line per bank transfer, with everything that transfer has
 *   credited. Choosing there is what makes the act "this bank transfer was bigger than
 *   we thought" rather than "this row was wrong".
 * - **The operator types the TOTAL THE BANK MOVED, never the difference**, and the
 *   figure the reference already credits is on screen beside the field. A difference is
 *   a subtraction a human does at 2am with a statement open, and a subtraction done
 *   wrong lands as a real credit that reads correct for ever. A total is transcribed.
 *   The label, the hint and the outstanding-step line all say "total" for that reason.
 * - **The confirmation goes on the wire for EVERY restatement, and it carries the
 *   amount** — the route's rule, argued there: this correction has one direction, no
 *   ceiling above it, and it credits the client. The amount is double-keyed here too, on
 *   the field that decides how much appears.
 */
export default function CreditsPage({
  params,
}: {
  // Next 15: `params` is a Promise, unwrapped with React's `use()` in a client component.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const ledger = useCredits(adminSession(), tenantId);
  // The mutations live here rather than inside the forms: a successful write invalidates
  // the read, and a mutation held inside a form that the read remounts would lose its own
  // confirmation at the moment the write landed (`/commercials` records the same trap).
  const save = useRecordTopUp(adminSession(), tenantId);
  const correct = useRecordAdjustment(adminSession(), tenantId);
  const restate = useRecordRestatement(adminSession(), tenantId);
  // `POST .../credits` is `admin:tenants` (`credit_routes.py` argues why recording a
  // received payment is that permission and not a `billing:write` that does not exist).
  // The admin realm's own identity read answers it — see `@/app/admin/access` for why the
  // client realm's `useWriteAccess` is the wrong instrument on an admin screen.
  const write = useAdminAccess("admin:tenants", "record a payment on this client's wallet");
  // The same permission, a DIFFERENT sentence. Both controls are `admin:tenants`, but a
  // restriction note has to name the control it sits under — two identical explanations
  // on one screen leave an operator unsure which button either of them is about.
  const amend = useAdminAccess("admin:tenants", "correct an entry on this client's wallet");
  // Third control, third sentence. Same permission again — a restriction note has to name
  // the control it sits under, and three identical explanations on one screen would leave
  // an operator unsure which button any of them is about.
  const uprate = useAdminAccess("admin:tenants", "restate a payment on this client's wallet");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  // A 403, a 500 or a dropped connection is not "no such client".
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenantQuery.data) return <EmptyState title="Client not found" />;

  const tenant = tenantQuery.data;
  const state = ledgerState(ledger);

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Credits</h1>
        <p className="text-sm text-ink-muted">
          What is on this client&apos;s wallet, and the payments we have recorded against
          it. Every line is permanent: the ledger is append-only, so a mistake here is
          corrected by adding an entry, never by changing one.
        </p>
      </div>

      {ledger.error && <ProblemNotice error={ledger.error} onRetry={() => ledger.refetch()} />}

      {state.status === "loading" ? (
        <Skeleton rows={6} />
      ) : state.status === "unreadable" ? (
        <LedgerUnreadable />
      ) : (
        <>
          <BalancePanel wallet={state.wallet} />
          <RecordPanel
            clientName={tenant.name}
            wallet={state.wallet}
            save={save}
            write={write}
          />
          {/* Withheld with the form above and for the identical reason: a correction is
              a write against a specific ledger row, so a ledger nobody could read is a
              row nobody can name. */}
          <CorrectionPanel
            clientName={tenant.name}
            wallet={state.wallet}
            correct={correct}
            write={amend}
          />
          {/* Withheld with the two forms above and for the same reason, one step
              stronger: a restatement is measured against what a payment ALREADY
              credits, so a wallet nobody can read is a figure nobody can measure from. */}
          <RestatementPanel
            clientName={tenant.name}
            wallet={state.wallet}
            restate={restate}
            write={uprate}
          />
          <PaymentsTable wallet={state.wallet} />
          <LedgerTable wallet={state.wallet} />
        </>
      )}

      {/* Rendered on every branch, deliberately: it depends on no read, and the operator
          most likely to need it is the one who has just credited the wrong account and
          come back to a screen that will not load. */}
      <CorrectionCard />
    </div>
  );
}

/**
 * The wallet as this screen may know it — three states, and never a fourth.
 *
 * The shape `admin/ops/page.tsx` uses for the dead-letter depth, and here for the same
 * reason in a place it costs more: a balance of ₹0 and a balance we could not read are
 * OPPOSITE facts. One says "this client has nothing left"; the other says "we have no
 * idea what you are about to add to". A `Credits | undefined` collapses them at the
 * first `??`.
 */
type LedgerState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; wallet: Credits };

function ledgerState(query: {
  data: Credits | undefined;
  isError: boolean;
}): LedgerState {
  // Error FIRST. A refetch that fails leaves the previous `data` in place, and a stale
  // balance rendered as the current one is the same lie as an invented one.
  if (query.isError) return { status: "unreadable" };
  if (!query.data) return { status: "loading" };
  return { status: "read", wallet: query.data };
}

/**
 * THE LEDGER WE COULD NOT READ, said as itself — and the form withheld with it.
 *
 * Not "no entries", not "₹0", and not a form with an empty table beside it. Recording a
 * payment against a ledger nobody can see means crediting without the one check that
 * catches a payment a colleague recorded ten minutes ago, on a write that cannot be
 * taken back.
 */
function LedgerUnreadable() {
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="We could not read this wallet, so nothing can be credited to it here"
    >
      <p className="mt-1">
        This screen will not tell you the balance is zero and it will not tell you the
        ledger is empty — it does not know either. The error above says what stopped the
        read; retry it and the form comes back with it.
      </p>
      <p className="mt-2">
        The form is withheld rather than merely blank on purpose. A top-up recorded
        against a ledger nobody can see is a top-up recorded without the one check that
        catches a payment already credited — and no entry on this ledger can be taken
        back.
      </p>
      <p className="mt-2 text-xs">
        If a client is blocked on credit and this will not load,
        runbooks/topup-payments.md §3 carries the request to send by hand.
      </p>
    </NoticeBox>
  );
}

/** The balance, as the SERVER computed it — never re-derived by adding up the deltas. */
function BalancePanel({ wallet }: { wallet: Credits }) {
  const newest = wallet.entries.length > 0 ? wallet.entries[0] : null;
  return (
    <Card title="On the wallet now">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="text-2xl font-bold tabular-nums text-ink">
          {formatINR(wallet.balance_inr)}
        </p>
        <p className="text-xs text-ink-muted">
          {newest
            ? `Newest entry ${formatIST(newest.occurred_at)}`
            : "No entry has ever been written to this ledger."}
        </p>
      </div>

      {/* `is_low` is the SERVER's verdict (`billing.service.LOW_BALANCE_INR`), displayed
          and never computed here — the same rule `tm_registration.is_live` follows on the
          ops screen. A console that decided for itself what counts as low would eventually
          disagree with the gate that actually stops the dialling. */}
      {wallet.is_low && (
        <NoticeBox
          className="mt-4"
          tone="warn"
          icon={<CircleAlert aria-hidden className="h-5 w-5" />}
          title={`Below the low-balance line of ${formatINR(wallet.low_balance_threshold_inr)}`}
        >
          <p className="mt-1">
            An empty wallet stops outbound dialling for a self-serve or trial client
            (the compliance gate reads this balance). A managed client is invoiced
            against their retainer and is not blocked by it — their plan is on the
            Commercials screen.
          </p>
        </NoticeBox>
      )}
    </Card>
  );
}

/** The draft, as strings — the money one because hard rule 7 says so. */
interface Draft {
  amount: string;
  reference: string;
  /** Typed a second time. Double keying: see the screen header. */
  confirm: string;
  note: string;
}

const EMPTY: Draft = { amount: "", reference: "", confirm: "", note: "" };

/**
 * The write.
 *
 * Opens EMPTY, unlike `/commercials`, which prefills from the agreement in effect. A
 * prefilled amount or reference would be a payment nobody read off a statement, and the
 * one thing this form must never make easy is submitting a value the operator did not
 * transcribe.
 */
function RecordPanel({
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

  const reference = normalizeReference(draft.reference);
  const amount = draft.amount.trim();
  // Field problems are shown only once there is something to be wrong about: an empty
  // form is not an error, it is an unstarted one.
  const amountProblem = amount === "" ? null : rupeeProblem(draft.amount);
  const referenceIssue = reference === "" ? null : referenceProblem(draft.reference);
  const caution = referenceCaution(draft.reference);
  const amountReady = amount !== "" && amountProblem === null;
  const referenceReady = reference !== "" && referenceIssue === null;
  const confirmed = referenceReady && normalizeReference(draft.confirm) === reference;

  /**
   * Already on the ledger we can SEE — a preview, never the enforcement.
   *
   * One-directional on purpose. A match here is a fact and is worth saying before the
   * click; an absence proves nothing, because this list is the newest {LEDGER_LIMIT}
   * entries and the server checks the whole ledger. So this warns and never reassures,
   * and it never blocks: submitting a repeat is harmless (the route returns the existing
   * entry) and blocking it would leave the operator with no way to find that out.
   */
  const alreadyOnLedger =
    referenceReady
      ? wallet.entries.find((entry) => entry.reason === "topup" && entry.ref === reference)
      : undefined;

  const ready = write.allowed && amountReady && confirmed && !save.isPending;

  // WHICH STEP IS OUTSTANDING, beside the button — not a restatement of the field
  // messages above, which say what is wrong with a value. The permission case is absent
  // because `RestrictionNote` renders it directly under the button.
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
    <Card title="Record a payment">
      <p className="-mt-2 text-xs text-ink-muted">
        For money that has already arrived — a NEFT or UPI transfer read off the bank
        statement. This does not take a payment; it records one.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(
            {
              amountInr: amount,
              paymentRef: reference,
              note: draft.note.trim() === "" ? null : draft.note.trim(),
            },
            // Cleared on BOTH outcomes, and the result panel carries everything that was
            // sent: a form still holding a reference the server has answered for invites
            // a second click that can only be a replay.
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
            <p className="text-xs">{caution}</p>
          </NoticeBox>
        )}

        {alreadyOnLedger && (
          <NoticeBox
            tone="warn"
            icon={<Info aria-hidden className="h-5 w-5" />}
            title="That reference is already on this ledger"
          >
            <p className="mt-1 text-xs">
              It credited {formatINR(alreadyOnLedger.delta_inr)} on{" "}
              {formatIST(alreadyOnLedger.occurred_at)}. Sending it again credits nothing —
              the server returns the entry that already exists. If this is a second,
              genuine payment it has its own reference; reusing this one for a different
              amount is refused as a conflict.
            </p>
          </NoticeBox>
        )}

        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON: the act, then that it cannot be
            undone, then that it is recorded — the order the ops screen uses, because an
            operator who reads only the first line has read the part that matters. */}
        <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
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
              <span className="font-semibold">There is no undo.</span> This ledger is
              append-only and a database trigger refuses UPDATE and DELETE, so a credit
              to the wrong client or for the wrong amount is corrected by ADDING a
              compensating entry — “Correct a wrong entry”, below. That is a repair, not
              an undo: both lines stay on the ledger for ever, and the client may already
              have spent the money.
            </p>
            <p className="mt-1 text-xs text-ink-faint">
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

        {/* Beside the control it explains — a reason a screenful away from its button is
            the defect §52 found on three screens. */}
        <RestrictionNote reason={write.reason} />

        {outstanding && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {outstanding}
          </p>
        )}
      </form>
    </Card>
  );
}

/**
 * What the server did — and the one distinction this screen exists to make legible.
 *
 * `recorded` is the whole message. Both outcomes are 200 (a 201 on a replay would claim
 * a creation that never happened, which the route says out loud), so a screen that
 * rendered one panel for both would leave the operator to work out from a balance
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
        <p className="mt-1 text-xs">
          <span className="font-mono">{result.payment_ref}</span> was already on this
          wallet for {formatINR(result.amount_inr)}, so no second entry was written and
          the balance did not move. It stands at {formatINR(result.balance_inr)}.{" "}
          <span className="font-semibold">
            This client has not been credited twice — this is the reference doing its job.
          </span>
        </p>
        <p className="mt-2 text-xs">
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
      <p className="mt-1 text-xs">
        Against <span className="font-mono">{result.payment_ref}</span>. The wallet now
        holds {formatINR(result.balance_inr)}
        {result.is_low ? ", which is still under the low-balance line." : "."}
      </p>
      <p className="mt-2 text-xs">
        Entry <span className="font-mono">{result.entry_id}</span>, on the ledger below
        and there permanently.
      </p>
    </NoticeBox>
  );
}

/** The correction draft. Strings throughout — the money one because hard rule 7. */
interface Correction {
  entryId: string;
  amount: string;
  /** Typed a second time. Double keying, on the field that decides how much moves. */
  confirm: string;
  reason: string;
}

const NO_CORRECTION: Correction = { entryId: "", amount: "", confirm: "", reason: "" };

/**
 * Take a wrong entry back off the wallet — by APPENDING, never by editing.
 *
 * The control this screen said did not exist. Its shape is argued in the file header;
 * what is worth reading here is the ONE-DIRECTIONAL honesty the panel keeps:
 *
 * - the choice is limited to entries with something left to take back, because an entry
 *   already fully corrected is a dead option and offering one is the defect §52 named;
 * - the ceiling beside the amount is the SERVER's `reversible_inr`, displayed and never
 *   recomputed — the console does no decimal arithmetic on money at all, so it cannot
 *   preview the resulting balance and does not pretend to;
 * - the consequence that cannot be previewed — a balance that lands below zero, which
 *   stops a self-serve or trial client dialling — is stated as a CONDITION above the
 *   button and answered as a FACT by the server underneath it.
 */
function CorrectionPanel({
  clientName,
  wallet,
  correct,
  write,
}: {
  clientName: string;
  wallet: Credits;
  correct: ReturnType<typeof useRecordAdjustment>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<Correction>(NO_CORRECTION);
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
  // The DIRECTION, read off the entry exactly as the route derives it. Everything the
  // panel says about danger hangs on this, so it is computed once and never re-guessed.
  const debit = entry !== null && takesCreditAway(entry);

  if (wallet.entries.length === 0) {
    // Not a disabled form: there is genuinely nothing on this ledger to correct, and a
    // form over an empty ledger reads as "a correction is a thing you make up".
    return (
      <Card title="Correct a wrong entry">
        <p className="text-sm text-ink-muted">
          Nothing has been written to this ledger, so there is nothing to correct. A
          correction always names the entry it cancels.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Correct a wrong entry">
      <p className="-mt-2 text-xs text-ink-muted">
        For an entry that should not have been made — a payment credited to the wrong
        client, or for more than arrived. The entry stays on the ledger; a new one with
        the opposite sign cancels it.
      </p>

      {options.length === 0 ? (
        <p className="mt-4 text-sm text-ink-muted">
          Every entry on this wallet has already been taken back in full, so there is
          nothing left to correct here.
        </p>
      ) : (
        <form
          className="mt-4 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (entry === null) return;
            correct.mutate(
              { entry, amountInr: amount, reason },
              // Cleared on success only, and the result panel carries what was sent: a
              // form still holding the correction the server has answered for invites a
              // second click that can only be a replay.
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
              <p className="mt-1 text-xs">
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

          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — the ops order: the act, then that
              it cannot be undone, then the consequence nobody can preview, then that it
              is recorded. An operator who reads only the first line has read the part
              that matters. */}
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${debit ? "text-rose-600" : "text-ink-faint"}`}
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
              <p className="mt-1 text-ink-muted">
                A correction may take the balance <span className="font-semibold">below
                zero</span> — a wrong credit that has already been spent cannot be fully
                taken back any other way. For a self-serve or trial client that stops
                outbound dialling immediately, exactly as an empty wallet does; a managed
                client is invoiced against their retainer and keeps calling. The answer
                comes back with the result rather than being guessed here.
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the audit log against your admin account with the reason you
                type above, in the same transaction as the money.
                {debit
                  ? " Taking credit away also sends the confirmation header the route demands for this direction."
                  : ""}
              </p>
            </div>
          </div>

          {correct.error != null && <ProblemNotice error={correct.error} />}
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
            <p className="flex items-start gap-2 text-xs text-ink-muted">
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
    </Card>
  );
}

/**
 * What the correction did — and the two things a balance alone would not tell anyone.
 *
 * `recorded` separates "we have just taken ₹50,000 off this client" from "that
 * correction was already made", both of which are 200. `stops_dialling` is the more
 * expensive one: it is the dial gate's own verdict on the balance this write produced,
 * and an operator who does not read it here reads it in a phone call from the client.
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
            <p className="mt-1 text-xs">
              Against entry <span className="font-mono">{result.corrects_entry_id}</span>.
              The wallet now holds {formatINR(result.balance_inr)}
              {result.is_low ? ", which is under the low-balance line." : "."}
            </p>
            <p className="mt-2 text-xs">
              The compensating entry is{" "}
              <span className="font-mono">{result.entry_id}</span>, on the ledger below
              and there permanently. The entry it cancels is still there too.
            </p>
          </>
        ) : (
          <p className="mt-1 text-xs">
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
          title={`${clientName} cannot place outbound calls until this wallet is topped up`}
        >
          <p className="mt-1 text-xs">
            The balance is at or below zero and this is a self-serve or trial account, so
            the compliance gate refuses every outbound dial (`no_credits`). Inbound calls
            are unaffected — their receptionist keeps answering. If the credit was
            genuinely theirs, record the payment above; if it was not, this is the
            correct state and they need to pay before they dial.
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

/** The restatement draft. Strings throughout — the money one because hard rule 7. */
interface Restatement {
  paymentRef: string;
  /** THE TOTAL THE BANK MOVED. Never the difference; the server works that out. */
  total: string;
  /** Typed a second time. Double keying, on the field that decides how much appears. */
  confirm: string;
  reason: string;
}

const NO_RESTATEMENT: Restatement = { paymentRef: "", total: "", confirm: "", reason: "" };

/**
 * Put right a payment we recorded for LESS than the bank moved.
 *
 * The control that did not exist, and whose absence had a documented workaround that was
 * worse than the gap: a second top-up under an annotated reference. The file header
 * argues the shape; what is worth reading here is the ONE thing every control in this
 * panel is arranged around — the operator must type the TOTAL, and the commonest way to
 * get this wrong is to type the difference, which is a well-formed number that no
 * validator can distinguish from a correct one.
 *
 * So the total is stated four times before the click: in the field label, in its hint,
 * in the notice that names what the payment credits TODAY, and in the outstanding-step
 * line under the button. And it is typed twice, and it travels in the confirmation
 * header, so the figure the operator confirmed is the figure the server acts on.
 */
function RestatementPanel({
  clientName,
  wallet,
  restate,
  write,
}: {
  clientName: string;
  wallet: Credits;
  restate: ReturnType<typeof useRecordRestatement>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<Restatement>(NO_RESTATEMENT);
  const set = (key: keyof Restatement, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    // The last result described a restatement that is no longer the one in the form.
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
    // Not a disabled form: there is genuinely no payment on this wallet to restate, and
    // a form over none reads as "a restatement is a thing you make up". A restatement
    // always names a payment we have already recorded — it cannot create one.
    return (
      <Card title="A payment was for more than we recorded">
        <p className="text-sm text-ink-muted">
          No payment has been recorded on this wallet, so there is none to restate. This
          repairs a payment we entered for too little; it never creates one.
        </p>
      </Card>
    );
  }

  return (
    <Card title="A payment was for more than we recorded">
      <p className="-mt-2 text-xs text-ink-muted">
        For a bank transfer entered for less than it actually moved — ₹5,000 typed for a
        ₹50,000 UTR. The difference is credited against the SAME reference, so the wallet
        still shows one payment and the ledger still matches the statement.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (payment === null) return;
          restate.mutate(
            { payment, correctedAmountInr: total, reason },
            // Cleared on success only, and the result panel carries what was sent: a
            // form still holding the restatement the server has answered for invites a
            // second click that can only be a replay.
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

        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — the ops order again: the act, then
            that it cannot be undone, then the mistake this control admits and how it is
            recovered, then that it is recorded. */}
        <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
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

        {restate.error != null && <ProblemNotice error={restate.error} />}
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
    </Card>
  );
}

/**
 * What the restatement did — and the number that proves the ledger still matches a bank
 * statement.
 *
 * `credited_inr` is the assertion this whole control exists to make true: ONE reference,
 * ONE figure, comparable by eye against the statement line. `added_inr` is what moved,
 * and the two together are what an operator checks before closing the ticket.
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
    </NoticeBox>
  );
}

/**
 * The bank transfers behind the ledger, one line each — the panel a person reconciles
 * against a statement.
 *
 * The ledger below shows ROWS and this shows PAYMENTS, and the difference is the whole
 * point of D-89: a restated payment is two rows and one transfer. Without this table an
 * operator comparing the ledger to a statement would find two lines for a transfer the
 * bank shows once and have to add them up by hand — which is decimal arithmetic on money
 * done by a human, the failure mode this console refuses everywhere else.
 */
function PaymentsTable({ wallet }: { wallet: Credits }) {
  if (wallet.payments.length === 0) return null;
  return (
    <Card title="Payments — one line per bank transfer">
      <ScrollRegion label="Payments — one line per bank transfer">
        <table className="w-full text-left text-xs">
          <thead className="text-ink-muted">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">
                Reference
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                First recorded
              </th>
              <th scope="col" className="py-1 pr-3 text-right font-medium">
                Credited
              </th>
              <th scope="col" className="py-1 pr-3 text-right font-medium">
                Ledger entries
              </th>
            </tr>
          </thead>
          <tbody>
            {wallet.payments.map((payment: Payment) => (
              <tr key={payment.payment_ref} className="border-t border-line">
                <td className="py-1.5 pr-3 font-mono">{payment.payment_ref}</td>
                <td className="py-1.5 pr-3">{formatIST(payment.first_at)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">
                  {formatINR(payment.credited_inr)}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-ink-muted">
                  {payment.entries === 1 ? "1" : `${payment.entries} — restated`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      <p className="mt-3 text-xs text-ink-muted">
        Compare <span className="font-semibold">Credited</span> against the statement, one
        line to one line. A payment restated after being entered for too little occupies
        more than one row on the ledger below and still exactly one line here — that is
        what keeps the reference usable as the thing reconciliation keys on.
      </p>
    </Card>
  );
}

function LedgerTable({ wallet }: { wallet: Credits }) {
  if (wallet.entries.length === 0) {
    return (
      <Card title="Ledger">
        {/* A REAL empty state, reachable only through a successful read: the failed read
            is `LedgerUnreadable` and never arrives here. */}
        <EmptyState
          title="Nothing has ever been written to this ledger"
          hint="No payment, no call charge, no adjustment. A new account looks exactly like this."
        />
      </Card>
    );
  }

  return (
    <Card title="Ledger — newest first">
      <ScrollRegion label="Credit ledger, newest first">
        <table className="w-full text-left text-xs">
          <thead className="text-ink-muted">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">
                When
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Movement
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                What
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Reference
              </th>
              <th scope="col" className="py-1 pr-3 text-right font-medium">
                Balance after
              </th>
              {/* Why an entry is, or is not, offered in the correction panel above —
                  and the only place an operator can see that a line has ALREADY been
                  corrected without adding up the deltas themselves. */}
              <th scope="col" className="py-1 pr-3 text-right font-medium">
                Left to take back
              </th>
            </tr>
          </thead>
          <tbody>
            {wallet.entries.map((entry) => (
              <Row key={entry.id} entry={entry} />
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      <p className="mt-3 text-xs text-ink-muted">
        The newest {LEDGER_LIMIT}. Nothing here can be edited or removed — and the
        repeated-reference check the server makes reads the WHOLE ledger, not only what
        is shown here, so a reference missing from this list is not proof the payment is
        new.
      </p>
    </Card>
  );
}

function Row({ entry }: { entry: LedgerEntry }) {
  // The sign is in the DIGITS (`formatINR` keeps the leading minus), so the colour
  // reinforces it and is never the only signal — a screen read in monochrome, or by
  // someone who cannot separate the two greens, still reads the same movement.
  const credit = !entry.delta_inr.startsWith("-");
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 pr-3">{formatIST(entry.occurred_at)}</td>
      <td
        className={`py-1.5 pr-3 tabular-nums ${
          credit ? "text-emerald-700 dark:text-emerald-400" : "text-ink"
        }`}
      >
        {credit ? "+" : ""}
        {formatINR(entry.delta_inr)}
      </td>
      <td className="py-1.5 pr-3">{creditReasonLabel(entry.reason)}</td>
      <td className="py-1.5 pr-3 font-mono">{entry.ref ?? "—"}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums">
        {formatINR(entry.balance_after_inr)}
      </td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-muted">
        {isFullyReversed(entry) ? "fully corrected" : formatINR(entry.reversible_inr)}
      </td>
    </tr>
  );
}

/**
 * WHICH remedy, for which mistake — named where an operator will look for it, which is
 * after the mistake.
 *
 * This is not decoration on an append-only ledger. The instinct on discovering a wrong
 * credit is to look for an edit or a delete; there is none, a trigger refuses both
 * (`scripts/check_ledger_immutability.py`), and an operator who does not know that goes
 * looking for a database console.
 *
 * It used to end with "there is no control for this — not on this screen and not
 * anywhere", which was honest and is now false: `CorrectionPanel` above is the control,
 * and this card's job changed from naming an absence to routing between two remedies
 * that repair different failures. The duplicate case still belongs to the script,
 * because a duplicate is DETECTED rather than reported — its key is a fingerprint of the
 * group it cancels, which no operator can type.
 */
function CorrectionCard() {
  return (
    <Card title="If a credit was wrong">
      <p className="text-sm text-ink-muted">
        Nothing on this ledger is edited or deleted, ever — hard rule 4, and a database
        trigger enforces it. The wrong entry stays where it is, because it is the
        evidence that it happened. The balance is repaired by appending ONE compensating
        entry with the opposite sign and{" "}
        <span className="font-mono">reason = &apos;adjustment&apos;</span>.
      </p>
      <ul className="mt-3 space-y-3 text-sm text-ink-muted">
        <li>
          <span className="font-semibold text-ink">
            TOO MUCH was credited — the wrong client, or more than arrived.
          </span>{" "}
          Use <span className="font-semibold">Correct a wrong entry</span> above. It
          names the entry it cancels, takes back at most what that entry put in, derives
          the direction from it, and is keyed so that clicking twice corrects once. The
          balance may end below zero — for a self-serve or trial client that stops their
          dialling, and the result says so.
        </li>
        <li>
          <span className="font-semibold text-ink">
            TOO LITTLE was credited — ₹5,000 recorded for a ₹50,000 UTR.
          </span>{" "}
          Use <span className="font-semibold">
            A payment was for more than we recorded
          </span>{" "}
          above. Re-recording the reference is refused as a conflict, and that refusal is
          doing its job — it is what stops one bank transfer being credited twice. Never
          work around it by recording the difference under an invented reference like{" "}
          <span className="font-mono">UTR-123-part2</span>: the wallet would then show two
          payments where the bank shows one, and the reference is the thing reconciliation
          keys on. Type the TOTAL the bank moved; the difference is worked out for you and
          credited against the same reference.
        </li>
        <li>
          <span className="font-semibold text-ink">
            The same payment credited twice.
          </span>{" "}
          <span className="font-mono text-xs">
            uv run python -m scripts.reconcile_credit_ledger --tenant &lt;id&gt; --apply
          </span>{" "}
          is the tool, and it stays the tool: a duplicate is found by the script rather
          than reported by a person, and its correction is keyed on a fingerprint of the
          exact rows being cancelled — not something to retype into a form. It reads
          without <span className="font-mono">--apply</span>, runs under the same
          per-tenant credit lock as every writer, and deletes nothing.
        </li>
      </ul>
      <p className="mt-3 text-xs text-ink-muted">
        runbooks/topup-payments.md, &ldquo;What NOT to do&rdquo;, is the full list —
        including why a payment is never credited by hand while a signature failure is
        unexplained.
      </p>
    </Card>
  );
}

/**
 * The description an input points at. Both halves are named so a screen reader hears the
 * error AND the guidance — an error span that nothing references is a message only
 * sighted users get, which on the field that decides double-crediting is the wrong half
 * of the audience to serve.
 */
function describedBy(id: string, hasError: boolean): string {
  return hasError ? `${id}-hint ${id}-error` : `${id}-hint`;
}

function Field({
  label,
  id,
  hint,
  error,
  children,
}: {
  label: string;
  id: string;
  hint: string;
  error: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      {/* A PERSISTENT VISIBLE label, not a placeholder. axe scores a placeholder as an
          accessible name and WCAG 3.3.2 does not: the text vanishes on the first
          keystroke, which on a hand-transcribed bank reference is exactly when it is
          needed (tests/a11y.ts states this limitation). */}
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="mt-1">{children}</div>
      <span id={`${id}-hint`} className={FIELD_HINT}>
        {hint}
      </span>
      {error && (
        <span
          id={`${id}-error`}
          className="mt-1 block text-xs font-medium text-rose-700 dark:text-rose-300"
        >
          {error}
        </span>
      )}
    </div>
  );
}

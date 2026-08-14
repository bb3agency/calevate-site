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
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { adminSession, useTenant } from "@/lib/api/admin";
import {
  LEDGER_LIMIT,
  creditReasonLabel,
  normalizeReference,
  referenceCaution,
  referenceProblem,
  rupeeProblem,
  useCredits,
  useRecordTopUp,
  type Credits,
  type LedgerEntry,
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
 * ## THERE IS NO UNDO, AND THE SCREEN SAYS SO WHERE IT IS DECIDED
 *
 * `credit_ledger` is append-only (hard rule 4, enforced by a database trigger). A wrong
 * credit is corrected by APPENDING a compensating `adjustment` entry; the wrong row
 * stays, because it is the evidence. This console cannot append one — the route records
 * positive top-ups only and refuses a negative amount — so the path is named rather than
 * left to be discovered after the fact. See `CorrectionCard`.
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
  // The mutation lives here rather than inside the form: a successful write invalidates
  // the read, and a mutation held inside a form that the read remounts would lose its own
  // confirmation at the moment the write landed (`/commercials` records the same trap).
  const save = useRecordTopUp(adminSession(), tenantId);
  // `POST .../credits` is `admin:tenants` (`credit_routes.py` argues why recording a
  // received payment is that permission and not a `billing:write` that does not exist).
  // The admin realm's own identity read answers it — see `@/app/admin/access` for why the
  // client realm's `useWriteAccess` is the wrong instrument on an admin screen.
  const write = useAdminAccess("admin:tenants", "record a payment on this client's wallet");

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
              append-only and a database trigger refuses UPDATE and DELETE, so a credit to
              the wrong client or for the wrong amount is corrected by ADDING a
              compensating entry — which this console cannot do. Read “If a credit was
              wrong” below before you click, not after.
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
      <div className="overflow-x-auto">
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
            </tr>
          </thead>
          <tbody>
            {wallet.entries.map((entry) => (
              <Row key={entry.id} entry={entry} />
            ))}
          </tbody>
        </table>
      </div>
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
    </tr>
  );
}

/**
 * The remedy, named where an operator will look for it — which is after the mistake.
 *
 * This is not decoration on an append-only ledger. The instinct on discovering a wrong
 * credit is to look for an edit or a delete; there is none, a trigger refuses both
 * (`scripts/check_ledger_immutability.py`), and an operator who does not know that goes
 * looking for a database console. Every branch below is honest about what exists,
 * INCLUDING the one that does not: `POST .../credits` records positive top-ups and
 * refuses a negative amount, and no admin endpoint appends a free-form adjustment,
 * though SURFACES §1 promises one ("credit adjustments (compensating entries, never
 * edits)"). Offering a dead control would be worse than saying so.
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
            The same payment credited twice.
          </span>{" "}
          <span className="font-mono text-xs">
            uv run python -m scripts.reconcile_credit_ledger --tenant &lt;id&gt; --apply
          </span>{" "}
          is the tool. It reads without <span className="font-mono">--apply</span>,
          derives its own reference so it cannot itself double-correct, runs under the
          same per-tenant credit lock as every writer, and deletes nothing.
        </li>
        <li>
          <span className="font-semibold text-ink">
            The wrong client, or the wrong amount.
          </span>{" "}
          There is no control for this — not on this screen and not anywhere. This route
          records positive top-ups only and refuses a negative amount rather than letting
          a &ldquo;top-up&rdquo; quietly take credit away, and no admin endpoint appends a
          free-form adjustment yet. Escalate instead of improvising: the correction has to
          go through <span className="font-mono">record_entry</span>, which owns the
          balance arithmetic and the lock.
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

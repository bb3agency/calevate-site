"use client";

import type { ReactNode } from "react";
import { CircleAlert, CircleHelp } from "lucide-react";

import { minutesLine } from "@/components/admin/credit";
import { NoticeBox, formatINR, formatIST } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import type { TenantSummary } from "@/lib/api/admin";
import type { Credits } from "@/lib/api/credits";

/**
 * THE WALLET AT A GLANCE: the balance as the SERVER computed it (never re-derived from the
 * deltas), and beside it the two lifetime figures the founder's guardrail keeps apart —
 * what this wallet has been PAID for and what it has been GIVEN.
 */
export function WalletSummary({
  wallet,
  tenant,
  actions,
}: {
  wallet: Credits;
  /** The directory row, for the minutes left: credit is stated minutes first (founder,
   * 10 Oct 2026), and the row carries the wallet's own per-quality runway. */
  tenant: TenantSummary;
  actions: ReactNode;
}) {
  const newest = wallet.entries.length > 0 ? wallet.entries[0] : null;
  const minutes = minutesLine(tenant);
  return (
    <section aria-label="Wallet" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-8 gap-y-4 lg:grid-cols-4">
          <Metric
            label="Minutes left"
            value={minutes ?? (tenant.plan_tier === "managed" ? "Moving to credits" : "—")}
            hint={
              tenant.minutes_left === null && tenant.credit_inr !== null
                ? "Not quoted during a trial: the calling is on us."
                : undefined
            }
          />
          <Metric
            label="On the wallet now"
            value={formatINR(wallet.balance_inr)}
            tone={wallet.is_low ? "warn" : "default"}
            hint={
              newest
                ? `Newest entry ${formatIST(newest.occurred_at)}`
                : "No entry has ever been written to this ledger."
            }
          />
          <Metric label="Paid for, lifetime" value={formatINR(wallet.paid_inr)} />
          <Metric label="Given, lifetime" value={formatINR(wallet.granted_inr)} />
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto [&>*]:max-sm:flex-1">{actions}</div>
      </div>

      {/* `is_low` is the SERVER's verdict (`billing.service.LOW_BALANCE_INR`), displayed and
          never computed here: a console that decided what counts as low would eventually
          disagree with the gate that actually stops the dialling. EVERY client,
          and BOTH directions (D-551, D-577) — guarded by `tests/credit_stop_copy_test.py`. */}
      {wallet.is_low && (
        <NoticeBox
          tone="warn"
          icon={<CircleAlert aria-hidden className="h-5 w-5" />}
          title={`Below the low-balance line of ${formatINR(wallet.low_balance_threshold_inr)}`}
        >
          <p className="mt-1">
            An empty wallet stops this client calling and being called. Every account that
            pays from a wallet — which is every client — has its
            outgoing calls refused by the compliance gate at a balance of zero or below,
            and its agents stop answering incoming ones: callers hear a short apology that
            gives no reason. Record the payment below and both start again. A client
            inside a trial period is on us and
            is stopped by neither, however empty this wallet is.
          </p>
        </NoticeBox>
      )}
    </section>
  );
}

/**
 * THE LEDGER WE COULD NOT READ, said as itself — and every write withheld with it.
 *
 * Not "no entries", not "₹0", and not a form beside an empty table: crediting against a
 * ledger nobody can see removes the one check that catches a payment a colleague recorded
 * ten minutes ago, on a write that cannot be taken back.
 */
export function LedgerUnreadable() {
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="We could not read this wallet, so nothing can be credited to it here"
    >
      <p className="mt-1">
        This screen will not tell you the balance is zero and it will not tell you the
        ledger is empty — it does not know either. The error above says what stopped the
        read; retry it and the form comes back with it.{" "}
        <InfoTip label="Why the forms are withheld">
          The form is withheld rather than merely blank on purpose. A top-up recorded
          against a ledger nobody can see is a top-up recorded without the one check that
          catches a payment already credited — and no entry on this ledger can be taken
          back.
        </InfoTip>
      </p>
      <p className="mt-2 text-meta">
        If a client is blocked on credit and this will not load, the top-up payments
        runbook has the steps to record it by hand.
      </p>
    </NoticeBox>
  );
}

/**
 * WHICH remedy, for which mistake — named where an operator looks for it, which is after
 * the mistake. Visible on every branch (it depends on no read) and word for word: the
 * instinct on finding a wrong credit is to look for an edit or a delete, there is none
 * (`scripts/check_ledger_immutability.py`), and it carries the guarded credit-stop
 * sentence. The duplicate case belongs to the reconciliation script, because a duplicate is
 * DETECTED rather than reported — its key is a fingerprint no operator can type.
 */
export function CorrectionCard() {
  return (
    <Section title="If a credit was wrong">
      <p className="text-body text-ink-muted">
        Nothing on this ledger is edited or deleted, ever — that is a firm rule, and the
        database enforces it. The wrong entry stays where it is, because it is the
        evidence that it happened. The balance is repaired by adding ONE opposite entry
        that cancels it.
      </p>
      <ul className="mt-3 space-y-3 text-body text-ink-muted">
        <li>
          <span className="font-semibold text-ink">
            TOO MUCH was credited — the wrong client, or more than arrived.
          </span>{" "}
          Use <span className="font-semibold">Correct a wrong entry</span> above. It
          names the entry it cancels, takes back at most what that entry put in, derives
          the direction from it, and is keyed so that clicking twice corrects once. The
          balance may end below zero — that stops the client&apos;s
          outgoing calls and stops their agents answering incoming ones until you add
          credit back, and the result says so.
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
          This one is not fixed from this screen. A duplicate is found and cancelled by our
          reconciliation tool, which matches on a fingerprint of the exact rows involved —
          not something anyone can retype into a form. Ask engineering to run it against
          this client; it checks before it changes anything and deletes nothing.
        </li>
      </ul>
      <p className="mt-3 text-meta text-ink-muted">
        The top-up payments runbook, under &ldquo;What NOT to do&rdquo;, is the full list —
        including why a payment is never credited by hand while a signature failure is
        unexplained.
      </p>
    </Section>
  );
}

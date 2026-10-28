"use client";

import { formatPayableINR } from "@/lib/numberDisplay";
import { CircleAlert, CircleCheck, Clock, HelpCircle, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { Section } from "@/components/console/section";
import {
  MonoValue,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { useTopUpAttempts, type TopUpAttempt } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

import { Why } from "@/components/why";

/**
 * Payments that were started and did not become credit — and what to do about each.
 *
 * **WHY THIS PANEL EXISTS AT ALL.** A declined card moves no money, so it has no ledger
 * entry, so before `topup_attempts` a client whose payment failed came back to a screen
 * indistinguishable from one they had never touched: no credit, no failure, nothing. The
 * only way to find out what had happened was to ask us.
 *
 * **THREE OUTCOMES, THREE DIFFERENT SENTENCES, AND ONLY ONE OF THEM IS A PROBLEM.**
 *
 * - `settling` — we have not heard back yet. This is the state a client who closed the tab
 *   mid-payment is in, and the sentence has to say the thing they most need to know: their
 *   credit lands on its own if the payment went through, WITHOUT this page. The browser is
 *   not what credits a wallet (`billing/payment_routes.py` — the signed webhook is), so
 *   "do not pay again" is a fact about our system rather than reassurance.
 * - `unfinished` — old enough that nothing is coming. Offer another go.
 * - `failed` — the provider told us it did not go through. Offer another go.
 *
 * **THE PANEL HIDES ITSELF WHEN THERE IS NOTHING TO SAY.** A card headed "Payments that
 * did not finish" reading "none" on every visit is a permanent invitation to worry. A
 * captured attempt is not shown either: it is on the ledger, one card down, where money
 * belongs.
 *
 * **THE RETRY OPENS THE ADD CREDIT DRAWER; IT MINTS NOTHING.** Starting a payment is
 * `TopUp`'s job, the one place money is spent, so "Try again" opens that drawer rather than
 * creating an intent of its own. Two controls that both start a payment is how a client
 * ends up with two orders for one top-up.
 */
export function UnfinishedPayments({
  session,
  onAddCredit,
}: {
  session: Session;
  /** Opens the Add credit drawer, the one place a payment starts, so a retry here cannot
      mint a second order beside it. */
  onAddCredit?: () => void;
}) {
  const attempts = useTopUpAttempts(session);

  if (attempts.isLoading) return <Skeleton rows={2} label="Checking for unfinished payments" />;
  // `|| !attempts.data` and not `attempts.error` alone: TanStack PARKS a query rather than
  // starting it while the browser is offline, and a paused query reports
  // `isLoading === false` AND `error === null` with `data === undefined` — so an `?? []`
  // here would quietly tell a client that no payment of theirs is outstanding, which on
  // this panel is the one claim it exists to avoid making (§52).
  if (attempts.error || !attempts.data) {
    return (
      <Section title="Payments in progress">
        <ProblemNotice error={attempts.error ?? new Error("Your payments in progress did not load.")} onRetry={() => void attempts.refetch()} />
      </Section>
    );
  }
  // Captured attempts belong on the ledger, not here. Nothing outstanding means no card.
  const open = attempts.data.filter((row) => row.outcome !== "captured");
  if (open.length === 0) return null;

  return (
    <Section title="Unfinished payments">
      <ul className="divide-y divide-line border-y border-line">
        {open.map((attempt) => (
          <li key={attempt.id} className="py-3.5 text-body">
            <AttemptRow attempt={attempt} />
          </li>
        ))}
      </ul>
      {onAddCredit && open.some((row) => RETRYABLE.has(row.outcome)) && (
        <div className="mt-3 space-y-1">
          <button
            type="button"
            onClick={onAddCredit}
            className={`${SECONDARY_BUTTON} w-full justify-center sm:w-auto`}
          >
            <RotateCcw aria-hidden className="h-4 w-4" />
            Try again
          </button>
          <Why label="Is it safe?">
            <p>
              A new payment is always safe: credit is only ever added once for each payment
              that goes through.
            </p>
          </Why>
        </div>
      )}
    </Section>
  );
}

/** The outcomes a new payment answers. A settling one may still land, so it gets no retry. */
const RETRYABLE = new Set(["unfinished", "failed"]);

const OUTCOMES: Record<string, { icon: ReactNode; title: string; line: string; body: string }> = {
  settling: {
    icon: <Clock className="h-4 w-4" aria-hidden />,
    title: "Still settling",
    line: "Don't pay again yet.",
    body:
      "We have not heard back about this payment yet. If it went through, your credit is " +
      "added automatically — you do not need to keep this page open, and you should not " +
      "pay again yet.",
  },
  authorized: {
    icon: <Clock className="h-4 w-4" aria-hidden />,
    title: "Verifying",
    line: "Bank approved it. Don't pay again.",
    // No vendor named in client copy (D-679).
    body:
      "Your bank has approved this payment and we are completing it. Your credit is " +
      "added automatically within minutes.",
  },
  unfinished: {
    icon: <HelpCircle className="h-4 w-4" aria-hidden />,
    title: "Never finished",
    line: "Nothing was charged.",
    body:
      "This payment was started but never completed, so nothing was charged and no credit " +
      "was added. If your bank shows the amount taken, send us the reference below and we " +
      "will trace it.",
  },
  failed: {
    icon: <CircleAlert className="h-4 w-4" aria-hidden />,
    title: "Did not go through",
    line: "Nothing was charged.",
    body:
      "Your bank did not complete this payment, so nothing was charged and no credit was " +
      "added. You can try again with the same or a different payment method.",
  },
  captured: {
    icon: <CircleCheck className="h-4 w-4" aria-hidden />,
    title: "Paid",
    line: "Credit added.",
    body: "This payment went through and the credit is on your balance.",
  },
};

function AttemptRow({ attempt }: { attempt: TopUpAttempt }) {
  // THROUGH `lookup()`, never `OUTCOMES[value]`: the key is a WIRE string, and a plain
  // index reads the prototype chain — an outcome of `constructor` would resolve to the
  // `Object` function and render as source code (`lib/lookup.ts`).
  //
  // And it fails VISIBLE: an outcome this build has no word for still renders its own
  // name and the amount rather than a blank row — the direction `creditReasonLabel`
  // takes, and it matters more here because the row is about a payment nobody can
  // otherwise account for.
  const copy = lookup(OUTCOMES, attempt.outcome);
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-semibold text-ink">
          <span className="text-ink-muted" aria-hidden>
            {copy?.icon ?? <HelpCircle className="h-4 w-4" />}
          </span>
          {formatPayableINR(attempt.amount_inr)}
          <span className="text-meta font-normal text-ink-muted">
            {copy?.title ?? attempt.outcome}
          </span>
        </p>
        <p className="text-meta text-ink-muted">Started {formatIST(attempt.started_at)}</p>
      </div>
      <p className="mt-1 text-ink-muted">{copy?.line ?? "No final answer yet."}</p>
      <Why label="Details">
        <p>
          {copy?.body ??
            "We do not have a final answer about this payment yet. Send us the reference below and we will check it."}
        </p>
      </Why>
      <p className="mt-1 text-meta text-ink-muted">
        ref <MonoValue>{attempt.receipt}</MonoValue>
      </p>
    </>
  );
}

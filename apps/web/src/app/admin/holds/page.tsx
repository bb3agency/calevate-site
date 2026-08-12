"use client";

import Link from "next/link";

import { EmptyState, NOTICE_TONES, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useHeldTenants } from "@/lib/api/admin";
import {
  WAIT_BREACH_HOURS,
  holdRule,
  hoursWaiting,
  waitBand,
  waitedFor,
  type HeldTenant,
} from "@/lib/api/holds";

/**
 * The ops work list: who is waiting on a human, and for how long.
 *
 * Two R-11 gates block tenants — subscriber KYC and the first-campaign review — and both
 * shipped with the enforcement half only. `GET /v1/admin/compliance/holds` closed the
 * discovery gap in the API and left the console with none: an operator's only way to
 * find a held account was a curl, which means in practice they found out when the client
 * emailed to ask why nothing worked. `admin/holds.py` names that failure exactly: it
 * makes a mitigation depend on the client complaining, and it is worst for the accounts
 * that never complain and simply churn.
 *
 * **This is a work QUEUE, not a report**, and three things follow from that:
 *
 * 1. **The wait is the headline, not the roster.** `signed_up_at` is on the row so that
 *    an account sitting held for a fortnight is visible as such, so it is rendered as a
 *    DURATION and banded, never as a date an operator has to subtract from today.
 * 2. **Every row ends in a control.** Each rule carries the screen that clears it
 *    (`HOLD_RULES`), so no row is a fact the reader has to work out what to do about.
 *    The two gates have different remedies and an account can be held by both, so a row
 *    offers as many as apply rather than picking one.
 * 3. **Empty is the GOOD state.** Nobody waiting is the outcome this screen exists to
 *    produce, so it says so — a queue that renders "no data" at its own success would
 *    read as a failed load, and the next thing an operator does with a failed load is
 *    reach for the curl this screen replaced.
 *
 * The server's order is kept exactly: oldest signup first is the triage order
 * (`held_tenants`), and re-sorting in the console would be a second opinion about
 * priority held in the place least able to defend it.
 *
 * Hard rule 6 is a property of the payload and nothing here widens it: no phone number,
 * no document reference, no signatory, no reviewer prose. The blockers' `reason` strings
 * are dropped server-side because a rejection interpolates an operator's free text, and
 * this screen deliberately does not fetch any of it back to fill the gap — the account's
 * own screens hold it, behind the permission that opens them.
 */
export default function HeldAccountsPage() {
  const queue = useHeldTenants();
  const rows = queue.data ?? [];
  // One clock for the whole render, so two rows a millisecond apart cannot land in
  // different bands, and so the numbers on screen agree with each other.
  const now = Date.now();
  const breaching = rows.filter((row) => hoursWaiting(row.signed_up_at, now) >= WAIT_BREACH_HOURS);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Held accounts</h1>
        <p className="mt-0.5 text-sm text-slate-400">
          Accounts that cannot dial until someone here acts — identity not verified, or a
          first campaign not yet released. Oldest signup first.
        </p>
      </div>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => queue.refetch()} />}

      {/* Said above the table rather than inside it: the count an operator carries away
          from this screen is "how many, and is anything rotting", and a number that only
          exists as a row you have to scroll to is a number nobody has. */}
      {!queue.isLoading && !queue.error && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-slate-300">
            {rows.length} {rows.length === 1 ? "account" : "accounts"} waiting
          </span>
          {breaching.length > 0 && (
            <span className={`rounded-md border px-2 py-1 text-xs ${NOTICE_TONES.stop}`}>
              {breaching.length} waiting over a week
            </span>
          )}
          {/* Computed from the rows rather than read off the first one. The server
              orders oldest-first and this screen keeps that order, but a headline number
              that would quietly become wrong if the order ever changed is a number worth
              deriving. */}
          <span className="text-xs text-slate-500">
            Longest wait: {waitedFor(longestWait(rows), now)}
          </span>
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900">
        {queue.isLoading ? (
          <div className="p-4">
            <Skeleton rows={4} />
          </div>
        ) : queue.error ? (
          /* Deliberately NOT the empty state. "Nobody is waiting" is a claim about the
             world, and a failed read is not evidence for it — an operator told the queue
             was clear because a token expired would stop looking. */
          <div className="p-4 text-sm text-slate-400">
            The queue could not be read, so we cannot say whether anyone is waiting.
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nobody is waiting on us"
            hint="Every self-serve account has its identity verified and its first campaign released. This list fills up on its own as new accounts sign up."
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2 font-medium">Client</th>
                <th className="px-4 py-2 font-medium">Waiting</th>
                <th className="px-4 py-2 font-medium">Motion</th>
                <th className="px-4 py-2 font-medium">Held on</th>
                <th className="px-4 py-2 font-medium">Next step</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((row) => (
                <HoldRow key={row.tenant_id} row={row} now={now} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-xs text-slate-500">
        Read-only: every decision is recorded on the account&apos;s own screen, where it is
        audited. A row leaves this list when the gate that held it is cleared — the list is
        built from the same predicates that refuse the client&apos;s dial and launch, so it
        cannot say an account is clear while the client is staring at a refusal.
      </p>
    </div>
  );
}

/** The earliest signup on the list — only called with a non-empty list. */
function longestWait(rows: HeldTenant[]): string {
  return rows.reduce((oldest, row) =>
    new Date(row.signed_up_at) < new Date(oldest.signed_up_at) ? row : oldest,
  ).signed_up_at;
}

function HoldRow({ row, now }: { row: HeldTenant; now: number }) {
  const band = waitBand(row.signed_up_at, now);
  // Two rules can share one remedy (`kyc_missing` and `kyc_not_verified` are separate
  // facts with the same screen), so the destinations are deduped by href — an operator
  // does not need to be offered the same page twice on one row.
  const remedies = new Map<string, string>();
  for (const rule of row.holds) {
    const copy = holdRule(rule);
    if (copy) remedies.set(copy.screen(row.tenant_id), copy.cta);
  }
  const unknown = row.holds.filter((rule) => holdRule(rule) === null);

  return (
    <tr className="align-top hover:bg-slate-800/50">
      <td className="px-4 py-2">
        <Link href={`/admin/tenants/${row.tenant_id}`} className="font-medium hover:underline">
          {row.name}
        </Link>
        <div className="text-xs text-slate-500">/c/{row.slug}</div>
      </td>
      <td className="px-4 py-2">
        {/* The duration is the fact; the signup date is the evidence for it, kept in the
            tooltip so the column stays scannable without becoming unverifiable. */}
        <span
          className={`inline-block rounded-md border px-2 py-0.5 text-xs ${NOTICE_TONES[band]}`}
          title={`Signed up ${formatIST(row.signed_up_at)} IST`}
        >
          {waitedFor(row.signed_up_at, now)}
        </span>
      </td>
      <td className="px-4 py-2 text-xs text-slate-400">{row.plan_tier}</td>
      <td className="px-4 py-2">
        <ul className="space-y-1">
          {row.holds.map((rule) => {
            const copy = holdRule(rule);
            return (
              <li key={rule} className="text-xs">
                <span className="font-medium text-slate-200">{copy?.label ?? rule}</span>
                <div className="text-slate-500">
                  {copy?.blocks ??
                    "This console does not know this rule. The account is held by it all the same — open the account."}
                </div>
              </li>
            );
          })}
        </ul>
      </td>
      <td className="px-4 py-2">
        <div className="flex flex-col items-start gap-1">
          {[...remedies].map(([href, cta]) => (
            <Link
              key={href}
              href={href}
              className="rounded-md border border-slate-700 px-2 py-0.5 text-xs hover:bg-slate-800"
            >
              {cta}
            </Link>
          ))}
          {/* A rule this build cannot name still has an account behind it. The row keeps
              it and sends the operator somewhere real rather than rendering a dead end;
              inventing a remedy for a rule we have never heard of would be worse. */}
          {unknown.length > 0 && (
            <Link
              href={`/admin/tenants/${row.tenant_id}`}
              className="rounded-md border border-amber-800 px-2 py-0.5 text-xs text-amber-300 hover:bg-slate-800"
            >
              Open the account
            </Link>
          )}
        </div>
      </td>
    </tr>
  );
}

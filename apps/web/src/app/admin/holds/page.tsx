"use client";

import Link from "next/link";
import { ArrowRight, Hourglass, TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
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
 *    reach for the curl this screen replaced. A FAILED read gets a third branch of its
 *    own, because "nobody is waiting" is a claim about the world and a dead token is not
 *    evidence for it.
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
 *
 * The page carries no `<h1>`: the shell derives the title from the nav list it renders
 * the sidebar from (`app/admin/layout.tsx`), so a heading here would be the same word
 * twice and, worse, a second place for it to be renamed.
 */
export default function HeldAccountsPage() {
  const queue = useHeldTenants();
  const rows = queue.data ?? [];
  // One clock for the whole render, so two rows a millisecond apart cannot land in
  // different bands, and so the numbers on screen agree with each other.
  const now = Date.now();
  const breaching = rows.filter((row) => hoursWaiting(row.signed_up_at, now) >= WAIT_BREACH_HOURS);

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        Accounts that cannot dial until someone here acts — identity not verified, or a
        first campaign not yet released. Oldest signup first.
      </p>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      {/* Said above the table rather than inside it: the count an operator carries away
          from this screen is "how many, and is anything rotting", and a number that only
          exists as a row you have to scroll to is a number nobody has. */}
      {!queue.isLoading && !queue.error && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="inline-flex items-center gap-2 font-semibold text-ink">
            <Hourglass className="h-4 w-4 text-ink-faint" />
            {rows.length} {rows.length === 1 ? "account" : "accounts"} waiting
          </span>
          {breaching.length > 0 && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${NOTICE_TONES.stop}`}
            >
              <TriangleAlert className="h-3.5 w-3.5" />
              {breaching.length} waiting over a week
            </span>
          )}
          {/* Computed from the rows rather than read off the first one. The server
              orders oldest-first and this screen keeps that order, but a headline number
              that would quietly become wrong if the order ever changed is a number worth
              deriving. */}
          <span className="text-xs text-ink-faint">
            Longest wait: {waitedFor(longestWait(rows), now)}
          </span>
        </div>
      )}

      <Card bodyClassName="p-0">
        {queue.isLoading ? (
          <div className="p-6">
            <Skeleton rows={4} />
          </div>
        ) : queue.error ? (
          /* Deliberately NOT the empty state. "Nobody is waiting" is a claim about the
             world, and a failed read is not evidence for it — an operator told the queue
             was clear because a token expired would stop looking. `NoticeBox` rather than
             a hand-built box: the tone table and the medallion are the same ones every
             other verdict on both realms uses, and this screen had drifted to its own. */
          <div className="p-6">
            <NoticeBox
              tone="warn"
              icon={<TriangleAlert className="h-5 w-5" />}
              title="The queue could not be read"
            >
              <p className="mt-1">
                So we cannot say whether anyone is waiting. This is not an empty queue.
              </p>
            </NoticeBox>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nobody is waiting on us"
            hint="Every self-serve account has its identity verified and its first campaign released. This list fills up on its own as new accounts sign up."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-6 py-3 font-semibold">Client</th>
                  <th className="px-6 py-3 font-semibold">Waiting</th>
                  <th className="px-6 py-3 font-semibold">Motion</th>
                  <th className="px-6 py-3 font-semibold">Held on</th>
                  <th className="px-6 py-3 font-semibold">Next step</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row) => (
                  <HoldRow key={row.tenant_id} row={row} now={now} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-ink-faint">
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
    <tr className="align-top hover:bg-black/[0.02] dark:hover:bg-white/[0.03]">
      <td className="px-6 py-3">
        <Link
          href={`/admin/tenants/${row.tenant_id}`}
          className="font-semibold text-ink hover:underline"
        >
          {row.name}
        </Link>
        <div className="text-xs text-ink-faint">/c/{row.slug}</div>
      </td>
      <td className="px-6 py-3">
        {/* The duration is the fact; the signup date is the evidence for it, kept in the
            tooltip so the column stays scannable without becoming unverifiable. */}
        <span
          className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${NOTICE_TONES[band]}`}
          title={`Signed up ${formatIST(row.signed_up_at)} IST`}
        >
          {waitedFor(row.signed_up_at, now)}
        </span>
      </td>
      <td className="px-6 py-3 text-xs text-ink-muted">{row.plan_tier}</td>
      <td className="px-6 py-3">
        <ul className="space-y-1.5">
          {row.holds.map((rule) => {
            const copy = holdRule(rule);
            return (
              <li key={rule} className="text-xs">
                <span className="font-semibold text-ink">{copy?.label ?? rule}</span>
                <div className="text-ink-muted">
                  {copy?.blocks ??
                    "This console does not know this rule. The account is held by it all the same — open the account."}
                </div>
              </li>
            );
          })}
        </ul>
      </td>
      <td className="px-6 py-3">
        <div className="flex flex-col items-start gap-1">
          {[...remedies].map(([href, cta]) => (
            <Link
              key={href}
              href={href}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
            >
              {cta}
              <ArrowRight className="h-3 w-3" />
            </Link>
          ))}
          {/* A rule this build cannot name still has an account behind it. The row keeps
              it and sends the operator somewhere real rather than rendering a dead end;
              inventing a remedy for a rule we have never heard of would be worse. */}
          {unknown.length > 0 && (
            <Link
              href={`/admin/tenants/${row.tenant_id}`}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium hover:underline ${NOTICE_TONES.warn}`}
            >
              Open the account
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}
        </div>
      </td>
    </tr>
  );
}

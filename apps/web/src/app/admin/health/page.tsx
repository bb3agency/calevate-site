"use client";

import Link from "next/link";

import { EmptyState, NOTICE_TONES, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useClientHealth } from "@/lib/api/admin";
import {
  causeCta,
  causeHref,
  causeLabel,
  severityTone,
  signalCopy,
  signalCount,
  trendClaim,
  type ClientHealth,
  type HealthSignal,
} from "@/lib/api/clientHealth";

/**
 * The client health overview: which account is about to churn or break, this week.
 *
 * The problem it exists for is stated in `apps/api/admin/health.py`: an operator with N
 * client businesses cannot open N dashboards on a Monday, so the accounts that are quietly
 * failing are found when the client emails — and the clients who never email are the ones
 * who simply churn. `/admin` (the directory) answers "who are my clients". This answers
 * the other question, and the difference decides everything about how it renders.
 *
 * **It is a work list, not a dashboard**, and four things follow:
 *
 * 1. **Only what is wrong appears.** The API omits healthy accounts entirely, so there is
 *    no green column, no full grid, and nothing to scan past. The row an operator sees is
 *    a row that needs them.
 * 2. **Every signal ends in a control.** Each one carries the screen that acts on it
 *    (`SIGNAL_COPY`), and each CAUSE of a blocked account carries its own — the two R-11
 *    gates reuse `HOLD_RULES`' screens and wording verbatim, everything else goes to the
 *    account. No row is a fact the reader has to work out what to do about.
 * 3. **A trend is only shown on a basis that earned it.** `trendClaim` is the only reader
 *    of `calls_basis`, and it returns a union rather than a string so there is no code
 *    path that formats a percentage for an account too new to have a previous week. A
 *    console that guessed here would send an operator to accuse a four-day-old client of
 *    churning.
 * 4. **Empty is the GOOD state.** Nobody in trouble is the outcome this screen exists to
 *    produce, so it says so — a board rendering "no data" at its own success reads as a
 *    failed load, and a failed load is a claim about the world this screen must never make
 *    from a failed read.
 *
 * The server's order is kept exactly: most-broken first (`admin/health.py::_triage_order`,
 * which counts rather than scores, so an operator can check it by looking at the row).
 * Re-sorting here would be a second opinion about priority held in the place least able to
 * defend it.
 *
 * Hard rule 6 is a property of the payload and nothing here widens it: accounts and
 * machine rule names, no phone number, no transcript, no reviewer prose. All wording comes
 * from this console's own tables and none of it is fetched back from the account.
 */
export default function ClientHealthPage() {
  const board = useClientHealth();
  const rows = board.data ?? [];
  const breaking = rows.filter((row) => row.severity === "stop");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Client health</h1>
        <p className="mt-0.5 text-sm text-slate-400">
          Accounts with something wrong this week, most broken first. Clients with nothing
          wrong are not listed — the full roster is on Clients.
        </p>
      </div>

      {board.error && <ProblemNotice error={board.error} onRetry={() => board.refetch()} />}

      {/* Above the table, not in it: the number an operator carries away is "how many, and
          how bad", and a number that only exists as a row you scroll to is a number nobody
          has. */}
      {!board.isLoading && !board.error && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-slate-300">
            {rows.length} {rows.length === 1 ? "account" : "accounts"} need attention
          </span>
          {breaking.length > 0 && (
            <span className={`rounded-md border px-2 py-1 text-xs ${NOTICE_TONES.stop}`}>
              {breaking.length} broken now
            </span>
          )}
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900">
        {board.isLoading ? (
          <div className="p-4">
            <Skeleton rows={4} />
          </div>
        ) : board.error ? (
          /* Deliberately NOT the empty state. "Every client is fine" is a claim about the
             world, and a failed read is not evidence for it — an operator told the board
             was clear because a token expired would stop looking. */
          <div className="p-4 text-sm text-slate-400">
            The board could not be read, so we cannot say whether any client is in trouble.
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Every client looks healthy"
            hint="No account is silent, blocked, near its cap, failing deliveries, or waiting on us to approve knowledge. This list fills up on its own."
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2 font-medium">Client</th>
                <th className="px-4 py-2 font-medium">Calls (7d vs prior)</th>
                <th className="px-4 py-2 font-medium">What is wrong</th>
                <th className="px-4 py-2 font-medium">Next step</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((row) => (
                <HealthRow key={row.tenant_id} row={row} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-xs text-slate-500">
        Read-only. Every signal is derived from the same rules that refuse the
        client&apos;s dial, meter their spend and gate their knowledge, so this board cannot
        say an account is fine while the client is looking at a refusal. A row leaves the
        list when the thing behind it is fixed.
      </p>
    </div>
  );
}

function HealthRow({ row }: { row: ClientHealth }) {
  const trend = trendClaim(row);

  return (
    <tr className="align-top hover:bg-slate-800/50">
      <td className="px-4 py-2">
        <Link href={`/admin/tenants/${row.tenant_id}`} className="font-medium hover:underline">
          {row.name}
        </Link>
        <div className="text-xs text-slate-500">/c/{row.slug}</div>
        <span
          className={`mt-1 inline-block rounded-md border px-2 py-0.5 text-xs ${
            NOTICE_TONES[severityTone(row.severity)]
          }`}
        >
          {row.severity === "stop" ? "broken now" : "will break"}
        </span>
      </td>
      <td className="px-4 py-2">
        {/* The whole `after_hours_basis` argument, rendered. An unearned basis prints the
            REASON we cannot say, never a dash and never a 0% that reads as measured. */}
        {trend.kind === "measured" ? (
          <>
            <div className="tabular-nums text-slate-200">
              {trend.to} <span className="text-slate-500">vs {trend.from}</span>
            </div>
            <div className="text-xs text-slate-500">
              {trend.droppedPct > 0
                ? `down ${trend.droppedPct}%`
                : `up ${Math.abs(trend.droppedPct)}%`}
            </div>
          </>
        ) : (
          <div className="text-xs text-slate-500">{trend.why}</div>
        )}
        <div className="mt-1 text-xs text-slate-600">
          Last call {formatIST(row.last_call_at)}
        </div>
      </td>
      <td className="px-4 py-2">
        <ul className="space-y-2">
          {row.signals.map((signal) => (
            <SignalCell key={signal.rule} signal={signal} tenantId={row.tenant_id} />
          ))}
        </ul>
      </td>
      <td className="px-4 py-2">
        <div className="flex flex-col items-start gap-1">
          {[...remedies(row)].map(([href, cta]) => (
            <Link
              key={href}
              href={href}
              className="rounded-md border border-slate-700 px-2 py-0.5 text-xs hover:bg-slate-800"
            >
              {cta}
            </Link>
          ))}
        </div>
      </td>
    </tr>
  );
}

/**
 * The destinations this row offers, deduped by href.
 *
 * Several signals legitimately share one screen (the account's own page carries the DLT
 * registration, the caps and the knowledge queue), and an operator does not need to be
 * offered the same page three times on one row. A signal this build cannot name still
 * contributes its account link rather than nothing — see `signalCopy`, which fails
 * visible.
 */
function remedies(row: ClientHealth): Map<string, string> {
  const found = new Map<string, string>();
  for (const signal of row.signals) {
    const copy = signalCopy(signal.rule);
    if (copy) {
      found.set(copy.screen(row.tenant_id, row.slug), copy.cta);
    } else {
      found.set(`/admin/tenants/${row.tenant_id}`, "Open the account");
    }
    // A blocked account's causes go to the desk that clears each one. For the two R-11
    // gates that desk is the screen `HOLD_RULES` names — the KYC record, the first-campaign
    // release — so the board offers the hold queue's OWN call to action rather than a
    // second wording for the same work.
    for (const cause of signal.causes) {
      found.set(causeHref(cause, row.tenant_id), causeCta(cause));
    }
  }
  return found;
}

function SignalCell({ signal, tenantId }: { signal: HealthSignal; tenantId: string }) {
  const copy = signalCopy(signal.rule);
  const count = signalCount(signal);

  return (
    <li className="text-xs">
      <span
        className={`inline-block rounded-md border px-2 py-0.5 ${
          NOTICE_TONES[severityTone(signal.severity)]
        }`}
      >
        {/* A signal added after this build shipped keeps its row and prints as itself. An
            operator who can read the unfamiliar name can go and find out what it is;
            dropping it would hide an account that is genuinely in trouble. */}
        {copy?.label ?? signal.rule}
      </span>
      {count && <span className="ml-2 text-slate-400">{count}</span>}
      <div className="mt-0.5 text-slate-500">
        {copy?.meaning ??
          "This console does not know this signal. The account is flagged by it all the same — open the account."}
      </div>
      {signal.causes.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {signal.causes.map((cause) => (
            <li key={cause}>
              <Link
                href={causeHref(cause, tenantId)}
                className="text-slate-400 underline-offset-2 hover:underline"
              >
                {causeLabel(cause)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

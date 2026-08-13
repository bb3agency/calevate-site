"use client";

import Link from "next/link";
import { ArrowRight, HeartPulse, TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
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
 *
 * The page carries no `<h1>`: the shell derives the title from the nav list it renders the
 * sidebar from (`app/admin/layout.tsx`), so a heading here would repeat it.
 */
export default function ClientHealthPage() {
  const board = useClientHealth();
  const rows = board.data ?? [];
  const breaking = rows.filter((row) => row.severity === "stop");

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        Accounts with something wrong this week, most broken first. Clients with nothing
        wrong are not listed — the full roster is on Clients.
      </p>

      {board.error && <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />}

      {/* Above the table, not in it: the number an operator carries away is "how many, and
          how bad", and a number that only exists as a row you scroll to is a number nobody
          has. */}
      {!board.isLoading && !board.error && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="inline-flex items-center gap-2 font-semibold text-ink">
            <HeartPulse className="h-4 w-4 text-ink-faint" />
            {rows.length} {rows.length === 1 ? "account" : "accounts"} need attention
          </span>
          {breaking.length > 0 && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${NOTICE_TONES.stop}`}
            >
              <TriangleAlert className="h-3.5 w-3.5" />
              {breaking.length} broken now
            </span>
          )}
        </div>
      )}

      <Card bodyClassName="p-0">
        {board.isLoading ? (
          <div className="p-6">
            <Skeleton rows={4} />
          </div>
        ) : board.error ? (
          /* Deliberately NOT the empty state. "Every client is fine" is a claim about the
             world, and a failed read is not evidence for it — an operator told the board
             was clear because a token expired would stop looking. `NoticeBox` rather than a
             hand-built box, so this refusal is painted by the same tone table as every
             other verdict in both realms. */
          <div className="p-6">
            <NoticeBox
              tone="warn"
              icon={<TriangleAlert className="h-5 w-5" />}
              title="The board could not be read"
            >
              <p className="mt-1">
                So we cannot say whether any client is in trouble. This is not a healthy
                estate.
              </p>
            </NoticeBox>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Every client looks healthy"
            hint="No account is silent, blocked, near its cap, failing deliveries, or waiting on us to approve knowledge. This list fills up on its own."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-6 py-3 font-semibold">Client</th>
                  <th className="px-6 py-3 font-semibold">Calls (7d vs prior)</th>
                  <th className="px-6 py-3 font-semibold">What is wrong</th>
                  <th className="px-6 py-3 font-semibold">Next step</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row) => (
                  <HealthRow key={row.tenant_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-ink-faint">
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
    <tr className="align-top hover:bg-black/[0.02] dark:hover:bg-white/[0.03]">
      <td className="px-6 py-3">
        <Link
          href={`/admin/tenants/${row.tenant_id}`}
          className="font-semibold text-ink hover:underline"
        >
          {row.name}
        </Link>
        <div className="text-xs text-ink-faint">/c/{row.slug}</div>
        <span
          className={`mt-1 inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${
            NOTICE_TONES[severityTone(row.severity)]
          }`}
        >
          {row.severity === "stop" ? "broken now" : "will break"}
        </span>
      </td>
      <td className="px-6 py-3">
        {/* The whole `after_hours_basis` argument, rendered. An unearned basis prints the
            REASON we cannot say, never a dash and never a 0% that reads as measured. */}
        {trend.kind === "measured" ? (
          <>
            <div className="tabular-nums font-medium text-ink">
              {trend.to} <span className="text-ink-faint">vs {trend.from}</span>
            </div>
            <div className="text-xs text-ink-muted">
              {trend.droppedPct > 0
                ? `down ${trend.droppedPct}%`
                : `up ${Math.abs(trend.droppedPct)}%`}
            </div>
          </>
        ) : (
          <div className="text-xs text-ink-muted">{trend.why}</div>
        )}
        <div className="mt-1 text-xs text-ink-faint">Last call {formatIST(row.last_call_at)}</div>
      </td>
      <td className="px-6 py-3">
        <ul className="space-y-2">
          {row.signals.map((signal) => (
            <SignalCell key={signal.rule} signal={signal} row={row} />
          ))}
        </ul>
      </td>
      <td className="px-6 py-3">
        <div className="flex flex-col items-start gap-1">
          {[...remedies(row)].map(([href, cta]) => (
            <Link
              key={href}
              href={href}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
            >
              {cta}
              <ArrowRight className="h-3 w-3" />
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

/**
 * The spend behind a `spend_cap_near`, in rupees, or null when there is no ceiling to be
 * near.
 *
 * The percentage is the SERVER's integer, computed from `Decimal`s — this adds the two
 * amounts it was computed from so an operator can act on it ("raise it by how much?")
 * without opening the account. Both are printed through `formatINR`, which formats the
 * DIGITS of the string the API sent and never parses them: `Number("10159.0000")` is how
 * ₹10,159.00 becomes ₹10,158.999999999998 on the screen an operator quotes to a client
 * (hard rule 7, and `UsagePanelOut`'s docstring).
 *
 * This is a rupee AMOUNT, not a rate, so two decimals is the right precision — the
 * distinction `/c/[slug]/usage` draws with its own `rupeeRate`, where `overage_rate_inr`
 * is NUMERIC(12,4) and rounding it to paise would misquote the published price.
 *
 * `spend_cap_inr` is nullable: an account with no ceiling cannot be near one, so the whole
 * line is absent rather than rendering "₹900.50 of —", which reads like a missing figure.
 */
function spendLine(row: ClientHealth): string | null {
  if (row.spend_cap_inr === null) return null;
  return `${formatINR(row.spend_used_inr)} of ${formatINR(row.spend_cap_inr)}`;
}

function SignalCell({ signal, row }: { signal: HealthSignal; row: ClientHealth }) {
  const copy = signalCopy(signal.rule);
  const count = signalCount(signal);
  const spend = signal.rule === "spend_cap_near" ? spendLine(row) : null;

  return (
    <li className="text-xs">
      <span
        className={`inline-block rounded-full border px-2.5 py-0.5 font-medium ${
          NOTICE_TONES[severityTone(signal.severity)]
        }`}
      >
        {/* A signal added after this build shipped keeps its row and prints as itself. An
            operator who can read the unfamiliar name can go and find out what it is;
            dropping it would hide an account that is genuinely in trouble. */}
        {copy?.label ?? signal.rule}
      </span>
      {count && <span className="ml-2 text-ink-muted">{count}</span>}
      <div className="mt-0.5 text-ink-muted">
        {copy?.meaning ??
          "This console does not know this signal. The account is flagged by it all the same — open the account."}
      </div>
      {spend && <div className="mt-0.5 tabular-nums text-ink-faint">{spend}</div>}
      {signal.causes.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {signal.causes.map((cause) => (
            <li key={cause}>
              <Link
                href={causeHref(cause, row.tenant_id)}
                className="text-ink-muted underline-offset-2 hover:underline"
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

"use client";

import Link from "next/link";
import { ArrowRight, TriangleAlert } from "lucide-react";

import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, LIST_HEAD, StatusPill } from "@/components/admin/kit";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION } from "@/components/console/section";
import {
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
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

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

  /*
   * THE WORK LIST, DECLARED TO THE SCREEN ASSISTANT.
   *
   * HOW MANY AND WHICH RULES, NEVER WHICH CLIENT. Every row here is a different tenant, so
   * the same cross-tenant argument the directory makes applies with more force: these rows
   * say an account is FAILING, and a leaked one is a claim about a named business in a
   * conversation about somebody else. What an operator actually asks this screen is "what
   * am I looking at and what do I do about it" — which the counts and the distinct rule
   * names answer completely, and neither identifies a tenant.
   *
   * The rule names are machine identifiers from `signals[].rule` (the same strings
   * `SIGNAL_COPY` is keyed on), not reviewer prose: this board deliberately fetches none
   * of the latter, and the declaration does not go looking for it either.
   */
  useCopilotSurface({
    route: "/admin/health",
    title: "Client health",
    realm: "admin",
    fields: [],
    facts: board.data
      ? [
          { key: "accounts", label: "Accounts with something wrong", value: String(rows.length) },
          { key: "breaking", label: "Broken now (severity stop)", value: String(breaking.length) },
          {
            key: "warning",
            label: "Will break (severity warn)",
            value: String(rows.length - breaking.length),
          },
          {
            key: "rules",
            label: "Which rules fired, across all listed accounts",
            value:
              [...new Set(rows.flatMap((row) => row.signals.map((signal) => signal.rule)))]
                .sort()
                .join(", ") || "none",
          },
        ]
      : [
          {
            key: "board",
            label: "The health board",
            // "Nobody is in trouble" is the good state and a failed read is not evidence
            // for it — the fourth rule in this module's header, kept here too.
            value: board.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  const answered = !board.isLoading && !board.error && board.data !== undefined;

  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description={
          <>
            Most broken first. Healthy clients are not listed.{" "}
            <InfoTip label="how this board works">
              <p>
                Every signal is derived from the same rules that refuse the client&apos;s dial,
                meter their spend and gate their knowledge, so this board cannot say an
                account is fine while the client is looking at a refusal.
              </p>
              <p>A row leaves the list when the thing behind it is fixed. The full roster is on Clients.</p>
            </InfoTip>
          </>
        }
        // The number an operator carries away is "how many, and how bad" — and only from
        // a board that ARRIVED: over a failed read there is no headline at all.
        status={
          answered && rows.length > 0 ? (
            <>
              <span className="text-body font-medium text-ink">
                {rows.length} {rows.length === 1 ? "account" : "accounts"} need attention
              </span>
              {breaking.length > 0 && <StatusPill tone="stop">{breaking.length} broken now</StatusPill>}
            </>
          ) : undefined
        }
      />

      {board.error && <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />}

      <div>
        {board.isLoading ? (
          <Skeleton rows={4} />
        ) : board.error || !board.data ? (
          /* Deliberately NOT the empty state: "every client is fine" is a claim about the
             world, and a failed read is not evidence for it. `|| !board.data` because a
             query PAUSED offline reports no error and no data, and used to fall through to
             the empty state. */
          <div>
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
            message={
              <>
                <span className="block font-medium text-ink">Every client looks healthy</span>
                No account is silent, blocked, near its cap, failing deliveries, or waiting on
                us to approve knowledge. This list fills up on its own.
              </>
            }
          />
        ) : (
          <>
            <div
              aria-hidden
              className={`hidden grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_9rem_minmax(0,0.9fr)] gap-5 pb-2 sm:px-2 lg:grid ${LIST_HEAD}`}
            >
              <span>Client</span>
              <span>What is wrong</span>
              <span>Calls, 7d vs prior</span>
              <span>Next step</span>
            </div>
            <ul aria-label="Client health board" className={HAIRLINE_LIST}>
              {rows.map((row) => (
                <HealthRow key={row.tenant_id} row={row} />
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

function HealthRow({ row }: { row: ClientHealth }) {
  const trend = trendClaim(row);

  return (
    <li className="grid gap-x-5 gap-y-3 py-4 sm:px-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_9rem_minmax(0,0.9fr)]">
      <div className="min-w-0">
        <Link
          href={`/admin/tenants/${row.tenant_id}`}
          className="block truncate rounded-sm text-body font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          {row.name}
        </Link>
        <div className="truncate text-meta text-ink-muted">/c/{row.slug}</div>
        <StatusPill tone={severityTone(row.severity)} className="mt-1.5">
          {row.severity === "stop" ? "Broken now" : "Will break"}
        </StatusPill>
      </div>
      <ul className="min-w-0 space-y-2">
        {row.signals.map((signal) => (
          <SignalCell key={signal.rule} signal={signal} row={row} />
        ))}
      </ul>
      <div className="text-meta">
        <span className="font-medium text-ink-muted lg:sr-only">Calls, 7 days vs prior: </span>
        {/* An unearned basis prints the REASON we cannot say, never a dash and never a 0%
            that reads as measured. */}
        {trend.kind === "measured" ? (
          <>
            <span className="tabular-nums text-body font-medium text-ink">
              {trend.to} <span className="text-ink-faint">vs {trend.from}</span>
            </span>
            <span className="ml-1.5 text-ink-muted lg:ml-0 lg:block">
              {trend.droppedPct > 0 ? `down ${trend.droppedPct}%` : `up ${Math.abs(trend.droppedPct)}%`}
            </span>
          </>
        ) : (
          <span className="text-ink-muted lg:block">{trend.why}</span>
        )}
        <span className="mt-0.5 block text-ink-faint">Last call {formatIST(row.last_call_at)}</span>
      </div>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-1 lg:flex-col">
        {[...remedies(row)].map(([href, cta]) => (
          <Link key={href} href={href} className={`${TEXT_ACTION} max-w-full`}>
            <span className="truncate">{cta}</span>
            <ArrowRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
          </Link>
        ))}
      </div>
    </li>
  );
}

/**
 * The destinations this row offers, deduped by href: several signals share one screen,
 * and an operator does not need the same page offered three times on one row. A signal
 * this build cannot name still contributes its account link (see `signalCopy`).
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
    // A blocked account's causes go to the desk that clears each one; for the two R-11
    // gates that is the hold queue's OWN screen and call to action (`HOLD_RULES`).
    for (const cause of signal.causes) {
      found.set(causeHref(cause, row.tenant_id), causeCta(cause));
    }
  }
  return found;
}

/**
 * The spend behind a `spend_cap_near`, or null with no ceiling to be near. Both amounts go
 * through `formatINR`, which formats the DIGITS the API sent and never parses them
 * (hard rule 7).
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
    <li className="text-meta">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {/* A signal added after this build keeps its row and prints as itself. */}
        <StatusPill tone={severityTone(signal.severity)}>{copy?.label ?? signal.rule}</StatusPill>
        {count && <span className="text-ink-muted">{count}</span>}
        {copy && (
          <InfoTip label={copy.label} align="start">
            {copy.meaning}
          </InfoTip>
        )}
      </div>
      {/* The unknown signal's sentence stays visible: it is the instruction, not help. */}
      {!copy && (
        <p className="mt-0.5 text-ink-muted">
          This console does not know this signal. The account is flagged by it all the same —
          open the account.
        </p>
      )}
      {spend && <div className="mt-0.5 tabular-nums text-ink-faint">{spend}</div>}
      {signal.causes.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {signal.causes.map((cause) => (
            <li key={cause} className="text-ink-muted">
              {causeLabel(cause)}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

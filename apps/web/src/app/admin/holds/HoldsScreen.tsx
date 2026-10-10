"use client";

import Link from "next/link";
import { ArrowRight, TriangleAlert } from "lucide-react";

import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, LIST_HEAD, StatusPill } from "@/components/admin/kit";
import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useHeldTenants } from "@/lib/api/admin";
import {
  WAIT_BREACH_HOURS,
  holdRule,
  hoursWaiting,
  waitBand,
  waitedFor,
  type HeldTenant,
} from "@/lib/api/holds";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * THE OPS WORK QUEUE: accounts that cannot dial until someone here acts, oldest first.
 *
 * Two R-11 gates hold tenants — subscriber KYC and the first-campaign review — and without
 * this queue an operator found a held account when the client emailed to ask why nothing
 * worked, which is worst for the accounts that never complain and simply churn.
 *
 * - **The wait is the headline**, as a banded DURATION, never a date to subtract.
 * - **Every row ends in a control**: each rule names the screen that clears it, deduped by
 *   destination, and a rule this build does not know still sends the operator somewhere real.
 * - **Empty is the GOOD state**, and is said only when the server answered. A failed or
 *   PAUSED read (TanStack parks a query while the browser is offline: `isLoading` false,
 *   `error` null) gets its own branch: "nobody is waiting" is a claim about the world.
 *
 * The server's order is kept (oldest signup first is triage). Hard rule 6 is a property of
 * the payload: no phone, no document reference, no reviewer prose — and nothing here
 * fetches any of it back.
 */
export function HoldsScreen() {
  const queue = useHeldTenants();
  const rows = queue.data ?? [];
  // One clock for the whole render, so rows cannot land in different bands.
  const now = Date.now();
  const breaching = rows.filter((row) => hoursWaiting(row.signed_up_at, now) >= WAIT_BREACH_HOURS);

  /*
   * DEPTH AND AGE, NOT THE ROSTER: every row names a business that cannot dial, so counts go
   * and names do not. The longest wait is a DURATION from the same `now` as the rows.
   */
  useCopilotSurface({
    route: "/admin/holds",
    title: "Waiting on us",
    realm: "admin",
    fields: [],
    facts: queue.data
      ? [
          { key: "waiting", label: "Accounts waiting on a human", value: String(rows.length) },
          {
            key: "breaching",
            label: `Waiting longer than ${WAIT_BREACH_HOURS / 24} days`,
            value: String(breaching.length),
          },
          {
            key: "longest_wait",
            label: "Longest anyone has waited",
            value: rows.length === 0 ? "nobody is waiting" : waitedFor(rows[0].signed_up_at, now),
          },
          {
            key: "rules",
            label: "Which gates are holding accounts",
            value:
              [...new Set(rows.flatMap((row) => row.holds))]
                .map((rule) => holdRule(rule)?.label ?? rule)
                .sort()
                .join(", ") || "none",
          },
        ]
      : [
          {
            key: "queue",
            label: "The hold queue",
            value: queue.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  const answered = !queue.isLoading && !queue.error && queue.data !== undefined;

  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description={
          <>
            Accounts that cannot dial until we act. Oldest first.{" "}
            <InfoTip label="About this queue">
              Read-only: every decision is recorded on the account&apos;s own screen, where it
              is audited. A row leaves this list when the gate that held it is cleared — the
              list is built from the same predicates that refuse the client&apos;s dial and
              launch, so it cannot say an account is clear while the client is staring at a
              refusal.
            </InfoTip>
          </>
        }
      />

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      {/* The count an operator carries away — "how many, and is anything rotting" — above
          the list, not as a row to scroll to. Derived from the rows, not read off the
          first one, so it cannot go quietly wrong if the order ever changes. */}
      {answered && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-body font-medium text-ink">
            {rows.length} {rows.length === 1 ? "account" : "accounts"} waiting
          </span>
          {breaching.length > 0 && <StatusPill tone="stop">{breaching.length} waiting over a week</StatusPill>}
          <span className="text-meta text-ink-muted">
            Longest wait: {waitedFor(longestWait(rows), now)}
          </span>
        </div>
      )}

      <div>
        {queue.isLoading ? (
          <Skeleton rows={4} />
        ) : !answered ? (
          <div>
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
          <EmptyState message="Nobody is waiting on us" />
        ) : (
          <HoldList rows={rows} now={now} />
        )}
      </div>
    </div>
  );
}

/** The earliest signup on the list — only called with a non-empty list. */
function longestWait(rows: HeldTenant[]): string {
  return rows.reduce((oldest, row) =>
    new Date(row.signed_up_at) < new Date(oldest.signed_up_at) ? row : oldest,
  ).signed_up_at;
}

const GRID = "md:grid md:grid-cols-[minmax(0,1.2fr)_8rem_minmax(0,1.6fr)_auto] md:items-start md:gap-6";

/**
 * A list rather than a table: each row is a short work item (who, how long, why, the next
 * step) that has to read on a phone without a sideways scroll. The column header is for the
 * wide layout only; on a phone each row stacks.
 */
function HoldList({ rows, now }: { rows: HeldTenant[]; now: number }) {
  return (
    <div>
      <div
        aria-hidden
        className={`hidden pb-2 sm:px-2 ${LIST_HEAD} ${GRID}`}
      >
        <span>Client</span>
        <span>Waiting</span>
        <span>Held on</span>
        <span className="text-right">Next step</span>
      </div>
      <ul aria-label="Accounts held on us" className={HAIRLINE_LIST}>
        {rows.map((row) => (
          <HoldRow key={row.tenant_id} row={row} now={now} />
        ))}
      </ul>
    </div>
  );
}

function HoldRow({ row, now }: { row: HeldTenant; now: number }) {
  const band = waitBand(row.signed_up_at, now);
  // Two rules can share a remedy (`kyc_missing` and `kyc_not_verified`), so destinations
  // are deduped by href rather than offering the same page twice.
  const remedies = new Map<string, string>();
  for (const rule of row.holds) {
    const copy = holdRule(rule);
    if (copy) remedies.set(copy.screen(row.tenant_id), copy.cta);
  }
  const unknown = row.holds.filter((rule) => holdRule(rule) === null);

  return (
    <li className={`space-y-2 py-3 sm:px-2 md:space-y-0 ${GRID}`}>
      <div className="min-w-0">
        <Link
          href={`/admin/tenants/${row.tenant_id}`}
          className="rounded-sm text-body font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          {row.name}
        </Link>
        <div className="text-meta text-ink-muted">
          /c/{row.slug} · {row.plan_tier}
        </div>
      </div>
      <div>
        <WaitPill row={row} band={band} now={now} />
      </div>
      <ul className="space-y-1.5">
        {row.holds.map((rule) => {
          const copy = holdRule(rule);
          return (
            <li key={rule} className="text-meta">
              <span className="font-medium text-ink">{copy?.label ?? rule}</span>
              <div className="text-ink-muted">
                {copy?.blocks ??
                  "This console does not know this rule. The account is held by it all the same — open the account."}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap gap-x-4 gap-y-1 md:flex-col md:items-end">
        {[...remedies].map(([href, cta]) => (
          <Link key={href} href={href} className={TEXT_ACTION}>
            {cta}
            <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        ))}
        {/* A rule this build cannot name still has an account behind it: send the operator
            somewhere real rather than inventing a remedy. */}
        {unknown.length > 0 && (
          <Link
            href={`/admin/tenants/${row.tenant_id}`}
            className={TEXT_ACTION}
          >
            Open the account
            <ArrowRight aria-hidden className="h-3 w-3" />
          </Link>
        )}
      </div>
    </li>
  );
}

function WaitPill({
  row,
  band,
  now,
}: {
  row: HeldTenant;
  band: ReturnType<typeof waitBand>;
  now: number;
}) {
  // The duration is the fact; the signup instant is its evidence, kept in the tooltip so the
  // column stays scannable without becoming unverifiable.
  return (
    <span title={`Signed up ${formatIST(row.signed_up_at)} IST`}>
      <StatusPill tone={band}>{waitedFor(row.signed_up_at, now)}</StatusPill>
    </span>
  );
}

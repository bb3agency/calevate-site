"use client";

import Link from "next/link";
import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
} from "@/components/ui";
import { currentISTMonth } from "@/lib/api/invoice";
import { useFleetSpend, type FleetTenant } from "@/lib/api/spend";

/**
 * THE MONEY BOARD — every live client's month, worst margin first.
 *
 * It answers one question and is laid out around it: **which client is costing us money?**
 * The per-client margin card says whether ONE account is healthy; nothing said which of
 * them to open, so the answer lived in whoever happened to check.
 *
 * ## NOTHING TRUNCATES, AND THAT IS DELIBERATE
 *
 * The server walks every live client's month one `tenant_session` at a time (`usage_events`
 * is FORCE RLS'd, so a cross-tenant `SUM` is unaskable in app code and reaching for the
 * admin DB role to get one would break hard rule 1). It is therefore the slowest read in
 * this console, it is not polled, and it hides nobody — a money board that quietly dropped
 * the client at the bottom would defeat the board. The server logs and names a remedy when
 * its own walk goes over budget rather than cutting the list.
 *
 * ## MONEY
 *
 * Every figure is an exact decimal STRING from the server and goes through `formatINR`,
 * which formats the digits and never parses them. NOTHING on this page is summed in the
 * browser: `revenue_inr`, `cost_inr` and `margin_inr` at the top are the server's own sums
 * of the rows, and adding them here would be float arithmetic on money (hard rule 7) with a
 * second answer to a question already answered.
 *
 * The page carries no `<h1>` — the shell derives the title from the nav list it renders the
 * sidebar from (`app/admin/layout.tsx`), so a heading here would repeat it.
 */
export default function FleetSpendPage() {
  const [month, setMonth] = useState(currentISTMonth);
  const board = useFleetSpend(month);
  const data = board.data;

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          What every live client billed and cost us this month, worst margin first.
          Suspended and closed accounts are not included.
        </p>
        <input
          type="month"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
          aria-label="Billing month"
        />
      </div>

      {board.error && <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />}

      {/* §52: a skeleton is not a fleet total and a failed walk is not "we made ₹0". */}
      {!data ? (
        board.error ? null : (
          <Skeleton rows={6} label="Adding up every client's month" />
        )
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
            <StatTile label="Our cost" value={formatINR(data.cost_inr)} />
            <div className="rounded-card border border-line bg-surface p-5">
              <p className="text-[13px] font-medium text-ink-muted">Margin</p>
              <p
                className={
                  data.margin_inr.trim().startsWith("-")
                    ? "mt-1 text-2xl font-bold tracking-tight tabular-nums text-rose-600 dark:text-rose-400"
                    : "mt-1 text-2xl font-bold tracking-tight tabular-nums text-brand-strong dark:text-brand-bright"
                }
              >
                {formatINR(data.margin_inr)}
              </p>
            </div>
            {/* null, not 0%: "nothing billed across the fleet" and "we made nothing" are
                different facts. */}
            <StatTile
              label="Margin %"
              value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
              hint={`${formatCount(data.clients)} live ${data.clients === 1 ? "client" : "clients"} walked.`}
            />
          </div>

          <Card bodyClassName="p-0">
            {data.tenants.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No live clients this month"
                  hint="Suspended and closed accounts are deliberately left out."
                />
              </div>
            ) : (
              <ScrollRegion label="Every live client's month">
                <table className="w-full min-w-[820px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                      <th className="px-4 py-3 font-semibold sm:px-6">Client</th>
                      <th className="px-4 py-3 font-semibold sm:px-6">Plan</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Calls</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Revenue</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Our cost</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.tenants.map((tenant) => (
                      <FleetRow key={tenant.tenant_id} tenant={tenant} />
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * One client's row, linking to the screen that says WHERE that margin came from.
 *
 * A losing month is marked rather than only coloured: colour is the one signal the a11y
 * sweep cannot check and the one a colour-blind operator may not have, so the warning
 * triangle carries a text alternative of its own.
 */
function FleetRow({ tenant }: { tenant: FleetTenant }) {
  const negative = tenant.margin_inr.trim().startsWith("-");
  return (
    <tr className={negative ? NOTICE_TONES.stop : undefined}>
      <td className="px-4 py-3 sm:px-6">
        <Link
          href={`/admin/tenants/${tenant.tenant_id}/spend`}
          className="font-medium text-ink underline underline-offset-2 hover:text-brand-strong"
        >
          {tenant.name}
        </Link>
        <span className="ml-2 text-xs text-ink-faint">/c/{tenant.slug}</span>
      </td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{tenant.plan_tier}</td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">{formatCount(tenant.calls)}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {tenant.minutes_used}
      </td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">
        {formatINR(tenant.revenue_inr)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {formatINR(tenant.cost_inr)}
      </td>
      <td className="px-4 py-3 text-right font-semibold tabular-nums sm:px-6">
        {negative && (
          <>
            <TriangleAlert aria-hidden className="mr-1 inline h-3.5 w-3.5" />
            <span className="sr-only">Losing money: </span>
          </>
        )}
        {formatINR(tenant.margin_inr)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {tenant.margin_pct === null ? "not billed yet" : `${tenant.margin_pct}%`}
      </td>
    </tr>
  );
}

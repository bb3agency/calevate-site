"use client";

import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import Link from "next/link";
import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, MetricRow } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import {
  FIELD_INLINE,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { currentISTMonth } from "@/lib/api/invoice";
import {
  isZeroMoney,
  marginPctLabel,
  useFleetSpend,
  type FleetSpend,
  type FleetTenant,
} from "@/lib/api/spend";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { VoiceCostModel } from "./VoiceCostModel";

/**
 * THE MONEY BOARD — every live client's month, worst margin first. It answers one question:
 * **which client is costing us money?** The margin is the margin on PAID calling: a free
 * trial's calls charge nothing by design, so their cost is its own column and total ("Trial
 * cost we cover"), an acquisition cost, and a trial client never reads as losing money.
 *
 * NOTHING TRUNCATES. The server walks every live client one `tenant_session` at a time
 * (`usage_events` is FORCE RLS'd, so a cross-tenant `SUM` is unaskable in app code), so it is
 * the slowest read in this console and is not polled — and it hides nobody. The server's
 * order is kept: re-sorting here would be a second opinion about triage.
 *
 * MONEY: every figure is an exact decimal STRING formatted by `formatINR`, and nothing is
 * summed in the browser — the totals are the server's own sums of the rows.
 */
export function FleetSpendScreen() {
  const [month, setMonth] = useState(currentISTMonth);
  const board = useFleetSpend(month);
  const data = board.data;

  /*
   * FLEET TOTALS, NO CLIENT ROWS. Every row below belongs to a DIFFERENT client, so sending
   * the table would drop one client's revenue into a conversation about another — hard
   * rule 1's leak with no query to blame. The sums and counts are CALEVATE's own margin, so
   * they go. The month is read-only: changing it re-walks every client.
   */
  useCopilotSurface({
    route: "/admin/spend",
    title: "Spend and margin, every client",
    realm: "admin",
    fields: [
      {
        id: "fleet-spend-month",
        label: "Billing month",
        type: "text",
        value: month,
        writable: false,
        help: "IST billing month as YYYY-MM. Changing it walks every live client again.",
      },
    ],
    facts: data
      ? [
          { key: "month", label: "Month shown", value: data.month },
          { key: "clients", label: "Live clients walked", value: String(data.clients) },
          { key: "revenue_inr", label: "Fleet revenue (₹)", value: data.revenue_inr },
          { key: "cost_inr", label: "What the fleet cost us (₹)", value: data.cost_inr },
          { key: "paid_cost_inr", label: "What the fleet's paid calls cost us (₹)", value: data.paid_cost_inr },
          {
            key: "trial_cost_inr",
            label: "Free trial calls we covered across the fleet (₹), an acquisition cost outside the margin",
            value: data.trial_cost_inr,
          },
          { key: "paid_margin_inr", label: "Fleet margin on paid calls (₹)", value: data.paid_margin_inr },
          {
            key: "paid_margin_pct",
            label: "Fleet margin on paid calls (%)",
            value: data.paid_margin_pct ?? "nothing billed this month",
          },
          { key: "margin_inr", label: "Fleet margin all in, trial cost included (₹)", value: data.margin_inr },
          {
            key: "ai_absorbed_inr",
            label: "Dashboard AI we absorbed across the fleet (₹), outside revenue, cost and margin",
            value: data.ai_absorbed_inr,
          },
          {
            key: "loss_making",
            label: "Clients whose month is losing money",
            value: String(data.tenants.filter((row) => losing(row.paid_margin_inr)).length),
          },
        ]
      : [
          {
            key: "board",
            label: "The board",
            // Never "₹0": a read that did not arrive is not a month with no revenue (§52).
            value: board.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description={
          <>
            Every live client this month, worst margin first.{" "}
            <InfoTip label="Who is on this board">
              Suspended and closed accounts are not included.
            </InfoTip>
          </>
        }
        actions={
          <input
            type="month"
            value={month}
            // No future months: an empty 2027 board reads like a failure (ux-audit F-9a).
            max={currentISTMonth()}
            onChange={(event) => setMonth(event.target.value)}
            className={FIELD_INLINE}
            aria-label="Billing month"
          />
        }
      />

      {board.error && <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />}

      {/* §52: a skeleton is not a fleet total and a failed walk is not "we made ₹0". */}
      {!data ? (
        board.error ? null : <Skeleton rows={6} label="Adding up every client's month" />
      ) : (
        <>
          <UnpricedNotice count={data.unpriced_rows} />
          <Totals data={data} />
          <ClientTable data={data} />
          {/* A footnote to the totals, never collapsed: these are the clients the figures
              above do NOT include. */}
          <UndecidableCard board={data} />
        </>
      )}

      <VoiceCostModel board={data} />
    </div>
  );
}

function losing(margin: string): boolean {
  return margin.trim().startsWith("-");
}

function Totals({ data }: { data: FleetSpend }) {
  const negative = losing(data.paid_margin_inr);
  const trialCost = !isZeroMoney(data.trial_cost_inr);
  return (
    <MetricRow>
      <Metric label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
      <Metric
        label={trialCost ? "Our cost of paid calls" : "Our cost"}
        value={formatINR(data.paid_cost_inr)}
      />
      {trialCost && (
        <Metric
          label="Trial cost we cover"
          value={formatINR(data.trial_cost_inr)}
          hint="Free trial calls: an acquisition cost, not in the margin."
        />
      )}
      <Metric
        label="Margin"
        tone={negative ? "danger" : "default"}
        value={
          <>
            {/* Colour is never the only signal that a month is losing money (F-18). */}
            {negative && <span className="sr-only">Losing money: </span>}
            {formatINR(data.paid_margin_inr)}
          </>
        }
      />
      {/* null, not 0%: "nothing billed across the fleet" and "we made nothing" differ. */}
      <Metric
        label="Margin %"
        value={data.paid_margin_pct === null ? "not billed yet" : `${data.paid_margin_pct}%`}
        hint={`${formatCount(data.clients)} live ${data.clients === 1 ? "client" : "clients"} walked.`}
      />
      {/* Outside the margin: the assistant has no matching revenue (AbsorbedAiSpendOut). */}
      <Metric
        label="AI we absorb"
        value={formatINR(data.ai_absorbed_inr)}
        hint={`${ASSISTANT_NAME}, AI tools, the standby model and post-call extraction. Not billed, not in the margin.`}
      />
    </MetricRow>
  );
}

const num = "whitespace-nowrap tabular-nums";

/**
 * One row per client, linking to the screen that says WHERE that margin came from. The
 * whole row is the link (one target, UX-DOCTRINE §4). Columns drop away by width rather than
 * forcing a min-width, so the board never scrolls the page sideways on a phone: the client,
 * the revenue and the margin always stay.
 */
function ClientTable({ data }: { data: FleetSpend }) {
  if (data.tenants.length === 0) {
    return <EmptyState message="No live clients this month" />;
  }
  const columns: DataColumn<FleetTenant>[] = [
    {
      id: "client",
      header: "Client",
      cell: (tenant) => (
        <>
          <Link
            href={`/admin/tenants/${tenant.tenant_id}/spend`}
            className="rounded-sm font-medium text-ink underline underline-offset-2 after:absolute after:inset-0 hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {tenant.name}
          </Link>
          <span className="block text-meta text-ink-muted">/c/{tenant.slug}</span>
        </>
      ),
    },
    { id: "plan", header: "Plan", hideBelow: "lg", cell: (tenant) => <span className="text-ink-muted">{tenant.plan_tier}</span> },
    { id: "calls", header: "Calls", align: "right", hideBelow: "md", cell: (tenant) => <span className={num}>{formatCount(tenant.calls)}</span> },
    { id: "minutes", header: "Minutes", align: "right", hideBelow: "lg", cell: (tenant) => <span className={`${num} text-ink-muted`}>{tenant.minutes_used}</span> },
    { id: "revenue", header: "Revenue", align: "right", cell: (tenant) => <span className={num}>{formatINR(tenant.revenue_inr)}</span> },
    { id: "cost", header: "Our cost", align: "right", hideBelow: "sm", cell: (tenant) => <span className={`${num} text-ink-muted`}>{formatINR(tenant.paid_cost_inr)}</span> },
    {
      id: "trial",
      header: "Trial cost we cover",
      align: "right",
      hideBelow: "md",
      cell: (tenant) => (
        <span className={`${num} text-ink-muted`}>
          {isZeroMoney(tenant.trial_cost_inr) && !tenant.trial_in_month ? "—" : formatINR(tenant.trial_cost_inr)}
        </span>
      ),
    },
    {
      id: "margin",
      header: "Margin",
      align: "right",
      cell: (tenant) => (
        <span className={`${num} font-semibold`}>
          {losing(tenant.paid_margin_inr) && (
            <>
              <TriangleAlert aria-hidden className="mr-1 inline h-3.5 w-3.5" />
              <span className="sr-only">Losing money: </span>
            </>
          )}
          {formatINR(tenant.paid_margin_inr)}
        </span>
      ),
    },
    {
      id: "ai",
      header: "AI we absorb",
      align: "right",
      hideBelow: "md",
      cell: (tenant) => (
        <span className={`${num} text-ink-muted`}>
          {formatINR(tenant.ai_absorbed_inr)}
          {/* The space keeps the count a separate word for screen readers and copy-paste. */}
          {tenant.ai_requests > 0 && " "}
          {tenant.ai_requests > 0 && (
            <span className="block text-meta">
              {formatCount(tenant.ai_requests)} {tenant.ai_requests === 1 ? "action" : "actions"}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "pct",
      header: "Margin %",
      align: "right",
      hideBelow: "sm",
      cell: (tenant) => (
        <span className={`${num} text-ink-muted`}>
          {marginPctLabel(tenant.paid_margin_pct, tenant.trial_in_month)}
        </span>
      ),
    },
    {
      // D-840: rows with no cost, and what the voice platform charged against what we
      // metered for the month's settled calls. Shown, never corrected on the ledger.
      id: "unpriced",
      header: "Not priced · vs charged",
      align: "right",
      hideBelow: "lg",
      cell: (tenant) => (
        <span className={`${num} text-ink-muted`}>
          {tenant.unpriced_rows > 0 ? (
            <span className="font-medium text-warn">
              {formatCount(tenant.unpriced_rows)} not priced
            </span>
          ) : (
            "—"
          )}
          {tenant.charge_variance_inr != null && (
            <span className="block text-meta">
              {formatINR(tenant.charge_variance_inr)} vs charged
            </span>
          )}
        </span>
      ),
    },
  ];
  return (
    <DataTable
      rows={data.tenants}
      columns={columns}
      getRowId={(tenant) => tenant.tenant_id}
      label="Every live client's month"
      rowClassName={(tenant) => (losing(tenant.paid_margin_inr) ? "bg-danger-soft/60 text-danger" : "")}
    />
  );
}

/**
 * THE CLIENTS THE TOTALS LEAVE OUT, named with the server's own reason. A board that silently
 * walked 59 of 60 clients under-reports revenue and says nothing. Renders NOTHING when the
 * list is empty, which is normal: an always-present "0 problems" card trains an operator to
 * stop reading this spot.
 */
/**
 * USAGE THE COSTS ABOVE LEAVE OUT (D-840): rows the meter wrote with no cost because a rate
 * or a fee was not recorded. Counted, never priced at ₹0. Renders nothing when there are none.
 */
export function UnpricedNotice({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <p className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn-soft/40 px-3 py-2 text-body text-ink">
      <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <span>
        {formatCount(count)} usage {count === 1 ? "row has" : "rows have"} no cost this month
        because a rate or fee was not recorded, so the costs above are floors and the margins
        are ceilings. Record the missing figure under Ops → Pricing → Per-minute rates.
      </span>
    </p>
  );
}

function UndecidableCard({ board }: { board: FleetSpend }) {
  const rows = board.undecidable ?? [];
  if (rows.length === 0) return null;
  return (
    <Section
      title={`${formatCount(rows.length)} ${rows.length === 1 ? "client is" : "clients are"} not in the totals above`}
      description={<>Their month could not be priced from the ledger. Every other client&rsquo;s figures above are complete.</>}
    >
      <ul className={HAIRLINE_LIST}>
        {rows.map((row) => (
          <li key={row.tenant_id} className="py-3 sm:px-2">
            <Link
              href={`/admin/tenants/${row.tenant_id}/spend`}
              className="rounded-sm text-body font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              {row.name}
            </Link>
            <p className="text-meta text-ink-muted">
              /c/{row.slug} · {row.plan_tier}
            </p>
            <p className="mt-1 text-meta text-ink-muted">{row.reason}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import {
  Card,
  FIELD_INLINE,
  NOTICE_TONES,
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
import { useFleetSpend, type FleetSpend, type FleetTenant } from "@/lib/api/spend";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { VoiceCostModel } from "./VoiceCostModel";

/**
 * THE MONEY BOARD — every live client's month, worst margin first. It answers one question:
 * **which client is costing us money?**
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
          { key: "margin_inr", label: "Fleet margin (₹)", value: data.margin_inr },
          { key: "margin_pct", label: "Fleet margin (%)", value: data.margin_pct ?? "nothing billed this month" },
          {
            key: "loss_making",
            label: "Clients whose month is losing money",
            value: String(data.tenants.filter((row) => losing(row.margin_inr)).length),
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
    <div className="space-y-6 pb-12">
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
  const negative = losing(data.margin_inr);
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
      <Metric label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
      <Metric label="Our cost" value={formatINR(data.cost_inr)} />
      <Metric
        label="Margin"
        tone={negative ? "danger" : "default"}
        value={
          <>
            {/* Colour is never the only signal that a month is losing money (F-18). */}
            {negative && <span className="sr-only">Losing money: </span>}
            {formatINR(data.margin_inr)}
          </>
        }
      />
      {/* null, not 0%: "nothing billed across the fleet" and "we made nothing" differ. */}
      <Metric
        label="Margin %"
        value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
        hint={`${formatCount(data.clients)} live ${data.clients === 1 ? "client" : "clients"} walked.`}
      />
    </div>
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
    return (
      <Card density="compact">
        <EmptyState message="No live clients this month" />
      </Card>
    );
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
          <span className="block text-xs text-ink-faint">/c/{tenant.slug}</span>
        </>
      ),
    },
    { id: "plan", header: "Plan", hideBelow: "lg", cell: (tenant) => <span className="text-ink-muted">{tenant.plan_tier}</span> },
    { id: "calls", header: "Calls", align: "right", hideBelow: "md", cell: (tenant) => <span className={num}>{formatCount(tenant.calls)}</span> },
    { id: "minutes", header: "Minutes", align: "right", hideBelow: "lg", cell: (tenant) => <span className={`${num} text-ink-muted`}>{tenant.minutes_used}</span> },
    { id: "revenue", header: "Revenue", align: "right", cell: (tenant) => <span className={num}>{formatINR(tenant.revenue_inr)}</span> },
    { id: "cost", header: "Our cost", align: "right", hideBelow: "sm", cell: (tenant) => <span className={`${num} text-ink-muted`}>{formatINR(tenant.cost_inr)}</span> },
    {
      id: "margin",
      header: "Margin",
      align: "right",
      cell: (tenant) => (
        <span className={`${num} font-semibold`}>
          {losing(tenant.margin_inr) && (
            <>
              <TriangleAlert aria-hidden className="mr-1 inline h-3.5 w-3.5" />
              <span className="sr-only">Losing money: </span>
            </>
          )}
          {formatINR(tenant.margin_inr)}
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
          {tenant.margin_pct === null ? "not billed yet" : `${tenant.margin_pct}%`}
        </span>
      ),
    },
  ];
  return (
    <Card density="compact" bodyClassName="px-0 py-1">
      <DataTable
        rows={data.tenants}
        columns={columns}
        getRowId={(tenant) => tenant.tenant_id}
        label="Every live client's month"
        rowClassName={(tenant) => (losing(tenant.margin_inr) ? NOTICE_TONES.stop : "")}
      />
    </Card>
  );
}

/**
 * THE CLIENTS THE TOTALS LEAVE OUT, named with the server's own reason. A board that silently
 * walked 59 of 60 clients under-reports revenue and says nothing. Renders NOTHING when the
 * list is empty, which is normal: an always-present "0 problems" card trains an operator to
 * stop reading this spot.
 */
function UndecidableCard({ board }: { board: FleetSpend }) {
  const rows = board.undecidable ?? [];
  if (rows.length === 0) return null;
  return (
    <Card
      density="compact"
      title={`${formatCount(rows.length)} ${rows.length === 1 ? "client is" : "clients are"} not in the totals above`}
    >
      <p className="mb-3 text-[13px] text-ink-muted">
        Their month could not be priced from the ledger. Every other
        client&rsquo;s figures above are complete.
      </p>
      <ul className="divide-y divide-line">
        {rows.map((row) => (
          <li key={row.tenant_id} className="py-3 first:pt-0 last:pb-0">
            <Link
              href={`/admin/tenants/${row.tenant_id}/spend`}
              className="rounded-sm text-sm font-semibold text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              {row.name}
            </Link>
            <p className="text-[13px] text-ink-muted">
              /c/{row.slug} · {row.plan_tier}
            </p>
            <p className="mt-1 text-[13px] text-ink-muted">{row.reason}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

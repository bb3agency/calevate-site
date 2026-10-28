"use client";

import { useState } from "react";

import { BarChart } from "@/components/arc/bar-chart";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatINR,
  hasNonZeroDigit,
} from "@/components/ui";
import {
  useSpendSeries,
  type AgentDailySpend,
  type SpendDay,
  type SpendWindowDays,
} from "@/lib/api/billingHistory";
import type { Session } from "@/lib/api/client";

import { OWNER_ONLY_SPENDING } from "./UsageTab";

const WINDOWS: SpendWindowDays[] = [7, 30, 90];

/** "2026-10-01" → "1 Oct", built and read in UTC so the day is the one the string names. */
function dayLabel(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (match === null) return date;
  const at = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return at.toLocaleDateString("en-IN", { timeZone: "UTC", day: "numeric", month: "short" });
}

const AGENT_COLUMNS: DataColumn<AgentDailySpend>[] = [
  {
    id: "agent",
    header: "Agent",
    cell: (row) =>
      row.agent_name ?? <span className="text-ink-muted">Not attributed to an agent</span>,
    sort: { value: (row) => row.agent_name ?? "" },
  },
  {
    id: "calls_inr",
    header: "Calls",
    align: "right",
    cell: (row) => <span className="tabular-nums">{formatINR(row.calls_inr)}</span>,
    sort: { value: (row) => row.calls_inr, kind: "decimal", first: "desc" },
  },
];

/**
 * What left the wallet each IST day, over a window the reader picks (D-655: 7 / 30 / 90
 * days are peer views of one series). Owner-only, like every figure behind `billing:read`:
 * the read is not even sent for a session that may not see it.
 */
export function SpendOverTime({ session, allowed }: { session: Session; allowed: boolean | null }) {
  const [days, setDays] = useState<SpendWindowDays>(30);
  const series = useSpendSeries(session, { days }, { enabled: allowed === true });

  if (allowed === false) {
    return (
      <RestrictionNote reason={OWNER_ONLY_SPENDING} />
    );
  }

  const data = series.data;
  return (
    <Section
      title="Spending"
      info={
        <p>
          What left your calling credit each day, in Indian Standard Time: calls, phone
          number rental, extra AI help you accepted, and any correction we made. Money you
          added is not spending, so it is not drawn here.
        </p>
      }
      action={
        <SegmentedControl
          label="Spending period"
          value={String(days)}
          onValueChange={(next) => setDays(Number(next) as SpendWindowDays)}
          options={WINDOWS.map((window) => ({ value: String(window), label: `${window} days` }))}
        />
      }
    >
      {series.error ? (
        <ProblemNotice error={series.error} onRetry={() => void series.refetch()} />
      ) : !data ? (
        <Skeleton rows={4} label="Loading your spending" />
      ) : !hasNonZeroDigit(data.spent_inr) ? (
        <EmptyState message={`No spending in the last ${days} days.`} />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Metric label="Spent" value={formatINR(data.spent_inr)} />
            <Metric label="Calls" value={formatINR(data.calls_inr)} />
            {hasNonZeroDigit(data.number_rental_inr) && (
              <Metric label="Phone number rental" value={formatINR(data.number_rental_inr)} />
            )}
            {hasNonZeroDigit(data.ai_assist_inr) && (
              <Metric label="Extra AI help" value={formatINR(data.ai_assist_inr)} />
            )}
            {hasNonZeroDigit(data.adjustments_inr) && (
              <Metric label="Corrections" value={formatINR(data.adjustments_inr)} />
            )}
          </div>
          <DailyBars days={data.days} />
          {data.by_agent.length > 0 && (
            <DataTable
              label={`Calls charged by agent, last ${days} days`}
              columns={AGENT_COLUMNS}
              rows={data.by_agent}
              getRowId={(row) => row.agent_id ?? "unattributed"}
              defaultSort={{ id: "calls_inr", direction: "desc" }}
            />
          )}
        </div>
      )}
    </Section>
  );
}

/**
 * What left the wallet each day. `Number()` sizes the bars only (the kit's chart rule);
 * the readout and the table print the server's string through `formatINR`. A negative day
 * draws as no bar rather than one below the baseline, which would be a second axis.
 */
function DailyBars({ days }: { days: SpendDay[] }) {
  return (
    <BarChart
      title="Spending by day (IST)"
      hideTitle
      description="Rupees spent each day"
      labelColumn="Day"
      categories={days.map((day) => dayLabel(day.date))}
      series={[
        {
          label: "Spent",
          values: days.map((day) => Math.max(0, Number(day.spent_inr))),
          display: days.map((day) => formatINR(day.spent_inr)),
        },
      ]}
      height={160}
      empty="No spending on any day in this period."
    />
  );
}


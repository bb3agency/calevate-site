"use client";

import { useState } from "react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Metric } from "@/components/console/metric";
import { Panel } from "@/components/console/panel";
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

const WINDOWS: SpendWindowDays[] = [7, 30, 90];

// `BigInt(…)` rather than `0n` literals: the project's TS target predates them.
const ZERO = BigInt(0);
const HUNDRED = BigInt(100);
const THOUSAND = BigInt(1000);

/**
 * Whole paise from the server's decimal string, for GEOMETRY ONLY.
 *
 * Bar heights are a ratio of two amounts, and a ratio of floats is how ₹10,159.00 becomes
 * a bar a hair shorter than ₹10,159.00 (hard rule 7). Every figure a reader sees is still
 * the server's string through `formatINR`; this exists so the picture is exact too.
 * Sub-paise digits are dropped (they cannot move a bar a pixel) and a negative day draws
 * as zero, because a bar below the baseline would be a second axis.
 */
export function toPaise(value: string): bigint {
  const match = /^\s*(-?)(\d*)(?:\.(\d*))?\s*$/.exec(value);
  if (match === null) return ZERO;
  const [, sign, whole, fraction = ""] = match;
  const paise = BigInt(whole || "0") * HUNDRED + BigInt((fraction + "00").slice(0, 2));
  return sign === "-" ? ZERO : paise;
}

/** A bar's height as a percentage of the busiest day, from integer arithmetic. */
export function barPercent(value: bigint, max: bigint): number {
  if (max <= ZERO || value <= ZERO) return 0;
  // Per-mille in integers, then one small Number for the CSS length.
  return Number((value * THOUSAND) / max) / 10;
}

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
      <RestrictionNote reason="Spending and usage are limited to the account owner. Ask them to share this month's figures, or to give you owner access." />
    );
  }

  const data = series.data;
  return (
    <Panel
      title="Spending"
      info={
        <p>
          What left your calling credit each day, in Indian Standard Time: calls, extra AI
          help you accepted, and any correction we made. Money you added is not spending, so
          it is not drawn here.
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
    </Panel>
  );
}

function DailyBars({ days }: { days: SpendDay[] }) {
  const values = days.map((day) => toPaise(day.spent_inr));
  const max = values.reduce((top, value) => (value > top ? value : top), ZERO);
  const first = days[0];
  const last = days[days.length - 1];
  const middle = days[Math.floor(days.length / 2)];
  return (
    <div>
      {/* The text alternative: the bars tie each amount to its day by position alone. */}
      <table className="sr-only">
        <caption>Spending by day (IST)</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Spent</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.date}>
              <th scope="row">{dayLabel(day.date)}</th>
              <td>{formatINR(day.spent_inr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div aria-hidden className="flex h-32 items-end gap-[2px] border-b border-line">
        {days.map((day, index) => {
          const percent = barPercent(values[index] ?? ZERO, max);
          return (
            <div
              key={day.date}
              title={`${dayLabel(day.date)}: ${formatINR(day.spent_inr)}`}
              className="flex h-full min-w-0 flex-1 items-end hover:[&>div]:bg-brand-strong"
            >
              {/* 4px rounded data-end anchored to the baseline; a zero day keeps no bar,
                  because a stub would read as a small amount. Bars grow once on first
                  paint and never on a period switch. */}
              <div
                className="w-full origin-bottom rounded-t-[4px] bg-brand transition-[scale,opacity] duration-(--duration-slow) ease-out starting:scale-y-90 starting:opacity-0 motion-reduce:transition-none"
                style={{ height: percent > 0 ? `max(${percent}%, 2px)` : "0" }}
              />
            </div>
          );
        })}
      </div>
      {first && last && middle && (
        <div aria-hidden className="mt-1.5 flex justify-between text-[11px] text-ink-faint">
          <span>{dayLabel(first.date)}</span>
          {days.length > 2 && <span>{dayLabel(middle.date)}</span>}
          <span>{dayLabel(last.date)}</span>
        </div>
      )}
    </div>
  );
}

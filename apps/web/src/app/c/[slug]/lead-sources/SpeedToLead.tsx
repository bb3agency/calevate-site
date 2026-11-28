"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { StatsBand, type StatItem } from "@/components/arc/stats-band";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { SECONDARY_BUTTON_SM, Skeleton, formatCallCap, formatCount } from "@/components/ui";
import {
  useSpeedToLead,
  type SpeedFigures,
  type SpeedPeriod,
  type SpeedSource,
  type SpeedToLead as SpeedToLeadData,
} from "@/lib/api/analytics";
import type { Session } from "@/lib/api/client";
import { saveCsv, tableCsv } from "@/lib/csvDownload";

import { sourceLabel } from "./sourceKinds";

const PERIODS: { value: SpeedPeriod; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
];

export const SPEED_COPY = {
  title: "How fast we called",
  info:
    "From the moment a lead reached us to our first call to them. A lead that came in outside your calling hours is timed from when you released it, or from when your hours opened. India time.",
  period: "Period",
  loading: "Timing your leads",
  error: "We could not load how fast your leads were called.",
  empty: "No new leads from your sources in this period yet.",
  wait: "Typical wait",
  waitHint: "Half were called within this",
  minute: "Called within a minute",
  never: "Never reached",
  neverHint: "Rung and not answered, or not allowed",
  waiting: "Waiting now",
  waitingHint: "Not called yet",
  sources: "By source",
  download: "Download",
  compareTitle: "Called within a minute vs later",
} as const;

function waitWords(seconds: number | null): string {
  return seconds === null ? "—" : formatCallCap(seconds);
}

function share(part: number, whole: number): string {
  return whole === 0 ? "—" : `${Math.round((part * 100) / whole)}%`;
}

/** The four figures, in the order an owner asks them. */
export function speedItems(total: SpeedFigures): StatItem[] {
  return [
    { label: SPEED_COPY.wait, value: waitWords(total.median_s), hint: total.called > 0 ? SPEED_COPY.waitHint : undefined },
    {
      label: SPEED_COPY.minute,
      value: total.called === 0 ? "—" : share(total.within_60s, total.called),
      hint: `${formatCount(total.within_60s)} of ${formatCount(total.called)} called`,
    },
    { label: SPEED_COPY.never, value: formatCount(total.never_reached), hint: SPEED_COPY.neverHint },
    { label: SPEED_COPY.waiting, value: formatCount(total.waiting), hint: SPEED_COPY.waitingHint },
  ];
}

/** "Called within a minute vs later", one short line per side with both counts, or what
 *  is still missing before the server offers it. */
export function compareLines(data: SpeedToLeadData): string[] {
  const c = data.compare;
  if (c === null) {
    return [`Shown from ${formatCount(data.compare_min_leads)} called leads. ${formatCount(data.total.called)} so far.`];
  }
  return [
    `Within a minute: ${formatCount(c.fast_interested)} of ${formatCount(c.fast_called)} interested (${share(c.fast_interested, c.fast_called)})`,
    `Later: ${formatCount(c.later_interested)} of ${formatCount(c.later_called)} interested (${share(c.later_interested, c.later_called)})`,
  ];
}

function sourceName(row: SpeedSource): string {
  return row.source ? sourceLabel(row.source) : "A source since removed";
}

const HEADERS = ["Source", "Leads", "Reached", "Interested", "Typical wait"] as const;

function sourceCells(row: SpeedSource): string[] {
  return [
    sourceName(row),
    String(row.leads),
    String(row.reached),
    String(row.interested),
    waitWords(row.median_s),
  ];
}

/**
 * "How fast we called": proof that new leads are rung at once, from the account's own
 * deliveries (`/v1/analytics/speed-to-lead`). Every figure is the server's; the comparison
 * of fast and later calls appears only from the server's floor, with its counts.
 */
export function SpeedToLead({ session }: { session: Session }) {
  const [period, setPeriod] = useState<SpeedPeriod>("7d");
  const speed = useSpeedToLead(session, period);
  const data = speed.data;

  const columns: DataColumn<SpeedSource>[] = [
    { id: "source", header: HEADERS[0], cell: (row) => <span className="[overflow-wrap:anywhere]">{sourceName(row)}</span> },
    { id: "leads", header: HEADERS[1], align: "right", cell: (row) => formatCount(row.leads), sort: { value: (row) => row.leads, kind: "number", first: "desc" } },
    { id: "reached", header: HEADERS[2], align: "right", cell: (row) => formatCount(row.reached), sort: { value: (row) => row.reached, kind: "number", first: "desc" } },
    { id: "interested", header: HEADERS[3], align: "right", cell: (row) => formatCount(row.interested), sort: { value: (row) => row.interested, kind: "number", first: "desc" } },
    { id: "wait", header: HEADERS[4], align: "right", cell: (row) => waitWords(row.median_s), sort: { value: (row) => row.median_s, kind: "number" } },
  ];

  return (
    <Section
      title={SPEED_COPY.title}
      info={SPEED_COPY.info}
      action={
        <SegmentedControl
          label={SPEED_COPY.period}
          value={period}
          onValueChange={(next) => setPeriod(PERIODS.find((p) => p.value === next)?.value ?? "7d")}
          options={PERIODS}
        />
      }
    >
      {speed.error && !data ? (
        <EmptyState variant="error" message={SPEED_COPY.error} error={speed.error} onRetry={() => void speed.refetch()} />
      ) : !data ? (
        <Skeleton rows={2} label={SPEED_COPY.loading} />
      ) : data.total.leads === 0 ? (
        <EmptyState message={SPEED_COPY.empty} />
      ) : (
        <div className="space-y-4">
          <StatsBand label={SPEED_COPY.title} items={speedItems(data.total)} />
          <div className="text-meta text-ink-muted">
            <p className="font-medium text-ink">{SPEED_COPY.compareTitle}</p>
            {compareLines(data).map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-ink">{SPEED_COPY.sources}</h3>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() => saveCsv(tableCsv(HEADERS, data.sources.map(sourceCells)), `lead-speed-${period}`)}
              >
                <Download aria-hidden className="h-3.5 w-3.5" />
                {SPEED_COPY.download}
              </button>
            </div>
            <DataTable
              rows={data.sources}
              columns={columns}
              getRowId={(row) => row.source_id}
              label="How fast each source's leads were called"
              partialNote={
                data.other_sources > 0
                  ? `${formatCount(data.other_sources)} more leads came from other sources.`
                  : undefined
              }
            />
          </div>
        </div>
      )}
    </Section>
  );
}

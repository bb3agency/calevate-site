"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { formatIST } from "@/components/ui";
import type { MaintenanceWindow } from "@/lib/api/maintenance";

import { STATE_COPY, StatePill } from "./windowState";

const COLUMNS: DataColumn<MaintenanceWindow>[] = [
  {
    id: "state",
    header: "State",
    cell: (row) => (
      <div className="flex flex-col items-start gap-1">
        <StatePill tone={STATE_COPY[row.state].tone}>{STATE_COPY[row.state].label}</StatePill>
        {row.forced && <span className="text-meta text-ink-muted">Forced on the deadline</span>}
      </div>
    ),
  },
  {
    id: "when",
    header: "When",
    sort: { value: (row) => row.starts_at, kind: "time", first: "desc" },
    cell: (row) => (
      <span className="whitespace-nowrap tabular-nums text-ink">
        {formatIST(row.starts_at)}
        <span className="text-ink-muted"> → {formatIST(row.ends_at)}</span>
      </span>
    ),
  },
  {
    id: "reason",
    header: "What clients were told",
    // Free operator text on a one-line row: the list is a schedule, not a log, so the
    // whole sentence lives in the title.
    cell: (row) => (
      <span title={row.reason} className="block max-w-[16rem] truncate text-ink-muted sm:max-w-md">
        {row.reason}
      </span>
    ),
  },
];

export function WindowHistory({ history }: { history: MaintenanceWindow[] }) {
  return (
    <section aria-labelledby="maintenance-history" className="space-y-2">
      <h2 id="maintenance-history" className="text-heading text-ink">
        Recent windows
      </h2>
      {history.length === 0 ? (
        <EmptyState
          message="No windows yet. Called-off windows are listed here too."
          className="py-6"
        />
      ) : (
        <DataTable
          rows={history}
          columns={COLUMNS}
          getRowId={(row) => row.id}
          label="Recent maintenance windows"
        />
      )}
    </section>
  );
}

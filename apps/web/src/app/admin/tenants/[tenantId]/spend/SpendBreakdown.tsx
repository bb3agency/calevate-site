"use client";

import { useState } from "react";

import { Section } from "@/components/console/section";
import { formatCount, formatINR, formatIST } from "@/components/ui";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { SegmentedControl } from "@/components/interior/segmented-control";
import type { AgentSpend, CallSpend, TenantSpend, UnitSpend } from "@/lib/api/spend";

type View = "agents" | "calls" | "units";

/** Three peer views of one month's attribution (D-655): who, which calls, which meters. */
export function Breakdown({ data }: { data: TenantSpend }) {
  const [view, setView] = useState<View>("agents");
  return (
    <Section title="Where it went">
      <div className="pb-3">
        <SegmentedControl
          label="Break down by"
          value={view}
          onValueChange={(value) => setView(value as View)}
          options={[
            { value: "agents", label: "By agent", count: String(data.by_agent.length) },
            { value: "calls", label: "Costliest calls", count: String(data.top_calls.length) },
            { value: "units", label: "Our cost by unit", count: String(data.by_unit.length) },
          ]}
        />
      </div>
      <div className="settings-enter" key={view}>
        {view === "agents" && <AgentsTable rows={data.by_agent} />}
        {view === "calls" && (
          <>
            {data.top_calls_truncated && (
              <p className="px-4 pb-2 text-meta text-ink-muted">
                The {formatCount(data.top_calls.length)} that cost us most, of{" "}
                {formatCount(data.calls)}.
              </p>
            )}
            <CallsTable rows={data.top_calls} />
          </>
        )}
        {view === "units" && <UnitsTable rows={data.by_unit} />}
      </div>
    </Section>
  );
}

/** An assumed cost currency, marked on the ROW that carries it (OPERATIONS §2 gate 7). */
function AssumedMark({ assumed }: { assumed: boolean }) {
  if (!assumed) return null;
  return (
    <abbr
      title="At least one cost row here was priced in a currency the vendor's data did not state."
      className="ml-1 cursor-help text-ink-muted no-underline"
    >
      *
    </abbr>
  );
}

function MarginCell({ value }: { value: string }) {
  const negative = value.trim().startsWith("-");
  return (
    <span className={`whitespace-nowrap font-semibold tabular-nums ${negative ? "text-danger" : ""}`}>
      {negative && <span className="sr-only">Losing money: </span>}
      {formatINR(value)}
    </span>
  );
}

const num = "whitespace-nowrap tabular-nums";

function AgentsTable({ rows }: { rows: AgentSpend[] }) {
  if (rows.length === 0) return <EmptyState message="No calls to attribute this month" />;
  const columns: DataColumn<AgentSpend>[] = [
    {
      id: "agent",
      header: "Agent",
      cell: (agent) => agent.agent_name ?? (agent.agent_id ? "Unnamed agent" : "Not attributed to an agent"),
    },
    { id: "calls", header: "Calls", align: "right", hideBelow: "sm", cell: (agent) => <span className={num}>{formatCount(agent.calls)}</span> },
    { id: "minutes", header: "Minutes", align: "right", hideBelow: "md", cell: (agent) => <span className={`${num} text-ink-muted`}>{agent.minutes}</span> },
    { id: "charged", header: "Charged", align: "right", cell: (agent) => <span className={num}>{formatINR(agent.charged_inr)}</span> },
    {
      id: "cost",
      header: "Our cost",
      align: "right",
      hideBelow: "sm",
      cell: (agent) => (
        <span className={`${num} text-ink-muted`}>
          {formatINR(agent.cost_inr)}
          <AssumedMark assumed={agent.cost_currency_assumed} />
        </span>
      ),
    },
    { id: "margin", header: "Margin", align: "right", cell: (agent) => <MarginCell value={agent.margin_inr} /> },
  ];
  return (
    <DataTable
      rows={rows}
      columns={columns}
      getRowId={(agent) => agent.agent_id ?? "unattributed"}
      label="Charge, cost and margin by agent"
    />
  );
}

function CallsTable({ rows }: { rows: CallSpend[] }) {
  if (rows.length === 0) return <EmptyState message="No calls this month" />;
  const columns: DataColumn<CallSpend>[] = [
    { id: "when", header: "When", cell: (call) => <span className="whitespace-nowrap">{formatIST(call.started_at)}</span> },
    { id: "agent", header: "Agent", hideBelow: "md", cell: (call) => <span className="text-ink-muted">{call.agent_name ?? "—"}</span> },
    { id: "direction", header: "Direction", hideBelow: "lg", cell: (call) => <span className="text-ink-muted">{call.direction ?? "—"}</span> },
    { id: "minutes", header: "Minutes", align: "right", hideBelow: "sm", cell: (call) => <span className={`${num} text-ink-muted`}>{call.minutes}</span> },
    { id: "charged", header: "Charged", align: "right", cell: (call) => <span className={num}>{formatINR(call.charged_inr)}</span> },
    {
      id: "cost",
      header: "Our cost",
      align: "right",
      hideBelow: "sm",
      cell: (call) => (
        <span className={`${num} text-ink-muted`}>
          {formatINR(call.cost_inr)}
          <AssumedMark assumed={call.cost_currency_assumed} />
        </span>
      ),
    },
    { id: "margin", header: "Margin", align: "right", cell: (call) => <MarginCell value={call.margin_inr} /> },
  ];
  return <DataTable rows={rows} columns={columns} getRowId={(call) => call.call_id} label="Costliest calls" />;
}

function UnitsTable({ rows }: { rows: UnitSpend[] }) {
  if (rows.length === 0) return <EmptyState message="No metered units this month" />;
  const columns: DataColumn<UnitSpend>[] = [
    { id: "unit", header: "Unit", cell: (unit) => <span className="font-mono text-meta">{unit.unit_type}</span> },
    // `qty` is not money and is not rounded like it: printed as the ledger holds it.
    { id: "qty", header: "Quantity", align: "right", cell: (unit) => <span className={`${num} text-ink-muted`}>{unit.qty}</span> },
    { id: "cost", header: "Our cost", align: "right", cell: (unit) => <span className={`${num} font-semibold`}>{formatINR(unit.cost_inr)}</span> },
  ];
  return <DataTable rows={rows} columns={columns} getRowId={(unit) => unit.unit_type} label="Our cost by metered unit" />;
}

"use client";

import { use, useState } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatIST,
} from "@/components/ui";
import { API_BASE, devSession, type Lead, type LeadStatus } from "@/lib/api/client";
import { useLeads, useUpdateLeadStatus } from "@/lib/api/hooks";

/** Fixed enum (D-21): clients cannot add statuses, because analytics and the hot-lead
 *  rules key off exactly these values. */
const STATUSES: LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

/** Two ways to look at the same leads: the table for scanning detail columns, the
 *  board for working the pipeline stage by stage (parity with what competitors ship). */
type ViewMode = "list" | "board";

export default function LeadsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = devSession(slug);
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  // useLeads already accepts a `status` param and filters server-side, so the chips
  // below drive the query directly — no client-side filtering needed.
  const leads = useLeads(session, { status, search: search || undefined, limit: 100 });
  const updateStatus = useUpdateLeadStatus(session);

  const columns = leads.data?.columns ?? [];
  const items = leads.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Leads</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {leads.data?.total ?? 0} leads · columns follow your agent&apos;s capture list
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name or last digits"
            className="w-52 rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
          {/* View toggle: the list keeps every capture-list column; the board trades
              detail for a stage-by-stage picture of the pipeline. */}
          <div
            role="group"
            aria-label="View"
            className="flex overflow-hidden rounded-md border border-slate-200 text-sm dark:border-slate-700"
          >
            {(["list", "board"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setView(mode)}
                aria-pressed={view === mode}
                className={
                  view === mode
                    ? "bg-slate-900 px-3 py-1.5 font-medium text-white dark:bg-slate-100 dark:text-slate-900"
                    : "bg-white px-3 py-1.5 text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800"
                }
              >
                {mode === "list" ? "List" : "Board"}
              </button>
            ))}
          </div>
          {/* A plain link, not a fetch: the export is a file download and the browser
              handles it better than we would. The API audit-logs the read. */}
          <a
            href={`${API_BASE}/v1/leads/export.csv`}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Export CSV
          </a>
        </div>
      </div>

      {/* Status filter chips replace the old dropdown: one click per status, and the
          active choice stays visible instead of hiding inside a closed select. They
          feed the same server-side `status` param the dropdown did. */}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by status">
        <FilterChip
          label="All"
          active={status === undefined}
          onClick={() => setStatus(undefined)}
        />
        {STATUSES.map((s) => (
          <FilterChip key={s} label={s} active={status === s} onClick={() => setStatus(s)} />
        ))}
      </div>

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {updateStatus.error && <ProblemNotice error={updateStatus.error} />}

      {view === "list" ? (
        <Card>
          {leads.isLoading ? (
            <Skeleton rows={6} />
          ) : items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                    <th className="py-2 pr-3 font-medium">Name</th>
                    <th className="py-2 pr-3 font-medium">Phone</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    {columns.map((column) => (
                      <th key={column.key} className="py-2 pr-3 font-medium">
                        {column.label}
                      </th>
                    ))}
                    <th className="py-2 pr-3 font-medium">Calls</th>
                    <th className="py-2 font-medium">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {items.map((lead) => (
                    <tr key={lead.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      <td className="py-2 pr-3 font-medium text-slate-800 dark:text-slate-200">
                        {lead.name ?? "Unknown"}
                        {lead.is_repeat_caller && (
                          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                            repeat
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-400">
                        {lead.phone_masked}
                      </td>
                      <td className="py-2 pr-3">
                        <StatusSelect
                          value={lead.status}
                          disabled={updateStatus.isPending}
                          onChange={(next) => updateStatus.mutate({ leadId: lead.id, status: next })}
                          className="rounded-md border border-transparent bg-transparent text-xs capitalize hover:border-slate-200 dark:hover:border-slate-700"
                        />
                      </td>
                      {columns.map((column) => (
                        <td key={column.key} className="py-2 pr-3 text-slate-600 dark:text-slate-400">
                          {cellValue(lead, column.key)}
                        </td>
                      ))}
                      <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-400">
                        {lead.call_count}
                      </td>
                      <td className="whitespace-nowrap py-2 text-xs text-slate-500">
                        {formatIST(lead.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No leads yet"
              hint="Every answered call becomes a lead within two minutes."
            />
          )}
        </Card>
      ) : (
        /* Board view: one column per D-21 status. Grouping happens over the loaded
           page — the six columns come from the enum, not from the data, so an empty
           stage still shows (an empty "won" column is information, not a bug). */
        <div className="overflow-x-auto">
          {leads.isLoading ? (
            <Skeleton rows={6} />
          ) : (
            <div className="grid min-w-[960px] grid-cols-6 gap-3">
              {STATUSES.map((s) => {
                const columnLeads = items.filter((l) => l.status === s);
                return (
                  <div
                    key={s}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-900/50"
                  >
                    <div className="flex items-center justify-between px-1 pb-2">
                      <StatusBadge value={s} />
                      <span className="text-xs tabular-nums text-slate-500">
                        {columnLeads.length}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {columnLeads.map((lead) => (
                        <div
                          key={lead.id}
                          className="rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
                        >
                          <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                            {/* The list of leads without a captured name is long; the
                                masked phone is the next-best stable identifier. */}
                            {lead.name ?? lead.phone_masked}
                          </p>
                          <p className="mt-0.5 text-xs text-slate-500">
                            {lead.source} · {formatIST(lead.updated_at)}
                          </p>
                          {/* No drag-and-drop: the same PATCH the table uses, behind a
                              select, works everywhere including on a phone. */}
                          <StatusSelect
                            value={lead.status}
                            disabled={updateStatus.isPending}
                            onChange={(next) =>
                              updateStatus.mutate({ leadId: lead.id, status: next })
                            }
                            className="mt-1.5 w-full rounded-md border border-slate-200 bg-transparent px-1 py-0.5 text-xs capitalize dark:border-slate-700"
                          />
                        </div>
                      ))}
                      {columnLeads.length === 0 && (
                        <p className="px-1 py-3 text-center text-xs text-slate-400">No leads</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-xs text-slate-500">
        {STATUSES.map((s) => (
          <span key={s} className="flex items-center gap-1">
            <StatusBadge value={s} /> {countByStatus(leads.data?.items, s)}
          </span>
        ))}
      </div>
    </div>
  );
}

/** One chip = one server-side status filter value; "All" clears it. */
function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? "rounded-full bg-slate-900 px-3 py-1 text-xs font-medium capitalize text-white dark:bg-slate-100 dark:text-slate-900"
          : "rounded-full border border-slate-200 bg-white px-3 py-1 text-xs capitalize text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800"
      }
    >
      {label}
    </button>
  );
}

/** The one status-change control, shared by table rows and board cards, so both
 *  views go through exactly the same mutation (useUpdateLeadStatus). */
function StatusSelect({
  value,
  disabled,
  onChange,
  className,
}: {
  value: LeadStatus;
  disabled: boolean;
  onChange: (next: LeadStatus) => void;
  className: string;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as LeadStatus)}
      className={className}
    >
      {STATUSES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

function cellValue(lead: Lead, key: string): string {
  const value = (lead.data as Record<string, unknown> | null | undefined)?.[key];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function countByStatus(items: Lead[] | undefined, status: LeadStatus): number {
  return (items ?? []).filter((l) => l.status === status).length;
}

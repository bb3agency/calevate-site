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

export default function LeadsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = devSession(slug);
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const leads = useLeads(session, { status, search: search || undefined, limit: 100 });
  const updateStatus = useUpdateLeadStatus(session);

  const columns = leads.data?.columns ?? [];

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
          <select
            value={status ?? ""}
            onChange={(e) => setStatus(e.target.value || undefined)}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm capitalize dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
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

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {updateStatus.error && <ProblemNotice error={updateStatus.error} />}

      <Card>
        {leads.isLoading ? (
          <Skeleton rows={6} />
        ) : leads.data?.items.length ? (
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
                {leads.data.items.map((lead) => (
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
                      <select
                        value={lead.status}
                        disabled={updateStatus.isPending}
                        onChange={(e) =>
                          updateStatus.mutate({
                            leadId: lead.id,
                            status: e.target.value as LeadStatus,
                          })
                        }
                        className="rounded-md border border-transparent bg-transparent text-xs capitalize hover:border-slate-200 dark:hover:border-slate-700"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
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

function cellValue(lead: Lead, key: string): string {
  const value = (lead.data as Record<string, unknown> | null | undefined)?.[key];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function countByStatus(items: Lead[] | undefined, status: LeadStatus): number {
  return (items ?? []).filter((l) => l.status === status).length;
}

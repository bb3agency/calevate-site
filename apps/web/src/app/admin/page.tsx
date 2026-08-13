"use client";

import Link from "next/link";

import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useTenants } from "@/lib/api/admin";
import { holdRule } from "@/lib/api/holds";
import { VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";

export default function AdminClientsPage() {
  const tenants = useTenants();

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Clients</h1>
          <p className="mt-0.5 text-sm text-slate-400">
            {tenants.data?.length ?? 0} accounts · health at a glance
          </p>
        </div>
        <Link
          href="/admin/new"
          className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-900"
        >
          New client
        </Link>
      </div>

      {tenants.error && <ProblemNotice error={tenants.error} onRetry={() => tenants.refetch()} />}

      <div className="rounded-xl border border-slate-800 bg-slate-900">
        {tenants.isLoading ? (
          <div className="p-4">
            <Skeleton rows={5} />
          </div>
        ) : (
          <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[800px] text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2 font-medium">Client</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Vertical</th>
                <th className="px-4 py-2 font-medium">Live agents</th>
                <th className="px-4 py-2 font-medium">Calls 7d</th>
                <th className="px-4 py-2 font-medium">Leads</th>
                <th className="px-4 py-2 font-medium">Last call</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(tenants.data ?? []).map((tenant) => (
                <tr key={tenant.id} className="hover:bg-slate-800/50">
                  <td className="px-4 py-2">
                    <Link href={`/admin/tenants/${tenant.id}`} className="font-medium hover:underline">
                      {tenant.name}
                    </Link>
                    <div className="text-xs text-slate-500">/c/{tenant.slug}</div>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={
                        tenant.status === "active"
                          ? "rounded-full bg-emerald-950 px-2 py-0.5 text-xs text-emerald-300"
                          : "rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                      }
                    >
                      {tenant.status}
                    </span>
                    {/* A capped tenant's outbound is refused pre-dispatch (TRD §9), so
                        it needs to be visible here rather than discovered in support. */}
                    {tenant.capped && (
                      <span className="ml-1 rounded-full bg-rose-950 px-2 py-0.5 text-xs text-rose-300">
                        capped
                      </span>
                    )}
                    {/* The same two R-11 gates the work list is built from, on the screen
                        an operator already reads. `TenantSummary.holds` comes from
                        `read_tenant_holds` — the blockers themselves — so this flag and
                        the queue cannot disagree about who is stuck. The label is the
                        rule's operator name where we know it and the gate's own name
                        where we do not; either way it links to the queue, which is where
                        the remedy lives. */}
                    {tenant.holds.map((rule) => (
                      <Link
                        key={rule}
                        href="/admin/holds"
                        className="ml-1 rounded-full bg-amber-950 px-2 py-0.5 text-xs text-amber-300 hover:underline"
                        title="Held for a human decision — see the work list"
                      >
                        {holdRule(rule)?.label ?? rule}
                      </Link>
                    ))}
                  </td>
                  <td className="px-4 py-2 text-slate-400">{tenant.vertical_template ?? "—"}</td>
                  <td className="px-4 py-2 tabular-nums">{tenant.live_agents}</td>
                  <td className="px-4 py-2 tabular-nums">{tenant.calls_7d}</td>
                  <td className="px-4 py-2 tabular-nums">{tenant.leads}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">
                    {formatIST(tenant.last_call_at)}
                  </td>
                  <td className="px-4 py-2">
                    {/* The marker tells the client shell to build the impersonating
                        session (admin token + X-Impersonate-Org). See
                        lib/api/session.tsx — it selects a credential, it grants none. */}
                    <Link
                      href={`/c/${tenant.slug}?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`}
                      className="text-xs text-sky-400 hover:underline"
                      title="Read-only view as this client (D-22) — every page view is logged"
                    >
                      View as
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  );
}

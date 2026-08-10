"use client";

import Link from "next/link";
import { use, useState } from "react";

import { EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  useKbDecision,
  useKbPreview,
  useTenantKbQueue,
  useTenants,
} from "@/lib/api/admin";

/**
 * One client: health, the read-only view-as link, and the KB approval queue.
 *
 * The queue is READ through impersonation and DECIDED through the admin surface —
 * that split is D-22 ("no acting-as: mutations still go through admin surfaces"), and
 * it is why the buttons here post to `/v1/admin/tenants/.../kb/...` rather than to the
 * client-realm KB routes the queue was read from.
 */
export default function TenantDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenants = useTenants();
  const tenant = tenants.data?.find((t) => t.id === tenantId);
  const slug = tenant?.slug ?? "";

  const queue = useTenantKbQueue(slug);
  const [selected, setSelected] = useState<string | null>(null);
  const preview = useKbPreview(slug, selected);
  const decide = useKbDecision(tenantId);

  if (tenants.isLoading) return <Skeleton rows={6} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/admin" className="text-sm text-sky-400 hover:underline">
            ← Clients
          </Link>
          <h1 className="mt-1 text-xl font-semibold">{tenant.name}</h1>
          <p className="text-sm text-slate-400">
            /c/{tenant.slug} · {tenant.status} · {tenant.vertical_template ?? "no template"}
          </p>
        </div>
        <Link
          href={`/c/${tenant.slug}`}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm"
          title="Read-only (D-22). Every page view is audit-logged."
        >
          View as client
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Live agents" value={tenant.live_agents} />
        <Stat label="Calls (7d)" value={tenant.calls_7d} />
        <Stat label="Leads" value={tenant.leads} />
        <Stat label="Last call" value={formatIST(tenant.last_call_at)} />
      </div>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => queue.refetch()} />}
      {decide.error && <ProblemNotice error={decide.error} />}

      {/* Same reason as the ops page: local panel styling, not the client-realm Card. */}
      <section className="rounded-xl border border-slate-800 bg-slate-900">
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">Knowledge awaiting approval</h2>
        </header>
        <div className="p-4">
        {queue.isLoading ? (
          <Skeleton rows={3} />
        ) : queue.data?.length ? (
          <ul className="space-y-2">
            {queue.data.map((source) => (
              <li key={source.id} className="rounded-lg border border-slate-800 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-100">
                      {source.name}{" "}
                      <span className="text-xs text-slate-500">v{source.version}</span>
                    </p>
                    <p className="text-xs text-slate-500">
                      {source.chunks} chunks · {source.kind}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setSelected(selected === source.id ? null : source.id)}
                      className="rounded-md border border-slate-700 px-2 py-1 text-xs"
                    >
                      {selected === source.id ? "Hide" : "Preview"}
                    </button>
                    <button
                      type="button"
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate({ sourceId: source.id, decision: "approve" })
                      }
                      className="rounded-md bg-emerald-500 px-2 py-1 text-xs font-medium text-emerald-950 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate({
                          sourceId: source.id,
                          decision: "reject",
                          reason: "Not suitable for the agent",
                        })
                      }
                      className="rounded-md border border-rose-800 px-2 py-1 text-xs text-rose-300 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
                {selected === source.id && (
                  <div className="mt-3 space-y-2">
                    {/* Chunk-by-chunk is how it is reviewed because chunk-by-chunk is
                        how it will be retrieved and read aloud. */}
                    {(preview.data ?? []).map((chunk) => (
                      <div
                        key={chunk.idx}
                        className="rounded-md bg-slate-950 p-2 text-xs text-slate-300"
                      >
                        <span className="mr-2 text-slate-600">#{chunk.idx}</span>
                        {chunk.content}
                        <span className="ml-2 text-slate-600">({chunk.chars} chars)</span>
                      </div>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nothing awaiting approval"
            hint="Approved sources still need publishing before the agent knows them."
          />
        )}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

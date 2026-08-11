"use client";

import Link from "next/link";
import { use, useState } from "react";

import { EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  useKbDecision,
  useKbPreview,
  useMargin,
  useProvisionNumber,
  useRegisterTemplate,
  useSetNumberDltStatus,
  useSetTemplateStatus,
  useTenant,
  useTenantAgents,
  useTenantKbQueue,
  useTenantNumbers,
  useTenantTemplates,
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
  // One request for one client — the list endpoint is N+1 by design (it counts calls
  // and leads per tenant under each tenant's own RLS), so fetching all of it to find
  // one row made a detail page cost the whole directory.
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";

  const queue = useTenantKbQueue(slug);
  // Approved-but-unpublished is its own queue: approving does NOT push to the engine
  // (kb_service.approve_source only moves the status), so without this list the
  // publish endpoint has no caller and the client's Knowledge screen sits on
  // "Approved, not live yet" forever.
  const publishQueue = useTenantKbQueue(slug, "approved");
  // Publishing leaves `status` at 'approved' and flips `is_active`, so the live ones
  // stay in this list — filter them out rather than offer a second Publish button.
  const awaitingPublish = (publishQueue.data ?? []).filter((source) => !source.is_active);
  const [selected, setSelected] = useState<string | null>(null);
  const preview = useKbPreview(slug, selected);
  const decide = useKbDecision(tenantId);

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  // A 403, a 500 or a dropped connection is not "no such client" — saying so sends
  // an operator hunting for a deleted tenant that is sitting right there.
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
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
        <div className="flex gap-2">
          <Link
            href={`/admin/tenants/${tenantId}/invoice`}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm"
          >
            Invoice
          </Link>
          <Link
            href={`/c/${tenant.slug}`}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm"
            title="Read-only (D-22). Every page view is audit-logged."
          >
            View as client
          </Link>
        </div>
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

      {/* Approve moves a source to `approved`; publishing is the separate step that
          pushes it to the engine and makes it the live version (FLOWS §7). Both are
          ours, so both need a button — an approved source with nowhere to press is
          work that silently stops halfway. */}
      {awaitingPublish.length > 0 ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900">
          <header className="border-b border-slate-800 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-100">Approved, awaiting publish</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              The agent does not know these until they are published.
            </p>
          </header>
          <ul className="divide-y divide-slate-800 px-4">
            {awaitingPublish.map((source) => (
              <li key={source.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                <span className="font-medium text-slate-100">{source.name}</span>
                <span className="text-xs text-slate-500">
                  v{source.version} · {source.chunks} chunks
                </span>
                <button
                  type="button"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate({ sourceId: source.id, decision: "publish" })}
                  className="ml-auto rounded-md bg-sky-500 px-2 py-1 text-xs font-medium text-sky-950 disabled:opacity-50"
                >
                  Publish
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <AgentsPanel tenantId={tenantId} slug={slug} />

      <MarginPanel tenantId={tenantId} />

      <CampaignSetup tenantId={tenantId} slug={slug} />
    </div>
  );
}

/** The tenant's agents, each linking to its prompt history — the entry point the
 * rollback screen needs, since a prompt belongs to an agent, not to the tenant. */
function AgentsPanel({ tenantId, slug }: { tenantId: string; slug: string }) {
  const agents = useTenantAgents(slug);
  if (!agents.data?.length) return null;
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900">
      <header className="border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-100">Agents</h2>
      </header>
      <ul className="divide-y divide-slate-800 px-4">
        {agents.data.map((agent) => (
          <li key={agent.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
            <span className="font-medium text-slate-100">{agent.name}</span>
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
              {agent.status}
            </span>
            <span className="text-xs text-slate-500">{agent.direction}</span>
            <Link
              href={`/admin/tenants/${tenantId}/agents/${agent.id}/prompt`}
              className="ml-auto rounded-md border border-slate-700 px-2 py-0.5 text-xs"
            >
              Prompt history
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}


/**
 * Per-client margin (D-12), the number gate G2 turns on.
 *
 * It lives in the ADMIN console and nowhere else: `unit_cost_paid` is our supplier
 * pricing, and a client who can see it is a client negotiating against it. Their own
 * usage panel shows what they used and what it costs them, which is the half that is
 * theirs.
 */
function MarginPanel({ tenantId }: { tenantId: string }) {
  const margin = useMargin(tenantId);
  if (margin.error) return <ProblemNotice error={margin.error} />;
  if (!margin.data) return null;
  const data = margin.data;
  const negative = data.margin_inr.trim().startsWith("-");

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900">
      <header className="border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-100">
          Margin · {data.month}
        </h2>
      </header>
      <div className="grid gap-3 p-4 sm:grid-cols-4">
        <Stat label="Revenue" value={`₹${data.revenue_inr}`} />
        <Stat label="Our cost" value={`₹${data.cost_inr}`} />
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-500">Margin</div>
          <div
            className={
              negative
                ? "mt-1 text-lg font-semibold tabular-nums text-rose-400"
                : "mt-1 text-lg font-semibold tabular-nums text-emerald-400"
            }
          >
            ₹{data.margin_inr}
          </div>
        </div>
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different
            facts, and an operator acts differently on each. */}
        <Stat label="Margin %" value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`} />
        <div className="sm:col-span-4 text-xs text-slate-500">
          {data.minutes_used} minutes across {data.calls} calls. Cost is what we actually
          paid, stamped per usage row at capture time with the fx rate used.
        </div>
      </div>
    </section>
  );
}

/**
 * The two prerequisites every client campaign stalls on (SEC-COMP §3).
 *
 * They live in the ADMIN console because they are our operational work: we buy the
 * number, we file the template with the registrar under the client's PE. A client who
 * could mark their own template "approved" would be launching under a registration
 * that does not exist — so the client realm reads these and never writes them.
 */
function CampaignSetup({ tenantId, slug }: { tenantId: string; slug: string }) {
  const numbers = useTenantNumbers(slug);
  const templates = useTenantTemplates(slug);
  const provision = useProvisionNumber(tenantId);
  const setDlt = useSetNumberDltStatus(tenantId);
  const register = useRegisterTemplate(tenantId);
  const setStatus = useSetTemplateStatus(tenantId);

  const [e164, setE164] = useState("");
  const [series, setSeries] = useState<"140" | "160" | "standard">("160");
  const [classification, setClassification] = useState<
    "promotional" | "transactional" | "service"
  >("service");
  const [body, setBody] = useState("");
  const [dltRef, setDltRef] = useState("");

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900">
      <header className="border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-100">Campaign setup</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Until a number and an approved template exist, every campaign this client
          creates is blocked at launch.
        </p>
      </header>
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Numbers
          </h3>
          {provision.error && <ProblemNotice error={provision.error} />}
          <ul className="space-y-1.5">
            {(numbers.data ?? []).map((number) => (
              <li
                key={number.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 p-2 text-xs"
              >
                <span className="font-mono text-slate-200">{number.e164}</span>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
                  {number.series}
                </span>
                <span className="text-slate-500">{number.dlt_status}</span>
                {number.dlt_status !== "registered" && (
                  <button
                    type="button"
                    disabled={setDlt.isPending}
                    onClick={() =>
                      setDlt.mutate({ numberId: number.id, dltStatus: "registered" })
                    }
                    className="ml-auto rounded-md border border-slate-700 px-2 py-0.5 disabled:opacity-50"
                  >
                    Mark registered
                  </button>
                )}
              </li>
            ))}
            {numbers.data?.length === 0 && (
              <li className="text-xs text-slate-500">No numbers provisioned.</li>
            )}
          </ul>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              provision.mutate({ e164, series }, { onSuccess: () => setE164("") });
            }}
          >
            <input
              required
              value={e164}
              onChange={(ev) => setE164(ev.target.value)}
              placeholder="+918041234567"
              className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs"
            />
            {/* The series is what the launch gate matches against the campaign's
                classification — wrong here is a DLT violation later, not a typo. */}
            <select
              value={series}
              onChange={(ev) => setSeries(ev.target.value as typeof series)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
            >
              <option value="140">140 — promotional</option>
              <option value="160">160 — service</option>
              <option value="standard">standard</option>
            </select>
            <button
              type="submit"
              disabled={provision.isPending || e164.length < 8}
              className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-900 disabled:opacity-50"
            >
              Add
            </button>
          </form>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            DLT voice templates
          </h3>
          {register.error && <ProblemNotice error={register.error} />}
          <ul className="space-y-1.5">
            {(templates.data ?? []).map((template) => (
              <li key={template.id} className="rounded-lg border border-slate-800 p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
                    {template.classification}
                  </span>
                  <span className="text-slate-500">{template.status}</span>
                  {template.status !== "approved" && (
                    <button
                      type="button"
                      disabled={setStatus.isPending}
                      onClick={() =>
                        setStatus.mutate({ templateId: template.id, status: "approved" })
                      }
                      className="ml-auto rounded-md bg-emerald-500 px-2 py-0.5 font-medium text-emerald-950 disabled:opacity-50"
                    >
                      Registrar approved
                    </button>
                  )}
                </div>
                <p className="mt-1 text-slate-400">{template.body}</p>
              </li>
            ))}
            {templates.data?.length === 0 && (
              <li className="text-xs text-slate-500">No templates registered.</li>
            )}
          </ul>
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              register.mutate(
                { classification, body, dlt_ref: dltRef || null },
                { onSuccess: () => { setBody(""); setDltRef(""); } },
              );
            }}
          >
            <div className="flex gap-2">
              <select
                value={classification}
                onChange={(ev) => setClassification(ev.target.value as typeof classification)}
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
              >
                <option value="promotional">promotional</option>
                <option value="service">service</option>
                <option value="transactional">transactional</option>
              </select>
              <input
                value={dltRef}
                onChange={(ev) => setDltRef(ev.target.value)}
                placeholder="registrar template id (optional)"
                className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
              />
            </div>
            <textarea
              required
              minLength={10}
              rows={3}
              value={body}
              onChange={(ev) => setBody(ev.target.value)}
              placeholder="The exact wording registered with the DLT registrar."
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
            />
            <button
              type="submit"
              disabled={register.isPending || body.length < 10}
              className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-900 disabled:opacity-50"
            >
              Register template
            </button>
          </form>
        </div>
      </div>
    </section>
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

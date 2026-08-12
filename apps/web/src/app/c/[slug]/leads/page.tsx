"use client";

import { useEffect, useState } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatIST,
} from "@/components/ui";
import { useAgents, type Agent } from "@/lib/api/agents";
import { type CallLeadResult, type Lead, type LeadStatus } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import {
  useCallLead,
  useExportLeads,
  useLeads,
  useMe,
  useUpdateLeadStatus,
} from "@/lib/api/hooks";

/** Fixed enum (D-21): clients cannot add statuses, because analytics and the hot-lead
 *  rules key off exactly these values. */
const STATUSES: LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

/** Two ways to look at the same leads: the table for scanning detail columns, the
 *  board for working the pipeline stage by stage (parity with what competitors ship). */
type ViewMode = "list" | "board";

/**
 * An agent that can actually place this call. Same test the Agents screen renders as
 * "Live": on the calling system AND switched on — plus able to dial at all, which an
 * inbound-only receptionist is not. Filtering here is what keeps D-21's dispatch button
 * off rows where the API would refuse it.
 */
function canDial(agent: Agent): boolean {
  return agent.published && agent.status === "live" && agent.direction !== "inbound";
}

export default function LeadsPage() {
  const session = useClientSession();
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  // The search box drives the query KEY, so an undebounced value is one request
  // (and one server-side LIKE) per keystroke. A short pause is what "finished
  // typing" looks like; the input itself stays instant.
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  // useLeads already accepts a `status` param and filters server-side, so the chips
  // below drive the query directly — no client-side filtering needed.
  const leads = useLeads(session, { status, search: searchTerm || undefined, limit: 100 });
  const updateStatus = useUpdateLeadStatus(session);
  const exportLeads = useExportLeads(session);

  const me = useMe(session);
  const agents = useAgents(session);
  const callLead = useCallLead(session);
  const [agentId, setAgentId] = useState("");
  /**
   * The dispatch answer, per lead. It has to live here rather than on the mutation:
   * `callLead.data` is one slot, so calling a second lead would move the first row's
   * verdict onto the second — and a compliance refusal moving rows is worse than none.
   */
  const [callResults, setCallResults] = useState<Record<string, CallLeadResult>>({});

  const columns = leads.data?.columns ?? [];
  const items = leads.data?.items ?? [];

  /**
   * D-22 read-only, applied to the controls rather than discovered on click. Now that
   * "View as client" genuinely lands an operator here, `leads:write` (the status
   * select) is a permission the API will refuse for them — the shell's amber banner
   * says why, so the control is disabled rather than left to answer 403.
   */
  const readOnly = Boolean(me.data?.impersonating);

  /**
   * D-21's "dispatch one AI call from the Leads table". `leads:dispatch` is a MUTATING
   * permission: `staff` does not hold it and an impersonating operator (D-22) is refused
   * it, so both cases render no button rather than a 403 waiting to happen.
   */
  const dialers = (agents.data ?? []).filter(canDial);
  const selectedAgentId = agentId || dialers[0]?.id || "";
  const canCall = Boolean(
    me.data &&
      me.data.permissions.includes("leads:dispatch") &&
      !me.data.impersonating &&
      selectedAgentId,
  );

  const dispatch = (leadId: string) =>
    callLead.mutate(
      { leadId, agentId: selectedAgentId },
      // A 200 carrying `status: "blocked"` is the compliance gate answering, not an
      // error — it is recorded against the row like the queued case (same shape the
      // call-detail follow-up card handles).
      { onSuccess: (result) => setCallResults((prev) => ({ ...prev, [leadId]: result })) },
    );

  const callCell = (lead: Lead) =>
    canCall ? (
      <CallControl
        result={callResults[lead.id]}
        pending={callLead.isPending && callLead.variables?.leadId === lead.id}
        onCall={() => dispatch(lead.id)}
      />
    ) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Leads</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {/* No count until there IS one: "0 leads" while the first page loads is a
                statement about the business, and it is the wrong one. */}
            {leads.data ? `${leads.data.total} leads · ` : ""}columns follow your
            agent&apos;s capture list
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            // The API caps `search` at 60 characters and 422s beyond it.
            maxLength={60}
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
          {/* Fetched, not linked: the endpoint authenticates from the session headers,
              which a browser navigation does not send — a plain <a> answers 401. The
              API audit-logs the read either way.

              The label says "all" because the endpoint means it: `/v1/leads/export.csv`
              accepts `agent_id` and nothing else, so the status chips and the search box
              below do NOT narrow the file. Saying so on the button is the difference
              between an export and a surprise. */}
          <button
            type="button"
            disabled={exportLeads.isPending}
            onClick={() => exportLeads.mutate({})}
            title="Downloads every lead in this account, with full phone numbers. Filters on this screen do not apply."
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {exportLeads.isPending ? "Preparing…" : "Export all as CSV"}
          </button>
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

      {/* Said once, plainly, next to the filters it does not obey. Louder while a
          filter IS on, because that is the moment "Export" means something different
          from what the screen shows. */}
      {status || searchTerm ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Heads up: the export ignores this filter. It downloads every lead in the
          account{leads.data ? ` (${leads.data.total})` : ""}, not the{" "}
          {items.length} shown here.
        </p>
      ) : (
        <p className="text-xs text-slate-500">
          The CSV export contains every lead with full phone numbers, and each download
          is recorded.
        </p>
      )}

      {/* Which agent dials decides the script, the voice and the disclosure line, so
          the choice is on screen whenever there is one — same reasoning as the campaign
          form. No picker and no buttons when nothing here can dial. */}
      {canCall && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>Calls from this table are placed by</span>
          {dialers.length > 1 ? (
            <select
              value={selectedAgentId}
              onChange={(e) => setAgentId(e.target.value)}
              aria-label="Agent that places calls from this table"
              className="rounded-md border border-slate-200 bg-transparent px-2 py-1 text-xs dark:border-slate-700"
            >
              {dialers.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          ) : (
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {dialers[0]?.name}
            </span>
          )}
          <span>
            · every call still goes through the do-not-call, calling-hours and consent
            checks, and can be refused.
          </span>
        </div>
      )}

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {updateStatus.error && <ProblemNotice error={updateStatus.error} />}
      {exportLeads.error && <ProblemNotice error={exportLeads.error} />}
      {/* A refusal by the gate comes back 200 and is rendered on the row; this is for
          the real failures (network, 403, a lead with no dialable number). */}
      {callLead.error != null && <ProblemNotice error={callLead.error} />}

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
                    <th className="py-2 pr-3 font-medium">Updated</th>
                    {canCall && <th className="py-2 font-medium">Call</th>}
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
                          disabled={updateStatus.isPending || readOnly}
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
                      <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">
                        {formatIST(lead.updated_at)}
                      </td>
                      {canCall && <td className="py-2">{callCell(lead)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : leads.error ? null : (
            /* Never "No leads yet" on a failed fetch: the notice above already says
               we could not read them, and this line would contradict it. */
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
                            disabled={updateStatus.isPending || readOnly}
                            onChange={(next) =>
                              updateStatus.mutate({ leadId: lead.id, status: next })
                            }
                            className="mt-1.5 w-full rounded-md border border-slate-200 bg-transparent px-1 py-0.5 text-xs capitalize dark:border-slate-700"
                          />
                          {/* Same control as the table: the board is where someone
                              works the pipeline, so leaving dispatch out of it would
                              make the feature reachable only from the other tab. */}
                          {canCall && <div className="mt-1.5">{callCell(lead)}</div>}
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

      {/* The tally counts the rows ON SCREEN, and says so. The list is capped at 100
          and the chips filter server-side, so an unlabelled row of badges would tell
          a client with a status filter on that they have zero leads in every other
          status — a statement about our query, read as a statement about their
          business. */}
      {leads.data && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>
            Showing {items.length} of {leads.data.total}
            {status ? ` ${status}` : ""} {leads.data.total === 1 ? "lead" : "leads"}:
          </span>
          {STATUSES.map((s) => (
            <span key={s} className="flex items-center gap-1">
              <StatusBadge value={s} /> {countByStatus(items, s)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * D-21 dispatch, per lead — the one control shared by the table and the board.
 *
 * The shape it has to respect: `POST /v1/leads/{id}/call` answers **200** with
 * `status: "blocked"` when the compliance gate refuses, because a refusal is a decision
 * this screen should explain, not an exception to swallow. Falling through to the
 * enabled button on that answer would look like the click did nothing, and the client
 * would press it again — so a blocked row shows the reason and offers no second attempt
 * (the server has already recorded its answer for this lead).
 */
function CallControl({
  result,
  pending,
  onCall,
}: {
  result: CallLeadResult | undefined;
  pending: boolean;
  onCall: () => void;
}) {
  if (result?.status === "queued") {
    return (
      <span className="whitespace-nowrap text-xs font-medium text-emerald-700 dark:text-emerald-400">
        Calling now
      </span>
    );
  }
  if (result?.status === "blocked") {
    return (
      <span className="text-xs text-amber-700 dark:text-amber-400">
        {result.blocked_reason ?? "This call was not allowed."}
        {result.blocked_rule ? ` (${result.blocked_rule})` : ""}
      </span>
    );
  }
  return (
    <button
      type="button"
      disabled={pending}
      onClick={onCall}
      className="whitespace-nowrap rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
    >
      {pending ? "Calling…" : "Call with AI"}
    </button>
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

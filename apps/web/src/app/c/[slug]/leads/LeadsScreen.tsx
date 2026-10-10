"use client";

import { useEffect, useState } from "react";

import { ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { useActAccess, useCallLead, useMe, useWriteAccess } from "@/lib/api/hooks";
import {
  useBulkLeads,
  useExportLeads,
  useLeadFacets,
  useLeadRowEdit,
  useLeadsUnderLens,
  useMembers,
  useSavedViews,
  type LeadBulkResult,
  type LeadColumn,
  type LeadStatus,
} from "@/lib/api/leads";
import { useLeadFields } from "@/lib/api/leadFields";
import { lookup } from "@/lib/lookup";
import { examplesFor } from "@/lib/verticalExamples";

import { BulkActionBar, EMPTY_SELECTION, type BulkSelection } from "./BulkActionBar";
import { DialerPicker } from "./DialerPicker";
import { LeadTable } from "./LeadTable";
import { LeadsFooter } from "./LeadsFooter";
import { LeadsToolbar } from "./LeadsToolbar";
import { MoreFilters } from "./MoreFilters";
import { STATUSES } from "./StatusSelect";
import { narrowedBeyondStatus } from "./leadFilters";
import { PAGE_SIZE, exportRefusal, scopeLabel } from "./leadsTable";
import { useLeadRowKit } from "./useLeadRowKit";
import { useLeadsCopilotSurface } from "./leadsCopilotSurface";
import { useLeadsLens } from "./useLeadsLens";

/**
 * The CRM table — every lead an agent captured, and the one place a client works them.
 *
 * PRIMARY JOB (UX-DOCTRINE §10): *work the queue* — find a lead, move its stage, ring it.
 *
 * Above the rows there is ONE toolbar (search, the question box, columns, export), the
 * stage chips with their counts, and a closed "More filters" holding what is used now and
 * then (owner, captured-answer filters, saved views). The table starts on five columns —
 * who, what they want, what is next, the last call and the stage — and the business's own
 * fields wait in the column chooser. On a phone the table scrolls sideways inside its own
 * region with the Name column pinned, and the page itself never does (founder, 10 Oct 2026).
 *
 * Two properties belong to the SCREEN rather than to the components below:
 *
 * - **A changed lens or page clears the selection.** The server deliberately does not
 *   re-apply the filter to an id-scoped bulk action (`crm.service.resolve_bulk_targets`),
 *   so a set of ticks must not outlive the filter it was made under.
 * - **Editing and selecting are gated on the same `leads:write` the API asks for**, so a
 *   control is disabled with its reason rather than clicking into a 403.
 *
 * Numbers render in full (D-436), never in a URL: search is a POST body (`LeadLensIn`).
 * The CSV export stays behind `calls:read_raw` with an audit row, because taking the whole
 * list is a different act from reading one row.
 */
export function LeadsScreen() {
  // `href` carries the D-22 operator marker forward on the links to each lead.
  const { session, href } = useClientRealm();
  /** Which captured field is "what they want". A failed read falls back to the core key. */
  const leadFields = useLeadFields(session);
  const needKey = leadFields.data?.need_key ?? "need";
  const f = useLeadsLens(needKey);
  const { lens } = f;

  const leads = useLeadsUnderLens(session, lens, { limit: PAGE_SIZE, offset: f.offset || undefined });
  const facets = useLeadFacets(session, lens);
  const savedViews = useSavedViews(session);
  const exportLeads = useExportLeads(session);
  const members = useMembers(session);
  /** One mutation for every inline edit, with each failure kept against its lead. */
  const rows = useLeadRowEdit(session);
  const bulk = useBulkLeads(session);
  const mayEditLead = useWriteAccess(session, "leads:write", "edit a lead");
  const mayDispatch = useWriteAccess(session, "leads:dispatch", "call a lead from this table");
  const me = useMe(session);
  /**
   * Saving a view asks TWO questions since D-587: `leads:write` is writable in a view-as
   * session, but the server refuses the act `leads.saved_view` there — a saved view is
   * owned by a `users.id`, which a view-as session does not have.
   */
  const mayApplyView = useActAccess(session, "leads:write", "leads.saved_view", "save a view");
  const exportAccess = useWriteAccess(session, "calls:read_raw", "export leads");
  const mayExport = exportAccess.allowed;
  /** Derived once and shown twice (UX-DOCTRINE §4): on the button and on the screen. */
  const exportRefused = exportRefusal(f.askTerm, mayExport, exportAccess.reason);
  const agents = useAgents(session);
  const callLead = useCallLead(session);
  const [agentId, setAgentId] = useState("");

  /** `ids` (rows ticked on this page) or `wholeQuery` (every lead the filters match). */
  const [selection, setSelection] = useState<BulkSelection>(EMPTY_SELECTION);
  /** The batch's answer, kept until dismissed so a partial failure cannot scroll away. */
  const [bulkResult, setBulkResult] = useState<LeadBulkResult | null>(null);
  useEffect(() => {
    setSelection(EMPTY_SELECTION);
    setBulkResult(null);
  }, [f.currentLens]);

  /** The SERVER's resolved columns — what the CSV header is built from — not our request. */
  const columns: LeadColumn[] = leads.data?.columns ?? [];
  const items = leads.data?.items ?? [];

  /**
   * How many leads sit in each stage, from the server, over the search and the other
   * filters but NOT the stage itself — which is what a count beside a stage filter has
   * to mean. Read through `lookup`, so a stage the response omits shows "—" rather than
   * a confident zero.
   */
  const stageCounts: Record<string, number> = leads.data?.status_counts_matching_search ?? {};
  const stageCount = (s: LeadStatus): number | undefined => lookup(stageCounts, s);
  /** The export takes the same lens as the table, so the file holds `total` leads. */
  const exportTotal = leads.data?.total ?? null;
  /** False only for a member without `leads:write`; fails closed with a sentence. */
  const readOnly = !mayEditLead.allowed;
  /** "Assigned to me" needs the server's own id for this person; no id, no chip. */
  const myUserId = me.data?.user_id ?? undefined;

  /* `canDialOut` is the ONE definition of "this agent can place a call"
     (src/lib/agentState.ts), shared with the agents screen and the campaign picker. */
  const dialers = agents.data?.filter(canDialOut);
  const selectedAgentId = agentId || dialers?.[0]?.id || "";
  const canCall = mayDispatch.allowed && selectedAgentId !== "";

  /**
   * A read that did not answer is said out loud — otherwise the Call column, the agent
   * picker and "Assigned to me" vanish exactly as they would for an account without the
   * feature. A KNOWN refusal (staff without `leads:dispatch`) is not this, and gets no
   * sentence: "you cannot" and "we could not find out" are different answers.
   */
  const unavailable =
    agents.error != null
      ? "We could not read your agents just now, so no call can be placed from this table. Reload the page to try again."
      : me.error != null
        ? "We could not check who you are signed in as, so calls from this table and the “Assigned to me” filter are closed. Reload the page to try again."
        : null;

  useLeadsCopilotSurface({
    status: f.status,
    setStatus: f.setStatus,
    search: f.search,
    leads,
    items,
    offset: f.offset,
    exportTotal,
    stageCount,
    columns,
    facetValues: f.facetValues,
    assignedTo: f.assignedTo,
    selection,
    readOnly,
    activeViewId: f.activeViewId,
  });

  const kit = useLeadRowKit({
    session,
    href,
    items,
    columns,
    rows,
    mayEditLead,
    members,
    readOnly,
    canCall,
    callLead,
    selectedAgentId,
    selection,
    setSelection,
    filtered: f.filtered,
    askTerm: f.askTerm,
    onClearFilters: f.clearFilters,
    stageCount,
  });

  const nameFor = (leadId: string) => {
    const lead = items.find((row) => row.id === leadId);
    return lead ? (lead.name ?? lead.phone_e164) : null;
  };

  const exportNote =
    exportTotal === null
      ? "The CSV export contains the leads shown here: name and full phone number first, then the columns shown here. Each download is recorded."
      : `The CSV export contains ${
          exportTotal === 1 ? "this 1 lead" : `these ${formatCount(exportTotal)} leads`
}: name and full phone number first, then the columns shown here. Each download is recorded.`;

  /** How many of the "More filters" are narrowing the rows, for its closed state. */
  const moreInUse =
    (f.assignedTo ? 1 : 0) + Object.values(f.facetValues).filter((values) => values.length > 0).length;

  return (
    <div className="space-y-4 pb-12">
      <LeadsToolbar
        askExample={examplesFor(me.data?.organization?.vertical_template).leadSearch}
        search={f.search}
        onSearch={f.setSearch}
        ask={f.ask}
        onAsk={(value) => {
          f.setAsk(value);
          if (value === "") f.setAskTerm("");
        }}
        askTerm={f.askTerm}
        onAskSubmit={() => {
          f.setAskTerm(f.ask.trim());
          f.setOffset(0);
        }}
        leads={leads}
        // What the table is SHOWING: the server's resolved list once it has answered, so a
        // column the server dropped is not shown ticked.
        chosenColumns={leads.data?.columns.map((c) => c.key) ?? lens.columns}
        onColumns={f.setChosenColumns}
        lens={lens}
        exportLeads={exportLeads}
        mayExport={mayExport}
        exportRefusal={exportRefused}
        exportNote={exportNote}
        onExported={() => undefined}
      />

      <RestrictionNote reason={exportRefused} />

      {/* STAGE, with the server's count for each beside it — the one filter a client
          uses most, and the stage tally in the same place. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedControl
          label="Filter by status"
          value={f.status ?? ""}
          onValueChange={(next) => f.setStatus(next === "" ? undefined : next)}
          options={[
            { value: "", label: "All" },
            ...STATUSES.map((s) => ({
              value: s,
              label: s.charAt(0).toUpperCase() + s.slice(1),
              count: leads.data ? formatCount(stageCount(s)) : undefined,
            })),
          ]}
          className="min-w-0"
        />
        <div className="flex flex-wrap items-center gap-3">
          <AskAssistant
            prompt={
              selection.wholeQuery || selection.ids.length > 0
                ? "Summarise the leads I've ticked and tell me who to call first."
                : "Summarise the leads on this screen and tell me who to call first."
            }
          />
          {/* No count until there IS one: "0 leads" while loading is a statement about the
              business, and the wrong one. */}
          {leads.data && (
            <p className="flex items-center gap-1 text-meta text-ink-muted">
              <span className="font-semibold tabular-nums text-ink">{formatCount(leads.data.total)}</span>{" "}
              {scopeLabel(lens, leads.data.total)}
              <InfoTip label="these counts" align="end">
                <p>
                  {narrowedBeyondStatus(lens)
                    ? "Matching these filters, by stage: the figures beside each stage count only the leads your other filters match."
                    : "In this account, by stage: the figures beside each stage count every lead in the account."}
                </p>
                <p>Columns match what your agent captures on each call.</p>
              </InfoTip>
            </p>
          )}
        </div>
      </div>

      <MoreFilters
        inUse={moreInUse}
        myUserId={myUserId}
        assignedToMe={f.assignedTo !== undefined}
        onAssignedToMe={(on) => f.setAssignedTo(on ? myUserId : undefined)}
        impersonating={me.data?.impersonating}
        facets={facets}
        facetValues={f.facetValues}
        onFacetValues={f.setFacetValues}
        views={savedViews}
        activeViewId={f.activeViewId}
        canSaveView={mayApplyView.allowed}
        saveViewReason={mayApplyView.reason}
        onApplyView={(view) => {
          f.setActiveViewId(view?.id);
          f.setStatus(view?.filters.status ?? undefined);
          f.setFacetValues(view?.filters.fields ?? {});
          f.setChosenColumns(view?.columns ?? undefined);
          // The owner filter is a BOOLEAN on the server, resolved fresh against whoever
          // is signed in — a stored id would dangle the day that colleague leaves.
          f.setAssignedTo(view?.filters.assigned_to_me ? myUserId : undefined);
        }}
        currentView={{
          filters: {
            status: f.status ?? null,
            assigned_to_me: Boolean(f.assignedTo),
            fields: f.facetValues,
          },
          columns: f.chosenColumns ?? null,
        }}
      />

      {/* WHAT THE ROWS ARE when a question is in force: a ranked table looks exactly like
          a filtered one. `semantic_truncated` is the server's own "is this all of them". */}
      {f.askTerm && leads.data && (
        <p className="max-w-prose text-meta text-ink-muted">
          Ranked by how closely each lead&rsquo;s captured answers match{" "}
          <span className="font-medium text-ink">&ldquo;{f.askTerm}&rdquo;</span>.
          {leads.data.semantic_truncated
            ? " There may be more matches than were ranked — ask a narrower question."
            : ""}{" "}
          Names, phone numbers and dates are not searched this way — use the search box and the
          filters for those.
        </p>
      )}

      <RestrictionNote reason={mayEditLead.reason} />

      <BulkActionBar
        selection={selection}
        // `undefined` while unknown: the confirmation states how many rows it changes,
        // and a manufactured 0 there is the one number nobody would question (§52).
        filteredTotal={leads.data?.total}
        pageSize={items.length}
        members={members.data}
        canWrite={mayEditLead.allowed}
        writeReason={mayEditLead.reason}
        pending={bulk.isPending}
        error={bulk.error}
        result={bulkResult}
        nameFor={nameFor}
        onSelectWholeQuery={() => setSelection({ ids: [], wholeQuery: true })}
        onClear={() => setSelection(EMPTY_SELECTION)}
        onDismissResult={() => setBulkResult(null)}
        onRun={(body) =>
          bulk.mutate(
            { lens, body },
            {
              onSuccess: (result) => {
                setBulkResult(result);
                // The selection is spent; leaving it ticked invites a second run.
                setSelection(EMPTY_SELECTION);
              },
            },
          )
        }
      />

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {exportLeads.error && <ProblemNotice error={exportLeads.error} />}
      {/* The team list failing leaves the rows fine and only the owner picker dead. */}
      {members.error != null && <ProblemNotice error={members.error} />}
      {/* Inline-edit failures are on their own row; a gate refusal (200) is on the row
          too. This is for real failures of a dispatch. */}
      {callLead.error != null && <ProblemNotice error={callLead.error} />}

      {/* Loading and failure are one answer for both views. `leads.data` can survive a
          failed REFETCH and those rows are real, so the guard is on data, not on error. */}
      {leads.isLoading ? (
        <div className="border-y border-line py-4">
          <Skeleton rows={6} label="Loading your leads" />
        </div>
      ) : !leads.data ? null : (
        <LeadTable
          kit={kit}
          partialNote={
            leads.data.total > items.length
              ? `Sorted within the ${formatCount(items.length)} leads on this page, not all ${formatCount(leads.data.total)}.`
              : undefined
          }
        />
      )}

      {/* Which agent rings a lead from this table, and the checks every such call passes.
          Under the rows it qualifies rather than above them, and never folded away. */}
      <DialerPicker
        unavailable={unavailable}
        canCall={canCall}
        dialers={dialers}
        selectedAgentId={selectedAgentId}
        onSelect={setAgentId}
      />

      <LeadsFooter
        leads={leads}
        items={items}
        offset={f.offset}
        lens={lens}
        onOffsetChange={f.setOffset}
      />
    </div>
  );
}

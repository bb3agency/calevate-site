"use client";

import { useEffect, useState } from "react";

import { Card, FilterChip, ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { useToast } from "@/components/interior/toaster";
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
import { lookup } from "@/lib/lookup";

import { BulkActionBar, EMPTY_SELECTION, type BulkSelection } from "./BulkActionBar";
import { DialerPicker } from "./DialerPicker";
import { FacetPanel } from "./FacetPanel";
import { LeadBoard } from "./LeadBoard";
import { LeadTable } from "./LeadTable";
import { LeadsFooter } from "./LeadsFooter";
import { LeadsToolbar } from "./LeadsToolbar";
import { SavedViewBar } from "./SavedViewBar";
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
  const { toast } = useToast();
  const f = useLeadsLens();
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
    view: f.view,
    setView: f.setView,
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
      ? "The CSV export contains the leads and columns shown here, with full phone numbers, and each download is recorded."
      : `The CSV export contains ${
          exportTotal === 1 ? "this 1 lead" : `these ${formatCount(exportTotal)} leads`
        } and the columns shown here, with full phone numbers. Each download is recorded.`;

  return (
    <div className="space-y-4 pb-12">
      <LeadsToolbar
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
        view={f.view}
        onView={f.setView}
        leads={leads}
        chosenColumns={f.chosenColumns}
        onColumns={f.setChosenColumns}
        lens={lens}
        exportLeads={exportLeads}
        mayExport={mayExport}
        exportRefusal={exportRefused}
        exportNote={exportNote}
        onExported={() =>
          toast({ tone: "success", title: "Export ready", description: "Your leads CSV has downloaded." })
        }
      />

      <RestrictionNote reason={exportRefused} />

      {/* STAGE, with the server's count for each beside it — the one filter a client
          uses most, and the stage tally in the same place. A second axis (owner) sits
          beside it as its own control. */}
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
        <div className="flex flex-wrap items-center gap-2">
          {myUserId && (
            <div role="group" aria-label="Filter by owner">
              <FilterChip
                label="Assigned to me"
                active={f.assignedTo !== undefined}
                onClick={() => f.setAssignedTo(f.assignedTo ? undefined : myUserId)}
              />
            </div>
          )}
          {/* No count until there IS one: "0 leads" while loading is a statement about the
              business, and the wrong one. */}
          {leads.data && (
            <p className="flex items-center gap-1 text-[13px] text-ink-muted">
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

      {/* An operator is a real person with a real id, so the chip works; it simply cannot
          match, because leads are owned by the client's own team. */}
      {myUserId && me.data?.impersonating && (
        <p className="text-xs text-ink-muted">
          You are viewing this account as Calevate operations, so no lead here is assigned to you.
        </p>
      )}

      {/* WHAT THE ROWS ARE when a question is in force: a ranked table looks exactly like
          a filtered one. `semantic_truncated` is the server's own "is this all of them". */}
      {f.askTerm && leads.data && (
        <p className="text-xs text-ink-muted">
          Ranked by how closely each lead&rsquo;s captured answers match{" "}
          <span className="font-medium text-ink">&ldquo;{f.askTerm}&rdquo;</span>.
          {leads.data.semantic_truncated
            ? " There may be more matches than were ranked — ask a narrower question."
            : ""}{" "}
          Names, phone numbers and dates are not searched this way — use the search box and the
          filters for those.
        </p>
      )}

      <FacetPanel
        facets={facets.data}
        loading={facets.isLoading}
        error={facets.error}
        selected={f.facetValues}
        onChange={f.setFacetValues}
        onRetry={() => facets.refetch()}
      />

      <SavedViewBar
        views={savedViews.data}
        error={savedViews.error}
        activeViewId={f.activeViewId}
        canWrite={mayApplyView.allowed}
        writeReason={mayApplyView.reason}
        onApply={(view) => {
          f.setActiveViewId(view?.id);
          f.setStatus(view?.filters.status ?? undefined);
          f.setFacetValues(view?.filters.fields ?? {});
          f.setChosenColumns(view?.columns ?? undefined);
          // The owner filter is a BOOLEAN on the server, resolved fresh against whoever
          // is signed in — a stored id would dangle the day that colleague leaves.
          f.setAssignedTo(view?.filters.assigned_to_me ? myUserId : undefined);
        }}
        currentBody={{
          filters: {
            status: f.status ?? null,
            assigned_to_me: Boolean(f.assignedTo),
            fields: f.facetValues,
          },
          columns: f.chosenColumns ?? null,
        }}
      />

      <DialerPicker
        unavailable={unavailable}
        canCall={canCall}
        dialers={dialers}
        selectedAgentId={selectedAgentId}
        onSelect={setAgentId}
      />

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
        <Card bodyClassName="p-4">
          <Skeleton rows={6} />
        </Card>
      ) : !leads.data ? null : f.view === "list" ? (
        <LeadTable
          kit={kit}
          partialNote={
            leads.data.total > items.length
              ? `Sorted within the ${formatCount(items.length)} leads on this page, not all ${formatCount(leads.data.total)}.`
              : undefined
          }
        />
      ) : (
        <LeadBoard kit={kit} />
      )}

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

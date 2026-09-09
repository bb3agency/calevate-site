"use client";

import { useEffect, useState } from "react";

import {
  Card,
  FilterChip,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { useToast } from "@/components/interior/toaster";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { useCallLead, useMe, useWriteAccess } from "@/lib/api/hooks";
import {
  useBulkLeads,
  useExportLeads,
  useLeadFacets,
  useLeadRowEdit,
  useLeadsUnderLens,
  useMembers,
  useSavedViews,
  lensKey,
  type LeadBulkResult,
  type LeadColumn,
  type LeadLens,
  type LeadStatus,
} from "@/lib/api/leads";
import { lookup } from "@/lib/lookup";

import { BulkActionBar, EMPTY_SELECTION, type BulkSelection } from "./BulkActionBar";
import { FacetPanel } from "./FacetPanel";
import { LeadBoard } from "./LeadBoard";
import { LeadTable } from "./LeadTable";
import { LeadsFooter } from "./LeadsFooter";
import { LeadsToolbar } from "./LeadsToolbar";
import { SavedViewBar } from "./SavedViewBar";
import { STATUSES } from "./StatusSelect";
import { PAGE_SIZE, scopeLabel, type ViewMode } from "./leadsTable";
import { useLeadRowKit } from "./useLeadRowKit";
import { useLeadsCopilotSurface } from "./leadsCopilotSurface";

/**
 * The CRM table — every lead an agent captured, and the one place a client works them.
 *
 * PRIMARY JOB (UX-DOCTRINE §10): *work the queue* — find a lead, move its stage, ring it.
 *
 * Two properties of the screen live HERE rather than in the components below, because
 * they are properties of the SCREEN:
 *
 * - **The selection is cleared whenever the lens moves.** A tick means "this row", and a
 *   set of ticks agreed to under one filter must not survive into another — the server
 *   deliberately does NOT re-apply the filter to an id-scoped action
 *   (`crm.service.resolve_bulk_targets`), so this is the half of that contract the screen
 *   owns.
 * - **Editing and selecting are gated on the same `leads:write` the API asks for**, which
 *   an impersonating operator is refused (D-22) — so the controls are absent or disabled
 *   with the reason, rather than clicking into a 403.
 *
 * Numbers render IN FULL (D-436): a lead nobody can ring is not a lead, and this table
 * is where a receptionist works the queue. Two things about that are unchanged and are
 * not rendering choices — a number never goes into a URL (search is a POST body, which
 * is why `LeadLensIn` exists), and the CSV export stays behind `calls:read_raw` with an
 * audit row, because taking the whole list is a different act from reading one row. The
 * export button says out loud what it downloads.
 *
 * ## What left this file, and why
 *
 * At 1,466 lines this was one module holding five subjects — UX-DOCTRINE §6's "a big file
 * is a hierarchy nobody could see". The row-drawing views are now `LeadTable.tsx` and
 * `LeadBoard.tsx` (they share `leadRowKit.ts`, because they draw the same row), the strip
 * above them is `LeadsToolbar.tsx`, the tally and pager are `LeadsFooter.tsx`, the
 * dispatch control is `CallControl.tsx`, and the arithmetic is the React-free
 * `leadsTable.ts`. What stayed is the state, the reads, the §52 refusals they earn, and
 * the ONE copilot surface a screen may declare.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Leads" beside it is a visible duplicate.
 */
export function LeadsScreen() {
  // `href` (not just the session) because the name cell now links to the lead's own
  // screen, and an in-realm link must carry the D-22 operator marker forward or the
  // next page silently falls back to a client token it does not have.
  const { session, href } = useClientRealm();
  // Transient success cue for the CSV export, which otherwise gives the client no
  // on-screen confirmation at all — the file simply starts downloading. Additive: the
  // gating, the audited request and the download in `useExportLeads` are unchanged, and
  // `useToast` is a no-op wherever no `ToastProvider` is mounted.
  const { toast } = useToast();
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  /**
   * THE SEMANTIC QUESTION (D-504) — "leads who asked about a 3BHK in Gachibowli".
   *
   * A second box beside the search box rather than a mode on it, for the reason
   * `LeadLens.ask` gives: the two match different things and a person must be able to use
   * both at once. It is submitted rather than debounced, and that is the difference that
   * matters — every keystroke of `search` costs a `LIKE`, but every submission of this
   * costs an EMBEDDING against the account's AI ceiling, so it fires when a person says
   * so and never while they are still typing.
   */
  const [ask, setAsk] = useState("");
  const [askTerm, setAskTerm] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  /** "Assigned to me" — a member id sent to the SERVER, never a slice of the page. */
  const [assignedTo, setAssignedTo] = useState<string | undefined>();
  // The search box drives the query KEY, so an undebounced value is one request
  // (and one server-side LIKE) per keystroke. A short pause is what "finished
  // typing" looks like; the input itself stays instant.
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  /**
   * The FACET selection: extraction-schema key → chosen values. Server-side, like every
   * other filter here — the panel's counts and the rows and the CSV all come from the
   * same three query parameters, so none of them can be a slice of the loaded page.
   */
  const [facetValues, setFacetValues] = useState<Record<string, string[]>>({});
  /**
   * The COLUMN selection. `undefined` means "the client has chosen nothing", which the
   * API renders as every column this agent has — deliberately not the same as choosing
   * all of them today, because that would freeze them out of a column added tomorrow.
   */
  const [chosenColumns, setChosenColumns] = useState<string[] | undefined>();
  /** Which saved view, if any, is currently applied — for the "Update this view" path. */
  const [activeViewId, setActiveViewId] = useState<string | undefined>();

  /**
   * ONE object describing which rows and which columns, shared by the table, the facet
   * counts and the CSV export. That sharing is the slice's whole correctness claim: the
   * file cannot disagree with the screen about the filters if there is one place that
   * spells them (`lib/api/leads.ts::lensQuery`).
   */
  const lens: LeadLens = {
    status,
    search: searchTerm || undefined,
    ask: askTerm || undefined,
    assigned_to: assignedTo,
    fields: facetValues,
    columns: chosenColumns,
  };

  // WHICH page of the lens. Row 101 used to be unreachable through the UI — the footer
  // printed an honest "Showing 100 of 1,240" and then stopped, leaving the majority of
  // an established account's CRM permanently invisible (ux-audit L1, its top blocker).
  // The server side always took {limit, offset}; this is the missing control.
  const [offset, setOffset] = useState(0);

  // Every filter on this screen is a SERVER-side filter — the chips, the search box, the
  // owner and the facets. The page is capped at 100 rows, so a filter applied here would
  // be a filter over whatever happened to load (BUILD-LOG §52 counts four defects of
  // exactly that shape, including the stage tally on this very screen).
  const leads = useLeadsUnderLens(session, lens, {
    limit: PAGE_SIZE,
    offset: offset || undefined,
  });
  const facets = useLeadFacets(session, lens);
  const savedViews = useSavedViews(session);
  const exportLeads = useExportLeads(session);
  const members = useMembers(session);
  /**
   * ONE mutation for every inline edit on a row — status, owner and name — with the
   * failure kept against the LEAD it happened to. It replaced `useUpdateLeadStatus` and
   * `useAssignLead`, which were two hooks on one route with two error channels, so a row
   * could only ever surface one of them.
   */
  const rows = useLeadRowEdit(session);
  const bulk = useBulkLeads(session);
  /**
   * May this session change an owner? The server's own answer to `/v1/me`, run through
   * the same helper every other gated control on this console uses: it folds the
   * permission and D-22 impersonation into one `{allowed, reason}` so the select is
   * disabled WITH the sentence rather than clicking into a 403.
   */
  const mayEditLead = useWriteAccess(session, "leads:write", "edit a lead");
  /**
   * D-21's dispatch permission, through the same helper rather than re-derived from
   * `/v1/me` inline. `useWriteAccess` folds the permission, D-22 impersonation AND the
   * failed-read case into one `{allowed, reason}`; the inline version this replaced had
   * no answer for the third and read a dead `/v1/me` as a refusal.
   */
  const mayDispatch = useWriteAccess(session, "leads:dispatch", "call a lead from this table");

  const me = useMe(session);
  /**
   * May this session take the CSV out? — through the same helper every other gated
   * control here uses, rather than reading the permission list inline.
   *
   * It used to be `me.data?.permissions?.includes("calls:read_raw") ?? false`, and that
   * `?? false` is BUILD-LOG §52's defect in its original costume: `me.data` is undefined
   * while `/v1/me` is in flight AND after it has failed, so a request that never landed
   * disabled the button under the sentence "Exporting full phone numbers is limited to
   * the account owner." An owner who holds the permission was told they do not — a
   * refusal manufactured from our own ignorance, which is the one thing a failed read
   * must never produce. `useWriteAccess` distinguishes the two: it answers "We could not
   * check whether you can …" on `me.error`, and stays quiet (reason `null`) while the
   * answer is still coming. tests/surfaceStatesGuard.test.ts keeps this shape out.
   */
  /**
   * May this session SAVE a view? `leads:write`, which the API asks for — and which an
   * impersonating operator is refused (D-22), so the Save control is disabled with the
   * sentence rather than clicking into a 403. Reading views needs no such check: an
   * operator simply has none.
   */
  const mayApplyView = useWriteAccess(session, "leads:write", "save a view");
  const exportAccess = useWriteAccess(session, "calls:read_raw", "export leads");
  const mayExport = exportAccess.allowed;
  const agents = useAgents(session);
  const callLead = useCallLead(session);
  const [agentId, setAgentId] = useState("");

  /**
   * THE SELECTION, and the two scopes it can be in — `ids` (rows ticked on this page) or
   * `wholeQuery` (every lead the filters match). Never a third, implicit one.
   */
  const [selection, setSelection] = useState<BulkSelection>(EMPTY_SELECTION);
  /** The batch's answer, kept until dismissed so a partial failure cannot scroll away. */
  const [bulkResult, setBulkResult] = useState<LeadBulkResult | null>(null);

  /**
   * A CHANGED LENS CLEARS THE SELECTION. Half of a contract whose other half is on the
   * server: `resolve_bulk_targets` acts on the ticked ids WITHOUT re-applying the filter,
   * because intersecting them would silently drop rows from a set the person had already
   * confirmed. That is only safe if a selection cannot outlive the filter it was made
   * under — so it does not. `lensKey` is the same string the query is keyed by, which
   * means "the lens moved" here and "refetch" there are the same event by construction.
   */
  // A changed FILTER returns to page one: page 4 of "hot" is not page 4 of "won", and
  // an offset kept across the switch would show a short page and read as missing leads.
  // Keyed WITHOUT the offset, or this effect would undo every page turn.
  const filterKey = lensKey(lens, { limit: PAGE_SIZE });
  useEffect(() => {
    setOffset(0);
  }, [filterKey]);

  // Keyed WITH the offset: turning the page moves the ticked rows out from under an
  // `ids` selection, so a page change clears it exactly like a filter change does — the
  // page-scoped select-all checkbox must never carry across pages (L1's constraint).
  const currentLens = lensKey(lens, { limit: PAGE_SIZE, offset: offset || undefined });
  useEffect(() => {
    setSelection(EMPTY_SELECTION);
    setBulkResult(null);
  }, [currentLens]);

  /**
   * The columns to render — the SERVER's resolved answer, not our own selection.
   *
   * That distinction is the mirroring: `chosenColumns` is what we asked for, `columns`
   * is what the agent's capture list actually has, and the CSV header is built from the
   * second one for the same query string. Rendering our request would let the table show
   * a column the file cannot contain.
   */
  const columns: LeadColumn[] = leads.data?.columns ?? [];
  const items = leads.data?.items ?? [];

  /**
   * How many leads sit in each stage, from the SERVER — never counted off the page.
   *
   * The scope is the search (and the agent), NOT the status chip, which is the only
   * combination that answers "of what I am looking at, how much sits in each stage"
   * (crm/service.py). Read through `lookup` so a stage the response omits renders as
   * "—" rather than as a confident zero: "we have none of these" and "the server did
   * not say" are different sentences, and only one of them is ours to make up.
   */
  const stageCounts: Record<string, number> = leads.data?.status_counts_matching_search ?? {};
  const stageCount = (s: LeadStatus): number | undefined => lookup(stageCounts, s);

  /**
   * The size of the file the Export button will write — now simply `total`.
   *
   * It used to sum the stage counts to reach the UNFILTERED account, because the export
   * ignored the filters and the sentence beside the button had to name the wider figure
   * (and had to fall silent under a search, where the response could not name it at
   * all). The export now takes the same lens as this table, so the number the file will
   * hold is the number the table is a page of, and there is one figure rather than two.
   */
  const exportTotal = leads.data?.total ?? null;

  /**
   * D-22 read-only, applied to the controls rather than discovered on click. Now that
   * "View as client" genuinely lands an operator here, `leads:write` (the status
   * select) is a permission the API will refuse for them — the shell's amber banner
   * says why, so the control is disabled rather than left to answer 403.
   *
   * It was `Boolean(me.data?.impersonating)`, which is BUILD-LOG §52's `?? false` in a
   * different costume: `me.data` is undefined while `/v1/me` is in flight and after it
   * fails, so a dead permission read answered "you are NOT read-only" and re-opened
   * every status select to a 403. `mayEditLead` is the same gate the owner column
   * already uses, and it fails closed WITH a sentence.
   */
  const readOnly = !mayEditLead.allowed;

  /**
   * The id "Assigned to me" means, from the SERVER's answer to `/v1/me` — never guessed
   * and never a literal `me` in the query string. Absent while that request is in
   * flight or failed, in which case the chip does not render at all: a filter we cannot
   * fill in is a filter that would silently mean "everyone". `unavailable` below says so
   * out loud rather than leaving the chip's absence to be read as "there is no such
   * filter".
   */
  const myUserId = me.data?.user_id ?? undefined;

  /**
   * D-21's "dispatch one AI call from the Leads table". `leads:dispatch` is a MUTATING
   * permission: `staff` does not hold it and an impersonating operator (D-22) is refused
   * it, so both cases render no button rather than a 403 waiting to happen.
   */
  /* `canDialOut`, the ONE definition (src/lib/agentState.ts). This file used to carry a
     byte-identical `canDial` of its own, kept in step with the agents screen by hand —
     two spellings of one rule is a defect even while both agree, and the agents console
     made a third caller of it (the campaign picker). Filtering here is what keeps D-21's
     dispatch button off rows where the API would refuse it. */
  const dialers = agents.data?.filter(canDialOut);
  const selectedAgentId = agentId || dialers?.[0]?.id || "";
  const canCall = mayDispatch.allowed && selectedAgentId !== "";

  /**
   * The two reads this table's controls are built from, and what to say when one of
   * them did not answer — §52's "failure is a refusal", for controls whose absence is
   * otherwise indistinguishable from "your account does not have this".
   *
   * Both used to be spent as though they had answered: `(agents.data ?? []).filter(…)`
   * made an empty dialer list out of a failed `/v1/agents`, and the permission test read
   * a missing `/v1/me` as "no". The Call column, the agent picker and the "Assigned to
   * me" chip then vanished with nothing said — a client who has the feature seeing a
   * screen identical to one where it was never built.
   *
   * A KNOWN refusal is not this: a staff user who genuinely lacks `leads:dispatch` gets
   * no call controls and no sentence, because "you cannot do this" and "we could not
   * find out" are different answers and only the second one is ours to explain.
   */
  const unavailable =
    agents.error != null
      ? "We could not read your agents just now, so no call can be placed from this table. Reload the page to try again."
      : me.error != null
        ? "We could not check who you are signed in as, so calls from this table and the “Assigned to me” filter are closed. Reload the page to try again."
        : null;

  useLeadsCopilotSurface({
    status,
    setStatus,
    view,
    setView,
    search,
    leads,
    items,
    offset,
    exportTotal,
    stageCount,
    columns,
    facetValues,
    assignedTo,
    selection,
    readOnly,
    activeViewId,
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
    status,
    searchTerm,
    askTerm,
    onClearFilters: () => {
      setStatus(undefined);
      setSearch("");
    },
    stageCount,
  });

  /** A loaded row's display name, so a failure can be named rather than only numbered. */
  const nameFor = (leadId: string) => {
    const lead = items.find((row) => row.id === leadId);
    return lead ? (lead.name ?? lead.phone_e164) : null;
  };

  /* A failed first load has no rows to show and must not pretend otherwise — in either
     view. `leads.data` can still be present on a failed REFETCH (keepPreviousData), and
     those rows are real, so the guard is on the data and not on the error. */
  const showRows = Boolean(leads.data);

  /**
   * Ticking is offered exactly when the API would accept the write — `leads:write`, which
   * a D-22 impersonating operator is refused. Checkboxes that only lead to a 403 are the
   * "deliberate restriction wearing the costume of a broken button" §52 names.
   */

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Columns match what your agent captures on each call.
        </p>
        {/* No count until there IS one: "0 leads" while the first page loads is a
            statement about the business, and it is the wrong one. */}
        {leads.data && (
          <p className="text-sm text-ink-muted">
            <span className="font-semibold tabular-nums text-ink">
              {formatCount(leads.data.total)}
            </span>{" "}
            {scopeLabel(status, searchTerm, leads.data.total)}
          </p>
        )}
        {/* WHAT THE ROWS ARE, said in words, because a ranked table looks exactly like a
            filtered one and a person who cannot tell them apart will read "12 leads" as
            "this account has 12 leads". `semantic_truncated` is the server's own answer to
            "is this all of them" — never inferred here from a full page, which is the
            guess `_listing` refuses to make on the copilot's side of the same data. */}
        {askTerm && leads.data && (
          <p className="mt-1 text-xs text-ink-muted">
            Ranked by how closely each lead&rsquo;s captured answers match{" "}
            <span className="font-medium text-ink">&ldquo;{askTerm}&rdquo;</span>.
            {leads.data.semantic_truncated
              ? " There may be more matches than were ranked — ask a narrower question."
              : ""}{" "}
            Names, phone numbers and dates are not searched this way — use the search box
            and the filters for those.
          </p>
        )}
      </div>

      <LeadsToolbar
        search={search}
        onSearch={setSearch}
        ask={ask}
        onAsk={(value) => {
          setAsk(value);
          if (value === "") setAskTerm("");
        }}
        askTerm={askTerm}
        onAskSubmit={() => {
          setAskTerm(ask.trim());
          setOffset(0);
        }}
        view={view}
        onView={setView}
        leads={leads}
        chosenColumns={chosenColumns}
        onColumns={setChosenColumns}
        lens={lens}
        exportLeads={exportLeads}
        mayExport={mayExport}
        exportReason={exportAccess.reason}
        onExported={() =>
          toast({
            tone: "success",
            title: "Export ready",
            description: "Your leads CSV has downloaded.",
          })
        }
      />

      {/* Status filter chips replace the old dropdown: one click per status, and the
          active choice stays visible instead of hiding inside a closed select. They
          feed the same server-side `status` param the dropdown did. */}
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="Filter by status"
      >
        <FilterChip
          label="All"
          active={status === undefined}
          onClick={() => setStatus(undefined)}
        />
        {STATUSES.map((s) => (
          <FilterChip key={s} label={s} active={status === s} onClick={() => setStatus(s)} />
        ))}
      </div>

      {/* A SECOND axis, in its own group: owner is not a stage, and one `role="group"`
          labelled "Filter by status" containing an owner toggle is a lie to a screen
          reader. It sends `assigned_to=<my id>` to the server — the count, the stage
          badges and the export all follow it, because they are all computed over the
          filtered SET rather than over the rows that happen to have loaded. */}
      {myUserId && (
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filter by owner"
        >
          <FilterChip
            label="Assigned to me"
            active={assignedTo !== undefined}
            onClick={() => setAssignedTo(assignedTo ? undefined : myUserId)}
          />
          {/* The reason WHERE THE CONTROL IS. An impersonating operator is a real
              person with a real id, so the chip works — it just cannot match anything,
              because leads are owned by the client's own team and never by us. Saying
              so beats letting support read an empty table as an outage. */}
          {me.data?.impersonating && (
            <span className="text-xs text-ink-muted">
              You are viewing this account as Calevate operations, so no lead here is assigned to
              you.
            </span>
          )}
        </div>
      )}

      {/* The FACET RAIL, built from this agent's extraction schema. Its own component so
          the loading and failure branches are stated once, and so this file stays about
          the table. */}
      <FacetPanel
        facets={facets.data}
        loading={facets.isLoading}
        error={facets.error}
        selected={facetValues}
        onChange={setFacetValues}
        onRetry={() => facets.refetch()}
      />

      {/* SAVED VIEWS — the named lens over everything above. Below the filters it saves
          rather than above them, because "save what I have set up" reads in that order. */}
      <SavedViewBar
        views={savedViews.data}
        error={savedViews.error}
        activeViewId={activeViewId}
        canWrite={mayApplyView.allowed}
        writeReason={mayApplyView.reason}
        onApply={(view) => {
          setActiveViewId(view?.id);
          setStatus(view?.filters.status ?? undefined);
          setFacetValues(view?.filters.fields ?? {});
          setChosenColumns(view?.columns ?? undefined);
          // A view's owner filter is a BOOLEAN on the server (`assigned_to_me`) and a
          // user id here, resolved fresh against whoever is signed in — a stored id
          // would be a dangling pointer the day that colleague leaves.
          setAssignedTo(view?.filters.assigned_to_me ? myUserId : undefined);
        }}
        currentBody={{
          filters: {
            status: status ?? null,
            assigned_to_me: Boolean(assignedTo),
            fields: facetValues,
          },
          columns: chosenColumns ?? null,
        }}
      />

      {/* The one sentence about the file, now that it is the same file as the screen.
          The warning this replaces said "the export ignores this filter", which was true
          and is no longer — leaving it would have been the more dangerous of the two
          wrong sentences, since it teaches a client to distrust a control that works. */}
      <p className="text-xs text-ink-muted">
        {exportTotal === null
          ? "The CSV export contains the leads and columns shown here, with full phone numbers, and each download is recorded."
          : `The CSV export contains ${
              exportTotal === 1 ? "this 1 lead" : `these ${formatCount(exportTotal)} leads`
            } and the columns shown here, with full phone numbers. Each download is recorded.`}
      </p>

      {/* Which agent dials decides the script, the voice and the disclosure line, so
          the choice is on screen whenever there is one — same reasoning as the campaign
          form. No picker and no buttons when nothing here can dial, and the sentence
          instead of the picker when we could not find out whether anything can. */}
      {unavailable !== null ? (
        <p className="text-xs text-ink-muted">{unavailable}</p>
      ) : (
        canCall && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <span>Calls from this table are placed by</span>
            {dialers !== undefined && dialers.length > 1 ? (
              <select
                value={selectedAgentId}
                onChange={(e) => setAgentId(e.target.value)}
                aria-label="Agent that places calls from this table"
                className="rounded-md border border-line bg-transparent px-2 py-1 text-xs text-ink"
              >
                {dialers.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-semibold text-ink">{dialers?.[0]?.name}</span>
            )}
            <span>
              · every call still goes through the do-not-call, calling-hours and consent checks, and
              can be refused.
            </span>
          </div>
        )
      )}

      {/* The reason the owner column is dead, said once above the table it is dead in.
          `RestrictionNote` renders nothing while `/v1/me` is still in flight, so the
          sentence never flashes and is never retracted. */}
      <RestrictionNote reason={mayEditLead.reason} />

      {/* THE BULK BAR, between the filters and the table it acts on — the set it is
          about is the set above it, and the rows it will change are below it. It renders
          nothing until something is selected. */}
      <BulkActionBar
        selection={selection}
        // The server's `total` for this lens, and `undefined` while that is unknown: the
        // confirmation states how many rows it will change, and a manufactured 0 under
        // that sentence is the one number nobody would question (§52).
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
                // The selection is spent. Leaving it ticked invites a second run against
                // rows that have already moved, and the result summary above is now the
                // thing to read.
                setSelection(EMPTY_SELECTION);
              },
            },
          )
        }
      />

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {exportLeads.error && <ProblemNotice error={exportLeads.error} />}
      {/* The team list failing is not the leads list failing: the rows are fine and only
          the picker is dead, which is why this is its own notice and the owner cells
          fall back to naming the owner in plain text rather than to an empty select. */}
      {members.error != null && <ProblemNotice error={members.error} />}
      {/* Inline-edit failures are NOT here. They belong to one row each and are rendered
          in that row (`rowFailure`) — a page-level notice on a hundred-row table says an
          edit failed without saying which, which is the half of the message that matters.
          A bulk failure is likewise on the bar, beside the set it was about. */}
      {/* A refusal by the gate comes back 200 and is rendered on the row; this is for
          the real failures (network, 403, a lead with no dialable number). */}
      {callLead.error != null && <ProblemNotice error={callLead.error} />}

      {/* Loading and failure are the same answer in both views, so they are given once
          here rather than twice below: a skeleton is not a number, and a request that
          did not land gets no container at all — the notice above is the whole answer. */}
      {leads.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={6} />
        </Card>
      ) : !showRows ? null : view === "list" ? (
        <LeadTable kit={kit} />
      ) : (
        <LeadBoard kit={kit} />
      )}

      <LeadsFooter
        leads={leads}
        items={items}
        offset={offset}
        status={status}
        searchTerm={searchTerm}
        stageCount={stageCount}
        onOffsetChange={setOffset}
      />
    </div>
  );
}

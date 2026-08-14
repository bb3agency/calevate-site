"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Download,
  LayoutGrid,
  List,
  PhoneOutgoing,
  Search,
  ShieldAlert,
} from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatusBadge,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useAgents, type Agent } from "@/lib/api/agents";
import { type CallLeadResult } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { useCallLead, useMe, useUpdateLeadStatus, useWriteAccess } from "@/lib/api/hooks";
import {
  useAssignLead,
  useExportLeads,
  useLeadFacets,
  useLeadsUnderLens,
  useMembers,
  useSavedViews,
  type Lead,
  type LeadColumn,
  type LeadLens,
  type LeadStatus,
} from "@/lib/api/leads";
import { lookup } from "@/lib/lookup";

import { AssigneeSelect } from "./AssigneeSelect";
import { ColumnChooser } from "./ColumnChooser";
import { FacetPanel } from "./FacetPanel";
import { SavedViewBar } from "./SavedViewBar";

/**
 * The CRM table — every lead an agent captured, and the one place a client works them.
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, lucide icons as
 * affordances) WITHOUT changing what it fetches, what it filters on, or what the dispatch
 * button does. What did change is every number that was not the server's:
 *
 * - **The stage tally at the foot counted the loaded page, not the account.** Six badges
 *   over `items.filter(...)`, under a 100-row cap and a server-side status filter — so a
 *   client who clicked "hot" was told "new 0 · contacted 0 · won 0", which is a statement
 *   about our query read as a statement about their business. `LeadListOut` carries
 *   `status_counts_matching_search` for exactly this (crm/schemas.py names this bug as
 *   the one it replaces), and it is now what the badges render.
 * - **The export warning printed the FILTERED total next to the words "every lead in the
 *   account".** `total` counts rows matching every filter, `status` included. The
 *   unfiltered figure is the sum of the stage counts — but those follow the SEARCH, so
 *   with a search on the number is not in the response at all and the sentence now goes
 *   out without one rather than with a wrong one.
 * - **The board rendered six "No leads" columns on a FAILED request.** The list view had
 *   the guard (`leads.error ? null : <EmptyState/>`); the board did not, so a request
 *   that never landed painted an empty, confident pipeline. Failure is the notice above,
 *   never a zero.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Leads" beside it is a visible duplicate.
 *
 * Hard rule 6 holds at the row: `phone_masked` is the only number on `LeadOut`, and the
 * only one this screen may render or put in a URL. The CSV export is the one path to
 * full numbers, it goes through the session headers, and the API audit-logs the read —
 * which is why the button says out loud what it downloads.
 */

/** Fixed enum (D-21): clients cannot add statuses, because analytics and the hot-lead
 *  rules key off exactly these values. */
const STATUSES: LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

/** Two ways to look at the same leads: the table for scanning detail columns, the
 *  board for working the pipeline stage by stage (parity with what competitors ship). */
type ViewMode = "list" | "board";

/** Table cell metrics, once — a table whose columns disagree about padding reads as two
 *  tables. `p-2` on the card body plus `px-3` here is the design's 20px edge inset. */
const HEAD_CELL = "px-3 py-2.5 font-semibold";
const BODY_CELL = "px-3 py-2.5";

/**
 * An agent that can actually place this call. Same test the Agents screen renders as
 * "Live": on the calling system AND switched on — plus able to dial at all, which an
 * inbound-only receptionist is not. Filtering here is what keeps D-21's dispatch button
 * off rows where the API would refuse it.
 */
function canDial(agent: Agent): boolean {
  return agent.published && agent.status === "live" && agent.direction !== "inbound";
}

/** What the header count is a count OF, with both filters that narrow it named. */
function scopeLabel(status: string | undefined, search: string, total: number): string {
  const stage = status ? `${status} ` : "";
  const noun = total === 1 ? "lead" : "leads";
  return search ? `${stage}${noun} matching your search` : `${stage}${noun}`;
}

export default function LeadsPage() {
  // `href` (not just the session) because the name cell now links to the lead's own
  // screen, and an in-realm link must carry the D-22 operator marker forward or the
  // next page silently falls back to a client token it does not have.
  const { session, href } = useClientRealm();
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState("");
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
    assigned_to: assignedTo,
    fields: facetValues,
    columns: chosenColumns,
  };

  // Every filter on this screen is a SERVER-side filter — the chips, the search box, the
  // owner and the facets. The page is capped at 100 rows, so a filter applied here would
  // be a filter over whatever happened to load (BUILD-LOG §52 counts four defects of
  // exactly that shape, including the stage tally on this very screen).
  const leads = useLeadsUnderLens(session, lens, { limit: 100 });
  const facets = useLeadFacets(session, lens);
  const savedViews = useSavedViews(session);
  const updateStatus = useUpdateLeadStatus(session);
  const exportLeads = useExportLeads(session);
  const members = useMembers(session);
  const assignLead = useAssignLead(session);
  /**
   * May this session change an owner? The server's own answer to `/v1/me`, run through
   * the same helper every other gated control on this console uses: it folds the
   * permission and D-22 impersonation into one `{allowed, reason}` so the select is
   * disabled WITH the sentence rather than clicking into a 403.
   */
  const mayAssign = useWriteAccess(session, "leads:write", "change who owns a lead");

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
   * The dispatch answer, per lead. It has to live here rather than on the mutation:
   * `callLead.data` is one slot, so calling a second lead would move the first row's
   * verdict onto the second — and a compliance refusal moving rows is worse than none.
   */
  const [callResults, setCallResults] = useState<Record<string, CallLeadResult>>({});

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
   */
  const readOnly = Boolean(me.data?.impersonating);

  /**
   * The id "Assigned to me" means, from the SERVER's answer to `/v1/me` — never guessed
   * and never a literal `me` in the query string. Absent while that request is in
   * flight or failed, in which case the chip does not render at all: a filter we cannot
   * fill in is a filter that would silently mean "everyone".
   */
  const myUserId = me.data?.user_id ?? undefined;

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
      {
        onSuccess: (result) => setCallResults((prev) => ({ ...prev, [leadId]: result })),
      },
    );

  const callCell = (lead: Lead) =>
    canCall ? (
      <CallControl
        result={callResults[lead.id]}
        pending={callLead.isPending && callLead.variables?.leadId === lead.id}
        onCall={() => dispatch(lead.id)}
      />
    ) : null;

  const ownerCell = (lead: Lead, className: string) => (
    <AssigneeSelect
      lead={lead}
      members={members.data}
      // The picker is only offered when the team list actually ARRIVED. An empty
      // `<select>` over a failed `/v1/members` would read as "you have no colleagues",
      // which is a statement about the business made from a request that never landed.
      unavailableReason={
        members.error
          ? "We could not read your team just now, so the owner cannot be changed. Reload the page to try again."
          : mayAssign.reason
      }
      disabled={!mayAssign.allowed || assignLead.isPending}
      onChange={(userId) => assignLead.mutate({ leadId: lead.id, userId })}
      className={className}
    />
  );

  /**
   * ONE CELL, chosen by the server's column key.
   *
   * The switch is the price of a chooseable table and it is worth paying here rather
   * than in a generic renderer: `phone` must be `phone_masked` and nothing else (hard
   * rule 6), `status` and `owner` are interactive controls rather than text, and `name`
   * is the link to the lead. A table that rendered every column as `String(value)` would
   * be shorter and would put a full number on the screen the first time somebody added
   * a `phone_e164` column. Anything the switch does not name is an extraction field.
   */
  const renderCell = (column: LeadColumn, lead: Lead) => {
    switch (column.kind === "fixed" ? column.key : "") {
      case "name":
        return (
          <>
            {/* The lead's own screen, where the timeline lives. The href carries the
                lead ID and never the number — a URL reaches browser history, referrers
                and access logs, so hard rule 6 is stricter for a link than for text. */}
            <Link href={href(`/c/${session.orgSlug}/leads/${lead.id}`)} className="hover:underline">
              {lead.name ?? <span className="font-normal text-ink-faint">No name</span>}
            </Link>
            {lead.is_repeat_caller && (
              <span className="ml-2 rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold text-brand-strong">
                repeat
              </span>
            )}
          </>
        );
      case "phone":
        // MASKED, always. `phone_masked` is the only number `LeadOut` carries and the
        // only one this screen may render; full numbers exist on the audited CSV export
        // and nowhere else.
        return lead.phone_masked;
      case "status":
        return (
          <StatusSelect
            value={lead.status}
            label={`Status for ${lead.name ?? lead.phone_masked}`}
            disabled={updateStatus.isPending || readOnly}
            onChange={(next) => updateStatus.mutate({ leadId: lead.id, status: next })}
            className="rounded-md border border-transparent bg-transparent px-1 py-0.5 text-xs capitalize text-ink hover:border-line"
          />
        );
      case "owner":
        return ownerCell(
          lead,
          "rounded-md border border-transparent bg-transparent px-1 py-0.5 text-xs text-ink hover:border-line",
        );
      case "source":
        return lead.source;
      case "calls":
        return formatCount(lead.call_count);
      case "created_at":
        return formatIST(lead.created_at);
      case "updated_at":
        return formatIST(lead.updated_at);
      default:
        return cellValue(lead, column.key);
    }
  };

  /* A failed first load has no rows to show and must not pretend otherwise — in either
     view. `leads.data` can still be present on a failed REFETCH (keepPreviousData), and
     those rows are real, so the guard is on the data and not on the error. */
  const showRows = Boolean(leads.data);

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Columns follow your agent&apos;s capture list. Phone numbers are masked here.
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
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            // The API caps `search` at 60 characters and 422s beyond it.
            maxLength={60}
            aria-label="Search leads"
            placeholder="Name or last digits"
            className="w-56 rounded-md border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-ink placeholder:text-ink-faint"
          />
        </div>

        {/* View toggle: the list keeps every capture-list column; the board trades
            detail for a stage-by-stage picture of the pipeline. */}
        <div
          role="group"
          aria-label="View"
          className="flex overflow-hidden rounded-md border border-line text-sm"
        >
          {(["list", "board"] as const).map((mode) => {
            const Icon = mode === "list" ? List : LayoutGrid;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => setView(mode)}
                aria-pressed={view === mode}
                className={
                  view === mode
                    ? "flex items-center gap-1.5 bg-brand-strong px-3 py-1.5 font-semibold text-white"
                    : "flex items-center gap-1.5 bg-surface px-3 py-1.5 font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {mode === "list" ? "List" : "Board"}
              </button>
            );
          })}
        </div>

        {/* The COLUMN CHOOSER. It sits beside Export rather than above the table on
            purpose: it decides what the table shows AND what the file contains, and a
            control that changes the download belongs next to the download. */}
        <ColumnChooser
          available={leads.data?.available_columns}
          chosen={chosenColumns}
          onChange={setChosenColumns}
          unavailableReason={
            leads.error
              ? "We could not read this table's columns just now, so they cannot be chosen. Reload the page to try again."
              : null
          }
        />

        {/* Fetched, not linked: the endpoint authenticates from the session headers,
            which a browser navigation does not send — a plain <a> answers 401. The
            API audit-logs the read either way.

            The label no longer says "all". `/v1/leads/export.csv` now takes the SAME
            lens as this table — status, search, owner, facets and the chosen columns —
            so the file is what the screen is showing, and the button says which. */}
        {/* GATED ON THE PERMISSION THE ROUTE ACTUALLY REQUIRES. This is the one
            endpoint where a client's contact list leaves us with FULL phone numbers,
            so it demands `calls:read_raw` — owner in the client realm, never `staff`
            (crm/routes.py says so at the decorator). The button used to render for
            every viewer, which meant a staff user clicked it and got a 403 dressed as
            a fault. Disabled WITH the reason is the doctrine this app already follows
            for dispatch and for D-22 impersonation: an answer given before the click
            beats a refusal after it. The server still refuses either way — this is a
            preview of its answer, never a substitute for it. */}
        <button
          type="button"
          disabled={exportLeads.isPending || !mayExport}
          onClick={() => exportLeads.mutate(lens)}
          title={
            mayExport
              ? "Downloads the leads and the columns shown here, with full phone numbers."
              : // The refusal in the server's own terms — "Only an account owner can
                // export leads." for a role that lacks it, and "We could not check…"
                // when `/v1/me` failed. Those are different facts and the tooltip used
                // to state the first for both.
                (exportAccess.reason ?? "Checking whether you can export these leads…")
          }
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
        >
          <Download className="h-3.5 w-3.5" />
          {exportLeads.isPending ? "Preparing…" : "Export this view as CSV"}
        </button>
      </div>

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
          form. No picker and no buttons when nothing here can dial. */}
      {canCall && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <span>Calls from this table are placed by</span>
          {dialers.length > 1 ? (
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
            <span className="font-semibold text-ink">{dialers[0]?.name}</span>
          )}
          <span>
            · every call still goes through the do-not-call, calling-hours and consent checks, and
            can be refused.
          </span>
        </div>
      )}

      {/* The reason the owner column is dead, said once above the table it is dead in.
          `RestrictionNote` renders nothing while `/v1/me` is still in flight, so the
          sentence never flashes and is never retracted. */}
      <RestrictionNote reason={mayAssign.reason} />

      {leads.error && <ProblemNotice error={leads.error} onRetry={() => leads.refetch()} />}
      {updateStatus.error && <ProblemNotice error={updateStatus.error} />}
      {exportLeads.error && <ProblemNotice error={exportLeads.error} />}
      {/* The team list failing is not the leads list failing: the rows are fine and only
          the picker is dead, which is why this is its own notice and the owner cells
          fall back to naming the owner in plain text rather than to an empty select. */}
      {members.error != null && <ProblemNotice error={members.error} />}
      {assignLead.error != null && <ProblemNotice error={assignLead.error} />}
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
        <Card bodyClassName="p-2">
          {items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  {/* THE HEADER IS THE SERVER'S COLUMN LIST, in the server's order — the
                      same list `export.csv` writes its header from for this query
                      string. It used to be four hard-coded `<th>`s, the schema fields,
                      and two more hard-coded ones, which is precisely how the screen and
                      the file came to hold different columns. */}
                  <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                    {columns.map((column) => (
                      <th key={column.key} className={HEAD_CELL}>
                        {column.label}
                      </th>
                    ))}
                    {canCall && <th className={HEAD_CELL}>Call</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {items.map((lead) => (
                    <tr key={lead.id} className="hover:bg-black/[0.02] dark:hover:bg-white/[0.03]">
                      {columns.map((column) => (
                        <td key={column.key} className={cellClass(column)}>
                          {renderCell(column, lead)}
                        </td>
                      ))}
                      {canCall && <td className={BODY_CELL}>{callCell(lead)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            /* "No leads yet" only where the server said so — never on a failed fetch,
               which is why that case never reaches this Card at all. With a filter on,
               the emptiness belongs to the filter and not to the business. */
            <EmptyState
              title={status || searchTerm ? "No leads match this filter" : "No leads yet"}
              hint={
                status || searchTerm
                  ? "Clear the filter to see everything."
                  : "Every answered call becomes a lead within two minutes."
              }
            />
          )}
        </Card>
      ) : (
        /* Board view: one column per D-21 status. The cards are the loaded page; the
           count in each header is the SERVER's figure for that stage, so a column can
           legitimately show more than it holds — and says so underneath rather than
           letting the header be read as "this is all of them". */
        <div className="overflow-x-auto pb-2">
          <div className="grid min-w-[960px] grid-cols-6 gap-3">
            {STATUSES.map((s) => {
              const columnLeads = items.filter((l) => l.status === s);
              const total = stageCount(s);
              const hidden = total === undefined ? 0 : total - columnLeads.length;
              return (
                <div key={s} className="rounded-card border border-line bg-app p-2">
                  <div className="flex items-center justify-between px-1 pb-2">
                    <StatusBadge value={s} />
                    <span className="text-xs font-semibold tabular-nums text-ink-muted">
                      {formatCount(total)}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {columnLeads.map((lead) => (
                      <div
                        key={lead.id}
                        className="rounded-lg border border-line bg-surface p-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                      >
                        <p className="truncate text-sm font-semibold text-ink">
                          {/* The list of leads without a captured name is long; the
                              masked phone is the next-best stable identifier. */}
                          <Link
                            href={href(`/c/${session.orgSlug}/leads/${lead.id}`)}
                            className="hover:underline"
                          >
                            {lead.name ?? lead.phone_masked}
                          </Link>
                        </p>
                        <p className="mt-0.5 truncate text-xs text-ink-faint">
                          {lead.source} · {formatIST(lead.updated_at)}
                        </p>
                        {/* No drag-and-drop: the same PATCH the table uses, behind a
                            select, works everywhere including on a phone. */}
                        <StatusSelect
                          value={lead.status}
                          label={`Status for ${lead.name ?? lead.phone_masked}`}
                          disabled={updateStatus.isPending || readOnly}
                          onChange={(next) =>
                            updateStatus.mutate({
                              leadId: lead.id,
                              status: next,
                            })
                          }
                          className="mt-1.5 w-full rounded-md border border-line bg-transparent px-1 py-0.5 text-xs capitalize text-ink"
                        />
                        {/* Same control as the table, for the reason the dispatch
                            button below states: the board is where someone works the
                            pipeline, so a feature reachable only from the other tab is
                            a feature half the users never find. */}
                        <div className="mt-1.5">
                          {ownerCell(
                            lead,
                            "w-full rounded-md border border-line bg-transparent px-1 py-0.5 text-xs text-ink",
                          )}
                        </div>
                        {canCall && <div className="mt-1.5">{callCell(lead)}</div>}
                      </div>
                    ))}
                    {/* The gap between the stage's real size and what fits on this
                        page, named. Without it a chip filtered to one stage empties
                        five columns whose headers still (correctly) show a count. */}
                    {hidden > 0 && (
                      <p className="px-1 py-2 text-center text-xs text-ink-faint">
                        {columnLeads.length === 0
                          ? `${formatCount(hidden)} not on this page`
                          : `+${formatCount(hidden)} more not on this page`}
                      </p>
                    )}
                    {/* "No leads" is a claim, so it needs the server to have made it:
                        `total === 0`, not "nothing rendered". A response missing this
                        stage leaves the column blank under a "—" header instead. */}
                    {columnLeads.length === 0 && total === 0 && (
                      <p className="px-1 py-3 text-center text-xs text-ink-faint">No leads</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* The stage tally, from `status_counts_matching_search` — the server's numbers
          over the server's scope. It used to count the rows ON SCREEN, which under a
          status chip printed five confident zeroes about stages the client demonstrably
          had leads in. Both scopes are stated, because they differ: the denominator
          obeys every filter, the badges obey the search only. */}
      {leads.data && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 text-xs text-ink-muted">
          <span>
            Showing{" "}
            <span className="font-semibold tabular-nums text-ink">{formatCount(items.length)}</span>{" "}
            of {formatCount(leads.data.total)}
            {status ? ` ${status}` : ""} {leads.data.total === 1 ? "lead" : "leads"}.
          </span>
          <span>{searchTerm ? "Matching your search" : "In this account"}, by stage:</span>
          {STATUSES.map((s) => (
            <span key={s} className="flex items-center gap-1">
              <StatusBadge value={s} />
              <span className="font-semibold tabular-nums text-ink">
                {formatCount(stageCount(s))}
              </span>
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
 *
 * A refusal is amber, not rose: the gate working is not a fault, and painting it like an
 * error is what teaches a client to report their own compliance rules as bugs.
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
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-brand-strong dark:text-brand-bright">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        Calling now
      </span>
    );
  }
  if (result?.status === "blocked") {
    return (
      <span className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          {result.blocked_reason ?? "This call was not allowed."}
          {result.blocked_rule ? ` (${result.blocked_rule})` : ""}
        </span>
      </span>
    );
  }
  return (
    <button
      type="button"
      disabled={pending}
      onClick={onCall}
      className="flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs font-semibold text-ink-muted hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/5"
    >
      <PhoneOutgoing className="h-3.5 w-3.5 shrink-0" />
      {pending ? "Calling…" : "Call with AI"}
    </button>
  );
}

/** One chip = one server-side status filter value; "All" clears it. */

/** The one status-change control, shared by table rows and board cards, so both
 *  views go through exactly the same mutation (useUpdateLeadStatus). The label names
 *  the LEAD: a screen reader meeting a hundred selects called "status" cannot tell
 *  which row it is on. */
function StatusSelect({
  value,
  label,
  disabled,
  onChange,
  className,
}: {
  value: LeadStatus;
  label: string;
  disabled: boolean;
  onChange: (next: LeadStatus) => void;
  className: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
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
  // `lookup`, not `data[key]`: `data` arrives from JSON.parse and therefore inherits
  // Object.prototype, so an extraction field keyed `constructor` — a client's own field
  // name, which nothing on our side constrains — would print
  // `function Object() { [native code] }` into the cell (src/lib/lookup.ts).
  const data: Record<string, unknown> = lead.data ?? {};
  const value = lookup(data, key);
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** Per-column table styling. A column's LOOK follows its kind, so a client who moves
 *  Phone to the end still gets tabular numerals and no wrapping there. */
function cellClass(column: LeadColumn): string {
  switch (column.key) {
    case "name":
      return `${BODY_CELL} font-semibold text-ink`;
    case "phone":
      return `${BODY_CELL} whitespace-nowrap tabular-nums text-ink-muted`;
    case "calls":
      return `${BODY_CELL} tabular-nums text-ink-muted`;
    case "created_at":
    case "updated_at":
      return `${BODY_CELL} whitespace-nowrap text-xs text-ink-faint`;
    default:
      return `${BODY_CELL} text-ink-muted`;
  }
}

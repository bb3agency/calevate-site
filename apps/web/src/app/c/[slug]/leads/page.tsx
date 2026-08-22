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
  ScrollRegion,
  Skeleton,
  StatusBadge,
  formatCount,
  formatIST,
} from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { type CallLeadResult } from "@/lib/api/client";
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
  type Lead,
  type LeadBulkResult,
  type LeadColumn,
  type LeadLens,
  type LeadStatus,
} from "@/lib/api/leads";
import { lookup } from "@/lib/lookup";

import { AssigneeSelect } from "./AssigneeSelect";
import { BulkActionBar, EMPTY_SELECTION, type BulkSelection } from "./BulkActionBar";
import { ColumnChooser } from "./ColumnChooser";
import { FacetPanel } from "./FacetPanel";
import { InlineName } from "./InlineName";
import { RowFailure } from "./RowFailure";
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
 * **Slice AE added the other half of the table floor**: bulk actions and the inline text
 * edit. Two properties of it live HERE rather than in the components, because they are
 * properties of the screen:
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
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Leads" beside it is a visible duplicate.
 *
 * Numbers render IN FULL (D-436): a lead nobody can ring is not a lead, and this table
 * is where a receptionist works the queue. Two things about that are unchanged and are
 * not rendering choices — a number never goes into a URL (search is a POST body, which
 * is why `LeadLensIn` exists), and the CSV export stays behind `calls:read_raw` with an
 * audit row, because taking the whole list is a different act from reading one row. The
 * export button says out loud what it downloads.
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
 * The two controls a client touches most — move a lead's stage, reassign its owner — at
 * a size a thumb can hit.
 *
 * They were `px-1 py-0.5 text-xs`: 12px text in a 16px line box plus 2px each side, so
 * about a 20px-tall target, inside a table that scrolls sideways on a phone. That is
 * under WCAG 2.2 SC 2.5.8 Target Size (Minimum), which is 24×24 at Level AA. Both are
 * WRITES — a mis-tap on the status select changes a lead's stage, and `RowFailure` only
 * speaks after a FAILED write, never after a wrong one — so the cost of a near-miss here
 * is a lead in the wrong column that nobody knows moved.
 *
 * `touch:min-h-11` (44px on a coarse pointer) rather than the 24px the AA minimum would
 * accept, and rather than a flat `min-h-11`. Both halves of that are the repo's own
 * answer rather than a new one: 44px is the size every other tap target here uses, and
 * the `touch:` variant is `globals.css`'s `@media (pointer: coarse)` — a tap target is a
 * fact about the FINGER, not the viewport, so a mouse-driven console keeps its density
 * and a tablet gets the target. A second, flat spelling would have quietly restyled the
 * densest table in the product for every operator on a desktop.
 *
 * The visual compactness the small padding was buying is preserved by the transparent
 * border and background the class already carries — the control still reads as text until
 * it is hovered. `tests/responsive.test.ts` pins it.
 */
const INLINE_EDIT =
  "touch:min-h-11 rounded-md border border-transparent bg-transparent px-1 py-0.5 text-xs text-ink";

/**
 * Rows per request, named because the bulk bar has to talk about it.
 *
 * "All 100 leads on this page are selected" and "select all 1,240 matching these filters"
 * are two different actions, and the sentence that offers the second one has to say how
 * big the first is. A literal in two places is how those two numbers come to disagree.
 */
const PAGE_SIZE = 100;

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
  const leads = useLeadsUnderLens(session, lens, { limit: PAGE_SIZE });
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
   * The dispatch answer, per lead. It has to live here rather than on the mutation:
   * `callLead.data` is one slot, so calling a second lead would move the first row's
   * verdict onto the second — and a compliance refusal moving rows is worse than none.
   */
  const [callResults, setCallResults] = useState<Record<string, CallLeadResult>>({});

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
  const currentLens = lensKey(lens, { limit: PAGE_SIZE });
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
          : mayEditLead.reason
      }
      // Per-ROW pending, not the mutation's global flag: one saving row must not freeze
      // every other row's controls.
      disabled={!mayEditLead.allowed || rows.pendingFor(lead.id)}
      onChange={(userId) => rows.edit(lead.id, { assigned_to: userId })}
      className={className}
    />
  );

  /**
   * THE FAILURE, IN THE ROW IT BELONGS TO — once per row, in its FIRST cell.
   *
   * An inline edit that fails and reverts is a lie the user cannot see: the control snaps
   * back to the stored value because the row re-renders from a cache the server never
   * changed, and without this the only evidence is a value that did not stick. A single
   * page-level notice cannot do that job on a hundred-row table — it says an edit failed
   * without saying which row.
   *
   * The first cell rather than the edited one, and that is not laziness: the column
   * chooser can drop the name, the status or the owner, so a message anchored to any one
   * of them would disappear exactly when that column was hidden — and a row can only have
   * one failure at a time (one mutation, one error slot), so one place per row is the
   * honest number of places.
   */
  const rowFailure = (lead: Lead) => <RowFailure error={rows.errorFor(lead.id)} />;

  /**
   * ONE CELL, chosen by the server's column key.
   *
   * The switch is the price of a chooseable table and it is worth paying here rather
   * than in a generic renderer: `status` and `owner` are interactive controls rather
   * than text, `name` is the link to the lead, and `phone` is plain text on purpose —
   * a `tel:` link would put the number in an `href`, which is the one place it still
   * must not go. Anything the switch does not name is an extraction field.
   */
  const renderCell = (column: LeadColumn, lead: Lead) => {
    switch (column.kind === "fixed" ? column.key : "") {
      case "name":
        // The link AND the inline text edit (SURFACES §2: "exit via Enter/click-out; no
        // modal"). `InlineName` carries the interaction and the row-level failure; the
        // gate is the same `leads:write` the two selects use.
        return (
          <InlineName
            lead={lead}
            href={href(`/c/${session.orgSlug}/leads/${lead.id}`)}
            canEdit={mayEditLead.allowed}
            editReason={mayEditLead.reason}
            saving={rows.pendingFor(lead.id)}
            onCommit={(name) => rows.edit(lead.id, { name })}
          />
        );
      case "phone":
        // IN FULL (D-436). Text, not a `tel:` href — see `renderCell` above.
        return lead.phone_e164;
      case "status":
        return (
          <StatusSelect
            value={lead.status}
            label={`Status for ${lead.name ?? lead.phone_e164}`}
            disabled={rows.pendingFor(lead.id) || readOnly}
            onChange={(next) => rows.edit(lead.id, { status: next })}
            className={`${INLINE_EDIT} capitalize hover:border-line`}
          />
        );
      case "owner":
        return ownerCell(
          lead,
          `${INLINE_EDIT} hover:border-line`,
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

  /**
   * Ticking is offered exactly when the API would accept the write — `leads:write`, which
   * a D-22 impersonating operator is refused. Checkboxes that only lead to a 403 are the
   * "deliberate restriction wearing the costume of a broken button" §52 names.
   */
  const maySelect = mayEditLead.allowed;
  // Not memoised: `items` is `leads.data?.items ?? []`, a fresh array every render, so a
  // `useMemo` keyed on it would recompute every render anyway while implying it did not.
  const pageIds = items.map((lead) => lead.id);
  const ticked = new Set(selection.wholeQuery ? pageIds : selection.ids);
  const allOfPageTicked = pageIds.length > 0 && pageIds.every((id) => ticked.has(id));

  const toggleRow = (leadId: string) =>
    setSelection((prev) => {
      // Ticking a row out of a whole-query selection narrows it back to THIS PAGE, and
      // says so through the bar's sentence. Silently keeping the query scope while a row
      // looks unticked would be the scope ambiguity in its most confusing form.
      const base = prev.wholeQuery ? pageIds : prev.ids;
      const next = base.includes(leadId)
        ? base.filter((id) => id !== leadId)
        : [...base, leadId];
      return { ids: next, wholeQuery: false };
    });

  /** A loaded row's display name, so a failure can be named rather than only numbered. */
  const nameFor = (leadId: string) => {
    const lead = items.find((row) => row.id === leadId);
    return lead ? (lead.name ?? lead.phone_e164) : null;
  };

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Columns follow your agent&apos;s capture list.
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
        <Card bodyClassName="p-2">
          {items.length ? (
            <ScrollRegion label="Leads">
              <table className="w-full text-sm">
                <thead>
                  {/* THE HEADER IS THE SERVER'S COLUMN LIST, in the server's order — the
                      same list `export.csv` writes its header from for this query
                      string. It used to be four hard-coded `<th>`s, the schema fields,
                      and two more hard-coded ones, which is precisely how the screen and
                      the file came to hold different columns. */}
                  <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                    {/* THE HEADER CHECKBOX IS PAGE-SCOPED, and its label says so. This
                        is the researched division (PatternFly, Helios): the header
                        selects what is in front of you, and extending to the whole
                        filtered query is a separate, named act offered by the bar. */}
                    {maySelect && (
                      <th className={`${HEAD_CELL} w-8`} scope="col">
                        {/* A column header whose only content is a checkbox has no
                            accessible name of its own, so a screen reader announces the
                            column as blank while reading every row's cell. The label is
                            visually hidden rather than dropped. */}
                        <span className="sr-only">Select</span>
                        <input
                          type="checkbox"
                          aria-label="Select all leads on this page"
                          checked={allOfPageTicked}
                          onChange={() =>
                            setSelection(
                              allOfPageTicked
                                ? EMPTY_SELECTION
                                : { ids: pageIds, wholeQuery: false },
                            )
                          }
                        />
                      </th>
                    )}
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
                      {maySelect && (
                        <td className={BODY_CELL}>
                          <input
                            type="checkbox"
                            // Names the LEAD: a screen reader meeting a hundred boxes
                            // called "select" cannot tell which row it is on.
                            aria-label={`Select ${lead.name ?? lead.phone_e164}`}
                            checked={ticked.has(lead.id)}
                            onChange={() => toggleRow(lead.id)}
                          />
                        </td>
                      )}
                      {columns.map((column, index) => (
                        <td key={column.key} className={cellClass(column)}>
                          {renderCell(column, lead)}
                          {/* Once per row, in its first cell — see `rowFailure`. */}
                          {index === 0 && rowFailure(lead)}
                        </td>
                      ))}
                      {canCall && <td className={BODY_CELL}>{callCell(lead)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
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
        <ScrollRegion label="Leads by stage" className="pb-2">
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
                              phone number is the next-best stable identifier. */}
                          <Link
                            href={href(`/c/${session.orgSlug}/leads/${lead.id}`)}
                            className="hover:underline"
                          >
                            {lead.name ?? lead.phone_e164}
                          </Link>
                        </p>
                        <p className="mt-0.5 truncate text-xs text-ink-faint">
                          {lead.source} · {formatIST(lead.updated_at)}
                        </p>
                        {/* No drag-and-drop: the same PATCH the table uses, behind a
                            select, works everywhere including on a phone. */}
                        <StatusSelect
                          value={lead.status}
                          label={`Status for ${lead.name ?? lead.phone_e164}`}
                          disabled={rows.pendingFor(lead.id) || readOnly}
                          onChange={(next) => rows.edit(lead.id, { status: next })}
                          className={`mt-1.5 w-full ${INLINE_EDIT} border-line capitalize`}
                        />
                        {/* Same control as the table, for the reason the dispatch
                            button below states: the board is where someone works the
                            pipeline, so a feature reachable only from the other tab is
                            a feature half the users never find. */}
                        <div className="mt-1.5">
                          {ownerCell(
                            lead,
                            `w-full ${INLINE_EDIT} border-line`,
                          )}
                        </div>
                        {/* The failure lands on the CARD for the same reason it lands on
                            the row: a select that snapped back with no sentence is an
                            edit the client cannot tell failed. */}
                        {rowFailure(lead)}
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
        </ScrollRegion>
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

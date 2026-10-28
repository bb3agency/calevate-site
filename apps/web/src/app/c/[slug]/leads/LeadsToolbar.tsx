"use client";

import { Download, SlidersHorizontal } from "lucide-react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { SearchField } from "@/components/arc/search-field";

import { InfoTip } from "@/components/console/infoTip";
import { FIELD_INLINE, RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";

import { type LeadList } from "@/lib/api/leads";

import { ColumnChooser } from "./ColumnChooser";

/**
 * FIND, SHAPE, TAKE AWAY — the strip above the table.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). One subject: the controls that decide WHICH
 * rows and WHICH columns, plus the download that takes exactly those away. The export
 * button's gate and its three tooltip states are a compliance surface — `calls:read_raw`
 * is the permission `/v1/leads/export.csv` requires, the refusal is the server's own
 * sentence, and every download is audited — and none of it was reworded in the move.
 *
 * ON A PHONE ONLY SEARCH STAYS OUT. The question box, Columns and Export (with the
 * export's refusal) fold behind one "Filters" button, together with the screen's
 * "More filters" (`filtersPanelIds` names both regions), so the first lead row sits under
 * the search and stage controls instead of under a screen of controls. The button counts
 * the filters in force, so a closed panel never hides that rows are narrowed. From `sm`
 * the panel is always open and the button is gone. It is CSS, not a width check, so the
 * table and every control render at every width.
 */
export function LeadsToolbar({
  search,
  onSearch,
  ask,
  onAsk,
  askTerm,
  onAskSubmit,
  leads,
  chosenColumns,
  onColumns,
  exportStatus,
  onExport,
  mayExport,
  exportRefusal,
  exportNote,
  askExample,
  filtersOpen,
  onFiltersOpen,
  filtersInUse,
  filtersPanelIds,
}: {
  search: string;
  onSearch: (value: string) => void;
  ask: string;
  onAsk: (value: string) => void;
  askTerm: string;
  onAskSubmit: () => void;
  leads: { data: LeadList | undefined; error: unknown };
  chosenColumns: string[] | undefined;
  onColumns: (columns: string[] | undefined) => void;
  /** The export's state, from the screen's `useActionFeedback`. */
  exportStatus: FeedbackStatus;
  onExport: () => void;
  mayExport: boolean;
  /**
   * WHY THE EXPORT IS REFUSED, or `null`. Derived once by the screen
   * (`leadsTable.exportRefusal`) because the SAME sentence is rendered twice: here on the
   * control, and on the screen in a `RestrictionNote` — a disabled button's `title` is
   * unreachable by keyboard and on touch, so it cannot be the only place the reason lives
   * (UX-DOCTRINE §4).
   */
  exportRefusal: string | null;
  /** What the file holds, in a sentence — behind the ⓘ beside the button. */
  exportNote: string;
  /** A request in this business's own words, for the search placeholder. */
  askExample: string;
  /** Whether the phone's folded panel is open. Ignored from `sm`, where it always is. */
  filtersOpen: boolean;
  onFiltersOpen: (open: boolean) => void;
  /** Filters narrowing the rows that live inside the panel (not stage, which stays out). */
  filtersInUse: number;
  /** Space-separated ids of every region the button shows, for `aria-controls`. */
  filtersPanelIds: string;
}) {
  const [panelId] = filtersPanelIds.split(" ");
  return (
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1 sm:w-56 sm:flex-none">
          {/* The lens debounces what reaches the API (`useLeadsLens`), so every keystroke
              goes to it. The API caps `search` at 60 characters and 422s beyond it. */}
          <SearchField
            label="Search leads"
            hideLabel
            value={search}
            onValueChange={onSearch}
            maxLength={60}
            placeholder="Name or last digits"
            slashToFocus
          />
        </div>

        <button
          type="button"
          aria-expanded={filtersOpen}
          aria-controls={filtersPanelIds}
          onClick={() => onFiltersOpen(!filtersOpen)}
          className={`${SECONDARY_BUTTON} shrink-0 aria-expanded:bg-ink/[0.06] sm:hidden`}
        >
          <SlidersHorizontal aria-hidden className="h-3.5 w-3.5" />
          Filters
          {filtersInUse > 0 ? <span className="tabular-nums text-ink-muted">· {filtersInUse}</span> : null}
        </button>

        <div
          id={panelId}
          className={`${filtersOpen ? "flex" : "hidden"} w-full flex-wrap items-center gap-2 sm:flex sm:w-auto sm:flex-1`}
        >

        {/* THE QUESTION BOX (D-504). A FORM, not a debounced input, and the difference is
            money: each submission buys one embedding against this account's AI ceiling,
            so it fires when the person says so. `type="search"` gives the browser's own
            clear affordance, and clearing it returns the table to the ordinary filtered
            list because `askTerm` is what the lens reads. */}
        <form
          className="relative w-full sm:w-auto sm:min-w-[18rem] sm:flex-1 lg:max-w-md"
          /* See `SavedViewBar`: the browser never refuses a form on a client screen,
             including the ones with no rule for it to refuse on. */
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            onAskSubmit();
          }}
        >
          <input
            type="search"
            value={ask}
            // Clearing the box clears the search. Anything else leaves a person
            // looking at ranked rows with an empty box and no way to explain them.
            onChange={(e) => onAsk(e.target.value)}
            maxLength={2000}
            aria-label="Find leads by what they asked for"
            placeholder={`What did they ask for? e.g. ${askExample}`}
            className={`${FIELD_INLINE} w-full`}
          />
        </form>

        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
        {/* The COLUMN CHOOSER. It sits beside Export rather than above the table on
            purpose: it decides what the table shows AND what the file contains, and a
            control that changes the download belongs next to the download. */}
        <ColumnChooser
          available={leads.data?.available_columns}
          chosen={chosenColumns}
          onChange={onColumns}
          unavailableReason={
            leads.error
              ? "Couldn't load columns. Reload to try again."
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
        {/* The button and its ⓘ wrap as one unit, so the ⓘ never sits alone on a line. */}
        <span className="inline-flex items-center gap-1">
        <ActionButton
          variant="secondary-sm"
          status={exportStatus}
          pendingLabel="Preparing…"
          successLabel="Downloaded"
          disabled={!mayExport || Boolean(askTerm)}
          onClick={onExport}
          title={
            // The refusal when there is one, in the server's own terms where the server
            // owns the wording — "Only an account owner can export leads." for a role
            // that lacks it, "We could not check…" when `/v1/me` failed, the question
            // sentence when a ranking is on screen. The remaining two cases are not
            // refusals: what the button DOES when it is live, and the wait while the
            // permission answer is still coming.
            exportRefusal ??
            (mayExport
              ? "Downloads these leads with full phone numbers."
              : "Checking you can export…")
          }
        >
          <Download aria-hidden className="h-3.5 w-3.5" />
          Export CSV
        </ActionButton>
        <InfoTip label="the CSV export" align="end">
          <p>{exportNote}</p>
        </InfoTip>
        </span>
        </div>

        {/* The refusal sits with the button it explains: a disabled button's `title` is
            unreachable on touch, so the sentence has to be on screen beside it. */}
        {exportRefusal ? (
          <div className="basis-full">
            <RestrictionNote reason={exportRefusal} />
          </div>
        ) : null}
        </div>
      </div>
  );
}

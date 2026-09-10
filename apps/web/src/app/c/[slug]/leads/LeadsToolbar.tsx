"use client";

import { Download, LayoutGrid, List, Search, Sparkles } from "lucide-react";

import { type LeadLens, type LeadList, type useExportLeads } from "@/lib/api/leads";

import { ColumnChooser } from "./ColumnChooser";
import { type ViewMode } from "./leadsTable";

/**
 * FIND, SHAPE, TAKE AWAY — the strip above the table.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). One subject: the controls that decide WHICH
 * rows and WHICH columns, plus the download that takes exactly those away. The export
 * button's gate and its three tooltip states are a compliance surface — `calls:read_raw`
 * is the permission `/v1/leads/export.csv` requires, the refusal is the server's own
 * sentence, and every download is audited — and none of it was reworded in the move.
 */
export function LeadsToolbar({
  search,
  onSearch,
  ask,
  onAsk,
  askTerm,
  onAskSubmit,
  view,
  onView,
  leads,
  chosenColumns,
  onColumns,
  lens,
  exportLeads,
  mayExport,
  exportRefusal,
  onExported,
}: {
  search: string;
  onSearch: (value: string) => void;
  ask: string;
  onAsk: (value: string) => void;
  askTerm: string;
  onAskSubmit: () => void;
  view: ViewMode;
  onView: (mode: ViewMode) => void;
  leads: { data: LeadList | undefined; error: unknown };
  chosenColumns: string[] | undefined;
  onColumns: (columns: string[] | undefined) => void;
  lens: LeadLens;
  exportLeads: ReturnType<typeof useExportLeads>;
  mayExport: boolean;
  /**
   * WHY THE EXPORT IS REFUSED, or `null`. Derived once by the screen
   * (`leadsTable.exportRefusal`) because the SAME sentence is rendered twice: here on the
   * control, and on the screen in a `RestrictionNote` — a disabled button's `title` is
   * unreachable by keyboard and on touch, so it cannot be the only place the reason lives
   * (UX-DOCTRINE §4).
   */
  exportRefusal: string | null;
  onExported: () => void;
}) {
  return (
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            // The API caps `search` at 60 characters and 422s beyond it.
            maxLength={60}
            aria-label="Search leads"
            placeholder="Name or last digits"
            className="w-56 rounded-md border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-ink placeholder:text-ink-faint"
          />
        </div>

        {/* THE QUESTION BOX (D-504). A FORM, not a debounced input, and the difference is
            money: each submission buys one embedding against this account's AI ceiling,
            so it fires when the person says so. `type="search"` gives the browser's own
            clear affordance, and clearing it returns the table to the ordinary filtered
            list because `askTerm` is what the lens reads. */}
        <form
          className="relative"
          /* See `SavedViewBar`: the browser never refuses a form on a client screen,
             including the ones with no rule for it to refuse on. */
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            onAskSubmit();
          }}
        >
          <Sparkles className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="search"
            value={ask}
            // Clearing the box clears the search. Anything else leaves a person
            // looking at ranked rows with an empty box and no way to explain them.
            onChange={(e) => onAsk(e.target.value)}
            maxLength={2000}
            aria-label="Find leads by what they asked for"
            placeholder="What did they ask for? e.g. 3BHK in Gachibowli"
            className="w-72 rounded-md border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-ink placeholder:text-ink-faint"
          />
        </form>

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
                onClick={() => onView(mode)}
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
          onChange={onColumns}
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
          disabled={exportLeads.isPending || !mayExport || Boolean(askTerm)}
          onClick={() =>
            // WITHOUT `ask`. The API refuses a lens carrying a question on the export
            // (`_ASK_CANNOT_BE_EXPORTED`): a ranking is not "the whole filtered set" the
            // file promises. The button is disabled with that sentence above, so this
            // strip is the belt — a lens that reached the mutation with a question would
            // otherwise be a 422 on a control we had already said was available.
            exportLeads.mutate({ ...lens, ask: undefined }, {
              onSuccess: onExported,
            })
          }
          title={
            // The refusal when there is one, in the server's own terms where the server
            // owns the wording — "Only an account owner can export leads." for a role
            // that lacks it, "We could not check…" when `/v1/me` failed, the question
            // sentence when a ranking is on screen. The remaining two cases are not
            // refusals: what the button DOES when it is live, and the wait while the
            // permission answer is still coming.
            exportRefusal ??
            (mayExport
              ? "Downloads the leads and the columns shown here, with full phone numbers."
              : "Checking whether you can export these leads…")
          }
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
        >
          <Download className="h-3.5 w-3.5" />
          {exportLeads.isPending ? "Preparing…" : "Export this view as CSV"}
        </button>
      </div>
  );
}

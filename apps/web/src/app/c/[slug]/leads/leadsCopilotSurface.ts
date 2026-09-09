"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { type LeadColumn, type LeadStatus } from "@/lib/api/leads";

import { STATUSES } from "./StatusSelect";
import { PAGE_SIZE, type ViewMode } from "./leadsTable";

/**
 * WHAT THE SCREEN ASSISTANT IS TOLD ABOUT THE LEADS TABLE.
 *
 * Extracted from `LeadsScreen.tsx` (UX-DOCTRINE §6). It is a REDACTION boundary as much
 * as a declaration — nothing about a ROW is declared, and the search box leaves as
 * «PRIVATE_1» (D-127 G-2) — so keeping it in one file is what makes that boundary
 * reviewable. The argument for every field and fact below travels with it.
 *
 * A screen gets exactly ONE surface (`lib/copilot/registry.ts` makes the innermost
 * registration the live one), so this hook is called once, by the screen.
 */
export function useLeadsCopilotSurface({
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
}: {
  status: string | undefined;
  setStatus: (value: string | undefined) => void;
  view: ViewMode;
  setView: (value: ViewMode) => void;
  search: string;
  leads: { data: unknown; error: unknown };
  items: unknown[];
  offset: number;
  exportTotal: number | null;
  stageCount: (stage: LeadStatus) => number | undefined;
  columns: LeadColumn[];
  facetValues: Record<string, string[]>;
  assignedTo: string | undefined;
  selection: { ids: string[]; wholeQuery: boolean };
  readOnly: boolean;
  activeViewId: string | undefined;
}): void {
  /*
   * THE LEADS TABLE, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## Not one lead
   *
   * This is the densest personal data in the client console — every row is a named person
   * and an E.164 — so nothing about a ROW is declared: no name, no number, no captured
   * field value, not even the assignee's name. What the assistant is told is the SHAPE of
   * what the reader is looking at: which filters are on, how many rows the server matched,
   * how the pipeline is distributed, and which columns are showing. That is what makes
   * "why does my hot column look empty" answerable, and it identifies nobody.
   *
   * ## The search box is `personal`, and it is not writable
   *
   * A person searching this table types a customer's name or number into it, which is why
   * it carries `personal: "text"` and leaves as `«PRIVATE_1»` (D-127 G-2) rather than as
   * itself. It is `writable: false` for the other half of the same reason: an assistant
   * that cannot see the term has no business inventing one, and a filled search silently
   * changes which rows a person then acts on in bulk.
   *
   * The FACET selection is declared by its KEYS only. A facet value is an extracted field
   * off a real call and can be anything a caller said; the keys are the client's own
   * schema, which is already the vocabulary the extraction screen sends.
   */
  useCopilotSurface({
    route: "/c/{slug}/leads",
    title: "Leads",
    realm: "client",
    fields: [
      {
        id: "leads-status",
        label: "Show only leads at this stage",
        type: "select",
        value: status ?? "",
        options: [
          { value: "", label: "Every stage" },
          ...STATUSES.map((stage) => ({ value: stage, label: stage })),
        ],
        help: "A server-side filter over the whole account, not a slice of this page.",
      },
      {
        id: "leads-view",
        label: "How the leads are laid out",
        type: "select",
        value: view,
        options: [
          { value: "list", label: "Table" },
          { value: "board", label: "Board (one column per stage)" },
        ],
      },
      {
        id: "leads-search",
        label: "Search",
        type: "text",
        value: search,
        writable: false,
        personal: "text",
        help: "What the reader typed. It usually names a customer, so the assistant is told there is a search rather than what it says.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: leads.data
          ? "the table below has loaded"
          : leads.error
            ? "the leads failed to load, so no row is listed"
            : "still loading",
      },
      { key: "rows_on_page", label: "Lead rows on this page", value: String(items.length) },
      { key: "page_size", label: "Rows per page", value: String(PAGE_SIZE) },
      { key: "page_offset", label: "Rows skipped before this page", value: String(offset) },
      {
        key: "total_matching",
        label: "Leads the current filters match, across every page",
        value: exportTotal === null ? "not known yet" : String(exportTotal),
      },
      {
        key: "stage_counts",
        label: "Leads per stage, matching the search (not the stage chip)",
        value:
          STATUSES.map((stage) => `${stage}: ${stageCount(stage) ?? "not stated"}`).join(", "),
      },
      { key: "columns_shown", label: "Columns in the table", value: String(columns.length) },
      {
        key: "facets_in_effect",
        label: "Captured fields being filtered on (their names, not the values chosen)",
        value: Object.keys(facetValues).length === 0 ? "none" : Object.keys(facetValues).join(", "),
      },
      {
        key: "assigned_filter",
        label: "Is the list narrowed to one owner?",
        value: assignedTo === undefined ? "no" : "yes, to one team member",
      },
      {
        key: "selection",
        label: "Rows ticked for a bulk action",
        value: selection.wholeQuery
          ? "every lead the filters match"
          : String(selection.ids.length),
      },
      {
        key: "editable",
        label: "May this session change a lead?",
        value: readOnly ? "no — the stage and owner controls are disabled" : "yes",
      },
      {
        key: "saved_view",
        label: "Is a saved view applied?",
        value: activeViewId === undefined ? "no" : "yes",
      },
    ],
    apply: (items_) => {
      for (const item of items_) {
        const text = asText(item.value);
        if (item.field_id === "leads-status") {
          if (text === "") setStatus(undefined);
          else if (STATUSES.some((stage) => stage === text)) setStatus(text);
        } else if (item.field_id === "leads-view" && (text === "list" || text === "board")) {
          setView(text);
        }
      }
    },
  });
}

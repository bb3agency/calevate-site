"use client";

import { useMemo } from "react";

import { Card, EmptyState, SECONDARY_BUTTON_SM, formatPhone } from "@/components/ui";
import { RowMenu } from "@/components/console/rowMenu";
import { copyText } from "@/components/interior/copy-button";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import type { Lead } from "@/lib/api/leads";

import { cellClass, sortFor } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * THE LEADS TABLE — every lead an agent captured, one row each.
 *
 * The data columns are the SERVER's resolved list in the server's order — the same list
 * `export.csv` writes its header from — so the screen and the file cannot hold different
 * columns. Headers sort the rows on this page; `partialNote` says so when the filter
 * matches more than one page. Loading and failure are given once by the screen, so this
 * only ever receives rows the server sent.
 */
export function LeadTable({ kit, partialNote }: { kit: LeadRowKit; partialNote?: string }) {
  const {
    items, columns, canCall, maySelect, ticked, allOfPageTicked,
    toggleRow, toggleAllOnPage, renderCell, rowFailure, callCell,
    filtered, askTerm, onClearFilters, hrefFor, callHref,
  } = kit;

  const tableColumns = useMemo(() => {
    const out: DataColumn<Lead>[] = [];
    // THE HEADER CHECKBOX IS PAGE-SCOPED and says so; extending to the whole filtered
    // query is a separate, named act on the bulk bar (PatternFly, Helios).
    if (maySelect) {
      out.push({
        id: "select",
        header: "Select",
        className: "w-8",
        renderHeader: () => (
          <input
            type="checkbox"
            aria-label="Select all leads on this page"
            checked={allOfPageTicked}
            onChange={toggleAllOnPage}
          />
        ),
        cell: (lead) => (
          <input
            type="checkbox"
            // Names the LEAD: a hundred boxes called "select" cannot be told apart.
            aria-label={`Select ${lead.name ?? lead.phone_e164}`}
            checked={ticked.has(lead.id)}
            onChange={() => toggleRow(lead.id)}
          />
        ),
      });
    }
    columns.forEach((column, index) =>
      out.push({
        id: column.key,
        header: column.label,
        className: cellClass(column),
        sort: sortFor(column),
        cell: (lead) => (
          <>
            {renderCell(column, lead)}
            {/* Once per row, in its first data cell — see `rowFailure`. */}
            {index === 0 && rowFailure(lead)}
          </>
        ),
      }),
    );
    if (canCall) out.push({ id: "call", header: "Call", cell: (lead) => callCell(lead) });
    // The row's secondary actions, so the row itself stays one target (its name link).
    out.push({
      id: "more",
      header: "More",
      renderHeader: () => null,
      className: "w-10 text-right",
      cell: (lead) => (
        <RowMenu
          label={lead.name ?? formatPhone(lead.phone_e164)}
          items={[
            { id: "open", label: "Open lead", href: hrefFor(lead) },
            ...(lead.last_call_id
              ? [{ id: "call", label: "Open the last call", href: callHref(lead.last_call_id) }]
              : []),
            { id: "copy", label: "Copy phone number", onSelect: () => void copyText(lead.phone_e164) },
          ]}
        />
      ),
    });
    return out;
  }, [maySelect, columns, canCall, allOfPageTicked, toggleAllOnPage, ticked, toggleRow, renderCell, rowFailure, callCell, hrefFor, callHref]);

  return (
    <Card bodyClassName="p-1 sm:p-2">
      {items.length ? (
        <DataTable
          rows={items}
          columns={tableColumns}
          getRowId={(lead) => lead.id}
          label="Leads"
          partialNote={partialNote}
          // A ticked row stays tinted so the selection is legible away from the checkbox.
          rowClassName={(lead) => (ticked.has(lead.id) ? "bg-brand-soft/50" : "")}
        />
      ) : (
        /* "No leads yet" only where the server said so; with a filter on, the emptiness
           belongs to the filter (`filtered` is one answer over the whole lens). */
        <EmptyState
          title={
            askTerm
              ? "No lead's captured answers match that question"
              : filtered
                ? "No leads match these filters"
                : "No leads yet"
          }
          hint={
            filtered
              ? "Clear the filters to see everything."
              : "Every answered call becomes a lead within two minutes."
          }
          action={
            filtered && (
              <button type="button" onClick={onClearFilters} className={SECONDARY_BUTTON_SM}>
                Clear the filters
              </button>
            )
          }
        />
      )}
    </Card>
  );
}

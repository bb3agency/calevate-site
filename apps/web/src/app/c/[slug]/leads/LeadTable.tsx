"use client";

import { useMemo } from "react";

import { formatPhone } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { RowMenu } from "@/components/arc/menu";
import { copyText } from "@/components/interior/copy-button";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import type { Lead } from "@/lib/api/leads";
import { useMediaQuery } from "@/lib/useMediaQuery";

import { LeadsPhoneList } from "./LeadsPhoneList";
import { cellClass, sortFor } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/** Below `sm` the leads are a swipeable list, not a table (different markup, so a query). */
const PHONE = "(max-width: 639px)";

/**
 * THE LEADS TABLE — every lead an agent captured, one row each.
 *
 * The data columns are the SERVER's resolved list in the server's order — the same list
 * `export.csv` writes its header from — so the screen and the file cannot hold different
 * columns. Headers sort the rows on this page; `partialNote` says so when the filter
 * matches more than one page. Loading and failure are given once by the screen, so this
 * only ever receives rows the server sent.
 *
 * On a phone the same leads are a list (`LeadsPhoneList`) whose rows swipe to their
 * follow-up actions: a table there scrolls sideways under the thumb, which a swipe cannot
 * share. The ⋯ menu carries the same actions wherever there is a mouse or a keyboard.
 */
export function LeadTable({ kit, partialNote }: { kit: LeadRowKit; partialNote?: string }) {
  const {
    items, columns, canCall, maySelect, ticked, setTicked,
    renderCell, rowFailure, callCell,
    filtered, askTerm, onClearFilters, hrefFor, callHref, followUp, targetOf,
  } = kit;
  const phone = useMediaQuery(PHONE);

  const tableColumns = useMemo(() => {
    const out: DataColumn<Lead>[] = [];
    columns.forEach((column, index) =>
      out.push({
        id: column.key,
        header: column.label,
        className: cellClass(column),
        // Who the row is stays in view while the rest scrolls sideways.
        pin: column.key === "name" ? "left-0" : undefined,
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
            ...followUp.menuItems(targetOf(lead)),
            { id: "open", label: "Open lead", href: hrefFor(lead), separated: true },
            ...(lead.last_call_id
              ? [{ id: "last-call", label: "Open the last call", href: callHref(lead.last_call_id) }]
              : []),
            { id: "copy", label: "Copy phone number", onSelect: () => void copyText(lead.phone_e164) },
          ]}
        />
      ),
    });
    return out;
  }, [columns, canCall, renderCell, rowFailure, callCell, hrefFor, callHref, followUp, targetOf]);

  return (
    // On the white ground between two hairlines, as the call log is (REDESIGN-2): a table
    // is a list, and a card around it is chrome a reader has to look past.
    <div className="border-y border-line max-sm:-mx-4">
      {items.length && phone ? (
        <LeadsPhoneList kit={kit} />
      ) : items.length ? (
        <DataTable
          rows={items}
          columns={tableColumns}
          getRowId={(lead) => lead.id}
          label="Leads"
          partialNote={partialNote}
          // THE HEADER CHECKBOX IS PAGE-SCOPED; extending to the whole filtered query is a
          // separate, named act on the bulk bar (PatternFly, Helios).
          selection={
            maySelect
              ? {
                  selected: ticked,
                  onChange: setTicked,
                  // Names the LEAD: a hundred boxes called "select" cannot be told apart.
                  rowLabel: (lead) => `Select ${lead.name ?? lead.phone_e164}`,
                  allLabel: "Select all leads on this page",
                }
              : undefined
          }
          // Said aloud only for what a person would turn round for (D-774); every other
          // arrival is visible, not spoken.
          announceArrivals={(arrived) => {
            const hot = arrived.filter((lead) => lead.status === "hot").length;
            if (hot === 0) return null;
            return hot === 1 ? "A new hot lead arrived." : `${hot} new hot leads arrived.`;
          }}
        />
      ) : filtered || askTerm ? (
        /* With a filter on, the emptiness belongs to the filter (`filtered` is one answer
           over the whole lens), never to the business. */
        <EmptyState
          variant="filtered"
          message={askTerm ? "No answers match that question" : "No leads match these filters"}
          onClear={filtered ? onClearFilters : undefined}
          clearLabel="Clear the filters"
        />
      ) : (
        <EmptyState
          illustration={<EmptySketch kind="leads" />}
          message="No leads yet"
          hint="Each answered call becomes a lead."
        />
      )}
    </div>
  );
}

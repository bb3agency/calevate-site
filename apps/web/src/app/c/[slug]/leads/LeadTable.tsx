"use client";

import { Card, EmptyState, SECONDARY_BUTTON_SM, ScrollRegion } from "@/components/ui";

import { BODY_CELL, HEAD_CELL, cellClass } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * THE LEADS TABLE — every lead an agent captured, one row each.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). Loading and failure are NOT here: they are
 * the same answer in both views and are given once by the screen, so this component is
 * only ever handed rows the server actually sent.
 */
export function LeadTable({ kit }: { kit: LeadRowKit }) {
  const {
    items, columns, canCall, maySelect, ticked, allOfPageTicked,
    toggleRow, toggleAllOnPage, renderCell, rowFailure, callCell,
    status, searchTerm, askTerm, onClearFilters,
  } = kit;
  return (
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
                          onChange={toggleAllOnPage}
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
              title={
              askTerm
                ? "No lead's captured answers match that question"
                : status || searchTerm
                  ? "No leads match this filter"
                  : "No leads yet"
            }
              hint={
                status || searchTerm
                  ? "Clear the filter to see everything."
                  : "Every answered call becomes a lead within two minutes."
              }
              /* The sentence used to NAME the action without offering it — the dead-end
                 shape ux-audit F-18 flags. Only the filtered case gets a button: an
                 account with genuinely no leads has nothing to clear. */
              action={
                (status || searchTerm) && (
                  <button
                    type="button"
                    onClick={onClearFilters}
                    className={SECONDARY_BUTTON_SM}
                  >
                    Clear the filters
                  </button>
                )
              }
            />
          )}
        </Card>
  );
}

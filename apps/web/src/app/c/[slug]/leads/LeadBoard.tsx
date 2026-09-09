"use client";

import Link from "next/link";
import { ScrollRegion, StatusBadge, formatCount, formatIST } from "@/components/ui";

import { STATUSES } from "./StatusSelect";
import { INLINE_EDIT } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * THE PIPELINE BOARD — the same leads, one column per stage.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). The reasoning that governs the counts is
 * kept with the markup below.
 */
export function LeadBoard({ kit }: { kit: LeadRowKit }) {
  const {
    items, canCall, stageCount, statusCell, ownerCell, rowFailure, callCell, hrefFor,
  } = kit;
  return (
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
                        <p
                          title={lead.name ?? lead.phone_e164}
                          className="truncate text-sm font-semibold text-ink"
                        >
                          {/* The list of leads without a captured name is long; the
                              phone number is the next-best stable identifier. */}
                          <Link
                            href={hrefFor(lead)}
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
                        {statusCell(
                          lead,
                          `mt-1.5 w-full ${INLINE_EDIT} border-line capitalize`,
                        )}
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
  );
}

"use client";

import { StatusBadge, formatCount } from "@/components/ui";
import { Pagination } from "@/components/interior/pagination";
import { type LeadList, type LeadStatus } from "@/lib/api/leads";

import { STATUSES } from "./StatusSelect";
import { PAGE_SIZE } from "./leadsTable";

/**
 * WHAT YOU ARE LOOKING AT, AND HOW TO REACH THE REST — the tally and the pager.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). Both render only from a response that
 * arrived: a failed read draws no pager and states no count (§52).
 */
export function LeadsFooter({
  leads,
  items,
  offset,
  status,
  searchTerm,
  stageCount,
  onOffsetChange,
}: {
  leads: { data: LeadList | undefined };
  items: unknown[];
  offset: number;
  status: string | undefined;
  searchTerm: string;
  stageCount: (stage: LeadStatus) => number | undefined;
  onOffsetChange: (offset: number) => void;
}) {
  return (
    <>
      {/* The stage tally, from `status_counts_matching_search` — the server's numbers
          over the server's scope. It used to count the rows ON SCREEN, which under a
          status chip printed five confident zeroes about stages the client demonstrably
          had leads in. Both scopes are stated, because they differ: the denominator
          obeys every filter, the badges obey the search only. */}
      {leads.data && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 text-xs text-ink-muted">
          <span>
            Showing{" "}
            <span className="font-semibold tabular-nums text-ink">
              {leads.data.total > PAGE_SIZE && items.length > 0
                ? `${formatCount(offset + 1)}–${formatCount(offset + items.length)}`
                : formatCount(items.length)}
            </span>{" "}
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

      {/* The way past row 100 (ux-audit L1). Rendered only off the SERVER's total — a
          failed read draws no pager, and one page draws none either. Numbered pages
          rather than load-more because a CRM table is revisited by position ("they were
          on page 3") and both views share the one offset. */}
      {leads.data && leads.data.total > PAGE_SIZE && (
        <div className="flex justify-center">
          <Pagination
            count={Math.ceil(leads.data.total / PAGE_SIZE)}
            page={Math.floor(offset / PAGE_SIZE) + 1}
            onPageChange={(page) => onOffsetChange((page - 1) * PAGE_SIZE)}
            label="Lead pages"
          />
        </div>
      )}
    </>
  );
}

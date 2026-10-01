"use client";

import { formatCount } from "@/components/ui";
import { Pagination } from "@/components/interior/pagination";
import { type LeadLens, type LeadList } from "@/lib/api/leads";

import { PAGE_SIZE } from "./leadsTable";

/**
 * WHERE YOU ARE IN THE LIST, AND HOW TO REACH THE REST. Both render only from a response
 * that arrived: a failed read states no count and draws no pager (§52). The per-stage
 * counts that used to sit here are on the stage filter itself, beside the stage they
 * count.
 */
export function LeadsFooter({
  leads,
  items,
  offset,
  lens,
  onOffsetChange,
}: {
  leads: { data: LeadList | undefined };
  items: unknown[];
  offset: number;
  lens: LeadLens;
  onOffsetChange: (offset: number) => void;
}) {
  if (!leads.data) return null;
  const { total } = leads.data;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-[13px] text-ink-muted">
        Showing{" "}
        <span className="font-semibold tabular-nums text-ink">
          {total > PAGE_SIZE && items.length > 0
            ? `${formatCount(offset + 1)}–${formatCount(offset + items.length)}`
            : formatCount(items.length)}
        </span>{" "}
        of {formatCount(total)}
        {lens.status ? ` ${lens.status}` : ""} {total === 1 ? "lead" : "leads"}
      </p>
      {/* The way past row 100 (ux-audit L1). Numbered pages rather than load-more: a CRM
          table is revisited by position ("they were on page 3"). */}
      {total > PAGE_SIZE && (
        <Pagination
          count={Math.ceil(total / PAGE_SIZE)}
          page={Math.floor(offset / PAGE_SIZE) + 1}
          onPageChange={(page) => onOffsetChange((page - 1) * PAGE_SIZE)}
          label="Lead pages"
        />
      )}
    </div>
  );
}

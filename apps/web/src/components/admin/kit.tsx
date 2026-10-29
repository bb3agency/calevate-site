import type { ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";

import { SECONDARY_BUTTON_SM, formatCount } from "@/components/ui";

export { MetricRow } from "@/components/console/metric";
export { StatusPill } from "@/components/console/statusPill";

/**
 * THE ADMIN CONSOLE'S SLICE OF THE CALM SYSTEM (docs/design/REDESIGN-2.md, "Design Read
 * and system"). Same system as the client console, at density 6 rather than 5: operators
 * read these screens all day, so lists carry one more column and rows sit a little closer,
 * but nothing else changes — ink on white, hairlines instead of boxes, one filled green
 * action per view, reasons behind an ⓘ.
 *
 * The client console owns the shared kit (`components/console/`). `StatusPill` and
 * `MetricRow` are used by both consoles, so they live there and are re-exported here; the
 * rest are admin-only until the client console needs them.
 *
 * - Page widths: `ADMIN_PAGE` for a settings page (label–value rows, forms), and
 *   `ADMIN_PAGE_WIDE` for a page whose subject is a list. Sections stack `space-y-10`.
 * - Lists: `HAIRLINE_LIST` (a hairline above and below, hairlines between rows). Never a
 *   rounded card around a list.
 * - Column labels over a list: `LIST_HEAD`.
 * - A row's state: `StatusPill` (soft tone, no border), the same shape as the client
 *   console's call and lead badges.
 * - Figures across the top of a page: `MetricRow` around `console/metric` `Metric`s.
 */

/** A page whose subject is settings or one record. */
export const ADMIN_PAGE = "max-w-3xl space-y-10 pb-12";

/** A page whose subject is a list or a board. */
export const ADMIN_PAGE_WIDE = "max-w-5xl space-y-10 pb-12";

/** A list between hairlines. Rows inside it pad themselves (`py-3`). */
export const HAIRLINE_LIST = "divide-y divide-line border-y border-line";

/** The column labels above a list: visual only, so pass `aria-hidden` when each cell names itself. */
export const LIST_HEAD = "text-meta font-medium text-ink-muted";

/** A list row's hover wash, the same 3% ink the chooser uses. */
export const ROW_HOVER = "transition-colors duration-(--duration-fast) hover:bg-ink/[0.03]";

/** `snake_case` wire values as words: "self_serve" → "Self serve". */
export function sentenceCase(value: string): string {
  const words = value.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A SAVE, ACKNOWLEDGED WHERE IT HAPPENED (founder, 10 Oct 2026): a small tick and the
 * server's own sentence about what changed, next to the control that saved it. Not a toast
 * (gone before it is read, and far from the field) and not a green box (a box reads as an
 * event bigger than a saved setting). `role="status"` so it is announced without moving
 * focus.
 */
export function SavedNote({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <p role="status" className={`flex items-start gap-1.5 text-meta text-ink-muted ${className}`}>
      <Check aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-strong" />
      <span>{children ?? "Saved"}</span>
    </p>
  );
}

/**
 * THE ROWS OF A SERVER-PAGED LIST, MARKED WHILE THE NEXT ANSWER IS IN FLIGHT.
 *
 * Paged admin lists keep the previous page on screen while the next loads
 * (`placeholderData`), so a page turn or a search never blanks the table. Without a mark,
 * nothing on screen moves for the length of the request and the old rows read as the
 * answer to the new question. `busy` dims them and sets `aria-busy`, which tells assistive
 * technology the region is about to change.
 */
export function PagedRows({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <div
      aria-busy={busy || undefined}
      className={`transition-opacity duration-(--duration-fast) ${busy ? "opacity-60" : ""}`}
    >
      {children}
    </div>
  );
}

/**
 * "Showing 26–50 of 312" with Previous and Next, for an offset-paged admin list.
 *
 * While the next page loads (`busy`) the line says so — it is a polite live region, so the
 * change is announced — and both buttons are disabled, so a second click cannot step past
 * a page whose rows have not arrived.
 */
export function OffsetPager({
  offset,
  shown,
  total,
  pageSize,
  busy,
  onOffset,
  previousLabel = "Previous",
  nextLabel = "Next",
}: {
  offset: number;
  shown: number;
  total: number;
  pageSize: number;
  busy: boolean;
  onOffset: (next: number) => void;
  previousLabel?: string;
  nextLabel?: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-meta text-ink-muted">
      <span aria-live="polite">
        {busy
          ? "Loading…"
          : `Showing ${formatCount(offset + 1)}–${formatCount(offset + shown)} of ${formatCount(total)}`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={busy || offset === 0}
          onClick={() => onOffset(Math.max(0, offset - pageSize))}
        >
          <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
          {previousLabel}
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={busy || offset + shown >= total}
          onClick={() => onOffset(offset + pageSize)}
        >
          {nextLabel}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

"use client";

/**
 * The bar above a list (calls, leads, campaigns, admin tables): search, the filters, the
 * list's own tools, and — under them — which filters are on, how many rows that leaves, and
 * one way to clear them all.
 *
 * Adapted from uiarc's `filter-toolbar` (MIT, see ./LICENSE) as a LAYOUT with slots rather
 * than a filter engine: each screen keeps its own filter state and controls (`FilterChip`,
 * a select, the leads facet panel) and passes them in, so filtering logic stays where the
 * query is built. What this owns is the shape the leads toolbar already proved on a phone:
 * the filters fold behind one "Filters · n" button below `sm`, search stays visible, and
 * every chip of an active filter can be removed on its own.
 */

import { useId, useState, type ReactNode } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import clsx from "clsx";

import { SECONDARY_BUTTON, formatCount } from "@/components/ui";

export type ActiveFilter = {
  id: string;
  /** "Status: Hot", "Agent: Reception". */
  label: string;
  onRemove: () => void;
};

export type FilterToolbarProps = {
  /** The search control (the kit's `SearchField`). Always visible. */
  search?: ReactNode;
  /** The filter controls. Folded behind one button on a phone. */
  filters?: ReactNode;
  /** The list's own tools on the right: columns, export, a view switch. */
  tools?: ReactNode;
  /** Every filter now narrowing the list, each removable. */
  active?: ActiveFilter[];
  onClearAll?: () => void;
  /** Rows shown and rows matching, and what a row is ("lead"). `total` undefined while unknown. */
  count?: { shown: number; total?: number; noun: string; nounPlural?: string };
  filtersLabel?: string;
  clearAllLabel?: string;
  /** Names the list of filters in use. */
  activeLabel?: string;
  removeLabel?: (filter: ActiveFilter) => string;
  className?: string;
};

function countSentence({ shown, total, noun, nounPlural }: NonNullable<FilterToolbarProps["count"]>): string {
  const plural = nounPlural ?? `${noun}s`;
  if (total === undefined || total === shown) return `${formatCount(shown)} ${shown === 1 ? noun : plural}`;
  return `${formatCount(shown)} of ${formatCount(total)} ${total === 1 ? noun : plural}`;
}

export function FilterToolbar({
  search,
  filters,
  tools,
  active = [],
  onClearAll,
  count,
  filtersLabel = "Filters",
  clearAllLabel = "Clear all",
  activeLabel = "Filters in use",
  removeLabel = (filter) => `Remove filter ${filter.label}`,
  className,
}: FilterToolbarProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const summary = active.length > 0 || count;

  return (
    <div className={clsx("space-y-2", className)}>
      <div className="flex flex-wrap items-center gap-2">
        {search ? <div className="min-w-0 flex-1 sm:flex-none">{search}</div> : null}
        {filters ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((was) => !was)}
            className={clsx(SECONDARY_BUTTON, "shrink-0 aria-expanded:bg-ink/[0.06] sm:hidden")}
          >
            <SlidersHorizontal aria-hidden className="h-3.5 w-3.5" />
            {filtersLabel}
            {active.length > 0 ? <span className="tabular-nums text-ink-muted">· {active.length}</span> : null}
          </button>
        ) : null}
        {filters ? (
          <div
            id={panelId}
            className={clsx(open ? "flex" : "hidden", "w-full min-w-0 flex-wrap items-center gap-2 sm:flex sm:w-auto sm:flex-1")}
          >
            {filters}
          </div>
        ) : null}
        {tools ? <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">{tools}</div> : null}
      </div>

      {summary ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-meta text-ink-muted">
          {count ? (
            <p role="status" className="tabular-nums">
              {countSentence(count)}
            </p>
          ) : null}
          {active.length > 0 ? (
            <ul className="flex flex-wrap items-center gap-1.5" aria-label={activeLabel}>
              {active.map((filter) => (
                <li key={filter.id}>
                  <button
                    type="button"
                    onClick={filter.onRemove}
                    aria-label={removeLabel(filter)}
                    className="press inline-flex min-h-7 items-center gap-1 rounded-full border border-line bg-surface pl-2.5 pr-1.5 text-meta font-medium text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                  >
                    {filter.label}
                    <X aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {active.length > 1 && onClearAll ? (
            <button
              type="button"
              onClick={onClearAll}
              className="press inline-flex min-h-7 items-center rounded-md px-1.5 text-meta font-medium text-brand-strong hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
            >
              {clearAllLabel}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export type SelectionBarProps = {
  /** How many rows are chosen. Renders nothing at 0. */
  count: number;
  /** What a row is: "lead". */
  noun: string;
  nounPlural?: string;
  /** The bulk actions (kit `ActionButton`s, each with its own feedback). */
  children: ReactNode;
  onClear: () => void;
  clearLabel?: string;
};

/**
 * What a `DataTable` selection can do: "3 leads selected", the bulk actions, and a way out.
 * It sticks to the bottom of the scrolling page so the actions stay in reach of a thumb
 * while the reader keeps choosing rows.
 */
export function SelectionBar({
  count,
  noun,
  nounPlural,
  children,
  onClear,
  clearLabel = "Clear selection",
}: SelectionBarProps) {
  if (count === 0) return null;
  const words = `${formatCount(count)} ${count === 1 ? noun : (nounPlural ?? `${noun}s`)} selected`;
  return (
    <div
      role="region"
      aria-label={words}
      className="sticky bottom-0 z-sticky flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom,0px))] shadow-raised sm:rounded-card sm:border sm:pb-2"
    >
      <p role="status" className="mr-auto text-meta font-semibold tabular-nums text-ink">
        {words}
      </p>
      {children}
      <button
        type="button"
        onClick={onClear}
        className="press inline-flex min-h-8 items-center rounded-md px-2 text-meta font-medium text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        {clearLabel}
      </button>
    </div>
  );
}

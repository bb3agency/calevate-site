"use client";

// Sort semantics adapted from interior.dev's sortable-table (github.com/ddoemonn/interior
// @3148000, MIT License, Copyright (c) 2026 ozzy; notice in components/interior/LICENSE):
// the asc → desc → original cycle, empty values last, a numeric-aware collator and
// stable ties. Rebuilt as a real `<table>` rather than an ARIA grid of positioned divs,
// because the consoles' rows wrap, hold controls and change height, which upstream's
// fixed-height absolutely-positioned rows cannot.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { ScrollRegion } from "@/components/ui";

import { FLASH_MS, compareDecimal } from "./valueFlash";

export type SortDirection = "asc" | "desc";
export type SortState = { id: string; direction: SortDirection } | null;

/**
 * How a column orders its rows. `decimal` is for money and other decimal STRINGS and
 * compares them exactly (never as floats, hard rule 7); `time` is an ISO instant.
 */
export type SortKind = "text" | "number" | "decimal" | "time";

export type DataColumn<T> = {
  id: string;
  /** Plain text: it is the column's name for a screen reader and for the sort status. */
  header: string;
  /**
   * A control in place of the header text (a select-all checkbox). The `header` string
   * is still rendered, visually hidden, so the column keeps a name.
   */
  renderHeader?: () => ReactNode;
  cell: (row: T) => ReactNode;
  sort?: {
    value: (row: T) => string | number | null | undefined;
    kind?: SortKind;
    /** Which way the first click sorts — newest-first reads better for a time. */
    first?: SortDirection;
  };
  align?: "left" | "right";
  /** Drop the column below this width; the first column can carry it instead. */
  hideBelow?: "sm" | "md" | "lg";
  /**
   * Keep this column in view while the table scrolls sideways, at this offset from the
   * left edge: `left-0` for the first column, `left-12` for one after a 3rem column.
   */
  pin?: "left-0" | "left-12";
  className?: string;
  /**
   * The raw value this cell shows. When it differs from the previous render for the
   * same row, the cell is marked briefly — a polled value that actually changed.
   */
  flash?: (row: T) => string | null | undefined;
};

const HIDE: Record<NonNullable<DataColumn<unknown>["hideBelow"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
};

/** Opaque, so rows scrolled under a pinned column do not show through it. */
const PIN: Record<NonNullable<DataColumn<unknown>["pin"]>, string> = {
  "left-0": "sticky left-0 z-[1] bg-surface",
  "left-12": "sticky left-12 z-[1] bg-surface",
};

const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

function compareValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
  kind: SortKind,
): number {
  if (kind === "number") return Number(a) - Number(b);
  if (kind === "time") return Date.parse(String(a)) - Date.parse(String(b));
  if (kind === "decimal") {
    const exact = compareDecimal(String(a), String(b));
    if (exact !== null) return exact;
  }
  return collator.compare(String(a), String(b));
}

export function sortRows<T>(rows: T[], columns: DataColumn<T>[], sort: SortState): T[] {
  const column = sort ? columns.find((c) => c.id === sort.id) : undefined;
  if (!sort || !column?.sort) return rows;
  const { value, kind = "text" } = column.sort;
  const sign = sort.direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, v: value(row) }))
    .sort((x, y) => {
      const xEmpty = x.v === null || x.v === undefined || x.v === "";
      const yEmpty = y.v === null || y.v === undefined || y.v === "";
      // Empty values sit last in both directions: a missing duration is not "shortest".
      if (xEmpty || yEmpty) return xEmpty === yEmpty ? x.index - y.index : xEmpty ? 1 : -1;
      return sign * compareValues(x.v, y.v, kind) || x.index - y.index;
    })
    .map((entry) => entry.row);
}

function nextSort<T>(column: DataColumn<T>, current: SortState): SortState {
  const first = column.sort?.first ?? "asc";
  const second: SortDirection = first === "asc" ? "desc" : "asc";
  if (current?.id !== column.id) return { id: column.id, direction: first };
  if (current.direction === first) return { id: column.id, direction: second };
  return null;
}

/**
 * Marks what changed between two renders of the same rows: a row id seen for the first
 * time (after the first render), and any cell whose `flash` value moved. Both clear after
 * `FLASH_MS`. Nothing is marked on the first render, so opening a screen is quiet.
 */
function useChangedKeys<T>(rows: T[], columns: DataColumn<T>[], getRowId: (row: T) => string) {
  const seen = useRef<Map<string, string> | null>(null);
  const [changed, setChanged] = useState<Set<string>>(() => new Set());
  // In a ref, not an effect cleanup: the rows array is rebuilt on every render, so a
  // cleanup would cancel the clearing timer on the very next render.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    const next = new Map<string, string>();
    const marked = new Set<string>();
    for (const row of rows) {
      const id = getRowId(row);
      next.set(id, "");
      if (seen.current && !seen.current.has(id)) marked.add(id);
      for (const column of columns) {
        if (!column.flash) continue;
        const key = `${id}\u0000${column.id}`;
        const value = column.flash(row) ?? "";
        const before = seen.current?.get(key);
        if (before !== undefined && before !== "" && before !== value) marked.add(key);
        next.set(key, value);
      }
    }
    seen.current = next;
    if (marked.size === 0) return;
    setChanged(marked);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setChanged(new Set()), FLASH_MS);
  }, [rows, columns, getRowId]);

  return changed;
}

export type DataTableProps<T> = {
  rows: T[];
  columns: DataColumn<T>[];
  getRowId: (row: T) => string;
  /** The table's caption, read by assistive technology (visually hidden). */
  label: string;
  sort?: SortState;
  defaultSort?: SortState;
  onSortChange?: (sort: SortState) => void;
  /**
   * When the rows are only part of the set (a page, or the loaded part of a log), say so:
   * sorting reorders only what is here, and the note beside an active sort states that.
   */
  partialNote?: string;
  rowClassName?: (row: T) => string;
  className?: string;
};

/**
 * THE CONSOLE'S DATA TABLE. Sortable headers (`aria-sort`, a polite status naming the
 * order), rows that can carry a single link stretched over the row (UX-DOCTRINE §4: one
 * target per row — give the link `after:absolute after:inset-0` and any other control in
 * the row `relative z-[1]`), columns that drop out at narrow widths, and cells that mark
 * themselves when a poll changes their value.
 *
 * Sorting is CLIENT-SIDE over the rows it is given. Where those rows are a page of a
 * server list, pass `partialNote` so the reader is told the order is not the server's.
 */
export function DataTable<T>({
  rows,
  columns,
  getRowId,
  label,
  sort: controlled,
  defaultSort = null,
  onSortChange,
  partialNote,
  rowClassName,
  className = "",
}: DataTableProps<T>) {
  const [internal, setInternal] = useState<SortState>(defaultSort);
  const sort = controlled !== undefined ? controlled : internal;
  const ordered = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);
  const changed = useChangedKeys(rows, columns, getRowId);

  const setSort = (next: SortState) => {
    if (controlled === undefined) setInternal(next);
    onSortChange?.(next);
  };
  const sortedColumn = sort ? columns.find((c) => c.id === sort.id) : undefined;

  return (
    <div className={className}>
      {/* `relative`: absolutely positioned descendants (visually hidden header text, a
          row's stretched link) must take this scroller as their containing block, or they
          escape its clipping and widen the page. */}
      <ScrollRegion label={label} className="scroll-shadow-x relative">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr className="border-b border-line">
              {columns.map((column) => {
                const active = sort?.id === column.id ? sort.direction : null;
                const Icon = active === "asc" ? ArrowUp : active === "desc" ? ArrowDown : ArrowUpDown;
                return (
                  <th
                    key={column.id}
                    scope="col"
                    aria-sort={active === "asc" ? "ascending" : active === "desc" ? "descending" : undefined}
                    className={`whitespace-nowrap px-3 py-2 text-[12px] font-medium text-ink-faint ${
                      column.align === "right" ? "text-right" : ""
                    } ${column.hideBelow ? HIDE[column.hideBelow] : ""} ${column.pin ? PIN[column.pin] : ""}`}
                  >
                    {column.renderHeader ? (
                      <>
                        <span className="sr-only">{column.header}</span>
                        {column.renderHeader()}
                      </>
                    ) : column.sort ? (
                      <button
                        type="button"
                        onClick={() => setSort(nextSort(column, sort))}
                        className={`group inline-flex items-center gap-1 rounded-sm hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 ${
                          active ? "text-ink" : ""
                        } ${column.align === "right" ? "flex-row-reverse" : ""}`}
                      >
                        {column.header}
                        <Icon
                          aria-hidden
                          className={`h-3 w-3 shrink-0 ${active ? "opacity-100" : "opacity-0 group-hover:opacity-60 group-focus-visible:opacity-60"}`}
                        />
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {ordered.map((row) => {
              const id = getRowId(row);
              return (
                <tr
                  key={id}
                  className={`relative transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.025] ${
                    changed.has(id) ? "value-flash" : ""
                  } ${rowClassName?.(row) ?? ""}`}
                >
                  {columns.map((column) => (
                    <td
                      key={column.id}
                      className={`px-3 py-3 align-middle ${column.align === "right" ? "text-right" : ""} ${
                        column.hideBelow ? HIDE[column.hideBelow] : ""
                      } ${column.pin ? PIN[column.pin] : ""} ${column.className ?? ""}`}
                    >
                      {column.flash ? (
                        <span
                          className={`-mx-1 inline-block max-w-full rounded-[4px] px-1 align-middle ${
                            changed.has(`${id}\u0000${column.id}`) ? "value-flash" : ""
                          }`}
                        >
                          {column.cell(row)}
                        </span>
                      ) : (
                        column.cell(row)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>
      {/* The partial note is part of the announcement, not only the visible line: a
          screen-reader user told "sorted by length, descending" over a page of a log would
          otherwise believe they had the longest call of all of them. */}
      <p aria-live="polite" className="sr-only">
        {sort && sortedColumn
          ? `Sorted by ${sortedColumn.header}, ${sort.direction === "asc" ? "ascending" : "descending"}.${
              partialNote ? ` ${partialNote}` : ""
            }`
          : ""}
      </p>
      {sort && partialNote && (
        <p aria-hidden className="px-3 pb-1 pt-2 text-[12px] text-ink-faint">
          {partialNote}
        </p>
      )}
    </div>
  );
}

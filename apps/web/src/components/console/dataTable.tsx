"use client";

// Sort semantics adapted from interior.dev's sortable-table (github.com/ddoemonn/interior
// @3148000, MIT License, Copyright (c) 2026 ozzy; notice in components/interior/LICENSE):
// the asc → desc → original cycle, empty values last, a numeric-aware collator and
// stable ties. Rebuilt as a real `<table>` rather than an ARIA grid of positioned divs,
// because the consoles' rows wrap, hold controls and change height, which upstream's
// fixed-height absolutely-positioned rows cannot.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { NewItemsPill } from "@/components/interior/new-items-pill";
import { continuesFrom, useArrivals } from "@/components/live/arrivals";
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
  /**
   * How the cell sits in a phone card. `field` (default): the column name on the left and
   * the value on the right. `block`: the value alone at full width, left-aligned, for a
   * cell that is a sentence or a row of actions, which beside a label reads as a ragged
   * right-aligned column.
   */
  card?: "field" | "block";
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
  "left-0": "sticky left-0 z-raised bg-surface max-sm:static",
  "left-12": "sticky left-12 z-raised bg-surface max-sm:static",
};

/*
 * ON A PHONE EACH ROW IS A CARD, in CSS alone: the header row hides, a row is a block, its
 * first cell is the row's title and every other cell carries its column's name beside its
 * value (`data-label`). A table swiped sideways at 375px hid every column but the first;
 * the same DOM keeps one reading order for a screen reader and one set of nodes for tests.
 * A column hidden below a width stays hidden: the card never brings it back.
 */
const CARD_TABLE = "max-sm:block";
const CARD_ROW = "max-sm:block max-sm:px-3 max-sm:py-3";
// `max-w-none w-auto`: a desktop title cell may use `max-w-0 w-full` to truncate inside the
// table, and as a block that pair collapses it to nothing.
const CARD_TITLE =
  "max-sm:block max-sm:w-auto max-sm:max-w-none max-sm:p-0 max-sm:pb-1 max-sm:text-left max-sm:font-medium";
const CARD_FIELD =
  "max-sm:flex max-sm:items-baseline max-sm:justify-between max-sm:gap-4 max-sm:p-0 max-sm:py-0.5 max-sm:text-right max-sm:before:shrink-0 max-sm:before:text-left max-sm:before:text-[12px] max-sm:before:text-ink-faint max-sm:before:content-[attr(data-label)]";
const CARD_BLOCK = "max-sm:block max-sm:p-0 max-sm:pt-1.5 max-sm:text-left";

/**
 * The same phone-card layout for a table that cannot be a `DataTable` (one with a
 * disclosure row, or a row header). Put `head` on the `<thead>`, `table`/`body` on the
 * table and body, `row` on each `<tr>`, `title` on the cell that names the row, and on
 * every other cell `field` with `data-label` set to its column's name (or `block` for a
 * sentence or actions). One layout for every table a client reads on a phone.
 */
export const CARD = {
  table: CARD_TABLE,
  head: "max-sm:hidden",
  body: CARD_TABLE,
  row: CARD_ROW,
  title: CARD_TITLE,
  field: CARD_FIELD,
  block: CARD_BLOCK,
} as const;

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
 * Marks what changed between two renders of the same rows: a row that arrived, and any cell
 * whose `flash` value moved. Both clear after `FLASH_MS`. Nothing is marked on the first
 * render, so opening a screen is quiet, nor when the rows were replaced rather than
 * continued (another page or filter), so paging is quiet too.
 */
function useChangedKeys<T>(
  rows: T[],
  columns: DataColumn<T>[],
  getRowId: (row: T) => string,
  onArrived?: (rows: T[]) => void,
) {
  const seen = useRef<Map<string, string> | null>(null);
  const [changed, setChanged] = useState<Set<string>>(() => new Set());
  // In a ref, not an effect cleanup: the rows array is rebuilt on every render, so a
  // cleanup would cancel the clearing timer on the very next render.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const arrivedCallback = useRef(onArrived);
  useEffect(() => {
    arrivedCallback.current = onArrived;
  });
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    const ids = rows.map(getRowId);
    const previous = seen.current;
    const previousIds = new Set<string>();
    if (previous) for (const key of previous.keys()) if (!key.includes("\u0000")) previousIds.add(key);
    const continuous = previous !== null && continuesFrom(previousIds, ids);
    const next = new Map<string, string>();
    const marked = new Set<string>();
    const arrived: T[] = [];
    rows.forEach((row, index) => {
      const id = ids[index];
      next.set(id, "");
      if (continuous && !previousIds.has(id)) {
        marked.add(id);
        arrived.push(row);
      }
      for (const column of columns) {
        if (!column.flash) continue;
        const key = `${id}\u0000${column.id}`;
        const value = column.flash(row) ?? "";
        const before = previous?.get(key);
        if (before !== undefined && before !== "" && before !== value) marked.add(key);
        next.set(key, value);
      }
    });
    seen.current = next;
    if (arrived.length > 0) arrivedCallback.current?.(arrived);
    if (marked.size === 0) return;
    setChanged(marked);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setChanged(new Set()), FLASH_MS);
  }, [rows, columns, getRowId]);

  return changed;
}


/**
 * A removed row fades out over 150 ms when the change continued the rows on screen, and
 * goes at once when they were replaced (another page) or motion is reduced.
 */
const ROW_EXIT = {
  leave: (animate: boolean) => ({
    opacity: 0,
    transition: animate ? { duration: 0.15, ease: [0.23, 1, 0.32, 1] as const } : { duration: 0 },
  }),
};

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
  /**
   * A sentence for screen readers when rows ARRIVE live, or null to say nothing. Only for
   * arrivals worth interrupting for (a new hot lead), never for every refetch.
   */
  announceArrivals?: (rows: T[]) => string | null;
  /**
   * Row selection for bulk actions: a checkbox column first, with a select-all header that
   * reads "some" when part of the rows are chosen. The caller owns the set (it survives
   * paging and filtering only if the caller wants it to) and renders its own bulk bar.
   */
  selection?: {
    selected: ReadonlySet<string>;
    onChange: (next: Set<string>) => void;
    /** Names one row's checkbox: "Select Priya Reddy". */
    rowLabel: (row: T) => string;
    /** Names the header checkbox. */
    allLabel?: string;
  };
  /** Shown in place of the rows when there are none (an `EmptyState`, a sentence). */
  empty?: ReactNode;
};

const CHECKBOX =
  "h-4 w-4 cursor-pointer rounded-[4px] border-line accent-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-5 touch:w-5";

/** The header checkbox: checked, unchecked, or the mixed state when only some rows are chosen. */
function SelectAll({ checked, mixed, label, onChange }: { checked: boolean; mixed: boolean; label: string; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = mixed;
  }, [mixed]);
  return (
    <span className="inline-flex touch:min-h-11 items-center">
      <input ref={ref} type="checkbox" aria-label={label} checked={checked} onChange={onChange} className={CHECKBOX} />
    </span>
  );
}

/**
 * THE CONSOLE'S DATA TABLE. Sortable headers (`aria-sort`, a polite status naming the
 * order), rows that can carry a single link stretched over the row (UX-DOCTRINE §4: one
 * target per row — give the link `after:absolute after:inset-0` and any other control in
 * the row `relative z-raised`), columns that drop out at narrow widths, and cells that mark
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
  announceArrivals,
  selection,
  empty,
}: DataTableProps<T>) {
  const [internal, setInternal] = useState<SortState>(defaultSort);
  const sort = controlled !== undefined ? controlled : internal;
  const ordered = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);
  const reduced = useReducedMotion() === true;
  const ids = useMemo(() => rows.map(getRowId), [rows, getRowId]);
  const { arrived, continuous } = useArrivals(ids);

  // Arrivals while the top of the table is scrolled out of view: say so quietly instead of
  // moving the reader (UX: never steal the scroll position).
  const top = useRef<HTMLDivElement>(null);
  const topInView = useRef(true);
  const [unseen, setUnseen] = useState(0);
  // Mounted from the first arrival a reader did not see, and kept: the control and its
  // polite count exist only on a table that has had something to offer.
  const [offered, setOffered] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    const element = top.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      topInView.current = entry.isIntersecting;
      if (entry.isIntersecting) setUnseen(0);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const changed = useChangedKeys(rows, columns, getRowId, (list) => {
    if (!topInView.current) {
      setOffered(true);
      setUnseen((count) => count + list.length);
    }
    const sentence = announceArrivals?.(list);
    if (sentence) setAnnouncement(sentence);
  });
  const showArrivals = () => {
    top.current?.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    setUnseen(0);
  };

  const setSort = (next: SortState) => {
    if (controlled === undefined) setInternal(next);
    onSortChange?.(next);
  };
  const sortedColumn = sort ? columns.find((c) => c.id === sort.id) : undefined;
  const chosenHere = selection ? ids.filter((id) => selection.selected.has(id)).length : 0;
  const toggleAll = () => {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (chosenHere === ids.length) for (const id of ids) next.delete(id);
    else for (const id of ids) next.add(id);
    selection.onChange(next);
  };
  const toggleRow = (id: string) => {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selection.onChange(next);
  };
  const span = columns.length + (selection ? 1 : 0);

  return (
    <div className={className}>
      <div ref={top} aria-hidden className="h-0" />
      {/* The console's one "new above" control (`NewItemsPill`, also the assistant's
          activity log), in a zero-height sticky strip so it floats over the rows while the
          page scrolls and pushes nothing. */}
      {offered && (
        <div className="sticky top-0 z-sticky h-0">
          <NewItemsPill
            count={unseen}
            onJump={showArrivals}
            label={(count, over) => `${count}${over ? "+" : ""} new ${count === 1 && !over ? "row" : "rows"}`}
          />
        </div>
      )}
      {/* `relative`: absolutely positioned descendants (visually hidden header text, a
          row's stretched link) must take this scroller as their containing block, or they
          escape its clipping and widen the page. */}
      <ScrollRegion label={label} className="scroll-shadow-x relative">
        <table className={`w-full border-collapse text-left text-sm ${CARD_TABLE}`}>
          <caption className="sr-only">{label}</caption>
          <thead className="max-sm:hidden">
            <tr className="border-b border-line">
              {selection ? (
                <th scope="col" className="w-10 px-3 py-2">
                  <SelectAll
                    checked={ids.length > 0 && chosenHere === ids.length}
                    mixed={chosenHere > 0 && chosenHere < ids.length}
                    label={selection.allLabel ?? "Select all rows"}
                    onChange={toggleAll}
                  />
                </th>
              ) : null}
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
          <tbody className={`divide-y divide-line ${CARD_TABLE}`}>
            {/* `initial={false}`: the rows present when the table first renders do not
                enter. Arrivals enter by class (`live-enter`, CSS, off the main thread);
                Motion is here only for the exit, which CSS cannot do. */}
            {ordered.length === 0 && empty ? (
              <tr>
                <td colSpan={span} className="px-3 py-6 max-sm:block">
                  {empty}
                </td>
              </tr>
            ) : null}
            <AnimatePresence initial={false} custom={continuous && !reduced}>
            {ordered.map((row) => {
              const id = getRowId(row);
              const arriving = arrived.has(id) || changed.has(id);
              return (
                <motion.tr
                  key={id}
                  variants={ROW_EXIT}
                  exit="leave"
                  className={`relative transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.025] ${CARD_ROW} ${
                    arriving ? "live-arrive" : ""
                  } ${selection?.selected.has(id) ? "bg-brand-soft/60" : ""} ${rowClassName?.(row) ?? ""}`}
                >
                  {selection ? (
                    <td className="relative z-raised w-10 px-3 py-3 align-middle max-sm:float-right max-sm:w-auto max-sm:p-0">
                      <span className="inline-flex touch:min-h-11 items-center">
                        <input
                          type="checkbox"
                          aria-label={selection.rowLabel(row)}
                          checked={selection.selected.has(id)}
                          onChange={() => toggleRow(id)}
                          className={CHECKBOX}
                        />
                      </span>
                    </td>
                  ) : null}
                  {columns.map((column, index) => (
                    <td
                      key={column.id}
                      data-label={column.header}
                      className={`px-3 py-3 align-middle ${column.align === "right" ? "text-right" : ""} ${
                        column.hideBelow
                          ? HIDE[column.hideBelow]
                          : index === 0
                            ? CARD_TITLE
                            : column.card === "block"
                              ? CARD_BLOCK
                              : CARD_FIELD
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
                </motion.tr>
              );
            })}
            </AnimatePresence>
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
      {/* Its own region: an arrival worth announcing must not replace the sort status. */}
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {sort && partialNote && (
        <p aria-hidden className="px-3 pb-1 pt-2 text-[12px] text-ink-faint">
          {partialNote}
        </p>
      )}
    </div>
  );
}

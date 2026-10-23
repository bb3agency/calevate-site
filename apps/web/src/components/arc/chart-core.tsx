"use client";

/**
 * The pieces every kit chart is made of: the series palette, scales and ticks, the frame
 * that owns loading / empty / error, the legend, the hover tooltip, and the data table.
 *
 * Plain SVG and no chart library, because the charts this console draws are small (a
 * week of calls, a month of spend) and a library would bring its own colours, number
 * formats and accessibility model to override. Every chart renders the same data twice:
 * once as marks for the eye (`aria-hidden`), once as a real `<table>` — visually hidden
 * by default and shown on request — so a screen reader reads numbers, not shapes.
 *
 * Numbers in charts are display magnitudes. Money arrives as decimal strings (hard rule 7):
 * a screen passes `Number(wire)` for the bar's height only and the exact text through
 * `display` (from `formatINR`), so what a person reads is never a float.
 */

import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import clsx from "clsx";

import { ScrollRegion, Skeleton, formatCount } from "@/components/ui";

/** The categorical slots, in their fixed order (globals.css `--series-*`). */
export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
] as const;

/** Colour follows the series' position in the caller's list, never its rank in the data. */
export function seriesColor(index: number): string {
  return SERIES[index] ?? "var(--chart-neutral)";
}

/** 12,345 → "12K", 1,23,456 → "1.2L": compact Indian grouping for axis ticks. */
const COMPACT = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
export function formatCompact(value: number): string {
  return Math.abs(value) < 1000 ? formatCount(Math.round(value * 100) / 100) : COMPACT.format(value);
}

/** "24 Oct" for an instant, in IST. */
const IST_SHORT_DAY = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
});
export function istShortDay(instant: string | Date): string {
  const at = typeof instant === "string" ? new Date(instant) : instant;
  return Number.isNaN(at.getTime()) ? "—" : IST_SHORT_DAY.format(at);
}

/** Round tick values from 0 to at least `max`: 0 / 5 / 10, never 0 / 3.7 / 7.4. */
export function niceTicks(max: number, count = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v < max + step * 0.999; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

/** The rendered width of a container, following it as the layout changes. */
export function useMeasuredWidth(ref: RefObject<HTMLElement | null>, fallback = 560): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export type LegendItem = { label: string; color: string; shape?: "dot" | "line" };

export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <ul className={clsx("flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-muted", className)}>
      {items.map((item) => (
        <li key={item.label} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={item.shape === "line" ? "h-0.5 w-3 rounded-full" : "h-2 w-2 rounded-full"}
            style={{ background: item.color }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** The table every chart renders beside its marks. */
export type ChartTable = {
  /** What one row is: "Day", "Hour", "Agent". */
  columns: string[];
  rows: (string | number)[][];
};

export type ChartStateProps = {
  loading?: boolean;
  /** Plain words: "We could not load your calls." Rendered instead of the marks. */
  error?: ReactNode;
  /** Shown when there is no data, in the screen's own terms: "No calls this week yet." */
  empty?: ReactNode;
  /** Label for the loading state, read by screen readers. */
  loadingLabel?: string;
};

export type ChartFrameProps = ChartStateProps & {
  /** Names the chart: its caption, and the accessible name of its table. */
  title: string;
  /** Hide the visible title when the card around the chart already says it. */
  hideTitle?: boolean;
  /** One line under the title: the unit or the period ("Calls per day, IST"). */
  description?: ReactNode;
  legend?: LegendItem[];
  table: ChartTable;
  isEmpty: boolean;
  /** Height of the plot, px; the loading skeleton takes the same room. */
  height: number;
  showTableLabel?: string;
  hideTableLabel?: string;
  className?: string;
  children: ReactNode;
};

/**
 * Title, states, plot, legend and table, in one order every chart shares. The plot is
 * `aria-hidden`; the `<table>` carries the data for assistive tech and is visually hidden
 * until "Show as table" reveals it, which is also the relief for a series whose marks are
 * hard to tell apart.
 */
export function ChartFrame({
  title,
  hideTitle = false,
  description,
  legend,
  table,
  isEmpty,
  height,
  loading,
  error,
  empty = "Nothing to show yet.",
  loadingLabel,
  showTableLabel = "Show as table",
  hideTableLabel = "Hide table",
  className,
  children,
}: ChartFrameProps) {
  const [tableShown, setTableShown] = useState(false);
  const titleId = useId();
  const plotState = loading ? "loading" : error ? "error" : isEmpty ? "empty" : "ready";
  return (
    <figure aria-labelledby={titleId} className={clsx("min-w-0 space-y-3", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <figcaption id={titleId} className={hideTitle ? "sr-only" : "text-body font-semibold text-ink"}>
            {title}
          </figcaption>
          {description ? <p className="text-meta text-ink-muted">{description}</p> : null}
        </div>
        {plotState === "ready" ? (
          <button
            type="button"
            aria-expanded={tableShown}
            onClick={() => setTableShown((shown) => !shown)}
            className="press inline-flex min-h-8 items-center rounded-md px-2 text-meta font-medium text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
          >
            {tableShown ? hideTableLabel : showTableLabel}
          </button>
        ) : null}
      </div>
      {plotState === "loading" ? (
        <div style={{ minHeight: height }}>
          <Skeleton rows={Math.max(2, Math.round(height / 48))} label={loadingLabel ?? `Loading ${title}`} />
        </div>
      ) : plotState === "error" ? (
        <div role="alert" className="flex items-center border-l-2 border-danger py-2 pl-3 text-body text-ink" style={{ minHeight: height / 2 }}>
          {error}
        </div>
      ) : plotState === "empty" ? (
        <div className="grid place-items-center rounded-card border border-dashed border-line px-4 text-center text-body text-ink-muted" style={{ minHeight: height }}>
          {empty}
        </div>
      ) : (
        <>
          <div aria-hidden className="relative">
            {children}
          </div>
          {legend && legend.length > 1 ? <Legend items={legend} /> : null}
          <DataTable title={title} table={table} visible={tableShown} />
        </>
      )}
    </figure>
  );
}

function DataTable({ title, table, visible }: { title: string; table: ChartTable; visible: boolean }) {
  const body = (
      <table className="w-full text-left text-meta">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr className="border-b border-line">
            {table.columns.map((column) => (
              <th key={column} scope="col" className="py-1.5 pr-4 font-semibold text-ink-muted">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              {row.map((cell, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="py-1.5 pr-4 font-medium text-ink">
                    {cell}
                  </th>
                ) : (
                  <td key={j} className="py-1.5 pr-4 tabular-nums text-ink">
                    {typeof cell === "number" ? formatCount(cell) : cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
  );
  // Shown, it can be wider than a phone, so it scrolls in a keyboard-reachable region;
  // hidden, it is still read by a screen reader.
  return visible ? (
    <ScrollRegion label={title} className="max-w-full">
      {body}
    </ScrollRegion>
  ) : (
    <div className="sr-only">{body}</div>
  );
}

/**
 * The hover/focus readout over a plot. Positioned in the plot's own pixel space and kept
 * inside it: it flips to the left of the pointer past the midline so it never runs off
 * a phone screen.
 */
export function ChartTooltip({
  x,
  y,
  width,
  children,
}: {
  x: number;
  y: number;
  /** The plot's width, to decide which side of the pointer the readout sits on. */
  width: number;
  children: ReactNode;
}) {
  const flip = x > width / 2;
  return (
    <div
      className="pointer-events-none absolute z-raised max-w-56 rounded-md border border-line bg-surface px-2.5 py-1.5 text-meta text-ink shadow-raised"
      style={{
        left: x,
        top: y,
        transform: `translate(${flip ? "calc(-100% - 10px)" : "10px"}, -50%)`,
      }}
    >
      {children}
    </div>
  );
}

/** Ref + measured width for a responsive plot container. */
export function usePlotWidth(fallback?: number) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(ref, fallback);
  return { ref, width };
}

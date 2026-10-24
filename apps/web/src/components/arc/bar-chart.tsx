"use client";

/**
 * Bars for magnitude: calls per day (columns), spend by agent (horizontal bars), outcomes
 * stacked per day.
 *
 * Adapted from uiarc's `bar-chart` (MIT, see ./LICENSE), to the dataviz mark specs: bars
 * at most 24px thick with a 4px rounded data end and a square baseline, a 2px surface gap
 * between touching bars, one baseline, values at the tips only where the screen asks.
 *
 * Horizontal bars are HTML rather than SVG, on purpose: their labels are the screen's
 * own words (an agent's name, a Telugu campaign title) and must wrap instead of being
 * cut, which an SVG `<text>` cannot do.
 */

import { useState, type PointerEvent } from "react";
import clsx from "clsx";

import {
  ChartFrame,
  ChartTooltip,
  formatCompact,
  niceTicks,
  seriesColor,
  usePlotWidth,
  type ChartStateProps,
} from "./chart-core";

export type BarSeries = {
  label: string;
  values: number[];
  /** Exact text per bar for the readout, the tip label and the table. */
  display?: string[];
};

export type BarChartProps = ChartStateProps & {
  title: string;
  hideTitle?: boolean;
  description?: string;
  /** One per bar group, already formatted by the screen ("Mon 21", "Reception"). */
  categories: string[];
  series: BarSeries[];
  orientation?: "vertical" | "horizontal";
  /** Stack the series in each category instead of placing them side by side. */
  stacked?: boolean;
  /** Print each bar's value at its tip (horizontal) — for a short ranked list. */
  showValues?: boolean;
  height?: number;
  formatTick?: (value: number) => string;
  labelColumn?: string;
  className?: string;
};

const MARGIN = { top: 8, right: 8, bottom: 22, left: 40 };
const MAX_BAR = 24;
const GAP = 2;

/** A bar with a 4px rounded top and a square foot, as a path. */
function columnPath(x: number, y: number, w: number, h: number, round: boolean): string {
  if (h <= 0) return "";
  const r = round ? Math.min(4, w / 2, h) : 0;
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

export function BarChart({
  title,
  hideTitle,
  description,
  categories,
  series,
  orientation = "vertical",
  stacked = false,
  showValues = false,
  height = 200,
  formatTick = formatCompact,
  labelColumn = "Category",
  className,
  ...state
}: BarChartProps) {
  const text = (s: BarSeries, i: number) => s.display?.[i] ?? formatTick(s.values[i] ?? 0);
  const totals = categories.map((_, i) => series.reduce((sum, s) => sum + Math.max(0, s.values[i] ?? 0), 0));
  const peak = stacked ? Math.max(0, ...totals) : Math.max(0, ...series.flatMap((s) => s.values));
  const isEmpty = categories.length === 0 || peak === 0;
  const table = {
    columns: [labelColumn, ...series.map((s) => s.label)],
    rows: categories.map((c, i) => [c, ...series.map((s) => text(s, i))]),
  };
  const legend = series.map((s, i) => ({ label: s.label, color: seriesColor(i) }));
  return (
    <ChartFrame
      title={title}
      hideTitle={hideTitle}
      description={description}
      height={orientation === "vertical" ? height : Math.max(80, categories.length * 32)}
      isEmpty={isEmpty}
      legend={legend}
      table={table}
      className={className}
      {...state}
    >
      {orientation === "vertical" ? (
        <Columns
          categories={categories}
          series={series}
          stacked={stacked}
          height={height}
          peak={peak}
          formatTick={formatTick}
          text={text}
        />
      ) : (
        <Rows categories={categories} series={series} stacked={stacked} peak={peak} showValues={showValues} text={text} />
      )}
    </ChartFrame>
  );
}

function Columns({
  categories,
  series,
  stacked,
  height,
  peak,
  formatTick,
  text,
}: {
  categories: string[];
  series: BarSeries[];
  stacked: boolean;
  height: number;
  peak: number;
  formatTick: (v: number) => string;
  text: (s: BarSeries, i: number) => string;
}) {
  const { ref, width } = usePlotWidth();
  const [hover, setHover] = useState<number | null>(null);
  const ticks = niceTicks(peak);
  const top = ticks[ticks.length - 1] || 1;
  const plotW = Math.max(40, width - MARGIN.left - MARGIN.right);
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const band = plotW / categories.length;
  const lanes = stacked ? 1 : series.length;
  // Bars never fill their slot: capped at 24px, the leftover is air between groups.
  const barW = Math.max(2, Math.min(MAX_BAR, (band * 0.7 - GAP * (lanes - 1)) / lanes));
  const groupW = barW * lanes + GAP * (lanes - 1);
  const y = (v: number) => MARGIN.top + (1 - v / top) * plotH;
  const every = Math.max(1, Math.ceil((categories.length * 48) / plotW));

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const i = Math.floor(((event.clientX - box.left) / box.width) * categories.length);
    setHover(Math.max(0, Math.min(categories.length - 1, i)));
  };

  return (
    <div ref={ref} className="w-full">
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} className="block max-w-full">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={MARGIN.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-ink-faint text-[11px] tabular-nums">
              {formatTick(t)}
            </text>
          </g>
        ))}
        {categories.map((c, i) => {
          const left = MARGIN.left + band * i + (band - groupW) / 2;
          let base = 0;
          return (
            <g key={`${c}-${i}`} opacity={hover === null || hover === i ? 1 : 0.55}>
              {series.map((s, si) => {
                const v = Math.max(0, s.values[i] ?? 0);
                const isTop = !stacked || si === series.length - 1 || series.slice(si + 1).every((n) => !(n.values[i] > 0));
                const yTop = y(base + v);
                // A 2px surface gap between stacked segments, taken from the lower one.
                const h = y(base) - yTop - (stacked && base > 0 ? GAP : 0);
                const xBar = stacked ? left : left + si * (barW + GAP);
                const d = columnPath(xBar, yTop, barW, Math.max(0, h), isTop);
                if (stacked) base += v;
                return d ? <path key={s.label} d={d} fill={seriesColor(si)} /> : null;
              })}
              {i % every === 0 || i === categories.length - 1 ? (
                <text x={MARGIN.left + band * i + band / 2} y={height - 6} textAnchor="middle" className="fill-ink-faint text-[11px]">
                  {c}
                </text>
              ) : null}
            </g>
          );
        })}
        <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(0)} y2={y(0)} stroke="var(--text-faint)" strokeWidth={1} />
        <rect
          x={MARGIN.left}
          y={MARGIN.top}
          width={plotW}
          height={plotH}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      {hover !== null ? (
        <ChartTooltip x={MARGIN.left + band * hover + band / 2} y={MARGIN.top + plotH / 2} width={width}>
          <p className="font-semibold text-ink">{categories[hover]}</p>
          {series.map((s, si) => (
            <p key={s.label} className="flex items-center gap-1.5 tabular-nums">
              <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: seriesColor(si) }} />
              <span className="text-ink-muted">{s.label}</span>
              <span className="ml-auto pl-2 font-medium text-ink">{text(s, hover)}</span>
            </p>
          ))}
        </ChartTooltip>
      ) : null}
    </div>
  );
}

function Rows({
  categories,
  series,
  stacked,
  peak,
  showValues,
  text,
}: {
  categories: string[];
  series: BarSeries[];
  stacked: boolean;
  peak: number;
  showValues: boolean;
  text: (s: BarSeries, i: number) => string;
}) {
  return (
    <ul className="space-y-2.5">
      {categories.map((c, i) => (
        <li key={`${c}-${i}`} className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
          <span className="text-meta text-ink [overflow-wrap:anywhere]">{c}</span>
          <span className="flex min-w-0 items-center gap-2">
            <span className={clsx("flex min-w-0 flex-1", stacked ? "gap-0.5" : "flex-col gap-1")}>
              {series.map((s, si) => {
                const share = peak > 0 ? Math.max(0, s.values[i] ?? 0) / peak : 0;
                return share > 0 ? (
                  <span
                    key={s.label}
                    className={clsx("block h-3 rounded-e-[4px]", stacked && si > 0 && "rounded-s-none")}
                    style={{ width: `${share * 100}%`, background: seriesColor(si), maxWidth: "100%" }}
                  />
                ) : null;
              })}
            </span>
            {showValues ? (
              <span className="shrink-0 text-meta tabular-nums text-ink">
                {series.map((s) => text(s, i)).join(" · ")}
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

"use client";

/**
 * How long calls run, compared across agents or weeks: one smoothed distribution per row,
 * stacked so their shapes can be compared on one shared time axis, each with its median
 * marked.
 *
 * Adapted from uiarc's `ridgeline` (MIT, see ./LICENSE). The density is a Gaussian kernel
 * estimate with Silverman's bandwidth, the textbook default for a smooth unimodal-ish
 * sample; the screen passes raw durations and the component owns the smoothing. All rows
 * share one colour (they are the same measure, not different categories) and the median
 * tick and table carry the numbers. The table gives median, the middle half and the count,
 * which is what a reader compares.
 */

import { useState } from "react";

import { ChartFrame, ChartTooltip, usePlotWidth, type ChartStateProps } from "./chart-core";
import { formatCount, formatDuration } from "@/components/ui";

/**
 * `values` draw the shape. When the server has measured the row exactly (a binned read),
 * pass its `median`, `p90` and `count`: the tick, readout and table then say those figures
 * rather than ones re-derived from the drawn sample.
 */
export type RidgeSeries = { label: string; values: number[]; median?: number; p90?: number; count?: number };

export type RidgelineProps = ChartStateProps & {
  title: string;
  hideTitle?: boolean;
  description?: string;
  series: RidgeSeries[];
  /** Formats an x value (default: seconds as m:ss). */
  formatValue?: (value: number) => string;
  /** Cut the shared axis at this value so one 40-minute outlier does not squash the rest. */
  maxValue?: number;
  rowHeight?: number;
  labelColumn?: string;
  medianColumn?: string;
  middleColumn?: string;
  /** Heading of the 90th-percentile column, used when every row carries `p90`. */
  p90Column?: string;
  countColumn?: string;
  className?: string;
};

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Silverman's rule-of-thumb bandwidth; falls back to a sliver of the range for a flat sample. */
function bandwidth(sorted: number[], span: number): number {
  const n = sorted.length;
  const mean = sorted.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(sorted.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, n - 1));
  const iqr = quantile(sorted, 0.75) - quantile(sorted, 0.25);
  const spread = Math.min(sd, iqr / 1.34) || sd || span / 20;
  return Math.max(span / 200, 0.9 * spread * n ** -0.2);
}

function density(sorted: number[], xs: number[], h: number): number[] {
  const k = 1 / (sorted.length * h * Math.sqrt(2 * Math.PI));
  return xs.map((x) => sorted.reduce((sum, v) => sum + Math.exp(-0.5 * ((x - v) / h) ** 2), 0) * k);
}

export function Ridgeline({
  title,
  hideTitle,
  description,
  series,
  formatValue = (v) => formatDuration(Math.round(v)),
  maxValue,
  rowHeight = 36,
  labelColumn = "Row",
  medianColumn = "Median",
  middleColumn = "Middle half",
  p90Column = "9 in 10 under",
  countColumn = "Calls",
  className,
  ...state
}: RidgelineProps) {
  const { ref, width } = usePlotWidth();
  const [hover, setHover] = useState<number | null>(null);
  const rows = series.map((s) => {
    const sorted = s.values.filter((v) => Number.isFinite(v) && v >= 0).sort((a, b) => a - b);
    return {
      ...s,
      sorted,
      mid: s.median ?? (sorted.length ? quantile(sorted, 0.5) : null),
      n: s.count ?? sorted.length,
    };
  });
  const exact = rows.length > 0 && rows.every((r) => r.p90 !== undefined);
  const all = rows.flatMap((r) => r.sorted);
  const domainMax = maxValue ?? (all.length ? quantile([...all].sort((a, b) => a - b), 0.98) : 0);
  const labelW = Math.min(112, width * 0.3);
  const plotW = Math.max(40, width - labelW - 8);
  const overlap = 1.6;
  const height = rowHeight * (rows.length - 1) + rowHeight * overlap + 22;
  const xs = Array.from({ length: 64 }, (_, i) => (i / 63) * (domainMax || 1));
  const curves = rows.map((r) => (r.sorted.length > 1 && domainMax > 0 ? density(r.sorted, xs, bandwidth(r.sorted, domainMax)) : []));
  const peak = Math.max(0, ...curves.flat());
  const sx = (v: number) => labelW + (Math.min(v, domainMax) / (domainMax || 1)) * plotW;

  return (
    <ChartFrame
      title={title}
      hideTitle={hideTitle}
      description={description}
      height={height}
      isEmpty={all.length === 0}
      table={{
        columns: [labelColumn, medianColumn, exact ? p90Column : middleColumn, countColumn],
        rows: rows.map((r) => [
          r.label,
          r.mid !== null && r.n > 0 ? formatValue(r.mid) : "—",
          exact
            ? r.n > 0 && r.p90 !== undefined
              ? formatValue(r.p90)
              : "—"
            : r.sorted.length
              ? `${formatValue(quantile(r.sorted, 0.25))} – ${formatValue(quantile(r.sorted, 0.75))}`
              : "—",
          formatCount(r.n),
        ]),
      }}
      className={className}
      {...state}
    >
      <div ref={ref} className="relative w-full">
        <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} className="block max-w-full">
          {rows.map((r, i) => {
            const base = rowHeight * i + rowHeight * overlap;
            const curve = curves[i];
            const scale = (rowHeight * overlap - 4) / (peak || 1);
            const d = curve.length
              ? `M${sx(0)},${base} ` + curve.map((v, k) => `L${sx(xs[k]).toFixed(1)},${(base - v * scale).toFixed(1)}`).join(" ") + ` L${sx(domainMax)},${base} Z`
              : "";
            const median = r.sorted.length ? r.mid : null;
            const dim = hover !== null && hover !== i;
            return (
              <g key={r.label} opacity={dim ? 0.35 : 1} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <text x={0} y={base - 4} className="fill-ink-muted text-[11px]">
                  {/* The full label is in the table; code points, so a character is never split. */}
                  {Array.from(r.label).length > 16 ? `${Array.from(r.label).slice(0, 15).join("")}…` : r.label}
                </text>
                <line x1={labelW} x2={labelW + plotW} y1={base} y2={base} stroke="var(--line)" strokeWidth={1} />
                {d ? <path d={d} fill="var(--series-1)" fillOpacity={0.18} stroke="var(--series-1)" strokeWidth={1.5} strokeLinejoin="round" /> : null}
                {median !== null ? (
                  <line x1={sx(median)} x2={sx(median)} y1={base} y2={base - rowHeight * 0.6} stroke="var(--text)" strokeWidth={1.5} />
                ) : null}
              </g>
            );
          })}
          {[0, 0.25, 0.5, 0.75, 1].map((q) => (
            <text key={q} x={sx(domainMax * q)} y={height - 4} textAnchor={q === 0 ? "start" : q === 1 ? "end" : "middle"} className="fill-ink-faint text-[11px] tabular-nums">
              {formatValue(domainMax * q)}
            </text>
          ))}
        </svg>
        {hover !== null && rows[hover].sorted.length && rows[hover].mid !== null ? (
          <ChartTooltip x={sx(rows[hover].mid ?? 0)} y={rowHeight * hover + rowHeight} width={width}>
            <p className="font-semibold text-ink">{rows[hover].label}</p>
            <p className="tabular-nums text-ink-muted">
              {medianColumn} {formatValue(rows[hover].mid ?? 0)}
              {rows[hover].p90 !== undefined ? ` · ${p90Column.toLowerCase()} ${formatValue(rows[hover].p90 ?? 0)}` : ""}
              {` · ${formatCount(rows[hover].n)} ${countColumn.toLowerCase()}`}
            </p>
          </ChartTooltip>
        ) : null}
      </div>
    </ChartFrame>
  );
}

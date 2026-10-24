"use client";

/**
 * A line chart for change over time: calls per day, spend per week, answer rate by month.
 *
 * Adapted from uiarc's `line-chart` (MIT, see ./LICENSE). Kept: thin 2px lines, a
 * crosshair readout on hover, one axis. Changed: the x positions are the caller's own
 * labels (already formatted in IST by the screen, so the chart never guesses a time zone),
 * the y axis is compact en-IN ("1.2L"), the data also renders as a table, and nothing
 * draws in on first view.
 */

import { useState, type PointerEvent } from "react";

import {
  ChartFrame,
  ChartTooltip,
  formatCompact,
  niceTicks,
  seriesColor,
  usePlotWidth,
  type ChartStateProps,
} from "./chart-core";

export type LineSeries = {
  label: string;
  /** One value per x label; `null` is a gap (no reading), never zero. */
  values: (number | null)[];
  /** Exact text per point for the readout and the table (money from `formatINR`). */
  display?: string[];
};

export type LineChartProps = ChartStateProps & {
  title: string;
  hideTitle?: boolean;
  description?: string;
  /** The x labels, in order, formatted by the screen ("24 Oct", "Week of 7 Oct"). */
  labels: string[];
  series: LineSeries[];
  /** A wash under a single series. Ignored for two or more, where washes would overlap. */
  area?: boolean;
  height?: number;
  formatTick?: (value: number) => string;
  /** Heading of the table's first column. */
  labelColumn?: string;
  className?: string;
};

const MARGIN = { top: 8, right: 8, bottom: 22, left: 40 };

export function LineChart({
  title,
  hideTitle,
  description,
  labels,
  series,
  area = false,
  height = 200,
  formatTick = formatCompact,
  labelColumn = "Period",
  className,
  ...state
}: LineChartProps) {
  const { ref, width } = usePlotWidth();
  const [hover, setHover] = useState<number | null>(null);
  const values = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const isEmpty = labels.length === 0 || values.length === 0;
  const ticks = niceTicks(Math.max(0, ...values));
  const top = ticks[ticks.length - 1] || 1;
  const plotW = Math.max(40, width - MARGIN.left - MARGIN.right);
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const x = (i: number) => MARGIN.left + (labels.length <= 1 ? plotW / 2 : (i / (labels.length - 1)) * plotW);
  const y = (v: number) => MARGIN.top + (1 - v / top) * plotH;
  // Label every k-th x so labels never collide: a slot sized to the longest label (11px text
  // runs about 6.5px a character) plus a gap. The last is always kept, so a regular label
  // too close to it gives way.
  const slot = Math.max(56, Math.max(0, ...labels.map((label) => label.length)) * 6.5 + 20);
  const every = Math.max(1, Math.ceil((labels.length * slot) / plotW));

  const text = (s: LineSeries, i: number) => {
    const v = s.values[i];
    return s.display?.[i] ?? (v === null || v === undefined ? "—" : formatTick(v));
  };

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const share = (event.clientX - box.left) / box.width;
    setHover(Math.max(0, Math.min(labels.length - 1, Math.round(share * (labels.length - 1)))));
  };

  return (
    <ChartFrame
      title={title}
      hideTitle={hideTitle}
      description={description}
      height={height}
      isEmpty={isEmpty}
      className={className}
      legend={series.map((s, i) => ({ label: s.label, color: seriesColor(i), shape: "line" as const }))}
      table={{
        columns: [labelColumn, ...series.map((s) => s.label)],
        rows: labels.map((label, i) => [label, ...series.map((s) => text(s, i))]),
      }}
      {...state}
    >
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
          {labels.map((label, i) =>
            (i % every === 0 && labels.length - 1 - i >= every) || i === labels.length - 1 ? (
              <text
                key={`${label}-${i}`}
                x={x(i)}
                y={height - 6}
                textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"}
                className="fill-ink-faint text-[11px]"
              >
                {label}
              </text>
            ) : null,
          )}
          {series.map((s, si) => {
            // A null breaks the line: a gap says "no reading", a dip to zero would lie.
            const runs: [number, number][][] = [];
            let run: [number, number][] = [];
            s.values.forEach((v, i) => {
              if (v === null) {
                if (run.length) runs.push(run);
                run = [];
              } else run.push([x(i), y(v)]);
            });
            if (run.length) runs.push(run);
            const path = (points: [number, number][]) =>
              points.map(([px, py], k) => `${k ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
            const colour = seriesColor(si);
            return (
              <g key={s.label}>
                {area && series.length === 1
                  ? runs.map((points, k) => (
                      <path
                        key={`a${k}`}
                        d={`${path(points)} L${points[points.length - 1][0]},${y(0)} L${points[0][0]},${y(0)} Z`}
                        fill={colour}
                        fillOpacity={0.1}
                      />
                    ))
                  : null}
                {runs.map((points, k) =>
                  points.length === 1 ? (
                    <circle key={k} cx={points[0][0]} cy={points[0][1]} r={3} fill={colour} />
                  ) : (
                    <path key={k} d={path(points)} fill="none" stroke={colour} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                  ),
                )}
              </g>
            );
          })}
          {hover !== null ? (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={MARGIN.top + plotH} stroke="var(--text-faint)" strokeWidth={1} />
              {series.map((s, si) =>
                s.values[hover] === null || s.values[hover] === undefined ? null : (
                  <circle
                    key={s.label}
                    cx={x(hover)}
                    cy={y(s.values[hover] as number)}
                    r={4}
                    fill={seriesColor(si)}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ),
              )}
            </g>
          ) : null}
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
          <ChartTooltip x={x(hover)} y={MARGIN.top + plotH / 2} width={width}>
            <p className="font-semibold text-ink">{labels[hover]}</p>
            {series.map((s, si) => (
              <p key={s.label} className="flex items-center gap-1.5 tabular-nums">
                <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: seriesColor(si) }} />
                <span className="text-ink-muted">{s.label}</span>
                <span className="ml-auto pl-2 font-medium text-ink">{text(s, hover)}</span>
              </p>
            ))}
          </ChartTooltip>
        ) : null}
      </div>
    </ChartFrame>
  );
}

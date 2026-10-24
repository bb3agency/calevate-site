"use client";

/**
 * A long series with a window onto it: the whole period as a small overview strip, a
 * brush on the strip choosing the stretch shown in full above. For leads captured per day
 * over a quarter, a campaign's dials per day since launch.
 *
 * Adapted from uiarc's `brush-chart` (MIT, see ./LICENSE). The detail view is the kit's
 * `LineChart` (so it brings its table, states and readout); this file adds only the
 * overview and the brush. The brush is operable without a pointer: its two edges are
 * sliders (arrow keys move a day, Page Up/Down a week, Home/End to the ends), which is
 * the APG multi-thumb slider pattern, and the selection is named in words beside it.
 */

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { lookup } from "@/lib/lookup";

import { LineChart } from "./line-chart";
import { usePlotWidth, type ChartStateProps } from "./chart-core";

export type BrushChartProps = ChartStateProps & {
  title: string;
  description?: string;
  /** One label per bucket, formatted by the screen in IST ("24 Oct"). */
  labels: string[];
  values: number[];
  /** Exact text per bucket for the readout and table. */
  display?: string[];
  seriesLabel: string;
  /** Initial window as [first, last] bucket index; default the last quarter of the data. */
  defaultRange?: [number, number];
  onRangeChange?: (range: [number, number]) => void;
  startLabel?: string;
  endLabel?: string;
  /** Words for the selection: "24 Oct to 7 Nov". */
  rangeText?: (from: string, to: string) => string;
  height?: number;
  className?: string;
};

const STRIP = 44;
/** Buckets a key moves an edge by: one bucket, or a week of daily buckets. */
const KEY_STEPS: Record<string, number> = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -7, PageUp: 7 };
const MIN_SPAN = 1;

export function BrushChart({
  title,
  description,
  labels,
  values,
  display,
  seriesLabel,
  defaultRange,
  onRangeChange,
  startLabel = "Start of the shown period",
  endLabel = "End of the shown period",
  rangeText = (from, to) => `${from} to ${to}`,
  height = 200,
  className,
  ...state
}: BrushChartProps) {
  const n = labels.length;
  const last = Math.max(0, n - 1);
  const [range, setRange] = useState<[number, number]>(
    () => defaultRange ?? [Math.max(0, Math.floor(last * 0.75)), last],
  );
  const [from, to] = [Math.min(range[0], last), Math.min(range[1], last)];
  const { ref, width } = usePlotWidth();
  const drag = useRef<{ kind: "start" | "end" | "window"; x0: number; r0: [number, number] } | null>(null);

  const commit = (next: [number, number]) => {
    const a = Math.max(0, Math.min(next[0], last - MIN_SPAN));
    const b = Math.min(last, Math.max(next[1], a + MIN_SPAN));
    setRange([a, b]);
    onRangeChange?.([a, b]);
  };

  const step = width / Math.max(1, last);
  const xOf = (i: number) => (last === 0 ? 0 : (i / last) * width);
  // The window and its handles are HTML over the SVG, so they are placed as a share of the
  // strip rather than in pixels: right at any width, before the strip is measured too.
  const pctOf = (i: number) => `${last === 0 ? 0 : (i / last) * 100}%`;
  const peak = Math.max(1, ...values);
  const overview =
    n > 1
      ? values.map((v, i) => `${i ? "L" : "M"}${xOf(i).toFixed(1)},${(STRIP - 4 - (v / peak) * (STRIP - 8)).toFixed(1)}`).join(" ")
      : "";

  const onDown = (kind: "start" | "end" | "window") => (event: PointerEvent<HTMLElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { kind, x0: event.clientX, r0: [from, to] };
  };
  const onMove = (event: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const shift = Math.round((event.clientX - d.x0) / (step || 1));
    if (d.kind === "start") commit([d.r0[0] + shift, d.r0[1]]);
    else if (d.kind === "end") commit([d.r0[0], d.r0[1] + shift]);
    else {
      const span = d.r0[1] - d.r0[0];
      const a = Math.max(0, Math.min(last - span, d.r0[0] + shift));
      commit([a, a + span]);
    }
  };
  const onUp = () => {
    drag.current = null;
  };

  const onKey = (edge: "start" | "end") => (event: KeyboardEvent<HTMLElement>) => {
    const move = lookup(KEY_STEPS, event.key);
    let next: [number, number] | null = null;
    if (move !== undefined) {
      next = edge === "start" ? [from + move, to] : [from, to + move];
    } else if (event.key === "Home") next = edge === "start" ? [0, to] : [from, from + MIN_SPAN];
    else if (event.key === "End") next = edge === "start" ? [to - MIN_SPAN, to] : [from, last];
    if (next) {
      event.preventDefault();
      commit(next);
    }
  };

  const thumb =
    "absolute top-0 z-raised flex h-full w-4 -translate-x-1/2 cursor-ew-resize touch-none items-center justify-center rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:w-11";

  return (
    <div className={className}>
      <LineChart
        title={title}
        description={description}
        labels={labels.slice(from, to + 1)}
        series={[{ label: seriesLabel, values: values.slice(from, to + 1), display: display?.slice(from, to + 1) }]}
        area
        height={height}
        {...state}
      />
      {n > 1 && !state.loading && !state.error ? (
        // Clipped sideways: the end handle's touch area reaches past the strip's edge.
        <div className="mt-3 space-y-1 overflow-x-clip">
          <div ref={ref} className="relative w-full select-none" style={{ height: STRIP }} onPointerMove={onMove} onPointerUp={onUp}>
            <svg aria-hidden width="100%" height={STRIP} viewBox={`0 0 ${width} ${STRIP}`} className="block max-w-full rounded-md bg-surface-muted">
              <path d={overview} fill="none" stroke="var(--text-faint)" strokeWidth={1.5} />
            </svg>
            <div
              aria-hidden
              onPointerDown={onDown("window")}
              className="absolute top-0 h-full cursor-grab touch-none rounded-md border-2 border-brand bg-brand/10 active:cursor-grabbing"
              style={{ left: pctOf(from), width: `max(4px, calc(${pctOf(to)} - ${pctOf(from)}))` }}
            />
            {(["start", "end"] as const).map((edge) => {
              const index = edge === "start" ? from : to;
              return (
                <div
                  key={edge}
                  role="slider"
                  tabIndex={0}
                  aria-label={edge === "start" ? startLabel : endLabel}
                  aria-valuemin={0}
                  aria-valuemax={last}
                  aria-valuenow={index}
                  aria-valuetext={labels[index]}
                  onKeyDown={onKey(edge)}
                  onPointerDown={onDown(edge)}
                  className={thumb}
                  style={{ left: pctOf(index) }}
                >
                  <span aria-hidden className="h-5 w-1.5 rounded-full bg-brand-strong" />
                </div>
              );
            })}
          </div>
          <p className="text-meta text-ink-muted" aria-live="polite">
            {rangeText(labels[from] ?? "", labels[to] ?? "")}
          </p>
        </div>
      ) : null}
    </div>
  );
}

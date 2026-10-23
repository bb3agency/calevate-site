"use client";

/**
 * When calls happen: a 7 × 24 grid of IST weekday by hour, darker where there were more.
 * It answers "when should the line be staffed / when should a campaign dial".
 *
 * Adapted from uiarc's `activity-heatmap` (MIT, see ./LICENSE), reshaped from its
 * calendar-of-days into the weekday-by-hour grid the founder asked for (f7d9f716). One
 * hue, light to dark (sequential: magnitude never takes a second colour), with the scale
 * shown as a "Fewer → More" key and every count in the table. The wave reveal and rolling
 * total are not carried over.
 *
 * The buckets are the server's, already in IST (D-709); this component never converts a
 * time, it only lays out the 168 numbers it is given.
 */

import { useState } from "react";

import { ChartFrame, ChartTooltip, usePlotWidth, type ChartStateProps } from "./chart-core";
import { formatCount } from "@/components/ui";

export type HeatmapCell = {
  /** 0 = Monday … 6 = Sunday, in IST. */
  weekday: number;
  /** 0–23, the IST hour the bucket starts at. */
  hour: number;
  count: number;
};

export type ActivityHeatmapProps = ChartStateProps & {
  title: string;
  hideTitle?: boolean;
  description?: string;
  cells: HeatmapCell[];
  /** Row labels, Monday first. */
  weekdays?: string[];
  /** Noun for the readout: "calls". */
  unit?: string;
  fewerLabel?: string;
  moreLabel?: string;
  className?: string;
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** Five steps of brand over the surface; step 0 is "none", a hairline cell. */
const STEPS = [0, 22, 45, 70, 100];

function hourLabel(hour: number): string {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${hour < 12 ? "am" : "pm"}`;
}

export function ActivityHeatmap({
  title,
  hideTitle,
  description,
  cells,
  weekdays = DAYS,
  unit = "calls",
  fewerLabel = "Fewer",
  moreLabel = "More",
  className,
  ...state
}: ActivityHeatmapProps) {
  const grid = Array.from({ length: 7 }, () => Array<number>(24).fill(0));
  for (const c of cells) {
    if (c.weekday >= 0 && c.weekday < 7 && c.hour >= 0 && c.hour < 24) grid[c.weekday][c.hour] += Math.max(0, c.count);
  }
  const peak = Math.max(0, ...grid.flat());
  const { ref, width } = usePlotWidth();
  const [hover, setHover] = useState<{ d: number; h: number; x: number; y: number } | null>(null);
  const step = (v: number) => (v <= 0 || peak === 0 ? 0 : Math.min(4, Math.ceil((v / peak) * 4)));
  const fill = (s: number) =>
    s === 0 ? "var(--surface-muted)" : `color-mix(in oklab, var(--series-1) ${STEPS[s]}%, var(--surface))`;

  return (
    <ChartFrame
      title={title}
      hideTitle={hideTitle}
      description={description}
      height={190}
      isEmpty={peak === 0}
      table={{
        columns: ["Day", ...Array.from({ length: 24 }, (_, h) => hourLabel(h))],
        rows: grid.map((row, d) => [weekdays[d] ?? DAYS[d], ...row]),
      }}
      className={className}
      {...state}
    >
      <div ref={ref} className="relative">
        <div className="grid grid-cols-[2rem_repeat(24,minmax(0,1fr))] gap-[2px]">
          {grid.map((row, d) => (
            <div key={d} className="contents">
              <span className="pr-1 text-[11px] leading-none text-ink-faint self-center">{weekdays[d] ?? DAYS[d]}</span>
              {row.map((v, h) => (
                <span
                  key={h}
                  className="aspect-square rounded-[3px]"
                  style={{ background: fill(step(v)) }}
                  onPointerEnter={(e) => {
                    const box = e.currentTarget.getBoundingClientRect();
                    const host = ref.current?.getBoundingClientRect();
                    setHover({ d, h, x: box.left - (host?.left ?? 0) + box.width / 2, y: box.top - (host?.top ?? 0) });
                  }}
                  onPointerLeave={() => setHover(null)}
                />
              ))}
            </div>
          ))}
          <span />
          {Array.from({ length: 24 }, (_, h) => (
            <span key={h} className="text-center text-[10px] text-ink-faint">
              {h % 6 === 0 ? hourLabel(h) : ""}
            </span>
          ))}
        </div>
        {hover ? (
          <ChartTooltip x={hover.x} y={hover.y} width={width}>
            <span className="font-semibold">
              {weekdays[hover.d] ?? DAYS[hover.d]} {hourLabel(hover.h)}
            </span>
            {" · "}
            {formatCount(grid[hover.d][hover.h])} {unit}
          </ChartTooltip>
        ) : null}
        <div className="mt-3 flex items-center justify-end gap-1.5 text-[11px] text-ink-faint">
          <span>{fewerLabel}</span>
          {[0, 1, 2, 3, 4].map((s) => (
            <span key={s} className="h-2.5 w-2.5 rounded-[2px]" style={{ background: fill(s) }} />
          ))}
          <span>{moreLabel}</span>
        </div>
      </div>
    </ChartFrame>
  );
}

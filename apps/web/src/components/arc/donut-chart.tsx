"use client";

/**
 * Parts of one whole: how calls ended, where credit went this month.
 *
 * Adapted from uiarc's `donut-chart` (MIT, see ./LICENSE). A donut only where there are
 * six parts or fewer and the whole is meaningful; anything past the sixth folds into
 * "Other" rather than taking a generated colour (dataviz: a seventh series is never a new
 * hue). The legend beside it carries each part's words and share, so the ring is never
 * read by colour alone, and the centre holds the total.
 */

import { useState } from "react";

import { ChartFrame, seriesColor, type ChartStateProps } from "./chart-core";
import { formatCount } from "@/components/ui";

export type DonutSegment = {
  label: string;
  value: number;
  /** Exact text for the legend and table (money via `formatINR`); defaults to the count. */
  display?: string;
};

export type DonutChartProps = ChartStateProps & {
  title: string;
  hideTitle?: boolean;
  description?: string;
  segments: DonutSegment[];
  /** The figure in the hole: the whole, formatted ("1,240 calls", "₹8,450.00"). */
  centerValue?: string;
  centerLabel?: string;
  otherLabel?: string;
  size?: number;
  labelColumn?: string;
  shareColumn?: string;
  className?: string;
};

const MAX_SEGMENTS = 6;

function fold(segments: DonutSegment[], otherLabel: string): DonutSegment[] {
  const positive = segments.filter((s) => s.value > 0);
  if (positive.length <= MAX_SEGMENTS) return positive;
  const kept = positive.slice(0, MAX_SEGMENTS - 1);
  const rest = positive.slice(MAX_SEGMENTS - 1);
  return [...kept, { label: otherLabel, value: rest.reduce((sum, s) => sum + s.value, 0) }];
}

function share(value: number, total: number): string {
  if (total <= 0) return "0%";
  const pct = (value / total) * 100;
  return pct > 0 && pct < 1 ? "<1%" : `${Math.round(pct)}%`;
}

export function DonutChart({
  title,
  hideTitle,
  description,
  segments,
  centerValue,
  centerLabel,
  otherLabel = "Other",
  size = 168,
  labelColumn = "Part",
  shareColumn = "Share",
  className,
  ...state
}: DonutChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const parts = fold(segments, otherLabel);
  const total = parts.reduce((sum, s) => sum + s.value, 0);
  const text = (s: DonutSegment) => s.display ?? formatCount(s.value);
  const r = size / 2 - 10;
  const stroke = 18;
  const circumference = 2 * Math.PI * r;
  // A 2px surface gap between parts, as an arc length.
  const gap = parts.length > 1 ? 2 : 0;
  let offset = 0;

  return (
    <ChartFrame
      title={title}
      hideTitle={hideTitle}
      description={description}
      height={size}
      isEmpty={total <= 0}
      table={{ columns: [labelColumn, "Value", shareColumn], rows: parts.map((s) => [s.label, text(s), share(s.value, total)]) }}
      className={className}
      {...state}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
        <div className="relative shrink-0" style={{ width: size, height: size }}>
          <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-muted)" strokeWidth={stroke} />
            {parts.map((s, i) => {
              const length = (s.value / total) * circumference;
              const dash = Math.max(0, length - gap);
              const node = (
                <circle
                  key={s.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={r}
                  fill="none"
                  stroke={seriesColor(i)}
                  strokeWidth={hover === i ? stroke + 4 : stroke}
                  strokeDasharray={`${dash} ${circumference - dash}`}
                  strokeDashoffset={-offset}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  className="motion-safe:transition-[stroke-width] motion-safe:duration-(--duration-fast)"
                />
              );
              offset += length;
              return node;
            })}
          </svg>
          <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
            <span className="text-heading tabular-nums text-ink">
              {hover !== null ? text(parts[hover]) : (centerValue ?? formatCount(total))}
            </span>
            <span className="text-meta text-ink-muted">{hover !== null ? parts[hover].label : centerLabel}</span>
          </div>
        </div>
        <ul className="min-w-0 grow basis-48 space-y-1.5">
          {parts.map((s, i) => (
            <li key={s.label} className="flex items-center gap-2 text-meta" onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: seriesColor(i) }} />
              <span className="min-w-0 flex-1 break-words text-ink">{s.label}</span>
              <span className="tabular-nums text-ink">{text(s)}</span>
              <span className="w-10 text-right tabular-nums text-ink-muted">{share(s.value, total)}</span>
            </li>
          ))}
        </ul>
      </div>
    </ChartFrame>
  );
}

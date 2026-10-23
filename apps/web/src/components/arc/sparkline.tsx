"use client";

/**
 * A word-sized trend line beside a figure: the shape of the last week, not its values.
 *
 * Adapted from uiarc's `sparkline` (MIT, see ./LICENSE). Kept: the line with its end dot.
 * Not kept: the per-character rolling caption, the draw-in on view and the scrubbing,
 * because a sparkline sits beside the number that matters and a reader who wants values
 * opens the full chart. It is therefore an image with a sentence for a name (`summary`),
 * not an interactive plot.
 */

import { formatCompact } from "./chart-core";

export type SparklineProps = {
  values: number[];
  /** What the line is: "Calls, last 7 days". Spoken with the first and last value. */
  label: string;
  /** Replaces the spoken sentence when the caller can say it better. */
  summary?: string;
  /** `brand` for the screen's own measure; `neutral` for context beside it. */
  tone?: "brand" | "neutral";
  /** Fills under the line with a 10% wash of its colour. */
  area?: boolean;
  height?: number;
  className?: string;
};

export function Sparkline({
  values,
  label,
  summary,
  tone = "brand",
  area = false,
  height = 28,
  className = "",
}: SparklineProps) {
  const clean = values.filter((v) => Number.isFinite(v));
  const spoken =
    summary ??
    (clean.length === 0
      ? `${label}: no data`
      : `${label}: from ${formatCompact(clean[0])} to ${formatCompact(clean[clean.length - 1])}`);
  if (clean.length < 2) {
    return (
      <span role="img" aria-label={spoken} className={`inline-block text-meta text-ink-faint ${className}`}>
        —
      </span>
    );
  }
  const width = 100;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  // 3px of headroom top and bottom so the 2px line and the end dot are never clipped.
  const pad = 3;
  const points = clean.map((v, i) => {
    const x = (i / (clean.length - 1)) * width;
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const colour = tone === "brand" ? "var(--series-1)" : "var(--text-faint)";
  const [endX, endY] = points[points.length - 1];
  return (
    <svg
      role="img"
      aria-label={spoken}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={`block h-7 w-24 overflow-visible ${className}`}
      style={{ height }}
    >
      {area ? (
        <path d={`${line} L${width},${height} L0,${height} Z`} fill={colour} fillOpacity={0.1} stroke="none" />
      ) : null}
      <path
        d={line}
        fill="none"
        stroke={colour}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* The end dot as a zero-length round-capped stroke: a <circle> would be squashed
          into an ellipse by the non-uniform viewBox scaling. */}
      <path
        d={`M${endX},${endY} L${endX},${endY}`}
        stroke={colour}
        strokeWidth={6}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

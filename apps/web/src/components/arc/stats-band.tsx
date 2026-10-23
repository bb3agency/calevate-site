"use client";

/**
 * The headline figures across the top of an analytics screen, each with its change and
 * its recent shape.
 *
 * Adapted from uiarc's `stats-band` (MIT, see ./LICENSE) as data in, `MetricRow` +
 * `Metric` out: the console has one KPI unit and this does not add a second. What the band
 * adds is the wiring — a sparkline per figure from its series, and the delta chip — so an
 * analytics screen passes data rather than assembling markup. Arc's world map, counting
 * digits and marketing-scale type are not carried over.
 */

import { Metric, MetricRow, type MetricDelta } from "@/components/console/metric";

import { Sparkline } from "./sparkline";

export type StatItem = {
  label: string;
  /** Already formatted: `formatCount`, `formatINR`, `formatDuration`. "—" when unknown. */
  value: string;
  /** The raw wire value, so a polled figure marks itself when it changes. */
  flashValue?: string | null;
  delta?: MetricDelta;
  /** The recent series for a sparkline; two points or more. */
  trend?: number[];
  hint?: string;
  tone?: "default" | "warn" | "danger";
};

export function StatsBand({
  items,
  label,
  className,
}: {
  items: StatItem[];
  /** Names the band as a region: "This week at a glance". */
  label?: string;
  className?: string;
}) {
  return (
    <MetricRow label={label} className={className}>
      {items.map((item) => (
        <Metric
          key={item.label}
          label={item.label}
          value={item.value}
          flashValue={item.flashValue}
          hint={item.hint}
          tone={item.tone}
          delta={item.delta}
          trend={item.trend && item.trend.length > 1 ? <Sparkline values={item.trend} label={item.label} /> : undefined}
        />
      ))}
    </MetricRow>
  );
}

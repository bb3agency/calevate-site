import type { StatItem } from "@/components/arc/stats-band";
import type { MetricDelta } from "@/components/console/metric";
import { formatDateShort } from "@/components/arc/ist-dates";
import { formatCount, formatDuration } from "@/components/ui";
import type { Stats, StatsMetric } from "@/lib/api/analytics";

type MetricKey = StatsMetric["key"];

const LABELS: Record<MetricKey, string> = {
  calls: "Calls",
  answered: "Answered",
  answer_rate_pct: "Answer rate",
  leads: "New leads",
  hot_leads: "Hot leads",
  avg_duration_s: "Average call length",
  talk_minutes: "Talk time",
};

/** Hints that say what a figure counts, where the label alone could be misread. */
const HINTS: Partial<Record<MetricKey, string>> = {
  answer_rate_pct: "Calls that reached a real conversation",
  avg_duration_s: "Completed calls",
  talk_minutes: "Minutes spent talking on answered calls",
};

/** "24 Oct" from an IST calendar day "2026-10-24", read and never re-parsed as an instant. */
export function istDayLabel(istDate: string): string {
  return formatDateShort(istDate).replace(/ \d{4}$/, "");
}

/** The server's decimal string as the figure a reader sees; "—" when nothing was measured. */
export function statValue(metric: StatsMetric): string {
  if (metric.value === null) return "—";
  switch (metric.key) {
    case "answer_rate_pct":
      return `${trimZero(metric.value)}%`;
    case "avg_duration_s":
      return formatDuration(Math.round(Number(metric.value)));
    case "talk_minutes":
      return `${trimZero(metric.value)} min`;
    default:
      return formatCount(Number(metric.value));
  }
}

/** "12.0" → "12"; "12.5" stays. The figures are counts and percentages, never money. */
function trimZero(value: string): string {
  return value.replace(/\.0+$/, "");
}

/**
 * The change against the previous window. A rate moves in percentage points ("4.5 points"),
 * because "+10%" of a 40% answer rate reads as 50%; everything else moves by the server's
 * own `change_pct`. Colour follows `higher_is_better`, never the sign alone.
 */
export function statDelta(metric: StatsMetric, context: string): MetricDelta | undefined {
  if (metric.key === "answer_rate_pct") {
    if (metric.value === null || metric.previous === null) return undefined;
    const points = Math.round((Number(metric.value) - Number(metric.previous)) * 10) / 10;
    return delta(points, `${formatPoints(Math.abs(points))} ${Math.abs(points) === 1 ? "point" : "points"}`, metric, context);
  }
  if (metric.change_pct === null) return undefined;
  const change = Number(metric.change_pct);
  return delta(change, `${trimZero(metric.change_pct.replace(/^[-+]/, ""))}%`, metric, context);
}

function formatPoints(value: number): string {
  return value.toLocaleString("en-IN", { maximumFractionDigits: 1 });
}

function delta(change: number, magnitude: string, metric: StatsMetric, context: string): MetricDelta {
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  return {
    text: direction === "flat" ? "No change" : `${direction === "up" ? "+" : "−"}${magnitude}`,
    direction,
    good: direction === "flat" ? undefined : (direction === "up") === metric.higher_is_better,
    context,
  };
}

/**
 * The stats band's items, in the order `keys` names them. A figure with no previous reading
 * says so in its hint instead of a change chip.
 */
export function statItems(
  stats: Stats,
  keys: MetricKey[],
  { context, trends = {} }: { context: string; trends?: Partial<Record<MetricKey, number[]>> },
): StatItem[] {
  const byKey = new Map(stats.metrics.map((metric) => [metric.key, metric]));
  return keys.flatMap((key) => {
    const metric = byKey.get(key);
    if (!metric) return [];
    const change = statDelta(metric, context);
    const nothingBefore = change === undefined && metric.value !== null && (metric.previous === null || Number(metric.previous) === 0);
    return [
      {
        label: LABELS[key],
        value: statValue(metric),
        flashValue: metric.value,
        delta: change,
        trend: trends[key],
        hint: nothingBefore ? `None ${context.replace(/^vs /, "in ")}` : HINTS[key],
      },
    ];
  });
}

import type { StatItem } from "@/components/arc/stats-band";
import type { MetricDelta } from "@/components/console/metric";
import { formatDateShort } from "@/components/arc/ist-dates";
import { formatCount, formatDecimal, formatDuration, formatINR, formatPercent } from "@/components/ui";
import type { Stats, StatsMetric } from "@/lib/api/analytics";
import { leadWords, type BusinessCapabilities } from "@/lib/businessCapabilities";

type MetricKey = StatsMetric["key"];

const LABELS: Record<MetricKey, string> = {
  calls: "Calls",
  answered: "Answered",
  answer_rate_pct: "Answer rate",
  leads: "New leads",
  hot_leads: "Reached a goal",
  avg_duration_s: "Average call length",
  talk_minutes: "Talk time",
  interested_rate_pct: "Interested rate",
  spent_inr: "Spent",
};

/**
 * The labels a business's own words change: "New leads" only for a business judged to sell,
 * else its interested callers (`leadWords`, the twin of `tenancy/caller_words`).
 */
export function businessLabels(caps: BusinessCapabilities): Partial<Record<MetricKey, string>> {
  if (caps.sells === true) return {};
  const words = leadWords(caps).leads;
  return { leads: words.charAt(0).toUpperCase() + words.slice(1) };
}

/**
 * A figure's label as the stats band shows it, for every other reader of the same figure
 * (Pip's view of the screen), so nobody is told "hot leads" where the band says "Reached a goal".
 */
export function metricLabel(key: MetricKey, caps?: BusinessCapabilities): string {
  return (caps ? businessLabels(caps)[key] : undefined) ?? LABELS[key];
}

/** Hints that say what a figure counts, where the label alone could be misread. */
const HINTS: Partial<Record<MetricKey, string>> = {
  answer_rate_pct: "Calls someone picked up",
  leads: "People who showed interest",
  hot_leads: "People whose call ended on a goal you set",
  avg_duration_s: "Completed calls",
  talk_minutes: "Minutes spent talking on answered calls",
  interested_rate_pct: "Of the people who answered",
  spent_inr: "What left your wallet",
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
    case "interested_rate_pct":
      return formatPercent(metric.value);
    case "spent_inr":
      return formatINR(metric.value);
    case "avg_duration_s":
      return formatDuration(Math.round(Number(metric.value)));
    case "talk_minutes":
      return `${formatDecimal(metric.value)} min`;
    default:
      return formatCount(Number(metric.value));
  }
}

/**
 * The change against the previous window. A rate moves in percentage points ("4.5 points"),
 * because "+10%" of a 40% answer rate reads as 50%; everything else moves by the server's
 * own `change_pct`. Colour follows `higher_is_better`, never the sign alone.
 */
export function statDelta(metric: StatsMetric, context: string): MetricDelta | undefined {
  if (metric.key === "answer_rate_pct" || metric.key === "interested_rate_pct") {
    if (metric.value === null || metric.previous === null) return undefined;
    const points = Math.round((Number(metric.value) - Number(metric.previous)) * 10) / 10;
    return delta(points, `${formatDecimal(Math.abs(points))} ${Math.abs(points) === 1 ? "point" : "points"}`, metric, context);
  }
  if (metric.change_pct === null) return undefined;
  const change = Number(metric.change_pct);
  return delta(change, formatPercent(metric.change_pct.replace(/^[-+]/, "")), metric, context);
}

function delta(change: number, magnitude: string, metric: StatsMetric, context: string): MetricDelta {
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  return {
    text: direction === "flat" ? "No change" : `${direction === "up" ? "+" : "−"}${magnitude}`,
    direction,
    // Spend is neither good nor bad news on its own (more calls cost more), so it is not
    // coloured; the server marks it `higher_is_better: false` only to say a rise is no win.
    good:
      direction === "flat" || metric.key === "spent_inr"
        ? undefined
        : (direction === "up") === metric.higher_is_better,
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
  {
    context,
    trends = {},
    caps,
  }: { context: string; trends?: Partial<Record<MetricKey, number[]>>; caps?: BusinessCapabilities },
): StatItem[] {
  const labels = { ...LABELS, ...(caps ? businessLabels(caps) : {}) };
  const byKey = new Map(stats.metrics.map((metric) => [metric.key, metric]));
  return keys.flatMap((key) => {
    const metric = byKey.get(key);
    if (!metric) return [];
    const change = statDelta(metric, context);
    const nothingBefore = change === undefined && metric.value !== null && (metric.previous === null || Number(metric.previous) === 0);
    return [
      {
        label: labels[key],
        value: statValue(metric),
        flashValue: metric.value,
        delta: change,
        trend: trends[key],
        hint: nothingBefore ? `None ${context.replace(/^vs /, "in ")}` : HINTS[key],
      },
    ];
  });
}

"use client";

import { BarChart } from "@/components/arc/bar-chart";
import type { Dashboard } from "@/lib/api/client";

import { istDayLabel } from "./analyticsFigures";

/**
 * Calls each day for the last 7 days, stacked by how they ended, from `daily_7d`.
 *
 * The four classes PARTITION `calls.status` — the API guarantees
 * `completed + no_answer + failed + in_flight === total` on every bucket — so a column's
 * stack adds up to that day's calls. A day with no calls stays in the list: the API
 * zero-fills it because a quiet day is a fact about that day.
 */
const DAY_CLASSES = [
  { key: "completed", label: "Completed" },
  { key: "no_answer", label: "No answer" },
  { key: "failed", label: "Failed" },
  { key: "in_flight", label: "Still running" },
] as const;

export function DailyCalls({ days }: { days: Dashboard["daily_7d"] }) {
  // A class with no calls all week adds a legend entry that names nothing on the plot.
  const shown = DAY_CLASSES.filter((cls) => days.some((day) => day[cls.key] > 0));
  return (
    <BarChart
      title="Calls each day"
      hideTitle
      description="Last 7 days, India time"
      labelColumn="Day"
      // `ist_date` is already an IST calendar day; it is read, never re-parsed as an instant.
      categories={days.map((day) => istDayLabel(day.ist_date))}
      series={shown.map((cls) => ({ label: cls.label, values: days.map((day) => day[cls.key]) }))}
      stacked
      height={180}
      empty="No calls in the last 7 days. Each day appears here as it happens."
    />
  );
}

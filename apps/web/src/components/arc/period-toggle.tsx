"use client";

/**
 * THE PERIOD SWITCH over a money or usage view: "This month" or "All time" (founder,
 * 24 Oct 2026: there are no monthly or annual plans, so uiarc's `billing-toggle` is
 * reshaped into this). It is `SegmentedControl` with the two periods named once, so every
 * screen that switches a credit or usage view says it the same way; "This month" means
 * the calendar month in India (D-709), which the screen's query must also use.
 */

import { SegmentedControl } from "@/components/interior/segmented-control";

export type Period = "month" | "all";

export function PeriodToggle({
  value,
  onChange,
  label = "Show",
  monthLabel = "This month",
  allLabel = "All time",
  className,
}: {
  value: Period;
  onChange: (value: Period) => void;
  /** The group's accessible name. */
  label?: string;
  monthLabel?: string;
  allLabel?: string;
  className?: string;
}) {
  return (
    <SegmentedControl
      label={label}
      className={className}
      value={value}
      onValueChange={(next) => onChange(next === "all" ? "all" : "month")}
      options={[
        { value: "month", label: monthLabel },
        { value: "all", label: allLabel },
      ]}
    />
  );
}

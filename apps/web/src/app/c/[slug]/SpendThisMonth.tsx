"use client";

import Link from "next/link";

import { Card, ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import type { UsagePanel, useUsage } from "@/lib/api/hooks";

/** Inside the dashboard's money block, which already draws the outline. */
const FLAT = "rounded-none border-0 shadow-none";

/**
 * What this month has cost so far — `month_charges_inr`, the SERVER's total of retainer,
 * extra minutes and any model upgrade (D-455). It is the same field the usage screen
 * prints as "Total so far" and the invoice books, so the three cannot disagree; nothing
 * here adds rupees. Loading is a skeleton and a failed read a refusal, never a "—" that
 * reads like "nothing spent".
 */
export function SpendThisMonth({
  usage,
  href,
}: {
  usage: ReturnType<typeof useUsage>;
  href: string;
}) {
  if (usage.isLoading) {
    return (
      <Card density="compact" title="Spend this month" className={FLAT}>
        <Skeleton rows={2} />
      </Card>
    );
  }
  if (usage.error || !usage.data) {
    return (
      <Card density="compact" title="Spend this month" className={FLAT}>
        <ProblemNotice
          error={usage.error ?? new Error("Your spend did not load.")}
          onRetry={() => void usage.refetch()}
        />
      </Card>
    );
  }
  return (
    <Metric
      className="py-4"
      label="Spend this month"
      value={formatINR(usage.data.month_charges_inr)}
      flashValue={usage.data.month_charges_inr}
      hint={
        <Link href={href} className="underline decoration-ink/30 underline-offset-2 hover:text-ink">
          {minutesHint(usage.data)}
        </Link>
      }
    />
  );
}

/**
 * The line under the figure. During a trial the figure is ₹0.00 because the period is on
 * us, so the line says that and what the calling was worth at the client's own rate
 * (`trial_absorbed_inr`, never our cost). "of 0 included" is dropped for a plan that
 * includes no minutes, where it reads as a limit already used up.
 */
function minutesHint(usage: UsagePanel): string {
  if (usage.trial.active) {
    return `${usage.minutes_used} min used, free during your trial (worth ${formatINR(usage.trial_absorbed_inr)})`;
  }
  if (usage.included_minutes === 0) return `${usage.minutes_used} min used`;
  return `${usage.minutes_used} min used of ${formatCount(usage.included_minutes)} included`;
}

"use client";

import Link from "next/link";

import { ProblemNotice, Skeleton, formatCount, formatDecimal, formatINR } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import type { UsagePanel, useUsage } from "@/lib/api/hooks";

import { MoneyRowPending } from "./moneyRow";

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
      <MoneyRowPending label="Spend this month">
        <Skeleton rows={2} />
      </MoneyRowPending>
    );
  }
  if (usage.error || !usage.data) {
    return (
      <MoneyRowPending label="Spend this month">
        <ProblemNotice
          error={usage.error ?? new Error("Your spend did not load.")}
          onRetry={() => void usage.refetch()}
        />
      </MoneyRowPending>
    );
  }
  return (
    <Metric
      className="py-4"
      label="Spend this month"
      value={formatINR(usage.data.month_charges_inr)}
      flashValue={usage.data.month_charges_inr}
      hint={
        <Link href={href} className="underline decoration-ink/30 underline-offset-2 hover:text-ink touch:inline-flex touch:min-h-11 touch:items-center">
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
    return `${formatDecimal(usage.minutes_used)} min free in trial (worth ${formatINR(usage.trial_absorbed_inr)})`;
  }
  if (usage.included_minutes === 0) return `${formatDecimal(usage.minutes_used)} min used`;
  return `${formatDecimal(usage.minutes_used)} min used of ${formatCount(usage.included_minutes)} included`;
}

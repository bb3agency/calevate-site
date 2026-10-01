"use client";

import Link from "next/link";

import { ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import { Panel } from "@/components/console/panel";
import type { useUsage } from "@/lib/api/hooks";

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
      <Panel title="Spend this month" className={FLAT}>
        <Skeleton rows={2} />
      </Panel>
    );
  }
  if (usage.error || !usage.data) {
    return (
      <Panel title="Spend this month" className={FLAT}>
        <ProblemNotice
          error={usage.error ?? new Error("Your spend did not load.")}
          onRetry={() => void usage.refetch()}
        />
      </Panel>
    );
  }
  return (
    <Metric
      className="p-4 sm:p-5"
      label="Spend this month"
      value={formatINR(usage.data.month_charges_inr)}
      flashValue={usage.data.month_charges_inr}
      hint={
        <Link href={href} className="underline decoration-ink/30 underline-offset-2 hover:text-ink">
          {usage.data.minutes_used} min used of {formatCount(usage.data.included_minutes)} included
        </Link>
      }
    />
  );
}

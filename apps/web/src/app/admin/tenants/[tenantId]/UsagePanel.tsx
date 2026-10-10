"use client";

import Link from "next/link";

import { MetricRow } from "@/components/admin/kit";
import { Metric } from "@/components/console/metric";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatCount, formatCountOf, formatINR } from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import { currentISTMonth } from "@/lib/api/invoice";
import { useTenantSpend, type TenantSpend } from "@/lib/api/spend";
import { useTenantTrial, type TrialStatus } from "@/lib/api/trials";
import type { CopilotFact } from "@/lib/copilot/types";

import { CostBreakdownList, costBreakdownFacts } from "./CostBreakdownList";

/**
 * USAGE ON THE OVERVIEW: what this client has used and what it cost us, trial or not.
 *
 * The margin card beside it is the call margin and leaves absorbed AI out by design
 * (D-127 G-3), so a trial client whose only activity is the assistant and their knowledge
 * read ₹0 everywhere on this page while the trial panel said otherwise. This reads the
 * Spend screen's `cost_all_in` (same request key as Spend for the current month) and the
 * trial panel's read, so the three screens show one set of numbers.
 */
export function UsagePanel({ tenantId }: { tenantId: string }) {
  const month = currentISTMonth();
  const spend = useTenantSpend(tenantId, month);
  const trial = useTenantTrial(adminSession(), tenantId);
  const all = spend.data?.cost_all_in ?? null;
  const t = trial.data ?? null;

  return (
    <Section
      title={`Usage · ${month}`}
      info="What this client used this month and what it cost us at our supplier rates, including the AI we absorb. Never shown to the client."
      action={
        <Link href={`/admin/tenants/${tenantId}/spend`} className={TEXT_ACTION}>
          Open spend
        </Link>
      }
    >
      {spend.error ? (
        <ProblemNotice error={spend.error} onRetry={() => void spend.refetch()} />
      ) : !spend.data ? (
        <Skeleton rows={3} />
      ) : (
        <div className="space-y-4">
          <MetricRow className="border-b-0 pb-0">
            <Metric
              label="Cost to us this month"
              value={all ? formatINR(all.total_inr) : "—"}
              hint="Calls and the AI we absorb"
            />
            <Metric
              label="AI assistant"
              value={all ? formatINR(all.assistant_inr) : "—"}
              hint={all ? formatCountOf(all.assistant_requests, "action") : undefined}
            />
            <Metric
              label="Calls this month"
              value={formatCount(spend.data.calls)}
              hint={`${spend.data.minutes_used} minutes`}
            />
            {t?.active ? (
              <Metric
                label="Free test-call minutes"
                value={
                  t.free_minutes === null
                    ? `${formatCount(t.minutes_used)} used`
                    : `${formatCount(Math.max(t.free_minutes - t.minutes_used, 0))} left`
                }
                hint={
                  t.free_minutes === null
                    ? "This trial has no minute limit"
                    : `${formatCount(t.minutes_used)} of ${formatCountOf(t.free_minutes, "minute")} used`
                }
              />
            ) : null}
          </MetricRow>
          {all && <CostBreakdownList breakdown={all} />}
          {t?.active && (
            <p className="text-meta text-ink-muted">
              On trial: {formatCountOf(t.days_remaining ?? 0, "day")} left. Cost to us since the
              trial began: {formatINR(t.cost_to_us_inr)}.
            </p>
          )}
        </div>
      )}
    </Section>
  );
}

/**
 * The same figures as copilot facts for the Overview's assistant. Reads share the panel's
 * query keys, so asking costs no request.
 */
export function useUsageFacts(tenantId: string): CopilotFact[] {
  const spend = useTenantSpend(tenantId, currentISTMonth());
  const trial = useTenantTrial(adminSession(), tenantId);
  return usageFacts(spend.data, spend.isError, trial.data);
}

export function usageFacts(
  spend: TenantSpend | undefined,
  spendFailed: boolean,
  trial: TrialStatus | null | undefined,
): CopilotFact[] {
  if (!spend?.cost_all_in) {
    return [
      {
        key: "usage_month",
        label: "Usage and cost to us this month",
        value: spendFailed ? "could not be read" : "still loading",
      },
    ];
  }
  const facts: CopilotFact[] = [
    { key: "usage_month", label: "Usage month (IST)", value: spend.month },
    { key: "usage_calls", label: "Calls this month", value: String(spend.calls) },
    { key: "usage_minutes", label: "Call minutes this month", value: spend.minutes_used },
    ...costBreakdownFacts("usage", "this month", spend.cost_all_in),
  ];
  if (trial?.active) {
    facts.push(
      {
        key: "trial_minutes",
        label: "Free test-call minutes used",
        value:
          trial.free_minutes === null
            ? `${trial.minutes_used} (no limit)`
            : `${trial.minutes_used} of ${trial.free_minutes}`,
      },
      { key: "trial_cost_inr", label: "Cost to us since the trial began (₹)", value: trial.cost_to_us_inr },
    );
  }
  return facts;
}

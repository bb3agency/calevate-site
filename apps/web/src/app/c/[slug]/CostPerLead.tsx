"use client";

import Link from "next/link";

import { Metric } from "@/components/console/metric";
import { ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { useCostPerResult, type CostWindow } from "@/lib/api/proof";
import { useBusinessCapabilities, type BusinessCapabilities } from "@/lib/businessCapabilities";

import { MoneyRowPending } from "./moneyRow";

const LEAD_LABEL = "Cost per lead, 7 days";

/** One figure from the 7-day window: its label, value and the count line under it. */
interface Figure {
  label: string;
  value: string;
  count: string;
}

/**
 * Which result the home screen prices. A business that sells nothing has no leads to buy
 * (its callers are users being helped), so it is priced by its own goal (`goal_labels`, the
 * outcomes the owner chose, as on Billing) or, with none chosen, by answered call. Every
 * other business, and one not yet judged, keeps cost per lead (D-944).
 */
export function costFigure(
  week: CostWindow,
  goalLabels: readonly string[],
  caps: Pick<BusinessCapabilities, "sells">,
): Figure {
  const count = (n: number, one: string, many: string) => `${formatCount(n)} ${n === 1 ? one : many}`;
  if (caps.sells === false && goalLabels.length > 0) {
    return {
      label: goalLabels.length === 1 ? `Cost per ${goalLabels[0]}, 7 days` : "Cost per goal reached, 7 days",
      value: week.per_goal_inr == null ? "None yet" : formatINR(week.per_goal_inr),
      count: count(week.goals_reached, "call", "calls"),
    };
  }
  if (caps.sells === false) {
    return {
      label: "Cost per answered call, 7 days",
      value: week.per_answered_call_inr == null ? "None yet" : formatINR(week.per_answered_call_inr),
      count: count(week.answered_calls, "answered call", "answered calls"),
    };
  }
  return {
    label: LEAD_LABEL,
    value: week.per_lead_inr == null ? "No leads yet" : formatINR(week.per_lead_inr),
    count: count(week.leads, "lead", "leads"),
  };
}

/**
 * Rupees per result over the last 7 days (D-944), inside the home screen's money block. A
 * lead is a person who showed interest, not everyone called (`crm/lead_definition` on the
 * server). Owner-only like every spend figure: a session without `billing:read` renders
 * nothing and never sends the read. The full card (7 or 30 days, per call and per goal
 * reached) is on the Billing screen the hint links to.
 */
export function CostPerLead({ session, href }: { session: Session; href: string }) {
  const me = useMe(session);
  const allowed = me.data?.permissions.includes("billing:read") === true;
  const cost = useCostPerResult(session, { enabled: allowed });
  const caps = useBusinessCapabilities();
  const pendingLabel = caps.sells === false ? "Cost per result, 7 days" : LEAD_LABEL;
  if (!allowed) return null;
  if (cost.error) {
    return (
      <MoneyRowPending label={pendingLabel}>
        <ProblemNotice error={cost.error} onRetry={() => void cost.refetch()} />
      </MoneyRowPending>
    );
  }
  if (!cost.data) {
    return (
      <MoneyRowPending label={pendingLabel}>
        <Skeleton rows={2} label="Working out what each result cost" />
      </MoneyRowPending>
    );
  }
  // An answer without the 7-day window has nothing to show here; a skeleton would spin forever.
  const week = cost.data.windows.find((w) => w.days === 7);
  if (!week) return null;
  const figure = costFigure(week, cost.data.goal_labels, caps);
  return (
    <Metric
      className="py-4"
      label={figure.label}
      value={figure.value}
      hint={
        <Link
          href={href}
          className="underline decoration-ink/30 underline-offset-2 hover:text-ink touch:inline-flex touch:min-h-11 touch:items-center"
        >
          {figure.count} for {formatINR(week.spent_inr)}
        </Link>
      }
    />
  );
}

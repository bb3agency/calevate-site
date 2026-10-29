"use client";

import Link from "next/link";

import { Metric } from "@/components/console/metric";
import { ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { useCostPerResult } from "@/lib/api/proof";

/**
 * Rupees per new lead over the last 7 days (D-944), inside the home screen's money block.
 * Owner-only like every spend figure: a session without `billing:read` renders nothing and
 * never sends the read. The full card (7 or 30 days, per call and per booking) is on the
 * Billing screen the hint links to.
 */
export function CostPerLead({ session, href }: { session: Session; href: string }) {
  const me = useMe(session);
  const allowed = me.data?.permissions.includes("billing:read") === true;
  const cost = useCostPerResult(session, { enabled: allowed });
  if (!allowed) return null;
  if (cost.error) {
    return (
      <div className="py-4">
        <ProblemNotice error={cost.error} onRetry={() => void cost.refetch()} />
      </div>
    );
  }
  if (!cost.data) return <Skeleton rows={2} label="Working out your cost per lead" />;
  // An answer without the 7-day window has nothing to show here; a skeleton would spin forever.
  const week = cost.data.windows.find((w) => w.days === 7);
  if (!week) return null;
  return (
    <Metric
      className="py-4"
      label="Cost per new lead, 7 days"
      value={week.per_lead_inr == null ? "No leads yet" : formatINR(week.per_lead_inr)}
      hint={
        <Link
          href={href}
          className="underline decoration-ink/30 underline-offset-2 hover:text-ink touch:inline-flex touch:min-h-11 touch:items-center"
        >
          {formatCount(week.leads_captured)} {week.leads_captured === 1 ? "lead" : "leads"} for{" "}
          {formatINR(week.spent_inr)}
        </Link>
      }
    />
  );
}

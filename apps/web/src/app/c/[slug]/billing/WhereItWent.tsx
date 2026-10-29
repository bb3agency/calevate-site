"use client";

import { useState } from "react";

import { DonutChart } from "@/components/arc/donut-chart";
import { PeriodToggle, type Period } from "@/components/arc/period-toggle";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatINR, hasNonZeroDigit } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { formatBillingMonth } from "@/lib/billingMonth";
import { useCreditUsage, type CreditUsagePeriod } from "@/lib/api/voiceTiers";

/**
 * Where the credit went, this IST month or over the wallet's whole life
 * (`/v1/billing/credit-usage`, owner-only like every spend figure).
 *
 * **THERE ARE EXACTLY FOUR OUTGOING PARTS AND MESSAGING IS NOT ONE.** Calls, phone number
 * rental (D-665), extra AI help and corrections are what debit the wallet; nothing debits
 * it for a WhatsApp message or an SMS, so a "Messaging" part would be a category invented
 * to look complete. A zero part is left out; the total always shows, because "nothing
 * spent" is itself an answer.
 *
 * Credit that lapsed unused is not spend: it is its own "Credit expired" line beside the
 * credit added, never a part of the donut or of `spent_inr`.
 *
 * **NO ARITHMETIC ON MONEY HAPPENS HERE.** `spent_inr` is the server's sum of the four
 * parts; every figure a reader sees is its string through `formatINR`. `Number()` is used
 * only to size the arcs.
 */
const PARTS: { key: keyof CreditUsagePeriod; label: string }[] = [
  { key: "calls_inr", label: "Calls" },
  { key: "number_rental_inr", label: "Phone number rental" },
  { key: "ai_assist_inr", label: "Extra AI help" },
  { key: "adjustments_inr", label: "Corrections" },
];

export function WhereItWent({ session }: { session: Session }) {
  const usage = useCreditUsage(session);
  const [period, setPeriod] = useState<Period>("month");
  const data = usage.data;
  const figures = data ? (period === "month" ? data.this_month : data.all_time) : undefined;
  const scope = data && period === "month" ? `in ${formatBillingMonth(data.month)}` : "since you started";

  return (
    <Section
      title="Where your credit went"
      action={<PeriodToggle value={period} onChange={setPeriod} />}
    >
      {usage.error ? (
        <ProblemNotice error={usage.error} onRetry={() => void usage.refetch()} />
      ) : !figures ? (
        <Skeleton rows={4} label="Loading where your credit went" />
      ) : !hasNonZeroDigit(figures.spent_inr) &&
        !hasNonZeroDigit(figures.added_inr) &&
        !hasNonZeroDigit(figures.expired_inr) ? (
        <EmptyState
          illustration={<EmptySketch kind="deliveries" />}
          message={period === "month" ? "Nothing has moved on your credit this month" : "Nothing has moved on your credit yet"}
          hint="What each part costs will show here."
        />
      ) : (
        <div className="space-y-4">
          <DonutChart
            title={`Where your credit went ${scope}`}
            hideTitle
            description={`Spent ${scope}`}
            labelColumn="Part"
            segments={PARTS.filter((part) => hasNonZeroDigit(String(figures[part.key]))).map((part) => {
              const value = String(figures[part.key]);
              return { label: part.label, value: Math.max(0, Number(value)), display: formatINR(value) };
            })}
            centerValue={formatINR(figures.spent_inr)}
            centerLabel="spent"
            empty={`Nothing spent ${scope}.`}
          />
          {hasNonZeroDigit(figures.added_inr) ? (
            <p className="text-body text-ink-muted">
              Credit added {scope}:{" "}
              <span className="font-semibold tabular-nums text-ink">{formatINR(figures.added_inr)}</span>
            </p>
          ) : null}
          {hasNonZeroDigit(figures.expired_inr) ? (
            <p className="text-body text-ink-muted">
              Credit expired {scope}:{" "}
              <span className="font-semibold tabular-nums text-ink">{formatINR(figures.expired_inr)}</span>
            </p>
          ) : null}
        </div>
      )}
    </Section>
  );
}

"use client";

import { useState } from "react";

import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useCostPerResult, type CostWindow } from "@/lib/api/proof";

/**
 * WHAT EACH RESULT COST (D-944): rupees per answered call, per new lead and per booking,
 * over the last 7 or 30 IST days. The rupees are what left the wallet; the server divides and
 * rounds, this screen only prints its strings. A figure with nothing to divide by says so
 * instead of showing ₹0. Owner-only like every spend figure: the read is not sent otherwise.
 */
export function CostPerResult({ session, allowed }: { session: Session; allowed: boolean | null }) {
  const [days, setDays] = useState<7 | 30>(30);
  const cost = useCostPerResult(session, { enabled: allowed === true });
  if (allowed !== true) return null;

  const window = cost.data?.windows.find((w) => w.days === days);
  return (
    <Section
      title="What each result cost"
      description={cost.data ? `Calls billed in ${cost.data.billing_step_seconds}-second steps.` : undefined}
      info={
        <p>
          Everything that left your credit in these days (calls, number rental, AI help),
          divided by what you got. A booking is a call your agent marked as wanting to buy
          or book.
        </p>
      }
      action={
        <SegmentedControl
          label="Period"
          value={String(days)}
          onValueChange={(next) => setDays(next === "7" ? 7 : 30)}
          options={[
            { value: "7", label: "7 days" },
            { value: "30", label: "30 days" },
          ]}
        />
      }
    >
      {cost.error ? (
        <ProblemNotice error={cost.error} onRetry={() => void cost.refetch()} />
      ) : !window ? (
        <Skeleton rows={2} label="Working out what each result cost" />
      ) : (
        <CostFigures window={window} />
      )}
    </Section>
  );
}

function each(value: string | null | undefined, count: number, noun: string): { value: string; hint: string } {
  return value == null
    ? { value: "None yet", hint: `No ${noun}s in this period` }
    : { value: formatINR(value), hint: `${formatCount(count)} ${count === 1 ? noun : `${noun}s`}` };
}

function CostFigures({ window }: { window: CostWindow }) {
  const call = each(window.per_answered_call_inr, window.answered_calls, "answered call");
  const lead = each(window.per_lead_inr, window.leads_captured, "new lead");
  const booked = each(window.per_booked_result_inr, window.booked_results, "booking");
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
      <Metric label="Spent" value={formatINR(window.spent_inr)} hint={`Last ${window.days} days`} />
      <Metric label="Per answered call" value={call.value} hint={call.hint} />
      <Metric label="Per new lead" value={lead.value} hint={lead.hint} />
      <Metric label="Per booking" value={booked.value} hint={booked.hint} />
    </div>
  );
}

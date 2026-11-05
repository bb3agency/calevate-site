"use client";

import Link from "next/link";
import { useState } from "react";

import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, Skeleton, formatCount, formatINR, hasNonZeroDigit } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useCostPerResult, type CostWindow } from "@/lib/api/proof";

/**
 * WHAT EACH RESULT COST (D-944): rupees per answered call, per lead and per goal reached,
 * over the last 7 or 30 IST days. A lead is a person who showed interest, not everyone
 * called, as an ad platform counts cost per lead. The goal is named by the owner's own call
 * outcomes (`goal_labels`); this screen never names it for them, and with none set it
 * links to where they are chosen. The server divides and rounds; a figure with nothing to
 * divide by says so instead of showing ₹0. Owner-only like every spend figure.
 */
export function CostPerResult({
  session,
  allowed,
  goalsHref,
}: {
  session: Session;
  allowed: boolean | null;
  /** The screen where the owner chooses which call results count as the goal. */
  goalsHref: string;
}) {
  const [days, setDays] = useState<7 | 30>(30);
  const cost = useCostPerResult(session, { enabled: allowed === true });
  if (allowed !== true) return null;

  const window = cost.data?.windows.find((w) => w.days === days);
  const labels = cost.data?.goal_labels ?? [];
  return (
    <Section
      title="What each result cost"
      description={cost.data ? `Calls billed in ${cost.data.billing_step_seconds}-second steps.` : undefined}
      info={
        <>
          <p>All credit used in these days (calls, number rental, AI help), divided by results.</p>
          <p>
            A lead is a person who became interested, hot or won, counted once. Everyone else
            your agent spoke to is not counted as a lead.
          </p>
          {labels.length > 0 && <p>{goalSentence(labels)}</p>}
        </>
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
        <CostFigures window={window} labels={labels} goalsHref={goalsHref} />
      )}
    </Section>
  );
}

function goalSentence(labels: readonly string[]): string {
  return `A goal is a call that ended as ${labels.map((l) => `"${l}"`).join(" or ")}.`;
}

/** Said in place of a per-result rupee figure when nothing was charged: "₹0 per lead" read
 *  as "leads are free" (e2e audit OB-14). */
export const NOTHING_CHARGED = { value: "—", hint: "No charges in this period" } as const;

function each(value: string | null | undefined, count: number, one: string, many: string, charged: boolean) {
  if (value == null) return { value: "None yet", hint: `No ${many} in this period` };
  if (!charged) return NOTHING_CHARGED;
  return { value: formatINR(value), hint: `${formatCount(count)} ${count === 1 ? one : many}` };
}

function CostFigures({
  window,
  labels,
  goalsHref,
}: {
  window: CostWindow;
  labels: readonly string[];
  goalsHref: string;
}) {
  const charged = hasNonZeroDigit(window.spent_inr);
  const call = each(window.per_answered_call_inr, window.answered_calls, "answered call", "answered calls", charged);
  const lead = each(window.per_lead_inr, window.leads, "lead", "leads", charged);
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
      <Metric label="Spent" value={formatINR(window.spent_inr)} hint={`Last ${window.days} days`} />
      <Metric label="Per answered call" value={call.value} hint={call.hint} />
      <Metric label="Per lead" value={lead.value} hint={lead.hint} />
      {labels.length === 0 ? (
        <Metric
          label="Per goal reached"
          value="No goal set"
          hint={
            <Link
              href={goalsHref}
              className="underline decoration-ink/30 underline-offset-2 hover:text-ink touch:inline-flex touch:min-h-11 touch:items-center"
            >
              Choose your goal
            </Link>
          }
        />
      ) : (
        <GoalFigure window={window} labels={labels} />
      )}
    </div>
  );
}

function GoalFigure({ window, labels }: { window: CostWindow; labels: readonly string[] }) {
  const goal = each(window.per_goal_inr, window.goals_reached, "call", "calls", hasNonZeroDigit(window.spent_inr));
  const label = labels.length === 1 ? `Per ${labels[0]}` : "Per goal reached";
  return <Metric label={label} value={goal.value} hint={goal.hint} />;
}

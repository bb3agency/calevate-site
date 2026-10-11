"use client";

import { useState } from "react";

import {
  FIELD_INLINE,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatCountOf,
  formatINR,
} from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { currentISTMonth } from "@/lib/api/invoice";
import { useTenant } from "@/lib/api/admin";
import {
  CHARGE_BASIS_COPY,
  isZeroMoney,
  marginPctLabel,
  useTenantSpend,
  type TenantSpend,
} from "@/lib/api/spend";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { CostBreakdownList, costBreakdownFacts } from "../CostBreakdownList";
import { SpendCapPanel } from "../SpendCapPanel";

import { Breakdown } from "./SpendBreakdown";

/**
 * SPEND — where this client's month made or lost us money, and the cap that can stop it.
 *
 * The operator's half of the exact computation the client reads at `/c/<slug>/spend`, so a
 * support call is two people looking at one attribution. Admin-realm by the response TYPE:
 * every `cost_inr` and `margin_inr` is `unit_cost_paid`, our supplier pricing, and
 * `GET /v1/billing/spend` declares no cost-shaped field at all.
 *
 * The headline figures are the server's, read verbatim, and nothing here adds two rupee
 * strings together. The margin shown is the margin on PAID calling: calls a free trial
 * covered were free by design, so their cost is its own line ("Trial calls we cover"), an
 * acquisition cost rather than a loss. D-12's all-in margin stays on the wire.
 *
 * `cost_currency_stated` is false only when a cost row converted a vendor figure in a
 * currency WE chose (OPERATIONS §2 gate 7). Attested INR rates assume nothing, so the
 * caveat appears only where it is true. No CLIENT-facing figure is affected.
 *
 * The spend cap lives here (D-661 Money › Spend): it is this client's money too, and its
 * recompute route binds its step-up to this tenant id, so it belongs on the client's own
 * pages rather than behind a picker on /admin/ops.
 */
export function SpendScreen({ tenantId }: { tenantId: string }) {
  const [month, setMonth] = useState(currentISTMonth);
  const spend = useTenantSpend(tenantId, month);
  const tenant = useTenant(tenantId).data;
  const data = spend.data;

  /*
   * ONE CLIENT'S MONTH, DECLARED TO THE ASSISTANT. `top_calls` is NOT declared: those rows
   * are individual calls, each a conversation with a person, and the summary answers every
   * question a margin screen is asked without naming one. `cost_currency_stated` travels
   * WITH the cost figures, so a margin is never quoted from a model that missed the caveat.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/spend",
    title: "Spend and margin",
    realm: "admin",
    fields: [
      {
        id: "tenant-spend-month",
        label: "Billing month",
        type: "text",
        value: month,
        writable: false,
        help: "IST billing month as YYYY-MM.",
      },
    ],
    facts: data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
          { key: "month", label: "Month", value: data.month },
          { key: "plan_tier", label: "Plan tier", value: data.plan_tier },
          { key: "charge_basis", label: "How calls are charged", value: data.charge_basis },
          { key: "calls", label: "Calls", value: String(data.calls) },
          { key: "minutes_used", label: "Minutes used", value: data.minutes_used },
          { key: "revenue_inr", label: "Charged to the client (₹)", value: data.revenue_inr },
          { key: "cost_inr", label: "What it cost us (₹)", value: data.cost_inr },
          {
            key: "trial_cost_inr",
            label: "Our cost of calls a free trial covered (₹), an acquisition cost",
            value: `${data.trial_cost_inr} across ${formatCountOf(data.trial_calls, "call")}`,
          },
          { key: "paid_cost_inr", label: "Our cost of paid calls (₹)", value: data.paid_cost_inr },
          {
            key: "paid_margin_inr",
            label: "Margin on paid calls (₹), trial cost excluded",
            value: data.paid_margin_inr,
          },
          {
            key: "paid_margin_pct",
            label: "Margin on paid calls (%)",
            value: marginPctLabel(data.paid_margin_pct, data.trial_in_month),
          },
          {
            key: "margin_inr",
            label: "Margin all in (₹), trial cost included",
            value: data.margin_inr,
          },
          {
            key: "cost_confidence",
            label: "Do the cost figures rest on a stated or attested currency",
            value: data.cost_currency_stated
              ? `yes — ${data.cost_currency ?? "rupees"}`
              : "NO. Some cost rows converted a vendor figure whose currency the vendor did not name, so those are scaled by our assumption.",
          },
          {
            // D-608: the KNOWLEDGE half of the absorbed AI cost is what an operator asks
            // about by name when a new client's first month looks alarming.
            key: "ai_assist",
            label: "AI we absorb for this client this month (₹), and the knowledge part of it",
            value: data.ai_assist
              ? `${data.ai_assist.used_inr} across ${formatCountOf(data.ai_assist.requests, "action")}, of which ${data.ai_assist.kb_used_inr} was preparing what they added (${formatCountOf(data.ai_assist.kb_requests, "job")})`
              : "none — this client ran no AI this month",
          },
          ...(data.cost_all_in ? costBreakdownFacts("all_in", "this month", data.cost_all_in) : []),
          {
            key: "itemisation_residual_inr",
            label: "Charge not attributable to any one call or agent (₹)",
            value: data.itemisation_residual_inr,
          },
          {
            key: "residual_reason",
            label: "Why there is a residual",
            value: data.residual_reason ?? "none recorded",
          },
          { key: "by_agent", label: "Agents with spend this month", value: String(data.by_agent.length) },
        ]
      : [
          { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
          {
            key: "board",
            label: "This client's month",
            value: spend.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="max-w-5xl space-y-10">
      <PageHeader
        title="Spend"
        description="What this client was charged, what it cost us, and the cap that can stop them."
        actions={
          <input
            type="month"
            value={month}
            // No future months: an empty 2027 board reads like a failure (ux-audit F-9a).
            max={currentISTMonth()}
            onChange={(event) => setMonth(event.target.value)}
            className={FIELD_INLINE}
            aria-label="Billing month"
          />
        }
      />

      {spend.error && <ProblemNotice error={spend.error} onRetry={() => void spend.refetch()} />}

      {/* §52: a skeleton is not a margin and a failed read is not a ₹0.00 month. */}
      {!data ? (
        spend.error ? null : <Skeleton rows={8} label="Loading this client's spend" />
      ) : (
        <SpendBoard data={data} />
      )}

      {tenant && (
        <SpendCapPanel tenantId={tenantId} slug={tenant.slug} directoryCapped={tenant.capped} />
      )}
    </div>
  );
}

function SpendBoard({ data }: { data: TenantSpend }) {
  const basis = lookup(CHARGE_BASIS_COPY, data.charge_basis) ?? {
    label: "How each call is charged",
    hint: "",
  };
  // The margin on PAID calling: a free trial's calls are an acquisition cost shown on their
  // own line, never a loss (the server's subtraction, not the browser's).
  const negative = data.paid_margin_inr.trim().startsWith("-");
  const trialCost = !isZeroMoney(data.trial_cost_inr);

  return (
    <div className="space-y-5">
      <div
        className={`grid grid-cols-2 gap-x-6 gap-y-5 ${trialCost ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}
      >
        <Metric label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
        <Metric
          label={trialCost ? "Our cost of paid calls" : "Our cost of calls"}
          value={formatINR(data.paid_cost_inr)}
        />
        {trialCost && (
          <Metric
            label="Trial calls we cover"
            value={formatINR(data.trial_cost_inr)}
            hint={`${formatCountOf(data.trial_calls, "free trial call")}, ${data.trial_minutes} minutes. An acquisition cost, not in the margin.`}
          />
        )}
        <Metric
          label="Margin"
          tone={negative ? "danger" : "default"}
          // Colour is never the only signal that a month is losing money (F-18).
          value={
            <>
              {negative && <span className="sr-only">Losing money: </span>}
              {formatINR(data.paid_margin_inr)}
            </>
          }
        />
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different facts. */}
        <Metric label="Margin %" value={marginPctLabel(data.paid_margin_pct, data.trial_in_month)} />
      </div>

      <p className="text-meta text-ink-muted">
        {data.plan_tier} · {data.minutes_used} minutes across{" "}
        {formatCountOf(data.calls, "call")}
        {data.trial_calls > 0 &&
          (data.trial_calls === data.calls
            ? ", all on a free trial"
            : `, ${formatCount(data.trial_calls)} of them on a free trial`)}
        {data.retainer_inr === null
          ? ", no monthly fee"
          : `, plus a ${formatINR(data.retainer_inr)} monthly fee`}
        . <strong className="font-semibold text-ink">{basis.label}</strong> — the client sees
        the same per-call figures on their own spend screen.{" "}
        {data.cost_currency_stated ? (
          <>
            Our cost is recorded in {data.cost_currency ?? "rupees"} at stated or attested
            rates.
          </>
        ) : (
          <>
            <strong className="font-semibold text-ink">Cost is scaled by an assumption.</strong>{" "}
            <InfoTip label="About the cost currency">
              At least one cost row converted a vendor figure whose currency the vendor&rsquo;s
              data did not name, so we treated it as{" "}
              {data.cost_currency ?? "our configured default"} — a figure we chose, not one the
              vendor stated. Rows marked * in the breakdown carry that assumption; no figure
              the client sees does, because a client is priced off minutes at their own rate.
            </InfoTip>
          </>
        )}
      </p>

      {data.residual_reason !== null && (
        <div className="border-l-2 border-warn py-1 pl-3 text-meta text-ink">
          The rows below account for {formatINR(data.itemised_charge_inr)} of{" "}
          {formatINR(data.period_charge_inr)} in calling charge — a residual of{" "}
          {formatINR(data.itemisation_residual_inr)} ({data.residual_reason}).
        </div>
      )}

      {data.unattributed && (
        <div className="border-l-2 border-line py-1 pl-3 text-meta text-ink-muted">
          {formatINR(data.unattributed.cost_inr)} of cost this month belongs to no call
          ({data.unattributed.minutes} minutes). The only unit that lands here is{" "}
          <span className="font-mono">number_rental</span>: our cost of the phone numbers we
          rent to this client. What they were charged for them is in the revenue above.
        </div>
      )}

      {/* ABSORBED DASHBOARD-AI COST (D-127 G-3), deliberately NOT in the margin above: it is
          metered per tenant but not billed, so folding it in would add cost with no matching
          revenue. Knowledge preparation is split out (D-608) because it is a different
          curve — a burst on the day they onboard, not a steady copilot spend. */}
      {data.ai_assist && (
        <section className="border-y border-line py-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-meta font-semibold text-ink">AI assistant — cost we absorb</h3>
            <p className="text-heading tabular-nums text-ink">
              {formatINR(data.ai_assist.used_inr)}
            </p>
          </div>
          <p className="mt-1 text-meta text-ink-muted">
            {formatCount(data.ai_assist.requests)}{" "}
            {data.ai_assist.requests === 1 ? "assist" : "assists"} this month —{" "}
            <strong className="font-semibold text-ink">not billed to the client</strong> and not
            part of the revenue, cost or margin above.{" "}
            <InfoTip label="About absorbed AI cost">
              Copilot, re-summarise and script drafting. Calevate absorbs this cost; the
              client sees their own AI usage on their AI-assistance screen, against a monthly
              allowance.
            </InfoTip>
          </p>
          <dl className="mt-3 flex flex-wrap items-baseline justify-between gap-2 border-t border-line pt-3">
            {/* Worded around `knowledgeClaims.test.ts`: this line is about what WE PAID, not
                about what the agent can do, so it names the three jobs and claims nothing
                about retrieval. */}
            <dt className="text-meta text-ink-muted">
              of which, preparing what they added (writing an English key beside
              non-English text, reading photographed pages, and indexing both)
            </dt>
            <dd className="text-body font-semibold tabular-nums text-ink">
              {formatINR(data.ai_assist.kb_used_inr)}
              <span className="ml-2 text-meta font-normal text-ink-muted">
                {formatCount(data.ai_assist.kb_requests)}{" "}
                {data.ai_assist.kb_requests === 1 ? "job" : "jobs"}
              </span>
            </dd>
          </dl>
        </section>
      )}

      {/* ALL IN: the calls above plus the AI we absorb, split by what it bought — the same
          reader as the trial panel's "cost to Calevate" and the Overview's usage card. */}
      {data.cost_all_in && (
        <section aria-labelledby="spend-all-in" className="space-y-2">
          <h3 id="spend-all-in" className="text-meta font-semibold text-ink">
            Cost to us this month, all in
          </h3>
          {data.ai_assist === null && (
            <p className="text-meta text-ink-muted">This client used no AI this month.</p>
          )}
          <CostBreakdownList breakdown={data.cost_all_in} />
        </section>
      )}

      <Breakdown data={data} />
    </div>
  );
}

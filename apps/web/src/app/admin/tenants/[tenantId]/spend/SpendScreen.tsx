"use client";

import { useState } from "react";

import {
  FIELD_INLINE,
  NOTICE_TONES,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { currentISTMonth } from "@/lib/api/invoice";
import { useTenant } from "@/lib/api/admin";
import {
  CHARGE_BASIS_COPY,
  useTenantSpend,
  type TenantSpend,
} from "@/lib/api/spend";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

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
 * The four headline figures are `margin_for_tenant`'s own, read verbatim: D-12's margin has
 * ONE definition, and nothing here adds two rupee strings together.
 *
 * `cost_currency_stated` is false whenever WE chose the currency because the vendor named
 * none (OPERATIONS §2 gate 7) — every row today — so the caveat is stated unconditionally
 * rather than only when something looks wrong. No CLIENT-facing figure is affected.
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
          { key: "margin_inr", label: "Margin (₹)", value: data.margin_inr },
          {
            key: "margin_pct",
            label: "Margin (%)",
            value: data.margin_pct ?? "nothing billed this month",
          },
          {
            key: "cost_confidence",
            label: "Do the cost figures rest on a currency the VENDOR stated",
            value: data.cost_currency_stated
              ? `yes — ${data.cost_currency ?? "unnamed"}`
              : "NO. We chose the currency because the vendor's payload names none, so every cost and margin above is scaled by our assumption.",
          },
          {
            // D-608: the KNOWLEDGE half of the absorbed AI cost is what an operator asks
            // about by name when a new client's first month looks alarming.
            key: "ai_assist",
            label: "AI we absorb for this client this month (₹), and the knowledge part of it",
            value: data.ai_assist
              ? `${data.ai_assist.used_inr} across ${data.ai_assist.requests} action(s), of which ${data.ai_assist.kb_used_inr} was preparing what they added (${data.ai_assist.kb_requests} job(s))`
              : "none — this client ran no AI this month",
          },
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
    <div className="space-y-6">
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
  const negative = data.margin_inr.trim().startsWith("-");

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
        <Metric label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
        <Metric label="Our cost" value={formatINR(data.cost_inr)} />
        <Metric
          label="Margin"
          tone={negative ? "danger" : "default"}
          // Colour is never the only signal that a month is losing money (F-18).
          value={
            <>
              {negative && <span className="sr-only">Losing money: </span>}
              {formatINR(data.margin_inr)}
            </>
          }
        />
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different facts. */}
        <Metric
          label="Margin %"
          value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
        />
      </div>

      <p className="text-xs text-ink-muted">
        {data.plan_tier} · {data.minutes_used} minutes across {formatCount(data.calls)} calls
        {data.retainer_inr === null
          ? ", no monthly fee"
          : `, plus a ${formatINR(data.retainer_inr)} monthly fee`}
        . <strong className="font-semibold text-ink">{basis.label}</strong> — the client sees
        the same per-call figures on their own spend screen.{" "}
        {data.cost_currency_stated ? (
          <>
            Our cost is recorded in {data.cost_currency ?? "the vendor's own currency"}, as the
            vendor stated it.
          </>
        ) : (
          <>
            <strong className="font-semibold text-ink">Cost is scaled by an assumption.</strong>{" "}
            <InfoTip label="About the cost currency">
              The vendor&rsquo;s data names no currency, so we treated it as{" "}
              {data.cost_currency ?? "our configured default"} — a figure we chose, not one the
              vendor stated. Every cost and margin figure on this page carries that assumption;
              no figure the client sees does, because a client is priced off minutes at their
              own rate.
            </InfoTip>
          </>
        )}
      </p>

      {data.residual_reason !== null && (
        <div className={`rounded-card border p-3 text-xs ${NOTICE_TONES.warn}`}>
          The rows below account for {formatINR(data.itemised_charge_inr)} of{" "}
          {formatINR(data.period_charge_inr)} in calling charge — a residual of{" "}
          {formatINR(data.itemisation_residual_inr)} ({data.residual_reason}).
        </div>
      )}

      {data.unattributed && (
        <div className={`rounded-card border p-3 text-xs ${NOTICE_TONES.neutral}`}>
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
        <section className="rounded-card border border-line bg-surface p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-[13px] font-semibold text-ink">AI assistant — cost we absorb</h3>
            <p className="text-lg font-bold tabular-nums text-ink">
              {formatINR(data.ai_assist.used_inr)}
            </p>
          </div>
          <p className="mt-1 text-xs text-ink-muted">
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
            <dt className="text-xs text-ink-muted">
              of which, preparing what they added (writing an English key beside
              non-English text, reading photographed pages, and indexing both)
            </dt>
            <dd className="text-sm font-semibold tabular-nums text-ink">
              {formatINR(data.ai_assist.kb_used_inr)}
              <span className="ml-2 text-xs font-normal text-ink-faint">
                {formatCount(data.ai_assist.kb_requests)}{" "}
                {data.ai_assist.kb_requests === 1 ? "job" : "jobs"}
              </span>
            </dd>
          </dl>
        </section>
      )}

      <Breakdown data={data} />
    </div>
  );
}

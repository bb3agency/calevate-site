"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
  formatIST,
} from "@/components/ui";
import { currentISTMonth } from "@/lib/api/invoice";
import {
  CHARGE_BASIS_COPY,
  useTenantSpend,
  type AgentSpend,
  type CallSpend,
  type TenantSpend,
} from "@/lib/api/spend";
import { lookup } from "@/lib/lookup";

/**
 * ONE CLIENT'S MONTH, BOTH DIRECTIONS — what they were charged, what we paid, the margin.
 *
 * The margin card on the client's own detail screen answers "how much"; this answers
 * "where". It is the operator's half of the exact computation the client reads at
 * `/c/<slug>/spend`, so the two screens itemise the same rupees and a support call is two
 * people looking at one attribution rather than two.
 *
 * ## WHY IT IS ADMIN-REALM AND STAYS THAT WAY
 *
 * Every `cost_inr` and `margin_inr` below is `unit_cost_paid` — our supplier pricing —
 * and a client who can see it is a client negotiating against it. The split is enforced
 * by the response TYPE rather than by this screen: `GET /v1/billing/spend` declares no
 * cost-shaped field at all, so there is no flag here to get wrong.
 *
 * ## THE FOUR HEADER FIGURES ARE `margin_for_tenant`'S OWN
 *
 * Read from the server verbatim, never recomputed: D-12's margin has ONE definition, and a
 * second one on the screen beside it is drift `billing/service.py` has already paid for
 * twice. Nothing on this page adds two rupee strings together — the residual, the totals
 * and the per-row margins are all the server's.
 *
 * ## THE HONESTY ABOUT OUR COST
 *
 * `cost_currency_stated` is false whenever WE chose the currency rather than the vendor
 * naming it (OPERATIONS §2 gate 7) — which is every row today, because the vendor's
 * execution object declares no currency at all. Every cost figure here is scaled by that
 * assumption and the screen says so, unconditionally, rather than letting an operator
 * quote a margin whose denominator is a guess. No CLIENT-facing figure is affected: a
 * client is priced off minutes at their own rate.
 */
export default function TenantSpendPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = use(params);
  const [month, setMonth] = useState(currentISTMonth);
  const spend = useTenantSpend(tenantId, month);
  const data = spend.data;

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to client
        </Link>
        <input
          type="month"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
          aria-label="Billing month"
        />
      </div>

      {spend.error && <ProblemNotice error={spend.error} onRetry={() => void spend.refetch()} />}

      {/* §52: a skeleton is not a margin and a failed read is not a ₹0.00 month. */}
      {!data ? (
        spend.error ? null : (
          <Skeleton rows={8} label="Loading this client's spend" />
        )
      ) : (
        <TenantSpendBoard data={data} />
      )}
    </div>
  );
}

function TenantSpendBoard({ data }: { data: TenantSpend }) {
  const basis = lookup(CHARGE_BASIS_COPY, data.charge_basis) ?? {
    label: "How each call is charged",
    hint: "",
  };
  const negative = data.margin_inr.trim().startsWith("-");

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
        <StatTile label="Our cost" value={formatINR(data.cost_inr)} />
        <div className="rounded-card border border-line bg-surface p-5">
          <p className="text-[13px] font-medium text-ink-muted">Margin</p>
          <p
            className={
              negative
                ? "mt-1 text-2xl font-bold tracking-tight tabular-nums text-rose-600 dark:text-rose-400"
                : "mt-1 text-2xl font-bold tracking-tight tabular-nums text-brand-strong dark:text-brand-bright"
            }
          >
            {formatINR(data.margin_inr)}
          </p>
        </div>
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different facts,
            and an operator acts differently on each. */}
        <StatTile
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
        the same per-call figures at /c/&lt;slug&gt;/spend.
      </p>

      {/* Unconditional, and phrased as what it IS rather than as a warning that only
          appears when something is wrong: every cost row today was priced in a currency
          we chose, so an operator who only saw this occasionally would read its absence
          as a guarantee. */}
      <div className={`rounded-card border p-3 text-xs ${NOTICE_TONES.neutral}`}>
        {data.cost_currency_stated ? (
          <>
            Our cost is recorded in {data.cost_currency ?? "the vendor's own currency"}, as the
            vendor stated it.
          </>
        ) : (
          <>
            <strong className="font-semibold">Cost is scaled by an assumption.</strong> The
            vendor&rsquo;s payload names no currency, so we treated it as{" "}
            {data.cost_currency ?? "our configured default"} (OPERATIONS §2 gate 7). Every
            cost and margin figure on this page carries that assumption; no figure the client
            sees does, because a client is priced off minutes at their own rate.
          </>
        )}
      </div>

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
          ({data.unattributed.minutes} minutes) — number rental and nothing else today.
        </div>
      )}

      <Card title="What our cost is made of" bodyClassName="p-0">
        {data.by_unit.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No metered units this month" />
          </div>
        ) : (
          <ScrollRegion label="Our cost by metered unit">
            <table className="w-full min-w-[420px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-4 py-3 font-semibold sm:px-6">Unit</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Quantity</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Our cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.by_unit.map((unit) => (
                  <tr key={unit.unit_type}>
                    <td className="px-4 py-3 sm:px-6">{unit.unit_type}</td>
                    {/* `qty` is not money and is deliberately not rounded like it —
                        seconds and character counts are published as the ledger holds
                        them. */}
                    <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
                      {unit.qty}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums sm:px-6">
                      {formatINR(unit.cost_inr)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      <Card title="By agent" bodyClassName="p-0">
        {data.by_agent.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No calls to attribute this month" />
          </div>
        ) : (
          <ScrollRegion label="Charge, cost and margin by agent">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-4 py-3 font-semibold sm:px-6">Agent</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Calls</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Charged</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Our cost</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.by_agent.map((agent) => (
                  <AgentSpendRow key={agent.agent_id ?? "unattributed"} agent={agent} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      <Card
        title="Costliest calls"
        bodyClassName="p-0"
        action={
          data.top_calls_truncated ? (
            <span className="text-xs text-ink-muted">
              The {formatCount(data.top_calls.length)} that cost us most, of{" "}
              {formatCount(data.calls)}.
            </span>
          ) : undefined
        }
      >
        {data.top_calls.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No calls this month" />
          </div>
        ) : (
          <ScrollRegion label="Costliest calls">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-4 py-3 font-semibold sm:px-6">When</th>
                  <th className="px-4 py-3 font-semibold sm:px-6">Agent</th>
                  <th className="px-4 py-3 font-semibold sm:px-6">Direction</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Charged</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Our cost</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.top_calls.map((call) => (
                  <CallSpendRow key={call.call_id} call={call} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>
    </div>
  );
}

/** An assumed cost currency, marked on the ROW that carries it (OPERATIONS §2 gate 7). */
function AssumedMark({ assumed }: { assumed: boolean }) {
  if (!assumed) return null;
  return (
    <abbr
      title="At least one cost row here was priced in a currency the vendor's payload did not state."
      className="ml-1 cursor-help text-ink-faint no-underline"
    >
      *
    </abbr>
  );
}

function AgentSpendRow({ agent }: { agent: AgentSpend }) {
  const negative = agent.margin_inr.trim().startsWith("-");
  return (
    <tr>
      <td className="px-4 py-3 sm:px-6">
        {agent.agent_name ?? (agent.agent_id ? "Unnamed agent" : "Not attributed to an agent")}
      </td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">{formatCount(agent.calls)}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {agent.minutes}
      </td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">
        {formatINR(agent.charged_inr)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {formatINR(agent.cost_inr)}
        <AssumedMark assumed={agent.cost_currency_assumed} />
      </td>
      <td
        className={
          negative
            ? "px-4 py-3 text-right font-semibold tabular-nums text-rose-600 sm:px-6 dark:text-rose-400"
            : "px-4 py-3 text-right font-semibold tabular-nums sm:px-6"
        }
      >
        {formatINR(agent.margin_inr)}
      </td>
    </tr>
  );
}

function CallSpendRow({ call }: { call: CallSpend }) {
  const negative = call.margin_inr.trim().startsWith("-");
  return (
    <tr>
      <td className="px-4 py-3 sm:px-6">{formatIST(call.started_at)}</td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{call.agent_name ?? "—"}</td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{call.direction ?? "—"}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">{call.minutes}</td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">{formatINR(call.charged_inr)}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {formatINR(call.cost_inr)}
        <AssumedMark assumed={call.cost_currency_assumed} />
      </td>
      <td
        className={
          negative
            ? "px-4 py-3 text-right font-semibold tabular-nums text-rose-600 sm:px-6 dark:text-rose-400"
            : "px-4 py-3 text-right font-semibold tabular-nums sm:px-6"
        }
      >
        {formatINR(call.margin_inr)}
      </td>
    </tr>
  );
}

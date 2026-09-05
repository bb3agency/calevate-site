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
import { useTenant } from "@/lib/api/admin";
import {
  CHARGE_BASIS_COPY,
  useTenantSpend,
  type AgentSpend,
  type CallSpend,
  type TenantSpend,
} from "@/lib/api/spend";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
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
  // WHICH client's rupees these are. The operator arrives from /admin/spend having just
  // scanned every client's rows, and this page used to never print a name — the
  // cross-tenant ambiguity ux-audit F-1 flagged as its top blocker. Same query key as
  // every sibling screen, so this costs no extra request. The spend board deliberately
  // does NOT wait on this read: a failed name lookup must not blank a money screen.
  const tenantQuery = useTenant(tenantId);
  const tenantName = tenantQuery.data?.name;
  const data = spend.data;

  /*
   * ONE CLIENT'S MONTH, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Scoped by the route, so this is the screen the fleet board deliberately sends people
   * to rather than shipping its own rows: here the tenant is named in the URL, in the
   * heading and in the declaration, and there is no second client's rupees in scope.
   *
   * `top_calls` IS NOT DECLARED. Those rows are individual calls, and a call is a
   * conversation with a person; the summary figures answer every question an operator asks
   * a margin screen ("what did this cost, where did it go, why is the residual so big")
   * without naming one.
   *
   * `cost_currency_stated` GOES WITH THE COST FIGURES AND NOT SEPARATELY. Every cost here
   * is scaled by an assumption WE made when the vendor named no currency (OPERATIONS §2
   * gate 7), and a margin quoted from a model that never saw the caveat is exactly hard
   * rule 11's "a REPORTED figure repeated as fact".
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
          { key: "client", label: "Client", value: tenantName ?? "not read yet" },
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
              : "NO. We chose the currency because the vendor's payload names none, so every cost and margin above is scaled by our assumption (OPERATIONS §2 gate 7).",
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
          { key: "client", label: "Client", value: tenantName ?? "not read yet" },
          {
            key: "board",
            label: "This client's month",
            value: spend.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href={`/admin/tenants/${tenantId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {tenantName ?? "Back to client"}
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-ink">Spend &amp; margin</h1>
        </div>
        <input
          type="month"
          value={month}
          // No future months: an empty 2027 board reads like a failure, not a question
          // nobody has asked yet (ux-audit F-9a).
          max={currentISTMonth()}
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
            {/* Colour is never the only signal that a month is losing money (F-18). */}
            {negative && <span className="sr-only">Losing money: </span>}
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
        the same per-call figures on their own spend screen.
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
            vendor&rsquo;s data names no currency, so we treated it as{" "}
            {data.cost_currency ?? "our configured default"} — a figure we chose, not one the
            vendor stated. Every cost and margin figure on this page carries that assumption;
            no figure the client sees does, because a client is priced off minutes at their
            own rate.
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
          ({data.unattributed.minutes} minutes). The only unit that can land here is{" "}
          <span className="font-mono">number_rental</span>, and nothing writes one —
          clients rent their numbers from their own operator, not from us.
        </div>
      )}

      {/* ABSORBED DASHBOARD-AI COST (D-127 G-3), on its own and deliberately NOT in the
          margin above. The re-summarise, the script draft and the in-app copilot are
          metered per tenant but not billed to the client, so they are neither revenue nor
          a call cost — folding them into the figures above would add cost with no matching
          revenue. This is where a client who runs the copilot but places no calls stops
          reading as a ₹0.00 month. Only rendered when there is something to show. */}
      {data.ai_assist && (
        <div className={`rounded-card border p-4 ${NOTICE_TONES.neutral}`}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-[13px] font-semibold text-ink">AI assistant — cost we absorb</p>
            <p className="text-lg font-bold tabular-nums text-ink">
              {formatINR(data.ai_assist.used_inr)}
            </p>
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            {formatCount(data.ai_assist.requests)}{" "}
            {data.ai_assist.requests === 1 ? "assist" : "assists"} this month (copilot,
            re-summarise and script drafting). Calevate absorbs this cost — it is{" "}
            <strong className="font-semibold text-ink">not billed to the client</strong> and is
            not part of the revenue, cost or margin above. The client sees their own AI usage
            on their AI-assistance screen, against a monthly allowance.
          </p>
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
      title="At least one cost row here was priced in a currency the vendor's data did not state."
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

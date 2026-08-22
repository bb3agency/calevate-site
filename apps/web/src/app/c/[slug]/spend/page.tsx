"use client";

import Link from "next/link";
import { use, useState } from "react";
import { Coins, PhoneCall, Timer } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  ScrollRegion,
  RestrictionNote,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { currentISTMonth } from "@/lib/api/invoice";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import {
  CHARGE_BASIS_COPY,
  RESIDUAL_REASON_COPY,
  useSpend,
  type AgentCharge,
  type CallCharge,
  type Spend,
} from "@/lib/api/spend";
import { lookup } from "@/lib/lookup";

/**
 * WHERE THE MONEY WENT — this month's calling charge, per agent and per call.
 *
 * The Usage screen answers "how much, and how much is left". This answers the question a
 * client asks the moment the first one has a number in it: **which of my agents, and
 * which of my calls, is that?** Until this screen the answer existed only in the admin
 * console — a client who wanted per-rupee attribution had to ask us for it — and Invoice
 * is a legal document about a closed month rather than a working breakdown of a live one.
 *
 * ## WHAT THIS SCREEN CANNOT SHOW, AND WHY IT IS NOT A SETTING
 *
 * Calevate's supplier cost and our margin. `GET /v1/billing/spend` declares no cost-shaped
 * field at ALL — `spend_routes.py` makes that a property of the response type
 * (`extra="forbid"`, no shared base with the admin model) rather than of a branch somebody
 * could invert, and a server-side test reads the model's own field list to keep it that
 * way. So there is nothing here to hide and nothing to leak: `unit_cost_paid` is our
 * supplier pricing, and a client who can see it is a client negotiating against it.
 *
 * Nor is it inferred. This screen performs NO arithmetic on money — every figure below is
 * printed exactly as the server sent it, including the residual, which the server computes
 * precisely so a browser never has to subtract two rupee strings to find it.
 *
 * ## MONEY IS A STRING AND STAYS ONE
 *
 * Hard rule 7's frontend shadow: every rupee and every minute arrives as an exact decimal
 * STRING and reaches the DOM as the same string. `formatINR` formats the DIGITS — it never
 * parses them — because `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998
 * on the screen a client checks against their own books.
 *
 * ## WHICH KIND OF NUMBER THE PER-CALL FIGURE IS
 *
 * `charge_basis` decides it, and the screen says which rather than picking one label for
 * both. On a prepaid account each row is the exact amount that call took off the balance;
 * on a managed plan each row is that call's SHARE of a month priced as a whole. Printing
 * "what this call cost you" over an allocation would be a claim the server did not make.
 *
 * ## THE RETAINER IS NOT DIVIDED ACROSS CALLS
 *
 * It buys the account rather than any particular minute, so it is published on its own and
 * is deliberately absent from every row below. A screen that spread it over calls would
 * make a quiet month's calls look expensive and a busy month's look cheap, for a charge
 * that did not move.
 */
export default function ClientSpendPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = useClientSession();
  const me = useMe(session);
  const [month, setMonth] = useState(currentISTMonth);
  const spend = useSpend(session, month);

  /**
   * `GET /v1/billing/spend` requires `billing:read`, which `staff` does not hold — spend
   * is an owner's business (SEC-COMP §5), the same gate `/usage` and `/invoice` apply. The
   * nav shows this screen to everyone, so without this a staff member reaches it and
   * collects a red 403 that reads like an outage.
   *
   * Read off `/v1/me` rather than from a role list this build would have to keep in step
   * with `core/rbac.py`. NOT `useWriteAccess`: that refuses every permission to an
   * impersonating operator (D-22), which is right for a control that writes and wrong here
   * — `billing:read` is not a mutating permission, an operator holds it, and blanking this
   * screen for the person on the support call would be a refusal the server never made.
   * While `/v1/me` is in flight nothing is refused, so the screen never flashes an
   * explanation it is about to withdraw.
   */
  const refused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  if (refused) {
    return (
      <RestrictionNote reason="Spending is limited to the account owner. Ask them to share this month's breakdown, or to give you owner access." />
    );
  }

  const data = spend.data;

  return (
    <div className="space-y-5 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Every rupee of this month&rsquo;s calling charge, against the agent and the call
          that produced it. Billing months run in Indian Standard Time.
        </p>
        <input
          type="month"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
          aria-label="Billing month"
        />
      </div>

      {spend.error && <ProblemNotice error={spend.error} onRetry={() => void spend.refetch()} />}

      {/* §52: loading is a skeleton and failure is a refusal, and neither is ₹0.00. "You
          spent nothing this month" is a claim about a month's business, and a 503 is not
          evidence for it. */}
      {!data ? (
        spend.error ? null : (
          <Skeleton rows={8} label="Loading this month's spend" />
        )
      ) : (
        <SpendBreakdown data={data} slug={slug} />
      )}
    </div>
  );
}

/**
 * The breakdown, given a month that ARRIVED.
 *
 * Takes `Spend` rather than the query envelope for `agents/[agentId]/page.tsx`'s reason:
 * every sentence below is a claim about this client's money, and a component that cannot
 * see `undefined` cannot make one out of it.
 */
function SpendBreakdown({ data, slug }: { data: Spend; slug: string }) {
  const basis = lookup(CHARGE_BASIS_COPY, data.charge_basis) ?? {
    label: "What each call added to this month",
    hint: "",
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {/* The month's CALLING charge, which is what the rows below itemise. The retainer
            is published separately and on purpose — see the file header. */}
        <StatTile
          label={`Calling charge · ${data.month}`}
          value={formatINR(data.period_charge_inr)}
          icon={<Coins className="h-5 w-5" />}
          hint="What your calls cost this month, before the monthly fee below."
        />
        <StatTile
          label="Monthly fee"
          value={data.retainer_inr === null ? "None" : formatINR(data.retainer_inr)}
          hint={
            data.retainer_inr === null
              ? "Your plan has no monthly fee — you pay for what you use."
              : "Buys the account rather than any particular call, so it is not split across the calls below."
          }
        />
        <StatTile
          label="Minutes used"
          value={data.minutes_used}
          icon={<Timer className="h-5 w-5" />}
          hint="Metered to the same precision your invoice bills."
        />
        <StatTile
          label="Calls"
          value={formatCount(data.calls)}
          icon={<PhoneCall className="h-5 w-5" />}
        />
      </div>

      {/* WHICH KIND OF NUMBER every figure below is — said once, above the tables, rather
          than repeated as a column header nobody reads. */}
      <p className="rounded-card border border-line bg-surface px-4 py-3 text-sm text-ink-muted">
        <strong className="font-semibold text-ink">{basis.label}.</strong>{" "}
        {basis.hint || "Ask your account manager how this month is priced."}
      </p>

      <Residual data={data} />

      <Card title="By agent" bodyClassName="p-0">
        {data.by_agent.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No calls to attribute this month"
              hint="Once your agents start taking and making calls, each one's share of the charge appears here."
            />
          </div>
        ) : (
          <ScrollRegion label="Charge by agent">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-4 py-3 font-semibold sm:px-6">Agent</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Calls</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Charge</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.by_agent.map((agent) => (
                  <AgentRow
                    key={agent.agent_id ?? "unattributed"}
                    agent={agent}
                    slug={slug}
                  />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      <Card
        title="Your costliest calls"
        bodyClassName="p-0"
        action={
          data.top_calls_truncated ? (
            <span className="text-xs text-ink-muted">
              The {formatCount(data.top_calls.length)} most expensive, of{" "}
              {formatCount(data.calls)} this month.
            </span>
          ) : undefined
        }
      >
        {data.top_calls.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No calls this month"
              hint="Calls appear here as soon as they are metered, most expensive first."
            />
          </div>
        ) : (
          <ScrollRegion label="Your costliest calls">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-4 py-3 font-semibold sm:px-6">When</th>
                  <th className="px-4 py-3 font-semibold sm:px-6">Agent</th>
                  <th className="px-4 py-3 font-semibold sm:px-6">Direction</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                  <th className="px-4 py-3 text-right font-semibold sm:px-6">Charge</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.top_calls.map((call) => (
                  <CallRow key={call.call_id} call={call} slug={slug} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>
    </div>
  );
}

/**
 * Why the rows do not add up to the charge at the top.
 *
 * Rendered ONLY when the server says there is something to explain: `residual_reason` is
 * `null` whenever the residual is ₹0.00, so this panel cannot appear over a month whose
 * parts already sum. An unrecognised reason prints its own code rather than vanishing —
 * a client can quote it to their account manager, which is worth more than a blank.
 */
function Residual({ data }: { data: Spend }) {
  if (data.residual_reason === null) return null;
  const sentence =
    lookup(RESIDUAL_REASON_COPY, data.residual_reason) ??
    `Your account manager can explain this month's breakdown (${data.residual_reason}).`;
  return (
    <div className={`rounded-card border p-4 text-sm ${NOTICE_TONES.neutral}`}>
      <p className="font-semibold">
        The calls below add up to {formatINR(data.itemised_charge_inr)} of{" "}
        {formatINR(data.period_charge_inr)}
      </p>
      <p className="mt-1 text-ink-muted">{sentence}</p>
      <p className="mt-1 text-ink-muted">
        Difference: {formatINR(data.itemisation_residual_inr)}.
      </p>
    </div>
  );
}

/**
 * One agent's share. Links to the agent when there is one to link to.
 *
 * `agent_id` is null for a call whose agent row is unreadable — a LEFT JOIN gap the
 * response types honestly rather than papering over — and that row is named as what it is
 * rather than dropped, because dropping it would make the column stop adding up with
 * nothing on screen to say why.
 */
function AgentRow({ agent, slug }: { agent: AgentCharge; slug: string }) {
  const { href } = useClientRealm();
  return (
    <tr>
      <td className="px-4 py-3 sm:px-6">
        {agent.agent_id ? (
          <Link
            href={href(`/c/${slug}/agents/${agent.agent_id}`)}
            className="font-medium text-ink underline underline-offset-2 hover:text-brand-strong"
          >
            {agent.agent_name ?? "Unnamed agent"}
          </Link>
        ) : (
          <span className="text-ink-muted">Not attributed to an agent</span>
        )}
      </td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">{formatCount(agent.calls)}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {agent.minutes}
      </td>
      <td className="px-4 py-3 text-right font-semibold tabular-nums sm:px-6">
        {formatINR(agent.charged_inr)}
      </td>
    </tr>
  );
}

/** One call, and what it added to this month's bill. */
function CallRow({ call, slug }: { call: CallCharge; slug: string }) {
  const { href } = useClientRealm();
  return (
    <tr>
      <td className="px-4 py-3 sm:px-6">
        <Link
          href={href(`/c/${slug}/calls/${call.call_id}`)}
          className="font-medium text-ink underline underline-offset-2 hover:text-brand-strong"
        >
          {/* `formatIST` prints "—" for a call that never started, which is the honest
              rendering of a nullable timestamp and keeps the link usable either way. */}
          {formatIST(call.started_at)}
        </Link>
      </td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{call.agent_name ?? "—"}</td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{call.direction ?? "—"}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">{call.minutes}</td>
      <td className="px-4 py-3 text-right font-semibold tabular-nums sm:px-6">
        {formatINR(call.charged_inr)}
      </td>
    </tr>
  );
}

"use client";

/**
 * Where every rupee went — the three reads over one server-side attribution.
 *
 * - the client: `GET /v1/billing/spend`                    — what THEY were charged
 * - ops, one client: `GET /v1/admin/tenants/{id}/spend`     — the same, plus what WE paid
 * - ops, the fleet: `GET /v1/admin/spend`                   — one row per live client
 *
 * ONE computation behind all three (`billing/attribution.py::period_attribution`), so an
 * operator reading a client's page and the client reading their own are looking at the
 * same rupees. The hooks are three thin fetches of three shapes rather than one shape
 * with a flag, and that mirrors the server deliberately.
 *
 * ## THE SPLIT IS THE POINT OF THIS MODULE
 *
 * `SpendOut` — the client's — DECLARES NO COST OR MARGIN FIELD, and `spend_routes.py`
 * makes that a property of the type (`extra="forbid"`, no shared base class) rather than
 * of a branch somebody could invert. `unit_cost_paid` is our supplier pricing, and a
 * client who can see it is a client negotiating against it. Nothing in this module and no
 * screen reading `Spend` may compute, infer or display a cost or a margin: there is no
 * field to read, no second request to make, and inferring one from a charge is the same
 * disclosure by arithmetic. `TenantSpend` and `FleetSpend` carry both directions and are
 * ADMIN-REALM ONLY — they go through `adminSession()`, which the client realm has no way
 * to construct.
 *
 * ## MONEY
 *
 * Every rupee and every minute on all three shapes is an exact decimal STRING (hard rule
 * 7's frontend shadow) and must stay one all the way to the DOM: `Number("10159.00")` is
 * how ₹10,159.00 becomes ₹10,158.999999999998 on the screen a client checks against their
 * own books. `formatINR` formats the digits and never parses them.
 *
 * Nothing here re-derives a total. The server publishes `itemised_charge_inr` and
 * `itemisation_residual_inr` precisely so a screen never has to add `by_agent` up — and a
 * browser that summed them would be a second implementation of a bill, in floats.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * The CLIENT's month. No cost field, no margin field — see the module header.
 *
 * `charge_basis` decides what kind of number every per-call figure is and the screen has
 * to say which: `wallet_debit` is the exact amount taken off a prepaid balance for that
 * call, `allocated` is that call's share of a month priced as a whole. They are different
 * claims and a screen that prints one label for both is making the wrong one half the time.
 */
export type Spend = Schemas["SpendOut"];
export type AgentCharge = Schemas["AgentChargeOut"];
export type CallCharge = Schemas["CallChargeOut"];

/** One client's month, BOTH directions. Admin realm only. */
export type TenantSpend = Schemas["TenantSpendOut"];
export type AgentSpend = Schemas["AgentSpendOut"];
export type CallSpend = Schemas["CallSpendOut"];
export type UnitSpend = Schemas["UnitSpendOut"];

/** Every live client's month, worst margin first. Admin realm only. */
export type FleetSpend = Schemas["FleetSpendOut"];
export type FleetTenant = Schemas["FleetTenantOut"];

/**
 * The month query string all three share, so no two callers can key their cache
 * differently — `invoice.ts::monthQuery`'s reason, one endpoint family over.
 */
function monthQuery(month?: string): string {
  return month ? `?month=${encodeURIComponent(month)}` : "";
}

/**
 * A client reading their OWN spend.
 *
 * No tenant parameter, and that is the server's design rather than an omission: the
 * tenant comes from the principal and the session is RLS-scoped to it, so another
 * account's month is not merely forbidden but unaddressable.
 *
 * `billing:read`, which owners hold and staff do not — the same gate `/v1/usage` and
 * `/v1/billing/invoice` apply, and the same one the page checks before rendering so a
 * staff member meets a sentence rather than a red 403 that reads like an outage.
 */
export function useSpend(session: Session, month?: string): UseQueryResult<Spend> {
  return useQuery({
    queryKey: ["spend", session.orgSlug, month ?? "current"],
    queryFn: () => apiRequest<Spend>(session, `/v1/billing/spend${monthQuery(month)}`),
  });
}

/** Ops reading one client's month, both directions. */
export function useTenantSpend(tenantId: string, month?: string): UseQueryResult<TenantSpend> {
  return useQuery({
    queryKey: ["admin", "spend", tenantId, month ?? "current"],
    queryFn: () =>
      apiRequest<TenantSpend>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/spend${monthQuery(month)}`,
      ),
    enabled: Boolean(tenantId),
  });
}

/**
 * The fleet board: one row per live client, worst margin first.
 *
 * The server walks every live client's month one `tenant_session` at a time and NOTHING
 * TRUNCATES — hiding the client at the bottom of a money board defeats the board — so
 * this read is deliberately slower than the rest of the console and is not polled.
 */
export function useFleetSpend(month?: string): UseQueryResult<FleetSpend> {
  return useQuery({
    queryKey: ["admin", "fleet-spend", month ?? "current"],
    queryFn: () => apiRequest<FleetSpend>(adminSession(), `/v1/admin/spend${monthQuery(month)}`),
  });
}

/**
 * What `charge_basis` MEANS, in the client's words — one table, read by both realms.
 *
 * The label and the sentence live together because they are one claim: an operator on the
 * phone to a client must be reading the same explanation of "allocated" that the client
 * is looking at, and two spellings of it is where a support call goes wrong.
 */
export const CHARGE_BASIS_COPY: Record<string, { label: string; hint: string }> = {
  wallet_debit: {
    label: "What each call took off your balance",
    hint: "Your account is prepaid, so each call is charged as it ends and the figure beside it is the exact amount that came off your balance.",
  },
  allocated: {
    label: "Each call's share of this month",
    // "AT THE RATE THAT MINUTE CARRIED" IS NOT A FLOURISH — the allocation weight stopped
    // being length alone when D-455 landed. `billing/attribution.py::_rung_rate` adds the
    // plan's `llm_model_surcharge` to the minutes a model the CLIENT chose ran on, which
    // is deliberate: it points this breakdown at the agent that actually incurred the
    // upgrade. A hint that still said "by how long each one ran, at your own rate" would
    // leave an owner unable to explain why one agent's calls carry more than another's of
    // the same length — the exact question this screen exists to answer.
    hint: "Your plan prices the month as a whole, so we split this month's calling charge across your calls — by how long each one ran, and at the rate those minutes carried. An agent you put on a dearer AI model carries its extra per-minute charge here, so the share lands on the agent that ran it.",
  },
};

/**
 * Why the itemised rows do not add up to the month's charge — the server's closed
 * vocabulary, in the words an owner can act on.
 *
 * `residual_reason` is `null` whenever the residual IS zero, so a sentence here is only
 * ever rendered when there is something to explain. An unrecognised reason falls through
 * to the code itself rather than vanishing: a client can quote it to their account
 * manager, which is the fallback direction `lib/agentState.ts` argues for the same class
 * of bare wire string.
 */
export const RESIDUAL_REASON_COPY: Record<string, string> = {
  // The prepaid basis: each row is the exact debit that call took off the balance, so
  // nothing is bent to make the column add up (`_allocate_charges` argues why — a figure
  // that disagreed with the wallet history would break the one document a prepaid client
  // can check this against). What is left over is per-call rounding plus anything charged
  // to the account this month that was not charged call by call.
  prepaid_wallet_vs_panel:
    "Each call below shows exactly what it took off your balance, so the rows are not rounded to make them add up. The difference is that rounding, plus anything charged to your account this month that was not charged call by call — your invoice itemises those.",
  // The managed basis with no weight to divide by: nothing can carry a share, so the
  // whole charge is published as the residual rather than spread over calls that did not
  // earn it.
  no_billable_minutes:
    "None of this month's calls carry billable minutes yet, so there is nothing to split this month's charge across. The charge above is right; the breakdown fills in as calls are metered.",
};

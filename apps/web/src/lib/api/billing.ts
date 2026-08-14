"use client";

/**
 * Prepaid wallet top-ups (D-34, D-98).
 *
 * Two hooks, and a deliberate absence.
 *
 * `useTopUpCapability` asks the server what it can do BEFORE the form is offered. That
 * is D-75's shape (`sheets_delivery_available`): the capability is a RENDERING HINT and
 * never the check — `POST /v1/billing/topups/intent` asks the same selector server-side
 * and remains the authority, so a stale hint costs a refusal and never a payment. It
 * exists because without it the top-up form was offered on every deployment and refused
 * on every deployment: `PAYMENT_PROVIDER` is unset by default, so `payments_not_configured`
 * was the only answer this control could ever get. Offering a control that cannot work is
 * §52's defect one step earlier than §52 usually catches it.
 *
 * `useTopUpIntent` prices the top-up, binds it to the tenant and — on a deployment
 * holding the Razorpay API secret — returns the provider's `order_id`. **No deployment
 * holds it**: no Razorpay account has been provisioned, so `provider_order_id` is null
 * and `provider_order_pending` is true, exactly as before, now for a named reason
 * (`no_api_secret`) rather than for a missing feature.
 *
 * THE ABSENCE: there is still no `useCompleteTopUp` and no checkout widget. Razorpay's
 * `checkout.js` is a THIRD unverified vendor surface and a supply-chain decision (hard
 * rule 9), and it would not be the source of truth in any case — the wallet is credited
 * by the signed webhook, never by the browser's callback. So an order id is rendered as
 * a reference to quote, and the screen says plainly that there is no checkout here.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * `provider_order_id` and `provider_order_pending` are REQUIRED on the wire, and that is
 * load-bearing rather than tidy. Their Pydantic models carry no default precisely so the
 * generated types are required: with a default they would generate `field?: T`, and
 * `provider_order_id === null` (there is no order) would become indistinguishable from
 * `undefined` (the server did not say) — rendering our own ignorance as one of the
 * server's answers. That is the trap this repository has hit four times.
 */
export type TopUpIntent = Schemas["TopUpIntentOut"];
export type TopUpCapability = Schemas["TopUpCapabilityOut"];

/**
 * The bounds the server enforces (`MIN_TOPUP_INR` / `MAX_TOPUP_INR`), mirrored here
 * only to hint the input. The refusal is `topup_amount_out_of_range` and it arrives as
 * problem+json with its own message — these constants shape the form, they do not
 * decide anything, and the screen still renders the server's answer if they drift.
 */
export const MIN_TOPUP_INR = 100;
export const MAX_TOPUP_INR = 100_000;

/**
 * The plans that HAVE a wallet. Read from the server's `plan_tier` rather than guessed
 * from a null balance: a managed (invoiced) tenant is not "a prepaid tenant with no
 * credit", it is a tenant with nothing to top up, and offering it a top-up form earns
 * a `topup_not_available` refusal after the click instead of before it.
 */
export const PREPAID_TIERS = ["self_serve", "trial"] as const;

export function isPrepaid(planTier: string | undefined): boolean {
  return PREPAID_TIERS.includes(planTier as (typeof PREPAID_TIERS)[number]);
}

/**
 * Money crosses the wire as a STRING (hard rule 7). The API's `amount_inr` accepts a
 * JSON number too, but sending one would put a rupee amount through a binary float on
 * the way out — the exact thing the string form exists to prevent.
 */
export function useTopUpIntent(session: Session) {
  return useMutation({
    mutationFn: (amountInr: string) =>
      apiRequest<TopUpIntent>(session, "/v1/billing/topups/intent", {
        method: "POST",
        body: { amount_inr: amountInr },
      }),
  });
}

/**
 * What this deployment can do about money, asked before the click.
 *
 * `retry: false` deliberately. This decides whether a CONTROL is offered, so a failure
 * must land on the screen as a refusal quickly rather than be masked by three silent
 * retries during which the panel shows a skeleton that is really an error. The answer
 * changes only when someone edits the environment, so it is cached for the session
 * rather than re-fetched per mount.
 */
export function useTopUpCapability(session: Session) {
  return useQuery({
    queryKey: ["billing", "topup-capability"],
    queryFn: () => apiRequest<TopUpCapability>(session, "/v1/billing/topups/capability"),
    retry: false,
    staleTime: Infinity,
  });
}

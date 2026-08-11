"use client";

/**
 * Prepaid wallet top-ups (D-34).
 *
 * One hook, and a deliberate absence: there is no `useCompleteTopUp`, because the
 * server cannot yet create the provider-side order. `POST /v1/billing/topups/intent`
 * prices the top-up, binds it to the tenant and hands back a receipt, and returns
 * `provider_order_id: null` with `provider_order_pending: true` — creating the
 * Razorpay order is a server-to-server call with credentials this deployment does not
 * hold (`billing/payment_routes.py`).
 *
 * So the intent is real (the amount is validated, the receipt is minted, the notes
 * carry the tenant the webhook will credit) and the payment is not. Every consumer of
 * this module has to say so; see the Usage screen, which renders the reference as
 * something to quote on a bank transfer rather than as a checkout that got stuck.
 */

import { useMutation } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TopUpIntent = Schemas["TopUpIntentOut"];

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

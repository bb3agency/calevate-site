"use client";

/**
 * Prepaid wallet top-ups (D-34, D-98).
 *
 * Four hooks, and a deliberate absence that survived the checkout landing.
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
 * holding the Razorpay API secret — returns the provider's `order_id` and everything else
 * Checkout needs. On a deployment without that secret `provider_order_id` is null and
 * `provider_order_pending` is true, for a named reason (`no_api_secret`), and the screen
 * renders the reference to quote on a bank transfer instead.
 *
 * `useConfirmTopUp` closes the third side. It posts the three fields Checkout hands the
 * browser back to `POST /v1/billing/topups/callback`, where the signature is verified with
 * the key secret — **on the server, because that is the only place the secret exists**.
 * THE ABSENCE THAT REMAINS, and it is the important one: this hook does not credit
 * anything and does not report a balance. `CheckoutCallbackOut.credit_pending` is
 * hard-coded `true` server-side because the callback carries no amount and no tenant; the
 * wallet is moved by the signed webhook and by nothing else. So the success branch
 * invalidates the balance reads and says "received, updating" — it never asserts a figure
 * the API has not sent, which is the same honesty `provider_order_pending` keeps.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { capsKey } from "./caps";
import { apiRequest, type Session } from "./client";
import { walletAttemptsKey, walletKey, walletLedgerKey } from "./wallet";
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
/** The three fields Razorpay Checkout hands back, named exactly as the provider names them. */
export type CheckoutCallback = Schemas["CheckoutCallbackIn"];
export type CheckoutConfirmation = Schemas["CheckoutCallbackOut"];
export type TopUpCapability = Schemas["TopUpCapabilityOut"];
export type CreditPack = Schemas["CreditPackOut"];
export type CreditPacks = Schemas["CreditPacksOut"];

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
 *
 * MIRRORS `apps/api/billing/rates.py::PREPAID_TIERS` and must move with it — `prepaid`
 * joined both with D-521, which made it the default tier, so the invoiced screen this
 * list selects is now the rare case rather than the common one.
 */
export const PREPAID_TIERS = ["prepaid", "self_serve", "trial"] as const;

export function isPrepaid(planTier: string | undefined): boolean {
  return PREPAID_TIERS.includes(planTier as (typeof PREPAID_TIERS)[number]);
}

/**
 * A top-up is priced EITHER by a pack (`packId`, amount from the catalogue) or by a
 * free-form amount — the server refuses both or neither with a 422, so this input is a
 * discriminated union rather than two optional fields.
 *
 * Money crosses the wire as a STRING (hard rule 7). The API's `amount_inr` accepts a JSON
 * number too, but sending one would put a rupee amount through a binary float on the way
 * out — the exact thing the string form exists to prevent. A pack sends no amount at all;
 * the catalogue is the authority on its price.
 */
export type TopUpRequest = { packId: string } | { amountInr: string };

export function useTopUpIntent(session: Session) {
  return useMutation({
    mutationFn: (request: TopUpRequest) =>
      apiRequest<TopUpIntent>(session, "/v1/billing/topups/intent", {
        method: "POST",
        body:
          "packId" in request
            ? { pack_id: request.packId }
            : { amount_inr: request.amountInr },
      }),
  });
}

/**
 * Hand the Checkout callback to the server, which is the only party that can judge it.
 *
 * ## Why exactly three fields, spelled out
 *
 * `CheckoutCallbackIn` is a `Strict` model (extra = forbid), and the object Checkout hands
 * the `handler` is the PROVIDER's, whose shape we do not control and have not read a
 * specification for. Forwarding it whole would make a vendor adding one field turn every
 * client's payment confirmation into a 422 — a failure that would look, on the screen, like
 * a payment that could not be verified. So the three are copied by name; anything else the
 * vendor sends is dropped at this seam, which is the same rule hard rule 2 applies to
 * engine payloads.
 *
 * ## Why the success branch invalidates rather than sets
 *
 * A verified callback proves AUTHENTICITY and moves no money: the credit follows from the
 * signed webhook (`apps/api/billing/payments.py`), which may land before this request
 * returns or a moment after it. `setQueryData` would need a balance, and the only balance
 * the browser could construct is one it computed — the exact arithmetic hard rule 7 keeps
 * out of this console. Invalidating asks the server for the figure instead, and the screen
 * says "updating" until the server's own number changes.
 *
 * EVERY surface that renders the balance is invalidated, and the list is the whole
 * correctness of this hook. `/v1/usage` carries `credit_balance_inr` and
 * `/v1/billing/caps` carries the spend this month is measured against — the pair
 * `useSetCaps` invalidates. The three WALLET keys are the ones added when the credits
 * screen was built, and forgetting them was a real defect for exactly one test run: the
 * top-up panel now LIVES on `/c/{slug}/credits`, so a hook that refreshed only the two
 * Usage reads left a client staring at their old balance on the very screen they had just
 * paid from. `topups` is in the list for the same reason one step along — the attempt they
 * just completed should stop being listed as unfinished.
 */
export function useConfirmTopUp(session: Session) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fields: CheckoutCallback) =>
      apiRequest<CheckoutConfirmation>(session, "/v1/billing/topups/callback", {
        method: "POST",
        body: {
          razorpay_order_id: fields.razorpay_order_id,
          razorpay_payment_id: fields.razorpay_payment_id,
          razorpay_signature: fields.razorpay_signature,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["usage", session.orgSlug] });
      void queryClient.invalidateQueries({ queryKey: capsKey(session.orgSlug) });
      void queryClient.invalidateQueries({ queryKey: walletKey(session.orgSlug) });
      void queryClient.invalidateQueries({ queryKey: walletLedgerKey(session.orgSlug) });
      void queryClient.invalidateQueries({ queryKey: walletAttemptsKey(session.orgSlug) });
    },
  });
}

/**
 * The prepaid credit-pack rate card, priced at the live list rate server-side. A read that
 * changes only when the catalogue or the list rate does, so it is cached for the session.
 * The effective rate and talk time are computed by the server (hard rule 7 reaches the
 * browser: no decimal arithmetic on money here) and rendered as sent.
 */
export function useCreditPacks(session: Session) {
  return useQuery({
    queryKey: ["billing", "credit-packs"],
    queryFn: () => apiRequest<CreditPacks>(session, "/v1/billing/topups/packs"),
    staleTime: Infinity,
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

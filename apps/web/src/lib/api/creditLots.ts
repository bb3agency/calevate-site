"use client";

/**
 * CREDIT LOTS, AS THE ADMIN WALLET SCREEN READS THEM (D-547).
 *
 * It lived in the credits page's own directory while the lot shapes were being added to
 * the credit routes by another lane and `src/lib/api/**` was not that lane's to touch.
 * With the hand validators collapsed onto the generated types, what is left is two wire
 * aliases, a path, a step-up string and a mutation hook — the shape of every other module
 * beside it, and the sibling of `credits.ts`, which owns the wallet read these lots arrive
 * on.
 *
 * A lot is what one purchase, grant or migration created: credits, and the TWO per-minute
 * rates frozen onto them at that instant. Spending is oldest lot first, and a minute is
 * priced by the lot it comes out of — so "the balance" is no longer one number with one
 * price behind it, and an operator crediting a wallet is opening a priced object, not
 * adding to a pot.
 *
 * ## THE PROMISE THIS MODULE EXISTS TO MAKE VISIBLE
 *
 * A restatement moves a lot's TOTALS and never its RATES
 * (`billing/models.CreditLot`: the terms-frozen trigger allows `credits_total`,
 * `credits_remaining`, `closed_at`, `updated_at` and nothing else). That is precisely what
 * the client was sold — "the rates shown when you paid apply to that purchase's credit
 * until it is spent" — so the screen says it at the moment an operator restates, rather
 * than leaving them to infer it from a table that happens not to change.
 *
 * ## Money
 *
 * Every credit figure and every rate is the server's exact decimal STRING, printed
 * verbatim. This module does no arithmetic on money: it cannot tell you what a lot is worth
 * in minutes and does not pretend to, because dividing credits by a rate in a browser is
 * exactly the float arithmetic hard rule 7 exists to keep away from a wallet.
 *
 * ## Vendor names
 *
 * The two rates are `sarvam_inr_per_min` and `cartesia_inr_per_min` — the vendors, because
 * this is the admin console and an operator has to connect a rate to the key they installed
 * and the invoice they attested. The client-facing label for each ("Clear", "Studio")
 * crosses the wire beside it and is rendered too, so an operator on the phone reads the
 * same word the client is looking at. Neither name is invented in the browser.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import { creditsKey } from "@/lib/api/credits";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

/**
 * ONE LOT — `CreditLotOut`, generated.
 *
 * **THIS WAS A LOCAL `interface CreditLot` PLUS `asCreditLot`/`lotsOf`/`lotOf`/
 * `asOverridePack`/`overridePacksOf`, AND ALL OF THEM ARE GONE.** They stood in while the
 * lot shapes were being added to the credit routes by another lane, and what they bought
 * was real at the time: a missing rate rendered as `0` would tell an operator this
 * client's minutes are free, and a missing `credits_remaining` defaulted to
 * `credits_total` would show spent money as available. `CreditsOut.lots`,
 * `CreditsOut.override_packs` and the `lot` on every write's answer are now generated and
 * REQUIRED, with every field on them required too, so the hand validators re-checked only
 * what the compiler already proves — and two spellings of one wire contract is how the
 * weaker one comes to be trusted. Screens read `wallet.lots`, `wallet.override_packs` and
 * `result.lot` off the typed responses they already hold.
 *
 * `source` stays a plain string on the wire: an unknown source still prints.
 */
export type CreditLot = Schemas["CreditLotOut"];

/**
 * A pack an operator may re-price a lot at, as the wallet read publishes it.
 *
 * The choices come from the SERVER rather than from a catalogue this screen keeps, for the
 * reason every other list on this console does: a pack ladder spelled twice is a ladder
 * that drifts, and the rates shown beside each option have to be the ones the write will
 * actually freeze onto the lot.
 */
export type OverridePack = Schemas["OverridePackOut"];

export function lotOverridePath(tenantId: string, lotId: string): string {
  return `/v1/admin/tenants/${tenantId}/credit-lots/${lotId}/override`;
}

/**
 * The step-up string for re-pricing ONE lot, bound to that lot so a confirmation captured
 * for one purchase cannot re-price another.
 */
export function lotOverrideConfirmation(lotId: string): string {
  return `override_lot_rates:${lotId}`;
}

export interface LotOverrideDraft {
  lotId: string;
  /** The pack whose rates this lot should be sold at from now on. */
  packId: string;
  reason: string;
}

/**
 * "Sell this lot at pack X's rates" — the founding-client promotion, and every negotiated
 * deal after it (plan §0 Q6).
 *
 * It is a WRITE THAT CHANGES A FROZEN TERM, which is why it is a route of its own with its
 * own step-up and its own audit row rather than a field on the lot: the rates are otherwise
 * unwritable by construction, and the one path that moves them has to be the one path that
 * records who moved them and why.
 */
export function useApplyLotOverride(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ lotId, packId, reason }: LotOverrideDraft) =>
      apiRequest<unknown>(adminSession(), lotOverridePath(tenantId, lotId), {
        method: "POST",
        body: { pack_id: packId, reason },
        confirmAction: lotOverrideConfirmation(lotId),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: creditsKey(tenantId) }),
  });
}

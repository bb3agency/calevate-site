"use client";

/**
 * CREDIT LOTS, AS THE ADMIN WALLET SCREEN READS THEM (D-547).
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

/** How a lot came into being. A string, not a union — an unknown source still prints. */
export type LotSource = string;

export interface CreditLot {
  lot_id: string;
  source: LotSource;
  /** The pack whose rates this lot carries, when a pack decided them. */
  pack_id: string | null;
  /** Set when an operator sold this lot at another pack's rates (audited). */
  override_of_pack_id: string | null;
  credits_total: string;
  credits_remaining: string;
  sarvam_inr_per_min: string;
  cartesia_inr_per_min: string;
  /** What a client calls each voice — `billing/rates.VOICE_TIER_LABELS`, over the wire. */
  sarvam_label: string;
  cartesia_label: string;
  opened_at: string;
  closed_at: string | null;
}

function money(value: unknown): value is string {
  return typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value.trim());
}

/**
 * THE SEAM. A lot that is not fully formed is dropped rather than defaulted.
 *
 * The lot shapes are being added to the credit routes by another lane. A missing rate
 * rendered as `0` would tell an operator this client's minutes are free; a missing
 * `credits_remaining` defaulted to `credits_total` would show spent money as available. So
 * nothing is defaulted and a partial payload renders as a stated absence.
 */
export function asCreditLot(raw: unknown): CreditLot | null {
  if (typeof raw !== "object" || raw === null) return null;
  const lot = raw as Record<string, unknown>;
  const text = (value: unknown): value is string => typeof value === "string" && value !== "";
  if (!text(lot.lot_id) || !text(lot.source) || !text(lot.opened_at)) return null;
  if (!text(lot.sarvam_label) || !text(lot.cartesia_label)) return null;
  if (!money(lot.credits_total) || !money(lot.credits_remaining)) return null;
  if (!money(lot.sarvam_inr_per_min) || !money(lot.cartesia_inr_per_min)) return null;
  const optional = (value: unknown): string | null => (text(value) ? value : null);
  return {
    lot_id: lot.lot_id,
    source: lot.source,
    pack_id: optional(lot.pack_id),
    override_of_pack_id: optional(lot.override_of_pack_id),
    credits_total: lot.credits_total,
    credits_remaining: lot.credits_remaining,
    sarvam_inr_per_min: lot.sarvam_inr_per_min,
    cartesia_inr_per_min: lot.cartesia_inr_per_min,
    sarvam_label: lot.sarvam_label,
    cartesia_label: lot.cartesia_label,
    opened_at: lot.opened_at,
    closed_at: optional(lot.closed_at),
  };
}

/** The wallet's open lots, oldest first as they will be spent — or `null` if unsent. */
export function lotsOf(wallet: unknown): CreditLot[] | null {
  if (typeof wallet !== "object" || wallet === null) return null;
  const list = (wallet as Record<string, unknown>).lots;
  if (!Array.isArray(list)) return null;
  const lots = list.map(asCreditLot);
  if (lots.some((lot) => lot === null)) return null;
  return lots as CreditLot[];
}

/**
 * The lot a WRITE opened or moved, off that write's own answer.
 *
 * Read from the response rather than from the refetched wallet deliberately: the receipt
 * has to name the object THIS click created, and a list re-read a moment later cannot say
 * which of five lots that was.
 */
export function lotOf(result: unknown): CreditLot | null {
  if (typeof result !== "object" || result === null) return null;
  return asCreditLot((result as Record<string, unknown>).lot);
}

/**
 * What a restatement did to the lot — totals only, and the amount the lot could not absorb.
 *
 * `shortfall_inr` is ADDENDUM 2 §2.2's case: a downward restatement of more than the lot
 * has left floors the remainder at zero and the rest becomes wallet overdraft, repaid by
 * the next purchase before a new lot opens. It is the one part of a restatement an operator
 * cannot see coming, so it is published rather than inferred.
 */
export interface LotRestatement {
  lot: CreditLot;
  shortfall_inr: string | null;
}

export function lotRestatementOf(result: unknown): LotRestatement | null {
  const lot = lotOf(result);
  if (lot === null) return null;
  const raw = (result as Record<string, unknown>).lot_shortfall_inr;
  return { lot, shortfall_inr: money(raw) ? raw : null };
}

/**
 * A pack an operator may re-price a lot at, as the wallet read publishes it.
 *
 * The choices come from the SERVER rather than from a catalogue this screen keeps, for the
 * reason every other list on this console does: a pack ladder spelled twice is a ladder
 * that drifts, and the rates shown beside each option have to be the ones the write will
 * actually freeze onto the lot.
 */
export interface OverridePack {
  pack_id: string;
  amount_inr: string;
  sarvam_inr_per_min: string;
  cartesia_inr_per_min: string;
}

export function asOverridePack(raw: unknown): OverridePack | null {
  if (typeof raw !== "object" || raw === null) return null;
  const pack = raw as Record<string, unknown>;
  if (typeof pack.pack_id !== "string" || pack.pack_id === "") return null;
  if (!money(pack.amount_inr)) return null;
  if (!money(pack.sarvam_inr_per_min) || !money(pack.cartesia_inr_per_min)) return null;
  return {
    pack_id: pack.pack_id,
    amount_inr: pack.amount_inr,
    sarvam_inr_per_min: pack.sarvam_inr_per_min,
    cartesia_inr_per_min: pack.cartesia_inr_per_min,
  };
}

/** The packs a lot may be sold at, or `null` when this API does not publish them. */
export function overridePacksOf(wallet: unknown): OverridePack[] | null {
  if (typeof wallet !== "object" || wallet === null) return null;
  const list = (wallet as Record<string, unknown>).override_packs;
  if (!Array.isArray(list) || list.length === 0) return null;
  const packs = list.map(asOverridePack);
  return packs.some((pack) => pack === null) ? null : (packs as OverridePack[]);
}

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

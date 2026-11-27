"use client";

/**
 * WHAT A MINUTE ON EACH VOICE COSTS THIS ACCOUNT, for the voice picker (PLAN 2026-11-28 §7).
 *
 * The figure is never typed here. A minute is priced by the credit it is spent from, and each
 * purchase freezes its two rates on its lot (`clear_inr_per_min` / `studio_inr_per_min`), so:
 *
 *  1. an open lot: the OLDEST one's rate, because calls spend the oldest lot first
 *     (`GET /v1/billing/wallet/lots` lists them in spend order) — "₹X a minute";
 *  2. no open lot (a trial, or an empty wallet): the lowest rate any pack sells, because the
 *     next purchase decides the rate — "from ₹X a minute", and on a trial, free for now. The
 *     pack card states that minimum itself (`from_<tier>_inr_per_min`, the minimum of the
 *     same `packRate` column), so the browser does not search the packs for it;
 *  3. neither readable (staff cannot read the pack card, `billing:read`): no figure at all,
 *     and the picker says when one will show. Never a guessed number.
 *
 * Figures are printed with `formatINR`, the display rule every client billing screen prints
 * lot and pack rates with; nothing is added or multiplied into a new price (hard rule 7).
 */

import type { UseQueryResult } from "@tanstack/react-query";

import { lotRate, useWalletLots, type VoiceTier, type WalletLots } from "@/app/c/[slug]/billing/lots";
import { formatINR } from "@/components/ui";
import { useCreditPacks, type CreditPacks } from "@/lib/api/billing";
import type { Session } from "@/lib/api/client";
import { cardFromRate } from "@/lib/api/rateCard";
import { useTrialPanel, type TrialPanel } from "@/lib/api/trialCalls";

export type VoiceMinutePrice =
  | { kind: "loading" }
  | { kind: "lot"; rate: string }
  | { kind: "from"; rate: string; trial: boolean }
  | { kind: "unknown" };

/** Said where no figure can be read. */
export const PRICE_LATER = "Price shown when you add credit";

/** Said beside a "from" figure while the account is on its free trial. */
export const FREE_ON_TRIAL = "Free during your trial";

/** The price of a minute on `tier` from the three reads, as `VoiceMinutePrice` explains. */
export function voiceMinutePrice(
  tier: VoiceTier,
  lots: UseQueryResult<WalletLots>,
  packs: UseQueryResult<CreditPacks>,
  trial: UseQueryResult<TrialPanel>,
): VoiceMinutePrice {
  if (lots.isLoading) return { kind: "loading" };
  const first = lots.data?.lots[0];
  if (first) return { kind: "lot", rate: lotRate(first, tier) };
  if (packs.isLoading || trial.isLoading) return { kind: "loading" };
  if (!packs.data || packs.data.packs.length === 0) return { kind: "unknown" };
  return { kind: "from", rate: cardFromRate(packs.data, tier), trial: trial.data?.on_trial === true };
}

/** One price per voice, read once for the whole picker. */
export function useVoiceMinutePrices(session: Session): (tier: VoiceTier) => VoiceMinutePrice {
  const lots = useWalletLots(session);
  const packs = useCreditPacks(session);
  const trial = useTrialPanel(session);
  return (tier) => voiceMinutePrice(tier, lots, packs, trial);
}

/** The figure in words: "₹4.5 a minute", "from ₹4.5 a minute", the later line, or nothing yet. */
export function priceWords(price: VoiceMinutePrice): string | null {
  switch (price.kind) {
    case "loading":
      return null;
    case "lot":
      return `${formatINR(price.rate)} a minute`;
    case "from":
      return `from ${formatINR(price.rate)} a minute`;
    case "unknown":
      return PRICE_LATER;
  }
}

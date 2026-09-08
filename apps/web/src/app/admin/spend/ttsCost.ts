"use client";

/**
 * THE VOICE VENDOR'S BILL, AS THE MONEY BOARD READS IT (D-547, plan Phase D).
 *
 * Two figures that must never be confused, and this module exists to keep them apart:
 *
 * - **ATTRIBUTED** — what we charged to calls. Under BYOK the engine bills us nothing for
 *   the synthesizer leg, so a Cartesia minute's cost is `attested ₹/1,000 chars × the
 *   characters our own transcript says the agent spoke`. It is real cost, allocated to the
 *   client whose call incurred it.
 * - **PLAN SPEND** — what the vendor actually took: a monthly commitment, paid whether or
 *   not the allotment is used. It belongs to the platform, not to any client.
 *
 * Their difference is the allotment nobody spoke into. A board showing only the first would
 * under-state what we pay; one showing only the second could not tell which client caused
 * it. Both are the SERVER's own figures — nothing here subtracts one from the other,
 * because a difference computed in a browser is float arithmetic on money (hard rule 7).
 *
 * ## Why the speaking rate is on this page at all
 *
 * The characters that price a Cartesia row are counted from OUR transcripts, and the
 * measured chars-per-minute card beside it is the same measurement at fleet scale. It is
 * therefore no longer only a check on TRD §10.1's assumed band: it is the quantity the
 * Cartesia rows are metered on, and an operator reading a Cartesia cost has to be able to
 * see how many characters it was struck from.
 */

import { isSignedMoneyString } from "@/lib/money";
import type { components } from "@/lib/api/schema";

/**
 * One voice vendor's month: what the plan cost, what the calls attributed, and the price
 * those calls were struck at.
 */
export interface TtsPlanSpend {
  provider: string;
  tier_label: string;
  month: string;
  /** What the vendor billed for the month — the operator-attested plan fee. */
  plan_inr: string;
  /** What this month's calls attributed to that vendor's leg. */
  attributed_inr: string;
  /** The plan's unspoken allotment, as the SERVER computed it. Null when it cannot. */
  unused_inr: string | null;
  /** Characters the fleet's agents spoke on this vendor this month. */
  chars: string;
  /** The attested rate those characters were priced at. Null when nothing is attested. */
  inr_per_1k_chars: string | null;
}

export function asTtsPlanSpend(raw: unknown): TtsPlanSpend | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const text = (value: unknown): value is string => typeof value === "string" && value !== "";
  if (!text(row.provider) || !text(row.tier_label) || !text(row.month)) return null;
  if (!isSignedMoneyString(row.plan_inr) || !isSignedMoneyString(row.attributed_inr)) return null;
  if (!isSignedMoneyString(row.chars)) return null;
  return {
    provider: row.provider,
    tier_label: row.tier_label,
    month: row.month,
    plan_inr: row.plan_inr,
    attributed_inr: row.attributed_inr,
    unused_inr: isSignedMoneyString(row.unused_inr) ? row.unused_inr : null,
    chars: row.chars,
    inr_per_1k_chars: isSignedMoneyString(row.inr_per_1k_chars) ? row.inr_per_1k_chars : null,
  };
}

/**
 * THE SEAM, AND IT IS STILL A SEAM. ⚠ **`tts_plan` IS NOT ON `FleetSpendOut`** — checked
 * against `lib/api/openapi.json` after the D-547 regeneration (8 Sep 2026): the fleet board
 * publishes `clients`, `cost_inr`, `margin_inr`, `margin_pct`, `month`, `revenue_inr` and
 * `tenants`, and nothing about what the voice vendors billed. So this reader is NOT a
 * placeholder to collapse onto a generated type: there is no generated type to collapse
 * onto, and the card renders its stated absence on every load until the API publishes the
 * field. Reported as a backend finding rather than papered over — a plan fee defaulted to
 * ₹0 would show a fleet margin that does not exist, which is the exact error the two
 * figures above are separated to prevent.
 */
export function ttsPlanSpendOf(board: unknown): TtsPlanSpend[] | null {
  if (typeof board !== "object" || board === null) return null;
  const list = (board as Record<string, unknown>).tts_plan;
  if (!Array.isArray(list) || list.length === 0) return null;
  const rows = list.map(asTtsPlanSpend);
  return rows.some((row) => row === null) ? null : (rows as TtsPlanSpend[]);
}

/**
 * What the measured speaking rate means for ONE voice vendor — `SpeakingRateByProviderOut`,
 * generated.
 *
 * `pooled_inr_per_minute` is the SERVER's multiplication of its own two figures. The
 * browser does not multiply a chars/min string by a ₹/1k string — that is money arithmetic,
 * and the answer would be a third figure disagreeing with the meter's.
 *
 * **THE LOCAL INTERFACE AND `asSpeakingRateByProvider`/`speakingRateByProviderOf` ARE
 * GONE.** `TtsSpeakingRateOut.by_provider` is generated and REQUIRED, every field on the row
 * with it, so the hand validator re-checked what the compiler proves. The card reads
 * `rate.by_provider` off the typed response.
 */
export type SpeakingRateByProvider = components["schemas"]["SpeakingRateByProviderOut"];

/** The vendor, named — this is the admin console, and the invoice has a vendor on it. */
export function vendorName(provider: string): string {
  if (provider === "sarvam") return "Sarvam";
  if (provider === "cartesia") return "Cartesia";
  return provider;
}

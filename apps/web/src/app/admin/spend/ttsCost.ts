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

/** Money as the server spelled it. Nothing here parses one. */
function money(value: unknown): value is string {
  return typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value.trim());
}

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
  if (!money(row.plan_inr) || !money(row.attributed_inr) || !money(row.chars)) return null;
  return {
    provider: row.provider,
    tier_label: row.tier_label,
    month: row.month,
    plan_inr: row.plan_inr,
    attributed_inr: row.attributed_inr,
    unused_inr: money(row.unused_inr) ? row.unused_inr : null,
    chars: row.chars,
    inr_per_1k_chars: money(row.inr_per_1k_chars) ? row.inr_per_1k_chars : null,
  };
}

/**
 * THE SEAM. `tts_plan` is being added to the fleet board by the lane building Cartesia
 * metering; until it lands (and on any payload this build cannot fully read) the card
 * renders a stated absence. A plan fee defaulted to ₹0 would show a fleet margin that does
 * not exist, which is the exact error the two figures are separated to prevent.
 */
export function ttsPlanSpendOf(board: unknown): TtsPlanSpend[] | null {
  if (typeof board !== "object" || board === null) return null;
  const list = (board as Record<string, unknown>).tts_plan;
  if (!Array.isArray(list) || list.length === 0) return null;
  const rows = list.map(asTtsPlanSpend);
  return rows.some((row) => row === null) ? null : (rows as TtsPlanSpend[]);
}

/**
 * What the measured speaking rate means for ONE voice vendor: the ₹/min it implies at that
 * vendor's own price, and whether that price exists at all.
 *
 * `pooled_inr_per_minute` is the SERVER's multiplication of its own two figures. The
 * browser does not multiply a chars/min string by a ₹/1k string — that is money arithmetic,
 * and the answer would be a third figure disagreeing with the meter's.
 */
export interface SpeakingRateByProvider {
  provider: string;
  tier_label: string;
  price_attested: boolean;
  inr_per_1k_chars: string | null;
  pooled_inr_per_minute: string | null;
}

export function asSpeakingRateByProvider(raw: unknown): SpeakingRateByProvider | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const text = (value: unknown): value is string => typeof value === "string" && value !== "";
  if (!text(row.provider) || !text(row.tier_label)) return null;
  if (typeof row.price_attested !== "boolean") return null;
  return {
    provider: row.provider,
    tier_label: row.tier_label,
    price_attested: row.price_attested,
    inr_per_1k_chars: money(row.inr_per_1k_chars) ? row.inr_per_1k_chars : null,
    pooled_inr_per_minute: money(row.pooled_inr_per_minute) ? row.pooled_inr_per_minute : null,
  };
}

export function speakingRateByProviderOf(rate: unknown): SpeakingRateByProvider[] | null {
  if (typeof rate !== "object" || rate === null) return null;
  const list = (rate as Record<string, unknown>).by_provider;
  if (!Array.isArray(list) || list.length === 0) return null;
  const rows = list.map(asSpeakingRateByProvider);
  return rows.some((row) => row === null) ? null : (rows as SpeakingRateByProvider[]);
}

/** The vendor, named — this is the admin console, and the invoice has a vendor on it. */
export function vendorName(provider: string): string {
  if (provider === "sarvam") return "Sarvam";
  if (provider === "cartesia") return "Cartesia";
  return provider;
}

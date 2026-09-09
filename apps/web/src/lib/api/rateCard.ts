/**
 * The public self-serve rate card (D-545) — the ONE way the marketing site knows a price.
 *
 * ## Why this module exists
 *
 * The site used to hold a typed `500` paise in `lib/roi.ts` whose own comment admitted it
 * would drift the day `self_serve_inr_per_min` moved on the server. The founder's pricing
 * decision of 5 Sep 2026 — keep the list rate at ₹5.00 and lead with the effective rate
 * the ₹50,000 pack already delivers — needed the PACK LADDER on the site too, and typing
 * five more numbers beside the first would have been the same defect five times over.
 *
 * So the API publishes the card at `GET /v1/public/rate-card`, unauthenticated, built by
 * the same function as the signed-in `/v1/billing/topups/packs` read and pinned against
 * the margin guard's own arithmetic (`tests/public_rate_card_test.py`). This module reads
 * it and nothing else. **No figure on the public site is typed any more**: every rupee
 * on `/pricing` and every rate in the ROI calculator is a string that arrived in this
 * response, formatted from its digits.
 *
 * ## Two rates per pack, and the NAME of each voice, since D-547 (7 Sep 2026)
 *
 * A pack no longer has "an" effective rate. It has one ₹/min for each of the two voices an
 * agent can speak with, and which one prices a call is a property of the AGENT that took
 * it. So every reader on this site asks for a rate BY VOICE (`packRate`, `cardFromRate`),
 * and the single-rate fields (`from_inr_per_min`, `effective_rate_inr_per_min`,
 * `talk_time_minutes`) are deprecated on the wire for one release and read by nothing here.
 *
 * The card also carries what a CLIENT calls each voice, and that is the second reason this
 * module exists in the shape it does: no client-facing surface names a vendor as a product
 * tier (founder, 7 Sep 2026), the two names are defined once in `billing/rates.py`
 * (`VOICE_TIER_LABELS`), and a copy of them in TypeScript would be a second definition of a
 * name a client reads — the drift that ends with one buyer meeting both. So the label
 * crosses the wire beside the rate and `tierLabel` passes it through untouched. The wire
 * FIELD names still say `sarvam`/`cartesia`: those mean the vendor, they are the ledger's
 * vocabulary, and they are not shown to anybody.
 *
 * ## Server-side, at request time, through the generated client
 *
 * NOT `"use client"`, deliberately. The marketing tree has no `QueryClientProvider`
 * (`app/providers.tsx` is mounted by the two console shells and the auth pages only), so
 * a TanStack hook cannot run there — and it should not: the pages are already rendered
 * per request (`app/layout.tsx` is `force-dynamic` for the CSP nonce), so the page
 * itself awaits this and hands plain data to its sections. The request still goes
 * through `apiRequest`, never a bare `fetch`: same deadline, same problem+json parsing,
 * same seam `tests/transportGuard.test.ts` enforces.
 *
 * ## Honest failure
 *
 * `fetchPublicRateCard` returns `null` when the card cannot be had — a network refusal,
 * a 503 from a maintenance window, a 429, a body that is not the shape the schema says —
 * and every reader renders "could not be loaded" in those words. Nothing falls back to
 * a constant, because a stale or typed price on a pricing page is precisely the claim
 * hard rule 11 exists to stop.
 *
 * ## Money stays a string until it is digits
 *
 * Rates arrive at 4dp (`"4.6296"`), amounts at 2dp (`"50000.00"`). Nothing here calls
 * `Number()` on either: `rateToTenThousandths` reads the DIGITS into an exact integer
 * (ten-thousandths of a rupee — the API's own NUMERIC(12,4) scale), and every derived
 * figure is integer arithmetic from there, the discipline `lib/roi.ts` states for the
 * calculator and `lib/api/wallet.ts` states for the console.
 */

import { formatPaiseINR } from "@/lib/roi";
import { MONEY_STRING } from "@/lib/money";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * The card: the entry rate, the lowest rate on each voice, what a client calls each voice,
 * and every pack priced on both.
 *
 * The tier labels ride on `CreditPacksOut` itself: the API names each voice quality
 * (`billing/rates.VOICE_TIER_LABELS`) and this module passes the name through, so no
 * browser copy of it can drift from the one the server serves.
 */
export type PublicRateCard = Schemas["CreditPacksOut"];
/** One pack: amount, credits, a ₹/min and a talk time on each of the two voices. */
export type RateCardPack = Schemas["CreditPackOut"];

/**
 * The two voices a rate can be for, spelled the way the WIRE and the ledger spell them —
 * by vendor. A client never reads these strings: what they read is the card's
 * `*_tier_label`, which is a name the API chose (`billing/rates.VOICE_TIER_LABELS`) and
 * this module only ever passes through. The two vocabularies are deliberately different:
 * a vendor may be replaced under a voice quality without renaming anything a client has
 * seen, and a money column that said "Clear" instead of "sarvam" would stop being
 * auditable the day the vendor behind it changed.
 */
export type VoiceTier = "sarvam" | "cartesia";

/**
 * Both voices, in the order the card leads with them (the cheaper first).
 *
 * A TUPLE rather than `readonly VoiceTier[]`, so `.length` is the literal `2` and a
 * renderer can pin its own arity against it at compile time. `components/marketing/
 * rateCard.tsx` does: its voice switch writes out two Tailwind `peer` names because
 * Tailwind scans source text and cannot generate a class it has not read, and a third
 * voice arriving would otherwise be priced in the document with no way to select it.
 */
export const VOICE_TIERS = ["sarvam", "cartesia"] as const satisfies readonly VoiceTier[];

/** One pack's ₹/min on one voice, as the 4dp string the API sent. THE ONE DOOR. */
export function packRate(pack: RateCardPack, voice: VoiceTier): string {
  return voice === "sarvam" ? pack.sarvam_inr_per_min : pack.cartesia_inr_per_min;
}

/** Whole minutes one pack's credits buy on one voice, as the API floored them. */
export function packMinutes(pack: RateCardPack, voice: VoiceTier): number {
  return voice === "sarvam" ? pack.sarvam_minutes : pack.cartesia_minutes;
}

/** The lowest ₹/min any pack delivers on one voice — the site's "from" figure. */
export function cardFromRate(card: PublicRateCard, voice: VoiceTier): string {
  return voice === "sarvam" ? card.from_sarvam_inr_per_min : card.from_cartesia_inr_per_min;
}

/**
 * What a CLIENT calls this voice. Read from the response, never held here: two copies of
 * a name is how a client comes to meet both of them (founder, 7 Sep 2026).
 */
export function tierLabel(card: PublicRateCard, voice: VoiceTier): string {
  return voice === "sarvam" ? card.sarvam_tier_label : card.cartesia_tier_label;
}

export const PUBLIC_RATE_CARD_PATH = "/v1/public/rate-card";

/**
 * Nobody. The route reads nothing about its caller and the site holds no session, so
 * this sends no bearer, no org header and no grant — `apiRequest` omits each header
 * whose value is absent rather than sending an empty one.
 */
const NOBODY: Session = { orgSlug: "" };

/**
 * `"4.6296"` → `46296`, `"5.00"` → `50000`: an exact integer count of ten-thousandths
 * of a rupee, read from the digits. Throws on anything that is not a money string of
 * ours — a caller that has validated the card (`isRateCard`) never sees the throw, and a
 * caller that has not should, loudly, rather than compute with `NaN`.
 */
export function rateToTenThousandths(value: string): number {
  if (!MONEY_STRING.test(value)) throw new Error(`not a money string: ${JSON.stringify(value)}`);
  const [whole, fraction = ""] = value.split(".");
  return Number(whole) * 10_000 + Number(fraction.padEnd(4, "0"));
}

/**
 * A rate as the calculator's input unit — PAISE per minute, carried to a hundredth of a
 * paisa so a pack's 4dp effective rate is priced exactly rather than rounded to the
 * paisa first (`lib/roi.ts::computeRoi` rounds once, at the end of the line).
 */
export function ratePaisePerMin(rate: string): number {
  return rateToTenThousandths(rate) / 100;
}

/**
 * A rate for a sentence: `"4.6296"` → `"₹4.63"`. Half-up to the paisa, in integer
 * arithmetic, then formatted from the digits by the calculator's own formatter.
 */
export function formatRateINR(rate: string): string {
  const tenThousandths = rateToTenThousandths(rate);
  return formatPaiseINR(Math.floor((tenThousandths + 50) / 100));
}

/**
 * An amount for a sentence: `"50000.00"` → `"₹50,000"`, `"2500.50"` → `"₹2,500.50"`.
 * Whole rupees drop the `.00` — a pack is "the ₹50,000 pack", not "the ₹50,000.00 pack".
 */
export function formatAmountINR(amount: string): string {
  const paise = Math.floor((rateToTenThousandths(amount) + 50) / 100);
  const formatted = formatPaiseINR(paise);
  return paise % 100 === 0 ? formatted.slice(0, -3) : formatted;
}

/**
 * The pack that delivers this voice's "from" rate, or the last pack if none matches.
 *
 * PER VOICE since D-547, and it has to be: the two columns fall at different speeds
 * (Cartesia 8.00 → 6.00 against Sarvam 5.00 → 4.50), so "the cheapest pack" is a question
 * with two answers and the old single-rate form silently answered the Sarvam one for both.
 * It matched on `effective_rate_inr_per_min`, a field that is now deprecated and holds the
 * Sarvam figure for unmigrated readers — which is exactly how a caller asking about the
 * dearer voice would have been handed the cheaper voice's pack and never noticed.
 */
export function cheapestPack(card: PublicRateCard, voice: VoiceTier): RateCardPack | undefined {
  const from = cardFromRate(card, voice);
  return card.packs.find((pack) => packRate(pack, voice) === from) ?? card.packs.at(-1);
}

/**
 * Is this body the card the schema promises? Checked at the seam because the site
 * renders it with no session and no screen to catch a surprise on: a body that is
 * missing a field or carries a rate that is not a money string is treated exactly like
 * an unreachable API — "could not be loaded" — rather than printed.
 */
export function isRateCard(body: unknown): body is PublicRateCard {
  if (typeof body !== "object" || body === null) return false;
  const card = body as Record<string, unknown>;
  if (typeof card.list_rate_inr_per_min !== "string" || !MONEY_STRING.test(card.list_rate_inr_per_min))
    return false;
  if (typeof card.from_inr_per_min !== "string" || !MONEY_STRING.test(card.from_inr_per_min))
    return false;
  // The two "from" rates and the two tier names, which are what the pages LEAD with: a
  // missing one is a heading with `undefined` in it, and a blank label is a voice with no
  // name beside its price. Checked before the rows because a card that cannot introduce
  // its columns cannot honestly print them.
  for (const field of ["from_sarvam_inr_per_min", "from_cartesia_inr_per_min"] as const) {
    if (typeof card[field] !== "string" || !MONEY_STRING.test(card[field] as string)) return false;
  }
  for (const field of ["sarvam_tier_label", "cartesia_tier_label"] as const) {
    const label = card[field];
    if (typeof label !== "string" || label.trim() === "") return false;
  }
  if (!Array.isArray(card.packs) || card.packs.length === 0) return false;
  return card.packs.every((pack: unknown) => {
    if (typeof pack !== "object" || pack === null) return false;
    const row = pack as Record<string, unknown>;
    const money = (value: unknown): boolean =>
      typeof value === "string" && MONEY_STRING.test(value);
    const wholeMinutes = (value: unknown): boolean =>
      typeof value === "number" && Number.isInteger(value);
    return (
      typeof row.pack_id === "string" &&
      money(row.amount_inr) &&
      // BOTH rates and BOTH talk times, because both are rendered. The deprecated
      // `bonus_pct` / `effective_rate_inr_per_min` / `talk_time_minutes` are NOT checked
      // any more: nothing on this site reads them, they leave the wire next release
      // (plan §10), and a guard that refuses a card for a field nobody renders would take
      // the pricing page down on the release that removes them.
      money(row.sarvam_inr_per_min) &&
      money(row.cartesia_inr_per_min) &&
      wholeMinutes(row.sarvam_minutes) &&
      wholeMinutes(row.cartesia_minutes) &&
      typeof row.best_value === "boolean"
    );
  });
}

/**
 * The card, or `null` when it cannot honestly be shown.
 *
 * Every failure is logged as one line an operator can act on — the status when there was
 * one, the error's name when there was not — and nothing else: the request carries no
 * caller and the response carries no person, so there is nothing hard rule 6 could ask
 * this to redact.
 */
export async function fetchPublicRateCard(): Promise<PublicRateCard | null> {
  let body: unknown;
  try {
    body = await apiRequest<unknown>(NOBODY, PUBLIC_RATE_CARD_PATH);
  } catch (error) {
    const status = (error as { status?: number }).status;
    const name = error instanceof Error ? error.name : typeof error;
    console.error("public_rate_card_unavailable", { status: status ?? null, error: name });
    return null;
  }
  if (!isRateCard(body)) {
    console.error("public_rate_card_malformed", { path: PUBLIC_RATE_CARD_PATH });
    return null;
  }
  return body;
}

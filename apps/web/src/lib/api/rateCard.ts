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

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** The card: the live list rate, the lowest effective rate, and every pack priced. */
export type PublicRateCard = Schemas["CreditPacksOut"];
/** One pack, priced at the list rate: amount, bonus, effective ₹/min, talk time. */
export type RateCardPack = Schemas["CreditPackOut"];

export const PUBLIC_RATE_CARD_PATH = "/v1/public/rate-card";

/**
 * Nobody. The route reads nothing about its caller and the site holds no session, so
 * this sends no bearer, no org header and no grant — `apiRequest` omits each header
 * whose value is absent rather than sending an empty one.
 */
const NOBODY: Session = { orgSlug: "" };

/** A rupee figure as this API spells it: digits, optionally a point and 1–4 digits. */
const MONEY_STRING = /^\d+(\.\d{1,4})?$/;

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

/** The pack that delivers the card's `from_inr_per_min`, or the last pack if none matches. */
export function cheapestPack(card: PublicRateCard): RateCardPack | undefined {
  return (
    card.packs.find((pack) => pack.effective_rate_inr_per_min === card.from_inr_per_min) ??
    card.packs.at(-1)
  );
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
  if (!Array.isArray(card.packs) || card.packs.length === 0) return false;
  return card.packs.every((pack: unknown) => {
    if (typeof pack !== "object" || pack === null) return false;
    const row = pack as Record<string, unknown>;
    return (
      typeof row.pack_id === "string" &&
      typeof row.amount_inr === "string" &&
      MONEY_STRING.test(row.amount_inr) &&
      typeof row.bonus_pct === "string" &&
      MONEY_STRING.test(row.bonus_pct) &&
      typeof row.effective_rate_inr_per_min === "string" &&
      MONEY_STRING.test(row.effective_rate_inr_per_min) &&
      typeof row.talk_time_minutes === "number" &&
      Number.isInteger(row.talk_time_minutes) &&
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

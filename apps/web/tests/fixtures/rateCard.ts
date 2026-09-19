import type { PublicRateCard } from "@/lib/api/rateCard";

/**
 * The public rate card, as `GET /v1/public/rate-card` sends it (D-545, reshaped by D-547).
 *
 * ONE fixture, imported by every suite that renders a marketing page, because those pages
 * are async server components now: they await the card, and a suite that does not stub it
 * renders the honest "could not be loaded" state instead of the page under test. Two
 * copies of this would drift the day the ladder moves, and the drift would show up as a
 * marketing test failing for a reason that has nothing to do with marketing.
 *
 * ⚠ **IT WAS FIVE PACKS AT ONE RATE UNTIL 7 SEP 2026, AND IT KEPT PASSING AFTER THE CARD
 * CHANGED.** The pack discount stopped being bonus credits at a single list rate and became
 * TWO per-minute rates per pack (`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` §2.2), with a
 * sixth rung at ₹15,000 — and this fixture went on describing the old card, because the
 * deprecated fields it matched on (`bonus_pct`, `effective_rate_inr_per_min`,
 * `talk_time_minutes`) were deliberately kept alive on the wire for one release (plan §10).
 * A fixture that only exercises the fields on their way out is a fixture that tests the
 * previous release. Hence `satisfies PublicRateCard` below: the compiler now holds this
 * body to the generated wire type, so the next reshape breaks here rather than in six
 * months.
 *
 * The figures are the REAL ones, copied from `rate_card_out()`'s own output rather than
 * rounded by hand — rates at the 4dp the API sends (`NUMERIC(12,4)`), talk time floored the
 * way `_pack_out` floors it. `tests/public_rate_card_test.py` is what pins the server's
 * arithmetic; this is only the shape the browser is handed.
 *
 * ⚠ **THE CARD IS THE FOUNDER'S OF 14 SEP 2026** (`docs/PIPECAT-MIGRATION.md` §12): Clear
 * FLAT at ₹4.00 on all six rungs, Studio falling 7.00 → 5.50. The flat column is not a
 * copy-paste slip — it is what makes `from_clear_inr_per_min` equal `list_rate_inr_per_min`
 * here, which is the case `pricing/page.tsx::bandSentence` and
 * `billing/WhatCallsCost.tsx::rateBand` collapse to a single figure rather than rendering
 * "₹4.00 a minute, down to ₹4.00 on the largest pack".
 *
 * The two tier LABELS are values the API sends, not names the web knows: no client-facing
 * surface names a vendor as a product tier (founder, 7 Sep 2026), so a page may only print
 * a name that arrived in this response — which `marketingPages.test.tsx` proves by handing
 * a page a card with different labels and requiring THOSE on screen.
 */
export const RATE_CARD = {
  list_rate_inr_per_min: "4.0000",
  from_inr_per_min: "4.0000",
  from_clear_inr_per_min: "4.0000",
  from_studio_inr_per_min: "5.5000",
  clear_tier_label: "Clear",
  studio_tier_label: "Studio",
  packs: [
    { pack_id: "starter", amount_inr: "2000.00", paid_credits: "2000.00", bonus_credits: "0.00", total_credits: "2000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "7.0000", clear_minutes: 500, studio_minutes: 285, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 500, best_value: false },
    { pack_id: "growth", amount_inr: "5000.00", paid_credits: "5000.00", bonus_credits: "0.00", total_credits: "5000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "6.7000", clear_minutes: 1250, studio_minutes: 746, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 1250, best_value: false },
    { pack_id: "scale", amount_inr: "10000.00", paid_credits: "10000.00", bonus_credits: "0.00", total_credits: "10000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "6.4000", clear_minutes: 2500, studio_minutes: 1562, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 2500, best_value: false },
    { pack_id: "plus", amount_inr: "15000.00", paid_credits: "15000.00", bonus_credits: "0.00", total_credits: "15000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "6.1000", clear_minutes: 3750, studio_minutes: 2459, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 3750, best_value: false },
    { pack_id: "pro", amount_inr: "25000.00", paid_credits: "25000.00", bonus_credits: "0.00", total_credits: "25000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "5.8000", clear_minutes: 6250, studio_minutes: 4310, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 6250, best_value: false },
    { pack_id: "max", amount_inr: "50000.00", paid_credits: "50000.00", bonus_credits: "0.00", total_credits: "50000.00", bonus_pct: "0", clear_inr_per_min: "4.0000", studio_inr_per_min: "5.5000", clear_minutes: 12500, studio_minutes: 9090, effective_rate_inr_per_min: "4.0000", talk_time_minutes: 12500, best_value: true },
  ],
} satisfies PublicRateCard;

/** The route map to hand `stubApi` so an awaited marketing page gets its card. */
export const RATE_CARD_ROUTES = { "/v1/public/rate-card": RATE_CARD };

/**
 * The public rate card, as `GET /v1/public/rate-card` sends it (D-545).
 *
 * ONE fixture, imported by every suite that renders a marketing page, because those pages
 * are async server components now: they await the card, and a suite that does not stub it
 * renders the honest "could not be loaded" state instead of the page under test. Two
 * copies of this would drift the day the ladder moves, and the drift would show up as a
 * marketing test failing for a reason that has nothing to do with marketing.
 *
 * The figures are REAL-SHAPED, not round. Effective rates carry four decimals because the
 * API sends NUMERIC(12,4); rounding them here to the paisa would hide a formatting bug,
 * since `₹4.63` is `4.6296` rounded and the PAGE is what does the rounding. The ladder
 * mirrors `apps/api/billing/credit_packs.py::PACK_CATALOGUE` at a ₹5.00 list rate —
 * `tests/public_rate_card_test.py` is what pins the server's arithmetic; this is only the
 * shape the browser is handed.
 */
export const RATE_CARD = {
  list_rate_inr_per_min: "5.00",
  from_inr_per_min: "4.6296",
  packs: [
    { pack_id: "starter", amount_inr: "2000.00", bonus_pct: "0", paid_credits: "2000.00", bonus_credits: "0.00", total_credits: "2000.00", effective_rate_inr_per_min: "5.0000", talk_time_minutes: 400, best_value: false },
    { pack_id: "growth", amount_inr: "5000.00", bonus_pct: "3", paid_credits: "5000.00", bonus_credits: "150.00", total_credits: "5150.00", effective_rate_inr_per_min: "4.8544", talk_time_minutes: 1030, best_value: false },
    { pack_id: "scale", amount_inr: "10000.00", bonus_pct: "5", paid_credits: "10000.00", bonus_credits: "500.00", total_credits: "10500.00", effective_rate_inr_per_min: "4.7619", talk_time_minutes: 2100, best_value: false },
    { pack_id: "pro", amount_inr: "25000.00", bonus_pct: "7", paid_credits: "25000.00", bonus_credits: "1750.00", total_credits: "26750.00", effective_rate_inr_per_min: "4.6729", talk_time_minutes: 5350, best_value: false },
    { pack_id: "max", amount_inr: "50000.00", bonus_pct: "8", paid_credits: "50000.00", bonus_credits: "4000.00", total_credits: "54000.00", effective_rate_inr_per_min: "4.6296", talk_time_minutes: 10800, best_value: true },
  ],
};

/** The route map to hand `stubApi` so an awaited marketing page gets its card. */
export const RATE_CARD_ROUTES = { "/v1/public/rate-card": RATE_CARD };

import type { RateCard } from "@/lib/api/opsRateCard";

/**
 * THE CARD IN FORCE, as `GET /v1/ops/rate-card` answers it — two rungs of the six, one thin
 * and one healthy.
 *
 * `starter` on the Clear rung is the founder's own deliberately thin rung (17.60% against a
 * 20% target, and well above the ₹4.1211 the minute costs); `max` on Studio clears the
 * target. The pairing is the point: the panel has to render one as a warning and neither as
 * a refusal. Shared by every screen that mounts the rate-card panel.
 */
export const OPS_RATE_CARD = {
  effective_from: "2026-09-07T04:30:00Z",
  target_gross_margin_pct: "20",
  // Nothing scheduled, and the notice window a change would have to respect.
  pending: [],
  notice_days: 30,
  notice_recipients: 3,
  earliest_effective_from: "2026-10-08T09:44:00Z",
  // The Clear column's cost floor, struck at the assumed speaking rate until enough calls
  // are measured.
  speaking_rate: {
    measured: false,
    chars_per_call_minute: "540",
    calls: 3,
    minimum_calls: 20,
    window: null,
    basis:
      "assumed 540 chars/call-min (TRD 10.1, unmeasured - pilot gate 12); 3 of 20 calls measured",
    cost_floor_inr_per_min: "4.1211",
    refusal_floor_inr_per_min: "4.1211",
    floor_above_refusal: false,
  },
  cells: [
    {
      pack_id: "starter",
      amount_inr: "2000.00",
      voice_tier: "clear",
      tier_label: "Clear",
      inr_per_min: "5.0000",
      cost_floor_inr_per_min: "4.1211",
      gross_margin_pct: "17.60",
      below_target: true,
      below_floor: false,
      breakeven_call_minutes: null,
      cost_inr_per_min_at_volume: "4.1211",
      gross_margin_pct_at_volume: "17.60",
      below_target_at_volume: true,
      below_floor_at_volume: false,
    },
    {
      pack_id: "max",
      amount_inr: "50000.00",
      voice_tier: "studio",
      tier_label: "Studio",
      inr_per_min: "6.0000",
      cost_floor_inr_per_min: "5.5899",
      gross_margin_pct: "6.84",
      below_target: true,
      below_floor: false,
      breakeven_call_minutes: "126",
      cost_inr_per_min_at_volume: "4.9299",
      gross_margin_pct_at_volume: "17.84",
      below_target_at_volume: true,
      below_floor_at_volume: false,
    },
  ],
  // THE VOLUME BLOCK the panel refuses to render a cost column without (9 Sep 2026): a
  // Studio minute's cost is a function of the month's volume, so a fixture that omitted it
  // would exercise the refusal arm rather than the table.
  cartesia_volume: {
    month: "2026-09",
    measured_call_minutes: "200",
    measured_characters: "108000",
    cost_inr_per_min: "4.9299",
    plan_id: "pro",
    assumed_chars_per_call_minute: "540",
    fx_usd_inr: "88",
    fx_source: "frankfurter:FBIL",
    fx_as_of: "2026-09-08",
    floor_inr_per_min: "5.5899",
    best_marginal_cost_inr_per_min: "4.6395",
    refusal_floor_inr_per_min: "5.5899",
    plan_crossover_call_minutes: "1439",
    plans: [
      {
        plan_id: "pro",
        fee_inr: "440",
        included_credits: "100000",
        included_call_minutes: "185",
        marginal_cost_inr_per_min: "5.5899",
        tts_concurrency: 3,
      },
    ],
    ladder: [
      { call_minutes: "200", plan_id: "pro", cost_inr_per_min: "4.9299" },
    ],
  },
} satisfies RateCard;

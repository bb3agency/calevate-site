import { describe, expect, it } from "vitest";

import { breakevenText } from "@/app/admin/ops/RateCardPanel";
import type { RateCardCell } from "@/lib/api/opsRateCard";

/**
 * The break-even column is EXHAUSTIVE over the rungs, never a ternary.
 *
 * ⚠ It read `cell.voice_tier !== "studio" ? "" : …` until 19 Sep 2026. `voice_tier` is a
 * plain `string` on the wire (`RateCardCellOut`), so that shape is total over every string
 * there is, and a rung this build does not know would have rendered BLANK under a column
 * headed "break-even" — which an operator reads as "this rung's cost does not move with
 * volume". That is a claim about a vendor's pricing model made by a comparison that never
 * looked at the vendor, and this ladder has gained and lost a rung twice this month
 * (D-618, D-629).
 *
 * The same defect, the same day and the same fix as the per-rung accessors in
 * `lib/api/rateCard.ts`, whose `unpricedTier` is the `never` arm here. The compile-time
 * half is that a third member of `VoiceTier` makes the switch a type error; this is the
 * runtime half, for a value that arrives off the wire from a newer server.
 */

function cell(over: Partial<RateCardCell> = {}): RateCardCell {
  return {
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
    ...over,
  };
}

describe("the break-even column", () => {
  it("is blank on the Clear rung, whose cost does not move with volume", () => {
    expect(breakevenText(cell())).toBe("");
  });

  it("prints the minutes on the Studio rung", () => {
    expect(
      breakevenText(cell({ voice_tier: "studio", breakeven_call_minutes: "126" })),
    ).toBe("126");
  });

  it('says "never" where no volume rescues the rate — a different fact from a big number', () => {
    expect(
      breakevenText(cell({ voice_tier: "studio", breakeven_call_minutes: null })),
    ).toBe("never");
  });

  it("does not render a rung it cannot name as if it were the Clear one", () => {
    // The regression: a third rung resolved to the blank arm, silently asserting that its
    // cost is flat. It has to fail VISIBLE instead — and it must not throw, because this
    // runs inside a render and would take the whole ops screen down with it.
    const unknown = breakevenText(cell({ voice_tier: "encore", tier_label: "Encore" }));
    expect(unknown).not.toBe("");
    expect(unknown).toBe("unknown rung");
  });
});

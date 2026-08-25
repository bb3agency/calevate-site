import { describe, expect, it } from "vitest";

import {
  CALEVATE_PAISE_PER_MIN,
  computeRoi,
  formatPaiseINR,
  type RoiInputs,
} from "@/lib/roi";

/**
 * The homepage ROI cost model. This is the honesty guarantee for the one priced surface on
 * the marketing site: the numbers have to add up exactly (integer paise, no float drift)
 * and the comparison has to stay truthful when a buyer pushes the inputs to their edges.
 */

/** The default-shaped inputs the calculator starts with; each test overrides what it probes. */
const BASE: RoiInputs = {
  callsPerDay: 200,
  avgMinutes: 2,
  workingDays: 26,
  callsPerAgentPerDay: 100,
  basePerAgentInr: 21_240,
  loadedPerAgentInr: 32_000,
  attritionPctPerYear: 40,
  replacementCostInr: 150_000,
};

describe("computeRoi — Calevate cost", () => {
  it("prices minutes at ₹5.00/min in exact paise", () => {
    // 200 calls × 26 days × 2 min = 10,400 min × ₹5.00 = ₹52,000.00 = 5,200,000 paise.
    const r = computeRoi(BASE);
    expect(r.callsPerMonth).toBe(5_200);
    expect(r.calevatePaise).toBe(5_200_000);
    expect(formatPaiseINR(r.calevatePaise)).toBe("₹52,000.00");
  });

  it("handles a fractional call length without float error", () => {
    // 100 calls × 20 days × 1.5 min = 3,000 min × ₹5 = ₹15,000.00. The 1.5 is the case a
    // naive `minutes * price` in floating point would round wrong.
    const r = computeRoi({ ...BASE, callsPerDay: 100, workingDays: 20, avgMinutes: 1.5 });
    expect(r.calevatePaise).toBe(1_500_000);
    expect(formatPaiseINR(r.calevatePaise)).toBe("₹15,000.00");
  });

  it("honours an overridden per-minute rate", () => {
    const r = computeRoi({ ...BASE, calevatePaisePerMin: 550 });
    // 10,400 min × ₹5.50 = ₹57,200.00.
    expect(r.calevatePaise).toBe(5_720_000);
  });

  it("defaults the rate to the shared constant", () => {
    expect(CALEVATE_PAISE_PER_MIN).toBe(500);
    const withDefault = computeRoi(BASE);
    const withExplicit = computeRoi({ ...BASE, calevatePaisePerMin: CALEVATE_PAISE_PER_MIN });
    expect(withDefault.calevatePaise).toBe(withExplicit.calevatePaise);
  });
});

describe("computeRoi — telecaller headcount", () => {
  it("rounds headcount UP — a partial agent is still a hire", () => {
    expect(computeRoi({ ...BASE, callsPerDay: 200 }).headcount).toBe(2);
    expect(computeRoi({ ...BASE, callsPerDay: 201 }).headcount).toBe(3);
    expect(computeRoi({ ...BASE, callsPerDay: 100 }).headcount).toBe(1);
    expect(computeRoi({ ...BASE, callsPerDay: 1 }).headcount).toBe(1);
  });

  it("scales headcount with the per-agent throughput the buyer sets", () => {
    expect(computeRoi({ ...BASE, callsPerDay: 300, callsPerAgentPerDay: 60 }).headcount).toBe(5);
    expect(computeRoi({ ...BASE, callsPerDay: 300, callsPerAgentPerDay: 140 }).headcount).toBe(3);
  });
});

describe("computeRoi — loaded cost and attrition", () => {
  it("splits base from the hidden loaded uplift", () => {
    // 2 agents: base 2 × ₹21,240 = ₹42,480; uplift 2 × (32,000 − 21,240) = 2 × 10,760 =
    // ₹21,520.
    const r = computeRoi(BASE);
    expect(r.humanBasePaise).toBe(42_480 * 100);
    expect(r.humanUpliftPaise).toBe(21_520 * 100);
  });

  it("floors the uplift at zero if loaded is dragged below base", () => {
    const r = computeRoi({ ...BASE, loadedPerAgentInr: 18_000, basePerAgentInr: 21_240 });
    expect(r.humanUpliftPaise).toBe(0);
    // Base still counts in full.
    expect(r.humanBasePaise).toBe(2 * 21_240 * 100);
  });

  it("amortises attrition monthly across the fleet", () => {
    // 2 agents × ₹1,50,000 × 40% ÷ 12 = 2 × 60,000 ÷ 12 = ₹10,000.00/mo.
    const r = computeRoi(BASE);
    expect(r.humanAttritionPaise).toBe(10_000 * 100);
  });

  it("totals base + uplift + attrition", () => {
    const r = computeRoi(BASE);
    expect(r.humanTotalPaise).toBe(
      r.humanBasePaise + r.humanUpliftPaise + r.humanAttritionPaise,
    );
    // ₹42,480 + ₹21,520 + ₹10,000 = ₹74,000.00.
    expect(formatPaiseINR(r.humanTotalPaise)).toBe("₹74,000.00");
  });

  it("reports the delta, which can be negative when the team is cheaper", () => {
    const r = computeRoi(BASE);
    // ₹74,000 − ₹52,000 = ₹22,000 in Calevate's favour.
    expect(r.deltaPaise).toBe(2_200_000);
    // At high minutes-per-call filling a single agent, the fixed-cost headcount can beat
    // pay-per-minute; the model must not hide it. 100 calls/day (still one agent) × 26 ×
    // 10 min × ₹5 = ₹1,30,000 vs one telecaller at ₹37,000.
    const lopsided = computeRoi({ ...BASE, callsPerDay: 100, avgMinutes: 10 });
    expect(lopsided.headcount).toBe(1);
    expect(lopsided.deltaPaise).toBeLessThan(0);
  });
});

describe("computeRoi — edge cases", () => {
  it("returns all zeros for zero calls, and never NaN", () => {
    const r = computeRoi({ ...BASE, callsPerDay: 0 });
    expect(r.headcount).toBe(0);
    expect(r.humanTotalPaise).toBe(0);
    expect(r.calevatePaise).toBe(0);
    expect(r.deltaPaise).toBe(0);
    expect(Number.isNaN(r.calevatePaise)).toBe(false);
  });

  it("clamps negative and non-finite inputs to zero", () => {
    const r = computeRoi({
      ...BASE,
      callsPerDay: -50,
      avgMinutes: Number.NaN,
      workingDays: Number.POSITIVE_INFINITY,
    });
    expect(r.callsPerMonth).toBe(0);
    expect(r.calevatePaise).toBe(0);
    expect(r.headcount).toBe(0);
  });

  it("returns zero headcount rather than dividing by zero throughput", () => {
    expect(computeRoi({ ...BASE, callsPerAgentPerDay: 0 }).headcount).toBe(0);
  });

  it("only computes pipeline value when the option is enabled", () => {
    expect(computeRoi(BASE).pipelineValuePaise).toBeNull();
    const r = computeRoi({
      ...BASE,
      leadValue: { enabled: true, convertedLeadInr: 5_000, conversionPct: 10 },
    });
    // 5,200 calls × 10% × ₹5,000 = ₹26,00,000.00.
    expect(r.pipelineValuePaise).toBe(26_00_000 * 100);
    expect(formatPaiseINR(r.pipelineValuePaise as number)).toBe("₹26,00,000.00");
  });
});

describe("formatPaiseINR — Indian grouping, digit-only", () => {
  it("groups last-three-then-twos and keeps two paise digits", () => {
    expect(formatPaiseINR(0)).toBe("₹0.00");
    expect(formatPaiseINR(500)).toBe("₹5.00");
    expect(formatPaiseINR(520_000)).toBe("₹5,200.00");
    expect(formatPaiseINR(1_00_00_000)).toBe("₹1,00,000.00");
    expect(formatPaiseINR(1_23_45_678)).toBe("₹1,23,456.78");
  });

  it("carries a leading minus for a negative delta", () => {
    expect(formatPaiseINR(-2_200_000)).toBe("-₹22,000.00");
  });
});

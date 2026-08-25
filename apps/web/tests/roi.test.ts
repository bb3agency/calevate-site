import { describe, expect, it } from "vitest";

import {
  CALEVATE_PAISE_PER_MIN,
  computeRoi,
  computeTwoStage,
  formatPaiseINR,
  TWO_STAGE,
  type RoiInputs,
  type TwoStageInputs,
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
  talkHoursPerDay: 5,
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
  it("defaults to a single business-hours shift when coverage is unset", () => {
    // No coverageHours on BASE — the everyday comparison must not inflate the human side.
    expect(computeRoi(BASE).shifts).toBe(1);
  });

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

  it("caps a short call at the DIAL ceiling, a long call at the TALK ceiling", () => {
    // 2-min calls, 5h talk = 150 talk-slots, but the dial ceiling of 100 is smaller.
    const short = computeRoi({ ...BASE, avgMinutes: 2 });
    expect(short.effectiveCallsPerAgentPerDay).toBe(100);
    expect(short.headcount).toBe(2); // ceil(200 / 100)

    // 4-min calls: 5h talk ÷ 4 = 75 slots now BELOW the dial ceiling, so it binds and
    // headcount rises with duration — the honest fix for "one agent = 100 calls" pretending
    // a person can talk 6.7 hours. 100 four-minute calls is physically impossible.
    const long = computeRoi({ ...BASE, avgMinutes: 4 });
    expect(long.effectiveCallsPerAgentPerDay).toBe(75); // floor(300 / 4)
    expect(long.headcount).toBe(3); // ceil(200 / 75), was 2 under the old fixed model
  });

  it("never lets talk-time exceed the dial ceiling on very short calls", () => {
    // 0.5-min calls would allow 600 talk-slots, but nobody dials more than the ceiling.
    const r = computeRoi({ ...BASE, avgMinutes: 0.5, callsPerAgentPerDay: 100 });
    expect(r.effectiveCallsPerAgentPerDay).toBe(100);
  });
});

describe("computeRoi — coverage (shifts), the always-on lever", () => {
  it("maps a coverage window to whole staffed shifts, capped at three", () => {
    // 9h shift: business hours = 1, into-the-evening (15h) = 2, around-the-clock = 3, and
    // nothing asks for more than three even if the hours are pushed past 24.
    expect(computeRoi({ ...BASE, coverageHours: 9 }).shifts).toBe(1);
    expect(computeRoi({ ...BASE, coverageHours: 15 }).shifts).toBe(2);
    expect(computeRoi({ ...BASE, coverageHours: 24 }).shifts).toBe(3);
    expect(computeRoi({ ...BASE, coverageHours: 48 }).shifts).toBe(3);
  });

  it("staffs every shift even when a shift's share of the volume is light", () => {
    // 30 calls/day around the clock: split three ways that is 10 calls a shift, well under
    // one agent's capacity — but you cannot answer a 2am call with nobody on, so it is
    // three agents, one per shift. This is the case an always-on human rota really costs
    // and an agent does not: Calevate charges only for the minutes actually spoken.
    const r = computeRoi({ ...BASE, callsPerDay: 30, avgMinutes: 3, coverageHours: 24 });
    expect(r.shifts).toBe(3);
    expect(r.headcount).toBe(3);
    // Three loaded agents dwarf a pay-per-minute bill of 30 × 26 × 3 min × ₹5 = ₹11,700.
    expect(r.calevatePaise).toBe(11_700 * 100);
    expect(r.deltaPaise).toBeGreaterThan(0); // Calevate is far cheaper here.
  });

  it("multiplies a busy line's headcount by the shifts it must cover", () => {
    // The screenshot case: 500 calls/day, 4-min calls. One shift needs ceil(500/75)=7.
    const oneShift = computeRoi({ ...BASE, callsPerDay: 500, avgMinutes: 4 });
    expect(oneShift.shifts).toBe(1);
    expect(oneShift.headcount).toBe(7);

    // Around the clock: 500 spread over 3 shifts = 167 a shift, ceil(167/75)=3 per shift,
    // ×3 = 9 agents to keep the line answered all day. Calevate's minutes — and so its
    // bill — are identical to the single-shift case; only the human side grew.
    const allDay = computeRoi({ ...BASE, callsPerDay: 500, avgMinutes: 4, coverageHours: 24 });
    expect(allDay.shifts).toBe(3);
    expect(allDay.headcount).toBe(9);
    expect(allDay.calevatePaise).toBe(oneShift.calevatePaise);
    expect(allDay.humanTotalPaise).toBeGreaterThan(oneShift.humanTotalPaise);
  });

  it("leaves Calevate's cost untouched by the coverage window", () => {
    const business = computeRoi({ ...BASE, coverageHours: 9 });
    const roundClock = computeRoi({ ...BASE, coverageHours: 24 });
    expect(roundClock.calevatePaise).toBe(business.calevatePaise);
  });

  it("still reports zero headcount for zero calls, whatever the coverage", () => {
    expect(computeRoi({ ...BASE, callsPerDay: 0, coverageHours: 24 }).headcount).toBe(0);
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
    // At high minutes-per-call, a single agent's fixed cost can beat pay-per-minute; the
    // model must not hide it. With the duration-aware ceiling, a 10-min call lets one agent
    // handle only floor(5h×60 / 10) = 30 calls/day, so 30 calls/day is still exactly one
    // telecaller: 30 × 26 × 10 min × ₹5 = ₹39,000 of Calevate vs one telecaller at ₹37,000.
    const lopsided = computeRoi({ ...BASE, callsPerDay: 30, avgMinutes: 10 });
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

/**
 * The two-stage funnel — the comparison that is honest once a call is long enough to be a
 * sales conversation. The single-stage showdown above compares Calevate against a
 * telecaller on the SAME calls; this one compares a team that works the whole list against
 * a team that works only the qualified share of it, with Calevate holding the short first
 * call with everybody.
 *
 * The property that matters most here is the last describe: it must be able to LOSE. A
 * model that cannot come out behind is a sales asset, not a calculator.
 */
const TWO: TwoStageInputs = {
  ...BASE,
  // Six minutes is the case the whole mode exists for — long enough that the call is a
  // conversation, and the length at which the old head-to-head comparison stopped being
  // a comparison of alternatives.
  avgMinutes: 6,
  qualifiedPct: TWO_STAGE.qualifiedPct.default,
  qualifyMinutes: TWO_STAGE.qualifyMinutes.default,
};

describe("computeTwoStage — the worked example the page shows", () => {
  it("prices 200 calls a day at 6-minute conversations, to the paise", () => {
    const r = computeTwoStage(TWO);

    // A — people call all 5,200. One person manages floor(5h×60 ÷ 6) = 50 a day, so four
    // salespeople: base 4×₹21,240 = ₹84,960, uplift 4×₹10,760 = ₹43,040, attrition
    // 4×₹1,50,000×40% ÷ 12 = ₹20,000. Total ₹1,48,000.
    expect(r.allHuman.headcount).toBe(4);
    expect(r.allHuman.humanTotalPaise).toBe(14_800_000);
    expect(formatPaiseINR(r.allHuman.humanTotalPaise)).toBe("₹1,48,000.00");

    // B, stage 1 — Calevate's 2-minute call to every one of the 5,200: ₹52,000.
    expect(r.qualificationPaise).toBe(5_200_000);

    // B, stage 2 — 30% of 200 = 60 conversations a day, still 50 per person, so TWO
    // salespeople rather than four: ₹42,480 + ₹21,520 + ₹10,000 = ₹74,000.
    expect(r.qualifiedCallsPerDay).toBe(60);
    expect(r.qualifiedCallsPerMonth).toBe(1_560);
    expect(r.humans.headcount).toBe(2);
    expect(r.humans.humanTotalPaise).toBe(7_400_000);

    // Together ₹1,26,000 — ₹22,000 a month less than ₹1,48,000.
    expect(r.blendedTotalPaise).toBe(12_600_000);
    expect(formatPaiseINR(r.blendedTotalPaise)).toBe("₹1,26,000.00");
    expect(r.deltaPaise).toBe(2_200_000);
    expect(formatPaiseINR(r.deltaPaise)).toBe("₹22,000.00");
  });

  it("counts the calls that never reach a person, and the hours that buys back", () => {
    const r = computeTwoStage(TWO);
    // 5,200 − 1,560 = 3,640 calls a month settled by the first call alone; at the 6-minute
    // conversation they would each have cost, that is 21,840 minutes — 364 hours.
    expect(r.triagedAwayPerMonth).toBe(3_640);
    expect(r.humanMinutesReleased).toBe(21_840);
    expect(Math.round(r.humanMinutesReleased / 60)).toBe(364);
  });

  it("keeps released minutes exact on a fractional conversation length", () => {
    // 2.5 min is the case a naive `count * minutes` in floating point rounds wrong.
    const r = computeTwoStage({
      ...TWO,
      callsPerDay: 100,
      workingDays: 20,
      avgMinutes: 2.5,
      qualifiedPct: 50,
    });
    expect(r.triagedAwayPerMonth).toBe(1_000);
    expect(r.humanMinutesReleased).toBe(2_500);
  });
});

describe("computeTwoStage — composition and the qualified share", () => {
  it("reports option A as exactly the single-stage human side of the same inputs", () => {
    // One cost model, run twice — so the two sides of the comparison can never disagree
    // about what a telecaller costs.
    const r = computeTwoStage(TWO);
    expect(r.allHuman).toEqual(computeRoi(TWO));
  });

  it("rounds the qualified share UP — a part-lead is still a conversation", () => {
    expect(computeTwoStage({ ...TWO, callsPerDay: 101, qualifiedPct: 30 }).qualifiedCallsPerDay)
      .toBe(31); // ceil(30.3)
    expect(computeTwoStage({ ...TWO, callsPerDay: 1, qualifiedPct: 5 }).qualifiedCallsPerDay)
      .toBe(1);
  });

  it("drives human headcount off the QUALIFIED volume, not the raw list", () => {
    const thin = computeTwoStage({ ...TWO, qualifiedPct: 10 }); // 20 conversations a day
    expect(thin.humans.headcount).toBe(1);
    expect(thin.allHuman.headcount).toBe(4);
  });

  it("prices the first call at the qualification length, over the WHOLE list", () => {
    // The first call goes to everyone — the qualified share must not shrink it.
    const a = computeTwoStage({ ...TWO, qualifiedPct: 10 });
    const b = computeTwoStage({ ...TWO, qualifiedPct: 90 });
    expect(a.qualificationPaise).toBe(b.qualificationPaise);
    // And it scales with the first call's length, not the conversation's.
    expect(computeTwoStage({ ...TWO, qualifyMinutes: 4 }).qualificationPaise).toBe(
      2 * a.qualificationPaise,
    );
  });

  it("staffs every covered shift on both sides of the comparison", () => {
    const r = computeTwoStage({ ...TWO, coverageHours: 24 });
    expect(r.allHuman.shifts).toBe(3);
    // 200 ÷ 3 = 67 a shift, ceil(67/50) = 2 per shift → 6.
    expect(r.allHuman.headcount).toBe(6);
    // 60 ÷ 3 = 20 a shift, one person each → 3. The qualified list still has to be worked
    // in every window the buyer says they cover.
    expect(r.humans.headcount).toBe(3);
  });
});

describe("computeTwoStage — it has to be able to lose, and not to NaN", () => {
  it("goes NEGATIVE when everything on the list is worth a conversation", () => {
    // Nothing for a first call to filter out, so it is an extra call on top of the same
    // team. The verdict copy is required to say so; this is the number it says it from.
    const r = computeTwoStage({ ...TWO, qualifiedPct: 100 });
    expect(r.qualifiedCallsPerDay).toBe(200);
    expect(r.humans.humanTotalPaise).toBe(r.allHuman.humanTotalPaise);
    expect(r.blendedTotalPaise).toBe(r.allHuman.humanTotalPaise + r.qualificationPaise);
    expect(r.deltaPaise).toBe(-5_200_000);
    expect(r.triagedAwayPerMonth).toBe(0);
    expect(r.humanMinutesReleased).toBe(0);
  });

  it("clamps a share above 100 rather than inventing leads that are not there", () => {
    const over = computeTwoStage({ ...TWO, qualifiedPct: 150 });
    expect(over.qualifiedCallsPerDay).toBe(200);
    expect(over.triagedAwayPerMonth).toBe(0);
  });

  it("treats a negative or non-finite share as none qualified", () => {
    const none = computeTwoStage({ ...TWO, qualifiedPct: Number.NaN });
    expect(none.qualifiedCallsPerDay).toBe(0);
    expect(none.humans.headcount).toBe(0);
    // Only the first call is billed, and the whole list is triaged away.
    expect(none.blendedTotalPaise).toBe(none.qualificationPaise);
    expect(none.triagedAwayPerMonth).toBe(5_200);
  });

  it("returns zeros for zero calls, and never NaN", () => {
    const r = computeTwoStage({ ...TWO, callsPerDay: 0 });
    expect(r.allHuman.humanTotalPaise).toBe(0);
    expect(r.qualificationPaise).toBe(0);
    expect(r.blendedTotalPaise).toBe(0);
    expect(r.deltaPaise).toBe(0);
    expect(r.triagedAwayPerMonth).toBe(0);
    expect(Number.isNaN(r.humanMinutesReleased)).toBe(false);
  });

  it("keeps its defaults inside the ranges the sliders clamp to", () => {
    for (const bound of [TWO_STAGE.qualifiedPct, TWO_STAGE.qualifyMinutes]) {
      expect(bound.default).toBeGreaterThanOrEqual(bound.min);
      expect(bound.default).toBeLessThanOrEqual(bound.max);
    }
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

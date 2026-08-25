/**
 * The cost model behind the homepage ROI calculator ("AI vs. hiring telecallers").
 *
 * ## Why this is a pure module with its own money arithmetic
 *
 * This is the ONE marketing surface that puts a number on the core sales argument, so it
 * has to be honest under a buyer who changes every input — which is exactly why the math
 * lives here, unit-tested, rather than inline in a component nobody can assert on.
 *
 * It is NOT billing. Hard rule 7 governs `unit_cost_paid` and every rupee that reaches a
 * wallet; those live in `billing/rates.py` server-side and never in the browser
 * (`lib/llmRates.ts` is emphatic that the client compares rates but never prices a call).
 * This is an ILLUSTRATIVE estimate a prospect drives themselves. But the reason hard rule
 * 7 exists — `Number("0.1") * 3` is `0.30000000000000004`, which prints a rupee figure
 * nobody was ever quoted — bites an estimate on a public page just as hard, so every
 * amount here is an INTEGER COUNT OF PAISE and every rupee/percent input is converted to
 * an integer before it multiplies anything. Numbers are rounded exactly once, at the end
 * of each line, and formatted straight from the digit string (`formatPaiseINR`) without
 * ever being re-parsed as a float.
 *
 * ## The defaults are illustrative, sourced, and every one is adjustable in the UI
 *
 * Credibility on this page comes from letting the buyer change the assumptions, not from
 * asserting ours. The component surfaces each figure and its benchmark range; this module
 * only carries the defaults and the ranges the sliders clamp to. Sources are cited on the
 * constants below and again in the page's "How we calculate this" disclosure.
 */

/**
 * Calevate's self-serve price, in PAISE per minute.
 *
 * MUST TRACK `self_serve_inr_per_min` in `packages/shared/src/calevate_shared/config.py`
 * (default `Decimal("5.00")`). It is duplicated here rather than fetched because the
 * homepage is public and unauthenticated (no API call), and a marketing estimate at the
 * published self-serve rate is the honest thing to show. If the backend price moves, this
 * constant moves with it — they are one price with two spellings, and the second is where
 * drift starts. 500 paise = ₹5.00/min.
 */
export const CALEVATE_PAISE_PER_MIN = 500;

/** A benchmark figure shown to the buyer, with the range the slider allows. */
export interface Benchmark {
  readonly default: number;
  readonly min: number;
  readonly max: number;
  readonly step: number;
}

/**
 * The telecaller-side benchmarks. Each is illustrative and adjustable; the ranges are the
 * spread reported for Indian voice-process / telecalling roles, not a claim of precision.
 *
 * - `callsPerAgentPerDay` — a productive agent handles roughly 80–120 dials/day on a
 *   5.5–6.5 hour productive shift; 100 is the round mid-point used for headcount.
 * - `basePerAgentInr` — advertised base pay clusters around ₹18k–₹25k/month for the role;
 *   ~₹21,240 is a common mid-figure. This is the number a job ad shows.
 * - `loadedPerAgentInr` — the base plus PF/ESI, on-target incentives (commonly 30–80% of
 *   base), a share of a supervisor, desk/power/phone/software, and ramp-up time before an
 *   agent is fully productive. ~₹32,000 is a mid loaded figure; the whole point of the
 *   calculator is that the base hides this.
 * - `attritionPctPerYear` — annual attrition in this role is widely reported at 35–45%.
 * - `replacementCostInr` — hiring + training + lost productivity to replace one leaver is
 *   commonly put at ₹1–2 lakh; folded in amortised monthly.
 *
 * These are relayed benchmarks, not measurements Calevate has taken; the UI labels them
 * so and the buyer moves them.
 */
export const TELECALLER: {
  callsPerAgentPerDay: Benchmark;
  talkHoursPerDay: Benchmark;
  basePerAgentInr: Benchmark;
  loadedPerAgentInr: Benchmark;
  attritionPctPerYear: Benchmark;
  replacementCostInr: Benchmark;
} = {
  callsPerAgentPerDay: { default: 100, min: 60, max: 140, step: 5 },
  // Productive TALK hours in a shift — the second, harder ceiling on how many calls one
  // agent can take. A 5.5–6.5 hour shift is not 6 hours of talk: dialling, ringing,
  // no-answers, wrap-up and breaks eat into it, so ~5h of actual talk is a generous
  // upper bound (many report 3–4h). This is what makes headcount rise with call length —
  // a fixed "calls per agent" pretends one person can talk for impossible hours on long
  // calls, which is the single thing that made this comparison read wrong at 4-min calls.
  talkHoursPerDay: { default: 5, min: 3, max: 6.5, step: 0.5 },
  basePerAgentInr: { default: 21_240, min: 15_000, max: 30_000, step: 500 },
  loadedPerAgentInr: { default: 32_000, min: 20_000, max: 45_000, step: 500 },
  attritionPctPerYear: { default: 40, min: 20, max: 60, step: 1 },
  replacementCostInr: { default: 150_000, min: 50_000, max: 300_000, step: 10_000 },
};

/** The three usage inputs and their defaults / slider ranges. */
export const USAGE: {
  callsPerDay: Benchmark;
  avgMinutes: Benchmark;
  workingDays: Benchmark;
} = {
  callsPerDay: { default: 200, min: 0, max: 2_000, step: 10 },
  avgMinutes: { default: 2, min: 0.5, max: 10, step: 0.5 },
  workingDays: { default: 26, min: 1, max: 31, step: 1 },
};

/**
 * How long a single human shift covers, in hours. A voice-process shift is ~8–9 hours
 * gross (of which only {@link TELECALLER.talkHoursPerDay} is actual talk); 9 is used so a
 * "business hours" line is exactly ONE shift and the everyday case never inflates the human
 * side. Coverage windows longer than this need more shifts STAFFED — the honest, and
 * usually decisive, difference between a person and an always-on agent.
 */
export const SHIFT_HOURS = 9;

/**
 * The coverage lever: how many hours a day the line must actually be answered.
 *
 * This is the one advantage a pure per-minute-vs-salary showdown hides. A telecaller works
 * one shift; a Calevate agent answers whenever the phone rings, at the SAME per-minute
 * price whether the call is at 11am or 2am. So to compare like with like, the human side
 * has to staff every shift the buyer needs covered — `ceil(coverageHours / SHIFT_HOURS)`
 * teams — while Calevate's cost does not move. Default is one shift, so the comparison only
 * widens when the buyer says out loud that they need the evenings or the nights too.
 */
export const COVERAGE: readonly { hours: number; shifts: number; label: string; caption: string }[] = [
  { hours: 9, shifts: 1, label: "Business hours", caption: "≈9 hrs · one shift" },
  { hours: 15, shifts: 2, label: "Into the evening", caption: "≈15 hrs · two shifts" },
  { hours: 24, shifts: 3, label: "Around the clock", caption: "24 hrs · three shifts" },
];

/** The optional missed-lead-value inputs (advanced, off by default). */
export const LEAD_VALUE: {
  convertedLeadInr: Benchmark;
  conversionPct: Benchmark;
} = {
  convertedLeadInr: { default: 5_000, min: 100, max: 500_000, step: 100 },
  conversionPct: { default: 10, min: 1, max: 100, step: 1 },
};

export interface RoiInputs {
  /** Calls handled per working day. */
  callsPerDay: number;
  /** Average call duration, in minutes (may be fractional, e.g. 1.5). */
  avgMinutes: number;
  /** Working days per month. */
  workingDays: number;
  /**
   * Hours a day the line must be answered. Optional; omit for a single business-hours
   * shift. Longer windows need more human shifts staffed (see {@link COVERAGE}); Calevate's
   * cost is unaffected because it answers at the same rate around the clock.
   */
  coverageHours?: number;
  /** Hours one human shift covers — defaults to {@link SHIFT_HOURS}. */
  shiftHours?: number;
  /** Calevate price in paise/min — defaults to {@link CALEVATE_PAISE_PER_MIN}. */
  calevatePaisePerMin?: number;
  /** Dial ceiling: the most calls one telecaller can start in a day (dialling/wrap-limited). */
  callsPerAgentPerDay: number;
  /** Productive talk hours per agent per day — the talk-time ceiling on daily calls. */
  talkHoursPerDay: number;
  /** Advertised base pay per agent per month, in whole rupees. */
  basePerAgentInr: number;
  /** Fully loaded cost per agent per month, in whole rupees. */
  loadedPerAgentInr: number;
  /** Annual attrition, as a percentage (e.g. 40 for 40%). */
  attritionPctPerYear: number;
  /** Cost to replace one leaver, in whole rupees. */
  replacementCostInr: number;
  /** Optional missed-lead-value context; omit or set enabled=false to leave it out. */
  leadValue?: {
    enabled: boolean;
    convertedLeadInr: number;
    conversionPct: number;
  };
}

export interface RoiResult {
  /** Calls per month = callsPerDay × workingDays. */
  callsPerMonth: number;
  /**
   * Calls ONE agent can actually handle a day at this call length = the smaller of the
   * dial ceiling and the talk-time ceiling (floor(talkHours×60 / avgMinutes)). This is
   * what falls as calls get longer, so headcount rises with duration just as Calevate's
   * per-minute cost does — the honest apples-to-apples the fixed "100 calls" hid.
   */
  effectiveCallsPerAgentPerDay: number;
  /**
   * Shifts the human side must staff to cover the requested window =
   * `clamp(ceil(coverageHours / shiftHours), 1..3)`. 1 for a business-hours line; 3 for
   * around-the-clock. Calevate needs none of this — it is the same price at every hour.
   */
  shifts: number;
  /**
   * Telecallers needed. For one shift this is `ceil(callsPerDay / perAgent)` as before; for
   * a wider window it is `shifts × max(1, ceil((callsPerDay / shifts) / perAgent))` — every
   * staffed shift needs at least one person on the phone even when its share of the volume
   * is light, which is exactly the cost an always-on human rota carries and an agent does
   * not.
   */
  headcount: number;
  /** Fleet base pay (headcount × base), in paise. */
  humanBasePaise: number;
  /**
   * Everything the base hides — PF/ESI, incentives, supervisor share, desk/overhead,
   * ramp — across the fleet, in paise. `max(0, loaded − base) × headcount`.
   */
  humanUpliftPaise: number;
  /** Amortised monthly attrition cost across the fleet, in paise. */
  humanAttritionPaise: number;
  /** Total telecaller cost per month (base + uplift + attrition), in paise. */
  humanTotalPaise: number;
  /** Calevate cost per month (variable, pay-per-minute), in paise. */
  calevatePaise: number;
  /** humanTotal − calevate; positive means Calevate is cheaper. May be negative. */
  deltaPaise: number;
  /**
   * Optional: monthly value of conversions across these calls
   * (callsPerMonth × conversion% × lead value), in paise. `null` when not enabled.
   * Framed in the UI as pipeline in play, not attributed to either option.
   */
  pipelineValuePaise: number | null;
}

/** Clamp to a finite, non-negative number; NaN/Infinity/negatives become 0. */
function nonNeg(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 0;
}

/**
 * Compute the whole comparison. Pure and total: any un-finite or negative input is
 * treated as 0, so a stray empty field can never produce `NaN` on screen.
 */
export function computeRoi(inputs: RoiInputs): RoiResult {
  const callsPerDay = Math.floor(nonNeg(inputs.callsPerDay));
  const workingDays = Math.floor(nonNeg(inputs.workingDays));
  const callsPerMonth = callsPerDay * workingDays;

  // Calevate: integer paise throughout. avgMinutes may be fractional, so carry it as an
  // integer count of hundredths-of-a-minute and divide (with a single final round) only
  // once the multiply is done — never `minutes * price` in floating point.
  const minuteHundredths = Math.round(nonNeg(inputs.avgMinutes) * 100);
  const calevatePaisePerMin = Math.round(
    nonNeg(inputs.calevatePaisePerMin ?? CALEVATE_PAISE_PER_MIN),
  );
  const calevatePaise = Math.round(
    (callsPerMonth * minuteHundredths * calevatePaisePerMin) / 100,
  );

  // Telecaller headcount. A human's day is bounded BOTH ways: a dial ceiling (dialling,
  // ringing, no-answers, wrap-up between calls) AND raw talk-time. At short calls the dial
  // ceiling binds; as calls get longer the talk-time ceiling takes over, because one
  // person cannot talk for more hours than a shift holds. Taking the SMALLER of the two is
  // what makes headcount — and so the human bill — rise with call length, instead of
  // pretending 100 four-minute calls (≈6.7h of pure talk) fit in a shift.
  const dialCeiling = Math.floor(nonNeg(inputs.callsPerAgentPerDay));
  const talkMinutesPerDay = nonNeg(inputs.talkHoursPerDay) * 60;
  const talkCeiling =
    minuteHundredths > 0
      ? Math.floor((talkMinutesPerDay * 100) / minuteHundredths)
      : dialCeiling;
  const perAgent = Math.max(0, Math.min(dialCeiling, talkCeiling));

  // Coverage: a person works ONE shift, so answering a wider window means staffing more
  // shifts. Calevate answers every hour at the same rate, so this multiplies the human side
  // and leaves Calevate untouched — the honest core of "always on" that a per-minute-only
  // comparison hides. Volume is spread across the staffed shifts (an even split is the
  // conservative, human-favourable assumption), but every staffed shift still needs at
  // least one agent on the phone, which is what an always-on human rota really costs.
  const shiftHours = nonNeg(inputs.shiftHours ?? 0) > 0 ? nonNeg(inputs.shiftHours ?? 0) : SHIFT_HOURS;
  const coverageHours =
    nonNeg(inputs.coverageHours ?? 0) > 0 ? nonNeg(inputs.coverageHours ?? 0) : shiftHours;
  const shifts = Math.min(3, Math.max(1, Math.ceil(coverageHours / shiftHours)));
  const headcount =
    perAgent > 0 && callsPerDay > 0
      ? shifts * Math.max(1, Math.ceil(callsPerDay / shifts / perAgent))
      : 0;

  const baseInr = Math.round(nonNeg(inputs.basePerAgentInr));
  const loadedInr = Math.round(nonNeg(inputs.loadedPerAgentInr));
  // The loaded figure is meant to sit at or above base; if a buyer drags it below, the
  // hidden-cost bucket floors at zero rather than going negative.
  const upliftInr = Math.max(0, loadedInr - baseInr);

  const humanBasePaise = headcount * baseInr * 100;
  const humanUpliftPaise = headcount * upliftInr * 100;

  // Amortised attrition: replacing `attrition%` of the fleet each year, spread monthly.
  // replacementInr × attrition% ÷ 100 ÷ 12, in paise, per agent, times headcount. One
  // round at the end keeps it in whole paise.
  const attritionPct = nonNeg(inputs.attritionPctPerYear);
  const replacementInr = Math.round(nonNeg(inputs.replacementCostInr));
  const humanAttritionPaise = Math.round(
    (headcount * replacementInr * attritionPct * 100) / 100 / 12,
  );

  const humanTotalPaise = humanBasePaise + humanUpliftPaise + humanAttritionPaise;
  const deltaPaise = humanTotalPaise - calevatePaise;

  let pipelineValuePaise: number | null = null;
  if (inputs.leadValue?.enabled) {
    const leadInr = Math.round(nonNeg(inputs.leadValue.convertedLeadInr));
    const conversionPct = nonNeg(inputs.leadValue.conversionPct);
    pipelineValuePaise = Math.round(
      (callsPerMonth * conversionPct * leadInr * 100) / 100,
    );
  }

  return {
    callsPerMonth,
    effectiveCallsPerAgentPerDay: perAgent,
    shifts,
    headcount,
    humanBasePaise,
    humanUpliftPaise,
    humanAttritionPaise,
    humanTotalPaise,
    calevatePaise,
    deltaPaise,
    pipelineValuePaise,
  };
}

/**
 * Format an integer count of paise as an Indian-grouped rupee string, e.g. `520000` →
 * `"₹5,200.00"`. Digit-only, like `ui.tsx::formatINR`: the paise integer is split into
 * whole rupees and remainder, the rupees are grouped last-three-then-twos, and the paise
 * are two fixed digits — the value is never turned back into a float. Kept here (rather
 * than importing `formatINR`) so this money module is self-contained and unit-testable
 * with no React dependency.
 */
export function formatPaiseINR(paise: number): string {
  const negative = paise < 0;
  const abs = Math.abs(Math.round(paise));
  const rupees = Math.floor(abs / 100);
  const remainder = abs % 100;
  const whole = String(rupees);
  const head = whole.length > 3 ? whole.slice(0, -3) : "";
  const tail = whole.slice(-3);
  const grouped = head
    ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`
    : tail;
  const paisePart = String(remainder).padStart(2, "0");
  return `${negative ? "-" : ""}₹${grouped}.${paisePart}`;
}

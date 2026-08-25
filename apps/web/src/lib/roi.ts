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
  basePerAgentInr: Benchmark;
  loadedPerAgentInr: Benchmark;
  attritionPctPerYear: Benchmark;
  replacementCostInr: Benchmark;
} = {
  callsPerAgentPerDay: { default: 100, min: 60, max: 140, step: 5 },
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
  /** Calevate price in paise/min — defaults to {@link CALEVATE_PAISE_PER_MIN}. */
  calevatePaisePerMin?: number;
  /** Calls one telecaller handles per day. */
  callsPerAgentPerDay: number;
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
  /** Telecallers needed = ceil(callsPerDay / callsPerAgentPerDay). */
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

  // Telecaller headcount and cost.
  const perAgent = Math.floor(nonNeg(inputs.callsPerAgentPerDay));
  const headcount = perAgent > 0 ? Math.ceil(callsPerDay / perAgent) : 0;

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

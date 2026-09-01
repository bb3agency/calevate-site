"use client";

/**
 * The homepage ROI calculator, driven by the buyer. It runs TWO comparisons.
 *
 * ## Why two, and why the second one exists
 *
 * The original — Calevate taking the SAME calls a telecaller would — is honest for a
 * receptionist workload and is still the default, because the default call length here is
 * two minutes and a two-minute call is an enquiry being written down. Run at six minutes
 * it compares two things that were never alternatives: a six-minute call is a sales
 * conversation, and nobody's alternative to their closer is a cheaper closer. It lost
 * there, and it deserved to.
 *
 * The second mode is the like-for-like one at that length, and it is the split every sales
 * organisation already runs: one person qualifies, another closes. Calevate holds the
 * short first call with the WHOLE list; the salespeople hold the full conversation only
 * with the qualified share, so headcount follows the qualified volume rather than the raw
 * one. `lib/roi.ts::computeTwoStage` prices it, and the rupee delta is the smaller half of
 * the answer — the argument is where the team's hours go. `docs/POSITIONING-QUALIFICATION-
 * LAYER.md` records the positioning, the vocabulary and, at length, the conversion
 * statistics that were REFUSED for want of a primary source (hard rule 11).
 *
 * ## Why a price appears here at all, on a page whose rule is "no prices"
 *
 * The landing page deliberately publishes no plan price (see `app/page.tsx` — D-11's
 * managed pricing is per-client and unquotable). This section is the one exception, and
 * it earns it by being a TOOL rather than a tag: it shows Calevate's published self-serve
 * rate (`self_serve_inr_per_min`, ₹5.00/min) as the input to a comparison the prospect
 * runs themselves, with every assumption on both sides exposed and adjustable. A number a
 * buyer can change and check is not the "quote nobody can honour" the page bans; a fixed
 * "₹X/month" would be. `publicLanding.test.tsx` scopes its price/percent bans to exclude
 * this section for exactly that reason, and keeps them in force everywhere else.
 *
 * ## Honesty is the whole design
 *
 * The telecaller side is built to be believed, not to win: the defaults are relayed
 * industry benchmarks (cited in `lib/roi.ts` and in the "How we calculate this"
 * disclosure), labelled illustrative, and every one is a slider the buyer can move. If the
 * running costs come out close at low volume, the delta line SAYS they are close and
 * hands the argument to the row of things a headcount cannot do — it never fakes a gap.
 * The two-stage mode is held to the same rule from the same three branches: set the
 * qualified share to everyone and it prints that the funnel costs MORE, in those words.
 * All money is integer paise (`lib/roi.ts`), formatted from digits, never floated.
 *
 * No borrowed statistic appears anywhere on this surface. Every conversion figure this
 * play is usually sold with traces to a source this sandbox could not read, so the whole
 * argument is arithmetic the buyer drives — which they cannot dispute, because the inputs
 * are theirs.
 *
 * ## No network
 *
 * The page is public and unauthenticated. This component fetches nothing; the price is the
 * `CALEVATE_PAISE_PER_MIN` constant, kept in lockstep with the backend config value.
 */

import { useId, useMemo, useState } from "react";
import {
  Bot,
  Clock3,
  Filter,
  Handshake,
  Infinity as InfinityIcon,
  ShieldCheck,
  Table2,
  TrendingDown,
  UserRound,
} from "lucide-react";

import {
  COVERAGE,
  computeRoi,
  computeTwoStage,
  formatPaiseINR,
  LEAD_VALUE,
  TELECALLER,
  TWO_STAGE,
  USAGE,
  type Benchmark,
} from "@/lib/roi";

/** A number field and a slider bound to one value, kept in sync and both labelled. */
function Control({
  label,
  bounds,
  value,
  onChange,
  unit,
  hint,
}: {
  label: string;
  bounds: Benchmark;
  value: number;
  onChange: (next: number) => void;
  /** A short suffix inside the number field, e.g. "calls" or "min". */
  unit?: string;
  hint?: string;
}) {
  const id = useId();
  // Empty is a legitimate transient state while typing; it reads back as 0 in the model
  // (`lib/roi.ts` clamps), so the display can never show NaN.
  const set = (raw: string) => onChange(raw === "" ? 0 : Number(raw));

  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
        </label>
        <div className="flex items-center gap-1.5">
          <input
            id={id}
            type="number"
            inputMode="decimal"
            min={bounds.min}
            max={bounds.max}
            step={bounds.step}
            value={Number.isFinite(value) ? value : 0}
            onChange={(e) => set(e.target.value)}
            className="w-24 rounded-md border border-line bg-app px-2.5 py-1.5 text-right text-sm font-semibold tabular-nums text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong touch:min-h-11"
          />
          {unit && <span className="w-10 text-xs text-ink-faint">{unit}</span>}
        </div>
      </div>
      <input
        type="range"
        min={bounds.min}
        max={bounds.max}
        step={bounds.step}
        value={Number.isFinite(value) ? Math.min(Math.max(value, bounds.min), bounds.max) : bounds.min}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
        aria-valuetext={unit ? `${value} ${unit}` : String(value)}
        /*
         * A 24px THUMB UNDER A COARSE POINTER, and the number is derived rather than
         * chosen. A 16px thumb is a comfortable mouse target and a poor thumb target: it
         * is under WCAG 2.2 SC 2.5.8's 24px AA minimum, and this is the one control on the
         * page a phone user is expected to DRAG rather than tap.
         *
         * The webkit thumb is positioned by a negative top margin against a 6px runnable
         * track, so the offset is not free: it is −(thumb − track) / 2, which is where the
         * existing −5px comes from (16 − 6) / 2. At 24px it is (24 − 6) / 2 = 9. Firefox
         * centres `::-moz-range-thumb` itself and needs no offset, which is why only the
         * webkit rule has one.
         *
         * The 44px path to the same value still exists and is the one to reach for if a
         * finger cannot manage this: every slider on this surface is paired with the
         * labelled number field above it, which carries `touch:min-h-11`.
         */
        className="mt-3 w-full cursor-pointer appearance-none bg-transparent [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-brand-strong [&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-line [&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-line [&::-webkit-slider-thumb]:-mt-[5px] [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-strong focus-visible:outline-none touch:[&::-moz-range-thumb]:h-6 touch:[&::-moz-range-thumb]:w-6 touch:[&::-webkit-slider-thumb]:-mt-[9px] touch:[&::-webkit-slider-thumb]:h-6 touch:[&::-webkit-slider-thumb]:w-6 dark:[&::-moz-range-thumb]:bg-brand-bright dark:[&::-webkit-slider-thumb]:bg-brand-bright"
      />
      {hint && <p className="mt-1.5 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}

/**
 * A small group of named choices, as cards. Buttons in a `radiogroup` rather than native
 * radios because each option carries a heading and a caption, and there are exactly two
 * such groups on this surface (which comparison to run, and how many hours to cover) — a
 * second hand-rolled copy is where the keyboard semantics of one of them would drift.
 */
function RadioCards<T extends string | number>({
  legend,
  options,
  value,
  onChange,
  columns,
}: {
  legend: string;
  options: readonly { id: T; label: string; caption: string }[];
  value: T;
  onChange: (next: T) => void;
  columns: 2 | 3;
}) {
  return (
    <fieldset className="border-0 p-0">
      <legend className="text-sm font-medium text-ink">{legend}</legend>
      <div
        role="radiogroup"
        aria-label={legend}
        className={
          // THREE COLUMNS ONLY WHERE THREE COLUMNS FIT. Unprefixed `grid-cols-3` gave each
          // option about 75px inside this panel on a 360px phone, and the options are
          // "Business hours" / "Into the evening" / "Around the clock" with a caption under
          // each — every one of them broke to three or four lines, at three different
          // heights. Stacked below `sm` they are three full-width rows, which is also the
          // shape the two-option group above already uses.
          "mt-3 grid gap-2 " +
          (columns === 3 ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-1 sm:grid-cols-2")
        }
      >
        {options.map((option) => {
          const selected = option.id === value;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(option.id)}
              className={
                "rounded-lg border px-2.5 py-2.5 text-left transition-colors touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong " +
                (selected
                  ? "border-brand-strong bg-brand-soft/60 text-ink dark:bg-brand-strong/15"
                  : "border-line bg-app text-ink-muted hover:border-brand/50")
              }
            >
              <span className="block text-sm font-semibold text-ink">{option.label}</span>
              <span className="mt-0.5 block text-xs text-ink-faint">{option.caption}</span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/** One line in the telecaller cost breakdown. */
function CostLine({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div
      className={
        "flex items-baseline justify-between gap-4 " +
        (strong ? "border-t border-line pt-3 text-ink" : "text-ink-muted")
      }
    >
      <span className={strong ? "text-sm font-semibold" : "text-sm"}>{label}</span>
      <span
        className={
          "tabular-nums " + (strong ? "text-base font-bold text-ink" : "text-sm font-medium text-ink")
        }
      >
        {value}
      </span>
    </div>
  );
}

/**
 * The two comparisons this tool can run, and why there are two rather than one.
 *
 * `answers` is the original showdown: Calevate takes the same calls a telecaller would.
 * It is the right comparison for a receptionist workload and it is the default, because
 * the default call length here is two minutes and a two-minute call is not a sale.
 *
 * `qualifies` is the comparison that is honest once the call gets long. A six-minute call
 * is a sales conversation; the alternative to a closer is not a cheaper closer, it is
 * having the closer talk only to people worth talking to. So the second mode compares a
 * team that calls the whole list against a team that calls the qualified share of it,
 * with Calevate holding the first, short call with everyone.
 *
 * Two modes rather than one merged screen because they answer different questions and a
 * merged one would have to average them into a number that is true of neither.
 */
const MODES: readonly { id: "answers" | "qualifies"; label: string; caption: string }[] = [
  { id: "answers", label: "Calevate answers the calls", caption: "It handles the call end to end" },
  { id: "qualifies", label: "Calevate calls first, your team closes", caption: "Triage, then a real conversation" },
];

type Mode = (typeof MODES)[number]["id"];

/** Whole hours, for the released-selling-time line. Minutes are already an integer. */
function hoursFromMinutes(minutes: number): number {
  return Math.round(minutes / 60);
}

const QUALITATIVE: { icon: typeof Clock3; title: string; body: string }[] = [
  {
    icon: Clock3,
    title: "Answers around the clock",
    body: "No shift to staff for evenings, weekends or festival days — the line is picked up whenever it rings.",
  },
  {
    icon: InfinityIcon,
    title: "Takes every call at once",
    body: "Fifty callers at 11am are fifty answered calls, not fifty in a queue behind three desks.",
  },
  {
    icon: TrendingDown,
    title: "No ramp, no attrition",
    body: "Nothing to hire, train for six weeks, or re-hire when someone leaves. It is ready the day you switch it on.",
  },
  {
    icon: ShieldCheck,
    title: "The rules on every dial",
    body: "Calling hours, do-not-call scrubbing and the AI-disclosure answer are enforced on every call, not left to a person to remember.",
  },
  {
    icon: Table2,
    title: "A filled-in row every time",
    body: "Each call lands as structured data in your leads list — the columns you chose — with the audio attached.",
  },
];

export function RoiCalculator() {
  const [mode, setMode] = useState<Mode>("answers");
  const [callsPerDay, setCallsPerDay] = useState(USAGE.callsPerDay.default);
  const [avgMinutes, setAvgMinutes] = useState(USAGE.avgMinutes.default);
  const [workingDays, setWorkingDays] = useState(USAGE.workingDays.default);
  // Default to business hours — one shift — so the everyday comparison never overstates the
  // human side. The advantage widens only when the buyer says they need the line answered
  // beyond a single shift, which is the honest place for "always on" to show up in rupees.
  const [coverageHours, setCoverageHours] = useState(COVERAGE[0].hours);

  const [callsPerAgentPerDay, setCallsPerAgent] = useState(
    TELECALLER.callsPerAgentPerDay.default,
  );
  const [talkHoursPerDay, setTalkHours] = useState(TELECALLER.talkHoursPerDay.default);
  const [basePerAgentInr, setBase] = useState(TELECALLER.basePerAgentInr.default);
  const [loadedPerAgentInr, setLoaded] = useState(TELECALLER.loadedPerAgentInr.default);
  const [attritionPct, setAttrition] = useState(TELECALLER.attritionPctPerYear.default);
  const [replacementInr, setReplacement] = useState(
    TELECALLER.replacementCostInr.default,
  );

  const [qualifiedPct, setQualifiedPct] = useState(TWO_STAGE.qualifiedPct.default);
  const [qualifyMinutes, setQualifyMinutes] = useState(TWO_STAGE.qualifyMinutes.default);

  const [leadOpen, setLeadOpen] = useState(false);
  const [convertedLeadInr, setLeadInr] = useState(LEAD_VALUE.convertedLeadInr.default);
  const [conversionPct, setConversion] = useState(LEAD_VALUE.conversionPct.default);

  const result = useMemo(
    () =>
      computeRoi({
        callsPerDay,
        avgMinutes,
        workingDays,
        coverageHours,
        callsPerAgentPerDay,
        talkHoursPerDay,
        basePerAgentInr,
        loadedPerAgentInr,
        attritionPctPerYear: attritionPct,
        replacementCostInr: replacementInr,
        leadValue: { enabled: leadOpen, convertedLeadInr, conversionPct },
      }),
    [
      callsPerDay,
      avgMinutes,
      workingDays,
      coverageHours,
      callsPerAgentPerDay,
      talkHoursPerDay,
      basePerAgentInr,
      loadedPerAgentInr,
      attritionPct,
      replacementInr,
      leadOpen,
      convertedLeadInr,
      conversionPct,
    ],
  );

  // The two-stage funnel, computed from the same inputs. Always computed, not gated on the
  // mode: it is one pure call over numbers already in state, and a `useMemo` that changed
  // shape with the mode would recompute on every toggle for no gain.
  const twoStage = useMemo(
    () =>
      computeTwoStage({
        callsPerDay,
        avgMinutes,
        workingDays,
        coverageHours,
        callsPerAgentPerDay,
        talkHoursPerDay,
        basePerAgentInr,
        loadedPerAgentInr,
        attritionPctPerYear: attritionPct,
        replacementCostInr: replacementInr,
        qualifiedPct,
        qualifyMinutes,
      }),
    [
      callsPerDay,
      avgMinutes,
      workingDays,
      coverageHours,
      callsPerAgentPerDay,
      talkHoursPerDay,
      basePerAgentInr,
      loadedPerAgentInr,
      attritionPct,
      replacementInr,
      qualifiedPct,
      qualifyMinutes,
    ],
  );

  const twoStageMode = mode === "qualifies";

  // The verdict is computed off whichever comparison is on screen, so the honest-close and
  // honest-loss branches below are the same three branches in both modes rather than two
  // sets of rules that could disagree about what "close" means.
  const baseline = twoStageMode ? twoStage.allHuman.humanTotalPaise : result.humanTotalPaise;
  const delta = twoStageMode ? twoStage.deltaPaise : result.deltaPaise;
  const cheaper = delta > 0;
  const close = baseline > 0 && Math.abs(delta) * 10 < baseline; // within ~10%

  const monthlyCalls = result.callsPerMonth.toLocaleString("en-IN");
  const coverage = COVERAGE.find((c) => c.hours === coverageHours) ?? COVERAGE[0];
  const singleShift = result.shifts <= 1;

  // The nudge that fixes the thing this whole mode exists for: at four minutes and up the
  // call is a conversation, not an enquiry being written down, and comparing it head-to-head
  // with a per-minute agent compares two things that were never alternatives. Shown only
  // while the buyer is in the head-to-head mode, so it points at the switch rather than
  // arguing with them.
  const longCall = !twoStageMode && avgMinutes >= 4 && result.humanTotalPaise > 0;

  return (
    // `data-roi-calculator`: the marker `publicLanding.test.tsx` uses to scope its
    // price/percent bans off this deliberately-priced section while keeping them in force
    // over the rest of the page.
    <div
      data-roi-calculator
      className="mt-10 grid gap-6 sm:mt-12 lg:grid-cols-[1fr_1.05fr] lg:items-start"
    >
      {/* --- Inputs -------------------------------------------------------------- */}
      <div className="rounded-2xl border border-line bg-surface p-5 sm:p-8">
        <h3 className="text-lg font-semibold text-ink">Your call volume</h3>
        <p className="mt-1.5 text-sm text-ink-muted">
          Two numbers and how long the phone must be covered. Everything else is pre-filled
          with local benchmarks you can adjust later if you want to.
        </p>
        <div className="mt-6 space-y-6">
          {/* Which comparison to run. First, because it changes what every number below
              means: in the second mode the call length is your salesperson's conversation,
              not the agent's. */}
          <RadioCards
            legend="What you want Calevate to do"
            options={MODES}
            value={mode}
            onChange={setMode}
            columns={2}
          />

          <Control
            label="Calls a day"
            bounds={USAGE.callsPerDay}
            value={callsPerDay}
            onChange={setCallsPerDay}
            unit="calls"
          />
          <Control
            label={twoStageMode ? "How long a real sales conversation runs" : "Average call length"}
            bounds={USAGE.avgMinutes}
            value={avgMinutes}
            onChange={setAvgMinutes}
            unit="min"
            hint={
              twoStageMode
                ? "The conversation your salesperson has with someone worth talking to — not the first call."
                : undefined
            }
          />

          {twoStageMode && (
            <>
              <Control
                label="Leads worth a real conversation"
                bounds={TWO_STAGE.qualifiedPct}
                value={qualifiedPct}
                onChange={setQualifiedPct}
                unit="%"
                hint="Out of everyone on the list, the share that turns out to be interested. Only these reach a person."
              />
              <Control
                label="Calevate's first call"
                bounds={TWO_STAGE.qualifyMinutes}
                value={qualifyMinutes}
                onChange={setQualifyMinutes}
                unit="min"
                hint="Long enough to find out what they want and whether they are interested — the call every lead gets."
              />
            </>
          )}

          {/* Coverage — the honest "always on" lever. A person works one shift; to keep a
              line answered longer you staff more shifts, and that is where an agent that
              answers every hour at the same price pulls ahead. Radios, not a slider: three
              named windows a buyer recognises, keyboard-operable as one group. */}
          <RadioCards
            legend="Hours you need the line answered"
            options={COVERAGE.map((c) => ({
              id: c.hours,
              label: c.label,
              caption: c.caption,
            }))}
            value={coverageHours}
            onChange={setCoverageHours}
            columns={3}
          />
        </div>

        <details className="group mt-8 border-t border-line pt-6">
          {/* The summary carries an <h3>, matching the FAQ and the "How we calculate"
              disclosure below — every disclosure on the page shares that shape, which the
              landing tests assert across all of them. */}
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-ink">
            <h3 className="text-sm font-semibold text-ink">
              Assumptions — working days, and what a telecaller really costs
            </h3>
            <span className="shrink-0 text-xs font-medium text-brand-strong group-open:hidden">
              Adjust
            </span>
            <span className="hidden shrink-0 text-xs font-medium text-ink-muted group-open:inline">
              Hide
            </span>
          </summary>
          <p className="mt-2 text-sm text-ink-muted">
            Pre-filled with illustrative benchmarks for the role in Andhra Pradesh and
            Telangana. You don&apos;t need to touch these — open them only to run the
            comparison on your own numbers.
          </p>
          <div className="mt-6 space-y-6">
            <Control
              label="Working days a month"
              bounds={USAGE.workingDays}
              value={workingDays}
              onChange={setWorkingDays}
              unit="days"
            />
          <Control
            label="Calls one telecaller handles a day"
            bounds={TELECALLER.callsPerAgentPerDay}
            value={callsPerAgentPerDay}
            onChange={setCallsPerAgent}
            unit="calls"
            hint="The dial ceiling — a productive agent starts roughly 80–120 dials on a 5.5–6.5 hour shift. On longer calls, talk-time (below) is the real limit."
          />
          <Control
            label="Productive talk hours a day"
            bounds={TELECALLER.talkHoursPerDay}
            value={talkHoursPerDay}
            onChange={setTalkHours}
            unit="hrs"
            hint="Actual talk time in a shift, after dialling, ringing, no-answers and wrap-up — usually 3–5 hours. This is why a longer call means fewer calls per agent, and more agents."
          />
          <Control
            label="Advertised base pay"
            bounds={TELECALLER.basePerAgentInr}
            value={basePerAgentInr}
            onChange={setBase}
            unit="/mo"
            hint="The figure a job ad shows — around ₹18k–₹25k for the role."
          />
          <Control
            label="Fully loaded cost"
            bounds={TELECALLER.loadedPerAgentInr}
            value={loadedPerAgentInr}
            onChange={setLoaded}
            unit="/mo"
            hint="Base plus PF/ESI, incentives, a share of a supervisor, desk and power, and ramp-up."
          />
          <Control
            label="Yearly attrition"
            bounds={TELECALLER.attritionPctPerYear}
            value={attritionPct}
            onChange={setAttrition}
            unit="%"
            hint="Widely reported at 35–45% a year in this role."
          />
          <Control
            label="Cost to replace one leaver"
            bounds={TELECALLER.replacementCostInr}
            value={replacementInr}
            onChange={setReplacement}
            unit="one-off"
            hint="Hiring, training and lost output — commonly ₹1–2 lakh, folded in monthly."
          />
          </div>
        </details>
      </div>

      {/* --- Results ------------------------------------------------------------- */}
      <div className="space-y-6">
        {twoStageMode ? (
          <>
            {/* Option A — the whole list, by people, at the full conversation length. */}
            <div className="rounded-2xl border border-line bg-surface p-5 sm:p-8">
              <p className="text-sm text-ink-muted">
                If your people work the whole list — all{" "}
                <span className="font-semibold text-ink tabular-nums">{monthlyCalls}</span>{" "}
                conversations a month — you&apos;d hire
              </p>
              <p className="mt-1 flex items-center gap-2.5 text-3xl font-bold tracking-tight text-ink">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <UserRound aria-hidden className="h-5 w-5" />
                </span>
                <span className="tabular-nums">{twoStage.allHuman.headcount}</span>
                <span className="text-lg font-semibold text-ink-muted">
                  {twoStage.allHuman.headcount === 1 ? "salesperson" : "salespeople"}
                </span>
              </p>
              <p className="mt-1.5 text-sm text-ink-muted">
                At {avgMinutes}-min conversations one person manages about{" "}
                <span className="font-semibold text-ink tabular-nums">
                  {twoStage.allHuman.effectiveCallsPerAgentPerDay}
                </span>{" "}
                a day — every one a full conversation, whether or not the person turns out
                to be interested.
              </p>
              {!singleShift && (
                <p className="mt-1.5 text-sm text-ink-muted">
                  Answering {coverage.label.toLowerCase()} means staffing{" "}
                  <span className="font-semibold text-ink tabular-nums">
                    {twoStage.allHuman.shifts}
                  </span>{" "}
                  shifts, on both sides of this comparison — every shift needs somebody on
                  the phone. Calevate&apos;s first call costs the same at every hour.
                </p>
              )}
              <div className="mt-6 space-y-3">
                <CostLine label="Base pay" value={formatPaiseINR(twoStage.allHuman.humanBasePaise)} />
                <CostLine
                  label="Incentives, PF/ESI, supervisor, desk & overhead"
                  value={formatPaiseINR(twoStage.allHuman.humanUpliftPaise)}
                />
                <CostLine
                  label="Amortised attrition"
                  value={formatPaiseINR(twoStage.allHuman.humanAttritionPaise)}
                />
                <CostLine
                  label="Your team on the whole list, a month"
                  value={formatPaiseINR(twoStage.allHuman.humanTotalPaise)}
                  strong
                />
              </div>
            </div>

            {/* Option B — triage by Calevate, closing by people. */}
            <div className="rounded-2xl border border-brand/40 bg-brand-soft/40 p-5 sm:p-8 dark:bg-brand-strong/10">
              <p className="flex items-center gap-2.5 text-sm font-medium text-brand-strong dark:text-brand-bright">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-strong text-white">
                  <Filter aria-hidden className="h-5 w-5" />
                </span>
                Calevate calls first, your team closes
              </p>
              <p className="mt-3 text-3xl font-bold tracking-tight tabular-nums text-ink">
                {formatPaiseINR(twoStage.blendedTotalPaise)}
              </p>
              <p className="mt-1.5 text-sm text-ink-muted">
                Calevate holds a {qualifyMinutes}-min first call with every one of the{" "}
                <span className="font-semibold text-ink tabular-nums">{monthlyCalls}</span>, sorts
                them, and writes each one down. Your{" "}
                <span className="font-semibold text-ink tabular-nums">
                  {twoStage.humans.headcount}
                </span>{" "}
                {twoStage.humans.headcount === 1 ? "salesperson" : "salespeople"} then hold
                the{" "}
                <span className="font-semibold text-ink tabular-nums">
                  {twoStage.qualifiedCallsPerMonth.toLocaleString("en-IN")}
                </span>{" "}
                conversations that are worth having.
              </p>
              <div className="mt-6 space-y-3">
                <CostLine
                  label="Calevate, first call to everyone"
                  value={formatPaiseINR(twoStage.qualificationPaise)}
                />
                <CostLine
                  label="Your team, on the qualified list only"
                  value={formatPaiseINR(twoStage.humans.humanTotalPaise)}
                />
                <CostLine
                  label="Together, a month"
                  value={formatPaiseINR(twoStage.blendedTotalPaise)}
                  strong
                />
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-2xl border border-line bg-surface p-5 sm:p-8">
              <p className="text-sm text-ink-muted">
                To take{" "}
                <span className="font-semibold text-ink tabular-nums">{monthlyCalls}</span>{" "}
                calls a month you&apos;d hire
              </p>
              <p className="mt-1 flex items-center gap-2.5 text-3xl font-bold tracking-tight text-ink">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <UserRound aria-hidden className="h-5 w-5" />
                </span>
                <span className="tabular-nums">{result.headcount}</span>
                <span className="text-lg font-semibold text-ink-muted">
                  telecaller{result.headcount === 1 ? "" : "s"}
                </span>
              </p>
              <p className="mt-1.5 text-sm text-ink-muted">
                At {avgMinutes}-min calls, one agent handles about{" "}
                <span className="font-semibold text-ink tabular-nums">
                  {result.effectiveCallsPerAgentPerDay}
                </span>{" "}
                a day — talk-time, not dialling, is the limit once calls run long.
              </p>
              {!singleShift && (
                <p className="mt-1.5 text-sm text-ink-muted">
                  To answer {coverage.label.toLowerCase()} you staff{" "}
                  <span className="font-semibold text-ink tabular-nums">{result.shifts}</span>{" "}
                  shifts — every shift needs someone on the phone even when it is quiet. Calevate
                  answers all {coverageHours === 24 ? "24 hours" : `${coverageHours} hours`} at
                  the very same per-minute price.
                </p>
              )}

              <div className="mt-6 space-y-3">
                <CostLine
                  label="Base pay"
                  value={formatPaiseINR(result.humanBasePaise)}
                />
                <CostLine
                  label="Incentives, PF/ESI, supervisor, desk & overhead"
                  value={formatPaiseINR(result.humanUpliftPaise)}
                />
                <CostLine
                  label="Amortised attrition"
                  value={formatPaiseINR(result.humanAttritionPaise)}
                />
                <CostLine
                  label="Telecallers, a month"
                  value={formatPaiseINR(result.humanTotalPaise)}
                  strong
                />
              </div>
            </div>

            <div className="rounded-2xl border border-brand/40 bg-brand-soft/40 p-5 sm:p-8 dark:bg-brand-strong/10">
              <p className="flex items-center gap-2.5 text-sm font-medium text-brand-strong dark:text-brand-bright">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-strong text-white">
                  <Bot aria-hidden className="h-5 w-5" />
                </span>
                Calevate, a month
              </p>
              <p className="mt-3 text-3xl font-bold tracking-tight tabular-nums text-ink">
                {formatPaiseINR(result.calevatePaise)}
              </p>
              <p className="mt-1.5 text-sm text-ink-muted">
                Variable and pay-as-you-go at ₹5.00/min — it rises with your calls and falls to
                zero on a quiet day. No headcount to carry between the busy months.
              </p>
            </div>
          </>
        )}

        {/* The honest verdict line: a real gap is stated, a close one is admitted. Both
            modes run the same three branches over `delta` and `baseline`, so neither can
            grow a friendlier rule than the other. */}
        <div
          className={
            "rounded-2xl border p-6 " +
            (cheaper && !close
              ? "border-brand/40 bg-surface"
              : "border-line bg-surface/60")
          }
        >
          {baseline === 0 ? (
            <p className="text-sm text-ink-muted">
              Set a call volume above to compare the two.
            </p>
          ) : cheaper && !close ? (
            <p className="flex flex-wrap items-baseline gap-x-2 text-base text-ink">
              <TrendingDown aria-hidden className="h-5 w-5 text-brand-strong dark:text-brand-bright" />
              <span className="font-semibold">
                About {formatPaiseINR(delta)} less a month
              </span>
              <span className="text-ink-muted">
                {twoStageMode
                  ? "— and your people spend that month closing rather than finding out who is interested."
                  : "with Calevate — and that is only the part a spreadsheet can see."}
              </span>
            </p>
          ) : cheaper ? (
            <p className="text-sm text-ink-muted">
              At this volume the running costs come out close (about{" "}
              <span className="font-semibold text-ink">{formatPaiseINR(delta)}</span>{" "}
              a month apart).{" "}
              {twoStageMode
                ? "The difference that matters is below — the same team, spending its hours on people who are actually interested."
                : "The difference that matters is the row below — the things a headcount cannot do at any price."}
            </p>
          ) : twoStageMode ? (
            <p className="text-sm text-ink-muted">
              On these assumptions the two-stage funnel costs{" "}
              <span className="font-semibold text-ink">{formatPaiseINR(-delta)}</span> more a
              month, not less — at this share of qualified leads there is little for a first
              call to filter out, so it is mostly an extra call on top. Said plainly rather
              than hidden: if that is really your list, your team should keep calling it.
            </p>
          ) : (
            <p className="text-sm text-ink-muted">
              At this volume a small team can match the running cost. What it cannot match is
              the row below — so the comparison is honestly about capability here, not price.
            </p>
          )}

          {/* The capacity line, which is the actual argument. Rupees are the smaller half:
              what moves is where your salespeople's hours go. Pure arithmetic off the
              buyer's own inputs — no borrowed conversion statistic, because none of the
              ones in circulation could be verified to a primary source. */}
          {twoStageMode && baseline > 0 && twoStage.triagedAwayPerMonth > 0 && (
            <p className="mt-3 flex flex-wrap items-baseline gap-x-2 border-t border-line pt-3 text-sm text-ink-muted">
              <Handshake aria-hidden className="h-5 w-5 text-brand-strong dark:text-brand-bright" />
              <span>
                <span className="font-semibold text-ink tabular-nums">
                  {twoStage.triagedAwayPerMonth.toLocaleString("en-IN")}
                </span>{" "}
                of those calls never reach a person — about{" "}
                <span className="font-semibold text-ink tabular-nums">
                  {hoursFromMinutes(twoStage.humanMinutesReleased).toLocaleString("en-IN")}
                </span>{" "}
                hours a month your team is not spending on someone who was never going to
                buy. Each of them still lands as a filled-in row you can read.
              </span>
            </p>
          )}

          {/* The nudge out of a comparison that stopped being like-for-like. See `longCall`. */}
          {longCall && (
            <p className="mt-3 border-t border-line pt-3 text-sm text-ink-muted">
              A {avgMinutes}-minute call is a{" "}
              <span className="font-medium text-ink">sales conversation</span>, not an enquiry
              being written down — and the answer to an expensive conversation is not a
              cheaper one, it is having fewer of them with the wrong people. Switch the
              choice above to{" "}
              <span className="font-medium text-ink">Calevate calls first, your team closes</span>{" "}
              to compare that instead.
            </p>
          )}

          {/* The coverage reveal: when the buyer is comparing a single business-hours shift
              and the running costs are close, the honest lever is the hours themselves —
              a human team is priced per shift, Calevate is not. This nudges without faking
              a gap; extend the hours above and the numbers move on their own. */}
          {!twoStageMode && result.humanTotalPaise > 0 && singleShift && !(cheaper && !close) && (
            <p className="mt-3 border-t border-line pt-3 text-sm text-ink-muted">
              This is a{" "}
              <span className="font-medium text-ink">business-hours</span> comparison — one
              human shift. If your line should be answered into the evening or overnight,
              set the hours above: a human team is paid per shift, so the cost climbs, while
              Calevate answers around the clock at the same rate.
            </p>
          )}

          {leadOpen && result.pipelineValuePaise !== null && (
            <p className="mt-3 border-t border-line pt-3 text-xs text-ink-faint">
              For context, at your conversion assumptions these calls carry about{" "}
              <span className="font-semibold text-ink">
                {formatPaiseINR(result.pipelineValuePaise)}
              </span>{" "}
              of converted-lead value a month. A line that is always answered and never
              queued is how more of that value is actually reached — it is not credited to
              either option above.
            </p>
          )}
        </div>
      </div>

      {/* --- Advanced: missed-lead value ---------------------------------------- */}
      <div className="lg:col-span-2">
        <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm font-medium text-ink">
          <input
            type="checkbox"
            checked={leadOpen}
            onChange={(e) => setLeadOpen(e.target.checked)}
            className="h-4 w-4 rounded border-line text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong"
          />
          Also weigh the value of the leads at stake (optional)
        </label>
        {leadOpen && (
          <div className="mt-4 grid gap-6 rounded-2xl border border-line bg-surface p-5 sm:grid-cols-2 sm:p-8">
            <Control
              label="Value of a converted lead"
              bounds={LEAD_VALUE.convertedLeadInr}
              value={convertedLeadInr}
              onChange={setLeadInr}
              unit="₹"
              hint="What one won customer is worth to you, on average."
            />
            <Control
              label="Conversion rate"
              bounds={LEAD_VALUE.conversionPct}
              value={conversionPct}
              onChange={setConversion}
              unit="%"
              hint="Share of answered calls that become a customer."
            />
          </div>
        )}
      </div>

      {/* --- Qualitative wins ---------------------------------------------------- */}
      <div className="lg:col-span-2">
        <h3 className="text-lg font-semibold text-ink">
          What no headcount maths captures
        </h3>
        <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {QUALITATIVE.map(({ icon: Icon, title, body }) => (
            <li
              key={title}
              className="rounded-2xl border border-line bg-surface p-5"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <h4 className="mt-4 text-[15px] font-semibold text-ink">{title}</h4>
              <p className="mt-1.5 text-sm text-ink-muted">{body}</p>
            </li>
          ))}
        </ul>
      </div>

      {/* --- Assumptions disclosure --------------------------------------------- */}
      <div className="lg:col-span-2">
        {/* Native <details>, matching the FAQ: keyboard-operable and announced with no
            script at all, and closed by default so it never renders as a wall of text.
            The summary carries an <h3> and the body a <p>, the shape the landing tests
            require of every disclosure on the page. */}
        <details className="group rounded-2xl border border-line bg-surface/60 p-6">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
            <h3 className="text-[15px] font-semibold text-ink">
              How we calculate this, and where the numbers come from
            </h3>
            <span
              aria-hidden
              className="text-xs font-medium text-ink-faint transition-transform group-open:rotate-180"
            >
              ▾
            </span>
          </summary>
          <div className="mt-4 space-y-3 text-sm text-ink-muted">
            <p>
              These figures are <span className="font-semibold text-ink">illustrative and
              fully adjustable</span> — the defaults are relayed industry benchmarks for the
              telecalling role, not measurements we have taken or promises we make. Move any
              slider to your own numbers and everything recalculates.
            </p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <span className="font-medium text-ink">Calevate</span> = calls a day ×
                average length × ₹5.00/min × working days. ₹5.00/min is our published
                self-serve rate.
              </li>
              <li>
                <span className="font-medium text-ink">Telecallers needed</span> = calls a
                day ÷ calls one agent handles a day, rounded up. The ~100/day default assumes
                80–120 dials on a 5.5–6.5 hour productive shift.
              </li>
              <li>
                <span className="font-medium text-ink">Hours covered</span>: a person works
                one ~9-hour shift, so answering into the evening (≈15h) or around the clock
                (24h) means staffing two or three shifts — and every staffed shift needs at
                least one person on the phone, even a quiet night one. We spread your call
                volume evenly across the shifts you choose, which is the assumption kindest
                to the human side. Calevate answers at every hour for the same per-minute
                rate, so widening the hours never changes its figure.
              </li>
              <li>
                <span className="font-medium text-ink">Calevate calls first, your team
                closes</span>: the other comparison. One side is your people working the
                whole list, every lead at the full conversation length. The other is Calevate
                holding a short first call with everyone, and your people holding the full
                conversation only with the share that came back interested — so headcount
                follows the qualified list, not the raw one. The two figures you set for it —
                how much of your list is worth a real conversation, and how long the first
                call runs — are assumptions about YOUR list, not benchmarks. Nobody can tell
                you those from outside, which is exactly why they are sliders. Set the
                qualified share to everyone and the arithmetic turns against us; the verdict
                says so.
              </li>
              <li>
                <span className="font-medium text-ink">Loaded vs. base</span>: the advertised
                base (~₹21,240) is what an ad shows; the loaded figure (~₹32,000 default) adds
                PF/ESI, on-target incentives (often 30–80% of base), a share of a supervisor,
                desk/power/phone/software, and ramp-up. The whole point is that the base hides
                the real cost.
              </li>
              <li>
                <span className="font-medium text-ink">Attrition</span> (35–45%/year, ₹1–2
                lakh to replace each leaver) is folded in as an amortised monthly line:
                replacement cost × attrition ÷ 12.
              </li>
            </ul>
            <p>
              All amounts are computed in whole paise and rounded once, so the rupee figures
              add up exactly. This is a planning estimate, not a quote — your actual Calevate
              cost is simply your minutes used at the rate above.
            </p>
          </div>
        </details>
      </div>
    </div>
  );
}

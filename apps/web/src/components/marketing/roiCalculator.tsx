"use client";

/**
 * The homepage ROI calculator: "AI vs. hiring telecallers", driven by the buyer.
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
 * All money is integer paise (`lib/roi.ts`), formatted from digits, never floated.
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
  Infinity as InfinityIcon,
  ShieldCheck,
  Table2,
  TrendingDown,
  UserRound,
} from "lucide-react";

import {
  computeRoi,
  formatPaiseINR,
  LEAD_VALUE,
  TELECALLER,
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
        className="mt-3 w-full cursor-pointer appearance-none bg-transparent [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-brand-strong [&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-line [&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-line [&::-webkit-slider-thumb]:-mt-[5px] [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-strong focus-visible:outline-none dark:[&::-moz-range-thumb]:bg-brand-bright dark:[&::-webkit-slider-thumb]:bg-brand-bright"
      />
      {hint && <p className="mt-1.5 text-xs text-ink-faint">{hint}</p>}
    </div>
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
  const [callsPerDay, setCallsPerDay] = useState(USAGE.callsPerDay.default);
  const [avgMinutes, setAvgMinutes] = useState(USAGE.avgMinutes.default);
  const [workingDays, setWorkingDays] = useState(USAGE.workingDays.default);

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

  const [leadOpen, setLeadOpen] = useState(false);
  const [convertedLeadInr, setLeadInr] = useState(LEAD_VALUE.convertedLeadInr.default);
  const [conversionPct, setConversion] = useState(LEAD_VALUE.conversionPct.default);

  const result = useMemo(
    () =>
      computeRoi({
        callsPerDay,
        avgMinutes,
        workingDays,
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

  const cheaper = result.deltaPaise > 0;
  const close =
    result.humanTotalPaise > 0 &&
    Math.abs(result.deltaPaise) * 10 < result.humanTotalPaise; // within ~10%

  const monthlyCalls = result.callsPerMonth.toLocaleString("en-IN");

  return (
    // `data-roi-calculator`: the marker `publicLanding.test.tsx` uses to scope its
    // price/percent bans off this deliberately-priced section while keeping them in force
    // over the rest of the page.
    <div
      data-roi-calculator
      className="mt-12 grid gap-6 lg:grid-cols-[1fr_1.05fr] lg:items-start"
    >
      {/* --- Inputs -------------------------------------------------------------- */}
      <div className="rounded-2xl border border-line bg-surface p-6 sm:p-8">
        <h3 className="text-lg font-semibold text-ink">Your call volume</h3>
        <p className="mt-1.5 text-sm text-ink-muted">
          Two numbers is all it takes. Everything else is pre-filled with local benchmarks
          you can adjust later if you want to.
        </p>
        <div className="mt-6 space-y-6">
          <Control
            label="Calls a day"
            bounds={USAGE.callsPerDay}
            value={callsPerDay}
            onChange={setCallsPerDay}
            unit="calls"
          />
          <Control
            label="Average call length"
            bounds={USAGE.avgMinutes}
            value={avgMinutes}
            onChange={setAvgMinutes}
            unit="min"
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
        <div className="rounded-2xl border border-line bg-surface p-6 sm:p-8">
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

        <div className="rounded-2xl border border-brand/40 bg-brand-soft/40 p-6 sm:p-8 dark:bg-brand-strong/10">
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

        {/* The honest verdict line: a real gap is stated, a close one is admitted. */}
        <div
          className={
            "rounded-2xl border p-6 " +
            (cheaper && !close
              ? "border-brand/40 bg-surface"
              : "border-line bg-surface/60")
          }
        >
          {result.humanTotalPaise === 0 ? (
            <p className="text-sm text-ink-muted">
              Set a call volume above to compare the two.
            </p>
          ) : cheaper && !close ? (
            <p className="flex flex-wrap items-baseline gap-x-2 text-base text-ink">
              <TrendingDown aria-hidden className="h-5 w-5 text-brand-strong dark:text-brand-bright" />
              <span className="font-semibold">
                About {formatPaiseINR(result.deltaPaise)} less a month
              </span>
              <span className="text-ink-muted">with Calevate — and that is only the part a spreadsheet can see.</span>
            </p>
          ) : cheaper ? (
            <p className="text-sm text-ink-muted">
              At this volume the running costs come out close (about{" "}
              <span className="font-semibold text-ink">{formatPaiseINR(result.deltaPaise)}</span>{" "}
              a month apart). The difference that matters is the row below — the things a
              headcount cannot do at any price.
            </p>
          ) : (
            <p className="text-sm text-ink-muted">
              At this volume a small team can match the running cost. What it cannot match is
              the row below — so the comparison is honestly about capability here, not price.
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
          <div className="mt-4 grid gap-6 rounded-2xl border border-line bg-surface p-6 sm:grid-cols-2 sm:p-8">
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

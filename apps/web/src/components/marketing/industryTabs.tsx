"use client";

/**
 * The industries band: four trades, and for each one what the OWNER receives.
 *
 * ## Why tabs, and why these four have equal weight
 *
 * The band used to be a four-card grid of field lists. A field list answers "will it ask
 * the right questions", which is the second question; the first is "what do I actually
 * get out of it", and that needed room a four-up grid does not have. Tabs buy that room
 * without a longer page — one panel visible, three a keypress away.
 *
 * All four are written to the same depth on purpose (the founder's decision, 5 Sep 2026):
 * clinics is first in reading order because it is first in `scripts/seed.py`, and it gets
 * no richer example, no default styling and no editorial promotion over the other three.
 *
 * ## The field lists are still the seed's own labels
 *
 * `fields` is copied label-for-label and in order from `VERTICAL_TEMPLATES` in
 * `scripts/seed.py`, and `publicLanding.test.tsx` reads them back out of the rendered DOM
 * and diffs them against that file. The value of this grid to a buyer is that it is the
 * actual first screen of their agent; a prettier label here is a small lie that only
 * shows up on the day they log in.
 *
 * `suite` marks the two verticals the golden-transcript fixtures cover today
 * (`tests/fixtures/golden_transcripts.json` carries `cl_*` and `re_*` only). Stated
 * rather than implied, on every tab, in both directions.
 *
 * ## The ARIA contract
 *
 * WAI-ARIA APG "Tabs" pattern, read 5 Sep 2026 (w3.org/WAI/ARIA/apg/patterns/tabs/ is
 * egress-blocked from this container; the pattern's requirements were confirmed from the
 * APG's own published summary via search that day):
 *
 *  - a `tablist` containing `tab`s, each `aria-selected` and `aria-controls` its panel;
 *  - each `tabpanel` `aria-labelledby` its tab, and focusable (`tabIndex={0}`) so a
 *    keyboard reader can scroll a panel that has no focusable content of its own;
 *  - ROVING TABINDEX: exactly one tab is in the Tab sequence, the rest are `-1`, so Tab
 *    enters and leaves the widget rather than walking four stops through it;
 *  - Left/Right move with wrap, Home/End jump to the ends;
 *  - AUTOMATIC activation — focus selects. The APG's condition for automatic activation is
 *    that every panel's content is already in the DOM and displays instantly, which is
 *    true here (all four are rendered; the hidden ones carry the `hidden` attribute).
 *
 * `hidden`, not `display:none` from a class: the attribute is what removes a panel from
 * the accessibility tree, and it is the one Testing Library and axe both read.
 */

import { useRef, useState, type KeyboardEvent } from "react";
import { Building2, GraduationCap, Stethoscope, Umbrella } from "lucide-react";

export interface Industry {
  readonly id: string;
  readonly icon: typeof Stethoscope;
  readonly name: string;
  /** The `VERTICAL_TEMPLATES` labels, verbatim and in the seed's order. */
  readonly fields: readonly string[];
  /** Whether a golden-transcript suite exists for this vertical today. */
  readonly suite: boolean;
  /** What the caller wanted, in the owner's words. */
  readonly asks: string;
  /** The row the owner opens — the structured result, as chips. */
  readonly result: readonly string[];
  /** Why that matters to the business, in one sentence. */
  readonly advantage: string;
}

export const INDUSTRIES: readonly Industry[] = [
  {
    id: "clinics",
    icon: Stethoscope,
    name: "Clinics",
    fields: ["Symptom / reason", "Preferred doctor", "Urgency", "Preferred slot", "Insurance"],
    suite: true,
    asks: "What is troubling you, how soon do you need to be seen, and who would you like to see?",
    result: ["Root canal", "Dr Rao", "This week", "Tuesday 6pm", "Cash"],
    advantage:
      "Your front desk opens the day on people who already said what they need and when they can come in.",
  },
  {
    id: "property",
    icon: Building2,
    name: "Property offices",
    fields: ["Budget (lakhs)", "Location", "BHK", "Timeline", "Site visit"],
    suite: true,
    asks: "What budget are you working with, which area, how many bedrooms, and when do you want to move?",
    result: ["80 lakh budget", "Gachibowli", "3BHK", "This month", "Site visit: Sat"],
    advantage:
      "Your salesperson rings a qualified buyer, not an unexplained phone number.",
  },
  {
    id: "insurance",
    icon: Umbrella,
    name: "Insurance",
    fields: ["Policy type", "Sum assured", "Renewal due", "Existing insurer"],
    suite: false,
    asks: "Which cover are you looking at, for how much, and when is your current policy due?",
    result: ["Health cover", "10 lakh sum assured", "Renewal in 3 weeks", "Existing: other insurer"],
    advantage:
      "You know which renewals are close before somebody else calls them first.",
  },
  {
    id: "coaching",
    icon: GraduationCap,
    name: "Coaching and colleges",
    fields: ["Course", "Class / year", "Fee concern", "Demo booked"],
    suite: false,
    asks: "Which course, which year is the student in, and would you like to sit in on a class?",
    result: ["NEET repeater", "Class 12", "Asked about fees", "Demo: Friday"],
    advantage:
      "Your counsellor spends admission season on parents who have already asked for a demo.",
  },
];

export function IndustryTabs() {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  /** Move selection AND focus together — automatic activation, per the APG. */
  const select = (index: number) => {
    const next = (index + INDUSTRIES.length) % INDUSTRIES.length;
    setActive(next);
    tabs.current[next]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case "ArrowRight":
        select(index + 1);
        break;
      case "ArrowLeft":
        select(index - 1);
        break;
      case "Home":
        select(0);
        break;
      case "End":
        select(INDUSTRIES.length - 1);
        break;
      default:
        return;
    }
    // Only for the keys handled above: Home/End otherwise scroll the page, and the
    // arrows otherwise move the caret in a way that fights the roving focus.
    event.preventDefault();
  };

  return (
    <div className="mt-10 sm:mt-12">
      <div
        role="tablist"
        aria-label="Industries"
        // WRAPS RATHER THAN SCROLLS SIDEWAYS, and the reason is a keyboard one rather
        // than a visual one. A horizontally scrolling strip is unreachable to somebody
        // driving the page from a keyboard unless it is a focusable region
        // (`tests/responsive.test.ts`, which caught this) — and wrapping the tablist in a
        // `ScrollRegion` would put a redundant tab stop in front of a widget whose own
        // children are already the tab stops. Two short rows on a 360px screen is the
        // better answer to the same problem.
        className="flex flex-wrap gap-2"
      >
        {INDUSTRIES.map((industry, index) => {
          const selected = index === active;
          return (
            <button
              key={industry.id}
              ref={(node) => {
                tabs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`industry-tab-${industry.id}`}
              aria-selected={selected}
              aria-controls={`industry-panel-${industry.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(index)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={
                "flex shrink-0 items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-semibold whitespace-nowrap transition-colors touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app " +
                (selected
                  ? "border-brand-strong bg-brand-strong text-white"
                  : "border-line bg-surface text-ink-muted hover:border-brand/50 hover:text-ink")
              }
            >
              <industry.icon aria-hidden className="h-4 w-4" />
              {industry.name}
            </button>
          );
        })}
      </div>

      {INDUSTRIES.map((industry, index) => (
        <div
          key={industry.id}
          role="tabpanel"
          id={`industry-panel-${industry.id}`}
          aria-labelledby={`industry-tab-${industry.id}`}
          tabIndex={0}
          hidden={index !== active}
          className="mt-5 rounded-2xl border border-line bg-surface p-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong sm:p-8"
        >
          <div className="grid gap-8 lg:grid-cols-2">
            <div>
              <h3 className="text-lg font-semibold text-ink">{industry.name}</h3>
              <p className="mt-3 text-xs font-semibold tracking-[0.14em] text-ink-faint uppercase">
                What it asks the caller
              </p>
              <p className="mt-2 text-base text-pretty text-ink-muted">“{industry.asks}”</p>
              <p className="mt-6 text-xs font-semibold tracking-[0.14em] text-ink-faint uppercase">
                The questions a new agent starts with
              </p>
              <ul data-seed-fields className="mt-2 flex flex-wrap gap-2">
                {industry.fields.map((field) => (
                  <li
                    key={field}
                    className="rounded-full border border-line bg-app/60 px-3 py-1 text-xs font-medium text-ink-muted"
                  >
                    {field}
                  </li>
                ))}
              </ul>
              <p className="mt-4 flex items-start gap-2 text-xs text-ink-faint">
                <span
                  aria-hidden
                  className={
                    "mt-1 h-1.5 w-1.5 shrink-0 rounded-full " +
                    (industry.suite ? "bg-brand-bright" : "bg-ink-faint")
                  }
                />
                {industry.suite
                  ? "Built against first, with its own suite of test calls behind it."
                  : "The field list ships; the test calls for it are still being written."}
              </p>
            </div>

            <div className="rounded-xl border border-line bg-app/50 p-5">
              <p className="text-xs font-semibold tracking-[0.14em] text-ink-faint uppercase">
                What you receive
              </p>
              <ul className="mt-3 flex flex-wrap gap-2">
                {industry.result.map((chip) => (
                  <li
                    key={chip}
                    className="rounded-lg bg-brand-soft px-3 py-1.5 text-sm font-semibold text-brand-strong"
                  >
                    {chip}
                  </li>
                ))}
              </ul>
              <p className="mt-5 border-t border-line pt-4 text-base text-pretty text-ink">
                {industry.advantage}
              </p>
              <p className="mt-3 text-xs text-ink-faint">
                An illustration of one lead, not a customer of ours.
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

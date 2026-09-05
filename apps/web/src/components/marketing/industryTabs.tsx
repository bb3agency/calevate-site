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
 * ## The content lives in `lib/marketing/industries.ts`
 *
 * One copy, shared with `/industries`, which renders the same four at full length. That
 * module's header carries the rules the data is held to — `fields` is `scripts/seed.py`'s
 * own labels in the seed's own order, `suite` is stated on every vertical in both
 * directions, and the example lead is captioned as an illustration wherever it renders.
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

import { INDUSTRIES } from "@/lib/marketing/industries";

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

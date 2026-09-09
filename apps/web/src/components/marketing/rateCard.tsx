import { ScrollRegion } from "@/components/ui";
import {
  formatAmountINR,
  formatRateINR,
  packMinutes,
  packRate,
  tierLabel,
  VOICE_TIERS,
  type PublicRateCard,
  type RateCardPack,
  type VoiceTier,
} from "@/lib/api/rateCard";

/**
 * The self-serve rate card: six prepaid packs, one voice's rates at a time.
 *
 * ## The founder's brief, and what the shape had to fix
 *
 * "Look how nice the competitor's cards are — the problem is they have less text to read
 * and still convey all they should convey, and we convey all we should through more text."
 * The card he was comparing against runs three side-by-side panels; ours ran **six rows,
 * each carrying a ₹/min AND a talk time on EACH of two voices** — twelve dense cells,
 * every one of them repeating the words "min of talk time". Measured at 1440x900, the
 * table used the left half of the shell and left the right half empty.
 *
 * Two decisions, both his (9 Sep 2026), and the second is what makes the first fit:
 *
 * 1. **TRANSPOSE IT.** Packs become COLUMNS and the two facts about a pack become ROWS.
 *    That is also what the form is for: side-by-side panels stop working past three or
 *    four options and a comparison TABLE is the established answer beyond that, which is
 *    the case we are in with six rungs. Every rung stays visible — a feature-heavy buyer
 *    justifying a spend internally needs the whole ladder, not three of it.
 * 2. **ONE VOICE AT A TIME**, chosen by the switch above the table. That halves what is on
 *    screen and loses nothing: the other voice is one keypress away and its figures are
 *    still in the document.
 *
 * ## Why the switch is CSS and not a client component
 *
 * It is two `<input type="radio">` and two `<label>`, styled through Tailwind's `peer`
 * variant — the sibling combinator. No `"use client"`, no hydration, no JavaScript at all:
 *
 * - **It degrades to nothing, because there is nothing to degrade.** A radio group works
 *   in a browser with scripting off, with a failed bundle, and in a crawler. The
 *   alternative — `useState` — would have made this page's one control the only thing on
 *   the site that needs a bundle to work, on a page whose entire job is to answer one
 *   question.
 * - **The keyboard and the screen reader come free and correct.** Tab reaches the group,
 *   the arrow keys move within it (which is the native behaviour for a set of radios and
 *   the behaviour the WAI tab pattern imitates), and the state is announced by the
 *   platform — "Studio voice, radio button, 2 of 2, selected" — rather than by an
 *   `aria-live` region we would have had to write and get right.
 * - **`components/interior/Tabs` is the console's tab primitive and is `"use client"`.**
 *   Mounting it here would drag a hook into an async server component that has no
 *   `QueryClientProvider` and no need of one. UX-DOCTRINE §3 asks for a decision-log entry
 *   before a tab-shaped device; this is D-559.
 *
 * ## And `IndustryTabs` is NOT the thing this should have reused
 *
 * The marketing tree already holds a panel switcher — `components/marketing/
 * industryTabs.tsx`, a hand-rolled WAI tablist with roving tabindex, Home/End and wrap.
 * Two ways of doing one thing is a defect even when both work (CLAUDE.md), so the
 * difference is stated here rather than left to be discovered:
 *
 * - **They are different widgets in ARIA's own taxonomy.** A `tablist` navigates between
 *   SECTIONS OF CONTENT — four trades, each a page's worth of prose. A `radiogroup`
 *   chooses a VALUE, and this control chooses one: which voice the figures below describe.
 *   A reader is not moving between two documents, they are asking one table a question.
 * - **The page they are on is the harder constraint.** The homepage already ships a client
 *   bundle (the hero simulation, the FAQ, the motion layer), so a stateful tablist costs
 *   it nothing. `/pricing` ships NO client component at all, and the thing being switched
 *   is the price — the one claim a buyer relies on before they have met anybody. Making it
 *   depend on a bundle to be readable is not a trade this page can make.
 *
 * If a THIRD panel switcher is ever wanted on a marketing page, the answer is to hoist one
 * of these two and move its caller in the same change — not to write a third.
 *
 * The one thing a CSS switch cannot do is announce the table's change to a reader who is
 * NOT on the switch when it happens. That reader gets the radio's own announcement, and
 * each table carries the selected voice's name in its `<caption>` — so arriving at the
 * table says which voice it prices, rather than leaving it to be inferred.
 *
 * ## `for`/`id` rather than a wrapping label, deliberately
 *
 * UX-DOCTRINE §8.1 prefers implicit association because two editors of two records on one
 * screen collide on any id scheme. That reason does not apply — this component renders
 * once per page — and the sibling combinator REQUIRES the input to precede the panels it
 * controls, which a wrapping label makes impossible.
 *
 * ## Two layouts, one source
 *
 * Six columns do not fit a 390px phone, and horizontal scrolling would hide the deepest
 * rungs behind a swipe nobody is told about. So the phone gets the packs back as ROWS —
 * which fits without scrolling now that the switch removed one of the two rate columns —
 * and the transposed comparison starts at `md`. Both are rendered from the same `packs`
 * array and the same accessors; neither holds a figure of its own.
 */
export function RateCard({ card }: { card: PublicRateCard }) {
  const [first, second] = VOICE_TIERS;
  return (
    <fieldset className="mt-10 sm:mt-12">
      <legend className="text-sm font-medium text-ink">Show rates for</legend>
      {/*
       * BOTH INPUTS COME FIRST, and every label and panel below is a following SIBLING of
       * both. That is the whole mechanism: `peer-checked/voice2:hidden` compiles to
       * `.peer\/voice2:checked ~ &`, which can only see forwards.
       *
       * The two names are written out rather than derived in a loop because Tailwind scans
       * SOURCE TEXT for class names — a templated `peer/${i}` produces no CSS at all. That
       * makes the arity a literal, which is what `ONE_SLOT_PER_VOICE` below pins.
       */}
      <input
        type="radio"
        name={VOICE_GROUP}
        id={VOICE_INPUT_IDS[0]}
        defaultChecked
        className="peer/voice1 sr-only"
      />
      <input
        type="radio"
        name={VOICE_GROUP}
        id={VOICE_INPUT_IDS[1]}
        className="peer/voice2 sr-only"
      />
      <label
        htmlFor={VOICE_INPUT_IDS[0]}
        className={`${SWITCH} me-2 peer-checked/voice1:border-brand-strong peer-checked/voice1:bg-brand-soft peer-checked/voice1:text-brand-strong peer-focus-visible/voice1:ring-2 peer-focus-visible/voice1:ring-brand-strong peer-focus-visible/voice1:ring-offset-2 peer-focus-visible/voice1:ring-offset-app dark:peer-checked/voice1:border-brand-bright dark:peer-checked/voice1:bg-brand-strong/20 dark:peer-checked/voice1:text-brand-bright`}
      >
        {tierLabel(card, first)} voice
      </label>
      <label
        htmlFor={VOICE_INPUT_IDS[1]}
        className={`${SWITCH} peer-checked/voice2:border-brand-strong peer-checked/voice2:bg-brand-soft peer-checked/voice2:text-brand-strong peer-focus-visible/voice2:ring-2 peer-focus-visible/voice2:ring-brand-strong peer-focus-visible/voice2:ring-offset-2 peer-focus-visible/voice2:ring-offset-app dark:peer-checked/voice2:border-brand-bright dark:peer-checked/voice2:bg-brand-strong/20 dark:peer-checked/voice2:text-brand-bright`}
      >
        {tierLabel(card, second)} voice
      </label>
      {/* The second voice's panel is `hidden` in the document and revealed by its own
          radio; the first is visible and hidden by the second's. Written that way round so
          that a browser which somehow applied none of the variants still shows a complete,
          correct rate card rather than an empty section. */}
      <div className="mt-7 peer-checked/voice2:hidden">
        <VoicePanel card={card} voice={first} />
      </div>
      <div className="mt-7 hidden peer-checked/voice2:block">
        <VoicePanel card={card} voice={second} />
      </div>
    </fieldset>
  );
}

/** The radio group's name, and the two ids the labels point at. */
const VOICE_GROUP = "rate-card-voice";
const VOICE_INPUT_IDS = ["rate-card-voice-1", "rate-card-voice-2"] as const;

/**
 * FAILS THE BUILD IF THE CARD EVER CARRIES A THIRD VOICE. The switch above renders
 * exactly two positions because Tailwind cannot generate a class name it has not read; a
 * third tier would otherwise be priced in the document and unreachable from the control,
 * which is the silent half-wiring CLAUDE.md's "leave no half-wired feature" is about.
 */
const ONE_SLOT_PER_VOICE: typeof VOICE_INPUT_IDS.length = VOICE_TIERS.length;
void ONE_SLOT_PER_VOICE;

/** One position of the switch, unselected. The selected look is a `peer-checked` variant. */
const SWITCH =
  "inline-flex cursor-pointer items-center rounded-full border border-line bg-surface px-5 py-2.5 text-sm font-medium text-ink-muted transition-colors hover:border-brand/50 touch:min-h-11";

/** Both layouts of one voice's ladder. Exactly one is displayed at any width. */
function VoicePanel({ card, voice }: { card: PublicRateCard; voice: VoiceTier }) {
  return (
    <>
      {/* `ScrollRegion`, not a bare `overflow-x-auto`: a scroll container no keyboard can
          reach is unusable without a mouse (UX-DOCTRINE §8.2, `tests/responsive.test.ts`).
          It is a safety net rather than the plan — the table fits from `md` up. */}
      <ScrollRegion
        label={`${tierLabel(card, voice)} voice rate card`}
        className="hidden md:block"
      >
        <PackColumns card={card} voice={voice} />
      </ScrollRegion>
      <PackRows card={card} voice={voice} />
    </>
  );
}

/** What the table is, in the words a screen reader hears before the figures. */
function caption(card: PublicRateCard, voice: VoiceTier): string {
  return `Prepaid credit packs on the ${tierLabel(card, voice)} voice: what you put on, the rate per minute it buys, and the talk time that comes to.`;
}

/** The one place the "this rung is the cheapest minute" treatment is spelled. */
function highlight(pack: RateCardPack): string {
  return pack.best_value ? "bg-brand-soft dark:bg-brand-strong/20" : "";
}

/**
 * THE LABEL ON THE HIGHLIGHTED COLUMN, and the reason it is this one.
 *
 * A recommended or "most popular" column is the single largest lever on a pricing page —
 * and we have no clients in production (our own `/resources` says so), so a popularity
 * badge here would be a fabrication, not a nudge. What IS true is arithmetic and is
 * visible in the row it sits above: this rung carries the lowest ₹/min on the card, on
 * both voices. "Best value" — the words this chip used to carry — is a JUDGEMENT about
 * value, which depends on how much a buyer will actually call; a clinic buying 300 minutes
 * a month is not better off at ₹50,000. The claim is narrowed to the fact.
 *
 * `best_value` is the API's own flag (`billing/credit_packs.py`, exactly one pack carries
 * it and `tests/credit_packs_test.py` pins that), so which column is marked is the
 * server's decision and not this page's.
 */
const LOWEST_RATE = "Lowest rate";

/** From `md` up: one COLUMN per pack, two rows of facts. The comparison form. */
function PackColumns({ card, voice }: { card: PublicRateCard; voice: VoiceTier }) {
  return (
    <table
      // Names the LAYOUT, not a style. `marketingPages.test.tsx` counts a pack per column
      // here and a pack per row in the stacked twin, and a selector written against a
      // Tailwind class would be a test that a class name has not changed.
      data-rate-layout="columns"
      // `md:` on the minimum width, and not decoration: this table is only rendered from
      // `md` up (its `ScrollRegion` is `hidden md:block`), so an unprefixed floor would be
      // a 672px minimum asserted on viewports that never paint it —
      // `tests/responsive.test.ts` fails on exactly that, and was right to.
      className="w-full table-fixed border-separate border-spacing-0 text-left text-sm md:min-w-[42rem]"
    >
      <caption className="sr-only">{caption(card, voice)}</caption>
      <thead>
        <tr>
          <td className="w-28 pb-4 align-bottom text-ink-muted">You put on</td>
          {card.packs.map((pack) => (
            <th
              key={pack.pack_id}
              scope="col"
              className={`rounded-t-2xl px-3 pt-4 pb-3 align-bottom font-semibold ${highlight(pack)}`}
            >
              <span className="block text-lg text-ink">
                {formatAmountINR(pack.amount_inr)}
              </span>
              {pack.best_value ? (
                <span className="mt-1 block text-xs font-semibold text-brand-strong dark:text-brand-bright">
                  {LOWEST_RATE}
                </span>
              ) : null}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row" className="border-t border-line py-4 pe-4 font-medium text-ink">
            Per minute
          </th>
          {card.packs.map((pack) => (
            <td
              key={pack.pack_id}
              className={`border-t border-line px-3 py-4 text-base font-semibold text-ink ${highlight(pack)}`}
            >
              {formatRateINR(packRate(pack, voice))}
            </td>
          ))}
        </tr>
        <tr>
          <th
            scope="row"
            className="border-t border-line/60 py-4 pe-4 font-medium text-ink"
          >
            Talk time
          </th>
          {card.packs.map((pack) => (
            <td
              key={pack.pack_id}
              className={`rounded-b-2xl border-t border-line/60 px-3 py-4 text-ink-muted ${highlight(pack)}`}
            >
              {packMinutes(pack, voice).toLocaleString("en-IN")} min
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

/**
 * Below `md`: one ROW per pack.
 *
 * Six columns are ~480px of content and a 390px phone is roughly 58% of this page's
 * traffic, so the transposed form would spend the majority case on a sideways scroll that
 * hides the deepest rungs — the two a reader is most likely to be comparing against. Rows
 * fit, because the switch above already removed one of the two rate columns.
 */
function PackRows({ card, voice }: { card: PublicRateCard; voice: VoiceTier }) {
  return (
    <table
      data-rate-layout="rows"
      className="w-full border-collapse text-left text-sm md:hidden"
    >
      <caption className="sr-only">{caption(card, voice)}</caption>
      <thead>
        <tr className="border-b border-line text-ink-muted">
          <th scope="col" className="py-3 pe-3 font-medium">
            You put on
          </th>
          <th scope="col" className="py-3 pe-3 font-medium">
            Per minute
          </th>
          <th scope="col" className="py-3 font-medium">
            Talk time
          </th>
        </tr>
      </thead>
      <tbody>
        {card.packs.map((pack) => (
          <tr key={pack.pack_id} className="border-b border-line/60">
            <th
              scope="row"
              className={`py-3 pe-3 font-semibold text-ink ${highlight(pack)}`}
            >
              {formatAmountINR(pack.amount_inr)}
              {pack.best_value ? (
                <span className="block text-xs font-semibold text-brand-strong dark:text-brand-bright">
                  {LOWEST_RATE}
                </span>
              ) : null}
            </th>
            <td
              className={`py-3 pe-3 font-semibold text-ink ${highlight(pack)}`}
            >
              {formatRateINR(packRate(pack, voice))}
            </td>
            <td className={`py-3 text-ink-muted ${highlight(pack)}`}>
              {packMinutes(pack, voice).toLocaleString("en-IN")} min
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

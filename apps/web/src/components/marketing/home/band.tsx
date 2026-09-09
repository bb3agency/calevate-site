import type { ReactNode } from "react";

import { Eyebrow, SECTION, SHELL } from "@/components/marketing/pageShell";
import { Reveal } from "@/components/marketing/motion";

/**
 * THE LANDING PAGE'S RHYTHM: chapters that differ, and bands that are ranked.
 *
 * ## The defect this replaces, stated so it is recognisable
 *
 * `app/page.tsx` was THIRTEEN bands of identical visual weight: `<Eyebrow index="01".."13">`,
 * an `<h2>` carrying the same `text-3xl sm:text-4xl` every time, `border-t border-line`
 * every time, and exactly two background treatments alternating over the lot. That is
 * UX-DOCTRINE §1's "everything equal means nothing primary" — written there about nine
 * equal `Card`s on the agent workspace — happening again one level up, on the page where
 * it costs the most: a landing page is SCANNED, and a scan needs something to catch on.
 * Measured before the change: 12,841px on a 1440px desktop, 21,488px on a 390px phone,
 * with no band louder than any other anywhere down it.
 *
 * ## The model
 *
 * A **chapter** is a tonal ground and a subject. A **band** is a section inside it. Most
 * chapters hold one band; two hold two, where the second is genuinely a supporting move on
 * the same subject rather than a new topic (the shortlist argument under the lead inbox;
 * the vertical field-lists under the language argument). A chapter is where the reader's
 * eye rests, so eight chapters replace thirteen bands without a sentence being deleted.
 *
 * Two channels carry the ranking, and they are deliberately the two UX-DOCTRINE §1 already
 * names for a screen's primary surface — SIZE and COLOUR — applied to a page rather than to
 * a panel:
 *
 * - **`weight`** sizes the `<h2>`: `anchor` (48px) for the three bands the argument rests
 *   on, `standard` (32px) for the supporting ones, `quiet` (24px) for material a buyer
 *   reads only if they are already interested. Three sizes over eleven bands, where there
 *   used to be one size over thirteen.
 * - **`tone`** grounds the chapter: `app`, `raised`, `brand` and one `dark`. Four
 *   treatments, non-alternating, so scroll position is legible from the colour alone.
 *
 * ## Why `weight` and `tone` are props and not classes at the call site
 *
 * Because the RANKING is the thing under test. `publicLanding.test.tsx` reads these back
 * (`data-band-weight`) and fails if every band goes back to one size — which is exactly how
 * this defect grew the first time, one reasonable-looking band at a time. A class string
 * typed per section cannot be asserted on without a test that knows Tailwind.
 *
 * ## The dark chapter
 *
 * `--brand-deep` (#0c5932), and it is the same value in both palettes — `.dark` in
 * `globals.css` redefines the surface and ink tokens, not the brand ramp — so the one band
 * that inverts is the one band that cannot drift between themes. White on it is 8.42:1 and
 * `text-white/80` is 6.03:1, both clear of WCAG 2.2 SC 1.4.3 AA (4.5:1). What
 * `tests/contrast.test.ts` bans is white type on the UNSUFFIXED brand green, which is
 * 3.38:1 — a different token from the one used here, two steps lighter on the same ramp.
 * (That sentence is written without the two class names beside each other on purpose: the
 * guard is a LINE scan and does not parse, so a comment describing the rule trips it. The
 * repo has paid for that lesson three times — see `tests/sourceScan.ts`.)
 * The product ships light-only (D-471), so nothing here reads
 * the device theme query or sets a class; the dormant `dark:` variants are kept in step
 * with the rest of the tree so the palette stays coherent if D-471 is ever superseded.
 */

/** The ground a chapter is painted on. */
export type ChapterTone = "app" | "raised" | "brand" | "dark";

/** How loud a band's heading is. Three steps, ranked. */
export type BandWeight = "anchor" | "standard" | "quiet";

const GROUND: Record<ChapterTone, string> = {
  app: "border-t border-line",
  raised: "border-t border-line bg-surface/40",
  // The brand ground is a tint, not a fill: cards inside stay `bg-surface` and lift off it.
  brand: "border-t border-line bg-brand-soft/60 dark:bg-brand-strong/10",
  // No top border — the colour change IS the boundary, and a hairline over it reads as a
  // seam. `text-white` is set here so a child that forgets a tone inherits a legible one.
  dark: "bg-brand-deep text-white",
};

const HEADING: Record<BandWeight, string> = {
  anchor: "text-[2.125rem] leading-[1.06] sm:text-[2.75rem] lg:text-5xl sm:leading-[1.04]",
  standard: "text-[1.75rem] leading-[1.15] sm:text-[2rem]",
  quiet: "text-2xl leading-[1.2] sm:text-[1.625rem]",
};

/**
 * A chapter: one ground, one subject, one shell.
 *
 * The vertical rhythm (`SECTION`) is spent ONCE per chapter rather than once per band,
 * which is where most of the page's height went: two consecutive bands on one subject used
 * to pay 2×80px of top padding, 2×80px of bottom padding and a hairline to say they were
 * different topics, when they were one.
 */
export function Chapter({
  tone = "app",
  children,
}: {
  tone?: ChapterTone;
  children: ReactNode;
}) {
  return (
    <div className={GROUND[tone]}>
      <div className={`${SHELL} ${SECTION}`}>{children}</div>
    </div>
  );
}

/**
 * One band inside a chapter: an eyebrow, a ranked `<h2>`, an optional lede, then content.
 *
 * `id` is the in-page anchor and is on the `<section>` rather than on a wrapper, so
 * `#how` still lands on the heading. `scroll-mt-20` clears the sticky header.
 */
export function Band({
  id,
  eyebrow,
  title,
  lede,
  weight = "standard",
  tone = "light",
  className = "",
  children,
}: {
  id: string;
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  weight?: BandWeight;
  /** `dark` inverts the type for the one chapter that is painted on `--brand-deep`. */
  tone?: "light" | "dark";
  /** Spacing when a chapter carries a SECOND band — `mt-16 sm:mt-20`, at the call site. */
  className?: string;
  children?: ReactNode;
}) {
  const dark = tone === "dark";
  return (
    <section
      id={id}
      data-band-weight={weight}
      // A band after the first in the same chapter is SPACED, not ruled: the chapter's
      // ground already says the two belong together, and a hairline between them would put
      // back the thirteen-equal-bands reading this whole file exists to end.
      className={`scroll-mt-20 ${className}`}
    >
      <Reveal>
        <Eyebrow tone={dark ? "inverse" : "default"}>{eyebrow}</Eyebrow>
        <h2
          className={`mt-4 max-w-3xl font-semibold tracking-tight text-balance ${
            dark ? "text-white" : "text-ink"
          } ${HEADING[weight]}`}
        >
          {title}
        </h2>
        {lede && (
          <p
            className={`mt-4 max-w-2xl text-pretty ${
              weight === "anchor" ? "text-lg" : "text-base"
            } ${dark ? "text-white/80" : "text-ink-muted"}`}
          >
            {lede}
          </p>
        )}
      </Reveal>
      {children}
    </section>
  );
}

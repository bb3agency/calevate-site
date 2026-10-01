import type { ReactNode } from "react";

import { Eyebrow, SHELL } from "@/components/marketing/pageShell";
import { Reveal } from "@/components/marketing/motion";

/**
 * THE LANDING PAGE'S RHYTHM: chapters that differ, and bands that are ranked.
 *
 * A **chapter** is a tonal ground and a subject; a **band** is a section inside it. Two
 * channels rank the bands, and both are props rather than class strings at the call site
 * because the ranking is what `publicLanding.test.tsx` asserts (`data-band-weight` and the
 * heading's size classes) — the page once drifted to thirteen bands at one size, one
 * reasonable-looking edit at a time:
 *
 * - **`weight`** sizes the `<h2>`: `anchor` for the three bands the argument rests on,
 *   `standard` for supporting ones, `quiet` for material read only by the already
 *   interested.
 * - **`tone`** grounds the chapter: `app`, `raised`, `brand` and one `dark`, non-
 *   alternating, so scroll position is legible from colour alone.
 *
 * The dark ground is `--brand-deep` (#0c5932), the same value in both palettes. White on it
 * is 8.42:1 and `text-white/80` 6.03:1, both clear of WCAG 1.4.3 AA. The product ships
 * light-only (D-471); the dormant `dark:` variants are kept in step with the rest of the
 * tree.
 */

export type ChapterTone = "app" | "raised" | "brand" | "dark";

export type BandWeight = "anchor" | "standard" | "quiet";

const GROUND: Record<ChapterTone, string> = {
  app: "border-t border-line",
  raised: "border-t border-line bg-surface",
  // A tint, not a fill: cards inside stay `bg-surface` and lift off it.
  brand: "border-t border-line bg-brand-soft/60 dark:bg-brand-strong/10",
  // No top border: the colour change is the boundary, and a hairline over it reads as a
  // seam. `text-white` here so a child that forgets a tone inherits a legible one.
  dark: "bg-brand-deep text-white",
};

const HEADING: Record<BandWeight, string> = {
  anchor: "text-[2.25rem] leading-[1.05] sm:text-[3rem] lg:text-[3.5rem] sm:leading-[1.03]",
  standard: "text-[1.875rem] leading-[1.12] sm:text-[2.5rem] sm:leading-[1.08]",
  quiet: "text-[1.625rem] leading-[1.2] sm:text-[2rem]",
};

/**
 * THE HOMEPAGE'S TYPE AND SPACE SCALE — one definition, read by every chapter.
 *
 * Named here rather than typed per section because the scale is what drifts: body copy on
 * this page once slid back to the console's 14px one module at a time. The page is read
 * once, at arm's length, by a stranger, so prose is 18-20px. `SECTION` (`pageShell`) is
 * deliberately separate — it is the rhythm of the interior pages.
 */
export const HOME = {
  /** A chapter's vertical rhythm. */
  chapter: "py-16 sm:py-24 lg:py-32",
  /** The gap when a chapter carries a SECOND band. */
  bandGap: "mt-20 sm:mt-28",
  /** Heading → lede. */
  ledeGap: "mt-5",
  /** The heading block → the band's content. */
  contentGap: "mt-12 sm:mt-16",
  /** Body copy: 18px on a phone, 20px from `sm`. */
  body: "text-lg sm:text-xl",
  /** Supporting copy: a caption, an aside, the sentence under a list. 16 → 18. */
  bodySm: "text-base sm:text-lg",
  /** The title of one item in a grid or row list. */
  itemTitle: "text-xl sm:text-2xl",
  /** Gap between items in a grid. */
  itemGap: "gap-5 sm:gap-6",
  /** A panel at the scale this page reads at. `CARD` is the console's 20/24px padding. */
  panel: "rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-8",
  /**
   * A panel that answers a pointer: 2px of lift and a stronger shadow. The transition
   * names its properties because these panels sit inside `Reveal`s, and GSAP writes
   * `opacity`/`transform` inline every frame — bare `transition` would chase each frame.
   * Tailwind's `-translate-y-*` sets the separate `translate` property GSAP never touches.
   * Hover-only (Tailwind 4 gates `hover:` to hover-capable pointers).
   */
  panelLift:
    "transition-[translate,border-color,box-shadow] duration-(--duration-base) ease-out hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-raised",
} as const;

/** A chapter: one ground, one subject, one shell. */
export function Chapter({
  tone = "app",
  children,
  className = "",
}: {
  tone?: ChapterTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`${GROUND[tone]} ${className}`}>
      <div className={`${SHELL} ${HOME.chapter}`}>{children}</div>
    </div>
  );
}

/**
 * One band inside a chapter: an eyebrow, a ranked `<h2>`, an optional lede, then content.
 *
 * `split` sets the lede beside the heading from `lg` up — the heading carries the claim,
 * the lede sits where the eye lands after it, and the band's content starts a screenful
 * higher than it would under a stacked block. `id` is on the `<section>` so an in-page
 * link lands on the heading; `scroll-mt-20` clears the sticky header.
 */
export function Band({
  id,
  eyebrow,
  title,
  lede,
  weight = "standard",
  tone = "light",
  split = false,
  className = "",
  children,
}: {
  id: string;
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  weight?: BandWeight;
  tone?: "light" | "dark";
  split?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const dark = tone === "dark";
  return (
    <section id={id} data-band-weight={weight} className={`scroll-mt-20 ${className}`}>
      <Reveal
        className={
          split && lede ? "grid gap-5 lg:grid-cols-[1.2fr_1fr] lg:items-end lg:gap-16" : ""
        }
      >
        <div>
          <Eyebrow tone={dark ? "inverse" : "default"}>{eyebrow}</Eyebrow>
          <h2
            className={`mt-5 max-w-4xl font-semibold tracking-tight text-balance ${
              dark ? "text-white" : "text-ink"
            } ${HEADING[weight]}`}
          >
            {title}
          </h2>
        </div>
        {lede && (
          <p
            className={`${split ? "lg:pb-1.5" : HOME.ledeGap} max-w-3xl text-pretty ${
              weight === "anchor" ? "text-xl sm:text-2xl" : HOME.body
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

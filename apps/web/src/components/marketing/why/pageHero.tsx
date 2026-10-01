import type { ReactNode } from "react";

import { HeroStagger } from "@/components/marketing/motion";
import { PILL_LINK, SHELL } from "@/components/marketing/pageShell";

/**
 * The opening of an interior page, in the homepage hero's shape: a centred subject, one
 * sentence on why it matters, then the product drawn full width beneath it.
 *
 * Not `PageIntro` (pageShell): that block is left-aligned text only, and the founder's
 * rule for these pages is that the product is shown rather than described. The type scale
 * is one step below the homepage's h1, because an interior page states a subject rather
 * than making the opening pitch again.
 *
 * `label` is a sentence-case pill rather than an uppercase tracked eyebrow, matching the
 * homepage hero's language pill.
 */
export function PageHero({
  label,
  title,
  lede,
  nav,
  product,
  caption = "An illustration of the product, not a recording, a real customer or a measurement of how well it does it.",
}: {
  label: string;
  title: string;
  lede: string;
  /** In-page links under the lede, for a page a reader jumps around in. */
  nav?: ReactNode;
  /** The product shot. Rendered with the illustration caption under it. */
  product?: ReactNode;
  caption?: string;
}) {
  return (
    <section className="relative isolate overflow-hidden border-b border-line">
      {/* Decorative ground, a sibling at -z-10 so the text over it has a resolvable
          background for the contrast checks (same arrangement as the homepage hero). */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="mk-grid-lines absolute inset-0" />
        <div className="mk-blob mk-blob--a mk-float absolute -top-24 left-[8%] h-56 w-56 sm:h-96 sm:w-96" />
      </div>

      <div className={`${SHELL} relative pt-10 pb-16 sm:pt-16 sm:pb-20 lg:pt-20`}>
        <HeroStagger className="mx-auto flex max-w-4xl flex-col items-center text-center">
          <p
            data-hero-item
            className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-1.5 text-sm font-medium text-ink-muted shadow-card"
          >
            {label}
          </p>
          <h1
            data-hero-item
            className="mt-6 max-w-4xl text-[2.25rem] leading-[1.08] font-semibold tracking-tight text-balance text-ink sm:mt-7 sm:text-5xl sm:leading-[1.05] lg:text-[3.5rem] lg:leading-[1.03]"
          >
            {title}
          </h1>
          <p
            data-hero-item
            className="mt-6 max-w-2xl text-lg text-pretty text-ink-muted sm:text-xl"
          >
            {lede}
          </p>
          {nav && (
            <div data-hero-item className="mt-8 w-full">
              {nav}
            </div>
          )}
        </HeroStagger>

        {product && (
          <div className="relative mx-auto mt-12 max-w-6xl sm:mt-16">
            {product}
            <p className="mx-auto mt-6 max-w-xl text-center text-base text-pretty text-ink-muted">
              {caption}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

/** The in-page links a hero carries: one row of pills, wrapping on a phone. */
export function JumpLinks({ links }: { links: readonly { href: string; label: string }[] }) {
  return (
    <nav aria-label="On this page">
      <ul className="flex flex-wrap justify-center gap-2">
        {links.map(({ href, label }) => (
          <li key={href}>
            <a href={href} className={PILL_LINK}>
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

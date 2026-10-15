import Link from "next/link";

import { ArrowRight, Check } from "lucide-react";

import {
  CTA_LABEL,
  CTA_PRIMARY,
  CTA_SECONDARY,
  NUDGE_ARROW,
  SHELL,
} from "@/components/marketing/pageShell";

import { HeroProduct } from "./mockups/heroProduct";

/**
 * The hero: the promise, who it is for, one door — and then the product, full width.
 *
 * CENTRED, with the product shot BELOW the copy rather than beside it. Side by side, the
 * product got half a 1280px row and was drawn at a size where its rows were a texture;
 * below, it gets the whole width and reads as a screen. It is also the dominant hero shape
 * across the product pages this redesign studied (Evil Martians' 2025 survey of 100
 * developer-tool landing pages found centred compositions the large majority).
 *
 * Kept from every version before this one, because each was paid for once:
 * - the phone headline is at most 40px (at 48px in a 320px box it set to four lines and
 *   pushed the call to action off the first screen), and fluid below that: the
 *   unbreakable "nobody answered." run is about 8.3em wide, so 10.2vw keeps it inside the
 *   20px gutters from 320px (32.6px type) and reaches 40px at about 390px;
 * - the audience sentence comes BEFORE the button — `publicLanding.test.tsx` pins the
 *   ORDER, since the words may change and the order is what regressed;
 * - the highlighted phrase and its full stop are one unbreakable run, or a lone "." wraps
 *   onto its own line at 72px;
 * - the four claims are each a shipped behaviour: 24/7 answering
 *   (`apps/api/agents/business_hours.py`), a first call on every enquiry
 *   (`apps/api/ingest/service.py`), the fixed qualification statuses
 *   (`apps/api/crm/schemas.py`) and the calendar action (`apps/api/actions/models.py`).
 *   They sit in the slot a landing page normally fills with borrowed proof, and they are
 *   not a claim about anybody else.
 *
 * The entrance is the `mk-hero-in` CSS stagger in `globals.css`, never GSAP: this block is
 * painted by the server, and a script entrance would replay it at hydration.
 */

const HERO_CLAIMS: readonly string[] = [
  "Answers day and night",
  "Follows up on every enquiry",
  "Qualifies before your team calls",
  "Books appointments",
];

export function Hero() {
  return (
    <section className="relative isolate overflow-hidden">
      {/*
        Decorative ground: the masked line grid, the marketing site's one texture. A SIBLING of the
        content at `z-below`, never an ancestor of it — a background image on an ancestor of
        text is what makes a contrast check unresolvable. `isolate` on the section is what
        keeps `z-below` inside it rather than behind the page's own background.
      */}
      <div aria-hidden className="pointer-events-none absolute inset-0 z-below">
        <div className="mk-grid-lines absolute inset-0" />
      </div>

      <div className={`${SHELL} relative pt-10 pb-16 sm:pt-16 sm:pb-24 lg:pt-20`}>
        <div className="mx-auto flex max-w-5xl flex-col items-center text-center">
          <p
            className="mk-hero-in mk-h1 text-sm font-medium text-ink-muted"
          >
            Telugu-first · Hindi · English
          </p>
          <h1
            className="mk-hero-in mk-h2 mt-6 max-w-4xl text-[length:clamp(2rem,10.2vw,2.5rem)] leading-[1.05] font-semibold tracking-tight text-balance text-ink sm:mt-7 sm:text-6xl sm:leading-[1.02] lg:text-[4.5rem]"
          >
            Never miss a lead because{" "}
            <span className="whitespace-nowrap">
              <span className="relative inline-block">
                <span className="relative z-raised">nobody answered</span>
                <span
                  aria-hidden
                  className="absolute inset-x-[-0.12em] bottom-[0.06em] z-base h-[0.42em] -rotate-1 rounded-sm bg-brand-soft dark:bg-brand-strong/45"
                />
              </span>
              .
            </span>
          </h1>
          <p
            className="mk-hero-in mk-h3 mt-6 max-w-2xl text-xl text-pretty text-ink-muted sm:mt-7 sm:text-2xl"
          >
            Calevate answers your calls, follows up on every enquiry, works out who is worth
            your team’s time, and turns each conversation into a lead they can act on.
          </p>
          <p className="mk-hero-in mk-h4 mt-4 max-w-2xl text-base text-pretty text-ink-muted sm:text-lg">
            Built Telugu-first for clinics, property offices, insurance advisors and coaching
            centres across Andhra Pradesh and Telangana.
          </p>
          <div className="mk-hero-in mk-h5 mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href="/signup" className={CTA_PRIMARY}>
              {CTA_LABEL}
              <ArrowRight aria-hidden className={NUDGE_ARROW} />
            </Link>
            <Link href="#how" className={CTA_SECONDARY}>
              See how it works
            </Link>
          </div>
          <ul
            className="mk-hero-in mk-h6 mt-8 flex flex-col items-start gap-y-3 sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-6"
          >
            {HERO_CLAIMS.map((claim) => (
              <li key={claim} className="flex items-center gap-2 text-base font-medium text-ink-muted">
                <Check aria-hidden className="h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright" strokeWidth={2.5} />
                {claim}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative mx-auto mt-12 max-w-7xl sm:mt-16">
          <HeroProduct />
        </div>
      </div>
    </section>
  );
}

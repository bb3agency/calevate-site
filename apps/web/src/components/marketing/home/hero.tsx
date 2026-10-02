import Link from "next/link";

import { ArrowRight, Check } from "lucide-react";

import { HeroStagger } from "@/components/marketing/motion";
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
 * - the phone headline is 40px (at 48px in a 320px box it set to four lines and pushed
 *   the call to action off the first screen);
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
        Decorative ground: the masked line grid and two soft brand glows. A SIBLING of the
        content at `-z-10`, never an ancestor of it — a background image on an ancestor of
        text is what makes a contrast check unresolvable. `isolate` on the section is what
        keeps `-z-10` inside it rather than behind the page's own background.
      */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="mk-grid-lines absolute inset-0" />
        <div className="mk-blob mk-blob--a mk-float absolute -top-24 left-[8%] h-56 w-56 sm:h-96 sm:w-96" />
        <div className="mk-blob mk-blob--b mk-float--slow absolute top-[38%] right-[-6rem] h-64 w-64 sm:h-[28rem] sm:w-[28rem]" />
      </div>

      <div className={`${SHELL} relative pt-10 pb-16 sm:pt-16 sm:pb-24 lg:pt-20`}>
        <HeroStagger className="mx-auto flex max-w-5xl flex-col items-center text-center">
          <p
            data-hero-item
            className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-1.5 text-sm font-medium text-ink-muted shadow-card"
          >
            Telugu-first · Hindi · English
          </p>
          <h1
            data-hero-item
            className="mt-6 max-w-4xl text-[2.5rem] leading-[1.05] font-semibold tracking-tight text-balance text-ink sm:mt-7 sm:text-6xl sm:leading-[1.02] lg:text-[4.5rem]"
          >
            Never miss a lead because{" "}
            <span className="whitespace-nowrap">
              <span className="relative inline-block">
                <span className="relative z-10">nobody answered</span>
                <span
                  aria-hidden
                  className="absolute inset-x-[-0.12em] bottom-[0.06em] z-0 h-[0.42em] -rotate-1 rounded-sm bg-brand-soft dark:bg-brand-strong/45"
                />
              </span>
              .
            </span>
          </h1>
          <p
            data-hero-item
            className="mt-6 max-w-2xl text-xl text-pretty text-ink-muted sm:mt-7 sm:text-2xl"
          >
            Calevate answers your calls, follows up on every enquiry, works out who is worth
            your team’s time, and turns each conversation into a lead they can act on.
          </p>
          {/* `-muted`, not `-faint`: this line sits over the hero's glow, and `--text-faint`
              has no headroom above 4.5:1 on a tinted ground (see `globals.css`). */}
          <p data-hero-item className="mt-4 max-w-2xl text-base text-pretty text-ink-muted sm:text-lg">
            Built Telugu-first for clinics, property offices, insurance advisors and coaching
            centres across Andhra Pradesh and Telangana.
          </p>
          <div data-hero-item className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href="/signup" className={CTA_PRIMARY}>
              {CTA_LABEL}
              <ArrowRight aria-hidden className={NUDGE_ARROW} />
            </Link>
            <Link href="#how" className={CTA_SECONDARY}>
              See how it works
            </Link>
          </div>
          <ul
            data-hero-item
            className="mt-8 flex flex-col items-start gap-y-3 sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-6"
          >
            {HERO_CLAIMS.map((claim) => (
              <li key={claim} className="flex items-center gap-2 text-base font-medium text-ink-muted">
                <Check aria-hidden className="h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright" strokeWidth={2.5} />
                {claim}
              </li>
            ))}
          </ul>
        </HeroStagger>

        <div className="relative mx-auto mt-12 max-w-7xl sm:mt-16">
          <HeroProduct />
          <p className="mx-auto mt-6 max-w-xl text-center text-base text-pretty text-ink-muted">
            An illustration of the product, not a recording, a real customer or a measurement
            of how well it does it.
          </p>
        </div>
      </div>
    </section>
  );
}

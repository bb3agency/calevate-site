import Link from "next/link";

import { ArrowRight, Check, Languages } from "lucide-react";

import { HeroCallSim } from "@/components/marketing/heroCallSim";
import { HeroStagger } from "@/components/marketing/motion";
import {
  CTA_LABEL,
  CTA_PRIMARY,
  CTA_SECONDARY,
  SHELL,
} from "@/components/marketing/pageShell";

/**
 * The hero — MOVED, NOT REWRITTEN.
 *
 * Every measurement in it was paid for once and is carried over unchanged: `pt-8` on a
 * phone rather than `pt-10` (the sticky header already spends ~56px, and the old pair put
 * the one sentence the page depends on a fifth of the way down a 640px screen), the 40px
 * headline rather than 48px (at `text-5xl` in a 320px box it set to four lines and pushed
 * the call to action off the screen), and the audience sentence ABOVE the button rather
 * than below it — which `publicLanding.test.tsx` pins as ORDER, not as words, because the
 * words may legitimately be rewritten and the order is what regressed.
 *
 * The four claims under the button are the only thing on this page in the slot a landing
 * page normally fills with borrowed proof, and each is a shipped behaviour: 24/7 answering
 * (`apps/api/agents/business_hours.py`), a first call on every enquiry
 * (`apps/api/ingest/service.py`, `apps/api/campaigns/service.py`), the fixed qualification
 * statuses (`apps/api/crm/schemas.py:29`) and the calendar action kind
 * (`apps/api/actions/models.py:53`). No count, no logo, no number.
 */

/** Four behaviours, each mapped to a shipped feature. Not a claim about anybody else. */
const HERO_CLAIMS: readonly string[] = [
  "Answers day and night",
  "Follows up on every enquiry",
  "Qualifies before your team calls",
  "Books appointments",
];

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* Decorative background: a masked dotted grid and two soft brand blobs.
          All aria-hidden, all pointer-events-none, all frozen under reduced motion. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="mk-grid-dots absolute inset-0" />
        <div className="mk-blob mk-blob--a mk-float absolute -top-24 -left-24 h-80 w-80" />
        <div className="mk-blob mk-blob--b mk-float--slow absolute -top-16 right-[-6rem] h-96 w-96" />
      </div>

      <div className={`${SHELL} relative pt-8 pb-12 sm:pt-14 sm:pb-16 lg:pt-16`}>
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12">
          <HeroStagger>
            <p
              data-hero-item
              className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3.5 py-1.5 text-xs font-medium text-ink-muted shadow-sm backdrop-blur"
            >
              <Languages aria-hidden className="h-3.5 w-3.5 text-brand-strong dark:text-brand-bright" />
              Telugu-first · Hindi · English
            </p>
            <h1
              data-hero-item
              className="mt-5 max-w-4xl text-[2.5rem] leading-[1.05] font-semibold tracking-tight text-balance text-ink sm:mt-6 sm:text-6xl sm:leading-[1.02] lg:text-[3.75rem]"
            >
              Never miss a lead because{" "}
              <span className="relative inline-block">
                <span className="relative z-10">nobody answered</span>
                <span
                  aria-hidden
                  className="absolute inset-x-[-0.12em] bottom-[0.06em] z-0 h-[0.42em] -rotate-1 rounded-sm bg-brand-soft dark:bg-brand-strong/45"
                />
              </span>
              .
            </h1>
            <p data-hero-item className="mt-5 max-w-2xl text-lg text-pretty text-ink-muted sm:text-xl">
              Calevate answers your calls, follows up on every enquiry, works out who is
              worth your team’s time, and turns each conversation into a lead they can act
              on.
            </p>
            <p data-hero-item className="mt-3 max-w-2xl text-sm text-pretty text-ink-faint">
              Built Telugu-first for clinics, property offices, insurance advisors and
              coaching centres across Andhra Pradesh and Telangana.
            </p>
            <div data-hero-item className="mt-7 flex flex-wrap items-center gap-3">
              <Link href="/signup" className={CTA_PRIMARY}>
                {CTA_LABEL}
                <ArrowRight
                  aria-hidden
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                />
              </Link>
              <Link href="#how" className={CTA_SECONDARY}>
                See how it works
              </Link>
            </div>
            <ul
              data-hero-item
              className="mt-7 flex flex-col gap-y-2.5 sm:flex-row sm:flex-wrap sm:gap-x-6 sm:gap-y-3"
            >
              {HERO_CLAIMS.map((claim) => (
                <li key={claim} className="flex items-center gap-2 text-sm font-medium text-ink-muted">
                  <span
                    aria-hidden
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                  >
                    <Check className="h-3 w-3" />
                  </span>
                  {claim}
                </li>
              ))}
            </ul>
          </HeroStagger>

          <div className="relative">
            {/* A glow tucked behind the figure so it reads as lifted off the page. */}
            <div
              aria-hidden
              className="mk-blob mk-blob--a pointer-events-none absolute inset-x-6 -top-6 -z-10 h-40"
            />
            <HeroCallSim />
          </div>
        </div>
      </div>
    </section>
  );
}

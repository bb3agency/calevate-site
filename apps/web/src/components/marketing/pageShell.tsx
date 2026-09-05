/**
 * The chrome and the rhythm every public marketing page shares.
 *
 * ## Why a component and not a route-group layout
 *
 * A Next layout would be the obvious answer and is the wrong one here for one measurable
 * reason: `tests/a11y.test.tsx` renders each `page.tsx` WITHOUT its layout (that is how
 * the App Router composes them, and how the rest of the suite renders screens). A layout
 * would therefore sweep eight marketing pages with no header, no navigation and no
 * footer — the exact parts where the keyboard and screen-reader barriers live. As a
 * component the chrome is part of the page under test.
 *
 * The second reason is smaller and still real: `/` would have to move into a route group
 * to share a layout with the rest, which renames the key every guard in this suite uses
 * for the homepage.
 *
 * ## What lives here
 *
 * The shell, the four spacing tokens and the call-to-action classes — ONE definition each.
 * They were local constants in `app/page.tsx` when there was one marketing page; eight
 * copies of `py-16 sm:py-20 lg:py-24` is precisely the drift CLAUDE.md's "one way per
 * problem" rule is about, and the one that falls behind is never the one you are editing.
 */

import type { ReactNode } from "react";
import Link from "next/link";

import { ArrowRight } from "lucide-react";

import { BrandLockup } from "@/components/brand";
import { LEGAL_DOCUMENTS } from "@/lib/legal";

import { SmoothScroll } from "./motion";
import { NAV_ROUTES, SiteHeader } from "./siteHeader";

/**
 * The content column. The steps are deliberately small (1152 → 1280 → 1440): past roughly
 * 75 characters a line gets hard to track back from, which is why the paragraphs inside
 * keep their own `max-w-2xl` regardless of what this does.
 */
export const SHELL =
  "mx-auto w-full max-w-6xl px-5 sm:px-6 xl:max-w-7xl 2xl:max-w-[90rem]";

/**
 * A band's vertical rhythm. It steps DOWN on a phone (64px, not 80px) — a dozen bands at
 * `py-20` spend over a thousand pixels of a 360px reader's scroll on nothing, and vertical
 * air is the one thing a phone has least of.
 */
export const SECTION = "py-16 sm:py-20 lg:py-24";

/**
 * A card. 20px of padding on a phone rather than 24px, for `tests/responsive.test.ts`'s
 * reason: inside a `px-5` shell, a flat `p-6` spends 88px of a 360px viewport on gutter
 * before any words.
 */
export const CARD = "rounded-2xl border border-line bg-surface p-5 sm:p-6";

/** The grid under a band's heading block. One gap, one top margin, everywhere. */
export const GRID = "mt-10 grid gap-4 sm:mt-12";

/**
 * ONE DOOR, ONE NAME FOR IT.
 *
 * `/signup` used to be reached under four different labels, which is CLAUDE.md's "two ways
 * of doing one thing" defect on a surface where it also costs conversion: a reader cannot
 * tell whether four buttons are four things or one. The label is the founder's decision of
 * 5 Sep 2026 (it displaced the same morning's "See how it works", which survives as the
 * hero's secondary). "Create a workspace" is banned outright — it names a noun a
 * first-time visitor does not have and would not want. Sentence case follows GOV.UK's
 * button guidance, "write button text in sentence case, describing the action it performs"
 * (alphagov/govuk-design-system `main`, `src/components/button/index.md`, read 1 Sep 2026).
 */
export const CTA_LABEL = "Get started";

export const CTA_PRIMARY =
  "group inline-flex items-center gap-2 rounded-full bg-brand-strong px-6 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app";

export const CTA_SECONDARY =
  "inline-flex items-center gap-2 rounded-full border border-line bg-surface px-6 py-3 text-sm font-semibold text-ink transition-colors hover:border-brand/50 hover:bg-brand-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app";

/** An inline link in body copy, in one place so eight pages cannot spell it eight ways. */
export const INLINE_LINK =
  "font-semibold text-brand-strong underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong dark:text-brand-bright";

/** The small editorial label above a band: an index, a hairline, a word. */
export function Eyebrow({ index, children }: { index: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-3 text-xs font-semibold tracking-[0.18em] text-brand-strong uppercase dark:text-brand-bright">
      <span className="font-mono text-ink-faint">{index}</span>
      <span aria-hidden className="h-px w-6 bg-brand/50" />
      {children}
    </p>
  );
}

/**
 * The opening block of an interior page: what this page is, and one sentence on why the
 * reader should care. Deliberately not the homepage hero — an interior page's job is depth,
 * so it states its subject and gets on with it rather than making the pitch again.
 */
export function PageIntro({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  children?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden border-b border-line">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="mk-grid-dots absolute inset-0" />
        <div className="mk-blob mk-blob--a mk-float absolute -top-24 -left-24 h-72 w-72" />
      </div>
      <div className={`${SHELL} pt-10 pb-12 sm:pt-14 sm:pb-16`}>
        <p className="text-xs font-semibold tracking-[0.18em] text-brand-strong uppercase dark:text-brand-bright">
          {eyebrow}
        </p>
        <h1 className="mt-4 max-w-4xl text-[2.25rem] leading-[1.08] font-semibold tracking-tight text-balance text-ink sm:text-5xl sm:leading-[1.05]">
          {title}
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-pretty text-ink-muted">{lede}</p>
        {children}
      </div>
    </section>
  );
}

/**
 * The closing offer, repeated at the foot of every interior page.
 *
 * Same door, same label, same two reassurances as the homepage — both of which are shipped
 * facts rather than commercial promises: a person approves what the agent may say
 * (`apps/api/kb/service.py:437::approve_source`, `apps/api/agents/service.py:1193`), and a
 * campaign is a draft until somebody launches it (`apps/api/campaigns/service.py:1199`).
 */
export function ClosingCta({ line }: { line: string }) {
  return (
    <section className="border-t border-line bg-surface/40">
      <div className={`${SHELL} ${SECTION}`}>
        <div className="rounded-2xl border border-line bg-surface p-6 sm:p-10">
          <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            {line}
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Tell us what your callers ring about and what you need written down about each
            one. You approve the agent before it goes live, and nothing calls a customer
            until you launch it.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link href="/signup" className={CTA_PRIMARY}>
              {CTA_LABEL}
              <ArrowRight
                aria-hidden
                className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
              />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * The footer.
 *
 * Two navigation landmarks, both DERIVED rather than typed out. The legal list comes from
 * `LEGAL_DOCUMENTS` because a hand-written copy is a second enumeration of the eight
 * documents and the one that falls behind is the footer — precisely the surface a payment
 * aggregator's reviewer checks before approving a merchant account. The site list comes
 * from `NAV_ROUTES` for the same reason, one tier up: a page added to the header and
 * forgotten here is a page with one way in.
 */
export function MarketingFooter() {
  return (
    <footer className="border-t border-line">
      <div className={`${SHELL} flex flex-col gap-6 py-10`}>
        <div className="flex items-center">
          <BrandLockup height={52} />
        </div>
        {/* "Site", not "Pages": the header's own nav is already named "Pages", and axe's
            `landmark-unique` rule is about a screen-reader user being able to tell two
            landmarks of the same role apart by name. */}
        <nav aria-label="Site">
          <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
            <li>
              <Link
                href="/"
                className="inline-block py-1 text-ink-muted underline-offset-4 hover:text-ink hover:underline touch:py-3.5"
              >
                Home
              </Link>
            </li>
            {NAV_ROUTES.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="inline-block py-1 text-ink-muted underline-offset-4 hover:text-ink hover:underline touch:py-3.5"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Legal">
          {/*
           * `inline-block py-1` plus `touch:py-3.5`: see `tests/responsive.test.ts`'s "a
           * navigation link's tap target", which pins this exact shape. `py-1` puts a 16px
           * line box in a 24px target, which clears WCAG 2.2 SC 2.5.8's AA minimum and is
           * still a poor box for a thumb; 14px either side makes it 44px, the SC 2.5.5
           * (Enhanced) size the Understanding document recommends for important links.
           * `touch:` is the `pointer: coarse` variant declared in globals.css, so desktop
           * density is untouched.
           */}
          <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link
                  href={`/legal/${doc.slug}`}
                  className="inline-block py-1 text-ink-faint underline-offset-4 hover:text-ink hover:underline touch:py-3.5"
                >
                  {doc.title}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <p className="text-xs text-ink-faint">
          Calevate — AI phone agents for Indian businesses.
        </p>
      </div>
    </footer>
  );
}

/**
 * A whole marketing page: smooth scroll, the marketing visual layer, the header, a `<main>`
 * and the footer.
 *
 * `data-marketing-root` is what lets `globals.css` hand the document its scrollbar back and
 * paint the marketing-only tokens without either rule reaching the fixed app shells under
 * /c and /admin, and it must be the OUTERMOST element for the `:has()` selector to fire.
 */
export function MarketingPage({ children }: { children: ReactNode }) {
  return (
    // `SmoothScroll` renders a context provider and no element of its own, so the marketing
    // root below is still the outermost ELEMENT — which is what the `:has()` rule and
    // `publicLanding.test.tsx` both require.
    <SmoothScroll>
      <div data-marketing-root className="bg-app text-ink">
        <SiteHeader />
        <main>{children}</main>
        <MarketingFooter />
      </div>
    </SmoothScroll>
  );
}

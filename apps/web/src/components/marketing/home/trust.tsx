import Link from "next/link";

import { ArrowRight, Check, Globe, Lock, ShieldCheck } from "lucide-react";

import { Reveal } from "@/components/marketing/motion";
import { INLINE_LINK } from "@/components/marketing/pageShell";
import {
  COMPLIANCE_INVARIANTS,
  DATA_PROMISES,
  TESTED_SCENARIOS,
  WHERE_IT_RUNS,
} from "@/lib/marketing/compliance";

import { Band, Chapter, HOME } from "./band";

/**
 * CHAPTER 7 — trust. COMPRESSED IN LAYOUT AND RANKING, NOT ONE WORD IN WORDING.
 *
 * ⚠ Every sentence rendered here comes from `lib/marketing/compliance.ts`, which forbids
 * rewording in its own header and is rendered by `/security` from the same constants so the
 * two surfaces cannot drift. `publicLanding.test.tsx` pins several of these substrings in
 * BOTH directions — the page must say the Indian half is Indian AND that the language model
 * is not, must keep "checked, not proved by a build", and must not claim a build proves
 * residency. Deleting any of those clauses is how the over-claim comes back looking like a
 * tidy-up, so the redesign MOVED this content and changed none of it.
 *
 * ## Why this chapter is `quiet` and not `anchor`
 *
 * Not because it matters less — it is the legally load-bearing part of the page. Because of
 * WHO reads it and WHEN: a buyer reaches the compliance section after they have decided the
 * product is interesting, and they read it closely rather than scanning it. A 48px heading
 * here would compete with the promise and the price for a reader who has not got this far,
 * and buys nothing from the reader who has. UX-DOCTRINE §1: urgency is a tone, not a rank.
 *
 * The material stays FOREGROUND — nothing about the guarantee is disclosed. What sits
 * inside a `<details>` is the four invariants in full and the residency paragraph in full,
 * both of which have a fact in the closed state, which is the "move complexity behind
 * interaction" rule applied to the one content on this page that may not be shortened by
 * rewriting.
 */

export function Trust() {
  return (
    <Chapter tone="raised">
      <Band
        id="trust"
        eyebrow="Trust"
        weight="quiet"
        title="An automated call is regulated here, and we built for that"
        lede="The agent speaks on your registration, so these are not settings with sensible defaults — they are limits the product enforces on every dial."
      >
        {/* THREE PANELS STACKED, NOT THREE COLUMNS.
            These three legitimately ARE cards — each is a bounded subject with its own
            disclosure control — so §1 does not turn them into rows. What three columns did
            was set the one legally load-bearing block on the page in 360px boxes at 14px,
            with two `<details>` whose closed state carries the FACT (§3) crushed into two
            lines. Stacked full width, each panel's fact is a sentence rather than a
            paragraph-shaped stack, and the reader meets one obligation at a time. */}
        <div className={`${HOME.contentGap} grid ${HOME.itemGap}`}>
          <Reveal as="section" className={HOME.panel}>
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
              <ShieldCheck aria-hidden className="h-7 w-7" />
            </span>
            <h3 className={`mt-6 ${HOME.itemTitle} font-semibold text-balance text-ink`}>
              The rules live in the code
            </h3>
            <p className={`mt-3 max-w-2xl text-pretty text-ink-muted ${HOME.bodySm}`}>
              Four things are enforced on the dispatch path rather than written in a policy
              page.
            </p>
            <details className="mt-5">
              <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-base font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                See all four
                <ArrowRight aria-hidden className="h-4 w-4" />
              </summary>
              <dl className="mt-4 space-y-4">
                {COMPLIANCE_INVARIANTS.map(({ icon: Icon, title, body }) => (
                  <div key={title}>
                    <dt className="flex items-center gap-2 text-base font-semibold text-ink sm:text-lg">
                      <Icon
                        aria-hidden
                        className="h-5 w-5 shrink-0 text-brand-strong dark:text-brand-bright"
                      />
                      {title}
                    </dt>
                    <dd className={`mt-1.5 text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </Reveal>

          <Reveal as="section" delay={0.08} className={HOME.panel}>
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
              <Globe aria-hidden className="h-7 w-7" />
            </span>
            <h3 className={`mt-6 ${HOME.itemTitle} font-semibold text-balance text-ink`}>
              Know where your customer data goes
            </h3>
            <p className={`mt-3 max-w-2xl text-pretty text-ink-muted ${HOME.bodySm}`}>
              Which part of a call runs where, including the parts that are not Indian. In
              full, in our words, before you sign anything.
            </p>
            <details className="mt-5">
              <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-base font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                Where each part runs
                <ArrowRight aria-hidden className="h-4 w-4" />
              </summary>
              {/* VERBATIM, AND FROM ONE DEFINITION. `/security` renders the same constant. */}
              <p className={`mt-4 text-pretty text-ink-muted ${HOME.bodySm}`}>{WHERE_IT_RUNS}</p>
              <p className="mt-4 text-base">
                <Link href="/legal/subprocessors" className={INLINE_LINK}>
                  Read the sub-processor page
                </Link>
              </p>
            </details>
          </Reveal>

          <Reveal as="section" delay={0.16} className={HOME.panel}>
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
              <Lock aria-hidden className="h-7 w-7" />
            </span>
            <h3 className={`mt-6 ${HOME.itemTitle} font-semibold text-balance text-ink`}>
              Your customers’ data stays yours
            </h3>
            <dl className="mt-4 space-y-4">
              {DATA_PROMISES.map(({ term, detail }) => (
                <div key={term}>
                  <dt className="text-base font-semibold text-ink sm:text-lg">{term}</dt>
                  <dd className={`mt-1.5 text-pretty text-ink-muted ${HOME.bodySm}`}>{detail}</dd>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>

        {/* The testing band, compressed to what it is: a list of what gets tested. No score
            of any kind — see `TESTED_SCENARIOS` for why. */}
        <Reveal as="section" delay={0.24} className={`mt-6 sm:mt-8 ${HOME.panel}`}>
          <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>
            Your agent is run against awkward calls before it takes a real one
          </h3>
          <p className={`mt-3 max-w-3xl text-pretty text-ink-muted ${HOME.bodySm}`}>
            An agent that sounds good on the demo call and loses a detail on the fortieth
            one is the ordinary failure of this whole category. These are the calls it is
            put through. We publish no score for them, because a number we cannot show you
            the working for is worth nothing.
          </p>
          <ul className="mt-6 flex flex-wrap gap-2.5">
            {TESTED_SCENARIOS.map((scenario) => (
              <li
                key={scenario}
                className="flex items-center gap-2 rounded-full border border-line bg-app/60 px-4 py-2 text-sm font-medium text-ink-muted"
              >
                <Check aria-hidden className="h-4 w-4 text-brand-strong dark:text-brand-bright" />
                {scenario}
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={0.3}>
          <p className={`mt-8 text-ink-muted ${HOME.bodySm}`}>
            The whole of it is written down:{" "}
            <Link href="/legal" className={INLINE_LINK}>
              our legal and compliance pages
            </Link>
            .
          </p>
        </Reveal>
      </Band>
    </Chapter>
  );
}

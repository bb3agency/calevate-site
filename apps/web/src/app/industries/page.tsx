import type { Metadata } from "next";
import Link from "next/link";

import { Check } from "lucide-react";

import {
  CARD,
  ClosingCta,
  Eyebrow,
  INLINE_LINK,
  MarketingPage,
  PageIntro,
  SECTION,
  SHELL,
} from "@/components/marketing/pageShell";
import { INDUSTRIES } from "@/lib/marketing/industries";

/**
 * `/industries` — the four trades the product ships starting points for, at full length.
 *
 * The homepage shows these as tabs because a first-time visitor needs to see that their
 * trade is one of them and move on. This page is for the reader who has found their trade
 * and wants the whole of it: the problem in their own words, what the agent asks, what
 * they receive, what a business like theirs typically sets up, and — stated on every one
 * of the four rather than implied by silence — whether a suite of test calls exists for it
 * yet.
 *
 * ALL FOUR ARE WRITTEN TO THE SAME DEPTH, which is the founder's decision of 5 Sep 2026
 * and is enforced by the shape of the data: `lib/marketing/industries.ts` gives every
 * vertical the same fields, so a section cannot quietly grow richer than its neighbours
 * without the others gaining the same field. Clinics leads because it leads `scripts/
 * seed.py`; it gets no default styling and no editorial promotion for it.
 *
 * The content rules are in that module's header. The one worth repeating here: `fields`
 * is the seed's own labels in the seed's own order, diffed against `scripts/seed.py` by
 * `publicLanding.test.tsx`, because this list's whole value to a buyer is that it is the
 * actual first screen of their agent.
 */
export const metadata: Metadata = {
  title: "Industries — Calevate",
  description:
    "What a Calevate agent asks, and what the owner receives, for clinics, property " +
    "offices, insurance advisors and coaching centres in Andhra Pradesh and Telangana.",
};

export default function IndustriesPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Industries"
        title="It asks the questions your trade actually asks"
        lede="A clinic needs to know what hurts and how soon. A property office needs a budget and an area. These are the field lists a new agent starts from — and then you change them, because the columns are yours rather than ours."
      >
        <nav aria-label="On this page" className="mt-8">
          <ul className="flex flex-wrap gap-2">
            {INDUSTRIES.map((industry) => (
              <li key={industry.id}>
                <Link
                  href={`#${industry.id}`}
                  className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink-muted transition-colors hover:border-brand/50 hover:text-ink touch:py-2.5"
                >
                  <industry.icon aria-hidden className="h-4 w-4" />
                  {industry.name}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </PageIntro>

      {INDUSTRIES.map((industry, index) => (
        <section
          key={industry.id}
          id={industry.id}
          className={
            "scroll-mt-20 border-t border-line " + (index % 2 === 1 ? "bg-surface/40" : "")
          }
        >
          <div className={`${SHELL} ${SECTION}`}>
            <div className="flex items-start gap-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <industry.icon aria-hidden className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <Eyebrow index={String(index + 1).padStart(2, "0")}>{industry.name}</Eyebrow>
                <h2 className="mt-3 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
                  {industry.problem}
                </h2>
              </div>
            </div>

            <div className="mt-10 grid gap-4 lg:grid-cols-2">
              <div className={CARD}>
                <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                  What it asks the caller
                </h3>
                <p className="mt-3 text-lg text-pretty text-ink">“{industry.asks}”</p>

                <h3 className="mt-8 text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                  The questions a new agent starts with
                </h3>
                <ul data-seed-fields className="mt-3 flex flex-wrap gap-2">
                  {industry.fields.map((field) => (
                    <li
                      key={field}
                      className="rounded-full border border-line bg-app/60 px-3 py-1 text-xs font-medium text-ink-muted"
                    >
                      {field}
                    </li>
                  ))}
                </ul>
                <p className="mt-4 text-sm text-ink-faint">
                  You change these. They are a starting point, not a schema you are stuck
                  with — the columns in your leads list are whatever you said you needed to
                  know.
                </p>
              </div>

              <div className="grid gap-4">
                <div className="rounded-2xl border border-brand/40 bg-brand-soft/30 p-5 sm:p-6 dark:bg-brand-strong/10">
                  <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                    What you receive
                  </h3>
                  <ul className="mt-3 flex flex-wrap gap-2">
                    {industry.result.map((chip) => (
                      <li
                        key={chip}
                        className="rounded-lg bg-surface px-3 py-1.5 text-sm font-semibold text-brand-strong dark:text-brand-bright"
                      >
                        {chip}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-5 border-t border-brand/30 pt-4 text-base text-pretty text-ink">
                    {industry.advantage}
                  </p>
                  <p className="mt-3 text-xs text-ink-faint">
                    An illustration of one lead. Nobody in it is a customer of ours.
                  </p>
                </div>

                <div className={CARD}>
                  <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                    What a business like yours sets up
                  </h3>
                  <ul className="mt-3 space-y-2.5">
                    {industry.typical.map((line) => (
                      <li
                        key={line}
                        className="flex items-start gap-2.5 text-sm text-pretty text-ink-muted"
                      >
                        <span
                          aria-hidden
                          className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                        >
                          <Check className="h-3 w-3" />
                        </span>
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            {/* Stated on all four, in both directions. Only `cl_*` and `re_*` cases exist
                in `tests/fixtures/golden_transcripts.json`, so exactly two verticals may
                make the stronger claim and the other two must say plainly that their test
                calls are not written. */}
            <p className="mt-6 flex items-start gap-2.5 text-sm text-ink-faint">
              <span
                aria-hidden
                className={
                  "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full " +
                  (industry.suite ? "bg-brand-bright" : "bg-ink-faint")
                }
              />
              {industry.suite
                ? "Built against first, with its own suite of test calls behind it."
                : "The field list ships; the test calls for it are still being written."}
            </p>
          </div>
        </section>
      ))}

      <section className="border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Not one of these four?
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Nothing is locked to a line of work. The four above have a starting list because
            somebody wrote one; for any other trade you write the list of things the agent
            has to find out, and that is the whole difference. A salon, a car dealership, a
            gym and a chartered accountant all set up the same way.
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            What the agent can do with those answers is the same in every trade —{" "}
            <Link href="/solutions" className={INLINE_LINK}>
              the six jobs
            </Link>{" "}
            do not change.
          </p>
        </div>
      </section>

      <ClosingCta line="Tell us what your callers ring about" />
    </MarketingPage>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

import { Check } from "lucide-react";

import { publicPageMetadata } from "@/lib/seo/metadata";

import { HOME } from "@/components/marketing/home/band";
import { MockStage } from "@/components/marketing/home/mockups/stage";
import { IndustryCallMock } from "@/components/marketing/industries/industryCall";
import { Reveal } from "@/components/marketing/motion";
import {
  ClosingCta,
  Eyebrow,
  INLINE_LINK,
  MarketingPage,
  PageIntro,
  PILL_LINK,
  SHELL,
} from "@/components/marketing/pageShell";
import { INDUSTRIES } from "@/lib/marketing/industries";

/**
 * `/industries` — the four trades the product ships starting points for, each shown as
 * one opened call: what the caller said, what the agent wrote down in that trade's own
 * columns, and what the owner is left holding.
 *
 * The homepage shows these as tabs because a first-time visitor needs to see that their
 * trade is one of them and move on. This page is for the reader who has found their trade
 * and wants to see the agent work in it.
 *
 * ALL FOUR ARE WRITTEN TO THE SAME DEPTH, which is the founder's decision of 5 Sep 2026
 * and is enforced by the shape of the data: `lib/marketing/industries.ts` gives every
 * vertical the same fields, and `industries/industryCall.tsx` gives every vertical one call
 * of the same shape. Clinics leads because it leads `scripts/seed.py`; it gets no default
 * styling and no editorial promotion for it.
 *
 * `fields` is the seed's own labels in the seed's own order, rendered as the
 * `data-seed-fields` list and diffed against `scripts/seed.py` by `publicLanding.test.tsx`;
 * the mockup's "Captured details" use the same labels (`tests/industryMockups.test.ts`).
 *
 * The page may not repeat the homepage band's lede (UX-DOCTRINE §5): the intro keeps only
 * the half this page needs.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/industries",
  title: "Industries — Calevate",
  description:
    "What a Calevate agent asks, and what the owner receives, for clinics, property " +
    "offices, insurance advisors and coaching centres in Andhra Pradesh and Telangana.",
});

export default function IndustriesPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Industries"
        title="It asks the questions your trade actually asks"
        lede="These are the field lists a new agent starts from. Then you change them — the columns are yours rather than ours."
      >
        <nav aria-label="On this page" className="mt-8">
          <ul className="flex flex-wrap gap-2">
            {INDUSTRIES.map((industry) => (
              <li key={industry.id}>
                <Link href={`#${industry.id}`} className={PILL_LINK}>
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
            "scroll-mt-20 border-t border-line " + (index % 2 === 1 ? "bg-surface" : "")
          }
        >
          <div className={`${SHELL} ${HOME.chapter}`}>
            <Reveal>
              <Eyebrow index={String(index + 1).padStart(2, "0")}>{industry.name}</Eyebrow>
              <h2 className="mt-5 max-w-4xl text-[1.875rem] leading-[1.12] font-semibold tracking-tight text-balance text-ink sm:text-[2.5rem] sm:leading-[1.08]">
                {industry.problem}
              </h2>
            </Reveal>

            <div className="mt-10 grid grid-cols-1 items-start gap-8 sm:mt-14 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)] lg:gap-12">
              <div className="min-w-0">
                <MockStage
                  label={`Illustration of one ${industry.name.toLowerCase()} call: the conversation, the details the agent wrote down in this trade's own columns, and the lead it left.`}
                >
                  <IndustryCallMock id={industry.id} />
                </MockStage>
                <p className="mt-4 text-sm text-pretty text-ink-muted">
                  An illustration of one lead. Nobody in it is a customer of ours.
                </p>
              </div>

              <div className="flex min-w-0 flex-col gap-8">
                <Reveal>
                  <h3 className="text-base font-semibold text-ink">What it asks the caller</h3>
                  <p className="mt-2 text-lg text-pretty text-ink sm:text-xl">
                    “{industry.asks}”
                  </p>
                </Reveal>

                <Reveal>
                  <h3 className="text-base font-semibold text-ink">
                    The questions a new agent starts with
                  </h3>
                  <ul data-seed-fields className="mt-3 flex flex-wrap gap-2">
                    {industry.fields.map((field) => (
                      <li
                        key={field}
                        className="rounded-full border border-line bg-surface px-3 py-1 text-sm font-medium text-ink-muted"
                      >
                        {field}
                      </li>
                    ))}
                  </ul>
                </Reveal>

                {/* `-muted`, not `-faint`, on the brand tint: `--text-faint` is held to
                    4.5:1 against `--surface` and `--app` only (`tests/contrastTokens.
                    test.ts`), and axe in a real Chromium reported it as a 1.4.3 failure
                    on this tint. */}
                <Reveal
                  as="section"
                  className="rounded-2xl border border-brand/40 bg-brand-soft/30 p-5 sm:p-6 dark:bg-brand-strong/10"
                >
                  <h3 className="text-base font-semibold text-ink">What you receive</h3>
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
                </Reveal>

                <Reveal>
                  <h3 className="text-base font-semibold text-ink">
                    What a business like yours sets up
                  </h3>
                  <ul className="mt-3 space-y-2.5">
                    {industry.typical.map((line) => (
                      <li
                        key={line}
                        className="flex items-start gap-2.5 text-base text-pretty text-ink-muted"
                      >
                        <Check
                          aria-hidden
                          className="mt-1 h-4 w-4 shrink-0 text-brand-strong"
                          strokeWidth={2.5}
                        />
                        {line}
                      </li>
                    ))}
                  </ul>
                </Reveal>

                {/* Stated on all four, in both directions. Only `cl_*` and `re_*` cases
                    exist in `tests/fixtures/golden_transcripts.json`, so exactly two
                    verticals may make the stronger claim and the other two must say
                    plainly that their test calls are not written. */}
                <p className="flex items-start gap-2.5 border-t border-line pt-5 text-sm text-ink-muted">
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
            </div>
          </div>
        </section>
      ))}

      <section className="border-t border-line">
        <div className={`${SHELL} ${HOME.chapter}`}>
          <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl lg:text-4xl">
            Not one of these four?
          </h2>
          <p className="mt-4 max-w-2xl text-lg text-pretty text-ink-muted">
            Nothing is locked to a line of work. For any other trade you write the list of
            things the agent has to find out, and that is the whole difference.
          </p>
          <p className="mt-4 max-w-2xl text-lg text-pretty text-ink-muted">
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

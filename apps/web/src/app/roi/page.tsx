import type { Metadata } from "next";

import { publicPageMetadata } from "@/lib/seo/metadata";

import { fetchPublicRateCard, tierLabel } from "@/lib/api/rateCard";
import Link from "next/link";

import { ArrowRight } from "lucide-react";

import { Reveal } from "@/components/marketing/motion";
import { RoiConsoleMock } from "@/components/marketing/roi/consoleMockups";
import {
  ClosingCta,
  Eyebrow,
  INLINE_LINK,
  MarketingPage,
  PageIntro,
  SECTION,
  SHELL,
} from "@/components/marketing/pageShell";
import { RoiCalculator } from "@/components/marketing/roiCalculator";

/**
 * `/roi` — the calculator, with the working one click away and nothing said twice.
 *
 * ## ONE CALCULATOR, NOT TWO
 *
 * `RoiCalculator` is imported, not forked. Two implementations of an arithmetic argument is
 * the worst possible instance of CLAUDE.md's "one way per problem" rule: the copies would
 * agree on the day they were written and disagree by the time anybody noticed, and the
 * disagreement would be about money on a public page. `lib/roi.ts` holds the model; both
 * pages render the same component over it, and `tests/roi.test.ts` scores the model itself.
 *
 * ## THE METHODOLOGY IS THE CALCULATOR'S OWN DISCLOSURE, NOT A SECOND COPY ON THE PAGE
 *
 * This page used to restate the whole model in a seven-row `<dl>` under "The working" —
 * the Calevate side, headcount, loaded cost, what is left out, hours covered, the
 * two-stage mode and rounding. Every one of those is already written, at greater length
 * and with the live figures in it, inside `RoiCalculator`'s own "How we calculate this,
 * and where the numbers come from" disclosure, one screen above it. That is UX-DOCTRINE
 * §5's "two spellings of one fact is a defect" on a public page, and the duplicate was
 * ~490 words of the ~1,190 this page rendered. It is deleted rather than trimmed: the
 * disclosure is on this page, closed, one click away, and nothing was lost.
 *
 * The one sentence that did NOT survive as a duplicate is the benchmark caveat — the
 * calculator carries it inside two closed disclosures, so it moved UP, verbatim, into the
 * calculator section's own intro where a reader meets it without opening anything.
 *
 * ## The honesty rules this page inherits
 *
 * - **No borrowed conversion statistic.** Every figure this play is usually sold with
 *   traces to a source this repository could not read (hard rule 11;
 *   `docs/POSITIONING-QUALIFICATION-LAYER.md` names each one and why it was refused).
 * - **The benchmarks are ILLUSTRATIVE and adjustable**, and are labelled so in the tool.
 *   They are relayed industry figures for the telecalling role, not measurements we took.
 * - **The one real price is ours**, and it is now a CARD rather than a number: the
 *   six-rung prepaid catalogue with a ₹/min for each of the two voices
 *   (`apps/api/billing/credit_packs.py::PACK_CATALOGUE`, D-547), fetched here at request
 *   time and used as the Calevate side of the comparison. `self_serve_inr_per_min` no
 *   longer prices it. It is published because it is real, and it is a self-serve rate
 *   rather than a quote —
 *   `/pricing` explains why the managed number is a conversation.
 *
 * ## The page around the calculator
 *
 * The calculator is not edited here (the homepage renders the same component). This page
 * adds the frame around it: the intro names the three inputs and the two monthly totals by
 * the calculator's own labels, so a reader knows what they will type and what comes back
 * before they scroll (inputs a buyer can answer in seconds, results that can be traced);
 * and a console mockup after it shows where those minutes and leads live once the product
 * runs. The mockup draws no rupee amount — the calculator's figures are the only priced
 * ones here.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/roi",
  title: "ROI — Calevate",
  description:
    "Compare Calevate against hiring telecallers with your own numbers, with every " +
    "assumption on both sides exposed — including the branches where the comparison " +
    "goes against us.",
});

/** The three branches in which the tool argues against us. */
const AGAINST: readonly { term: string; detail: string }[] = [
  {
    term: "When the running costs come out close",
    detail:
      "At low volume a small team can match the running cost, and the verdict says so " +
      "rather than rounding in our favour.",
  },
  {
    term: "When the call is a sales conversation",
    detail:
      "Past about four minutes, the alternative to a closer is not a cheaper closer. The " +
      "tool names that rather than quietly showing a losing number, and points at the " +
      "comparison that is like-for-like.",
  },
  {
    term: "When the two-stage funnel costs more",
    detail:
      "Set the qualified share to everyone and a first call has nothing to filter out. " +
      "The tool prints that it costs MORE a month, not less.",
  },
];

/** The calculator's three primary inputs and its two monthly totals, by its own labels. */
const INPUTS: readonly string[] = [
  "Calls a day",
  "Average call length",
  "What one telecaller costs you a month",
];
const OUTPUTS: readonly string[] = ["Telecallers, a month", "Calevate, a month"];

const H2 =
  "mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl lg:text-4xl";

export default async function RoiPage() {
  // Same fetch as the homepage and for the same reason (D-545). Deliberately NOT hoisted
  // into a shared helper: it is one awaited call, and a wrapper whose whole body is
  // `await fetchPublicRateCard()` would be indirection with nothing inside it.
  const rateCard = await fetchPublicRateCard();
  // The voice an agent can be put on today, named by the card (the calculator opens there).
  const offeredVoice = rateCard === null ? null : tierLabel(rateCard, "studio");

  return (
    <MarketingPage>
      <PageIntro
        eyebrow="ROI"
        title="Do the maths against hiring, with your own numbers"
        lede="Three numbers you already know, and every other assumption open to inspection."
      >
        {/* What goes in and what comes out, before the reader meets a slider. */}
        <div className="mt-8 grid max-w-4xl grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center sm:gap-4">
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5">
            <span className="text-xs font-medium text-ink-muted">You type</span>
            <ul className="mt-2 flex flex-wrap gap-2">
              {INPUTS.map((input) => (
                <li
                  key={input}
                  className="rounded-md bg-app px-2.5 py-1 text-sm font-medium text-ink ring-1 ring-line"
                >
                  {input}
                </li>
              ))}
            </ul>
          </div>
          <ArrowRight
            aria-hidden
            className="mx-auto h-5 w-5 rotate-90 text-brand-strong sm:rotate-0"
          />
          <div className="rounded-2xl border border-brand/40 bg-brand-soft/50 p-4 shadow-card sm:p-5">
            <span className="text-xs font-medium text-brand-strong">You get, side by side</span>
            <ul className="mt-2 flex flex-wrap gap-2">
              {OUTPUTS.map((output) => (
                <li
                  key={output}
                  className="rounded-md bg-surface px-2.5 py-1 text-sm font-semibold text-ink ring-1 ring-brand/30"
                >
                  {output}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </PageIntro>

      {/* --- The calculator ------------------------------------------------------ */}
      <section id="calculator" className="scroll-mt-20">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">The comparison</Eyebrow>
          <h2 className={H2}>Put your own volumes in</h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Nothing here is submitted anywhere — the page makes no request and stores
            nothing. The defaults are relayed industry benchmarks for the role in Andhra
            Pradesh and Telangana — not measurements we have taken, and not promises — and
            every one of them is a slider you can move to your own figures.
          </p>
          <RoiCalculator rateCard={rateCard} />
        </div>
      </section>

      {/* --- Where it argues against us ------------------------------------------ */}
      <section id="against" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="02">Where it goes against us</Eyebrow>
            <h2 className={H2}>A calculator that cannot lose is a brochure</h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Three branches in this tool say plainly that we are not the answer, on ordinary
              inputs.
            </p>
          </Reveal>
          {/* One surface in three cells, not three cards (UX-DOCTRINE §1). */}
          <Reveal className="mt-10 overflow-hidden rounded-2xl border border-line sm:mt-12">
            <dl className="grid grid-cols-1 gap-px bg-line lg:grid-cols-3">
              {AGAINST.map(({ term, detail }, index) => (
                <div key={term} className="bg-surface p-5 sm:p-8">
                  <span aria-hidden className="font-mono text-xs text-ink-faint">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <dt className="mt-3 text-[17px] font-semibold text-balance text-ink sm:text-xl">
                    {term}
                  </dt>
                  <dd className="mt-2 text-sm text-pretty text-ink-muted sm:text-base">{detail}</dd>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>
      </section>

      {/* --- What it looks like once it runs ------------------------------------- */}
      <section id="console" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="03">Once it is running</Eyebrow>
            <h2 className={H2}>The minutes on one screen, the leads they produced on the next</h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              The calculator works from your estimates. In the console the same month is
              counted as it happens: every billed minute on the Usage tab, and every caller as
              a lead your team can work through.
            </p>
          </Reveal>
          <div className="mt-10 rounded-2xl bg-[radial-gradient(circle_at_50%_0%,var(--brand-soft),transparent_70%)] p-3 sm:mt-12 sm:p-6">
            <RoiConsoleMock voiceLabel={offeredVoice} />
          </div>
        </div>
      </section>

      {/* --- What it cannot price ------------------------------------------------ */}
      <section className="border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="04">What no calculator can price</Eyebrow>
            <h2 className={H2}>The rupees are the smaller half of the answer</h2>
          </Reveal>
          <div className="mt-6 grid max-w-5xl grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-10">
            <p className="text-base text-pretty text-ink-muted">
              What this tool cannot put a number on is the call nobody answered, and the
              hours your salespeople spend finding out who was never going to buy —{" "}
              <Link href="/why-calevate" className={INLINE_LINK}>
                the part a headcount comparison cannot see
              </Link>
              .
            </p>
            <p className="text-base text-pretty text-ink-muted">
              The figure this tool uses for Calevate is our published list rate, the same for
              every client — see{" "}
              <Link href="/pricing" className={INLINE_LINK}>
                the pricing page
              </Link>
              .
            </p>
          </div>
        </div>
      </section>

      <ClosingCta line="Worth a conversation?" />
    </MarketingPage>
  );
}

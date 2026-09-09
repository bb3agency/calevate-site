import type { Metadata } from "next";
import { fetchPublicRateCard } from "@/lib/api/rateCard";
import Link from "next/link";

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
 *   time and used as the Calevate side of the comparison. ⚠ This bullet used to cite
 *   `self_serve_inr_per_min` as the price; that setting no longer prices this card. It is
 *   published because it is real, and it is a self-serve rate rather than a quote —
 *   `/pricing` explains why the managed number is a conversation.
 */
export const metadata: Metadata = {
  title: "ROI — Calevate",
  description:
    "Compare Calevate against hiring telecallers with your own numbers, with every " +
    "assumption on both sides exposed — including the branches where the comparison " +
    "goes against us.",
};

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

export default async function RoiPage() {
  // Same fetch as the homepage and for the same reason (D-545). Deliberately NOT hoisted
  // into a shared helper: it is one awaited call, and a wrapper whose whole body is
  // `await fetchPublicRateCard()` would be indirection with nothing inside it.
  const rateCard = await fetchPublicRateCard();

  return (
    <MarketingPage>
      <PageIntro
        eyebrow="ROI"
        title="Do the maths against hiring, with your own numbers"
        lede="Three numbers you already know, and every other assumption open to inspection."
      />

      {/* --- The calculator ------------------------------------------------------ */}
      <section id="calculator" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">The comparison</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Put your own volumes in
          </h2>
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
      <section id="against" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">Where it goes against us</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            A calculator that cannot lose is a brochure
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Three branches in this tool say plainly that we are not the answer, on ordinary
            inputs.
          </p>
          <dl className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
            {AGAINST.map(({ term, detail }) => (
              <div
                key={term}
                className="rounded-2xl border border-line bg-surface p-5 sm:p-6"
              >
                <dt className="text-[17px] font-semibold text-balance text-ink">{term}</dt>
                <dd className="mt-2 text-sm text-pretty text-ink-muted">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* --- What it cannot price ------------------------------------------------ */}
      <section className="border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">What no calculator can price</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The rupees are the smaller half of the answer
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            What this tool cannot put a number on is the call nobody answered, and the
            hours your salespeople spend finding out who was never going to buy —{" "}
            <Link href="/why-calevate" className={INLINE_LINK}>
              the part a headcount comparison cannot see
            </Link>
            .
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            The figure this tool uses for Calevate is our published self-serve rate. What a
            managed account pays is agreed with you — see{" "}
            <Link href="/pricing" className={INLINE_LINK}>
              the pricing page
            </Link>
            .
          </p>
        </div>
      </section>

      <ClosingCta line="Worth a conversation?" />
    </MarketingPage>
  );
}

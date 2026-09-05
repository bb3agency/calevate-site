import type { Metadata } from "next";
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
 * `/roi` — the same calculator, and the methodology the homepage now hides.
 *
 * ## ONE CALCULATOR, NOT TWO
 *
 * `RoiCalculator` is imported, not forked. Two implementations of an arithmetic argument is
 * the worst possible instance of CLAUDE.md's "one way per problem" rule: the copies would
 * agree on the day they were written and disagree by the time anybody noticed, and the
 * disagreement would be about money on a public page. `lib/roi.ts` holds the model; both
 * pages render the same component over it, and `tests/roi.test.ts` scores the model itself.
 *
 * ## What this page adds that the homepage deliberately does not
 *
 * The homepage asks three questions and puts everything else behind "Adjust assumptions",
 * because a visitor who has not yet agreed they have a problem will not do a spreadsheet
 * exercise. This page is for the reader who has, and it is where the assumptions belong AT
 * FULL LENGTH: where each benchmark came from, what each one does to the answer, and the
 * three branches in which the tool says we lose.
 *
 * ## The honesty rules this page inherits
 *
 * - **No borrowed conversion statistic.** Every figure this play is usually sold with
 *   traces to a source this repository could not read (hard rule 11;
 *   `docs/POSITIONING-QUALIFICATION-LAYER.md` names each one and why it was refused).
 * - **The benchmarks are ILLUSTRATIVE and adjustable**, and are labelled so in the tool.
 *   They are relayed industry figures for the telecalling role, not measurements we took.
 * - **The one real price is ours**: `self_serve_inr_per_min`
 *   (`packages/shared/src/calevate_shared/config.py:1284`), which the calculator uses as
 *   the Calevate side of the comparison. It is published because it is real, and it is a
 *   self-serve rate rather than a quote — `/pricing` explains why the managed number is a
 *   conversation.
 */
export const metadata: Metadata = {
  title: "ROI — Calevate",
  description:
    "Compare Calevate against hiring telecallers with your own numbers, with every " +
    "assumption on both sides exposed — including the branches where the comparison " +
    "goes against us.",
};

/** The methodology, at the length the homepage moves behind a disclosure. */
const METHOD: readonly { term: string; detail: string }[] = [
  {
    term: "The Calevate side",
    detail:
      "Calls a day × average call length × working days × our published self-serve rate. " +
      "That is the whole of it: usage, at a rate you can read. It does not change when you " +
      "widen the hours the line must be answered, because an agent costs the same at 2am " +
      "as at 2pm.",
  },
  {
    term: "How many telecallers the same work needs",
    detail:
      "Calls a day ÷ the calls one agent handles a day, rounded up — and once calls run " +
      "long, talk-time rather than dial count becomes the real limit, so the tool switches " +
      "to whichever of the two binds first. Both are sliders, because a business that runs " +
      "four-minute calls and one that runs ninety-second calls do not staff alike.",
  },
  {
    term: "What a telecaller actually costs",
    detail:
      "The advertised base is what a job ad shows. The loaded figure adds PF/ESI, " +
      "on-target incentives, a share of a supervisor, desk, power, phone and software, and " +
      "the ramp before somebody is productive. The whole reason the comparison is worth " +
      "doing is that the base hides most of the cost.",
  },
  {
    term: "Attrition, folded in monthly",
    detail:
      "Replacement cost × yearly attrition ÷ 12. Hiring and re-training is a real, " +
      "recurring line in this role rather than an occasional event, so it is priced as one " +
      "— and both numbers are yours to change.",
  },
  {
    term: "Hours covered",
    detail:
      "A person works one shift of about nine hours. Answering into the evening or around " +
      "the clock means staffing two or three, and every staffed shift needs at least one " +
      "person on the phone even on a quiet night. The tool spreads your call volume evenly " +
      "across the shifts you choose, which is the assumption kindest to the human side.",
  },
  {
    term: "The two-stage comparison",
    detail:
      "The other mode, and the honest one once a call is a sales conversation rather than " +
      "an enquiry being written down. One side is your people working the whole list at the " +
      "full conversation length; the other is Calevate holding a short first call with " +
      "everyone and your people holding the real conversation only with the share that came " +
      "back interested. The two numbers it needs — how much of your list is worth a real " +
      "conversation, and how long the first call runs — are facts about YOUR list that " +
      "nobody can tell you from outside, which is exactly why they are sliders.",
  },
  {
    term: "Rounding",
    detail:
      "Everything is computed in whole paise and rounded once at the end, so the rupee " +
      "figures add up exactly rather than drifting by a paisa per line.",
  },
];

/** The three branches in which the tool argues against us. */
const AGAINST: readonly { term: string; detail: string }[] = [
  {
    term: "When the running costs come out close",
    detail:
      "At low volume a small team can match the running cost, and the verdict says so in " +
      "those words rather than rounding in our favour. The argument then is about " +
      "capability — hours, concurrency, consistency — and the page says that too.",
  },
  {
    term: "When the call is a sales conversation",
    detail:
      "Past about four minutes, comparing Calevate head-to-head with a telecaller compares " +
      "two things nobody was choosing between: the alternative to a closer is not a cheaper " +
      "closer. The tool names that rather than quietly showing a losing number, and points " +
      "at the comparison that is like-for-like.",
  },
  {
    term: "When the two-stage funnel costs more",
    detail:
      "Set the qualified share to everyone and there is nothing for a first call to filter " +
      "out, so it is an extra call on top of the same team. The tool prints that it costs " +
      "MORE a month, not less, and says that if that is really your list, your team should " +
      "keep calling it.",
  },
];

export default function RoiPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="ROI"
        title="Do the maths against hiring, with your own numbers"
        lede="Three numbers you already know, and every other assumption open to inspection. This is the same tool the homepage carries, with the working shown rather than folded away."
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
            nothing. Change any input and every figure recomputes in front of you.
          </p>
          <RoiCalculator />
        </div>
      </section>

      {/* --- Methodology --------------------------------------------------------- */}
      <section id="method" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">The working</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Every line of the arithmetic, and where each number comes from
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            The telecaller side is built to be believed rather than to win. The defaults are
            relayed industry benchmarks for the role in Andhra Pradesh and Telangana — not
            measurements we have taken, and not promises — and every one of them is a slider
            you can move to your own figures.
          </p>
          <dl className="mt-10 divide-y divide-line border-y border-line sm:mt-12">
            {METHOD.map(({ term, detail }) => (
              <div key={term} className="grid gap-2 py-5 sm:grid-cols-[16rem_1fr] sm:gap-8">
                <dt className="text-[15px] font-semibold text-ink">{term}</dt>
                <dd className="max-w-2xl text-[15px] text-pretty text-ink-muted">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* --- Where it argues against us ------------------------------------------ */}
      <section id="against" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">Where it goes against us</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            A calculator that cannot lose is a brochure
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Three branches in this tool say plainly that we are not the answer. They are
            reachable with ordinary inputs, they are not hidden behind an advanced toggle,
            and they are covered by tests so that a later edit cannot quietly remove them.
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
          <Eyebrow index="04">What no calculator can price</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The rupees are the smaller half of the answer
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            What this tool cannot put a number on is the call nobody answered, because
            nobody recorded it — and the hours your salespeople spend finding out who was
            never going to buy. The first is the reason this product exists; the second is{" "}
            <Link href="/why-calevate" className={INLINE_LINK}>
              the part a headcount comparison cannot see
            </Link>
            .
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            The figure this tool uses for Calevate is our published self-serve rate. What a
            managed account pays is agreed with you —{" "}
            <Link href="/pricing" className={INLINE_LINK}>
              the pricing page
            </Link>{" "}
            explains the shape of that and why no number is printed on it.
          </p>
        </div>
      </section>

      <ClosingCta line="Worth a conversation?" />
    </MarketingPage>
  );
}

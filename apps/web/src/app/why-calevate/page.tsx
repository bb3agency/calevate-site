import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";


import { publicPageMetadata } from "@/lib/seo/metadata";

import { Band, Chapter, HOME } from "@/components/marketing/home/band";
import { AnsweringVignette, AnswersVignette } from "@/components/marketing/home/mockups/capabilityVignettes";
import { FollowUpMini, QualifiedMini } from "@/components/marketing/home/mockups/featureMockups";
import { MockStage } from "@/components/marketing/home/mockups/stage";
import { FieldListMock } from "@/components/marketing/home/mockups/stepMockups";
import { ClosingCta, INLINE_LINK, MarketingPage } from "@/components/marketing/pageShell";
import {
  BusyHourMock,
  DialRulesMock,
  RecordedVsSortedMock,
  WhyHeroMock,
} from "@/components/marketing/why/mockups";
import { PageHero } from "@/components/marketing/why/pageHero";

/**
 * `/why-calevate` — the case, including the parts that argue against us.
 *
 * ## Two arguments, in the order a buyer actually raises them
 *
 * 1. **Why not just hire somebody?** The answer is not "we are cheaper" — the calculator
 *    on `/roi` is honest enough to say when we are not. It is the five properties a
 *    headcount cannot have at any salary.
 * 2. **Does this replace my staff?** No, and the section says why in the founder's own
 *    framing: it is the layer that makes a salesperson more productive, not a salesperson.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/why-calevate",
  title: "Why Calevate — Calevate",
  description:
    "What a headcount comparison cannot price, and why an AI layer does not replace " +
    "your sales team.",
});

/**
 * The five properties a headcount cannot have. Each is a behaviour, not an adjective, and
 * each card's picture is the console screen where that behaviour shows. `span` varies so the
 * grid reads as five different things rather than one card five times. Every cell names its
 * span at BOTH grid breakpoints (two columns from `sm`, six from `lg`), so no cell depends on
 * one breakpoint's class winning over another's in the stylesheet.
 */
const BEYOND: readonly { title: string; body: string; figure: ReactNode; span: string }[] = [
  {
    figure: <AnsweringVignette />,
    span: "col-span-1 sm:col-span-1 lg:col-span-3",
    title: "Your phone doesn’t clock out",
    body:
      "Evenings, Sundays and festival days are answered at the same rate as a Tuesday " +
      "morning, because an agent runs at every hour unless you tell it otherwise. A human " +
      "rota for the same coverage is two or three shifts, and every staffed shift needs " +
      "somebody on the phone even on a quiet night.",
  },
  {
    figure: <BusyHourMock />,
    span: "col-span-1 sm:col-span-1 lg:col-span-3",
    title: "A busy hour is not a queue",
    body:
      "Fifty callers at 11am are fifty answered calls rather than fifty people waiting " +
      "behind three desks. Peak-hour capacity is the thing a small team cannot buy without " +
      "carrying that headcount through every quiet week as well.",
  },
  {
    figure: <AnswersVignette />,
    span: "col-span-1 sm:col-span-1 lg:col-span-2",
    title: "Nothing to train, and nothing resigns",
    body:
      "No six-week ramp, no re-hiring in four months, no re-teaching the price list to " +
      "somebody new. It is doing the job the day you switch it on and the same job a year " +
      "later.",
  },
  {
    figure: <FieldListMock />,
    span: "col-span-1 sm:col-span-1 lg:col-span-2",
    title: "The same questions, every single call",
    body:
      "The things you said you needed to know get asked whether it is the third call of " +
      "the day or the ninetieth, and they land in the same columns every time. Consistency " +
      "is not a virtue you can ask a tired person for at 7pm.",
  },
  {
    figure: <DialRulesMock />,
    span: "col-span-1 sm:col-span-2 lg:col-span-2",
    title: "The rules on every dial",
    body:
      "Calling hours, do-not-call scrubbing and the honest answer about being an AI are " +
      "enforced on the dispatch path rather than left to a person to remember. A rule that " +
      "depends on memory is a rule that breaks on the busiest day of the year.",
  },
];

/**
 * The qualification argument — the same three shipped surfaces the homepage names, each
 * drawn as the step it is: the first call, the row it leaves, the sorted list.
 */
const QUALIFICATION: readonly { title: string; body: string; figure: ReactNode }[] = [
  {
    figure: <FollowUpMini />,
    title: "Everyone on the list gets the first call",
    body:
      "All of them, in the order they came in. A web enquiry becomes a call without " +
      "waiting for someone to notice it, and the gap between the form and the dial is " +
      "timed on every one.",
  },
  {
    figure: <RecordedVsSortedMock />,
    title: "They come back sorted, not just recorded",
    body:
      "Each one lands as a row, marked contacted, interested or hot. A hot lead alerts " +
      "you while they are still thinking about it.",
  },
  {
    figure: <QualifiedMini />,
    title: "Your people open the day on a shortlist",
    body:
      "Your team talks to people who already said yes. Nobody spends the morning finding " +
      "out who didn’t.",
  },
];

export default function WhyCalevatePage() {
  return (
    <MarketingPage>
      <PageHero
        label="Why Calevate"
        title="The case, including the parts that argue against us"
        lede="Three questions decide this: why not just hire somebody, does it replace my staff, and why should I believe a word of it. The third one is answered by what this website refuses to say."
        product={
          <MockStage label="Illustration of one call: the agent's first line says it is an AI assistant and that the call is recorded, the details the caller gave land as a lead, and a running campaign shows the calling-hours and do-not-call rules applied.">
            <WhyHeroMock />
          </MockStage>
        }
      />

      {/* --- Beyond headcount ---------------------------------------------------- */}
      <Chapter tone="app">
        <Band
          id="beyond-headcount"
          eyebrow="Beyond headcount"
          title="Five things a salary cannot buy"
          lede={
            <>
              The cost comparison is on{" "}
              <Link href="/roi" className={INLINE_LINK}>
                the ROI page
              </Link>
              , and it is built to be believed rather than to win — at low volume it will
              tell you the running costs come out close.
            </>
          }
        >
          <div className={`${HOME.contentGap} grid grid-cols-1 ${HOME.itemGap} sm:grid-cols-2 lg:grid-cols-6`}>
            {BEYOND.map(({ title, body, figure, span }) => (
              <section
                key={title}
                className={`flex min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card ${HOME.panelLift} ${span}`}
              >
                <div className="p-5 sm:p-7">
                  <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
                  <p className={`mt-2 max-w-xl text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
                </div>
                {/* The ground takes the rest of the cell and centres its screen, so a short screen
                    in a tall row leaves tinted ground rather than a white gap under the copy. */}
                <MockStage className="flex flex-1 flex-col justify-center border-t border-line bg-app/70 p-4 sm:p-6">
                  {figure}
                </MockStage>
              </section>
            ))}
          </div>
        </Band>
      </Chapter>

      {/* --- Not a replacement --------------------------------------------------- */}
      <Chapter tone="raised">
        <Band
          id="your-team"
          eyebrow="Your team"
          title="Calevate is not your salesperson. It is the layer that makes your salesperson more productive."
          lede="Sales organisations that can afford it already split this job in two: one person works out who is worth talking to, another has the conversation. Calevate is the first half of that split, which is the half nobody enjoys and the half that scales badly with people."
        >
          <ol className={`${HOME.contentGap} grid grid-cols-1 ${HOME.itemGap} lg:grid-cols-3`}>
            {QUALIFICATION.map(({ title, body, figure }, i) => (
              <li
                key={title}
                // Each item spans two rows of the list's grid and shares them (subgrid), so
                // the three screens get one height per row and the numbered copy beneath
                // starts on one line instead of wherever its own screen happened to end.
                className="row-span-2 grid min-w-0 grid-cols-1 grid-rows-subgrid gap-0 overflow-hidden rounded-2xl border border-line bg-app/60 shadow-card"
              >
                <MockStage className="flex flex-col justify-center border-b border-line p-4 sm:p-6">
                  {figure}
                </MockStage>
                <div className="p-5 sm:p-7">
                  <span className="font-mono text-sm font-semibold text-brand-strong dark:text-brand-bright">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className={`mt-1.5 ${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
                  <p className={`mt-2 text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className={`mt-10 max-w-3xl font-semibold text-pretty text-ink ${HOME.body}`}>
            This is not your team replaced. It is the part of their day that was never
            selling.
          </p>
          <p className={`mt-3 text-ink-muted ${HOME.bodySm}`}>
            No conversion statistic appears anywhere on this site.
          </p>
        </Band>
      </Chapter>

      <ClosingCta line="Judge it on the parts you can check" />
    </MarketingPage>
  );
}

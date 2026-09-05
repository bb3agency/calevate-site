import type { Metadata } from "next";
import Link from "next/link";

import {
  Clock3,
  Filter,
  Handshake,
  Infinity as InfinityIcon,
  ListChecks,
  PhoneOutgoing,
  ShieldCheck,
  TrendingDown,
  X,
} from "lucide-react";

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

/**
 * `/why-calevate` — the case, including the parts that argue against us.
 *
 * ## Three arguments, in the order a buyer actually raises them
 *
 * 1. **Why not just hire somebody?** The answer is not "we are cheaper" — the calculator
 *    on `/roi` is honest enough to say when we are not. It is the five properties a
 *    headcount cannot have at any salary.
 * 2. **Does this replace my staff?** No, and the section says why in the founder's own
 *    framing: it is the layer that makes a salesperson more productive, not a salesperson.
 * 3. **Why should I believe any of this?** Because of what is NOT on this website. That
 *    last section is the one that could not be written by a competitor who does not keep
 *    the same rule, and it is the most persuasive thing here precisely because it costs us
 *    something.
 *
 * ## The refusals section is load-bearing and must not be softened
 *
 * Every item in it is a real constraint this repository operates under, and each is
 * checked by something: `publicLanding.test.tsx` bans the price, count, uptime, accuracy
 * and residency shapes on the homepage; D-36 records Telugu extraction quality as
 * UNMEASURED until task #87 scores it; `docs/POSITIONING-QUALIFICATION-LAYER.md` names
 * each conversion statistic that was refused for want of a primary source (hard rule 11).
 * If any of those stops being true, this section changes in the same commit — a page that
 * boasts about a discipline it has quietly dropped is worse than one that never claimed it.
 */
export const metadata: Metadata = {
  title: "Why Calevate — Calevate",
  description:
    "What a headcount comparison cannot price, why an AI layer does not replace your " +
    "sales team, and the claims this company will not make.",
};

/** The five properties a headcount cannot have. Each is a behaviour, not an adjective. */
const BEYOND: readonly { icon: typeof Clock3; title: string; body: string }[] = [
  {
    icon: Clock3,
    title: "Your phone doesn’t clock out",
    body:
      "Evenings, Sundays and festival days are answered at the same rate as a Tuesday " +
      "morning, because an agent runs at every hour unless you tell it otherwise. A human " +
      "rota for the same coverage is two or three shifts, and every staffed shift needs " +
      "somebody on the phone even on a quiet night.",
  },
  {
    icon: InfinityIcon,
    title: "A busy hour is not a queue",
    body:
      "Fifty callers at 11am are fifty answered calls rather than fifty people waiting " +
      "behind three desks. Peak-hour capacity is the thing a small team cannot buy without " +
      "carrying that headcount through every quiet week as well.",
  },
  {
    icon: TrendingDown,
    title: "Nothing to train, and nothing resigns",
    body:
      "No six-week ramp, no re-hiring in four months, no re-teaching the price list to " +
      "somebody new. It is doing the job the day you switch it on and the same job a year " +
      "later. Attrition in this role is real enough that the calculator on /roi treats " +
      "replacement cost as a line of its own.",
  },
  {
    icon: ListChecks,
    title: "The same questions, every single call",
    body:
      "The things you said you needed to know get asked whether it is the third call of " +
      "the day or the ninetieth, and they land in the same columns every time. Consistency " +
      "is not a virtue you can ask a tired person for at 7pm.",
  },
  {
    icon: ShieldCheck,
    title: "The rules on every dial",
    body:
      "Calling hours, do-not-call scrubbing and the honest answer about being an AI are " +
      "enforced on the dispatch path rather than left to a person to remember. A rule that " +
      "depends on memory is a rule that breaks on the busiest day of the year.",
  },
];

/** The qualification argument — the same three shipped surfaces the homepage names. */
const QUALIFICATION: readonly { icon: typeof Filter; title: string; body: string }[] = [
  {
    icon: PhoneOutgoing,
    title: "Everyone on the list gets the first call",
    body:
      "All of them, in the order they came in. A web enquiry becomes a call without " +
      "waiting for someone to notice it, and the gap between the form and the dial is " +
      "timed on every one.",
  },
  {
    icon: Filter,
    title: "They come back sorted, not just recorded",
    body:
      "Each one lands as a row, marked contacted, interested or hot. A hot lead alerts " +
      "you while they are still thinking about it.",
  },
  {
    icon: Handshake,
    title: "Your people open the day on a shortlist",
    body:
      "Your team talks to people who already said yes. Nobody spends the morning finding " +
      "out who didn’t.",
  },
];

/**
 * What is deliberately absent from this website, and why.
 *
 * Each `why` names the constraint rather than the virtue — a reason a reader can check is
 * worth more than a promise about our character.
 */
const REFUSALS: readonly { claim: string; why: string }[] = [
  {
    claim: "“Trusted by hundreds of businesses”",
    why:
      "There is no client in production yet. A customer count, a logo wall, a testimonial " +
      "and a case study would all be fabrications, so this site has none of them and will " +
      "not have one until there is somebody real to name.",
  },
  {
    claim: "“Industry-leading uptime and accuracy”",
    why:
      "Nothing here measures either. The console itself refuses to print a latency figure " +
      "because the column was dropped, and how well the agent understands Telugu is " +
      "recorded internally as unmeasured until somebody scores it properly. A number we " +
      "cannot show you the working for is worth nothing.",
  },
  {
    claim: "“₹X per month, cancel any time”",
    why:
      "Commercial terms are agreed with each client, so a fixed figure here would be a " +
      "quote nobody can honour. What you can have instead is the shape of the bill and a " +
      "calculator you drive with your own numbers.",
  },
  {
    claim: "“Calling within a minute makes you N× more likely to qualify a lead”",
    why:
      "That family of statistics traces back to studies we could not read. Repeating a " +
      "number because everybody repeats it is how a false claim gets into a contract, so " +
      "the argument here is made with arithmetic you supply the inputs for.",
  },
  {
    claim: "“Your data never leaves India”",
    why:
      "It is not true of every leg of a call, and the page that explains where each part " +
      "runs says so in full rather than in a privacy policy nobody reads. A residency " +
      "claim is the first thing a buyer in this market asks for, which is exactly why it " +
      "is the one we will not stretch.",
  },
  {
    claim: "“Hear a sample call”",
    why:
      "There is no recorded sample call. The conversation on the homepage is a written " +
      "illustration and is labelled as one — a button playing audio we do not have would " +
      "be the same defect as a page linking to a route nobody built.",
  },
];

export default function WhyCalevatePage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Why Calevate"
        title="The case, including the parts that argue against us"
        lede="Three questions decide this: why not just hire somebody, does it replace my staff, and why should I believe a word of it. The third one is answered by what this website refuses to say."
      />

      {/* --- 01 Beyond headcount ------------------------------------------------ */}
      <section id="beyond-headcount" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">Beyond headcount</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Five things a salary cannot buy
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            The cost comparison is on{" "}
            <Link href="/roi" className={INLINE_LINK}>
              the ROI page
            </Link>
            , and it is built to be believed rather than to win — at low volume it will tell
            you the running costs come out close. These five are the reason the comparison
            is not the whole argument.
          </p>
          <div className="mt-10 grid gap-4 sm:mt-12 sm:grid-cols-2 lg:grid-cols-3">
            {BEYOND.map(({ icon: Icon, title, body }) => (
              <section key={title} className={CARD}>
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-[17px] font-semibold text-balance text-ink">{title}</h3>
                <p className="mt-2 text-sm text-pretty text-ink-muted">{body}</p>
              </section>
            ))}
          </div>
        </div>
      </section>

      {/* --- 02 Not a replacement ----------------------------------------------- */}
      <section id="your-team" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">Your team</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Calevate is not your salesperson. It is the layer that makes your salesperson
            more productive.
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Sales organisations that can afford it already split this job in two: one person
            works out who is worth talking to, another has the conversation. Calevate is the
            first half of that split, which is the half nobody enjoys and the half that
            scales badly with people. It takes the first call to every enquiry and every
            name on your list, works out who is worth a conversation, and hands your people
            the shortlist.
          </p>
          <div className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
            {QUALIFICATION.map(({ icon: Icon, title, body }) => (
              <section key={title} className={CARD}>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-[17px] font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm text-pretty text-ink-muted">{body}</p>
              </section>
            ))}
          </div>
          <p className="mt-8 max-w-2xl text-base text-pretty text-ink">
            This is not your team replaced. It is the part of their day that was never
            selling. The goal is not to automate your business — it is to automate the parts
            of the phone workflow your team should not be spending their day on.
          </p>
          <p className="mt-4 max-w-2xl text-sm text-ink-faint">
            No conversion statistic appears anywhere on this site. The figures this play is
            usually sold with trace back to sources we could not read, and repeating one
            because it is widely repeated is not the same as knowing it.
          </p>
        </div>
      </section>

      {/* --- 03 What we will not claim ------------------------------------------ */}
      <section id="refusals" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">What we will not claim</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Six sentences you will not find on this website
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Every one of them is standard in this category, and every one of them is
            something we cannot stand behind today. They are absent by rule rather than by
            oversight: the site is tested for their absence, which is a strange thing to
            build unless you mean it.
          </p>
          <dl className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-2">
            {REFUSALS.map(({ claim, why }) => (
              <div key={claim} className={CARD}>
                <dt className="flex items-start gap-2.5 text-[17px] font-semibold text-ink">
                  <X aria-hidden className="mt-1 h-4 w-4 shrink-0 text-ink-faint" />
                  <span className="line-through decoration-ink-faint/60">{claim}</span>
                </dt>
                <dd className="mt-2 text-sm text-pretty text-ink-muted">{why}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-8 max-w-2xl text-base text-pretty text-ink-muted">
            What replaces them is narrower and checkable:{" "}
            <Link href="/solutions" className={INLINE_LINK}>
              what the product does
            </Link>
            ,{" "}
            <Link href="/security" className={INLINE_LINK}>
              where your customers’ data goes
            </Link>{" "}
            and{" "}
            <Link href="/roi" className={INLINE_LINK}>
              arithmetic you drive yourself
            </Link>
            .
          </p>
        </div>
      </section>

      <ClosingCta line="Judge it on the parts you can check" />
    </MarketingPage>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRight } from "lucide-react";

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
import { LEGAL_DOCUMENTS } from "@/lib/legal";

/**
 * `/resources` — where to read next, and what the words mean.
 *
 * ## WHY THIS IS NOT A BLOG, A WHITEPAPER SHELF OR A CASE-STUDY LIBRARY
 *
 * Because there is nothing to put on one. There is no client in production, so there are no
 * case studies; there is no measured benchmark, so there is no whitepaper; and a "Resources"
 * page carrying three placeholder cards is worse than no page at all — it is the empty-stub
 * defect with a nicer border. The founder's decision of 5 Sep 2026 rules the proof section
 * out entirely for the same reason, and that decision binds here.
 *
 * What a first-time buyer in this market genuinely lacks is not content marketing. It is
 * (a) a map of what is worth reading on this site and (b) a plain-language glossary,
 * because this product sits at the intersection of three vocabularies — telecom regulation,
 * CRM software and AI — and a clinic owner has no reason to know any of them. So this page
 * is those two things and nothing else.
 *
 * ## The glossary defines OUR vocabulary, never the law
 *
 * Every entry describes something in this product: a thing a client configures, a state a
 * record can be in, or a control they operate. Where a term is really a REGULATORY one —
 * the registrations outbound calling requires, what the calling-hours rule is grounded in —
 * the entry says what the PRODUCT does about it and points at the legal documents, which
 * are the instruments. A marketing page paraphrasing a TRAI obligation is exactly the
 * unverified claim hard rule 11 exists to stop, and it would be the first thing a
 * regulator's reader found.
 */
export const metadata: Metadata = {
  title: "Resources — Calevate",
  description:
    "Where to start on this site, the published legal documents, and a plain-language " +
    "glossary of the words Calevate uses.",
};

/** The reading order that actually helps somebody deciding. */
const READING: readonly { href: string; title: string; body: string }[] = [
  {
    href: "/solutions",
    title: "What it does, in detail",
    body:
      "The six jobs an agent takes off your team, what you set up for each, and what each " +
      "one deliberately does not do.",
  },
  {
    href: "/industries",
    title: "What it looks like in your trade",
    body:
      "Clinics, property offices, insurance and coaching — the questions asked, the row " +
      "you receive, and which of the four have a suite of test calls behind them today.",
  },
  {
    href: "/why-calevate",
    title: "Why this rather than hiring",
    body:
      "The five things a salary cannot buy, why this does not replace your sales team, and " +
      "the six sentences this website will not say.",
  },
  {
    href: "/roi",
    title: "What it would cost you",
    body:
      "The comparison against hiring, with your own volumes, the full methodology, and the " +
      "three branches where the arithmetic goes against us.",
  },
  {
    href: "/pricing",
    title: "How the bill is put together",
    body:
      "What is metered, how a plan is shaped, prepaid credit, the two spending ceilings, " +
      "and why no figure is printed on that page.",
  },
  {
    href: "/security",
    title: "What happens to your customers’ data",
    body:
      "The four rules enforced on every dial, where each part of a call runs, who can see " +
      "what, and the awkward calls an agent is tested against.",
  },
];

/**
 * The words this product uses, in plain language.
 *
 * Each is a thing in the product. The two regulatory-adjacent entries deliberately describe
 * the PRODUCT's behaviour and route to the documents rather than paraphrasing a rule.
 */
const GLOSSARY: readonly { term: string; detail: string }[] = [
  {
    term: "Agent",
    detail:
      "One configured AI that answers or makes calls for you. A business can have several " +
      "— a receptionist for the main line and a separate one that works a list, for " +
      "instance — each with its own language, its own opening line and its own questions.",
  },
  {
    term: "Your columns (an extraction schema)",
    detail:
      "The list of things you said you needed to know from every caller. It is the single " +
      "most important thing you set up: it becomes the columns of your leads list, the " +
      "headings of the spreadsheet you download, and the fields sent to your CRM. One " +
      "definition, so the screen and the file can never disagree.",
  },
  {
    term: "Lead status",
    detail:
      "How interested somebody turned out to be: new, contacted, interested, hot, won or " +
      "lost. A fixed set rather than free text, so two people reading the same list read " +
      "the same thing and the funnel means something.",
  },
  {
    term: "Campaign",
    detail:
      "A list of numbers the agent works through, with the times it may run. It is a draft " +
      "until a person launches it, it can be paused, and a no-answer goes back on a retry " +
      "ladder rather than being lost.",
  },
  {
    term: "Compliance gate",
    detail:
      "The check that runs before a campaign may start and before every dial. It is what " +
      "refuses a call outside 9am–9pm, a number on your do-not-call list, or an account " +
      "whose registrations are not in place. It is not a warning; the dial does not happen.",
  },
  {
    term: "Do-not-call list",
    detail:
      "Numbers that must not be rung. Yours, scrubbed before every dispatch. You can add " +
      "numbers and remove ones you added — but an entry recording a caller’s own request " +
      "to be removed is not removable by anybody, because it was not our decision or " +
      "yours to begin with.",
  },
  {
    term: "Registration (DLT)",
    detail:
      "Indian rules require the business whose calls they are to be registered, and the " +
      "telemarketer placing them to be registered too. Getting that in place is part of " +
      "setting you up, and the product refuses to dial a campaign until it is. Inbound " +
      "answering is not affected. What the obligation itself is belongs in the terms " +
      "rather than in a paragraph here.",
  },
  {
    term: "Callback",
    detail:
      "A time a caller asked to be rung back at, booked by the agent during the call. It " +
      "is dialled at that time. If it cannot be placed it settles with a visible reason " +
      "instead of retrying quietly for ever, because somebody is sitting by a phone.",
  },
  {
    term: "Key moments",
    detail:
      "Timestamps into a recording — where the slot was agreed, where a number was given, " +
      "where somebody asked to be removed — worked out once after the call so that " +
      "jumping to the right second costs nothing.",
  },
  {
    term: "Redacted transcript",
    detail:
      "What a transcript looks like by default: numbers, IDs and card details stripped " +
      "out. Reading the raw text takes a specific role and writes an audit entry naming " +
      "who read it.",
  },
  {
    term: "Publishing",
    detail:
      "The moment a change you made — a new answer, a different voice, an edited " +
      "question list — reaches live calls. Nothing you type is answering a caller until " +
      "you publish it, and the honest answers about being an AI and about recording are " +
      "attached above your script every time it happens.",
  },
  {
    term: "Wallet and credits",
    detail:
      "Prepaid balance, if your account runs that way, with the ledger it came out of. " +
      "When it is exhausted, outbound calling stops rather than running on into a bill " +
      "you did not agree to.",
  },
  {
    term: "Spend cap",
    detail:
      "A ceiling on what an account may spend in a month. There are two — one in your " +
      "arrangement that your staff cannot raise, and one you set yourself which may be as " +
      "low as you like, including zero. The stricter of the pair applies.",
  },
  {
    term: "Quality report",
    detail:
      "A monthly report on your own agent, in your dashboard, beside the calls it was " +
      "scored on. It is allowed to say bad news: where too few calls were scored to " +
      "support a figure it prints the count instead of a percentage, and the fields your " +
      "agent does not fill reliably are listed by their own labels.",
  },
];

export default function ResourcesPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Resources"
        title="Where to start, and what the words mean"
        lede="No case studies and no whitepapers — there is no client in production to write one about, and we would rather say that than invent one. What is here is a map of the site and a glossary, because this product sits between three vocabularies and you should not need any of them."
      />

      {/* --- 01 Where to start --------------------------------------------------- */}
      <section id="reading" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">Where to start</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Six pages, in the order they are useful
          </h2>
          <ul className="mt-10 grid gap-3 sm:mt-12 sm:grid-cols-2 lg:grid-cols-3">
            {READING.map(({ href, title, body }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="group flex h-full flex-col rounded-2xl border border-line bg-surface p-5 transition-colors hover:border-brand/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong"
                >
                  <span className="flex items-center gap-2 text-[17px] font-semibold text-balance text-ink">
                    {title}
                    <ArrowRight
                      aria-hidden
                      className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5"
                    />
                  </span>
                  <span className="mt-2 text-sm text-pretty text-ink-muted">{body}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* --- 02 The documents ---------------------------------------------------- */}
      <section id="documents" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">The documents</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Everything we publish, in full
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Which of these applies to you depends on whether you buy Calevate, work for a
            business that does, or received a call from one — each page says so at the top.{" "}
            <Link href="/security" className={INLINE_LINK}>
              The security page
            </Link>{" "}
            summarises the behaviour behind them without paraphrasing the documents
            themselves.
          </p>
          <ul className="mt-8 flex flex-wrap gap-2">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link
                  href={`/legal/${doc.slug}`}
                  className="inline-block rounded-full border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink-muted transition-colors hover:border-brand/50 hover:text-ink touch:py-2.5"
                >
                  {doc.shortTitle}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* --- 03 Glossary --------------------------------------------------------- */}
      <section id="glossary" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">Glossary</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The words we use, in plain language
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Every entry is a thing in the product — something you set up, a state a record
            can be in, or a control you operate. Where a word is really a regulator’s, the
            entry says what the product does about it and points at the document, because
            that is the instrument and this is not.
          </p>
          <dl className="mt-10 grid gap-4 sm:mt-12 sm:grid-cols-2">
            {GLOSSARY.map(({ term, detail }) => (
              <div key={term} className={CARD}>
                <dt className="text-[17px] font-semibold text-ink">{term}</dt>
                <dd className="mt-2 text-sm text-pretty text-ink-muted">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <ClosingCta line="Still have a question this site does not answer?" />
    </MarketingPage>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRight, Check, Globe, Lock } from "lucide-react";

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
import {
  COMPLIANCE_INVARIANTS,
  DATA_PROMISES,
  TESTED_SCENARIOS,
  WHERE_IT_RUNS,
} from "@/lib/marketing/compliance";
import { LEGAL_DOCUMENTS } from "@/lib/legal";

/**
 * `/security` — security and compliance, for the reader who is about to ask their lawyer.
 *
 * ## THIS PAGE RESTATES NOTHING. It reuses, or it links.
 *
 * That is a hard constraint rather than a style, and it has two halves:
 *
 * 1. **The marketing-side sentences come from `lib/marketing/compliance.ts` as CONSTANTS** —
 *    the four dispatch invariants, the residency paragraph, the three data promises and the
 *    tested-scenario list. The homepage renders the same constants. Two copies of a
 *    sentence that has been corrected three times is how a public page ends up
 *    contradicting itself, and the copy that falls behind is a misrepresentation rather
 *    than a stale comment.
 * 2. **The legal detail is NOT summarised here at all.** The eight published documents say
 *    what they say; a ninth page paraphrasing them would be a ninth document nobody
 *    maintains, and a paraphrase of a DPA clause is a new legal claim. So the last section
 *    is a set of links derived from `LEGAL_DOCUMENTS`, with each document's own summary,
 *    and the reader goes to the source.
 *
 * ## What this page adds that the documents do not
 *
 * The documents are written for a lawyer. This page answers the four questions an owner
 * asks in the order they ask them: what happens on every dial, where my customers' data
 * goes, who can see it, and how you know the agent works before it takes a real call. Each
 * answer is a behaviour enforced in code, cited at the point of use.
 *
 * ## NO SCORE, ANYWHERE
 *
 * The testing section is a LIST of what an agent is run against and carries no rating,
 * percentage, dot row, bar or pass mark — the founder's instruction of 5 Sep 2026, and the
 * honest position: nothing publishes a per-scenario result a client-facing page could read.
 * See `TESTED_SCENARIOS` for what was checked before the list was written.
 */
export const metadata: Metadata = {
  title: "Security & compliance — Calevate",
  description:
    "What Calevate enforces on every dial, where each part of a call runs, who can see " +
    "your customers' data, and the published legal documents behind all of it.",
};

export default function SecurityPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Security & compliance"
        title="An automated call is regulated here, and we built for that"
        lede="The agent speaks on your registration, so these are not settings with sensible defaults — they are limits the product enforces on every dial. Where we cannot enforce something, this page says who checks it instead."
      />

      {/* --- 01 On every dial ---------------------------------------------------- */}
      <section id="every-dial" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">On every dial</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Four rules that live in the code rather than in a policy page
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            None of these is a checkbox in your settings. They run on the dispatch path,
            which means a campaign cannot be configured around them and a busy Monday cannot
            forget them.
          </p>
          <dl className="mt-10 grid gap-4 sm:mt-12 sm:grid-cols-2">
            {/* The icon lives INSIDE the <dt>. A <div> grouping inside a <dl> may contain
                only <dt> and <dd> children (axe `definition-list`), and a decorative span
                between them is exactly the kind of markup that reads fine and announces
                badly. */}
            {COMPLIANCE_INVARIANTS.map(({ icon: Icon, title, body }) => (
              <div key={title} className={CARD}>
                <dt className="text-[17px] font-semibold text-ink">
                  <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                    <Icon aria-hidden className="h-5 w-5" />
                  </span>
                  {title}
                </dt>
                <dd className="mt-2 text-sm text-pretty text-ink-muted">{body}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-8 max-w-2xl text-sm text-ink-faint">
            Outbound calling also needs the registrations Indian rules require — the business
            whose calls they are, and the telemarketer placing them. The product refuses to
            dial a campaign until that is in place, and inbound answering is unaffected by
            any of it. What those obligations are is set out in{" "}
            <Link href="/legal/terms" className={INLINE_LINK}>
              the terms
            </Link>{" "}
            rather than summarised here.
          </p>
        </div>
      </section>

      {/* --- 02 Where each part runs --------------------------------------------- */}
      <section id="where-it-runs" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">Where it runs</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Know where your customer data goes
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            This is the question a serious buyer asks first, and the one a marketing page is
            most tempted to answer loosely. Here it is in full, in the same words the
            homepage carries and the sub-processor page expands on. A sophisticated customer
            would find the rest of it anyway; we would rather they found it here.
          </p>
          <div className="mt-10 max-w-3xl rounded-2xl border border-line bg-surface p-5 sm:mt-12 sm:p-8">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
              <Globe aria-hidden className="h-5 w-5" />
            </span>
            {/* VERBATIM, from the one definition. See `lib/marketing/compliance.ts` for the
                correction history and for why no part of it may be paraphrased. */}
            <p className="mt-4 text-[15px] leading-7 text-pretty text-ink-muted">
              {WHERE_IT_RUNS}
            </p>
            <p className="mt-5 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-4 text-sm">
              <Link href="/legal/subprocessors" className={INLINE_LINK}>
                Sub-processors
              </Link>
              <Link href="/legal/privacy" className={INLINE_LINK}>
                Privacy policy
              </Link>
              <Link href="/legal/dpa" className={INLINE_LINK}>
                Data processing addendum
              </Link>
            </p>
          </div>
          <p className="mt-6 max-w-2xl text-sm text-ink-faint">
            We hold no security certification — no SOC 2, no ISO 27001, no HIPAA — and this
            page will not imply one. What we have instead is the list above, the documents
            below, and a sub-processor page that names each vendor before you sign rather
            than after.
          </p>
        </div>
      </section>

      {/* --- 03 Who can see what ------------------------------------------------- */}
      <section id="access" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">Who can see what</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Your customers’ data stays yours
          </h2>
          <dl className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
            {DATA_PROMISES.map(({ term, detail }) => (
              <div key={term} className={CARD}>
                <dt className="text-[17px] font-semibold text-ink">
                  <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                    <Lock aria-hidden className="h-5 w-5" />
                  </span>
                  {term}
                </dt>
                <dd className="mt-2 text-sm text-pretty text-ink-muted">{detail}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-8 max-w-2xl space-y-4 text-[15px] leading-7 text-ink-muted">
            <p>
              {/* Roles gate the CRM; the export is a separate permission and writes an
                  `audit_log` entry (hard rule 5, `apps/api/crm/routes.py`'s role-gated,
                  audited export). */}
              Inside your own account it is your team who sees your callers, and which of
              them is your choice: roles decide who reads the CRM at all, and downloading
              the whole contact list is a separate permission that writes an audit entry
              naming who took it.
            </p>
            <p>
              {/* apps/workers/retention.py — RECORDING_FLOOR_DAYS = 90 and the
                  `recording_ttl_floor` CHECK on `retention_policies`. */}
              Recordings are held to a floor the database itself enforces, so a shorter
              retention policy cannot be set by you or by us. Everything else about how long
              we keep what we hold is in the privacy policy rather than paraphrased here.
            </p>
          </div>
        </div>
      </section>

      {/* --- 04 Before it takes a real call -------------------------------------- */}
      <section id="testing" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="04">Before it takes a real call</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The awkward calls an agent is run against
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            An agent that sounds good on the demo call and loses a detail on the fortieth one
            is the ordinary failure of this whole category. These are the calls it is put
            through — a scripted transcript for each, scored on whether the details reached
            the leads list correctly.
          </p>
          <ul className="mt-10 grid gap-3 sm:mt-12 sm:grid-cols-2 lg:grid-cols-3">
            {TESTED_SCENARIOS.map((scenario) => (
              <li
                key={scenario}
                className="flex items-start gap-2.5 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-muted"
              >
                <Check
                  aria-hidden
                  className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright"
                />
                {scenario}
              </li>
            ))}
          </ul>
          {/* NO SCORE. Not a percentage, not a rating, not a pass mark — nothing in the
              product publishes a per-scenario result a client-facing page could read, and
              the tick above is a list bullet rather than a verdict. */}
          <p className="mt-8 max-w-2xl text-base text-pretty text-ink-muted">
            We publish no score against that list, and no accuracy figure for any language.
            A number we cannot show you the working for is worth nothing, and the honest
            position today is that how well the agent understands Telugu has not been
            measured properly enough to publish. When it has been, the figure will arrive
            with its method attached.
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            What you get instead is a report in your own dashboard, beside the calls it was
            scored on, which is allowed to say bad news: where too few calls were scored to
            support a figure it prints the count and says so, and the fields your agent
            struggles with are listed by name.
          </p>
        </div>
      </section>

      {/* --- 05 The documents ---------------------------------------------------- */}
      <section id="documents" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="05">The documents</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The whole of it, in the documents themselves
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            Everything above is a summary of behaviour. These are the instruments — and this
            page deliberately does not paraphrase them, because a paraphrase of a data
            processing clause is a new claim rather than a shorter one. Which of them applies
            to you depends on whether you buy Calevate, work for a business that does, or
            received a call from one; each page says so at the top.
          </p>
          <ul className="mt-10 grid gap-3 sm:mt-12 sm:grid-cols-2">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link
                  href={`/legal/${doc.slug}`}
                  className="group flex h-full flex-col rounded-2xl border border-line bg-surface p-5 transition-colors hover:border-brand/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong"
                >
                  <span className="flex items-center gap-2 text-[17px] font-semibold text-ink">
                    {doc.shortTitle}
                    <ArrowRight
                      aria-hidden
                      className="h-4 w-4 text-ink-faint transition-transform group-hover:translate-x-0.5"
                    />
                  </span>
                  <span className="mt-1.5 text-sm text-pretty text-ink-muted">
                    {doc.summary}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <ClosingCta line="Ask us the hard questions before you sign" />
    </MarketingPage>
  );
}

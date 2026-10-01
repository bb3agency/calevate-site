import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { ArrowRight } from "lucide-react";

import { publicPageMetadata } from "@/lib/seo/metadata";

import { Band, Chapter, HOME } from "@/components/marketing/home/band";
import { LaunchCheckMock } from "@/components/marketing/home/mockups/featureMockups";
import { MockStage } from "@/components/marketing/home/mockups/stage";
import {
  CARD_LINK,
  ClosingCta,
  INLINE_LINK,
  MarketingPage,
  NUDGE_ARROW,
} from "@/components/marketing/pageShell";
import {
  AuditLogMock,
  CallingWindowMock,
  DoNotCallMock,
  OpeningNoticesMock,
  RedactedTranscriptMock,
  RetentionMock,
  RolesMock,
} from "@/components/marketing/security/mockups";
import { JumpLinks, PageHero } from "@/components/marketing/why/pageHero";
import {
  COMPLIANCE_INVARIANTS,
  DATA_PROMISES,
  TESTED_SCENARIOS,
  WHERE_IT_RUNS,
} from "@/lib/marketing/compliance";
import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { lookup } from "@/lib/lookup";

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
 * See `TESTED_SCENARIOS` for what was checked before the list was written. The list is
 * drawn with plain dots for the same reason: a tick beside a scenario reads as "passed".
 *
 * ## The mockups SHOW the controls the sentences name, and say nothing more
 *
 * Each picture is the console screen behind the sentence beside it
 * (`components/marketing/security/mockups.tsx` names each source). A mockup may print a
 * console label or a line this page already states; it may not add a claim the words do
 * not make, which is why the retention mockup prints only the recording floor.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/security",
  title: "Security & compliance — Calevate",
  description:
    "What Calevate enforces on every dial, where each part of a call runs, who can see " +
    "your customers' data, and the published legal documents behind all of it.",
});


/**
 * The screen behind each of the four dispatch rules, keyed by the rule's own title so the
 * pairing cannot slip if `COMPLIANCE_INVARIANTS` is reordered. A retitled rule renders
 * without a picture rather than beside the wrong one.
 */
const RULE_FIGURES: Record<string, ReactNode> = {
  "9am to 9pm, always": <CallingWindowMock />,
  "Do-not-call is checked first": <DoNotCallMock />,
  "It never denies being an AI": <OpeningNoticesMock />,
  "Recordings are kept for at least 90 days": <RetentionMock />,
};

const SECTIONS = [
  { href: "#every-dial", label: "On every dial" },
  { href: "#where-it-runs", label: "Where it runs" },
  { href: "#access", label: "Who can see what" },
  { href: "#testing", label: "Before a real call" },
  { href: "#documents", label: "The documents" },
] as const;

/** The three documents the residency paragraph points at. */
const WHERE_LINKS = [
  { href: "/legal/subprocessors", label: "Sub-processors" },
  { href: "/legal/privacy", label: "Privacy policy" },
  { href: "/legal/dpa", label: "Data processing addendum" },
] as const;

export default function SecurityPage() {
  return (
    <MarketingPage>
      <PageHero
        label="Security & compliance"
        title="An automated call is regulated here, and we built for that"
        lede="The agent speaks on your registration, so these are not settings with sensible defaults — they are limits the product enforces on every dial. Where we cannot enforce something, this page says who checks it instead."
        nav={<JumpLinks links={SECTIONS} />}
        product={
          <MockStage
            label="Illustration of a call transcript as a staff member sees it: phone numbers and personal details replaced with redaction marks, the full-transcript control refused with the reason that only an account owner can open it, and an audit log naming who opened a full transcript, downloaded the contact list and played a recording."
            className="grid gap-4 lg:grid-cols-[1.4fr_1fr] lg:items-start"
          >
            <span className="mk-rise mk-s1 block">
              <RedactedTranscriptMock />
            </span>
            <span className="mk-rise mk-s2 block">
              <AuditLogMock />
            </span>
          </MockStage>
        }
      />

      {/* --- On every dial ------------------------------------------------------- */}
      <Chapter tone="app">
        <Band
          id="every-dial"
          eyebrow="On every dial"
          title="Four rules that live in the code rather than in a policy page"
        >
          <div className={`${HOME.contentGap} grid ${HOME.itemGap} md:grid-cols-2`}>
            {COMPLIANCE_INVARIANTS.map(({ title, body }) => {
              const figure = lookup(RULE_FIGURES, title);
              return (
                <section
                  key={title}
                  className="flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card"
                >
                  <div className="p-5 sm:p-7">
                    <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
                    <p className={`mt-2 max-w-xl text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
                  </div>
                  {figure && (
                    <MockStage className="mt-auto border-t border-line bg-app/70 p-4 sm:p-6">
                      {figure}
                    </MockStage>
                  )}
                </section>
              );
            })}
          </div>

          <div className={`mt-10 grid ${HOME.itemGap} sm:mt-14 lg:grid-cols-[1.1fr_0.9fr] lg:items-start`}>
            <div className={`space-y-4 text-pretty text-ink-muted ${HOME.bodySm}`}>
              <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>
                Before a first outbound call
              </h3>
              <p>
                Outbound calling also needs the registrations Indian rules require —
                the business whose calls they are, and the telemarketer placing
                them. The product refuses to dial a campaign until that is in place,
                and inbound answering is unaffected by any of it. What those
                obligations are is set out in{" "}
                <Link href="/legal/terms" className={INLINE_LINK}>
                  the terms
                </Link>{" "}
                rather than summarised here.
              </p>
              {/* `check_dispatch` items 7b (`compliance/autodialer.py`) and 2c
                  (`compliance/kyc.py`), both outbound-only. Two things this may not say:
                  that the client is compliant (the autodialer obligation's own evidence
                  class is REPORTED; nobody here has opened TCCCPR Reg 4), and that a new
                  account can switch outbound on by itself, which the number arrangement
                  still prevents. */}
              <p>
                Two more things stand in front of a first outbound call, and until
                both are in place every outbound dial is refused. You have to tell
                your own telecom access provider, in writing and in advance, that
                these calls are placed by an automated dialler and what they are for
                — that notice is yours to give, because it is your business the
                provider holds to it. And we verify the business behind the account:
                an operator checks a public business-registry record before its
                calls go out. You record that notice yourself, on your agreements
                screen, once you have sent it. Outbound is still not something a new
                account switches on alone — the number your calls go out from is
                arranged with us — but every gate in front of it is one you can see
                and clear. Answering incoming calls is unaffected by any of it.
              </p>
            </div>
            <MockStage
              label="Illustration of the check a campaign passes before it can call anyone: a published agent, its AI disclosure line, the voice template, the calling number, the contact list and where it came from — then calls only between 9am and 9pm, with the do-not-call list removed."
              className="lg:sticky lg:top-28"
            >
              <LaunchCheckMock />
            </MockStage>
          </div>
          <p className={`mt-8 text-ink-muted ${HOME.bodySm}`}>
            The screens on this page are illustrations, not a real customer or a
            measurement.
          </p>
        </Band>
      </Chapter>

      {/* --- Where each part runs ------------------------------------------------ */}
      <Chapter tone="raised">
        <Band id="where-it-runs" eyebrow="Where it runs" title="Know where your customer data goes">
          <div className={`${HOME.contentGap} grid ${HOME.itemGap} lg:grid-cols-[1.5fr_1fr] lg:items-start`}>
            <div className={HOME.panel}>
              {/* VERBATIM, from the one definition. See `lib/marketing/compliance.ts` for
                  the correction history and for why no part of it may be paraphrased. */}
              <p className={`text-pretty text-ink-muted ${HOME.bodySm}`}>{WHERE_IT_RUNS}</p>
            </div>
            <div className="grid gap-3">
              {WHERE_LINKS.map(({ href, label }) => (
                <Link key={href} href={href} className={CARD_LINK}>
                  <span className="flex items-start justify-between gap-2 text-lg font-semibold text-ink">
                    {label}
                    <ArrowRight aria-hidden className={`${NUDGE_ARROW} mt-1.5 text-ink-faint`} />
                  </span>
                </Link>
              ))}
              <p className="mt-2 text-base text-pretty text-ink-muted">
                We hold no security certification — no SOC 2, no ISO 27001, no HIPAA
                — and this page will not imply one. What we have instead is the list
                above, the documents below, and a sub-processor page that names each
                vendor before you sign rather than after.
              </p>
            </div>
          </div>
        </Band>
      </Chapter>

      {/* --- Who can see what ---------------------------------------------------- */}
      <Chapter tone="app">
        <Band id="access" eyebrow="Who can see what" title="Your customers’ data stays yours">
          <div className={`${HOME.contentGap} grid ${HOME.itemGap} lg:grid-cols-[1.1fr_0.9fr] lg:items-start`}>
            <div>
              <dl className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
                {DATA_PROMISES.map(({ term, detail }) => (
                  <div key={term} className="p-5 sm:p-7">
                    <dt className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{term}</dt>
                    <dd className={`mt-2 text-pretty text-ink-muted ${HOME.bodySm}`}>{detail}</dd>
                  </div>
                ))}
              </dl>
              <div className={`mt-8 space-y-4 text-pretty text-ink-muted ${HOME.bodySm}`}>
                <p>
                  {/* Roles gate the CRM; the export is a separate permission and writes an
                      `audit_log` entry (hard rule 5, `apps/api/crm/routes.py`'s role-gated,
                      audited export). */}
                  Inside your own account it is your team who sees your callers, and
                  which of them is your choice: roles decide who reads the CRM at
                  all, and downloading the whole contact list is a separate
                  permission that writes an audit entry naming who took it.
                </p>
                <p>
                  {/* apps/workers/retention.py — RECORDING_FLOOR_DAYS = 90 and the
                      `recording_ttl_floor` CHECK on `retention_policies`. */}
                  Recordings are held to a floor the database itself enforces, so a
                  shorter retention policy cannot be set by you or by us. Everything
                  else about how long we keep what we hold is in the privacy policy
                  rather than paraphrased here.
                </p>
              </div>
            </div>
            <MockStage
              label="Illustration of the team screen: one owner and two staff, with what each role may do."
              className="lg:sticky lg:top-28"
            >
              <RolesMock />
            </MockStage>
          </div>
        </Band>
      </Chapter>

      {/* --- Before it takes a real call ----------------------------------------- */}
      <Chapter tone="raised">
        <Band
          id="testing"
          eyebrow="Before it takes a real call"
          title="The awkward calls an agent is run against"
          lede="The calls an agent is put through — a scripted transcript for each, scored on whether the details reached the leads list correctly."
        >
          {/* NO SCORE. Not a percentage, not a rating, not a pass mark, and plain dots
              rather than ticks: nothing in the product publishes a per-scenario result a
              client-facing page could read. */}
          <ul className={`${HOME.contentGap} flex flex-wrap gap-2.5`}>
            {TESTED_SCENARIOS.map((scenario) => (
              <li
                key={scenario}
                className="flex items-center gap-2 rounded-full border border-line bg-app/60 px-4 py-2 text-base font-medium text-ink-muted"
              >
                <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-ink/30" />
                {scenario}
              </li>
            ))}
          </ul>
          <p className={`mt-8 max-w-3xl text-pretty text-ink-muted ${HOME.bodySm}`}>
            We publish no score against that list, and no accuracy figure for
            any language. How well the agent understands Telugu has not been
            measured properly enough to publish.
          </p>
        </Band>
      </Chapter>

      {/* --- The documents ------------------------------------------------------- */}
      <Chapter tone="app">
        <Band
          id="documents"
          eyebrow="The documents"
          title="The whole of it, in the documents themselves"
          lede="Everything above is a summary of behaviour; these are the instruments. Which of them applies to you depends on whether you buy Calevate, work for a business that does, or received a call from one — each page says so at the top."
        >
          <ul className={`${HOME.contentGap} grid gap-3 sm:grid-cols-2 lg:grid-cols-4`}>
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link href={`/legal/${doc.slug}`} className={CARD_LINK}>
                  <span className="flex items-start justify-between gap-2 text-lg font-semibold text-ink">
                    {doc.shortTitle}
                    <ArrowRight aria-hidden className={`${NUDGE_ARROW} mt-1.5 text-ink-faint`} />
                  </span>
                  <span className="mt-1.5 text-sm text-pretty text-ink-muted">{doc.summary}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Band>
      </Chapter>

      <ClosingCta line="Ask us the hard questions before you sign" />
    </MarketingPage>
  );
}

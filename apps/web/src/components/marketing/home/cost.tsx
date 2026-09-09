import Link from "next/link";

import {
  ArrowRight,
  Check,
  Clock3,
  Infinity as InfinityIcon,
  ListChecks,
  ShieldCheck,
  TrendingDown,
} from "lucide-react";

import { Reveal } from "@/components/marketing/motion";
import { CTA_LABEL, CTA_PRIMARY } from "@/components/marketing/pageShell";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import type { PublicRateCard } from "@/lib/api/rateCard";

import { Band, Chapter, HOME } from "./band";

/**
 * CHAPTER 6 — what it costs, and what the maths misses. BANDS 10 AND 11, IN ONE ARGUMENT.
 *
 * "Why Calevate" (band 11) was headed *"The part a headcount comparison cannot see"* and sat
 * in its own numbered chapter AFTER the headcount comparison, separated from it by a rule
 * and a colour change — a section whose whole subject is the section above it, presented as
 * a new topic. It is a sub-heading of the cost argument, and it is one here.
 *
 * ## The one place a price appears, and it is served
 *
 * `RoiCalculator` shows Calevate's published self-serve rates as the INPUT to a comparison
 * the buyer drives with their own numbers (D-545, reshaped by D-547). Those rates are
 * FETCHED: `app/page.tsx` awaits `GET /v1/public/rate-card` and hands the card down here.
 * `null` is a first-class answer — the calculator renders "the comparison cannot run right
 * now" rather than a stale figure. **No rupee figure is typed anywhere in this tree**, and
 * `publicLanding.test.tsx` bans one everywhere outside the calculator's own subtree.
 *
 * ## The five are a list, not five more panels
 *
 * They were five `Card`s in a three-column grid, which put five equal boxes on the page
 * immediately after the calculator's own boxes. UX-DOCTRINE §1: one item in a homogeneous
 * list is a ROW inside ONE card, not a card of its own — `Roster.tsx` is the repo's worked
 * example, and it is the difference between a status board and a document. Each row is a
 * behaviour: 24/7 answering (`apps/api/agents/business_hours.py`), concurrency (the engine
 * dials per call, not per desk), no hiring cycle, the same questions every time (the
 * extraction schema, `apps/api/crm/columns.py`), and the dispatch-path invariants — calling
 * hours and DNC (`apps/api/compliance/service.py:208,621`).
 *
 * ## The call to action, offered where the reader has just done work
 *
 * Not a competing call to action: GOV.UK's rule is against multiple DIFFERENT default
 * buttons, and every primary button on this page is one action, one destination, one label
 * (`src/components/marketing/pageShell.tsx::CTA_LABEL`). The three lines under it are risk
 * reversal, and each is enforced in code: a person approves every word before an agent can
 * answer with it (`apps/api/kb/service.py:437::approve_source`,
 * `apps/api/agents/service.py:1193`), a campaign is a draft until somebody launches it
 * (`apps/api/campaigns/service.py:1199`), and pause stops the next dispatch tick
 * (`POST /v1/campaigns/{id}/pause`, `apps/api/campaigns/routes.py:731`).
 */

const BEYOND: readonly { icon: typeof Clock3; title: string; body: string }[] = [
  {
    icon: Clock3,
    title: "Your phone doesn’t clock out",
    body:
      "Evenings, Sundays and festival days are answered at the same rate as a Tuesday " +
      "morning. There is no shift to staff for them.",
  },
  {
    icon: InfinityIcon,
    title: "A busy hour is not a queue",
    body:
      "Fifty callers at 11am are fifty answered calls, not fifty people waiting behind " +
      "three desks.",
  },
  {
    icon: TrendingDown,
    title: "Nothing to train, and nothing resigns",
    body:
      "No six-week ramp, no re-hiring in four months. It is doing the job the day you " +
      "switch it on, and the same job a year later.",
  },
  {
    icon: ListChecks,
    title: "The same questions, every single call",
    body:
      "The things you said you needed to know get asked whether it is the third call of " +
      "the day or the ninetieth.",
  },
  {
    icon: ShieldCheck,
    title: "The rules on every dial",
    body:
      "Calling hours, do-not-call scrubbing and the AI-disclosure answer are enforced on " +
      "every call rather than left to a person to remember.",
  },
];

/** Three things the buyer keeps control of. Each one is enforced, not promised. */
const RISK_REVERSAL: readonly string[] = [
  "You approve every word before it goes live",
  "Nothing dials anybody until you launch it",
  "Pause it from your dashboard whenever you want",
];

export function Cost({ rateCard }: { rateCard: PublicRateCard | null }) {
  return (
    <Chapter tone="app">
      <Band
        id="cost"
        eyebrow="What it costs"
        weight="anchor"
        title="Do the maths against hiring, with your own numbers"
        lede="Three numbers you already know. Everything else is pre-filled and sitting behind “Adjust assumptions”, where you can change any of it."
      >
        <RoiCalculator rateCard={rateCard} />

        <Reveal delay={0.08}>
          <h3 className="mt-24 text-2xl font-semibold tracking-tight text-balance text-ink sm:mt-32 sm:text-3xl">
            The part a headcount comparison cannot see
          </h3>
        </Reveal>
        {/* ONE card, five rows — not five cards. See this file's header. */}
        <Reveal as="section" delay={0.12} className="mt-8 overflow-hidden rounded-2xl border border-line bg-surface sm:mt-10">
          <ul className="divide-y divide-line">
            {BEYOND.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex flex-col gap-4 p-6 sm:flex-row sm:gap-7 sm:p-8">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-6 w-6" />
                </span>
                <div>
                  <h4 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h4>
                  <p className={`mt-2 max-w-2xl text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal as="section" delay={0.1} className={`mt-14 ${HOME.panel} sm:mt-20`}>
          <h3 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Worth a conversation?
          </h3>
          <p className={`mt-4 max-w-2xl text-pretty text-ink-muted ${HOME.body}`}>
            Those figures came out of what you typed, not out of a claim we made. If the
            shape of it works for your business, the next step is a short conversation — we
            build the agent with you, and you hear exactly what it will say before it ever
            picks up.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/signup" className={CTA_PRIMARY}>
              {CTA_LABEL}
              <ArrowRight
                aria-hidden
                className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
              />
            </Link>
          </div>
          {/* THIS ONE STAYS THREE-UP, and the reason is worth writing down because the
              rest of the page went the other way: it is a CHECKLIST, not a card grid —
              three ticked half-sentences with no heading, no control and no outcome of
              their own, which read as one reassurance under one button. Stacking them
              would spend a third of a screenful restating what the paragraph above just
              said. They grow with the scale instead. */}
          <ul className="mt-8 grid gap-3.5 border-t border-line pt-6 sm:grid-cols-3">
            {RISK_REVERSAL.map((promise) => (
              <li key={promise} className={`flex items-start gap-2.5 text-ink-muted ${HOME.bodySm}`}>
                <span
                  aria-hidden
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                >
                  <Check className="h-3.5 w-3.5" />
                </span>
                {promise}
              </li>
            ))}
          </ul>
        </Reveal>
      </Band>
    </Chapter>
  );
}

import type { Metadata } from "next";

import { publicPageMetadata } from "@/lib/seo/metadata";

import {
  cardFromRate,
  fetchPublicRateCard,
  formatRateINR,
  ladderFalls,
  packRate,
  rateToTenThousandths,
  tierLabel,
  UNPRICED_TIER_NOTICE,
  VOICE_TIERS,
  type PublicRateCard,
  type VoiceTier,
} from "@/lib/api/rateCard";
import Link from "next/link";

import { Check, Info, Receipt, ShieldCheck, Wallet } from "lucide-react";

import { RateCard } from "@/components/marketing/rateCard";

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
 * `/pricing` — what a minute costs, and the one figure that is still a conversation.
 *
 * Two price stories, and only one of them has a number:
 *
 * - **Self-serve** is published: a static six-rung credit-pack card
 *   (`apps/api/billing/credit_packs.py::PACK_CATALOGUE`), whose every rate is checked in CI
 *   against its own voice's cost floor, served at `GET /v1/public/rate-card` and fetched
 *   here at request time. **Nothing on this page is typed** — every ₹ figure below is a
 *   string that arrived in that response, and `apps/web/tests/marketingPages.test.tsx`
 *   fails the build if one is not.
 * - **Managed** plans are negotiated per client (D-11) and have no publishable figure:
 *   every money column on `plans` is nullable with no default and the number is a founder
 *   decision (`apps/api/billing/models.py:217-258`). A managed rate typed into this copy
 *   would be a quote nobody can honour — worse here than anywhere, because a price is the
 *   one claim a buyer relies on before they have met anybody. That caveat is one paragraph,
 *   below the card, where the reader who needs it will look.
 *
 * A pack buys a ₹/min for each of the two voices an agent can speak with (D-547), and which
 * one prices a call is a property of the AGENT that took it. The packs are COLUMNS and a
 * switch above the table picks the voice, so one ladder is on screen at a time;
 * `components/marketing/rateCard.tsx` is the whole of that and this page keeps the prose
 * and the two band sentences.
 *
 * **The columns are named by the API, not here.** No client-facing surface names a vendor
 * as a product tier: the names live once in `apps/api/billing/rates.py::VOICE_TIER_LABELS`
 * and travel on the card, so a client meets one name for a voice and we can change the
 * vendor under it without a rename. Never type a tier name into this file.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/pricing",
  title: "Pricing — Calevate",
  description:
    "How Calevate is billed: what is metered, how a plan is shaped, prepaid credit, " +
    "spend caps and the monthly invoice. Commercial terms are agreed per client.",
});

/** What you are billed FOR. Each is a real meter, not a package name. */
const METERED: readonly { title: string; body: string }[] = [
  {
    title: "Talk time",
    body:
      "The minutes your agents actually spend on calls — not seats, not agents, not " +
      "numbers configured. A quiet month costs less than a busy one.",
  },
  {
    title: "The voice each agent uses",
    body:
      // The per-agent fact lives once, in the self-serve paragraph above (UX-DOCTRINE §5).
      // What only this card says is that the METER reads the voice a call actually used.
      "Each agent speaks with one of two voices, and the two are priced differently. " +
      "Every call is stamped with the voice it actually used, so a month is priced from " +
      "what happened rather than from what was configured at the end of it.",
  },
  {
    title: "The language model you chose",
    body:
      "If you pick a dearer model than the one your plan's rate is struck against, the " +
      "difference is a per-minute surcharge on the minutes that actually used it. Stay on " +
      "the standard model and there is no surcharge.",
  },
];

/** How a plan is shaped. Every element is a real column; none has a published value. */
const PLAN_SHAPE: readonly { term: string; detail: string }[] = [
  {
    term: "A setup fee, if there is one",
    detail:
      "One-off, for building the agent with you. Some arrangements have none.",
  },
  {
    term: "A monthly fee",
    detail:
      "The standing part of the arrangement, agreed before anything is signed.",
  },
  {
    term: "Talk time included in it",
    detail:
      "A bundle of minutes that comes with the monthly fee.",
  },
  {
    term: "A rate for anything past the bundle",
    // Never promise a PER-VOICE overage rate here: a managed plan carries one. `plans` has
    // two overage columns (`overage_rate`, `overage_rate_second`,
    // `apps/api/billing/models.py`) and the second is D-36's TTS ladder, not one of the two
    // VOICE QUALITIES the self-serve card prices; every call is counted on the base rung
    // anyway (`apps/workers/pipeline.py:2743-2745`). A column per voice is a quote nobody
    // could honour.
    detail:
      "Per minute, applied to the minutes over the included allowance.",
  },
  {
    term: "A start date the plan is priced from",
    detail:
      "A plan carries the period it is in effect for, so a price change agreed today " +
      "does not silently re-price last month.",
  },
];

/**
 * THE DEAREST ₹/min the card quotes on one voice — the ENTRY rung of the ladder, and the
 * end of the band that describes somebody's FIRST purchase.
 *
 * The page quotes a BAND, once per voice, both ends from the card, rather than one "from"
 * figure: nobody's first purchase is the largest pack, so a single cheapest-rung price is
 * the rung a buyer will not pay. Same shape as the console's explainer
 * (`app/c/[slug]/billing/WhatCallsCost.tsx::rateBand`).
 *
 * The cheap end is a field the API publishes (`from_*_inr_per_min`, `cardFromRate`); this
 * end is not, so it is a COMPARISON across the rows the card sent. Nothing is computed:
 * `rateToTenThousandths` reads the digits into the API's own NUMERIC(12,4) scale and the
 * two are compared as integers, and what is rendered is the string the server sent.
 *
 * Its twin in the console (`billing/lots.ts::dearestRate`) cannot be imported: that module
 * is `"use client"` and reads the SIGNED-IN card type, while this page is an async server
 * component reading `CreditPacksOut` off the public route. One four-line accessor each,
 * rather than a shared module that would drag a client hook into the marketing tree.
 */
function cardDearestRate(card: PublicRateCard, voice: VoiceTier): string {
  // SEEDED WITH THE SERVER'S OWN PUBLISHED MINIMUM rather than with the first pack, so the
  // function is TOTAL: a card that somehow carried no rows still answers with a rate the
  // API sent instead of `undefined` rendered into a price sentence. The max of the
  // published floor and every rung is the entry rung, which is the figure wanted.
  let dearest = cardFromRate(card, voice);
  for (const pack of card.packs) {
    const rate = packRate(pack, voice);
    if (rateToTenThousandths(rate) > rateToTenThousandths(dearest)) dearest = rate;
  }
  return dearest;
}

/**
 * One voice's ladder as a sentence: `"₹5.00 a minute, down to ₹4.50 on the largest pack"`.
 *
 * A ladder with one rung is not a band, and "down to ₹5.00" would be a discount described
 * where there is none, so that case says the one figure once.
 */
function bandSentence(card: PublicRateCard, voice: VoiceTier): string {
  const dearest = cardDearestRate(card, voice);
  const cheapest = cardFromRate(card, voice);
  if (rateToTenThousandths(dearest) === rateToTenThousandths(cheapest)) {
    return `${formatRateINR(dearest)} a minute`;
  }
  return `${formatRateINR(dearest)} a minute, down to ${formatRateINR(cheapest)} on the largest pack`;
}

export default async function PricingPage() {
  // The one request this page makes. `fetchPublicRateCard` never throws — it logs and
  // returns null — so there is no `try` here and no figure to fall back to: a page that
  // fell back to a typed constant would look identical to a working one while quoting a
  // rate nobody set. The card is static (D-547), so it moves on a deploy rather than on an
  // operator's save and the route's minute of edge cache is a cache of a constant rather
  // than a staleness window on a live price.
  const rateCard = await fetchPublicRateCard();
  return (
    <MarketingPage>
      {/* THE PRICE IS THE HEADLINE: a buyer's whole reason for arriving is the number, so
          it leads and the managed-plan caveat sits at the bottom in one line. `rateCard` is
          null only when the API cannot be reached; the fallback says so rather than printing
          a figure we cannot stand behind. */}
      <PageIntro
        eyebrow="Pricing"
        title={
          rateCard === null
            ? "You are billed for the minutes your agents actually talk"
            : /* The headline quotes the STUDIO voice because it is the one that can be
                  bought: the Clear rung has no attested vendor price, so hard rule 7 keeps
                  every voice in it off the picker (`apps/api/agents/voice_offer.py`). A
                  headline price must be one somebody can be put on; the other voice is in
                  the lede, with the notice saying why. */
              `Talk time on the ${tierLabel(rateCard, "studio")} voice: ${bandSentence(rateCard, "studio")}`
        }
        lede={
          rateCard === null
            ? "Not per seat, not per agent, not per number — you pay for the minutes your agents actually talk. Our live rate card could not be loaded just now, so there is no figure on this page we can stand behind; reload in a moment."
            : `The ${tierLabel(rateCard, "clear")} voice is ${bandSentence(rateCard, "clear")} on the same card. ${UNPRICED_TIER_NOTICE} No monthly fee, no per-seat charge — you are billed for the minutes your agents actually talk, and credit does not expire.`
        }
      />

      {/* --- Self-serve rate card (D-545) --------------------------------------- */}
      <section id="self-serve" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="00">Self-serve</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            {/* NO FIGURE HERE, DELIBERATELY: the band is overhead in the h1 and every rung
                is in the table below, so a heading re-quoting one end of the ladder is a
                duplicate price.

                Whether the rate falls is ASKED OF THE CARD, never typed — it is false the
                moment either column goes flat, and the next card takes the cheaper voice
                flat at ₹4.00 (`docs/PIPECAT-MIGRATION.md` §12). `every` and not `some`:
                this heading sits above the switch and speaks for both voices, so a claim
                true of only one of them is not a claim it may make. */}
            {rateCard === null
              ? "Our self-serve rate"
              : VOICE_TIERS.every((voice) => ladderFalls(rateCard, voice))
                ? "Prepaid credit, and the rate comes down as the pack gets bigger"
                : "Prepaid credit, at a published rate with no minimum"}
          </h2>
          {rateCard === null ? (
            <p role="status" className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Our live rate card could not be loaded just now, so there is no figure here we
              can stand behind. Reload in a moment — we would rather show nothing than a
              price that may be out of date.
            </p>
          ) : (
            <>
              <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                {/* THIS CARD IS PUBLISHED; A MANAGED PLAN IS QUOTED — the page has to say
                    which is which, because it says both. It says nothing about how an
                    ACCOUNT is opened: `self_serve_signup_enabled` is a live switch and the
                    door that reads it is the homepage's, so a second sentence here would be
                    a second place to get it wrong. It also does not repeat the lede's
                    "credit does not expire" or the heading's falling rate (UX-DOCTRINE §5:
                    two spellings of one fact is a defect). */}
                This is a published price, not a quote, and there is no minimum. The rates
                you bought at stay with that credit until it is spent.
              </p>
              <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                {/* The client picks the voice themselves — `PATCH /v1/agents/{agent_id}/
                    voice` is a CLIENT-realm door (`agents:write` on `owner` and `staff`,
                    D-586) and the picker is on their own agent screen
                    (`app/c/[slug]/agents/panels/delivery.tsx`). Never restore "tell your
                    account manager": it sells a self-serve product as one with a support
                    queue in front of a two-click control. */}
                A voice is set per agent rather than for the whole account, and you choose
                it yourself on each agent&rsquo;s own screen — moving an agent to the other
                voice costs nothing and changes none of your credit.
              </p>
              {/* The rate card itself: the switch, and one voice's ladder at a time.
                  Extracted to `components/marketing/rateCard.tsx` (UX-DOCTRINE §6 —
                  extract by SUBJECT) because the table is now two layouts and a control,
                  and this route module is already four times its budget. */}
              <RateCard card={rateCard} />
              <p className="mt-6 max-w-2xl text-sm text-pretty text-ink-muted">
                Talk time is the minutes your agents actually speak for, not connected
                time. Credit is spent oldest purchase first, at the rates that purchase was
                made at.
              </p>
            </>
          )}
        </div>
      </section>

      {/* The managed-plan caveat, placed after the reader has seen what things cost.
          Those figures genuinely are not publishable — every money column on `plans` is
          nullable with no default — but that is a footnote to a price list, not a
          substitute for one. */}
      <section className="border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <div className="flex items-start gap-3">
            <Info
              aria-hidden
              className="mt-0.5 h-5 w-5 shrink-0 text-brand-strong dark:text-brand-bright"
            />
            <p className="max-w-2xl text-base text-pretty text-ink-muted">
              <span className="font-medium text-ink">Calling a lot?</span>{" "}
              Above a certain volume a monthly plan with minutes included usually costs less
              than paying by the minute. Those are agreed with you rather than published —
              put your own numbers into the{" "}
              <Link href="/roi" className={INLINE_LINK}>
                cost comparison
              </Link>{" "}
              first.
            </p>
          </div>
        </div>
      </section>

      {/* --- 01 What is metered -------------------------------------------------- */}
      <section id="metered" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="01">What you pay for</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Three things are metered, and all three are things that happened
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            {/* Every call writes a usage_event carrying our own unit cost (hard rule 7,
                `apps/api/db/registry.py:89` — the table is append-only). */}
            Every call writes a usage record of its own, with the rate that applied to it.
            A correction is a new entry rather than an edit, so a bill can be explained line
            by line months later.
          </p>
          <div className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
            {METERED.map(({ title, body }) => (
              <section key={title} className={CARD}>
                <h3 className="text-[17px] font-semibold text-ink">{title}</h3>
                <p className="mt-2 text-sm text-pretty text-ink-muted">{body}</p>
              </section>
            ))}
          </div>
        </div>
      </section>

      {/* --- 02 The shape of a plan ---------------------------------------------- */}
      <section id="plan" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="02">The shape of a plan</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Five parts, and you will know the number against each one before you sign
          </h2>
          <dl className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-2">
            {PLAN_SHAPE.map(({ term, detail }) => (
              <div key={term} className={CARD}>
                <dt className="flex items-start gap-2.5 text-[17px] font-semibold text-ink">
                  <span
                    aria-hidden
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                  >
                    <Check className="h-3 w-3" />
                  </span>
                  {term}
                </dt>
                <dd className="mt-2 pl-7.5 text-sm text-pretty text-ink-muted">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* --- 03 Prepaid, caps and the invoice ------------------------------------ */}
      <section id="controls" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="03">Paying, and not overpaying</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            A phone bill that cannot surprise you
          </h2>
          <div className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
            <section className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Wallet aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">Prepaid credit</h3>
              <p className="mt-2 text-sm text-pretty text-ink-muted">
                {/* apps/api/billing/wallet.py — the client-side read of the prepaid wallet;
                    apps/api/billing/credit_packs.py; compliance.service.credits_exhausted
                    is the ONE predicate, and since D-551 it decides both directions: the
                    dial gate refuses outbound, and `agents/service.py::
                    reconcile_inbound_answering` silences answering at the engine. A
                    pricing page that promised only the outbound half would sell a phone
                    line the product does not keep answering. The warning email on the
                    way down is `apps/workers/wallet_alerts.py`, published on the ledger
                    entry that crosses `low_balance_threshold_inr`. */}
                When the credit is exhausted, calling stops rather than continuing on to a
                bill you did not agree to: nothing goes out, and your agents stop answering
                incoming calls until you top up. We email the account owner before it
                happens.
              </p>
            </section>
            <section className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <ShieldCheck aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">Two ceilings, and the stricter one wins</h3>
              <p className="mt-2 text-sm text-pretty text-ink-muted">
                {/* `plans.hard_cap_min` / `hard_cap_spend` are ADMIN-owned; `client_cap_min`
                    / `client_cap_spend` are the client's and "may never be set looser than
                    the admin's" (`apps/api/billing/models.py:259-269`). The EFFECTIVE cap is
                    the stricter of the pair, derived in `apps/api/billing/caps.py` and read
                    from there by both the meter and the client route. Zero means "stop my
                    outbound calling now". */}
                A cap is a limit on the account rather than a warning email. There is one in
                your arrangement that your staff cannot raise, and one you set yourself that
                can be as low as you like — including zero, which stops your outbound calling
                on the spot. Whichever is stricter is the one that applies.
              </p>
            </section>
            <section className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Receipt aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">An invoice you can check</h3>
              <p className="mt-2 text-sm text-pretty text-ink-muted">
                {/* apps/api/billing/invoice.py — an invoice is DERIVED from the usage
                    ledger at the plan in effect for that period (billing/plans.py), so it
                    does not change when you look at it twice. GST: billing/gst.py. */}
                A month&apos;s invoice is assembled from those usage records at the plan in
                effect for that month, with GST worked out on it. It reads the same next year
                as it does today.
              </p>
            </section>
          </div>
        </div>
      </section>

      {/* --- 04 What you get for it ---------------------------------------------- */}
      <section className="border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="04">What the money buys</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The same product, whatever you pay
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            There is no feature ladder here and no tier that withholds the compliance
            controls.{" "}
            <Link href="/solutions" className={INLINE_LINK}>
              Every job on the Solutions page
            </Link>{" "}
            is available to every account, the calling-hours and do-not-call rules are
            enforced on every dial for everybody, and the honest answer about being an AI is
            not something a cheaper plan turns off. What changes with the arrangement is the
            price of a minute, not what a minute does.
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            A managed plan is the part that is a conversation — the monthly fee, the talk
            time in it and the rate past it are agreed with you.{" "}
            <Link href="/roi" className={INLINE_LINK}>
              Bring your own numbers
            </Link>{" "}
            and we will tell you where we land against them.
          </p>
        </div>
      </section>

      <ClosingCta line="Ask us what it would cost for your call volume" />
    </MarketingPage>
  );
}

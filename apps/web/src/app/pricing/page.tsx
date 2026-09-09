import type { Metadata } from "next";
import {
  cardFromRate,
  fetchPublicRateCard,
  formatRateINR,
  packRate,
  rateToTenThousandths,
  tierLabel,
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
 * ⚠ **THIS HEADER USED TO BE A LONG ARGUMENT FOR HAVING NO PRICE ON THE PRICING PAGE, AND
 * IT WAS ALREADY UNTRUE WHEN THE PAGE BELOW IT STARTED PRINTING ONE (D-545).** It said the
 * one published number lived on `/roi`; it cited `self_serve_inr_per_min` as the source of
 * that number, which D-547 then stopped being. A stale doc comment on a money surface is
 * not cosmetic: it is the next reader's brief, and this one would have sent them to delete
 * a rate card as a rule violation.
 *
 * ## The two price stories, and why only one of them has a number
 *
 * - **Self-serve** is published, because it is real: a static six-rung credit-pack card
 *   (`apps/api/billing/credit_packs.py::PACK_CATALOGUE`), whose every rate is checked in CI
 *   against its own voice's cost floor, served at `GET /v1/public/rate-card` and fetched
 *   here at request time. **Nothing on this page is typed** — every ₹ figure below is a
 *   string that arrived in that response, and `apps/web/tests/marketingPages.test.tsx`
 *   fails the build if one is not.
 * - **Managed** plans are negotiated per client (D-11) and genuinely have no publishable
 *   figure: every money column on `plans` is nullable with no default, and two of them
 *   record in their own comments that the number "is a founder decision" and that no
 *   default may be invented (`apps/api/billing/models.py:217-258`). A managed rate typed
 *   into this copy would be a quote nobody can honour — hard rule 11's exact failure, and
 *   worse here than anywhere, because a price is the one claim a buyer relies on before
 *   they have met anybody. That caveat is one paragraph, below the card, where the reader
 *   who needs it will look.
 *
 * ## Two voices, two rates, one per agent (D-547), ONE OF THEM ON SCREEN (D-559)
 *
 * A pack no longer buys "minutes" at one rate. It carries a ₹/min for each of the two
 * voices an agent can speak with, and which one prices a call is a property of the AGENT
 * that took it.
 *
 * ⚠ **THIS USED TO SAY "the table has two rate columns rather than one", AND THE TABLE
 * NOW HAS NEITHER SHAPE.** Six pack ROWS x (rate + talk time) x two voices was twelve
 * dense cells; the packs are COLUMNS now and a switch above the table picks the voice, so
 * one ladder is on screen at a time. `components/marketing/rateCard.tsx` is the whole of
 * it and carries the argument; this page keeps the prose and the two band sentences.
 *
 * **The columns are named by the API, not here.** No client-facing surface names a vendor
 * as a product tier (founder, 7 Sep 2026): the names live once in
 * `apps/api/billing/rates.py::VOICE_TIER_LABELS` and travel on the card, so a client meets
 * one name for a voice and we can change the vendor under it without a rename. Never type
 * a tier name into this file.
 *
 * Every claim below cites the code that makes it true, at the point of use.
 */
export const metadata: Metadata = {
  title: "Pricing — Calevate",
  description:
    "How Calevate is billed: what is metered, how a plan is shaped, prepaid credit, " +
    "spend caps and the monthly invoice. Commercial terms are agreed per client.",
};

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
      // The per-agent fact and the "tell your account manager" register live once, in the
      // self-serve paragraph above (§5: two spellings of one fact is a defect). What only
      // this card says is that the METER reads the voice a call actually used.
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
    // ⚠ THIS USED TO PROMISE A PER-VOICE OVERAGE RATE, AND A MANAGED PLAN CANNOT CARRY
    // ONE. `plans` has exactly two overage columns (`overage_rate` and
    // `overage_rate_second`, `apps/api/billing/models.py`) and the second is D-36's
    // TTS ladder — premium/value — not one of the two VOICE QUALITIES the self-serve card
    // prices; and every call is counted on the base rung anyway
    // (`apps/workers/pipeline.py:2743-2745` passes `tts_tier=BASE_OVERAGE_RUNG`, "one voice
    // quality, so the base rung on every call"). So the order form has one overage rate,
    // and a sentence promising a column per voice is a quote nobody could honour.
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
 * ⚠ **THE PAGE USED TO QUOTE THREE DIFFERENT "THE PRICE" IN SIX LINES** (audit, 8 Sep
 * 2026): the h1 said the dearest Clear rung, the lede said "from" the cheapest, the h2 said
 * "start today from" the cheapest again and the paragraph under it said the dearest — four
 * consecutive elements, four figures, and the one a buyer would actually pay first is the
 * one none of them led with. Nobody's first purchase is the largest pack. So the page
 * quotes a BAND, once per voice, both ends from the card — the shape the console's own
 * explainer settled on (`app/c/[slug]/billing/WhatCallsCost.tsx::rateBand`).
 *
 * The cheap end is a field the API publishes (`from_*_inr_per_min`, `cardFromRate`); this
 * end is not, so it is a COMPARISON across the rows the card sent. Nothing is computed:
 * `rateToTenThousandths` reads the digits into the API's own NUMERIC(12,4) scale and the
 * two are compared as integers, and what is rendered is the string the server sent.
 *
 * Its twin in the console (`billing/lots.ts::dearestRate`) is not imported and cannot be:
 * that module is `"use client"` and reads the SIGNED-IN card type, while this page is an
 * async server component reading `CreditPacksOut` off the public route. One accessor each,
 * both four lines, rather than a shared module that would drag a client hook into the
 * marketing tree.
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
  // rate nobody set. ⚠ The card is STATIC since D-547 (the catalogue, not the old
  // `self_serve_inr_per_min` console setting), so it moves on a deploy rather than on an
  // operator's save; the minute of edge cache on the route is now a cheap cache of a
  // constant rather than a staleness window on a live price.
  const rateCard = await fetchPublicRateCard();
  return (
    <MarketingPage>
      {/* THE PRICE IS THE HEADLINE, and this page used to bury it (6 Sep 2026).
          It opened with a box titled "Why there is no price on this page" — an apology
          served to somebody whose entire reason for arriving was to see a number, and
          published while the self-serve rate WAS live and the deepest credit pack already
          delivered a lower one. The managed-plan caveat is real and is kept, at the
          bottom, in one line, where a reader who needs it will look for it.
          `rateCard` is null only when the API cannot be reached; the fallback says so
          rather than printing a figure we cannot stand behind. */}
      <PageIntro
        eyebrow="Pricing"
        title={
          rateCard === null
            ? "You are billed for the minutes your agents actually talk"
            : `Talk time on the ${tierLabel(rateCard, "sarvam")} voice: ${bandSentence(rateCard, "sarvam")}`
        }
        lede={
          rateCard === null
            ? "Not per seat, not per agent, not per number — you pay for the minutes your agents actually talk. Our live rate card could not be loaded just now, so there is no figure on this page we can stand behind; reload in a moment."
            : `The ${tierLabel(rateCard, "cartesia")} voice, which costs us more to run, is ${bandSentence(rateCard, "cartesia")}. No monthly fee, no per-seat charge — you are billed for the minutes your agents actually talk, and credit does not expire.`
        }
      />

      {/* --- Self-serve rate card (D-545) --------------------------------------- */}
      <section id="self-serve" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Eyebrow index="00">Self-serve</Eyebrow>
          <h2 className="mt-4 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            {/* NO FIGURE HERE, DELIBERATELY. This heading used to say "Start today from
                ₹4.50 a minute" — a third price in six lines, and the cheapest rung of the
                ladder, which is the one nobody's first purchase is at. The band is
                overhead in the h1 and every rung is in the table below; a heading that
                re-quoted one end of it was the duplicate the audit found. */}
            {rateCard === null
              ? "Our self-serve rate"
              : "Prepaid credit, and the rate comes down as the pack gets bigger"}
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
                {/* THIS CARD IS PUBLISHED; A MANAGED PLAN IS QUOTED — and the page has to
                    say which is which, because it says both. The figures below are the
                    real ones and nobody has to ask for them; the negotiated arrangement
                    lower down is the one with no publishable number. It says nothing
                    about how an ACCOUNT is opened: `self_serve_signup_enabled` is a live
                    switch and the door that reads it is the homepage's, so a second
                    sentence about it here would be a second place to get it wrong (the
                    argument `components/marketing/faq.tsx` already makes).

                    ⚠ TWO CLAUSES WERE CUT ON 9 SEP 2026 AND NEITHER WAS REPLACED. "Buy
                    credit in advance and the rate comes down" is what the heading above
                    already says and what the table below now SHOWS as a falling row;
                    "credit does not expire" is in the lede, at the top of this page, in
                    those words. Two spellings of one fact is a defect even when both are
                    true (UX-DOCTRINE §5), and on a page the founder is asking to make
                    shorter the duplicate is the first thing to go. */}
                This is a published price, not a quote, and there is no minimum. The rates
                you bought at stay with that credit until it is spent.
              </p>
              <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                {/* "YOU CHOOSE IT AGENT BY AGENT" WAS FALSE IN THE CLIENT REALM, and this
                    is the register both surfaces now use. The voice IS per agent, but
                    changing it is ours (D-21) — the picker is mounted in the admin realm
                    only, and the client's own agent screen says so in these words
                    ("Your account manager can confirm it",
                    `app/c/[slug]/agents/panels/publishing.tsx`). A page that told a buyer
                    they would have the control would be selling one that is not there.

                    ⚠ "EACH AGENT SPEAKS WITH ONE OF TWO VOICES" WAS CUT because the
                    control immediately below is now two named voices with one selected —
                    the sentence described what the reader is looking at. */}
                A voice is set per agent rather than for the whole account — tell your
                account manager which voice each agent should speak with.
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

      {/* The caveat that used to open the page, in its right size and its right place:
          after the reader has seen what things cost. Managed-plan figures genuinely are
          not publishable — every money column on `plans` is nullable with no default and
          two of them record in their own comments that the figure is a founder decision —
          but that is a footnote to a price list, not a substitute for one. */}
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
            {/* ⚠ THIS USED TO SAY THE PRICE IS A CONVERSATION, ON A PAGE THAT PUBLISHES
                ONE. Both halves were true of DIFFERENT things and the page ran them
                together: the self-serve card above is published, and it is the MANAGED
                plan that is negotiated. It also asserted a deployment fact — that accounts
                are opened by hand — which `self_serve_signup_enabled` decides at runtime
                and the homepage door already reads. */}
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

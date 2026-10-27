"use client";

import {
  CalendarClock,
  Clock3,
  Lock,
  PhoneMissed,
  ReceiptText,
  Waves,
} from "lucide-react";
import type { ReactNode } from "react";

import { Section } from "@/components/console/section";
import { Disclosure } from "@/components/ui";
import { GST_STATUS_SENTENCE } from "@/lib/gstStatus";
import type { CreditPacks } from "@/lib/api/billing";
import { voiceNotOffered, voiceNotOfferedNotice } from "@/lib/api/rateCard";

import type { TierLabels } from "./lots";

/**
 * WHAT CALLS COST — the plain-language explainer, and the only place this console makes
 * a claim about how our pricing works.
 *
 * ## Why it exists at all
 *
 * A prepaid balance is a number a client cannot check. They can see ₹3,400 and they can
 * see it going down, and nothing on any screen ever told them the rule it goes down BY.
 * The competitor the founder benchmarked answers that question on the same page you buy
 * from, and it is the single best idea on their screen. This is our version of it.
 *
 * ## EVERY SENTENCE HERE IS A CLAIM ABOUT MONEY, SO EVERY SENTENCE HERE IS CITED
 *
 * Hard rule 11 does not stop at vendors: a figure in our own tree is a claim until somebody
 * opens the code that produces it, so the citation stays beside the sentence.
 *
 * 1. **TWO VOICE QUALITIES, CHOSEN PER AGENT.** The catalogue carries two qualities at two
 *    per-minute rates (`apps/api/billing/credit_packs.py`; D-547,
 *    `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` §2.2) and the choice is a property of the
 *    AGENT (plan §2.1, §3.3 — the tier is derived from the chosen voice's provider, so an
 *    agent cannot hold one and be billed the other). Which quality no agent can be put on is
 *    the server's answer for this deployment (`lib/api/rateCard.voiceNotOffered`: the
 *    cheaper rung on our own voices; on ThinnestAI, Studio until our voice key is on and its
 *    minute is attested, D-688, while Clear is sold on the band the console names, D-792),
 *    and this panel prints the server's sentence for it. Neither quality
 *    is a degraded tier — what you hear in a demo is what a customer hears at three in
 *    the morning.
 *
 * 2. **THE RATES ARE FIXED ON THE PURCHASE, AND CREDIT IS SPENT OLDEST FIRST.** Plan §2.1
 *    and §2.3 invariant 3: each purchase opens a LOT carrying the two rates it was sold at,
 *    those rates have no UPDATE path (a database trigger refuses one), and a debit consumes
 *    the oldest open lot first, splitting across lots at each lot's own rate. So a later
 *    change to our card cannot reprice credit somebody already owns, and a client can read
 *    which price is live off the lot list on this screen. Terms §6.1 states the same promise
 *    in the words the founder approved.
 *
 * 3. **Billed in 30-second steps** (D-681). The debit prices `rates.client_billed_minutes`
 *    — `ceil(seconds / 30) x 0.5` of the actual duration — and every statement and usage
 *    figure reads the same rounding off the ledger. Zero seconds bills nothing.
 *
 * 4. **A call nobody answers costs nothing.** Two independent floors, both read: the rupee
 *    figure is ₹0.00 at `minutes <= 0`, and `billing/service.charge_for_call` returns before
 *    touching the ledger at `amount_inr <= 0`, so no entry is even written.
 *
 * 5. **Credit lasts 12 months — and calls are not the only thing that spends it.** Terms
 *    6.1 (revision 19, D-840): a purchase's lot is stamped with `credit_lots.expires_at`
 *    when it is credited, the daily `expire_credit_lots` lapses what is left after it, and
 *    a lot bought before the switch has no term. The months come from the card
 *    (`credit_expiry_months`), so the claim follows the console setting. CALLS ARE
 *    NOT THE ONLY DRAWDOWN, and a claim that they are is contradicted two cards below on
 *    this same screen: a block of extra dashboard AI a person accepts is a `usage` debit on
 *    this wallet (`apps/api/billing/ai_quota.py`, one row, `ref = ai_assist:<YYYY-MM>`) and
 *    `WhereItWent` renders it as "Extra AI help", with a "Corrections" row beside it. A
 *    phone number's monthly rental is another debit (`billing/number_rental.py`, D-665),
 *    rendered as "Phone number rental".
 *
 * 6. **The GST position, stated as a benefit AND as a warning.** The sentence is the
 *    shared `GST_STATUS_SENTENCE` (D-659): a sole proprietorship below the registration
 *    threshold, not GST-registered, so no GST is charged and no tax invoice is issued — and
 *    so no input tax credit. Both halves are said here, and the warning is never behind the
 *    click.
 *
 * ## DENSITY — one line each, the sentence behind a click (founder, 4 Sep 2026)
 *
 * The claim is on a line; the paragraph that argues it is one click away in the console's
 * one disclosure mechanism (`Disclosure`, `variant="inline"` — UX-DOCTRINE §3 forbids a
 * second). §3's rule decides which half goes where: "the closed state carries the FACT; the
 * click buys the CONTROL". §8's absolute — a sentence that qualifies a money claim may never
 * be hidden — is why the GST line says both halves unopened, above the button that takes the
 * money.
 *
 * ## What it deliberately does not do
 *
 * It names no competitor and quotes nobody else's price. And it names no VENDOR: the two
 * qualities are called what the API calls them (`billing/rates.py::VOICE_TIER_LABELS`,
 * carried on the card), never "Sarvam" or "Cartesia" — which company synthesises a voice is
 * our business and must be able to change without a client-visible rename. When the card
 * carries no labels this panel prints no rates and no quality names at all, rather than a
 * pair of unattributed rupee figures a reader would assign to the wrong voice.
 */
export function WhatCallsCost({
  card,
  labels,
}: {
  /**
   * The pack card (`GET /v1/billing/topups/packs`), or `undefined` when this session may
   * not read prices (`staff` holds `wallet:read` and not `billing:read`) or it has not
   * loaded. The panel drops the sentences that need a figure rather than inventing one.
   */
  card: CreditPacks | undefined;
  /** What a client calls each quality, from the same card. */
  labels: TierLabels | undefined;
}) {
  const months = card?.credit_expiry_months ?? null;
  return (
    <Section title="What calls cost">
      {/* The per-minute rates themselves are on "Clear or Studio" above, from the server's
          comparison; this panel explains how they are charged. */}
      <p className="text-body text-ink-muted">
        Calling is charged out of your credit as you use it, and 1 credit is ₹1.
      </p>

      <div className="mt-3 border-t border-line/60">
        <Fact
          icon={<Waves className="h-4 w-4" aria-hidden />}
          claim={
            labels
              ? `Two voice qualities — ${labels.clear} and ${labels.studio} — and each agent speaks with one of them`
              : "Two voice qualities, and each agent speaks with one of them"
          }
        >
          {/* The client holds this control themselves (D-586): `PATCH /v1/agents/
              {agent_id}/voice` is a CLIENT-realm door, `agents:write` is on `owner` AND
              `staff`, and the picker is on their own agent screen
              (`app/c/[slug]/agents/panels/delivery.tsx`). Never send them to an account
              manager for a control two clicks away on a screen they already have. The card
              is NAMED so the sentence points at something a reader can find. */}
          The voice belongs to the agent, not to the account: a receptionist
          that answers all day and an outbound campaign can speak with different
          voices, and each call is charged at its own agent&rsquo;s rate. You
          choose it yourself on the agent&rsquo;s own screen, under &ldquo;How
          it sounds, and how long a call may run&rdquo;. Neither is a cut-down
          version of the other — what you hear in a demo is what your customers
          hear at three in the morning. {notOfferedSentence(card, labels)}
        </Fact>

        <Fact
          icon={<Lock className="h-4 w-4" aria-hidden />}
          claim="The rates you buy at are fixed on that purchase"
        >
          Each time you add credit, the two per-minute rates shown for that
          purchase are fixed on it and stay with that credit until you have
          spent it. If we change our rate card later, credit you already own is
          untouched. Your calls are charged against your oldest credit first, so
          when you top up at a better rate you finish the older credit before
          you reach it — the list above shows exactly what is left at each
          price. Moving an agent to the other voice costs you nothing and
          changes none of your credit: the same purchase is drawn down, at the
          other rate that was fixed on it when you bought it.
        </Fact>

        <Fact
          icon={<Clock3 className="h-4 w-4" aria-hidden />}
          claim="Calls are billed in 30-second steps"
        >
          Each call is rounded up to the next 30 seconds: a 10-second call is
          charged as half a minute, a 40-second call as one minute, and a
          three-minute call as exactly three.
        </Fact>

        <Fact
          icon={<PhoneMissed className="h-4 w-4" aria-hidden />}
          claim="A call nobody answers costs nothing"
        >
          Ringing out, engaged, or a number that never picks up: there is no
          talk time, so there is nothing to charge and no entry appears in your
          history.
        </Fact>

        <Fact
          icon={<CalendarClock className="h-4 w-4" aria-hidden />}
          claim={
            months ? `Credit you buy lasts ${months} months` : "What uses your credit"
          }
        >
          {/* Calls are not the only drawdown: a block of extra dashboard AI is one
              `credit_ledger` debit against this wallet (`apps/api/billing/ai_quota.py`) and
              a correction we post is another (`WhereItWent`&rsquo;s "Corrections" row), and
              that panel is two cards below this one. Without the card (staff, or still
              loading) the term is not stated rather than guessed. */}
          Your calls run it down, and so do the monthly rent for your phone
          numbers and a block of extra dashboard AI if you accept one — nothing
          else does.{" "}
          {months ? (
            <>
              Each purchase lasts {months} months from the day it is added, and
              any of it still unused then lapses and is not refunded. Your
              oldest credit is used first, and your list of purchases shows when
              each one lapses. Credit bought before 27 October 2026 does not
              expire.{" "}
            </>
          ) : null}
          If we ever billed you wrongly, the correction is posted here too, where
          you can see it.
        </Fact>

        <Fact
          icon={<ReceiptText className="h-4 w-4" aria-hidden />}
          claim="No GST, and no tax invoice"
        >
          {GST_STATUS_SENTENCE} The price you see is the price you pay, and a
          business that needs to claim input tax credit on this spend will not be
          able to.
        </Fact>
      </div>
    </Section>
  );
}

/**
 * One fact: the claim on a line, the argument behind a click.
 *
 * `headingLevel={3}` because this sits inside `Card`&rsquo;s body, under its `h2` — a
 * heading list that reads h2 "What calls cost" then h3 per claim is the containment that
 * is actually on the screen. The claim is the `title` and never a `subtitle`: §3 wants the
 * closed state to carry the fact, and on a strip built to remove text a second line under
 * every heading would put it straight back.
 */
function Fact({
  icon,
  claim,
  children,
}: {
  icon: ReactNode;
  claim: string;
  children: ReactNode;
}) {
  return (
    <Disclosure variant="inline" headingLevel={3} icon={icon} title={claim}>
      {children}
    </Disclosure>
  );
}

/** The server's sentence for the voice no agent can be put on, led by that voice's name. */
function notOfferedSentence(
  card: CreditPacks | undefined,
  labels: TierLabels | undefined,
): string | null {
  if (!card) return null;
  const tier = voiceNotOffered(card);
  const notice = voiceNotOfferedNotice(card);
  if (!tier || !notice) return null;
  return labels ? `${labels[tier]} — ${notice}` : notice;
}

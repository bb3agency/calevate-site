"use client";

import { Clock3, Infinity as InfinityIcon, Lock, PhoneMissed, ReceiptText, Waves } from "lucide-react";
import type { ReactNode } from "react";

import { Card, Disclosure, formatRupeeRate } from "@/components/ui";
import type { CreditPacks } from "@/lib/api/billing";

import { VOICE_TIERS, cheapestRate, dearestRate, type TierLabels } from "./lots";

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
 * Hard rule 11 does not stop at vendors: a figure in our own tree is a claim until
 * somebody opens the code that produces it. Each of these was read in the source before
 * being written down, and the citation is left beside the sentence so the next person
 * inherits the evidence instead of the conclusion.
 *
 * 1. **TWO VOICE QUALITIES, CHOSEN PER AGENT.** ⚠ **THIS PANEL USED TO SAY THE OPPOSITE,
 *    AND THE OPPOSITE IS NOW FALSE.** It read "one voice, one rate, every call", cited to
 *    `billing/rates.py`'s note that the premium/value ladder had been deleted — true when
 *    it was written and superseded by D-547 (`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`
 *    §2.2, and the six-pack two-rate catalogue in `apps/api/billing/credit_packs.py`). The
 *    catalogue now carries two qualities at two per-minute rates, the choice is a property
 *    of the AGENT (plan §2.1, §3.3: the tier is derived from the chosen voice's provider,
 *    so an agent cannot hold one and be billed the other) — though the CHOICE is not the
 *    client's to make in this realm: the picker is admin-only and changing a voice is ours
 *    (D-21), so what this panel promises is that they tell us, not that they set it. A new
 *    agent defaults to the cheaper one (§0 Q9) — a default that costs more per minute has to be a choice somebody
 *    made. The rationale that survives is the one that made "one voice" a selling point:
 *    neither quality is a degraded tier, and what you hear in a demo is what a customer
 *    hears at three in the morning.
 *
 * 2. **THE RATES ARE FIXED ON THE PURCHASE, AND CREDIT IS SPENT OLDEST FIRST.** Plan §2.1
 *    and §2.3 invariant 3: each purchase opens a LOT carrying the two rates it was sold at,
 *    those rates have no UPDATE path (a database trigger refuses one), and a debit consumes
 *    the oldest open lot first, splitting across lots at each lot's own rate. So a later
 *    change to our card cannot reprice credit somebody already owns, and a client can read
 *    which price is live off the lot list on this screen. Terms §6.1 states the same promise
 *    in the words the founder approved.
 *
 * 3. **Billed by the second.** `apps/workers/pipeline.py` meters `minutes = duration_s / 60`
 *    from `_billable_seconds` — the actual duration, floored at zero — and the debit prices
 *    exactly that. There is no rounding up to a 30- or 60-second block anywhere on the path.
 *
 * 4. **A call nobody answers costs nothing.** Two independent floors, both read: the rupee
 *    figure is ₹0.00 at `minutes <= 0`, and `billing/service.charge_for_call` returns before
 *    touching the ledger at `amount_inr <= 0`, so no entry is even written.
 *
 * 5. **Credits do not expire — but calls are not the only thing that spends them.**
 *    `credit_ledger` (migration `f170dbce6f47`) carries delta / reason / ref /
 *    balance_after / occurred_at / meta and NO expiry column; the balance is the sum of the
 *    deltas, and the only sweeping job in the tree sweeps idempotency records. ⚠ **THIS
 *    ENTRY USED TO END "nothing can take credit back except a refund", AND THE FACT BELOW
 *    IT USED TO SAY "nothing runs it down except your own calls".** Both were false in the
 *    same direction: a block of extra dashboard AI a person accepts is a `usage` debit on
 *    this wallet (`apps/api/billing/ai_quota.py`, one row, `ref = ai_assist:<YYYY-MM>`), and
 *    `WhereItWent` renders it as "Extra AI help" TWO CARDS BELOW this panel — with a
 *    "Corrections" row beside it. A claim contradicted by another panel on the same screen
 *    is the cheapest kind of wrong to find and the most expensive kind to be caught in.
 *
 * 6. **The GST position, stated as a benefit AND as a warning.** `billing/gst.py` is
 *    explicit: the legal person is a sole proprietor trading as Calevate, is NOT registered
 *    for GST and is not required to be at present turnover, so under CGST s.32 we may not
 *    collect tax and under Rule 49 what we issue is a BILL OF SUPPLY, which confers no input
 *    tax credit. Both halves are said here, and the warning is never behind the click.
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
  const band = card && labels ? rateBand(card) : undefined;
  return (
    <Card title="What calls cost">
      <p className="text-sm text-ink-muted">
        Calling is charged out of your credit as you use it, and 1 credit is ₹1.
        {band && " What a minute costs depends on the voice the agent speaks with, and on"}
        {band && " how big a pack you buy:"}
      </p>
      {/* A LIST rather than a sentence, because it is four figures in two pairs and a
          sentence makes the reader hold the first pair while reading the second. Each rate
          sits under the name of the quality it prices — never two bare numbers side by
          side, which a reader assigns to whichever voice they had in mind. */}
      {band && labels && (
        <dl className="mt-2 space-y-1 text-sm">
          {VOICE_TIERS.map((tier) => (
            <div key={tier} className="flex flex-wrap items-baseline gap-x-2">
              <dt className="font-medium text-ink">{labels[tier]}</dt>
              <dd className="tabular-nums text-ink-muted">
                <strong className="font-semibold text-ink">
                  {formatRupeeRate(band[tier].dearest)}
                </strong>{" "}
                a minute, down to{" "}
                <strong className="font-semibold text-ink">
                  {formatRupeeRate(band[tier].cheapest)}
                </strong>{" "}
                on the largest pack
              </dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-3 border-t border-line/60">
        <Fact
          icon={<Waves className="h-4 w-4" aria-hidden />}
          claim={
            labels
              ? `Two voice qualities — ${labels.sarvam} and ${labels.cartesia} — and each agent speaks with one of them`
              : "Two voice qualities, and each agent speaks with one of them"
          }
        >
          {/* ⚠ THIS SAID "YOU CHOOSE WHICH ONE EACH AGENT SPEAKS WITH", AND A CLIENT
              CANNOT. The voice picker is mounted in the admin realm only; changing an
              agent&rsquo;s voice is ours (D-21), which is why the client&rsquo;s own agent
              screen carries the fact and no control ("Your account manager can confirm
              it", `app/c/[slug]/agents/panels/publishing.tsx`). The per-agent part was
              true and is kept; the control was not. */}
          The voice belongs to the agent, not to the account: a receptionist that answers
          all day and an outbound campaign can speak with different voices, and each call is
          charged at its own agent&rsquo;s rate. Tell your account manager which voice you
          want an agent to speak with and we set it. Neither is a cut-down version of the
          other — what you hear in a demo is what your customers hear at three in the
          morning. A new agent starts on the cheaper voice, so nothing costs you more per
          minute unless you asked for it.
        </Fact>

        <Fact
          icon={<Lock className="h-4 w-4" aria-hidden />}
          claim="The rates you buy at are fixed on that purchase"
        >
          Each time you add credit, the two per-minute rates shown for that purchase are
          fixed on it and stay with that credit until you have spent it. If we change our
          rate card later, credit you already own is untouched. Your calls are charged
          against your oldest credit first, so when you top up at a better rate you finish
          the older credit before you reach it — the list above shows exactly what is left
          at each price. Moving an agent to the other voice costs you nothing and changes
          none of your credit: the same purchase is drawn down, at the other rate that was
          fixed on it when you bought it.
        </Fact>

        <Fact
          icon={<Clock3 className="h-4 w-4" aria-hidden />}
          claim="You pay for the seconds you actually talk"
        >
          A call is charged on its real length, second by second. A 40-second call is
          charged as 40 seconds — we do not round it up to a minute, or to a block of any
          other size.
        </Fact>

        <Fact
          icon={<PhoneMissed className="h-4 w-4" aria-hidden />}
          claim="A call nobody answers costs nothing"
        >
          Ringing out, engaged, or a number that never picks up: there is no talk time, so
          there is nothing to charge and no entry appears in your history.
        </Fact>

        <Fact
          icon={<InfinityIcon className="h-4 w-4" aria-hidden />}
          claim="Your credit never expires"
        >
          {/* ⚠ THIS SAID "NOTHING RUNS IT DOWN EXCEPT YOUR OWN CALLS", TWO CARDS ABOVE A
              PANEL THAT RENDERS "Extra AI help" AS ITS OWN DRAWDOWN ROW. A block of extra
              dashboard AI, accepted by a person at a modal naming the figure, is one
              `credit_ledger` debit against this wallet (`apps/api/billing/ai_quota.py`),
              and a correction we post is another (`WhereItWent`&rsquo;s "Corrections" row).
              Neither is a call, and both take credit off. What survives is the claim the
              fact is actually about: nothing EXPIRES and nothing is swept. */}
          Your calls run it down, and so does a block of extra dashboard AI if you accept
          one — nothing else does. It never expires and is never swept, so a large pack
          bought in a quiet month is still there in a busy one. If we ever billed you
          wrongly, the correction is posted here too, where you can see it.
        </Fact>

        <Fact
          icon={<ReceiptText className="h-4 w-4" aria-hidden />}
          claim="No GST is added, and we cannot issue a tax invoice"
        >
          Calevate is not registered for GST, so nothing is added on top — the price you
          see is the price you pay. The other side of that is real and worth knowing
          before you buy: what we can issue is a bill of supply, not a tax invoice, so a
          business that needs to claim input tax credit on this spend will not be able to.
        </Fact>
      </div>
    </Card>
  );
}

/**
 * The two ends of the ladder on each quality, or `undefined` when the card cannot supply
 * both.
 *
 * Both ends, because one is not the sentence: "from ₹4.50" is the largest pack's rate and
 * describes nobody's first purchase, while the entry rate alone hides the whole reason a
 * bigger pack is worth buying. `cheapestRate` is the server's own published minimum
 * (`from_*_inr_per_min`) and `dearestRate` is a comparison across the rows it sent — no
 * price is computed here.
 */
function rateBand(
  card: CreditPacks,
): Record<"sarvam" | "cartesia", { cheapest: string; dearest: string }> | undefined {
  const sarvamLow = cheapestRate(card, "sarvam");
  const sarvamHigh = dearestRate(card, "sarvam");
  const cartesiaLow = cheapestRate(card, "cartesia");
  const cartesiaHigh = dearestRate(card, "cartesia");
  if (!sarvamLow || !sarvamHigh || !cartesiaLow || !cartesiaHigh) return undefined;
  return {
    sarvam: { cheapest: sarvamLow, dearest: sarvamHigh },
    cartesia: { cheapest: cartesiaLow, dearest: cartesiaHigh },
  };
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

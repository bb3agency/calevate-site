"use client";

import { Clock3, Infinity as InfinityIcon, PhoneMissed, ReceiptText, Waves } from "lucide-react";
import type { ReactNode } from "react";

import { Card, formatRupeeRate } from "@/components/ui";

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
 * somebody opens the code that produces it. These five were each read in the source
 * before being written down, and the citation is left beside the sentence so the next
 * person inherits the evidence instead of the conclusion.
 *
 * 1. **One voice quality.** `apps/api/billing/rates.py`'s module docstring records that
 *    the premium/value VOICE ladder was deleted outright — "there is one voice quality
 *    now (Sarvam Bulbul v3), so there is one TTS rate and nothing to select or fall back
 *    to", and `TtsTier`, `billable_tier` and `tier_of_voice` were deleted rather than
 *    left unreachable. There is therefore no cheaper tier that sounds worse, and no
 *    choice for a client to get wrong.
 *
 *    AND IT IS THE VENDOR'S TOP MODEL, which is the half that makes this a selling point
 *    rather than a shrug, and it is FIRST in the list for that reason. `agents/voices.py`
 *    :30-35 carries the evidence, class VERIFIED-VENDOR-SDK: the Sarvam SDK's TTS enum is
 *    `Literal["bulbul:v2", "bulbul:v3"]` and Sarvam's own Model Catalogue lists ONLY
 *    `bulbul:v3` — v2 is the older, value model. We ship v3 to every account, so "one
 *    voice" and "the good voice" are the same sentence.
 *
 *    The naming is deliberate and the boundary is in the next paragraph: this says our
 *    voice is the best one the VENDOR sells, which is a fact about our own configuration
 *    and stays true when anybody else reprices. It does NOT say it beats a competitor's
 *    premium voice, because nothing in this repo has measured that.
 *
 *    ⚠ NOT TO BE CONFUSED WITH THE PLAN'S OVERAGE RUNGS. `billing/invoice.py`'s
 *    `_RUNG_WORDING` still says "premium voice"/"value voice"; those are two rate SLOTS
 *    on a managed plan (`plans.overage_rate` / `overage_rate_value`, the second NULL on
 *    every plan today) and a founder pricing lever, not a voice quality. Nothing in this
 *    component, and nothing this component links to, may imply a client picks a voice.
 *
 * 2. **Billed by the second.** `apps/workers/pipeline.py:2402` meters
 *    `minutes = duration_s / Decimal(60)` from `_billable_seconds` — the actual duration,
 *    floored at zero — and `billing/rates.prepaid_billed_inr` prices exactly that. There
 *    is no rounding up to a 30- or 60-second block anywhere on the path. It is a real
 *    advantage and we claimed it nowhere until this panel.
 *
 * 3. **A call nobody answers costs nothing.** Two independent floors, both read:
 *    `rates.prepaid_billed_inr` returns ₹0.00 at `minutes <= 0`, and
 *    `billing/service.charge_for_call` returns before touching the ledger at
 *    `amount_inr <= 0` — so no entry is even written. `workers/pipeline.py:3323` states
 *    the same fact from the other end: "a `no_answer`, `busy` or `failed` call
 *    legitimately has no cost and no transcript FOREVER".
 *
 * 4. **Credits do not expire.** `credit_ledger` (migration `f170dbce6f47`) carries
 *    delta / reason / ref / balance_after / occurred_at / meta and NO expiry column; the
 *    balance is the sum of the deltas (`billing/wallet.py`), and the only sweeping job in
 *    the tree (`workers/dispatcher.sweep_expired`) sweeps idempotency records. Nothing
 *    can take credit back except a refund the client asked for.
 *
 * 5. **The GST position, stated as a benefit AND as a warning.** `billing/gst.py` is
 *    explicit: the legal person is a sole proprietor trading as Calevate, is NOT
 *    registered for GST and is not required to be at present turnover, so under CGST
 *    s.32 we may not collect tax and under Rule 49 what we issue is a BILL OF SUPPLY,
 *    which confers no input tax credit. Both halves are said here. The upside is real —
 *    no 18% on top, the price shown is the price paid — and so is the cost, and a
 *    business that needs an input-credit invoice has to learn that BEFORE they buy,
 *    not from a refund request afterwards.
 *
 * ## What it deliberately does not do
 *
 * It names no competitor, compares to no competitor, and quotes nobody else's price.
 * A claim about someone else's product is unverifiable from here, ages the moment they
 * reprice, and reads as defensive on the screen a client is about to pay from.
 *
 * ## The rate
 *
 * `listRate` is the SERVER's `list_rate_inr_per_min` (`GET /v1/billing/topups/packs`),
 * rendered through `formatRupeeRate` at its full 4dp rate precision — a rate is not a
 * rupee amount and must not be rounded like one (`billing/service.rate_to_display`). It
 * is `null` for a session that may not read billing figures (`staff` holds `wallet:read`
 * and not `billing:read`), and the panel simply drops the one sentence that needs it
 * rather than inventing a number or hiding the other four facts.
 */
export function WhatCallsCost({ listRate }: { listRate: string | null }) {
  return (
    <Card title="What calls cost">
      <p className="text-sm text-ink-muted">
        {listRate === null
          ? "Calling is charged out of your credit as you use it. 1 credit is ₹1."
          : "Calling is charged out of your credit as you use it. 1 credit is ₹1, and a minute of talking costs "}
        {listRate !== null && (
          <strong className="font-semibold tabular-nums text-ink">
            {formatRupeeRate(listRate)}
          </strong>
        )}
        {listRate !== null &&
          " at the standard rate — a bigger pack brings that down. One rate, because there is one voice and it is the best one our speech provider makes."}
      </p>

      <ul className="mt-4 space-y-3">
        <Point
          icon={<Waves className="h-4 w-4" aria-hidden />}
          title="One voice, and it is the top one"
        >
          Every account gets the best voice our speech provider makes — Sarvam&rsquo;s
          newest one — and there is nothing above it to upgrade to and nothing cheaper
          below it that sounds worse. One voice, one rate, every call. What you hear in a
          demo is what your customers hear at three in the morning.
        </Point>

        <Point
          icon={<Clock3 className="h-4 w-4" aria-hidden />}
          title="You pay for the seconds you actually talk"
        >
          A call is charged on its real length, second by second. A 40-second call is
          charged as 40 seconds — we do not round it up to a minute, or to a block of any
          other size.
        </Point>

        <Point
          icon={<PhoneMissed className="h-4 w-4" aria-hidden />}
          title="A call nobody answers costs nothing"
        >
          Ringing out, engaged, or a number that never picks up: there is no talk time, so
          there is nothing to charge and no entry appears in your history.
        </Point>

        <Point
          icon={<InfinityIcon className="h-4 w-4" aria-hidden />}
          title="Your credit never expires"
        >
          Nothing runs it down except your own calls, and nothing takes it back. Buy a
          large pack in a quiet month and it is still there in a busy one.
        </Point>

        <Point
          icon={<ReceiptText className="h-4 w-4" aria-hidden />}
          title="No GST is added, and we cannot issue a tax invoice"
        >
          Calevate is not registered for GST, so nothing is added on top — the price you
          see is the price you pay. The other side of that is real and worth knowing
          before you buy: what we can issue is a bill of supply, not a tax invoice, so a
          business that needs to claim input tax credit on this spend will not be able to.
        </Point>
      </ul>
    </Card>
  );
}

/**
 * One fact. A `<li>` with a heading and a sentence, because a screen reader moving by
 * list item should hear the claim before the explanation — and because a client scanning
 * on a phone reads the five headings and stops.
 */
function Point({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 shrink-0 text-brand">{icon}</span>
      <span className="text-sm">
        <strong className="font-semibold text-ink">{title}.</strong>{" "}
        <span className="text-ink-muted">{children}</span>
      </span>
    </li>
  );
}

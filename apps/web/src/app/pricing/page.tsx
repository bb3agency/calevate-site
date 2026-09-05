import type { Metadata } from "next";
import Link from "next/link";

import { Check, Info, Receipt, ShieldCheck, Wallet } from "lucide-react";

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
 * `/pricing` — the SHAPE of the bill, and deliberately not a number.
 *
 * ## ⚠ WHY THERE IS NO PRICE ON THE PRICING PAGE
 *
 * Because there is no price to publish. Commercial terms are negotiated per client (D-11),
 * and the `plans` table is per-tenant with every money column nullable: `setup_fee`,
 * `monthly_fee`, `included_min`, `overage_rate`, `overage_rate_value` and
 * `llm_model_surcharge` (`apps/api/billing/models.py:217-258`). There is no default rate
 * card in this repository, and the two columns that came closest say so in their own
 * comments — `overage_rate_value` and `llm_model_surcharge` both record that the number "is
 * a founder decision" and that no default may be invented, because TRD §10.1's cost bands
 * are explicitly unmeasured.
 *
 * So a figure typed onto this page would be a quote nobody can honour, invented by the
 * person writing marketing copy. That is precisely the failure hard rule 11 exists for, and
 * it is worse here than anywhere else on the site because a price is the one claim a buyer
 * relies on before they have met us.
 *
 * **THE FIGURES ARE THE FOUNDER'S TO SUPPLY.** Until they are, this page publishes what it
 * genuinely knows — which is a great deal: what you are billed FOR, how a plan is shaped,
 * how prepaid credit works, what stops a bill running away, and how the invoice is
 * assembled. A buyer can tell from this page whether the commercial model suits them, which
 * is most of what a pricing page is for.
 *
 * ## The ONE published number lives on /roi, not here
 *
 * `self_serve_inr_per_min` (`packages/shared/src/calevate_shared/config.py:1284`) is a real,
 * published self-serve rate and the ROI calculator uses it as the INPUT to a comparison the
 * buyer drives. It earns its place there by being a tool rather than a tag. Repeating it
 * here as "our price" would turn it back into the thing this page refuses to be, because
 * a managed client's rate is not that number.
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
      "The minutes your agents actually spend on calls. Not seats, not agents, not " +
      "numbers configured — a quiet month costs less than a busy one because there is " +
      "nothing to carry between them.",
  },
  {
    title: "The voice you chose",
    body:
      "There are two voice tiers, and a plan can quote them at different rates. Every " +
      "call is stamped with the one it used, so a month is priced from what happened " +
      "rather than from what was configured at the end of it.",
  },
  {
    title: "The language model you chose",
    body:
      "If you pick a dearer model than the one your plan's rate is struck against, the " +
      "difference is a per-minute surcharge on the minutes that actually used it. Stay on " +
      "the standard model and there is no surcharge at all.",
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
      "The standing part of the arrangement, agreed with you before anything is signed.",
  },
  {
    term: "Talk time included in it",
    detail:
      "A bundle of minutes that comes with the monthly fee, so ordinary months are " +
      "covered by the standing charge.",
  },
  {
    term: "A rate for anything past the bundle",
    detail:
      "Per minute, applied to the minutes over the included allowance — and quoted " +
      "separately for the cheaper voice tier if your plan offers one.",
  },
  {
    term: "A start date the plan is priced from",
    detail:
      "A plan carries the period it is in effect for, so a price change agreed today " +
      "does not silently re-price last month. Re-open an old invoice and it says the same " +
      "thing it said the first time.",
  },
];

export default function PricingPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Pricing"
        title="You are billed for the minutes your agents actually talk"
        lede="Not per seat, not per agent, not per number. This page is the shape of the bill and how it is put together; the figures are agreed with you, because a number published here would be a quote nobody could honour for every business."
      />

      {/* --- Why no number ------------------------------------------------------ */}
      <section className="border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <div className="flex items-start gap-3 rounded-2xl border border-brand/40 bg-brand-soft/30 p-5 sm:p-6 dark:bg-brand-strong/10">
            <Info
              aria-hidden
              className="mt-0.5 h-5 w-5 shrink-0 text-brand-strong dark:text-brand-bright"
            />
            <div>
              <h2 className="text-[17px] font-semibold text-ink">
                Why there is no price on this page
              </h2>
              <p className="mt-2 max-w-2xl text-base text-pretty text-ink-muted">
                What a business pays depends on how much it calls and gets called, which
                voice it uses and which language model it runs on — so we quote it for your
                business rather than publishing one number and changing it for every client.
                We would rather say that plainly than print a figure we would have to walk
                back on the first call.
              </p>
              <p className="mt-3 max-w-2xl text-base text-pretty text-ink-muted">
                What you can do without talking to anybody is put your own numbers into the{" "}
                <Link href="/roi" className={INLINE_LINK}>
                  cost comparison
                </Link>
                . It runs at our published self-serve rate and shows every assumption on
                both sides, including the ones that argue against us.
              </p>
            </div>
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
            Every call writes a usage record of its own, with the rate that applied to it,
            at the moment it happened. Those records are append-only: a correction is a new
            entry rather than an edit, so a bill can be explained line by line months later.
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
                    is the ONE gate that stops outbound. */}
                An account can run on credit you top up in advance. You can see the balance,
                the ledger it came out of, and the payment that failed last night — and when
                the credit is exhausted, outbound calling stops rather than continuing on to
                a bill you did not agree to.
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
                A month&apos;s invoice is assembled from those usage records at the plan that
                was in effect for that month, with GST worked out on it. It reads the same
                today as it will next year, because it is derived from what happened rather
                than stored as a summary.
              </p>
            </section>
          </div>
          <p className="mt-8 max-w-2xl text-sm text-ink-faint">
            All amounts are held as exact decimal rupees end to end — never as floating-point
            numbers, which is how a bill ends up a paisa out and nobody can say why.
          </p>
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
            Accounts are opened by hand with you rather than online, which is also why the
            price is a conversation. It is a short one:{" "}
            <Link href="/roi" className={INLINE_LINK}>
              bring your own numbers
            </Link>{" "}
            and we will tell you where we land against them.
          </p>
        </div>
      </section>

      <ClosingCta line="Ask us what it would cost for your call volume" />
    </MarketingPage>
  );
}

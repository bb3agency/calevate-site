"""Dashboard AI: what it costs us, what a client gets free, and what happens at the
ceiling (D-127 — G-3, G-4, G-5).

G-3 puts ONE Calevate-owned credential behind every client's dashboard assist and absorbs
the cost — an Azure OpenAI key since D-410, where it was a Gemini one. Three things follow
from that sentence and this module is all three:

- **absorbed is not unmetered.** Every assist lands in `usage_events` under its own unit
  types, per tenant, priced with what it cost US — so "which client is expensive" is a
  query and not an argument (D-12's whole point about metering not being retrofittable).
- **absorbed needs a ceiling, or it is a blank cheque.** The ceiling is counted in
  RUPEES, per tenant per IST billing month, because rupees are what actually protect us:
  one 1M-token context costs what a hundred autofills do, so a request count is a
  ceiling that varies by two orders of magnitude depending on what people paste in.
- **and one client's ceiling protects nothing against a hundred clients**, so there is a
  second, platform-wide brake on our own key (`platform_brake`, below).

WHY THE SCREEN SHOWS BOTH A COUNT AND A CEILING, AND WHICH ONE IS REAL
----------------------------------------------------------------------
A rupee ceiling does the work; "82 of about 416 assists used" is what an owner can plan
around. Nobody can reason about ₹41.7 of ₹100 of language-model inference. So the count
is published as an ESTIMATE and says so — `requests_included` is the ceiling divided by
`assist_nominal_inr(model)`, a reference price, and the word "about" is in the copy on the
screen rather than only in this comment. The number that blocks is always the rupee one.

(That 416 is `self_serve`'s ₹100 ceiling at `gpt-4o-mini`'s price, and it has now moved
THREE times on model decisions alone — 3.1 Flash-Lite, 2.5 Flash, and now D-410's Azure
OpenAI pair. Each move is exactly the drift a worked example in prose accumulates while
the code stays right, which is why the figure is recomputed here rather than generalised
away: the sentence is about what a person can plan around, and "the ceiling divided by a
reference price" is not that sentence.)

**AND IT NOW MOVES WITHOUT A DEPLOY.** `Settings.azure_openai_model` switches between
`gpt-4o-mini` and `gpt-4.1-mini` live, and an assist on the second costs 2.7x the first —
so the same ₹100 is about 416 assists or about 158 depending on a console value. That is
why the reference price is a FUNCTION OF THE MODEL and why `AiQuota` carries the model it
was priced with: an estimate that quoted the default model's price while the deployment
ran the other one would over-promise by 2.7x on a screen a client plans around.

WHERE THE CEILING LIVES, AND THE MECHANISM THIS DELIBERATELY DOES NOT DUPLICATE
-------------------------------------------------------------------------------
`AI_QUOTA_INR` is a per-TIER platform term: every tenant on a tier gets the same
included allowance, because that is what "one key, cost absorbed" means today — it is
not a negotiated commercial term, and nobody has priced one.

So it is NOT a `plans` column, and the reasoning matters more than the conclusion:
`plans` is resolved by valid time (`billing/plans.py::plan_in_effect_sql` — the half-open
window, the total order, `month_pricing_instant`), and that is THE mechanism for anything
a client and Calevate agreed. The day a founder prices per-tenant AI quota, it becomes a
nullable `plans` column resolved by that same function and defaulting to the tier value
here when NULL — exactly the shape `plans.overage_rate_value` already has. What is
refused is a SECOND effective-dating mechanism for one more number, and what is refused
just as firmly is a column with no writer (`billing/terms.py` is the only writer of a
`plans` row, and a term no operator can type is a defect that looks like a feature).

The TIER itself comes from `billing.service.plan_tier_of`, the one reader of
`organizations.plan_tier` — the same one `usage_summary` and `charge_for_call` use.

PAST THE CEILING: A BLOCK, A MODAL, AND EXACTLY ONE LEDGER ROW (G-4, G-5)
-------------------------------------------------------------------------
At the ceiling the feature BLOCKS. It does not degrade, it does not silently bill, and
it does not queue: `require_ai_assist` raises, the screen opens a modal naming the exact
rupee figure, and **nothing leaves the wallet until a person presses accept**.

What they accept is a FIXED BLOCK (`AI_OVERAGE_BLOCK_INR`), debited once, as ONE
`credit_ledger` row with reason `usage` and `ref = ai_assist:<YYYY-MM>` — an existing
reason, no new table, deduped by the existing `ux_credit_ledger_tenant_reason_ref`
(D-63's key shape). Three alternatives were considered and each fails on hard rule 4:

- *bill each assist as it happens* — G-4 rules it out in words ("no per-request
  billing"), and it would put one ledger row per button press on a client's statement;
- *one row per month that grows as they spend* — an UPDATE on an append-only ledger,
  which the `calevate_forbid_mutation` trigger refuses outright;
- *a row per assist netted at month end* — the same thing with extra steps, and it
  charges money before anyone agreed to it.

A block is also the only shape that lets the modal state a TRUE figure before the click:
"₹500 now" is checkable; "about ₹0.05 per assist for the rest of the month" is not.
The cost of the shape, stated rather than hidden: an unused part of the block is not
refunded and does not roll into next month. The screen says so in those words.

ONE BLOCK PER TENANT-MONTH, and that is the exposure limit rather than a UI convenience.
When it is spent the feature blocks again and the client is told the month is finished —
not offered a second modal. So the worst case for a client who mis-clicks is one block,
and the worst case for US is the included quota plus one block per tenant.

AND NOT IN THE LAST HOUR OF ONE (`LAST_SALEABLE_MINUTES`). The block expires with the
month, so on the 31st at 23:59 it is the same bargain arithmetically and not the same
bargain at all — and the same guard closes a race in which the debit lands under a month
key the next read no longer looks for.

**Prepaid tiers only** (`self_serve`, `trial`), which is the split
`billing.service.charge_for_call` and the top-up panel already make: a managed client is
invoiced against a retainer, their wallet is not the mechanism that pays for anything
(`usage_summary`: "their wallet must not shorten their runway any more than it blocks a
dial"), and this product has no way to put an ad-hoc charge on a DERIVED invoice without
inventing an invoice line nobody priced. A managed client at the ceiling is therefore
told the reset date and offered a CONVERSATION with their account manager — not an
add-on, because the add-on does not exist. Closed by a founder pricing AI overage on a
retainer, not by code.

THE METERING KEY IS OURS (`new_assist_ref`, `ASSIST_REF_PREFIX`). The writer's
idempotency is a switch that turns metering OFF, so a key a request could carry in is a
way to spend our credential for free; double-click protection belongs at the endpoint and
before the model is called.

Money is NUMERIC INR throughout (hard rule 7). No float is constructed in this module,
every rupee that reaches a response goes through `billing.service.to_paise`, and the
per-token prices this all rests on are in ONE table with their source
(`billing/rates.py::llm_inr_per_ktok`) rather than typed into four unfalsifiable
constants.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.models import AI_ASSIST_UNIT_TYPES
from apps.api.billing.plans import ist_month_end, parse_billing_month

# `PREPAID_TIERS` IS IMPORTED, NOT RESPELLED, and this module used to hold its own copy.
# That constant's whole justification is written above its definition — "a fourth tier
# added to one of them and not the others is a wallet that stops draining" — and a second
# literal here made this module one of the ones that would not have been told: it gates
# `extra_unavailable`'s `not_prepaid` and `purchase_ai_overage`'s refusal, i.e. WHO MAY
# SPEND MONEY. Two spellings of one money predicate is the D-103 shape, and it agreed with
# the original only by coincidence of nobody having edited either.
from apps.api.billing.rates import PREPAID_TIERS, llm_inr_per_ktok
from apps.api.billing.service import (
    _IST_MONTH,
    _IST_MONTH_WINDOW,
    _month_bounds,
    current_billing_month,
    find_entry_by_ref,
    lock_tenant_credits,
    plan_tier_of,
    record_entry,
    to_paise,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

# --- the numbers ---------------------------------------------------------------
#
# THESE ARE PRODUCT TERMS AND THEY ARE THE FOUNDER'S TO MOVE. They are constants rather
# than console fields on purpose: `platform_config.managed_fields()` computes the
# console's editable set from `Settings.model_fields`, so a field named
# `ai_quota_inr` would be editable from a web form the day it is declared — and what it
# governs is how much of OUR money a bug can spend. That is the doctrine
# `check_bootstrap_keys` applies to `APP_ENV` (D-95 §4) and `check_model_residency`
# applies to `AZURE_LOCATION` (D-410 — this named "the Vertex region (D-127)", which is
# the leg D-410 superseded; the guard's subject moved with it and this cross-reference
# did not), applied to the third value whose change is a commercial event wearing a
# config diff. Moving one is a code change with a review.

#: Included dashboard-AI allowance per tenant per IST billing month, in rupees, by plan
#: tier. Managed clients get the most because they pay the most; a trial gets enough to
#: form an opinion of the feature and not enough to be a business's whole workload.
#:
#: **`trial` MOVED FROM ₹25 TO ₹40 ONE MODEL DECISION AGO, AND D-410 IS WHY IT STAYS.**
#: ₹25 was set against a reference assist of ₹0.33475 and stopped clearing
#: `test_no_product_constant_is_out_by_an_order_of_magnitude`'s "enough to form an opinion"
#: floor (50 assists) the moment the model changed under it — a prospect told the trial is
#: over halfway through evaluating the feature is the one failure a trial tier cannot have.
#: ₹40 was chosen for HEADROOM rather than to clear the assertion, and that headroom is
#: what is now being spent.
#:
#: **THE BINDING CONSTRAINT IS NO LONGER THE SHIPPED MODEL — IT IS THE DEAREST SELECTABLE
#: ONE.** `Settings.azure_openai_model` is live, so a tier's allowance has to buy enough
#: assists on `gpt-4.1-mini` as well as on `gpt-4o-mini`, and the test walks both:
#:
#:   * `gpt-4o-mini`  — a reference assist is ₹0.15760, so ₹40 buys **253.8 assists**;
#:   * `gpt-4.1-mini` — a reference assist is ₹0.42115, so ₹40 buys **95.0 assists**.
#:
#: 95.0 is 1.9x the floor, so the trial survives an operator flipping the switch with no
#: constant moving. What D-410 also removed is the clock that used to sit on this note: the
#: old figures came with a DATED retirement (16 Oct 2026) and a dated end of introductory
#: pricing, and neither replacement was likely to be cheaper. There is no dated Azure
#: constant, so the next move of this number will be a price change rather than a deadline.
#:
#: WHAT A TRIAL TENANT SEES is `requests_included`, which divides by the NOMINAL (the
#: reference cost times the over-statement margin) and therefore reads **about 166** on
#: `gpt-4o-mini` and **about 63** on `gpt-4.1-mini` — deliberately below the real counts
#: above, because the margin exists to under-promise. Every one of those four numbers
#: clears 50, which is what makes the screen and the gate agree on both models.
AI_QUOTA_INR: Final[dict[str, Decimal]] = {
    "managed": Decimal("250.00"),
    "self_serve": Decimal("100.00"),
    "trial": Decimal("40.00"),
}

#: One thousand tokens — the unit `ai_assist_ktok_*` counts, because a per-token price is
#: not representable in NUMERIC(12,4) (`billing/models.py::AI_ASSIST_UNIT_TYPES`).
TOKENS_PER_KTOK: Final = Decimal("1000")


def ktok(tokens: int) -> Decimal:
    """Tokens as thousands, exactly. `Decimal` division by a `Decimal` — never `/ 1000.0`,
    which would put a metering quantity through a binary float."""
    return Decimal(tokens) / TOKENS_PER_KTOK


#: WHERE THE PER-TOKEN PRICE WENT (D-400, repriced by D-410):
#: `billing/rates.py::llm_inr_per_ktok(model)`, which this module now calls.
#:
#: It lived here as `ASSIST_LIST_PRICE_INR_PER_KTOK` — two INR literals with the exchange
#: rate already folded in — for as long as the dashboard assist was the only thing this
#: repository paid a language model for. D-400 ended that: the founder moved the IN-CALL
#: LLM leg onto the same paid account, so TRD §10 prices the same model at a different
#: point in the same pipeline, and a price constant that has already multiplied dollars by
#: an exchange rate cannot be corrected when either half moves. That is the D-103 / D-105
#: shape exactly, arriving on the money axis.
#:
#: So there is ONE statement of the vendor's dollar price
#: (`LLM_MODELS[model].price`), ONE exchange rate
#: (`rates.LIST_PRICE_USD_INR`), and ONE rupee table derived from them for every reader.
#: D-410 added the second axis: that table is keyed by MODEL, so the accessor takes one
#: and nothing in this module prices an assist without saying which model ran it.

#: The reference assist this estimate is built on: tokens in, tokens out. Deliberately
#: generous on BOTH legs, and MODEL-INDEPENDENT — the same reference workload is priced
#: against whichever model is configured, which is what makes the two published estimates
#: comparable.
#:
#: Input carries the response schema as well as the prompt and the transcript (a 30-field
#: schema with descriptions is not free). OUTPUT is generous because everything the model
#: emits bills at the output rate, which is 4x the input rate on both Azure models — so an
#: estimate that under-counted output would be wrong in the expensive direction. On Gemini
#: this line also had to carry THINKING tokens, which that vendor billed at the output rate
#: and reported separately; neither `gpt-4o-mini` nor `gpt-4.1-mini` is a reasoning model,
#: so there is no separate hidden leg to fold in — the generosity is kept anyway, because
#: an over-statement on this number under-promises on a screen and that is the safe
#: direction (`NOMINAL_ASSIST_MARGIN` makes the same argument).
REFERENCE_ASSIST_TOKENS: Final = {"in": 5_000, "out": 1_500}

#: How much dearer than the reference assist the published count assumes an assist is.
#: The error has a CHEAP direction and an expensive one and they are not symmetric: too
#: LOW a nominal prints "about 555 assists" for a month that turns out to hold 300, which
#: is a promise on a screen; too high prints 200 for a month that holds 550, which is a
#: pleasant surprise. So the margin is over-statement, and it is a factor rather than a
#: rounding so that it survives a price change.
NOMINAL_ASSIST_MARGIN: Final = Decimal("1.5")


def reference_assist_cost_inr(model: str) -> Decimal:
    """What one REFERENCE assist costs on `model` at list price, exactly.

    Not a charge — the input to the published estimate, and the number
    `tests/ai_quota_test.py` holds every product constant in this module to within an
    order of magnitude of, ON EVERY SELECTABLE MODEL rather than on the shipped default.

    `model` is REQUIRED and has no default (D-410, and `billing/rates.py`'s section
    comment argues it at length): the two models differ by 2.7x and the switch between
    them is a live console value, so a silent default here would put the wrong price under
    every ceiling justification and every "about N assists" on a screen.
    """
    price = llm_inr_per_ktok(model)
    return (
        ktok(REFERENCE_ASSIST_TOKENS["in"]) * price["in"]
        + ktok(REFERENCE_ASSIST_TOKENS["out"]) * price["out"]
    )


def assist_nominal_inr(model: str) -> Decimal:
    """The reference PRICE of one assist on `model`, used ONLY to turn a rupee ceiling
    into the "about N assists" a person can plan around.

    It is not a price anything is charged at, and no rupee figure on any screen is derived
    from it — the estimate it feeds is rendered with the word "about" beside it. ₹0.24 on
    `gpt-4o-mini`; ₹0.63 on `gpt-4.1-mini`.

    DERIVED, NOT TYPED, and that is the fix rather than the value: it shipped as a bare
    `Decimal("0.50")` whose only justification was the phrase "a few thousand tokens in
    and a few hundred out", which is unfalsifiable — it is equally consistent with ₹0.05
    and ₹5.00, and a ceiling wrong by 100 times is a product defect nobody would have
    caught by reading it. It now comes out of the published price and a stated reference
    assist, so the arithmetic is on the page and the number moves when the price does.

    **AND IT IS A FUNCTION RATHER THAN A `Final` FOR THE SAME REASON, TAKEN ONE STEP
    FURTHER (D-410).** A module-level constant is computed once, at import, from whatever
    the shipped default happens to be — so an operator flipping `Settings.azure_openai_model`
    to the 2.7x model would leave every screen quoting an assist count 2.6x too generous
    until somebody redeployed, and nothing would have looked wrong. Deriving it per model
    is what makes the estimate describe the model that will actually serve the next
    assist. Callers get the model from `AiQuota.assist_model`, which `read_ai_quota`
    stamps from the live setting.

    Quantized through `to_paise` because it is a rupee figure a person reads, not a unit
    price a ledger stores.
    """
    return to_paise(reference_assist_cost_inr(model) * NOMINAL_ASSIST_MARGIN)


#: What the modal offers past the ceiling, debited once per tenant-month.
#:
#: WHAT IT ACTUALLY BUYS, stated because the note here used to say "two blocks' worth of
#: assists on the smallest tier" and that is not a description of any quantity: at the
#: nominal it is about 2,083 assists on `gpt-4o-mini` and about 793 on `gpt-4.1-mini` —
#: five times a `self_serve` month's whole allowance and about thirteen times a `trial`
#: one, on EITHER model, because the block and the allowances are all rupee figures and
#: the model cancels out of the ratio. So it is not a small top-up on the small tiers, and
#: it comes out of the CALLING credit, which is the balance that dials.
#:
#: ⚠ **A trial tenant can therefore convert about a year's worth of AI allowance out of
#: the credit they need to make calls, in one click.** `record_entry(allow_negative=False)`
#: stops the wallet going under and the modal states the amount, so nothing here is
#: hidden or unbounded — but the size of the block relative to the smallest tier is a
#: PRICE, and a price is the founder's. It is left where they set it rather than quietly
#: scaled per tier by an agent; what is fixed here is the claim about it.
AI_OVERAGE_BLOCK_INR: Final = Decimal("500.00")

#: The brake on OUR key, across every tenant, per IST billing month. Independent of every
#: tenant's quota by construction: a hundred tenants each inside their own ceiling is
#: still a hundred ceilings of our money, and the failure this exists for — a retry loop
#: in a worker, a prompt that grew a zero — does not respect a per-tenant boundary.
#:
#: HOW IT IS RELEASED, said here rather than discovered at 3am: it clears when the IST
#: month rolls over, and before that ONLY by raising this constant — a code change with a
#: review. There is deliberately no button. A spend brake a console can lift is a spend
#: brake, and the run that tripped it is exactly the run nobody wants a tired person
#: waving through. What a released brake costs is bounded by the same constant on the
#: next tick, which is not true of a switch.
PLATFORM_AI_BRAKE_INR: Final = Decimal("25000.00")

#: How full the month may get before an operator is told, as a fraction of the brake.
#:
#: THE BRAKE USED TO ANNOUNCE ITSELF ONLY BY REFUSING SOMEBODY. That claim was checked
#: and it is true as far as it goes — `require_ai_assist` raises `kind="transient"`,
#: which `core/errors.install_error_handlers` turns into a 503 and an `alert()` — but it
#: is REACTIVE twice over: the first operator signal is a client already being refused,
#: and it never fires at all on a quiet weekend when the spend is a runaway worker rather
#: than a person clicking. The number an operator actually needs is "how close are we",
#: and nothing anywhere read `platform_ai_spend`.
#:
#: So the WRITER announces it, on the bump that crosses the line, using the counter's own
#: returned total: crossed-exactly-once needs no extra state and no second table, because
#: "was it under before and over after" is a fact the UPDATE already knows. At 80% there
#: is a fifth of the month's budget left to investigate in, which is the difference
#: between an operator with a decision and an operator with an incident.
PLATFORM_BRAKE_WARN_AT: Final = Decimal("0.80")

#: The `credit_ledger.ref` namespace for the one overage row per tenant-month. `reason`
#: is part of the key too (`find_entry_by_ref`), so this cannot collide with the call ids
#: `charge_for_call` writes under the same reason.
OVERAGE_REF_PREFIX: Final = "ai_assist"

#: `meta.kind` on both the ledger row and the usage rows, so a reader who finds one
#: knows what produced it without joining anything.
OVERAGE_META_KIND: Final = "ai_assist_overage"
ASSIST_META_KIND: Final = "ai_assist"

QuotaState = Literal["within", "ceiling_reached", "exhausted", "platform_paused"]

#: Why the extra block is not on offer. `None` means it IS.
ExtraUnavailable = Literal[
    "not_at_ceiling", "already_purchased", "not_prepaid", "platform_paused", "month_ending"
]

#: The refusal each reason produces when a caller posts anyway: (code, detail,
#: remediation). ONE table, so "the screen never offers a purchase the route refuses" is a
#: mapping a test can walk rather than a sentence in a docstring, and so the wording
#: cannot drift between the reason and the refusal. Every entry ends by saying that
#: nothing has been charged, because that is the first thing a person wants to know when
#: a money dialog answers with an error.
EXTRA_REFUSAL: Final[dict[str, tuple[str, str, str]]] = {
    "platform_paused": (
        "ai_paused_platform_wide",
        "AI help is paused across Calevate right now, so there is nothing to add to. "
        "Nothing has been charged.",
        "Try again later, or ask your account manager for an update.",
    ),
    "month_ending": (
        "ai_extra_month_ending",
        "This month's AI help is about to reset, so there is no point adding to it now. "
        "Nothing has been charged.",
        "Wait for the new month to start — the included allowance comes back within the "
        "hour, and it is larger than this.",
    ),
    "not_prepaid": (
        "ai_extra_not_available",
        "Extra AI help is not something this account can buy directly — it is billed "
        "with your plan. Nothing has been charged.",
        "Talk to your account manager to add more AI help this month.",
    ),
    "not_at_ceiling": (
        "ai_quota_not_reached",
        "This account still has included AI help left this month, so there is nothing to "
        "add yet. Nothing has been charged.",
        "Use the included allowance first; we will ask again at the limit.",
    ),
}


def overage_ref(month: str) -> str:
    """The idempotency key for the one overage row of a tenant-month.

    Content-addressed over the MONTH and nothing else, which is what makes a double-click
    a no-op rather than a second ₹500 (the argument `billing.service.adjustment_ref`
    makes at length). It deliberately does NOT carry the amount: a key of
    `ai_assist:2026-08:500.00` would let a client who reloads into a changed
    `AI_OVERAGE_BLOCK_INR` buy a second block in the same month, which is exactly the
    exposure "one block per tenant-month" exists to bound.
    """
    return f"{OVERAGE_REF_PREFIX}:{month}"


# --- what a tenant's month looks like -------------------------------------------


@dataclass(frozen=True, slots=True)
class AiQuota:
    """One tenant's dashboard-AI month: what they used, what they have, what they may do.

    Every rupee field is an exact `Decimal` and stays one until the route stringifies it
    (hard rule 7). The derived properties are properties rather than stored fields so
    that no caller can be handed a state that disagrees with the numbers beside it.
    """

    month: str
    plan_tier: str
    #: The tier's included allowance for the month.
    included_inr: Decimal
    #: What this tenant's assists have cost US this month, summed from `usage_events`.
    used_inr: Decimal
    #: Distinct request keys this month — the number the screen counts in "82 of ~500".
    requests_used: int
    #: The block already bought this month, or zero. Read from `credit_ledger`, so the
    #: wallet row IS the record of the acceptance and there is no second state to keep
    #: in step with it.
    extra_purchased_inr: Decimal
    #: The platform-wide brake, which overrides everything below it.
    platform_paused: bool
    #: WHICH MODEL THE "about N assists" ESTIMATE IS FOR (D-410). `read_ai_quota` stamps
    #: it from `Settings.azure_openai_model`, the live switch, so the count on the screen
    #: describes the model that will serve the NEXT assist rather than the one that
    #: happened to be the shipped default when this module was imported. Required, with no
    #: default, for the reason `assist_nominal_inr` gives: a quota that could be built
    #: without naming a model is a quota that can publish a count 2.6x too generous and
    #: look right.
    #:
    #: It is NOT a claim about the assists ALREADY counted in `used_inr` — those were
    #: priced, row by row, at whatever model actually ran them (`record_ai_assist_usage`),
    #: and a month during which the switch was flipped legitimately holds both. The rupee
    #: figures are exact either way; only the ESTIMATE needs a model, and the honest model
    #: for an estimate about the future is the one configured now.
    assist_model: str
    #: Too little of this month is left to sell an allowance for it — a stored fact rather
    #: than a property that reads the clock, so a quota object answers the same question
    #: twice the same way and a test can construct the state it wants to assert about.
    month_ending: bool = False

    @property
    def allowance_inr(self) -> Decimal:
        return self.included_inr + self.extra_purchased_inr

    @property
    def remaining_inr(self) -> Decimal:
        return max(Decimal("0"), self.allowance_inr - self.used_inr)

    @property
    def at_ceiling(self) -> bool:
        return self.used_inr >= self.allowance_inr

    @property
    def state(self) -> QuotaState:
        if self.platform_paused:
            return "platform_paused"
        if not self.at_ceiling:
            return "within"
        # At the ceiling with the block already spent, there is nothing left to offer:
        # `exhausted` is the state the screen refuses in rather than asking again.
        return "exhausted" if self.extra_purchased_inr > 0 else "ceiling_reached"

    @property
    def nominal_assist_inr(self) -> Decimal:
        """The reference price the two counts below divide by — one derivation, read
        twice, so `requests_included` and `requests_remaining` cannot come to be about
        different models."""
        return assist_nominal_inr(self.assist_model)

    @property
    def requests_included(self) -> int:
        """About how many assists the ALLOWANCE is worth, at the reference price."""
        return int(self.allowance_inr // self.nominal_assist_inr)

    @property
    def requests_remaining(self) -> int:
        return int(self.remaining_inr // self.nominal_assist_inr)

    @property
    def extra_unavailable(self) -> ExtraUnavailable | None:
        """Why the modal's button is not on offer.

        Published rather than left for the browser to infer from four other fields: a
        client who cannot buy needs the reason, and a second copy of this precedence in
        TypeScript is a second place for it to drift.

        THE GUARANTEE, stated precisely because the note here used to claim more than it
        delivered ("checked in the order the SERVER refuses in") while ordering
        `not_prepaid` ahead of `already_purchased` and `purchase_ai_overage` doing the
        opposite: whenever this returns a reason OTHER than `already_purchased`,
        `purchase_ai_overage` refuses with `EXTRA_REFUSAL_CODE[reason]`. The exception is
        deliberate and is the one case that is not a refusal at all — a block already
        bought is a REPLAY, so the purchase returns it and charges nothing rather than
        raising. `tests/ai_quota_test.py` walks the mapping.
        """
        if self.platform_paused:
            return "platform_paused"
        if self.month_ending:
            return "month_ending"
        if self.extra_purchased_inr > 0:
            return "already_purchased"
        if self.plan_tier not in PREPAID_TIERS:
            return "not_prepaid"
        if not self.at_ceiling:
            return "not_at_ceiling"
        return None


# WHAT THE MONTH'S ASSISTS COST US. `COUNT(DISTINCT ref)` is the request count and not a
# row count: one assist writes two rows (in and out) under one key, so counting rows
# would report double and counting one unit type would under-report an assist that
# produced no output tokens.
_USAGE_SQL = (
    "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0), COUNT(DISTINCT ref) "
    "FROM usage_events "
    "WHERE tenant_id = :tid AND unit_type = ANY(:units) AND ref IS NOT NULL "
    # The month is a half-open range on `occurred_at`, not a rendered string: the rendered
    # form cannot be an index condition (`billing/service._IST_MONTH_WINDOW` carries the
    # measurement), so this panel used to read the tenant's whole metering history.
    f"AND {_IST_MONTH_WINDOW}"
)


async def read_ai_quota(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> AiQuota:
    """This tenant's dashboard-AI month, from the two ledgers that hold it.

    `tenant_id` is in the predicate as well as in RLS for the reason `usage_summary`
    gives: the answer should depend on the argument rather than on which session it was
    handed, and RLS still fails the query closed.

    The month is VALIDATED through the shared `parse_billing_month`, not re-parsed here —
    two panels reading one ledger must not disagree about what a month is, and a month we
    cannot parse is one we cannot honestly report a ceiling for.
    """
    period = month or current_billing_month()
    parse_billing_month(period)

    row = (
        await session.execute(
            text(_USAGE_SQL),
            {
                "tid": tenant_id,
                "units": list(AI_ASSIST_UNIT_TYPES),
                **_month_bounds(period),
            },
        )
    ).one()
    # `Decimal(str(...))` — never `Decimal(float)` — on the way out of NUMERIC, the same
    # discipline `billing/terms.py::_money` keeps.
    used = Decimal(str(row[0] or 0))
    requests = int(row[1] or 0)

    tier = await plan_tier_of(session, tenant_id)
    # The wallet row IS the acceptance record (module docstring), so this read answers
    # "has a person agreed to spend money on this month" with no second state.
    purchased = await find_entry_by_ref(
        session, tenant_id=tenant_id, reason="usage", ref=overage_ref(period)
    )
    # `delta` is signed and a debit is negative; the block is reported as a positive
    # amount because that is what the client bought.
    extra = -purchased.amount_inr if purchased is not None else Decimal("0")

    return AiQuota(
        month=period,
        plan_tier=tier,
        included_inr=AI_QUOTA_INR.get(tier, AI_QUOTA_INR["trial"]),
        used_inr=used,
        requests_used=requests,
        extra_purchased_inr=extra,
        platform_paused=await platform_brake_tripped(session, month=period),
        # THE LIVE SWITCH, read here and nowhere else in this module. It is a `Literal` on
        # `Settings`, so it is already the closed set `llm_inr_per_ktok` prices — an
        # unpriced identifier cannot reach this line through the console.
        assist_model=get_settings().azure_openai_model,
        month_ending=month_is_ending(period),
    )


# --- the platform's own brake ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlatformAiSpend:
    month: str
    spend_inr: Decimal
    requests: int

    @property
    def tripped(self) -> bool:
        return self.spend_inr >= PLATFORM_AI_BRAKE_INR


async def read_platform_ai_spend(
    session: AsyncSession, *, month: str | None = None
) -> PlatformAiSpend:
    """What the dashboard-AI key has cost us this month, across every tenant.

    Reads `platform_ai_spend`, which carries no `tenant_id` and no policy, so this
    answers the same on a tenant-scoped session as on an untenanted one. That is the
    whole reason the table exists: the equivalent question asked of `usage_events` — sum
    the AI rows for all tenants — is unanswerable under FORCEd RLS without the admin DB
    role, which hard rule 1 forbids in app code.

    A month with no row is ₹0, not an error: nothing has been spent yet.
    """
    period = month or current_billing_month()
    row = (
        await session.execute(
            text("SELECT spend_inr, requests FROM platform_ai_spend WHERE month = :m"),
            {"m": period},
        )
    ).first()
    if row is None:
        return PlatformAiSpend(month=period, spend_inr=Decimal("0"), requests=0)
    return PlatformAiSpend(month=period, spend_inr=Decimal(str(row[0])), requests=int(row[1]))


async def platform_brake_tripped(session: AsyncSession, *, month: str | None = None) -> bool:
    return (await read_platform_ai_spend(session, month=month)).tripped


# The counter moves in ONE statement, so two tenants' assists landing at the same instant
# cannot both read a pre-increment total and both write it back (BACKEND-PATTERNS §5 —
# the guard is IN the write). `platform_ai_spend` is a counter and not a ledger, so an
# UPDATE here is correct and it is deliberately NOT in `APPEND_ONLY_TABLES`: every rupee
# it holds is re-derivable from the per-tenant `usage_events` rows that produced it.
_BUMP_PLATFORM_SQL = """
INSERT INTO platform_ai_spend (month, spend_inr, requests, updated_at)
VALUES (:month, :amount, :requests, now())
ON CONFLICT (month) DO UPDATE
   SET spend_inr = platform_ai_spend.spend_inr + EXCLUDED.spend_inr,
       requests  = platform_ai_spend.requests  + EXCLUDED.requests,
       updated_at = now()
RETURNING spend_inr
"""


def _announce_platform_headroom(*, month: str, spend_after: Decimal, added: Decimal) -> None:
    """Tell an operator on the bump that CROSSES a line, and only then.

    `spend_after - added` is the total before this assist, so "under before, over after"
    is decided from the UPDATE's own return value — exactly-once per month with no second
    table and no read-modify-write to race. Two lines, most-severe first, and a `break`
    because one large assist can cross both and two alerts about one event is noise on a
    phone at the moment it needs to be legible.

    Never raises: `alert()` is documented not to, and a metered assist must not be undone
    by a failure to talk about it.
    """
    spend_before = spend_after - added
    for threshold, code, detail in (
        (
            PLATFORM_AI_BRAKE_INR,
            "ai_platform_brake_tripped",
            "Dashboard AI is now PAUSED for every tenant: this month's platform-wide AI "
            "spend crossed the brake. Calls, campaigns and leads are unaffected. It "
            "clears on the IST month roll; releasing it sooner is a code change to "
            "PLATFORM_AI_BRAKE_INR.",
        ),
        (
            PLATFORM_AI_BRAKE_INR * PLATFORM_BRAKE_WARN_AT,
            "ai_platform_brake_near",
            "Platform-wide dashboard-AI spend passed 80% of this month's brake. At 100% "
            "AI help stops for every tenant. Check for a tenant or a loop spending "
            "unusually before it does.",
        ),
    ):
        if spend_before < threshold <= spend_after:
            alert(
                "CORE_LOGIC",
                code,
                detail=detail,
                # Rupees and a month. No tenant, because the tenant whose assist happened
                # to cross the line is not the finding — the month's total is.
                month=month,
                spend_inr=str(to_paise(spend_after)),
                brake_inr=str(to_paise(PLATFORM_AI_BRAKE_INR)),
            )
            break


# --- metering an assist -----------------------------------------------------------
#
# THE PREDICATE BELOW IS COPIED FROM MIGRATION e1a7c93d5b02 CHARACTER FOR CHARACTER.
# Postgres infers a PARTIAL unique index only from an `ON CONFLICT` whose own predicate
# implies the index's (postgresql.org/docs/16/sql-insert.html, "unique index inference").
# A predicate that almost matches does not degrade — it raises `there is no unique or
# exclusion constraint matching the ON CONFLICT specification`, which is a 500 on a
# button a client just pressed. `tests/ai_quota_test.py` reads both and fails on drift.
#
# `DO NOTHING`, never `DO UPDATE`: `usage_events` is in `APPEND_ONLY_TABLES` and
# `DO UPDATE` fires `calevate_forbid_mutation`. The silence `b8d3f47c2a19` rejects
# `DO NOTHING` for is the right answer HERE and the wrong one there, and the difference
# is what a duplicate MEANS: on the call path it means two runs interleaved and wrote a
# partial row set, which must abort; here it means the same button was pressed twice,
# which must be a no-op. `RETURNING id` is what tells the two apart at the call site.
INDEX_PREDICATE: Final = "ref IS NOT NULL AND call_id IS NULL"

# `RETURNING` carries the ROW'S OWN billing month, not just its id, and that is a
# two-clock fix rather than a convenience. `occurred_at` is the DATABASE's `now()`;
# `current_billing_month()` is the API PROCESS's `datetime.now(UTC)`. Those are two
# clocks, and near an IST month boundary they disagree — not hypothetically, but by
# whatever NTP skew exists between an app container and its database, which is routinely
# seconds and is unbounded when one of them drifts. The counter that the platform brake
# reads would then be incremented against a month the `usage_events` rows are not in, and
# the two would never reconcile: the brake would guard a month that had spent nothing
# while the month that actually spent it went unguarded. One clock — Postgres's, the one
# the row is stamped with — and the disagreement is unrepresentable.
_INSERT_USAGE = f"""
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          ref, occurred_at, meta, created_at)
VALUES (:id, :tid, NULL, :unit, :qty, :cost, :ref, now(), CAST(:meta AS jsonb), now())
ON CONFLICT (tenant_id, unit_type, ref) WHERE {INDEX_PREDICATE}
DO NOTHING
RETURNING id, {_IST_MONTH}
"""


#: The `usage_events.ref` namespace this module owns, and the shape it will accept.
#:
#: **THE REF IS THE METER'S OFF SWITCH, SO IT IS NOT THE CLIENT'S TO CHOOSE.** The insert
#: below is `ON CONFLICT … DO NOTHING`: a `ref` that has been seen before meters NOTHING,
#: moves no quota and moves no platform counter. That is exactly right for a retry of one
#: server-side attempt and exactly wrong for anything a caller can pick — a browser
#: allowed to send its own key sends `"1"` forever, and every assist after the first runs
#: on Calevate's credential, past a ceiling that can no longer move, invisible to the
#: brake. `billing/models.py` used to describe this as "the caller mints one `ref` per
#: request", which is true and ambiguous about which caller; this makes it structural.
#:
#: So the writer owns the namespace and will only accept `assist:<uuid>` from
#: `new_assist_ref()`. Two things follow that a bare prefix check would not give:
#:
#: - a value from ANOTHER feature's key space cannot be passed in by mistake — the
#:   column is shared with nothing today, but `ref` is a generic column on a shared
#:   ledger and the next writer of it is a matter of time; and
#: - a caller cannot pass a value it received from a browser, because a browser has no
#:   way to produce one that has not already been spent.
#:
#: WHERE DOUBLE-CLICK PROTECTION GOES INSTEAD, since this is where it used to be: at the
#: ENDPOINT, before the model is called, keyed on the client's own idempotency key and
#: answering with the stored result. Deduping AFTER the provider has already been paid
#: does not save the money — it only hides that we spent it.
ASSIST_REF_PREFIX: Final = "assist"
_ASSIST_REF_RE: Final = re.compile(
    rf"^{ASSIST_REF_PREFIX}:[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)


def new_assist_ref() -> str:
    """A fresh metering key for ONE assist attempt. Minted by the server, per attempt.

    uuid7 rather than uuid4 for the reason everything else in this repo uses it: the key
    sorts by the instant it was minted, so a `ref` found in a ledger row a year later
    still says when the attempt happened even if `occurred_at` is being doubted.
    """
    return f"{ASSIST_REF_PREFIX}:{uuid7()}"


@dataclass(frozen=True, slots=True)
class AssistMetered:
    """What `record_ai_assist_usage` did.

    `recorded` is False for a replay — the same `ref` already metered. With a server-minted
    key that is a RETRY of one attempt, never a second click, so `cost_inr` is zero and the
    caller can never charge the platform counter twice for one assist.
    """

    recorded: bool
    cost_inr: Decimal


async def record_ai_assist_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    ref: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    feature: str,
) -> AssistMetered:
    """Meter one dashboard assist: two `usage_events` rows and the platform counter.

    THE ONLY WRITER of `ai_assist_ktok_*`. It is idempotent on `ref` in the DATABASE
    (`ux_usage_events_tenant_unit_ref`), not in a reader's `if`, because the failure it
    has to survive is the same attempt arriving twice — and a check-then-write would let
    both copies read "not metered yet". That is the same hole `charge_for_call` takes an
    advisory lock to close; here the unique index closes it with no lock at all, which is
    what a natural key buys.

    `ref` MUST come from `new_assist_ref()`. It is validated rather than trusted, and the
    reason is on `ASSIST_REF_PREFIX`: this function's idempotency is a switch that turns
    metering off, so a key any caller could have taken from a request body is a way to
    spend our credential for free.

    The platform counter is bumped ONLY for rows that actually landed, so a replay adds
    nothing to the brake. Both halves commit in the CALLER's transaction: a metered
    assist whose platform total did not move is not a reachable state. The month it is
    bumped for is the month the ROW landed in, read back from the row (`_INSERT_USAGE`),
    never the app process's own clock.

    `model` and `feature` go into `meta` so that "which surface spent this" is a query.
    No prompt, no completion, no transcript and no identifier of a person is written
    here (hard rule 6) — a token COUNT is not content.

    **THE PRICE IS DERIVED FROM `model`, NOT PASSED BESIDE IT (D-410), AND THAT IS A
    STRUCTURAL FIX RATHER THAN A TIDY-UP.** This function used to take
    `price_in_inr_per_ktok` and `price_out_inr_per_ktok` as arguments and `model` as a
    third, independent one — three values a caller had to keep in step by hand. That was
    survivable while one model shipped and the price table had one entry. It stopped being
    survivable the moment `Settings.azure_openai_model` became a live switch between two
    models 2.7x apart: the caller reads the setting to choose the model, and any caller
    that then reached for the default's price — or simply forgot to change one of the two
    price lines when the other moved — would write a ledger row whose `unit_cost_paid`
    disagrees with its own `meta.model`, on an APPEND-ONLY table (hard rule 4), invisibly,
    for every assist. Deriving the price from the model makes that row unrepresentable,
    which is the only guarantee worth having on a ledger that cannot be corrected in place.
    """
    if not _ASSIST_REF_RE.match(ref):
        # A programming error, not a user's: raised rather than refused politely, because
        # every reachable caller mints its key from `new_assist_ref()` and one that did
        # not is a caller that has invented its own idempotency scheme.
        raise ValueError(
            f"an assist metering key must come from new_assist_ref() "
            f"({ASSIST_REF_PREFIX}:<uuid>), never from a request"
        )

    # Raises `ValueError` for a model this repository publishes no price for, BEFORE any
    # statement runs — the same "refuse rather than guess" the ref guard above makes, on
    # the other half of the row. Metering an assist at a made-up price is worse than not
    # metering it: the first is a wrong number on an append-only ledger, the second is a
    # gap an operator can see in the platform counter.
    inr_per_ktok = llm_inr_per_ktok(model)

    meta = json.dumps({"kind": ASSIST_META_KIND, "model": model, "feature": feature, "ref": ref})
    rows = (
        ("ai_assist_ktok_in", ktok(tokens_in), inr_per_ktok["in"]),
        ("ai_assist_ktok_out", ktok(tokens_out), inr_per_ktok["out"]),
    )
    landed = Decimal("0")
    landed_month: str | None = None
    for unit, qty, price in rows:
        inserted = (
            await session.execute(
                text(_INSERT_USAGE),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "unit": unit,
                    "qty": qty,
                    "cost": price,
                    "ref": ref,
                    "meta": meta,
                },
            )
        ).first()
        if inserted is not None:
            # The FIRST row's month wins if the two straddle a boundary. They are
            # microseconds apart and both are honest; what must not happen is the two
            # halves of one assist paying into two different months' brakes.
            landed_month = landed_month or str(inserted[1])
            landed += qty * price

    if landed_month is None:
        # Not an error and not silence either. With a server-minted key this means the
        # same attempt was written twice — a retried transaction — so the money is
        # already on the ledger. It is logged because the alternative is a path where we
        # paid a provider and recorded nothing, and the two look identical from here.
        log.warning(
            "ai_assist_replayed",
            extra={"tenant_id": str(tenant_id), "ref": ref, "model": model, "feature": feature},
        )
        return AssistMetered(recorded=False, cost_inr=Decimal("0"))

    spend_after = Decimal(
        str(
            (
                await session.execute(
                    text(_BUMP_PLATFORM_SQL),
                    {"month": landed_month, "amount": landed, "requests": 1},
                )
            ).scalar_one()
        )
    )
    _announce_platform_headroom(month=landed_month, spend_after=spend_after, added=landed)
    log.info(
        "ai_assist_metered",
        # Ids, a model name and a rupee total. No tenant name, no prompt, no output.
        extra={
            "tenant_id": str(tenant_id),
            "ref": ref,
            "model": model,
            "feature": feature,
            "month": landed_month,
            "cost_inr": str(landed),
        },
    )
    return AssistMetered(recorded=True, cost_inr=landed)


# --- the gate ----------------------------------------------------------------------


async def require_ai_assist(session: AsyncSession, *, tenant_id: UUID) -> AiQuota:
    """May this tenant run a dashboard assist right now? Returns the quota, or REFUSES.

    THE ONE PLACE that decides, so a second surface cannot answer differently — the same
    doctrine `compliance.service.check_dispatch` keeps for a dial. Every refusal carries
    a `remediation` the client can act on, and the browser switches on `code`:
    `ai_quota_exceeded` is what opens the modal.

    The numbers the modal shows are deliberately NOT stuffed into the problem body. The
    screen re-reads `GET /v1/billing/ai-quota`, which is the same computation this
    function used, so the figure a person is asked to accept can never be a stale copy
    carried in an error. RFC-9457 extensions were the alternative and would have made
    the modal's amount a second source of truth.
    """
    quota = await read_ai_quota(session, tenant_id=tenant_id)

    if quota.platform_paused:
        # `transient`/503 — the ONE status this repo's error ladder lets keep its
        # detailed message, and the honest kind: it clears when an operator raises the
        # brake or the month rolls over. NOT a 500: nothing is broken, we stopped it.
        raise ProblemError(
            kind="transient",
            code="ai_paused_platform_wide",
            title="AI help is paused",
            detail=(
                "AI help is paused across Calevate while we check unusually high usage. "
                "Your calls, campaigns and leads are unaffected."
            ),
            remediation="Try again later, or ask your account manager for an update.",
        )

    if not quota.at_ceiling:
        return quota

    if quota.extra_purchased_inr > 0:
        raise ProblemError.business_rule(
            "ai_quota_exhausted",
            (
                "This account has used all of this month's AI help, including the extra "
                "you added. It resets at the start of next month."
            ),
            remediation=("Talk to your account manager if you need more AI help before then."),
        )

    if quota.plan_tier not in PREPAID_TIERS:
        # A MANAGED tenant cannot be offered the block: their wallet is not what pays for
        # anything, and there is no priced AI-overage line on a derived invoice to put
        # this on. The remediation used to say "talk to your account manager to add more
        # AI help to this month's plan", which names an action nobody at Calevate can
        # currently perform — the line does not exist. Promising a purchase that cannot
        # be made is worse than naming the wait, so it names the wait, and asking is
        # offered as what it is: a conversation, not a transaction. "Your account
        # manager" is this console's established phrase for that conversation (the
        # verification, invoice and usage screens all use it) rather than a support
        # address this product does not publish anywhere.
        #
        # This is the ONE refusal in this module that is closed by something outside the
        # repo: a founder pricing AI overage on a retainer.
        raise ProblemError.business_rule(
            "ai_quota_exceeded_invoiced",
            (
                "This account has used all of this month's included AI help. It resets "
                "at the start of next month."
            ),
            remediation=(
                "Your calls, campaigns and leads are unaffected. If you need AI help "
                "before the reset, raise it with your account manager — extra AI help is "
                "not something we can add to an invoiced plan from the console."
            ),
        )

    if quota.extra_unavailable is not None:
        # Prepaid, at the ceiling, nothing bought, platform running — the only reason
        # left is that the month is nearly over. Read from the ONE ladder rather than
        # re-derived, so this cannot start promising a modal the purchase route refuses.
        code, detail, remediation = EXTRA_REFUSAL[quota.extra_unavailable]
        raise ProblemError.business_rule(code, detail, remediation=remediation)

    raise ProblemError.business_rule(
        "ai_quota_exceeded",
        (
            "This account has used all of this month's included AI help. You can add "
            "more from the AI assistance screen."
        ),
        remediation=(
            "Open AI assistance to see what more AI help costs and to add it, or wait "
            "for the allowance to reset at the start of next month."
        ),
    )


# --- buying the block (G-5) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtraPurchase:
    """The outcome of an acceptance. `charged` is False on a replay — the same month's
    block was already bought — and the caller audits only a real change, the convention
    `billing/terms.py::TermsWriteResult` and `kb.approve_source` established."""

    charged: bool
    amount_inr: Decimal
    quota: AiQuota


#: How little of an IST month may remain and the block still be sold. Below this the
#: purchase is REFUSED and nothing is charged.
#:
#: THE BLOCK EXPIRES WITH THE MONTH. Its whole shape — one fixed amount, once per
#: tenant-month, unused part not refunded and not carried over — is stated on the screen
#: and is a fair bargain on the 3rd. On the 31st at 23:59:50 it is ₹500 for ten seconds
#: of allowance, which is the same bargain arithmetically and not the same bargain at
#: all. Nothing in the code stopped it: `at_ceiling` is true all month once the ceiling
#: is hit, so the modal was on offer right up to the roll.
#:
#: IT ALSO CLOSES A RACE, and that is the half that is a correctness bug rather than a
#: product one. `read_ai_quota` resolves the month, and `record_entry` writes
#: `ai_assist:<that month>` some milliseconds later. If the roll happens between them the
#: debit lands under LAST month's key, which next month's `read_ai_quota` does not look
#: for: the client is ₹500 down, holds no extra allowance, and — because
#: `extra_purchased_inr` reads 0 — is immediately offered the block again. An hour-wide
#: refusal makes that interval unreachable instead of merely unlikely; a re-read after
#: the write would only have detected it, and detecting a debit is not undoing one.
#:
#: SIXTY MINUTES rather than a smaller number nobody could feel: the value being bought is
#: "AI help for the rest of the month", and under an hour there is no rest of the month to
#: sell. It is short enough to cost a real buyer nothing (the allowance resets in that
#: same hour and is then larger than the block on every tier) and long enough that no
#: plausible clock skew reopens the race.
LAST_SALEABLE_MINUTES: Final = 60


def month_is_ending(month: str, *, now: datetime | None = None) -> bool:
    """Is there too little of `month` left to sell an allowance for it?

    True for a month already over, which is the same statement and the reason this takes
    a month rather than reading the clock twice: `read_ai_quota` can be asked about July
    in September, and nobody may buy an allowance for July.
    """
    moment = now or datetime.now(UTC)
    return ist_month_end(month) - moment <= timedelta(minutes=LAST_SALEABLE_MINUTES)


async def purchase_ai_overage(
    session: AsyncSession, *, tenant_id: UUID, accepted_amount_inr: Decimal
) -> ExtraPurchase:
    """Debit the one block this tenant-month may buy — AFTER a person accepted it.

    `accepted_amount_inr` is what the modal SHOWED, echoed back, and it is compared
    against `AI_OVERAGE_BLOCK_INR` before anything moves. That is the client-realm form
    of the `X-Confirm-Action` double-key the admin credit routes use, and it exists for
    the same failure: a screen left open across a price change would otherwise debit a
    figure nobody was shown. A mismatch is refused, never clamped.

    ORDER OF CHECKS IS THE ORDER OF HARM. The lock is taken FIRST — before the read that
    decides whether to write at all — because a dedupe check outside it is the
    check-then-write hole two clicks walk straight through (`lock_tenant_credits`). Then
    the replay, so a second click returns the first click's block instead of buying
    another AND so a retry stays idempotent whatever else has changed since. Then the ONE
    reason ladder, which is `AiQuota.extra_unavailable` itself rather than a second copy
    of it — three hand-written refusals in this function used to BE that second copy, and
    they had already drifted from it by one position. Then the debit, the only step that
    moves money.

    `record_entry(allow_negative=False)`: this is a PURCHASE and not the recording of a
    cost already incurred, so an empty wallet must refuse it rather than overdraw. That
    is the opposite of `charge_for_call`, and the difference is exactly that a call has
    already happened.

    AND IT WILL NOT SELL THE LAST HOUR OF A MONTH — see `LAST_SALEABLE_MINUTES`.
    """
    if accepted_amount_inr != AI_OVERAGE_BLOCK_INR:
        raise ProblemError.business_rule(
            "ai_extra_amount_changed",
            "The amount you accepted is not the amount we would charge.",
            remediation="Reload the AI assistance screen and accept the amount shown.",
        )

    await lock_tenant_credits(session, tenant_id)
    quota = await read_ai_quota(session, tenant_id=tenant_id)

    if quota.extra_purchased_inr > 0:
        # A replay, not an error: the block is already on the wallet and nothing moves.
        # Reported as `charged=False` so the caller writes no second audit row. Checked
        # ahead of every refusal so that a retry of a request that SUCCEEDED answers the
        # same way it did the first time, even if the platform has paused since.
        return ExtraPurchase(charged=False, amount_inr=quota.extra_purchased_inr, quota=quota)

    reason = quota.extra_unavailable
    if reason is not None:
        # `already_purchased` is unreachable here — it is the branch above — so every
        # remaining reason has a refusal in the table, and mypy's exhaustiveness is not
        # what guarantees that: `tests/ai_quota_test.py` walks `ExtraUnavailable`.
        code, detail, remediation = EXTRA_REFUSAL[reason]
        raise ProblemError.business_rule(code, detail, remediation=remediation)

    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-AI_OVERAGE_BLOCK_INR,
        reason="usage",
        ref=overage_ref(quota.month),
        meta={
            "kind": OVERAGE_META_KIND,
            "month": quota.month,
            # What the person was shown when they accepted, so the row explains itself
            # on a statement a year from now without this module being read.
            "accepted_amount_inr": str(to_paise(AI_OVERAGE_BLOCK_INR)),
            "included_inr": str(to_paise(quota.included_inr)),
            "used_inr_at_acceptance": str(to_paise(quota.used_inr)),
        },
    )
    log.info(
        "ai_overage_purchased",
        extra={
            "tenant_id": str(tenant_id),
            "month": quota.month,
            "amount_inr": str(AI_OVERAGE_BLOCK_INR),
        },
    )
    return ExtraPurchase(
        charged=True,
        amount_inr=AI_OVERAGE_BLOCK_INR,
        # Re-read INSIDE the same transaction, so the response states the world after
        # the debit rather than the world the decision was made in.
        quota=await read_ai_quota(session, tenant_id=tenant_id),
    )


def quota_payload(quota: AiQuota) -> dict[str, Any]:
    """The wire shape, money as exact digit STRINGS (hard rule 7).

    Built here rather than in the route so the response model and the dataclass cannot
    drift into two definitions of the same month — the route validates this dict through
    its own `extra="forbid"` model, which is what fails loudly if they ever do.
    """
    return {
        "month": quota.month,
        "plan_tier": quota.plan_tier,
        "state": quota.state,
        "included_inr": str(to_paise(quota.included_inr)),
        "used_inr": str(to_paise(quota.used_inr)),
        "allowance_inr": str(to_paise(quota.allowance_inr)),
        "remaining_inr": str(to_paise(quota.remaining_inr)),
        "requests_used": quota.requests_used,
        "requests_included": quota.requests_included,
        "requests_remaining": quota.requests_remaining,
        # Null rather than "0.00" when nothing was bought: "they added ₹500" and "they
        # added nothing" are different facts and the screen says different things.
        "extra_purchased_inr": (
            str(to_paise(quota.extra_purchased_inr)) if quota.extra_purchased_inr > 0 else None
        ),
        # ALWAYS published, so the modal quotes the server's figure and never a constant
        # compiled into the browser bundle.
        "extra_block_inr": str(to_paise(AI_OVERAGE_BLOCK_INR)),
        # About how many assists the block is worth, derived HERE for the same reason
        # `requests_included` is: the browser must never divide a rupee amount, and the
        # reference price is not published precisely so nobody is tempted to.
        "extra_block_requests": int(AI_OVERAGE_BLOCK_INR // quota.nominal_assist_inr),
        "extra_available": quota.extra_unavailable is None,
        "extra_unavailable_reason": quota.extra_unavailable,
    }


__all__ = [
    "AI_OVERAGE_BLOCK_INR",
    "AI_QUOTA_INR",
    "ASSIST_META_KIND",
    "ASSIST_REF_PREFIX",
    "EXTRA_REFUSAL",
    "INDEX_PREDICATE",
    "LAST_SALEABLE_MINUTES",
    "NOMINAL_ASSIST_MARGIN",
    "OVERAGE_META_KIND",
    "OVERAGE_REF_PREFIX",
    "PLATFORM_AI_BRAKE_INR",
    "PLATFORM_BRAKE_WARN_AT",
    # `PREPAID_TIERS` is deliberately NOT re-exported: it is imported here, and listing it
    # would make this module a second import path for one predicate — which is how it came
    # to have a second SPELLING in the first place. `billing/rates.py` is where it lives.
    "REFERENCE_ASSIST_TOKENS",
    "AiQuota",
    "AssistMetered",
    "ExtraPurchase",
    "PlatformAiSpend",
    "assist_nominal_inr",
    "ktok",
    "month_is_ending",
    "new_assist_ref",
    "overage_ref",
    "platform_brake_tripped",
    "purchase_ai_overage",
    "quota_payload",
    "read_ai_quota",
    "read_platform_ai_spend",
    "record_ai_assist_usage",
    "reference_assist_cost_inr",
    "require_ai_assist",
]

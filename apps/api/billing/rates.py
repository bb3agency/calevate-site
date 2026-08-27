"""The TTS rate card (one voice quality) and the in-call / dashboard LLM cost model.

ONE VOICE QUALITY (the single-tier voice decision, superseding D-36/D-35/D-34)
-----------------------------------------------------------------------------
This module used to be the money half of a two-rung VOICE ladder — Bulbul v3 "premium" at
₹30/10,000 chars beside a Bulbul v2 "value" rung at ₹15, with an honesty rule
(`billable_tier`) that billed the cheaper rung whenever a premium voice could not be
proven. The founder-approved single-tier decision withdrew the v2 rung entirely: there is
one voice quality now (Sarvam Bulbul v3), so there is one TTS rate and nothing to select
or fall back to. The `TtsTier` type, `billable_tier`, `tier_of_voice`, `tier_correction_inr`
and the cross-rung correction have all been DELETED rather than left unreachable —
`apps/api/agents/voices.py` is the (now single-quality, persona-carrying) catalog half.

`SURFACES §2b`'s "never silently upgrade a degraded call" rule survives only where it still
has meaning: the PLAN's two overage-rate slots (`plans.overage_rate` /
`overage_rate_value`) in `billing/service.py`. Those are a founder pricing lever, not a
voice quality, and `overage_rate_value` is NULL on every plan today.

WHAT THE ENGINE STILL DOES NOT REPORT
-------------------------------------
**The engine does not report which voice actually synthesized a call**, and that fact is
unchanged by the collapse — `ExecutionSnapshot` carries no TTS model and no character
count, and the Bolna adapter parses none. It no longer threatens a BILL (there is one rate,
so a silent fallback could only be to the same voice at the same price), but it remains a
true, greppable engine-capability fact: `ENGINE_REPORTS_TTS_MODEL` stays False. The vendor
DOES publish a `usage_breakdown` block (`synthesizer_model`, `synthesizer_characters`) in
its spec, but as an ORPHAN schema referenced by no path — VERIFIED-VENDOR-REPO prose, not
VERIFIED-OAS — so `ExecutionSnapshot` still has no field for it and D-358 (a live capture on
OPERATIONS §2 gate 7) is still what would turn a synthesizer count into a measurement.

Money is NUMERIC INR (hard rule 7): no float ever appears here, and the one rounding
decision is ROUND_HALF_UP at NUMERIC(12,4), the storage precision of `unit_cost_paid`.
Note this is NOT `billing.service.to_paise` — that quantizes a RUPEE amount for a human
to read at 2dp; a unit price is stored at 4dp and must not be pre-rounded to paise.

THIS MODULE IS THE HOME OF THE TWO ROUNDING FACTS, for every writer and every reader
--------------------------------------------------------------------------------------
`MONEY_Q` (the storage quantum) and `ROUNDING` (the mode) live here because this is the
LOWEST money module in the import graph: `billing.service` imports this one, so the
constants cannot live there without a cycle. `service.PAISE` is a different quantum for
a different job (a rupee amount a human reads at 2dp) and stays where it is; `service
.ROUNDING` is now this name, re-exported, so there is exactly one mode in the tree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
)

from apps.api.billing.models import MONEY

# Sarvam's published Bulbul v3 rate, TRD §10.1. Per 10,000 characters, INR. NUMERIC,
# never a float.
#
# **ONE RATE, because there is one voice quality (the single-tier voice decision, which
# supersedes D-36/D-35/D-34's premium/value ladder).** This used to be a
# `Mapping[TtsTier, Decimal]` with a ₹30 premium (v3) and a ₹15 value (v2) rung, and the
# tier-honesty machinery that decided which rung a call was billed on lived beside it.
# With one voice there is nothing to decide: every call is Bulbul v3 at this rate, so the
# mapping, the `TtsTier` type, `billable_tier` and the cross-rung correction have all been
# deleted rather than left unreachable.
#
# THIS IS THE HOME OF THE RATE, and TRD §10.1 is the doc that states it.
# `scripts/check_docs_drift.py` §4b diffs the two in both directions and also checks
# §10.1's two spellings of the rate (₹/10,000 in the Sarvam card, ₹/1,000 in the
# per-call-minute table) against each other. Before that check existed, a vendor price
# move could land in the doc and not here — the shape D-102/D-103/D-105 each paid for,
# on the axis where it moves money.
TTS_INR_PER_10K_CHARS: Final[Decimal] = Decimal("30.0000")  # Bulbul v3

# Whether the engine's execution payload names the synthesizer model that served a call.
# A greppable capability constant (the honesty device `scripts/check_docs_drift.py` §5 and
# `tests/capability_claim_guard_test.py` verify against prose), discovered by AST, not a
# hand-listed registry. It NO LONGER guards a bill — there is one voice quality, so a
# synthesizer we could not identify would price identically anyway — but it stays False
# because it is still a true statement about the engine (see the module docstring: the
# `usage_breakdown` block is an orphan schema our snapshot has no field for). Flip it only
# when a captured payload proves the model is reported (D-358, OPERATIONS §2 gate 7).
ENGINE_REPORTS_TTS_MODEL = False

# THE OPEN VENDOR QUESTION ON THIS CARD, recorded here rather than left to be rediscovered.
#
# **THIS ENVIRONMENT STILL CANNOT READ SARVAM.** `sarvam.ai` and `docs.sarvam.ai` are
# refused by this container's egress proxy (CONNECT → 403, re-measured 27 Aug 2026, by
# `curl` and by the fetch tool), and no request has ever been made to them from this
# repository. That sentence has not changed and must not be deleted; what changed is that
# it is no longer the only way to reach the vendor.
#
# ⚠ **THE SEARCH-SUMMARY "BULBUL V4 HAS SHIPPED" CLAIM IS NOT BORNE OUT, AND THIS BLOCK IS
# WHERE IT LIVED.** This paragraph used to record — explicitly marked REPORTED-NOT-READ —
# that Aug 2026 search summaries described a shipped Bulbul v4 at the same rate. The
# founder holds a Sarvam account and read the dashboard Model Catalogue and Pricing page
# (`indus.sarvam.ai/model-catalogue`, `indus.sarvam.ai/pricing/buy-credits`) on 27 Aug 2026
# and relayed the reading here: the catalogue lists **`bulbul:v3` and no v4 row at all**,
# and no dashboard price for `bulbul:v2` either. TTS is confirmed at **₹30 / 10,000 chars
# for `bulbul:v3`** — exactly `TTS_INR_PER_10K_CHARS`, so no money moves — and the
# identifier `apps/api/agents/voices.py` pins is the one the vendor actually publishes.
#
# EVIDENCE CLASS of that correction: **VENDOR-PUBLISHED (Sarvam dashboard Model Catalogue
# and Pricing page, read by the founder 27 Aug 2026, relayed).** It is a first-party
# reading with a named reader and a date; it is NOT a page this container fetched.
#
# **THE LESSON IS RULE 11 LANDING ON THE BLOCK WRITTEN TO GUARD AGAINST IT.** A summary of
# a summary was recorded honestly, with its class marked, and was still wrong about the
# vendor's catalogue — which is why the correction is kept here in full rather than
# deleted: the next reader needs to inherit that a REPORTED vendor fact survived review for
# weeks, not just the corrected identifier.
#
# `ENGINE_TTS_MODEL_GENERATION_VERIFIED` STAYS FALSE, deliberately, and the flip was
# considered. It does not mean "we know which model generation Sarvam ships" — the
# catalogue reading answers that. It means the ENGINE tells us which model actually
# synthesized a given call, which is still false: the engine is Bolna, not Sarvam, its
# `ExecutionSnapshot` carries no synthesizer field, and no dashboard reading can change
# what a webhook payload contains. D-358 (a live capture on OPERATIONS §2 gate 7) is still
# the only thing that flips it.
ENGINE_TTS_MODEL_GENERATION_VERIFIED = False


# --- THE STT LEG: priced per unit of AUDIO TIME, not per character --------------------
#
# The SECOND half of the speech rate card, and until now the half with no code home at
# all. The ₹30/hour figure lived in TRD §10.1 prose and, blended with four other legs,
# inside `SELF_SERVE_COST_FLOOR_INR_PER_MIN` — so a vendor price move could land in the
# doc with nothing in code to notice, or here with nothing in the doc to notice. That is
# the D-103/D-105 shape arriving on the money axis one leg over from where
# `scripts/check_docs_drift.py` §4b already guards the TTS rate; §4d guards this one now,
# in both directions and across §10.1's two spellings of it (₹/hour and ₹/minute).
#
# ⚠ **EVIDENCE CLASS: VENDOR-PUBLISHED (Sarvam dashboard Model Catalogue,
# `indus.sarvam.ai/model-catalogue` and `indus.sarvam.ai/pricing/buy-credits`, read by the
# founder on 27 Aug 2026 and relayed here).** The catalogue prices **both `saaras:v3` and
# `saaras:v4` at ₹30 per hour of audio** — the same rate on both model versions, so a
# version move does not move this number — and ₹45/hour with diarization. This is a
# first-party reading with a named reader and a date; it is NOT a page this container
# fetched (see the egress note above, still true). TRD §10.1's own "verified rate" label at
# `docs/TRD.md:1395` was, until that reading, a repo-internal claim standing on itself,
# which hard rule 11 says is not evidence; it now stands on the reading.
#
# **THE DIARIZATION RATE IS DELIBERATELY NOT A CONSTANT HERE.** ₹45/hour is real and sits
# on the same card, but nothing in this repository enables diarization: a case-insensitive
# scan of `apps/`, `packages/`, `scripts/` and `docs/` for `diariz` finds exactly one hit —
# the TRD row itself. Pricing a feature we do not turn on would put a figure in the margin
# model that no call can produce, and the first reader to find it would reasonably assume
# we are billed it. It becomes a constant the day something asks the transcriber for
# speaker labels, and not before.
STT_INR_PER_HOUR: Final[Decimal] = Decimal("30.0000")  # Saaras (STT + Translate)

#: Seconds per hour, named because two functions below divide by it and a bare `3600` in
#: either is where a units error hides — this module's whole subject is that a rate has a
#: unit attached to it.
_SECONDS_PER_HOUR = Decimal("3600")

#: Minutes per hour, named for the same reason: TRD §10.1 states this rate in BOTH
#: spellings and the per-minute one is DERIVED here rather than restated as a second
#: constant. A literal `Decimal("0.50")` beside the hourly figure would be exactly the
#: two-homes-for-one-fact defect §4d exists to catch, living inside the module §4d reads.
_MINUTES_PER_HOUR = Decimal("60")

_CHARS_UNIT = Decimal("10000")

# The storage quantum, DERIVED from the column rather than restated beside it. `MONEY` is
# `Numeric(12, 4)` (billing/models.py), so this is `Decimal("0.0001")` — and it is spelled
# as a derivation because the literal was already living in three places (here, the
# metering writer, the fake adapter) and a scale change would have had to be found in all
# of them. Reading the scale off the type means the quantum cannot be wrong about the
# column it is quantizing FOR.
MONEY_Q = Decimal(1).scaleb(-(MONEY.scale or 0))

# THE rounding mode for every money quantization in this repository, passed EXPLICITLY at
# every call site and never inherited. `Decimal.quantize()` with no mode uses the ambient
# `decimal` context, whose default is ROUND_HALF_EVEN (banker's rounding) and which is
# process-global and mutable by any library in the image — a rupee that changes because
# somebody else changed a global is not an amount we can defend. ROUND_HALF_UP is the
# convention an Indian tax invoice is checked against.
#
# `tests/money_rounding_mode_test.py` scans the tree for a `quantize` that omits it.
ROUNDING = ROUND_HALF_UP


# --- the LLM leg, which stopped being free (D-400) and now has TWO prices (D-410) ----
#
# D-36 priced the in-call LLM leg at ₹0.00 because Sarvam 105B is free per token, and
# TRD §10 has reasoned the whole margin from that zero since. D-400 ended the zero by
# moving the leg to a paid account; D-410 moved it again, to Azure OpenAI (South India then,
# `eastus2` since D-449). THE REGION MOVE DID NOT MOVE THESE NUMBERS and deliberately was
# not made an excuse to re-derive them: they are the same GLOBAL STANDARD list prices
# `LLM_MODELS[model].price` has always carried, and the gap between that and what we
# actually buy — a Regional Standard deployment, reported at roughly 5-10% more — is still
# carried as an unpaid gate rather than folded in as a multiplier. Whether Azure's regional
# list differs between `southindia` and `eastus2` is a question the first invoice answers
# (OPERATIONS §2); inventing a factor for it here would make every derived figure in
# TRD §10 unfalsifiable, which is the exact failure that gate exists to avoid.
# This block is where the replacement number comes from, in the same shape as the TTS
# card above: one statement of the vendor's price, everything else derived, and the doc
# that quotes it checked against it.
#
# **WHAT D-410 CHANGED HERE IS NOT THE PRICE, IT IS THE ARITY.** Until it, one model
# shipped and one pair of numbers described the whole leg, so a cost function needed no
# argument to know what it was pricing. Now `Settings.azure_openai_model` is a LIVE
# console switch between `gpt-4o-mini` and `gpt-4.1-mini`, and `gpt-4.1-mini` costs 2.7x
# the default on BOTH legs. So EVERY function below takes the model EXPLICITLY and none
# of them has a default: a cost function that silently priced the shipped default while
# the deployment ran the other model would under-report the leg by 63% on every call and
# would look correct in every test that never flipped the switch. That is a metering
# defect with no other detector, and the shape of it — one identifier changing under a
# constant nobody re-derived — is D-103/D-105 arriving on the money axis for the third
# time. `tests/llm_cost_model_test.py` is what keeps the defaults off.
#
# ⚠ **NOTHING IS BILLING THE IN-CALL LEG, AND THAT IS NOT AN OVERSIGHT — IT IS
# PERMANENT.** WE CANNOT SEE THE TOKENS: `CostBreakdown` carries a per-leg cost in the
# engine's currency and, on a BYOK leg, the engine pays nothing and reports nothing —
# which is exactly the blindness `ENGINE_REPORTS_TTS_MODEL` documents one section up,
# arriving on a second leg. The truth will be the AZURE invoice, per subscription and not
# per tenant, and it will read HIGHER than these numbers by the regional-deployment
# premium that `LLM_MODELS[model].price` deliberately does not fold in. So these
# constants price the DECISION (TRD §10's unit economics, the margin a founder is
# choosing) and deliberately do not pretend to meter a call. The DASHBOARD leg is
# different and is metered for real — `billing/ai_quota.py` prices it from this table.

#: The USD/INR rate every published vendor list price in this repository is struck at.
#: RBI reference, 16 Aug 2026.
#:
#: NOT `Settings.usd_inr_rate`, and the distinction is why this is a named constant. That
#: field is the rate a CALL's engine cost is converted at, stamped into `usage_events
#: .meta` at capture so a ledger row can always be re-derived (`engine/bolna.py`). This
#: is the rate a LIST PRICE was quoted at — an input to a cost model and to an estimate
#: on a screen, never to a charge. Reading the live field here would make every "about N
#: assists" figure and every §10 margin move with an ops console, which is the opposite
#: of a number a person can plan around.
LIST_PRICE_USD_INR: Final = Decimal("95.66")


def _usd_mtok_to_inr_ktok(*, input_usd: Decimal, output_usd: Decimal) -> Mapping[str, Decimal]:
    """USD per MILLION tokens -> `{"in": ₹, "out": ₹}` per THOUSAND, at `LIST_PRICE_USD_INR`.

    ONE conversion, two callers — the catalogue reference table and the operator attestation
    — because a second spelling of `usd * fx / 1000` is a second place for the exchange rate
    or the unit to drift, and the two figures are meant to be COMPARABLE (the console shows
    them side by side so an operator can see what their invoice says against what the vendor
    lists). Four decimals because `unit_cost_paid` is NUMERIC(12,4): a price this ledger
    cannot store is a price it cannot honour.
    """
    return MappingProxyType(
        {
            leg: (usd * LIST_PRICE_USD_INR / Decimal("1000")).quantize(MONEY_Q, rounding=ROUNDING)
            for leg, usd in (("in", input_usd), ("out", output_usd))
        }
    )


#: THE CATALOGUE REFERENCE CARD, in rupees per THOUSAND tokens: every model this repository
#: permits on merit, at the vendor's PUBLISHED LIST price (`LLM_MODELS[model].price`) and the
#: one exchange rate above.
#:
#: ⚠ **IT IS NOT WHAT ANYTHING IS BILLED AT.** Read `LlmPrice` in the portability contract
#: for the full argument; the short form is that a list price is not what an account pays —
#: Azure's Regional Standard is vendor-confirmed at +10% on the figures below, Gemini's
#: 3.6/3.7 Flash step 2x on 1 Jan 2027, and negotiated rates and promotional tiers are
#: invisible on any page. The BILLING figure is `llm_inr_per_ktok`, which reads an operator's
#: attestation of their own invoice. This table drives TRD §10's margin model, the operator
#: console's pre-fill, and the picker's per-minute estimate.
#:
#: KEYED BY MODEL, and PRIVATE. The public way in is `llm_reference_inr_per_ktok(model)`,
#: which refuses an unpriced identifier with a message naming the ones it knows. A bare
#: mapping exported under the old name (`LLM_INR_PER_KTOK`, a flat `{"in", "out"}` pair) would
#: let `LLM_INR_PER_KTOK["in"]` keep parsing after the shape changed and fail at RUNTIME with
#: a `KeyError` on a metering path; the rename is what turns every stale reader into an
#: ImportError at collection time instead.
_LLM_INR_PER_KTOK: Final[Mapping[str, Mapping[str, Decimal]]] = MappingProxyType(
    {
        model: _usd_mtok_to_inr_ktok(
            input_usd=LLM_MODELS[model].price.input_usd_per_mtok,
            output_usd=LLM_MODELS[model].price.output_usd_per_mtok,
        )
        # SELECTABLE, not the whole catalogue, and the distinction is now about ROT rather
        # than about hard rule 7. It used to be the money rule itself: a REPORTED price one
        # `selectable=True` edit away from `unit_cost_paid` was the hazard, and excluding the
        # withdrawn models was the guard. That hazard is gone by construction — nothing here
        # reaches a bill. What remains is the older reason `PRICED_LLM_MODELS` was held equal
        # to the choosable set in both directions: a reference figure for a model nobody may
        # choose is a number that rots unnoticed, and a choosable model with no reference is
        # a blank cell on the console where the pre-fill should be.
        for model in SELECTABLE_LLM_MODELS
    }
)

#: The models this repository can put a rupee REFERENCE figure on, as a value.
#:
#: **IT EQUALS `SELECTABLE_LLM_MODELS` AND NO LONGER `AZURE_OPENAI_MODELS`.** That older
#: identity was true while Azure was the only leg anything was offered on, and several tests
#: and documents asserted it as if it were the invariant. It never was: the invariant is that
#: the reference card and the permitted set are the SAME SET, in both directions, so neither
#: can grow a member the other has not heard of. `agents/llm_models.every_selectable_model_
#: is_priced()` states it and `tests/llm_model_selection_test.py` fails on either direction.
PRICED_LLM_MODELS: Final[frozenset[str]] = frozenset(_LLM_INR_PER_KTOK)


def llm_reference_inr_per_ktok(model: str) -> Mapping[str, Decimal]:
    """`{"in": ₹, "out": ₹}` per 1,000 tokens for `model`, at the VENDOR'S LIST PRICE.

    ⚠ **A REFERENCE, NEVER A CHARGE.** The billing figure is `llm_inr_per_ktok` below, and
    the two are deliberately different functions with different failure modes rather than one
    function with a flag: a caller who reaches for the wrong one should get the wrong ANSWER
    loudly at the type/name level, not silently at the fourth decimal of an invoice. This one
    answers "what does the vendor list this at"; that one answers "what is this account
    actually charged".

    Refuses an unpriced identifier rather than falling back, because both fallbacks are worse
    than the error: the default's price silently under-states the dearer model, and a zero
    makes a leg look free.
    """
    try:
        return _LLM_INR_PER_KTOK[model]
    except KeyError:
        raise ValueError(
            f"{model!r} has no published reference price; this repository lists "
            f"{sorted(PRICED_LLM_MODELS)}"
        ) from None


# --- THE SARVAM CHAT LEG, WHICH IS NOT FREE ------------------------------------------
#
# ⚠ **THE FINDING: "SARVAM 105B IS FREE PER TOKEN" IS FALSE, AND THIS REPOSITORY IS BUILT
# ON IT IN THREE PLACES.** D-36 priced the Sarvam chat LLM at ₹0.00 and TRD §10 reasoned
# the margin from that zero; `calevate_shared/engine.py` (~:355) restates it, and
# `workers/script_assist.py:236` and `copilot/service.py` (~:330) go further and meter
# NOTHING for a Sarvam-served assist on the strength of it. The founder's dashboard reading
# contradicts it outright: `sarvam-105b` and `sarvam-105b-conversations` are priced per
# token, below.
#
# EVIDENCE CLASS: **VENDOR-PUBLISHED (Sarvam dashboard Model Catalogue,
# `indus.sarvam.ai/model-catalogue`, and the buy-credits pricing modal,
# `indus.sarvam.ai/pricing/buy-credits`, read by the founder on 27 Aug 2026 and relayed
# here).** Not fetched from this container — those hosts are egress-blocked here as
# `docs.sarvam.ai` is (403 on CONNECT, re-measured 27 Aug 2026).
#
# **IN RUPEES, NOT DOLLARS, WHICH IS WHY THIS IS NOT AN `LlmPriceAttestation` AND NOT AN
# `LLM_MODELS` ROW.** Three structural reasons, each of which would have to be broken to
# force it into the existing table:
#
# * Sarvam publishes and bills in INR. `LlmPrice` and `LlmPriceAttestation` are USD per
#   million tokens by construction, converted once at `LIST_PRICE_USD_INR`; feeding this
#   card through them would mean inventing a dollar figure nobody ever read and then
#   converting it back, so the rupee a client is reasoned about would move with an fx rate
#   that has nothing to do with the invoice.
# * `LLM_MODELS` is the set a CLIENT may pick for the IN-CALL leg. Sarvam is not on offer
#   there (`SELECTABLE_LLM_MODELS` is the five in `agents/llm_models.py`); it is the
#   disclosed dashboard fallback (D-127 G-7) and the post-call extraction pass. A seat in
#   that catalogue would say something false about what the product offers.
# * It carries a CACHED-INPUT rung, which `LlmPrice`'s two-legged `{in, out}` shape has no
#   slot for at all.
#
# **NO PATH TO `unit_cost_paid`, EXACTLY AS THE CATALOGUE CARD HAS NONE** (hard rule 7).
# `llm_inr_per_ktok` is the one door to a bill and it does not read this constant — it
# raises for `sarvam-105b`, today with "not a model this repository knows", because the
# identifier has no `LLM_MODELS` entry. What that means in practice is worth stating
# plainly rather than leaving to be discovered: a Sarvam-served assist currently records NO
# cost row at all, which is a FABRICATED ZERO on an append-only ledger — the same defect
# `_sum_usage` and `usage_from_body` argue against in the other direction. Closing it is a
# change at the metering call sites, not here.
#
# ⚠ **AN OPEN GAP THIS CARD DOES NOT RESOLVE, flagged by the founder and carried rather
# than guessed: `sarvam-105b` is described as "always-on reasoning", and the pricing modal
# shows Input / Cached input / Output with NO separate reasoning-token line.** Whether
# hidden reasoning tokens are billed at the Output rate is not stated anywhere they could
# find. If they are, the effective cost of this leg is HIGHER than this card says, and on a
# short answer it could be higher by a multiple. Do not assume either way — an invoice line
# against a request of known token counts settles it.
#
# ⚠ **CAPACITY IS PER ACCOUNT, NOT PER KEY.** The Starter tier allows 40 requests/minute on
# `sarvam-105b` chat, and the limit pools across every key on the account — issuing a
# second key buys no capacity. Same reading, same date. Nothing here rate-limits anything;
# it is recorded because "free per token" tends to be read as "unmetered", and the binding
# constraint on this leg was always the request rate rather than the price.

#: Sarvam's published `sarvam-105b` chat price, in **INR per MILLION tokens**, the vendor's
#: own unit and its own currency. `cached_in` is the discounted rung for input the vendor
#: served from its own prompt cache; it is on the card and is priced here so that a future
#: meter reading `prompt_tokens_details` has a rate to use rather than a reason to invent
#: one. NUMERIC, never float (hard rule 7).
SARVAM_LLM_INR_PER_MTOK: Final[Mapping[str, Decimal]] = MappingProxyType(
    {
        "in": Decimal("29.28"),
        "cached_in": Decimal("10.98"),
        "out": Decimal("73.20"),
    }
)

#: The one identifier this card prices. `sarvam-105b-conversations` is listed by the vendor
#: at the same three figures, so it is deliberately NOT a second entry: one price, one home
#: (`calevate_shared.engine.SARVAM_DEFAULT_LLM` is the identifier the code sends).
SARVAM_PRICED_LLM: Final = "sarvam-105b"


def sarvam_llm_reference_inr_per_ktok() -> Mapping[str, Decimal]:
    """`{"in", "cached_in", "out"}` in ₹ per 1,000 tokens — a REFERENCE, never a charge.

    Per THOUSAND for the reason `billing/models.py` gives for `ktok`: that is the unit
    `usage_events` counts an LLM leg in, so a meter built on this figure multiplies rather
    than divides. Quantized at `MONEY_Q` for `_usd_mtok_to_inr_ktok`'s reason — a price the
    ledger cannot store is a price it cannot honour — which is why this is a function
    rather than a second mapping literal: one conversion, stated once.

    It is NOT `llm_inr_per_ktok` and must not be mistaken for it: that function is the one
    door to `unit_cost_paid` and reads an operator attestation or a verified catalogue
    figure. This one answers only "what does Sarvam's dashboard list this at".
    """
    return MappingProxyType(
        {
            leg: (inr_per_mtok / Decimal("1000")).quantize(MONEY_Q, rounding=ROUNDING)
            for leg, inr_per_mtok in SARVAM_LLM_INR_PER_MTOK.items()
        }
    )


# --- THE OPERATOR-ATTESTED BILLING PRICE ---------------------------------------------
#
# **WHY A BILL IS PRICED FROM AN ATTESTATION AND NOT FROM A PAGE.** This product now runs on
# three vendors, and the founder holds all three accounts and installs all three keys. The
# only figure that is TRUE for this subscription is the one on this subscription's invoice:
# Azure's mandated Regional Standard deployment is vendor-confirmed at +10% over the Global
# list price the reference card carries, Google's 3.6/3.7 Flash carry a dated 2x step on
# 1 Jan 2027, and negotiated rates, committed-use discounts and promotional tiers appear on
# no published page at all. So the authoritative number is a FIRST-PARTY reading of a real
# invoice, and hard rule 7 is satisfied by it in a way no page-scrape could satisfy it.
#
# **THIS IS HARD RULE 7 MADE STRUCTURAL RATHER THAN REMEMBERED.** It used to be enforced by
# `LlmModelSpec` refusing to let a model be `selectable` on an unverified price — correct,
# but it protected `unit_cost_paid` by DELETING the model, so the whole multi-vendor offering
# was blocked by an egress rule. The protection now sits at the seam it is actually about:
# a catalogue price has no path to a bill at all, and `llm_inr_per_ktok` below is the one
# door, with exactly two keys.
#
# **THE STORAGE AND THE CONSOLE SCREENS ARE NOT HERE, DELIBERATELY.** `apps/api/ops/` owns
# where an attestation is kept, who may write one and what the form looks like; this module
# owns the CONTRACT — the record, the reader, and what happens when there is nothing to read.
# `install_llm_price_attestations` is the whole seam between them, and it is a function
# rather than an import so that the money module never depends on the console module.


@dataclass(frozen=True, slots=True)
class LlmPriceAttestation:
    """What an operator read off their own vendor invoice or console, for ONE model.

    **EVERY FIELD EXCEPT THE TWO PRICES IS PROVENANCE, AND THAT IS THE POINT.** A number in a
    settings row is indistinguishable from a number somebody guessed six months ago; this
    record cannot be written without saying who read it, when, and off what. `read_on` is what
    makes an attestation STALE rather than merely old — vendor prices move, and a figure
    nobody has re-read in a year is a claim about last year's invoice.

    USD PER MILLION TOKENS, the vendor's own unit, for `LlmPrice`'s reason: the rupee
    conversion happens once, at a named exchange rate, in `_usd_mtok_to_inr_ktok`. An
    operator typing rupees would be typing a number that already folded in an fx rate nobody
    recorded, and it could never be re-derived when the rate moved.

    `Decimal`, never `float` (hard rule 7). The ops layer parses the operator's input through
    `Decimal(str(...))` or a pydantic `condecimal` — never through a JSON float, which cannot
    hold `0.165` exactly and would put a rounding error four decimals deep into every minute.
    """

    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    #: When the operator read it. Not when the row was written — an operator correcting a
    #: typo is not a fresh reading, and only the reading's own date can say so.
    read_on: date
    #: Who read it, in whatever form the console records an operator (an id or an email).
    #: Free-form because this module must not know the shape of an operator identity.
    attested_by: str
    #: Where — an invoice number, a console URL, a billing-export line. Free-form for the
    #: same reason, and REQUIRED for D-31/D-32's: an unattributed figure is the defect class.
    source: str

    def __post_init__(self) -> None:
        if self.input_usd_per_mtok <= 0 or self.output_usd_per_mtok <= 0:
            raise ValueError(
                f"{self.model!r} was attested at a non-positive price "
                f"({self.input_usd_per_mtok}/{self.output_usd_per_mtok}). A zero here bills "
                "every minute on this model at ₹0 and looks exactly like a working leg — "
                "which is the one metering failure nobody investigates."
            )
        if not self.attested_by.strip() or not self.source.strip():
            raise ValueError(
                f"{self.model!r} was attested with no reader or no source. An attestation is "
                "stronger evidence than a vendor's page ONLY because somebody named is "
                "answering for it; without that it is a number in a text box."
            )


#: A function returning every attestation on file, keyed by model. Installed by the ops layer.
LlmPriceAttestationReader = Callable[[], Mapping[str, LlmPriceAttestation]]

_attestation_reader: LlmPriceAttestationReader | None = None


def install_llm_price_attestations(reader: LlmPriceAttestationReader | None) -> None:
    """Register where attested prices come from. `None` uninstalls (what tests reset to).

    **A REGISTRATION RATHER THAN AN IMPORT, AND THE DIRECTION IS THE WHOLE REASON.** The
    money module may not import the console module: `apps/api/ops/` already reads
    `billing/`, and the reverse edge would be an import cycle and, worse, a rate card that
    could not be exercised without a database. So the console calls this once at startup and
    `billing/` stays a pure function of its inputs.

    ⚠ **PROCESS-WIDE MUTABLE STATE, WHICH THIS REPOSITORY OTHERWISE AVOIDS.** The rejected
    alternative was threading a `Mapping` through every caller of `llm_inr_per_ktok` — the
    metering path, the assist meter, the picker and two guards — which is where "one way per
    problem" would normally point. It was rejected because those callers are several layers
    deep in code that has no business knowing prices exist, and passing a price table through
    them would put the money seam in five signatures instead of one. `get_settings()` and
    `platform_config.snapshot()` are the same shape for the same reason, so this follows the
    pattern already in the tree rather than inventing a sixth one.
    """
    global _attestation_reader
    _attestation_reader = reader


def attested_llm_prices() -> Mapping[str, LlmPriceAttestation]:
    """Every attestation on file. EMPTY when nothing is installed, never an error.

    Empty is the correct state for CI, for a fresh deployment and for every unit test, and it
    is not a failure — it means the Azure leg bills off its verified catalogue reading exactly
    as it did before this seam existed, and the other two legs are simply not offerable yet.
    """
    if _attestation_reader is None:
        return MappingProxyType({})
    return _attestation_reader()


def llm_price_is_billable(model: str) -> bool:
    """May a rupee figure for `model` reach `unit_cost_paid`? **THIS IS HARD RULE 7.**

    True on exactly two grounds, and there is no third:

    1. **An operator attested it** — a first-party reading of this account's own invoice.
    2. **The catalogue price was READ FROM THE VENDOR** (`price.evidence.verified`) — the
       incumbent Azure figures, which is why the Azure leg bills today with nothing installed
       and why this change moves no existing behaviour.

    A REPORTED figure — a tracker, a search summary, a vendor page nobody in this repository
    can re-fetch — is never billable, and no edit to `LLM_MODELS` can make it so. That is the
    property the old import-time raise protected by deleting the model; it is protected here
    by refusing the money instead, which leaves the model free to be offered the moment its
    price is attested.

    Total and never raising, including on an identifier the catalogue has forgotten: a model
    read back off a historical `usage_events` row is not billable and the honest answer is
    False, not an exception on a statement-rendering path.
    """
    if model in attested_llm_prices():
        return True
    spec = LLM_MODELS.get(model)
    return spec is not None and spec.price.evidence.verified


def llm_inr_per_ktok(model: str) -> Mapping[str, Decimal]:
    """`{"in": ₹, "out": ₹}` per 1,000 tokens **AS BILLED**. NO DEFAULT AND NO FALLBACK.

    THE ARGUMENT IS THE POINT (D-410). Which model a call ran is a per-agent choice now, so
    the only correct price is the one for the model the caller actually used — and the caller
    is the only one who knows it. Every reachable call site therefore names it.

    **THE ATTESTATION WINS WHEREVER THERE IS ONE, INCLUDING OVER A VERIFIED AZURE FIGURE**,
    and that ordering is deliberate rather than incidental. The catalogue's Azure prices are a
    Global Standard LIST reading; we are mandated onto REGIONAL Standard, which the vendor's
    own East US 2 card puts at +10%. So an operator who has entered what their invoice says is
    holding a strictly better number than the one in source, and a rate card that preferred
    its own constant would be preferring a figure it can prove is low.

    **AND IT RAISES RATHER THAN RETURNING ZERO FOR A MODEL NOBODY PRICED**, which is the
    behaviour hard rule 7 actually needs. An unpriced minute is not a free minute, it is an
    UNMETERED one: a leg quietly returning ₹0 looks like a working deployment, produces
    `usage_events` rows that reconcile against nothing, and is discovered when somebody
    compares a vendor invoice to a month of ledger. `offerable_models()` is what stops a
    client ever reaching this arm — a model with no billable price is not offered, is refused
    by `validate_llm_model` and is refused again at publish — so this raise is for the way in
    that no picker guards: an identifier read back off a historical row, or an operator
    revoking an attestation under accounts that already chose.
    """
    attested = attested_llm_prices().get(model)
    if attested is not None:
        return _usd_mtok_to_inr_ktok(
            input_usd=attested.input_usd_per_mtok, output_usd=attested.output_usd_per_mtok
        )
    spec = LLM_MODELS.get(model)
    if spec is not None and spec.price.evidence.verified:
        return _usd_mtok_to_inr_ktok(
            input_usd=spec.price.input_usd_per_mtok, output_usd=spec.price.output_usd_per_mtok
        )
    if spec is None:
        raise ValueError(
            f"{model!r} is not a model this repository knows, so nothing can price it. "
            f"Known: {sorted(LLM_MODELS)}."
        )
    raise ValueError(
        f"{model!r} has no billable price. Its catalogue figure "
        f"({spec.price.evidence.source}) is not a vendor reading this repository can stand "
        "behind, and no operator has attested one. Charging a client from it would put "
        "unverified evidence into unit_cost_paid (hard rule 7). Enter the price from the "
        "vendor invoice in the ops console; until then this model is not offerable."
    )


#: THE REFERENCE CONVERSATION the §10 per-minute figure is computed from. Every number
#: here is an ASSUMPTION and is named so it can be argued with, which is the whole reason
#: the per-minute figure is a function rather than a literal: the old "₹0.15-0.20/min for
#: a paid LLM" in TRD §10 had no inputs at all, so nobody could tell whether it had gone
#: stale when the model, the price or the prompt changed. All three have, twice.
#:
#: `prompt_tokens` — the system prompt as `compose_engine_prompt` renders it: a client's
#: script, the opening line, `TRUTHFUL_ANSWER_DIRECTIVE`, and whatever RAG snippet the
#: turn carried.
#:
#: `turn_tokens` — one full exchange, caller utterance plus agent reply, at Telugu's
#: token fertility (~2.1-2.3 tokens per word against English's ~1.2-1.4; the same figures
#: `engine/bolna.py` cites for its 400-token cap).
#:
#: `turns_per_minute` — six, a ten-second turn cycle on a phone call.
#:
#: `output_tokens_per_turn` — well under the 400-token cap, which is a safety valve
#: rather than a target.
#:
#: MODEL-INDEPENDENT ON PURPOSE: the conversation is the conversation whichever model
#: answers it, so switching models moves the PRICE and not the shape. That is what makes
#: the two published curves comparable at all.
REFERENCE_CALL: Final[Mapping[str, int]] = MappingProxyType(
    {
        "prompt_tokens": 900,
        "turn_tokens": 60,
        "turns_per_minute": 6,
        "output_tokens_per_turn": 35,
    }
)


def llm_cost_inr_per_minute(minutes: int, *, model: str) -> Decimal:
    """What the in-call LLM leg costs per minute on a call of this length, at list price.

    **IT IS NOT A CONSTANT PER MINUTE, AND THAT IS THE FINDING.** TRD §6.1 records that
    the full conversation is resent to the model on every turn, so input tokens grow
    linearly through a call and total input cost grows QUADRATICALLY with duration. A
    single "₹x/min" figure is therefore a blended average that a long call skews above —
    `scripts/pilot/knowledge.py::probe_h1_history_handling` exists to measure exactly
    this shape on the real engine, and says in its own docstring that a priced in-call
    LLM makes the correction matter. Taking `minutes` as an argument is what stops the
    cost model quoting minute one and reasoning about minute ten.

    **AND `model` IS KEYWORD-ONLY AND HAS NO DEFAULT** for the reason the section comment
    gives: the two selectable models differ by 2.7x, the switch between them is live, and
    a default here would make every caller's silence read as a claim about which one is
    deployed. Callers that quote a figure must say which model it is a figure FOR — TRD
    §10.1 publishes one row per model, and `scripts/check_docs_drift.py` scores each row
    against this function called with that row's own model.

    ⚠ **THIS IS WHAT THE LEG COSTS *US*. IT IS NOT A CLIENT-FACING PRICE AND MUST NEVER BE
    PUBLISHED AS ONE.** Written here rather than left to the section comment above because
    the distinction has already been lost once in this repository, on a bigger number:
    `charge_for_call` debited a prepaid wallet with `cost.total_inr` — the ENGINE's charge
    to us — while the client's own screen priced the same minute at `self_serve_inr_per_min`
    (P1.1/P1.3, argued in full at `prepaid_billed_inr`). One variable cannot answer both
    "what did we pay" and "what does the client owe", and this function answers the first.

    WHAT A CLIENT ACTUALLY PAYS FOR A MINUTE is `prepaid_billed_inr` on the prepaid motion
    and `billing.service.priced_overage` on the managed one, PLUS the model surcharge their
    plan quotes (`plans.llm_model_surcharge`, D-455). **None of the three takes a model,
    and that is still the whole point**: minutes are billed at the plan's rate, and the
    upgrade is billed at the plan's SURCHARGE — a rate a founder set, never a figure
    derived from this function.

    **THIS PARAGRAPH USED TO END "and moves their bill by exactly zero", WHICH WAS TRUE AND
    WAS THE DEFECT.** D-454 gave clients the choice and nothing priced it, so a client
    moving onto a model that costs us 2.7x paid nothing more. D-455 is the repricing;
    what has NOT changed is that this figure is still ours and is still not the client's
    price. A screen that prints it beside the words "what you pay" is wrong twice — it
    states a number nobody is charged, and it publishes our supplier cost and hence our
    margin to the client it is a margin on. The client-facing figure is
    `client_surcharge_inr_per_minute` (`agents/llm_routes.py`), and this one appears only
    on the operator's console; `tests/llm_cost_model_test.py` pins that no function
    deciding a client's bill can be told which model ran, so the two cannot be quietly
    reconciled the wrong way round.

    **IT PRICES FROM THE CATALOGUE REFERENCE, NOT FROM THE ATTESTED FIGURE**, and that is
    the one thing to know before reusing it. Its readers are TRD §10.1's published per-model
    rows, `scripts/check_docs_drift.py` (which recomputes each row and fails on drift) and the
    pilot scorecard — all of them statements about the MARGIN MODEL, which must be the same
    number on a laptop, in CI and on a founder's screen. An attested figure is per-deployment
    and absent in CI, so pricing this from it would make a documentation gate unrunnable
    anywhere the console had not been filled in, and would make TRD's published economics
    move when an operator typed. What a minute actually COSTS this account is
    `llm_inr_per_ktok`, and the gap between the two is the known +10% Regional Standard
    premium named at `_LLM_INR_PER_KTOK`.

    Rounded ONCE, at the end. Quantizing per turn would round 6·N times and drift.
    """
    if minutes < 1:
        raise ValueError("a reference call is at least one minute")
    price = llm_reference_inr_per_ktok(model)
    turns = minutes * REFERENCE_CALL["turns_per_minute"]
    # Turn k carries the prompt plus everything said before it (k-1 exchanges), so the
    # sum over the call is `turns * prompt + turn_tokens * (0 + 1 + … + turns-1)`.
    input_tokens = REFERENCE_CALL["prompt_tokens"] * turns + REFERENCE_CALL["turn_tokens"] * (
        turns * (turns - 1) // 2
    )
    output_tokens = REFERENCE_CALL["output_tokens_per_turn"] * turns
    total = (Decimal(input_tokens) * price["in"] + Decimal(output_tokens) * price["out"]) / Decimal(
        "1000"
    )
    return (total / Decimal(minutes)).quantize(MONEY_Q, rounding=ROUNDING)


def tts_rate_inr_per_char() -> Decimal:
    """Exact, unquantized: ₹30/10,000 is ₹0.003 and dividing is where precision is lost
    if it is done twice. Callers multiply by a character count and quantize once.

    No tier argument — there is one voice quality (the single-tier decision), so there is
    one rate and nothing to select."""
    return TTS_INR_PER_10K_CHARS / _CHARS_UNIT


def tts_cost_inr(chars: int) -> Decimal:
    """What `chars` characters of Bulbul v3 speech cost us.

    A CHARACTER COUNT IS REQUIRED — there is no default and no estimate. TRD §10.1's
    "360-540 chars per call-minute" is explicitly an unmeasured assumption (pilot gate
    12), so imputing a count here would put a made-up number on a ledger row and let it
    be read back later as a fact. Callers that do not have a count do not get a price.
    """
    if chars < 0:
        raise ValueError("character count cannot be negative")
    return (tts_rate_inr_per_char() * Decimal(chars)).quantize(MONEY_Q, rounding=ROUNDING)


def stt_rate_inr_per_second() -> Decimal:
    """Exact, unquantized: ₹30/hour is ₹0.008333… per second and no 4-decimal rupee holds
    it. Callers multiply by a duration and quantize ONCE — the same contract
    `tts_rate_inr_per_char` above has with its callers, for the same reason.

    **PER SECOND, because that is the unit a call's duration exists in everywhere in this
    codebase**: `ExecutionSnapshot.duration_s`, `workers/pipeline.py::_billable_seconds`,
    the `stt_s` usage rows it writes, `agents/models.py::CALL_CAP_MAX_S`. A per-minute
    signature would push `duration_s / 60` onto every caller — a lossy division done N
    times in place of an exact multiplication done once, and the arithmetic this module
    exists to keep out of the rest of the tree.
    """
    return STT_INR_PER_HOUR / _SECONDS_PER_HOUR


def stt_rate_inr_per_minute() -> Decimal:
    """The same rate in TRD §10.1's other spelling (₹0.50/min), DERIVED and never restated.

    Exact and unquantized for `stt_rate_inr_per_second`'s reason. This exists so the doc's
    per-minute cell has something in code to be diffed against
    (`scripts/check_docs_drift.py` §4d) without a second constant that could disagree with
    the first.
    """
    return STT_INR_PER_HOUR / _MINUTES_PER_HOUR


def stt_cost_inr(duration_s: int) -> Decimal:
    """What `duration_s` seconds of Saaras transcription cost us, at Sarvam's list rate.

    ⚠ **A MODEL FIGURE, NEVER A BILL — and unlike the TTS half this leg HAS a real
    counterpart on the ledger, so the distinction is sharper here than it is one function
    up.** What reaches `usage_events.unit_cost_paid` for STT is the ENGINE's own reported
    per-leg cost: `CostBreakdown.stt_inr` (`engine/bolna.py::_cost`, `leg("transcriber")`),
    divided by the call's billable seconds in `workers/pipeline.py::_meter` to make a price
    per unit of `qty`. Nothing on that path consults this function and nothing may: the
    engine rents its own Sarvam account, so what IT charges us is a fact about ITS invoice,
    while this card is a fact about Sarvam's list. Two numbers with two meanings — "what we
    pay" and "what the vendor lists" — and they are never the same variable again, which is
    the argument `llm_cost_inr_per_minute` makes for the LLM leg arriving on the speech one.

    **THE VENDOR'S BILLING GRANULARITY IS UNKNOWN, AND IS NOT IMPUTED.** The catalogue
    prices "per hour of audio"; whether a request is billed on exact audio duration, on
    whole seconds, or rounded up to some minimum billable unit is stated nowhere the
    founder could find and nowhere this container can reach. So this prices the seconds it
    is given and invents no minimum — the refusal `tts_cost_inr` makes about character
    counts, on the axis where this leg could be guessed. The consequence is stated rather
    than hidden: if Sarvam rounds a request up, this is a **FLOOR** on our real cost, so
    the margin model errs toward reporting a thinner margin than we have and can never
    quietly report a fatter one. A Sarvam invoice line against a request of known duration
    is what settles it.

    Zero is zero (a call that transcribed nothing costs nothing); a negative duration is
    refused rather than priced, because a negative cost on a usage event is a credit issued
    by an arithmetic accident — the same argument `tts_cost_inr` makes, and the one
    `_billable_seconds` had to make on the live money path.
    """
    if duration_s < 0:
        raise ValueError("audio duration cannot be negative")
    return (stt_rate_inr_per_second() * Decimal(duration_s)).quantize(MONEY_Q, rounding=ROUNDING)


#: THE BLENDED ALL-IN COST OF ONE SELF-SERVE CALL-MINUTE, used to MODEL MARGIN — never to
#: bill. This is the per-minute figure the prepaid credit-pack margin guard
#: (`billing/credit_packs.py`, `tests/credit_packs_test.py`) checks every pack's effective
#: rate against, so that no volume bonus can be set deep enough to sell minutes below a 20%
#: gross margin.
#:
#: ⚠ **EVIDENCE CLASS: ESTIMATE (pilot gate 12), founder-approved for margin modelling.**
#: It is TRD §10.3's launch blend (platform + STT + TTS + LLM + telephony ≈ ₹3.26-3.76/min),
#: taken at ₹3.70 — the founder-approved cost floor for the credit-pack rate card (Aug 2026).
#: The platform and telephony legs inside that blend are UNVERIFIED estimates and no check
#: can say otherwise (TRD §10, `scripts/check_docs_drift.py`), so this is deliberately a
#: single documented constant rather than a sum assembled from those unverified legs dressed
#: as if measured. It is NOT `unit_cost_paid` and reaches no bill (hard rule 7 is about the
#: billed figure): a pilot measurement or a real invoice is what would replace it.
#:
#: ⚠ **SENSITIVITY.** At the TOP of the launch band (₹3.76) the two deepest packs dip just
#: under 20% (≈19.4% and ≈18.8%); the ₹3.70 floor is the founder's approved basis and is
#: what the deepest bonus (8%) was capped against. If the measured cost lands above ₹3.70 the
#: guard will fail and the ₹24,999/₹50,000 bonuses must come down — which is the guard
#: working, not a bug.
SELF_SERVE_COST_FLOOR_INR_PER_MIN: Final[Decimal] = Decimal("3.70")


# --- THE ONE GROSS-MARGIN FLOOR, AND THE ONE FORMULA (hoisted from credit_packs) ------
#
# `MIN_GROSS_MARGIN` used to live in `billing/credit_packs.py`, beside the prepaid packs
# that were the only thing checking a margin. A committed-volume BUNDLE plan
# (`plans.monthly_fee` / `included_min` / `overage_rate`) sells minutes too, and nothing
# verified ITS rates cleared the same floor — so an operator could agree a bundle below
# cost by accident. That is a second caller for the same invariant, and a second COPY of
# the constant would be exactly the "two ways to say one thing" defect the repo forbids:
# the two would drift the day one is edited, and a founder reading "20% floor" would have
# to know which module's 20% they were reading. So the floor and its formula live HERE, in
# the lowest money module, next to the cost floor they are always compared against, and
# `credit_packs.py` imports them. This is the same move `MONEY_Q`/`ROUNDING` already made
# for the rounding facts one section up, and for the same reason.
#
# Gross margin here is `(rate - cost) / rate` — the fraction of each retail rupee that is
# NOT supplier cost. Founder-approved: no minute may be sold below 20% margin, which caps
# how deep a volume bonus (packs) or how thin a bundle rate (plans) may go.
MIN_GROSS_MARGIN: Final[Decimal] = Decimal("0.20")


def gross_margin_ratio(*, rate: Decimal, cost: Decimal) -> Decimal:
    """`(rate - cost) / rate`, EXACT and unquantized. NUMERIC in, NUMERIC out (hard rule 7).

    The one definition of gross margin, so the prepaid pack guard and the committed-bundle
    guard cannot disagree about what the word means. Unquantized because callers divide by
    it or compare it against a fraction floor — rounding here would round twice.

    `rate` must be positive: a zero or negative retail rate has no defined margin (you
    cannot express a supplier cost as a fraction of nothing), and it is a below-cost sale
    the caller has already decided to refuse. Callers guard `rate > 0` before asking;
    `committed_plan_margin` below does exactly that.
    """
    return (rate - cost) / rate


# --- THE COMMITTED-VOLUME BUNDLE MARGIN GUARD (D-469) ---------------------------------
#
# WHY THIS LIVES IN THE COST MODEL AND NOT IN `plans.py` OR `terms.py`. `plans.py` answers
# "which dated row is in effect"; `terms.py` is the writer of a row. Neither knows what a
# minute COSTS — that is this module's whole subject, and the margin of a bundle is a
# statement about a rate against `SELF_SERVE_COST_FLOOR_INR_PER_MIN` and `MIN_GROSS_MARGIN`,
# both of which live here. Putting the computation here keeps it a pure function of the two
# founder-approved constants beside it, exactly as `pack_gross_margin_ratio` sits beside
# them for the prepaid motion, and keeps the admin write path (`admin/routes.py`) a thin
# caller that decides POSTURE (refuse vs warn) rather than arithmetic.
#
# The effective committed per-minute rate of a bundle is `monthly_fee / included_min`: the
# retainer buys `included_min` minutes, so that division is what the client actually pays
# for each bundled minute. The overage rate is `overage_rate` directly. Either may be UNSET
# (`None`), and unset is NOT zero (the null-semantics rule `terms.CommercialTerms` and
# `admin/routes.CommercialTermsIn` both state): a bundle with no `included_min` quotes no
# committed rate to check, and an unset `overage_rate` quotes no overage to check.


@dataclass(frozen=True, slots=True)
class RateMargin:
    """One retail per-minute rate, judged against the cost floor and the margin target.

    `below_cost` and `below_target` are DISJOINT and each drives a different posture at the
    write path: a rate below cost is a guaranteed loss (refused server-side), a rate at or
    above cost but under `MIN_GROSS_MARGIN` is a deliberate thin-margin call (warned, not
    refused). `margin` is `None` only when the rate is non-positive, where the ratio is
    undefined — the rate is still `below_cost` (a free or negative minute is a loss), it
    simply has no fraction to display.
    """

    rate: Decimal
    margin: Decimal | None
    below_cost: bool
    below_target: bool


def _rate_margin(rate: Decimal, *, cost: Decimal, target: Decimal) -> RateMargin:
    """Judge one rate. `below_cost` strictly (`rate < cost`); `below_target` only when the
    rate clears cost yet the margin falls under the target."""
    below_cost = rate < cost
    margin = gross_margin_ratio(rate=rate, cost=cost) if rate > 0 else None
    below_target = margin is not None and not below_cost and margin < target
    return RateMargin(rate=rate, margin=margin, below_cost=below_cost, below_target=below_target)


@dataclass(frozen=True, slots=True)
class CommittedPlanMargin:
    """The margin verdict on a committed-volume bundle's two client rates.

    `committed` / `overage` are `None` when that rate is unset — nothing to judge, not a
    zero. `below_cost()` / `below_target()` name the rates that tripped each line, so the
    caller can build a message and a log line that say WHICH rate is the problem.
    """

    effective_committed_rate: Decimal | None
    committed: RateMargin | None
    overage: RateMargin | None

    def _judged(self) -> tuple[tuple[str, RateMargin], ...]:
        """The rates that were actually set, by name — an unset rate is judged by nothing."""
        pairs = (("committed", self.committed), ("overage", self.overage))
        return tuple((name, rm) for name, rm in pairs if rm is not None)

    def below_cost(self) -> tuple[str, ...]:
        """Names of the set rates priced below the cost floor — a guaranteed loss."""
        return tuple(name for name, rm in self._judged() if rm.below_cost)

    def below_target(self) -> tuple[str, ...]:
        """Names of the set rates at/above cost but under `MIN_GROSS_MARGIN`."""
        return tuple(name for name, rm in self._judged() if rm.below_target)


def committed_plan_margin(
    *,
    monthly_fee: Decimal | None,
    included_min: int | None,
    overage_rate: Decimal | None,
    cost: Decimal = SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    target: Decimal = MIN_GROSS_MARGIN,
) -> CommittedPlanMargin:
    """The gross margin of a committed bundle's committed and overage rates at the cost floor.

    Pure and total: every argument may be `None` (unset), and unset yields a `None` verdict
    for that rate rather than a judged zero — the load-bearing null semantics
    `CommercialTerms` states. A committed rate exists only when BOTH `monthly_fee` and a
    POSITIVE `included_min` are set; `included_min` of 0 (or unset) means no minutes are
    bundled, so there is no committed per-minute rate to judge — every minute is overage.

    `cost`/`target` are arguments with the founder-approved defaults so a test can pin an
    exact case without reaching into module state, mirroring `pack_gross_margin_ratio`.
    Decimal throughout (hard rule 7): the division uses `Decimal(included_min)`, never a
    float, and the effective rate is left EXACT for the margin ratio — callers that display
    it quantize once at the boundary.
    """
    if monthly_fee is not None and included_min is not None and included_min > 0:
        effective = monthly_fee / Decimal(included_min)
    else:
        effective = None
    committed = None if effective is None else _rate_margin(effective, cost=cost, target=target)
    overage = None if overage_rate is None else _rate_margin(overage_rate, cost=cost, target=target)
    return CommittedPlanMargin(
        effective_committed_rate=effective, committed=committed, overage=overage
    )


#: The plan tiers whose every minute is charged at a published list price, with no
#: included allowance in front of it. Spelled once because three places branch on it —
#: the meter's `charge_for_call`, the runway framing and `billing.service
#: .calling_revenue_inr` — and a fourth tier added to one of them and not the others is a
#: wallet that stops draining.
PREPAID_TIERS: Final = ("self_serve", "trial")


def prepaid_billed_inr(*, minutes: Decimal, self_serve_rate: Decimal) -> Decimal:
    """What a PREPAID client is charged for `minutes` of calling. Never what we paid.

    THE DEFECT THIS EXISTS FOR (P1.1/P1.3). `charge_for_call` was debiting the prepaid
    wallet with `cost.total_inr` — the engine's charge to US, ~₹2/min — while the runway
    framing on the client's own screen priced the same minute at `self_serve_inr_per_min`
    (₹5.00). The balance drained at a third of the advertised rate and Calevate booked
    zero gross margin on the entire self-serve motion. `spend_state.spend_used` had the
    same two-numbers-in-one-column problem one layer up, where it is the ceiling a client
    sets for themselves and the figure we print for them.

    So: THIS answers "what does the client owe", `cost.total_inr` answers "what did we
    pay", and they are never the same variable again. `unit_cost_paid` on the ledger row
    and the admin margin panel keep the second, because margin is the difference and a
    deployment that overwrote the paid side could never compute it, including
    retrospectively.

    **PREPAID ONLY, and it used to answer for managed tenants too.** It took a
    `marginal_rate` and, for a managed tier, returned `rate x minutes` — a SECOND way of
    pricing a managed month beside `billing.service.priced_overage`, which is what the
    panel and the invoice use. The two agreed only while a plan quoted a single overage
    rate; the meter now asks `priced_overage` what the month costs with this call and
    without it, so there is one rule and this function is the prepaid half of it. The
    managed arguments that lived here have moved with the branch: `priced_overage`
    carries "an unpriced plan accrues nothing, and a list price is deliberately not
    substituted for one".

    **PREPAID IS EXACT.** Every minute is charged at the list price — there is no
    included allowance to net off — so this IS their bill, and it is priced from the same
    config value the runway and the top-up flow read, which is what `config.py` already
    promised and only two of the three honoured.

    Quantized ONCE, at the end, with the explicit mode — the rate is a per-minute price
    with more precision than a rupee amount has, and rounding the multiplication rather
    than the rate is what keeps `rate x minutes` reading back as the product it was.
    """
    if minutes <= 0 or self_serve_rate <= 0:
        return Decimal("0").quantize(MONEY_Q, rounding=ROUNDING)
    return (self_serve_rate * minutes).quantize(MONEY_Q, rounding=ROUNDING)


# --- the MODEL SURCHARGE: the client's half of D-454's choice (D-455) -----------------
#
# **THE DEFECT THIS CLOSES.** D-454 gave a client a picker over `AZURE_OPENAI_MODELS`, and
# `llm_cost_inr_per_minute` above records that `gpt-4.1-mini` costs us 2.7x the default on
# both token legs. Nothing downstream priced that: `plans` had no model column,
# `prepaid_billed_inr` and `billing.service.priced_overage` price MINUTES at the plan's
# rate, and neither takes a model. So the dearer model was pure margin loss — a client
# could move their whole account onto it and their bill moved by exactly ₹0.00. The
# paragraph on `llm_cost_inr_per_minute` still stands unchanged and is the reason THIS is
# a separate number: our supplier cost is not a client price and must never be published
# as one. What a client pays for the upgrade is a term of their PLAN
# (`plans.llm_model_surcharge`), decided by a founder, and it is quoted per minute like
# every other rate on that row.
#
# **A SURCHARGE, NOT A REPLACEMENT RATE**, and that is what makes it shippable: the plan's
# per-minute rate stays the base, a NULL surcharge reproduces today's arithmetic exactly on
# every existing plan, and the base-rate model is free of change by construction. There is
# no repricing of live plans anywhere in this change.

#: The model the plan's per-minute rate is struck AT. Any other model a client CHOOSES is
#: an upgrade and carries the plan's surcharge.
#:
#: **THE FROZEN CONSTANT, NOT `Settings.azure_openai_model`, AND THE OPPOSITE CHOICE FROM
#: `agents/llm_models.platform_default_model()`.** That function reads the live setting
#: because it answers "what will an agent RUN"; this answers "what was the price struck
#: for", which is a fact about a rate card and must not move when an operator flips a
#: console switch. If it read the live setting, flipping the platform default would
#: silently re-classify every historical minute — the ledger stamp
#: (`usage_events.meta.llm_model`) exists precisely so a past call's model survives the
#: live rows moving, and a baseline that moved would throw that away one layer up.
BASE_RATE_LLM_MODEL: Final = AZURE_OPENAI_DEFAULT_MODEL

#: The `llm_model_source` values that mean **the client chose it** (`agents/llm_models.py`
#: resolves `agent` -> `organization` -> `platform`).
#:
#: **`platform` IS DELIBERATELY ABSENT, AND IT IS THE SAFETY PROPERTY OF THIS WHOLE
#: FEATURE.** `platform` means nobody on the client's side picked anything — the model is
#: whatever `Settings.azure_openai_model` happens to be. An operator flipping that switch
#: would otherwise raise the bill of every client who had never touched the picker, on the
#: next call, with no consent and no notice. A surcharge is the price of an upgrade the
#: client asked for; an upgrade we imposed is our cost.
CLIENT_CHOSEN_LLM_SOURCES: Final[frozenset[str]] = frozenset({"agent", "organization"})


def is_surchargeable_llm_model(model: str | None) -> bool:
    """Is this model an UPGRADE on the one the plan's rate is struck at — i.e. dearer?

    **IT USED TO MEAN "NOT THE BASE MODEL", AND THAT BROKE THE DAY A CHEAPER MODEL EXISTED.**
    While every choosable model was an Azure one dearer than `gpt-4o-mini`, "not the base"
    and "an upgrade" were the same set, and `surchargeable_models_are_dearer()` below existed
    precisely to fail the day they stopped being. They stopped being on the multi-provider
    offering: `gemini-2.5-flash-lite` lists at $0.10/$0.40 against the base model's
    $0.15/$0.60 — CHEAPER on both legs. Under the old test a client moving onto it would have
    been charged the plan's upgrade surcharge **for saving us money**, which is not a pricing
    disagreement but a charge for something we did not supply.

    **SO THE SURCHARGE FLOORS AT ZERO, AND THERE IS NO NEGATIVE ARM.** A model at or below the
    base rate on either leg is simply not surcharged; it is not a credit. The rejected
    alternative was a signed differential that discounts a client onto a cheaper model, and it
    was rejected on the same ground D-455 gives for the surcharge itself: what a client PAYS
    is a term of their plan set by a founder, not a figure derived from our supplier cost. A
    derived discount would publish our margin in the one direction a client could arithmetic
    backwards, and `tests/llm_cost_model_test.py` pins that no function deciding a client's
    bill can be told which model ran. A cheaper model is a cheaper minute for US; the client
    keeps their plan's rate.

    **BOTH LEGS MUST BE DEARER, not their blend**, for `surchargeable_models_are_dearer()`'s
    original reason: a model cheaper on input and dearer on output is not a straightforward
    upgrade, and which way it lands depends on a conversation's shape rather than on a rate
    card. That is a founder's decision, not a predicate's, and this returns False so the
    default is the one that cannot overcharge.

    **TOTAL AND NEVER RAISING**, including on an identifier this repository no longer prices.
    A model read back off a historical `usage_events` row is exactly what `llm_inr_per_ktok`
    refuses, and a month that cannot be re-priced is not an acceptable answer for a statement.
    An unknown model is therefore NOT surcharged — the same client-favouring asymmetry the
    overage rung reader applies to a call with no stamped rung, and for the same reason: the
    absence of evidence is never evidence of the dearer thing.

    **PRICED FROM THE CATALOGUE REFERENCE, NOT FROM THE ATTESTATION.** Which models are
    upgrades is a property of the rate card a plan was written against, and it must not change
    because an operator entered an invoice figure this morning — that would silently
    re-classify what an account is billed for, which is the same frozen-baseline argument
    `BASE_RATE_LLM_MODEL` carries one paragraph up.
    """
    if not model or model == BASE_RATE_LLM_MODEL:
        return False
    spec = LLM_MODELS.get(model)
    base = LLM_MODELS.get(BASE_RATE_LLM_MODEL)
    if spec is None or base is None:
        return False
    return (
        spec.price.input_usd_per_mtok > base.price.input_usd_per_mtok
        and spec.price.output_usd_per_mtok > base.price.output_usd_per_mtok
    )


def llm_surcharge_applies(*, model: str | None, source: str | None) -> bool:
    """Does the plan's model surcharge apply to a minute metered with this stamp?

    Both halves of the ledger stamp are read, and each refuses on its own:

    * an unrecognised, absent or base-rate `model` is not an upgrade (see above). A row
      written before D-454 stamped the model carries neither key and bills as base, which
      is the same client-favouring asymmetry the overage rung reader applies to an
      unattributed call — the absence of evidence is never evidence of the dearer thing;
    * a `source` outside `CLIENT_CHOSEN_LLM_SOURCES` means the client did not choose it.

    **PRICED FROM THE STAMP, NEVER FROM `agents.llm_model`.** Both columns behind that
    stamp are editable from two screens in two realms, so reading them at invoice time
    would re-price every closed month the moment a client switched. The stamp is what
    `apps/workers/pipeline.py::_meter` writes for this exact reason.
    """
    return is_surchargeable_llm_model(model) and source in CLIENT_CHOSEN_LLM_SOURCES


def surchargeable_models_are_dearer() -> bool:
    """Is every model this surcharge WOULD apply to actually dearer than the base?

    **IT NO LONGER GUARDS THE SAME THING, AND SAYING SO IS THE POINT OF KEEPING IT.** It was
    written as a tripwire under a crude predicate: `is_surchargeable_llm_model` tested "not
    the base model", so this had to verify that no cheaper model had crept into the choosable
    set, and it was designed to FAIL the day one did. One did — `gemini-2.5-flash-lite` — and
    the fix was to correct the predicate rather than to widen this. So it is now a
    CONSISTENCY check between two statements of one rule: everything the predicate surcharges
    really is dearer on both legs. That is a weaker guarantee than it used to make and a
    stronger one about the code, and deleting it would remove the only place the two are
    compared.

    Stated over the reference card because that is what the predicate reads. A PREDICATE
    rather than an assert at import, for `every_selectable_model_is_priced`'s reason: a reader
    wants the invariant in words and `tests/llm_model_surcharge_test.py` wants a named failure.
    """
    base = LLM_MODELS[BASE_RATE_LLM_MODEL].price
    return all(
        LLM_MODELS[model].price.input_usd_per_mtok > base.input_usd_per_mtok
        and LLM_MODELS[model].price.output_usd_per_mtok > base.output_usd_per_mtok
        for model in PRICED_LLM_MODELS
        if is_surchargeable_llm_model(model)
    )


def llm_surcharge_billed_inr(*, minutes: Decimal, surcharge: Decimal | None) -> Decimal:
    """What a client is charged for `minutes` run on an upgraded model. ONE CALL'S WORTH.

    The exact sibling of `prepaid_billed_inr`, at the same quantum and for the same
    readers: this is a LEDGER-scale figure (`MONEY_Q`, the NUMERIC(12,4) storage scale of
    the columns it lands in) charged against ONE call's own minutes, so a client reading
    their wallet entry by entry sees a call charged for its own length.

    A whole MONTH's surcharge is `billing.service.priced_llm_surcharge`, which quantizes to
    PAISE once over the month's allocated minutes — the same two-quantum split
    `prepaid_billed_inr` and `calling_revenue_inr` already carry, with the same bounded
    residual between them that `calling_revenue_inr` measures and names.

    `None` is "this plan quotes no surcharge" and returns zero, which is also what a
    quoted surcharge of zero returns: a plan may legitimately give the upgrade away, and
    the DISTINCTION between the two is kept where it means something (on the plan row and
    on the screens that publish a rate), never in the amount.
    """
    if surcharge is None or minutes <= 0 or surcharge <= 0:
        return Decimal("0").quantize(MONEY_Q, rounding=ROUNDING)
    return (surcharge * minutes).quantize(MONEY_Q, rounding=ROUNDING)


__all__ = [
    "BASE_RATE_LLM_MODEL",
    "CLIENT_CHOSEN_LLM_SOURCES",
    "ENGINE_REPORTS_TTS_MODEL",
    "ENGINE_TTS_MODEL_GENERATION_VERIFIED",
    "LIST_PRICE_USD_INR",
    "MIN_GROSS_MARGIN",
    "MONEY_Q",
    "PREPAID_TIERS",
    "PRICED_LLM_MODELS",
    "REFERENCE_CALL",
    "ROUNDING",
    "SARVAM_LLM_INR_PER_MTOK",
    "SARVAM_PRICED_LLM",
    "SELF_SERVE_COST_FLOOR_INR_PER_MIN",
    "STT_INR_PER_HOUR",
    "TTS_INR_PER_10K_CHARS",
    "CommittedPlanMargin",
    "LlmPriceAttestation",
    "LlmPriceAttestationReader",
    "RateMargin",
    "attested_llm_prices",
    "committed_plan_margin",
    "gross_margin_ratio",
    "install_llm_price_attestations",
    "is_surchargeable_llm_model",
    "llm_cost_inr_per_minute",
    "llm_inr_per_ktok",
    "llm_price_is_billable",
    "llm_reference_inr_per_ktok",
    "llm_surcharge_applies",
    "llm_surcharge_billed_inr",
    "prepaid_billed_inr",
    "sarvam_llm_reference_inr_per_ktok",
    "stt_cost_inr",
    "stt_rate_inr_per_minute",
    "stt_rate_inr_per_second",
    "surchargeable_models_are_dearer",
    "tts_cost_inr",
    "tts_rate_inr_per_char",
]

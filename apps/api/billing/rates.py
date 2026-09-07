"""The TTS cost model for TWO voice tiers, the in-call / dashboard LLM cost model, and
the two per-minute COST FLOORS the credit-pack card is judged against.

TWO VOICE TIERS, TWO COST SHAPES (D-547, 7 Sep 2026 — supersedes the un-numbered
single-tier voice decision that used to head this file)
--------------------------------------------------------------------------------------
A client's agent speaks with one of two voices, and the tier is a property of the AGENT —
DERIVED from the chosen voice's `provider` and stored nowhere (plan §3.3: a second column
could disagree with the voice, so there is not one; invariant 7 is Phase C's test):

* **`sarvam`** — Bulbul v3, a PER-CHARACTER list price (`TTS_INR_PER_10K_CHARS`). Its
  worst-case per-call-minute cost is the top of TRD §10.1's assumed speaking band, and
  it is one of the four legs summed into `SELF_SERVE_COST_FLOOR_INR_PER_MIN`.
* **`cartesia`** — Sonic 3.5, a MONTHLY PLAN with a character allotment, no
  pay-as-you-go option (`docs/evidence/cartesia-tts-verification-2026-09-06.md`). A plan
  has no per-character price until it is spread over the minutes it served, so its floor
  is the ex-plan legs PLUS the plan fee per minute at the count where the allotment is
  exactly consumed (`CARTESIA_COST_FLOOR_INR_PER_MIN`, and the arithmetic beside it).

`cost_floor_inr_per_min(voice)` is the one door to either floor. The credit-pack card
(`billing/credit_packs.py`) carries a Sarvam AND a Cartesia rate on every pack, and each
is judged against its own floor — `rate_margin` below is the verdict, the same
refuse-below-cost / warn-below-target posture `committed_plan_margin` already applies to a
bundle (D-469). **A voice tier is never a bill**: what a Cartesia call actually COSTS us
per character is Phase D's `TtsPriceAttestation`; everything here is the margin MODEL.

⚠ **THE APPROVED CARD IS BELOW THE 20% TARGET ON ITS WHOLE SARVAM COLUMN AND ABOVE COST
THROUGHOUT** — 17.6% at ₹5.00 down to 8.4% at ₹4.50 against a ₹4.1211 floor. That is the
founder's card (plan §2.2) read against a floor re-derived without telephony, and it is
why the guard REFUSES below cost and only REPORTS below target. Do not "fix" a
below-target row by moving the floor.

The previous two-rung ladder (Bulbul v3 "premium" beside a Bulbul v2 "value" rung, with
`billable_tier` billing the cheaper rung when a premium voice could not be proven) was
withdrawn before this change and its machinery deleted; the second tier that exists now is
a different VENDOR at a different price, chosen per agent, never a fallback.

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
from typing import Final, Literal

from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
)

from apps.api.billing.models import MONEY

# Sarvam's published Bulbul v3 rate, TRD §10.1. Per 10,000 characters, INR. NUMERIC,
# never a float.
#
# **THE SARVAM RUNG, and deliberately a scalar and not a mapping.** The second voice tier
# (Cartesia Sonic 3.5, D-547) is NOT a second entry here, because it is not a
# per-character list price: it is a monthly plan whose marginal per-character figure
# (`CARTESIA_TTS_INR_PER_10K_CHARS`, below the LLM section) is DERIVED from the plan fee
# and its allotment and is true only when the allotment is consumed. Putting the two side
# by side in one mapping would let a reader price a Cartesia character as if it were
# metered, which is the misreading the Cartesia evidence file exists to correct. The
# earlier `Mapping[TtsTier, Decimal]` (a ₹30 premium and a ₹15 value rung of the SAME
# vendor) and the tier-honesty machinery around it were deleted when the v2 rung was
# withdrawn, and nothing here selects a rung.
#
# THIS IS THE HOME OF THE RATE, and TRD §10.1 is the doc that states it.
# `scripts/check_docs_drift.py` §4b diffs the two in both directions — on BOTH rungs, the
# Sarvam one here and the Cartesia one below — and also checks §10.1's two spellings of
# each rate (₹/10,000 in the vendor card, ₹/1,000 in the per-call-minute table) against
# each other. Before that check existed, a vendor price move could land in the doc and not
# here — the shape D-102/D-103/D-105 each paid for, on the axis where it moves money.
TTS_INR_PER_10K_CHARS: Final[Decimal] = Decimal("30.0000")  # Bulbul v3

# TRD §10.1's ASSUMED speaking rate — the band the whole TTS line is priced from, and the
# one figure in the cost model that no vendor rate card can supply. §10.1 says it in its
# own words: *"the agent speaks 40-60% of a call, at ~900 characters/minute of actual
# speech → 360-540 TTS characters per call-minute. That ratio is itself unmeasured"*.
# 360 = 0.40 x 900 and 540 = 0.60 x 900, chars of agent speech per minute of CALL.
#
# WHY IT IS A CONSTANT AND NOT A SENTENCE. It is a FALLBACK, not a fact: it is what the
# cost floor rests on until `billing/tts_speaking_rate.py` has read enough real calls to
# replace it, and the board that publishes the measurement prints this band beside it so
# an operator can see what the number displaced. A band quoted in prose in two places
# is the D-102/D-105 drift class on the axis that moves the most money
# (₹0.27-0.40/min of a ₹3.70 floor), so `scripts/check_docs_drift.py` §4e diffs this
# pair against §10.1's sentence in both directions. Chars per call-minute, as Decimal so
# the ₹/min it implies is computed in the same arithmetic as every other rupee here.
TTS_ASSUMED_CHARS_PER_CALL_MINUTE: Final[tuple[Decimal, Decimal]] = (
    Decimal("360"),
    Decimal("540"),
)

# Whether the engine's execution payload names the synthesizer model that served a call.
# A greppable capability constant (the honesty device `scripts/check_docs_drift.py` §5 and
# `tests/capability_claim_guard_test.py` verify against prose), discovered by AST, not a
# hand-listed registry. It guards no bill: from Phase B a client's minute is priced at the
# lot's rate for the AGENT's own voice tier (D-547, plan §2.3.7), which is a fact about our
# `agents` row and not about what the engine reports — so an engine that silently fell back
# from Cartesia to Sarvam would cost us LESS than the client paid for, never more, and the
# publish read-back (`agents/verification.py`, Phase C.5) is what is being built to detect
# the fallback. It stays False because it is still a true statement about the engine (see
# the module docstring: the `usage_breakdown` block is an orphan schema our snapshot has no
# field for). Flip it only when a captured payload proves the model is reported (D-358,
# OPERATIONS §2 gate 7).
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
#: ⚠ **EVIDENCE CLASS: REPORTED, NOT READ, AND IT REACHES `unit_cost_paid`.** No session can
#: re-fetch it: `www.rbi.org.in` is refused by this container's egress proxy on CONNECT (the
#: same measurement `apps/workers/fx_pull.py` records for every FX host it tried). So this is
#: a figure a past session wrote down, and hard rule 11 is explicit that a value already in
#: this repo is not evidence of itself. It is called out HERE rather than left implied
#: because of where it ends up: `_usd_mtok_to_inr_ktok` converts BOTH the catalogue card and
#: an operator's attested USD invoice figure, so `llm_inr_per_ktok` — the one door to
#: `usage_events.unit_cost_paid` for a dashboard assist — is this constant multiplied by an
#: attested price. Attesting the price does not attest the rate that converts it.
#:
#: WHAT THAT COSTS AND WHAT IT DOES NOT. It cannot mis-bill a CLIENT for calling: nothing on
#: the invoice is priced from it (`usage_summary` prices minutes at the plan's own rupee
#: rate). What it does move is money WE absorb and the rupee allowance the client is measured
#: against — a rate that has drifted 5% makes every assist read 5% cheap or dear against
#: `AI_QUOTA_INR`, in the same direction for every tenant, silently.
#:
#: WHAT CLOSES IT, and it is not a live read: the FX store this repository already runs
#: (`ops/fx_rates`, a published FBIL reference, plausibility-banded and age-bounded) holds a
#: rate an operator can quote, so the fix is an OPERATOR-ATTESTED strike rate beside the
#: attested prices — the same seam, one more field — decided by the founder, since which
#: instant a list price is struck at is a pricing decision and not a refactor. Deliberately
#: NOT `Settings.usd_inr_rate` and NOT the live quote, for the reason directly below.
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

    **THE ONE LEVER THAT WOULD BEND THIS CURVE IS PROMPT CACHING, AND WHETHER THE ENGINE
    EXPOSES IT IS UNKNOWN — NOT IN THE MIRROR (OPERATIONS §2 gate 42).** The system prompt
    is byte-identical every turn (`compose_engine_prompt`), so a provider that cached the
    resent prefix would bill it at a cache-hit rate — but the Bolna docs mirror documents
    prompt caching for DeepSeek ONLY (`bolna-findings/mirror/pages/providers/llm-model/
    deepseek.md:59-61`), not for our azure-openai / openai / google legs, and exposes no
    cache field on the agent config. This function therefore prices the FULL resend, with
    NO cache discount assumed: a saving nobody has cited may not be folded into the margin
    model (hard rule 11). Gate 42 closes it with a primary source and a `cached_tokens`
    reading on a real call; until then this curve is the honest one.

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

    No tier argument, on purpose: this is the SARVAM per-character rate. The Cartesia
    tier has no per-character list price to return — its leg is a plan, spread over
    minutes by `cartesia_plan_inr_per_call_minute` — and a `voice` argument here would
    invite a caller to meter a Cartesia character as if Sarvam's card applied to it."""
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


def tts_inr_per_call_minute(chars_per_call_minute: Decimal) -> Decimal:
    """What one minute of CALL costs on the TTS leg at a given speaking rate.

    TRD §10.1's per-call-minute cell — ₹1.08-1.62 — is exactly this function over
    `TTS_ASSUMED_CHARS_PER_CALL_MINUTE`, and the measured board
    (`billing/tts_speaking_rate.py`) is the same function over what the transcripts say.
    One function for both so the assumed and the measured figures can never be priced by
    two arithmetics; multiply once, quantize once (`tts_rate_inr_per_char`'s contract).

    A speaking rate is a Decimal and never a float: it is chars x 60 / seconds computed
    exactly upstream, and a float here would put the one rounding this module exists to
    avoid on the largest single leg of the cost model.
    """
    if chars_per_call_minute < 0:
        raise ValueError("a speaking rate cannot be negative")
    return (tts_rate_inr_per_char() * chars_per_call_minute).quantize(MONEY_Q, rounding=ROUNDING)


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


# --- THE TWO COST FLOORS, one per voice tier (D-547) ------------------------------------
#
# Each floor is the WORST-CASE cost of one call-minute on that voice, SUMMED FROM THE
# NAMED LEGS ABOVE rather than typed as one blended figure. The blend this replaced
# (₹3.70, "TRD §10.3's launch band taken at a founder-approved point") could not say
# which leg had moved when a vendor price did, and it carried a telephony leg that is not
# ours to carry. The sum re-scores itself when any leg constant moves, which is what a
# margin guard is for.
#
# **NO TELEPHONY LEG, on either floor (D-474, Model B).** The client buys the connection
# on their own carrier account (Exotel/Plivo/Vobiz), is the subscriber of record and is
# billed the per-minute carrier rate by that carrier — Calevate supplies, rents and bills
# no number. Plivo's ₹0.38/min is therefore the CLIENT's cost and folding it in here would
# defend our margin with a rupee we never pay.
#
# THE LEGS, with the evidence class of each (hard rule 11):
#
#   engine platform fee  ₹1.76  VERIFIED-VENDOR-DOCS — "**Call pricing**: $0.02/min
#                               platform fee (plus provider charges)"
#                               (`bolna-findings/mirror/pages/
#                               frequently-asked-questions.md:39`, the hash-pinned
#                               mirror, read 7 Sep 2026) at the ₹88/$ this section uses.
#                               ⚠ **UPGRADED FROM REPORTED, AND THE UPGRADE IS THE
#                               POINT.** This was a founder's dashboard screenshot
#                               (TRD §10.4, "observed at 2¢/min ≈ ₹1.76"; marked
#                               UNVERIFIED — pilot gate 12 at
#                               `docs/PRODUCTION-READINESS.md` §A1 row 12 H) until the
#                               vendor's own FAQ was read in the mirror and said the
#                               same number. Gate 12 is NOT closed by it: what the FAQ
#                               proves is the published rate, not OUR commercial term,
#                               and an invoice is still what settles that.
#                               ⚠ **AND THE VENDOR PUBLISHES A SECOND, DIFFERENT
#                               PER-MINUTE FIGURE THAT NO PAGE RECONCILES WITH IT:**
#                               `pricing/preferred-models.md:11` states a flat
#                               "$0.06/min (₹5.52/min)" that BUNDLES ASR + LLM + TTS.
#                               It is a different line item, not a different fee — BYOK
#                               explicitly opts out of the bundled components
#                               ("Bolna does not charge for those components. You only
#                               pay your providers directly, plus Bolna's platform fee",
#                               `pricing/call-pricing.md:75`) and we are BYOK on all
#                               three. So $0.02 is the leg for our shape. Recorded
#                               rather than resolved: if an invoice ever shows $0.06 on
#                               a BYOK call, this floor is ₹3.52 too low and every
#                               margin below is wrong by that much.
#                               ⚠ Billing GRANULARITY for the BYOK fee is **UNKNOWN**
#                               (the 30-second pulse is documented for the Pilot plan
#                               only), so per-minute is what the model assumes.
#   STT                  ₹0.50  VENDOR-PUBLISHED — `STT_INR_PER_HOUR` / 60, per the Sarvam
#                               catalogue reading recorded on that constant.
#   LLM                  ₹0.24  ESTIMATE over a VENDOR-PUBLISHED list price — the
#                               `REFERENCE_CALL` shape priced at TRD §10.1's LONGEST
#                               published point (10 min) on the base-rate model. Longest
#                               because the curve is quadratic in call length
#                               (`llm_cost_inr_per_minute`), so 10 min is the worst of the
#                               three the doc publishes; the model is the one the plan
#                               rate is frozen against (`BASE_RATE_LLM_MODEL` below is
#                               this same constant — `tests/cost_floor_test.py` pins it).
#   Sarvam TTS           ₹1.62  ESTIMATE over VENDOR-PUBLISHED — `TTS_INR_PER_10K_CHARS`
#                               at the TOP of `TTS_ASSUMED_CHARS_PER_CALL_MINUTE` (540
#                               chars/min, itself unmeasured — pilot gate 12).
#   ─────────────────────────
#   Sarvam floor         ₹4.1211/min  (1.76 + 0.50 + 0.2411 + 1.62)
#
# ⚠ **EVIDENCE CLASS OF THE SUM: ESTIMATE**, and it is now the SPEAKING RATE rather than the
# fee that caps it — the fee was upgraded to VERIFIED-VENDOR-DOCS above, and the weakest
# input left is `TTS_ASSUMED_CHARS_PER_CALL_MINUTE`'s 360-540 band, which TRD §10.1 itself
# calls unmeasured (pilot gate 12) and which the admin spend board's "TTS speaking rate —
# measured" card exists to replace. The floor takes the TOP of that band, so a real count
# inside it makes the floor conservative and a count ABOVE it makes the floor wrong in the
# expensive direction — Indic character density is exactly the risk §10.1 names. It models
# margin and reaches no bill (`unit_cost_paid` is hard rule 7's subject; this is not it).
# A pooled measurement at twenty or more calls is what replaces the band.

#: The engine's BYOK platform fee for one call-minute, in the unit the VENDOR publishes it
#: in. $0.02/min, VERIFIED-VENDOR-DOCS — see the leg table above for the citation, for why
#: the vendor's other published per-minute figure ($0.06 bundled) is a different line item,
#: and for the granularity question that is still open.
ENGINE_PLATFORM_FEE_USD_PER_MIN: Final[Decimal] = Decimal("0.02")

#: The conversion the whole per-minute cost model is struck at: ₹88 = US$1.00. The rate
#: TRD §10.4 used for the same fee and the rate the Cartesia evidence file states at every
#: line, kept as one constant here rather than two so a floor comparison is not secretly a
#: comparison of two exchange rates. NOT `LIST_PRICE_USD_INR` (₹95.66, the LLM card's own
#: strike, which is a fact about a different card); `tests/cost_floor_test.py` computes the
#: Cartesia floor under that one too and shows the card clears either.
COST_MODEL_USD_INR: Final[Decimal] = Decimal("88")

#: ₹1.76 — DERIVED, so a conversion change and a fee change are distinguishable. Written as
#: a rupee literal until D-547; the vendor states dollars, and restating their number in our
#: currency was a place a re-read could not land.
ENGINE_PLATFORM_FEE_INR_PER_MIN: Final[Decimal] = (
    ENGINE_PLATFORM_FEE_USD_PER_MIN * COST_MODEL_USD_INR
)

#: The reference call length the LLM leg is priced at inside a cost floor: the longest of
#: the three points TRD §10.1 publishes (1 / 5 / 10 min), because that curve rises with
#: length and a floor takes the worst case.
COST_FLOOR_REFERENCE_CALL_MINUTES: Final = 10


def _ex_tts_cost_inr_per_min() -> Decimal:
    """The three legs both voices share — fee, STT, LLM — EXACT, before any TTS leg.

    One function for both floors so the shared legs cannot be summed two ways. Not
    quantized: each floor quantizes ONCE after adding its own TTS leg.
    """
    return (
        ENGINE_PLATFORM_FEE_INR_PER_MIN
        + stt_rate_inr_per_minute()
        + llm_cost_inr_per_minute(
            COST_FLOOR_REFERENCE_CALL_MINUTES, model=AZURE_OPENAI_DEFAULT_MODEL
        )
    )


#: THE SARVAM-VOICE COST FLOOR: the worst-case cost of one call-minute spoken by Bulbul
#: v3, at `MONEY_Q`. DERIVED from the legs above (see the table) — never typed. It is what
#: every pack's `sarvam_inr_per_min` is judged against (`credit_packs.pack_rate_margin`)
#: and what a committed bundle's rates are judged against (`committed_plan_margin`, whose
#: bundles are all Sarvam-voiced today).
#:
#: The name keeps its pre-D-547 spelling because eleven readers across `admin/`, `tests/`
#: and this file use it; `cost_floor_inr_per_min("sarvam")` is the same number by the
#: voice's name, and the door new code should use.
SELF_SERVE_COST_FLOOR_INR_PER_MIN: Final[Decimal] = (
    _ex_tts_cost_inr_per_min() + tts_inr_per_call_minute(TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1])
).quantize(MONEY_Q, rounding=ROUNDING)


# --- THE CARTESIA TIER: a PLAN, spread over minutes ---------------------------------------
#
# Cartesia sells Sonic as a monthly subscription with a character allotment and NO
# pay-as-you-go option, so there is no per-character price to put beside Sarvam's until
# the fee is spread over the characters it bought. The figures below are the STARTUP plan,
# which is the plan we would buy: its 5 TTS concurrency units cover ten concurrent lines by
# the vendor's own "~4 conversations per unit" rule of thumb, where Pro's 3 is
# "borderline-adequate" by that same rule (evidence file §A2) — and the file is explicit
# that the rule of thumb must be LOAD-TESTED, which is OPERATIONS gate 53.
#
# **EVERY FIGURE HERE IS REPORTED.** `docs/evidence/cartesia-tts-verification-2026-09-06.md`
# is a Comet research run relayed by the founder and its own header stamps the whole file
# REPORTED; `cartesia.ai` and `docs.cartesia.ai` are egress-blocked from this container
# (re-measured 6 Sep 2026), so nothing below was read from the vendor by this repository and
# the labels the file itself writes as VERIFIED are Comet's reading, not ours.
#
# The conversion is the one that file states at every line (₹88 = US$1.00), kept as its own
# constant rather than `LIST_PRICE_USD_INR` (₹95.66, the LLM card's strike) so the number in
# code is the number in the evidence it cites. The choice is not free and is bounded rather
# than waved at: at ₹95.66 the fee would be ₹4,687.34, the plan leg ₹2.0249/min and the
# floor ₹4.5260 — still under the ₹6.00 cheapest Cartesia rate, so the card clears either
# conversion. `tests/cost_floor_test.py` computes that alternative and asserts it, so the
# claim is scored rather than believed.
#
# HARD RULE 7: none of this reaches `unit_cost_paid`. What a Cartesia minute actually
# costs this account is Phase D's operator-attested `TtsPriceAttestation`; these constants
# price the DECISION (the card's Cartesia column) and the margin model only.

#: Cartesia Startup plan, monthly fee, USD. REPORTED (evidence file §A1, "Startup | $49/mo").
CARTESIA_STARTUP_PLAN_FEE_USD: Final[Decimal] = Decimal("49")
#: The USD→INR conversion the Cartesia evidence file uses throughout ("₹88 = US$1.00") —
#: which is `COST_MODEL_USD_INR`, the same rate the engine fee leg above is struck at, so
#: the two legs of one floor are not converted at two rates. Aliased rather than re-typed,
#: and kept as its own name because the EVIDENCE differs: this one is the research file's
#: stated assumption, that one is TRD §10.4's. If they ever have to diverge, this is the
#: line that moves.
CARTESIA_EVIDENCE_USD_INR: Final[Decimal] = COST_MODEL_USD_INR
#: ₹4,312 — the plan fee in rupees, DERIVED from the two above so the file's own
#: arithmetic ("$49 = Rs 4,312") is reproduced rather than restated.
CARTESIA_STARTUP_PLAN_FEE_INR: Final[Decimal] = (
    CARTESIA_STARTUP_PLAN_FEE_USD * CARTESIA_EVIDENCE_USD_INR
)
#: The Startup plan's monthly allotment, in characters. REPORTED (evidence file §A1,
#: "1,250,000 credits"; 1 credit = 1 character on every Sonic model, same file).
CARTESIA_STARTUP_PLAN_CHARS: Final[Decimal] = Decimal("1250000")

#: The plan's MARGINAL rate per 10,000 characters — fee / allotment, in the Sarvam rung's
#: unit so TRD §10.1 can state the two side by side and `check_docs_drift` §4b can diff
#: them on both rungs. ₹34.496, EXACT. True only when the whole allotment is consumed:
#: below that the real per-character cost is higher (the fee does not shrink), and above
#: it the OVERAGE RATE IS UNKNOWN — see `CARTESIA_COST_FLOOR_INR_PER_MIN`. This is the
#: figure plan §3.5 says an operator attests as the Cartesia TTS price
#: (₹3.4496 / 1,000 chars).
CARTESIA_TTS_INR_PER_10K_CHARS: Final[Decimal] = (
    CARTESIA_STARTUP_PLAN_FEE_INR / CARTESIA_STARTUP_PLAN_CHARS * _CHARS_UNIT
)


def cartesia_plan_breakeven_call_minutes() -> Decimal:
    """The platform-wide monthly Cartesia call-minute count at which the Startup allotment
    is EXACTLY consumed, at the worst-case speaking rate: `allotment / 540` ≈ 2,314.8.

    This is the "break-even count" the Cartesia floor is struck at (plan §4.A.3): at this
    count the plan fee per minute is at its lowest honest value, because every character
    bought was spoken. Fewer Cartesia minutes in a month than this and the fee per minute
    is HIGHER — the floor then UNDERSTATES our cost, in the direction a floor must never
    err silently, which is why Phase D's margin panel shows plan spend beside attributed
    cost. More minutes and the overage rate (UNKNOWN) applies. Exact, unquantized: it is
    a count for a comparison, not money.
    """
    return CARTESIA_STARTUP_PLAN_CHARS / TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]


def cartesia_plan_inr_per_call_minute() -> Decimal:
    """The plan fee per call-minute at the break-even count, at `MONEY_Q`: ₹1.8628.

    `fee / breakeven_minutes` — which is also `CARTESIA_TTS_INR_PER_10K_CHARS / 10,000 x
    540`, the marginal rate at the worst-case speaking band, and the two are the same
    formula rearranged. Computed from the fee and the count so a reader can check it
    against the evidence file's own table (1,000 min on Startup = ₹4.31/call-min ALL-IN
    for the plan fee, which at 2,315 min spreads to ₹1.86).
    """
    return (CARTESIA_STARTUP_PLAN_FEE_INR / cartesia_plan_breakeven_call_minutes()).quantize(
        MONEY_Q, rounding=ROUNDING
    )


#: THE CARTESIA-VOICE COST FLOOR: the shared legs (fee + STT + LLM = ₹2.5011) plus the plan
#: fee per minute at the break-even count (₹1.8628) = ₹4.3639/min. Every pack's
#: `cartesia_inr_per_min` is judged against this. EVIDENCE CLASS: REPORTED — the fee leg is
#: VERIFIED-VENDOR-DOCS, but the plan fee and allotment come from the Cartesia evidence file,
#: which is a relayed research run, and a sum is only as good as its weakest input. Reaches
#: no bill.
#:
#: ⚠ **THE TRUE WORST CASE IS DEARER THAN THIS, AND BY AN UNKNOWN AMOUNT.** A floor is
#: supposed to be the worst case, and this one is not: it is struck at the plan's BEST
#: per-minute price, the instant the allotment is exactly consumed. Past that point
#: Cartesia bills an OVERAGE per credit whose rate is **UNKNOWN — not published on the
#: docs page** (`docs/evidence/cartesia-tts-verification-2026-09-06.md` §A1 "Overage/
#: running out of credits", and the summary at its head; plan ADDENDUM 1, unknown #3,
#: which closes at `cartesia.ai/pricing`'s FAQ or by mailing support@cartesia.ai). Below
#: the break-even count the fee per minute is HIGHER too, because the fee does not shrink.
#: So this constant understates our cost at both ends of the volume range, and it is used
#: anyway because it is the only figure the evidence supports — the ₹6.00 cheapest
#: Cartesia rate clears it by 27%, which is the headroom that UNKNOWN is being carried on.
#: Phase D's margin panel (plan spend beside attributed cost) is what makes the gap
#: visible on a real month; do not narrow that headroom until the overage rate is a fact.
CARTESIA_COST_FLOOR_INR_PER_MIN: Final[Decimal] = (
    _ex_tts_cost_inr_per_min() + cartesia_plan_inr_per_call_minute()
).quantize(MONEY_Q, rounding=ROUNDING)

#: A voice tier — the property of an AGENT that decides which of a lot's two rates prices
#: its minutes (plan §2.1). Spelled here, in the lowest money module, because the two cost
#: floors are keyed by it and `credit_packs.py` / `list_rates.py` key their rates by it;
#: `agents/voices.py`'s `Voice.provider` must carry the same two members (plan §3.3 —
#: derived, never stored twice).
VoiceTier = Literal["sarvam", "cartesia"]

#: Every voice tier, in card order (Sarvam is the cheaper column). Iterated by the pack
#: guard, the card writer and the ops preview, so a third tier is added once, here.
VOICE_TIERS: Final[tuple[VoiceTier, ...]] = ("sarvam", "cartesia")


def cost_floor_inr_per_min(voice: VoiceTier) -> Decimal:
    """THE ONE DOOR to a per-minute cost floor, by the voice's name.

    Two floors, two constants, one selector — so a caller judging a rate names the voice
    it is a rate for and cannot compare a Cartesia rate against the Sarvam floor (which
    is lower, so the mistake would always pass). Total over the Literal; an unknown tier
    is a programming error and raises rather than defaulting to the cheaper floor.
    """
    if voice == "sarvam":
        return SELF_SERVE_COST_FLOOR_INR_PER_MIN
    if voice == "cartesia":
        return CARTESIA_COST_FLOOR_INR_PER_MIN
    raise ValueError(f"no cost floor for voice tier {voice!r}")


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
# founder-approved constants beside it, exactly as `credit_packs.pack_rate_margin` sits
# beside them for the prepaid motion, and keeps the admin write path (`admin/routes.py`) a thin
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

    `cost` is CARRIED rather than left to the caller because there are two floors now
    (D-547) and a verdict that does not say which one it was struck against is a verdict a
    reader has to guess at — the ops console's card preview renders twelve of these side by
    side, six against ₹4.1211 and six against ₹4.3639.
    """

    rate: Decimal
    cost: Decimal
    margin: Decimal | None
    below_cost: bool
    below_target: bool


def rate_margin(rate: Decimal, *, cost: Decimal, target: Decimal = MIN_GROSS_MARGIN) -> RateMargin:
    """Judge one rate. `below_cost` strictly (`rate < cost`); `below_target` only when the
    rate clears cost yet the margin falls under the target.

    Public since D-547: the credit-pack guard (`credit_packs.pack_rate_margin`) and the
    ops console's card preview judge twelve rates with it, and the committed-bundle guard
    below judges two — one verdict shape, one posture (refuse below cost, warn below
    target), so a screen and a test can never disagree about what "thin" means."""
    below_cost = rate < cost
    margin = gross_margin_ratio(rate=rate, cost=cost) if rate > 0 else None
    below_target = margin is not None and not below_cost and margin < target
    return RateMargin(
        rate=rate, cost=cost, margin=margin, below_cost=below_cost, below_target=below_target
    )


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
    exact case without reaching into module state, mirroring `credit_packs.pack_rate_margin`.
    Decimal throughout (hard rule 7): the division uses `Decimal(included_min)`, never a
    float, and the effective rate is left EXACT for the margin ratio — callers that display
    it quantize once at the boundary.
    """
    if monthly_fee is not None and included_min is not None and included_min > 0:
        effective = monthly_fee / Decimal(included_min)
    else:
        effective = None
    committed = None if effective is None else rate_margin(effective, cost=cost, target=target)
    overage = None if overage_rate is None else rate_margin(overage_rate, cost=cost, target=target)
    return CommittedPlanMargin(
        effective_committed_rate=effective, committed=committed, overage=overage
    )


#: The plan tiers whose every minute is charged at a published list price, with no
#: included allowance in front of it. Spelled once because three places branch on it —
#: the meter's `charge_for_call`, the runway framing and `billing.service
#: .calling_revenue_inr` — and a fourth tier added to one of them and not the others is a
#: wallet that stops draining.
#:
#: ⚠ **`prepaid` JOINED IT WITH D-521, WHICH IS ALSO WHEN THIS SET STOPPED BEING THE
#: EXCEPTION.** It is now what a new account gets (`tenancy/models.DEFAULT_PLAN_TIER`)
#: and what every existing account was migrated to (`a8d3f61c04e7`); `managed` is the
#: deliberate exception an operator sets for a client invoiced on a retainer. Nothing
#: reading this tuple had to change for that — every one of them asks "does this account
#: pay from a wallet", which is exactly what membership here means, and the answer simply
#: became yes for most tenants.
#:
#: **IT IS NO LONGER THE SAME SET AS `compliance/service.SELF_SERVE_TIERS`**, which used
#: to be an alias of this name. That one answers a different question — "did a stranger
#: sign this account up unattended?" — and keeps its two members, because `prepaid` is a
#: tier an OPERATOR creates for a client they have met. Aliasing them again would put the
#: subscriber-KYC dial gate (D-47) and the first-campaign hold (D-51) in front of every
#: client on the platform, which is not what either control is for.
PREPAID_TIERS: Final = ("prepaid", "self_serve", "trial")


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
    "CARTESIA_COST_FLOOR_INR_PER_MIN",
    "CARTESIA_EVIDENCE_USD_INR",
    "CARTESIA_STARTUP_PLAN_CHARS",
    "CARTESIA_STARTUP_PLAN_FEE_INR",
    "CARTESIA_STARTUP_PLAN_FEE_USD",
    "CARTESIA_TTS_INR_PER_10K_CHARS",
    "CLIENT_CHOSEN_LLM_SOURCES",
    "COST_FLOOR_REFERENCE_CALL_MINUTES",
    "COST_MODEL_USD_INR",
    "ENGINE_PLATFORM_FEE_INR_PER_MIN",
    "ENGINE_PLATFORM_FEE_USD_PER_MIN",
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
    "TTS_ASSUMED_CHARS_PER_CALL_MINUTE",
    "TTS_INR_PER_10K_CHARS",
    "VOICE_TIERS",
    "CommittedPlanMargin",
    "LlmPriceAttestation",
    "LlmPriceAttestationReader",
    "RateMargin",
    "VoiceTier",
    "attested_llm_prices",
    "cartesia_plan_breakeven_call_minutes",
    "cartesia_plan_inr_per_call_minute",
    "committed_plan_margin",
    "cost_floor_inr_per_min",
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
    "rate_margin",
    "sarvam_llm_reference_inr_per_ktok",
    "stt_cost_inr",
    "stt_rate_inr_per_minute",
    "stt_rate_inr_per_second",
    "surchargeable_models_are_dearer",
    "tts_cost_inr",
    "tts_inr_per_call_minute",
    "tts_rate_inr_per_char",
]

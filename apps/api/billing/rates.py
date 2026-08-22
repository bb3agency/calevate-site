"""The TTS tier rate card, and the rule that decides which rung a call is billed on.

SURFACES §2b names the pattern we hold ourselves to: "if a premium voice is unavailable
the call runs on the cheaper voice and is **billed at the cheaper rate**, never silently
upgraded." D-36 makes the ladder real — Bulbul v3 default at ₹30/10,000 chars, v2 as the
value tier at ₹15 (D-35 corrected D-20's "v2 is discontinued"; TRD §10.1 carries both
rates). This module is the money half of that ladder; `apps/api/agents/voices.py` is the
catalog half, and it is the single source of which voice sits on which rung.

WHAT WE CAN AND CANNOT KNOW — read this before trusting a tier
--------------------------------------------------------------
**The engine does not report which voice actually synthesized a call.**
`ExecutionSnapshot` (packages/shared/src/calevate_shared/engine.py) carries no TTS model
and no character count; `CostBreakdown` carries a synthesizer LEG COST in rupees and
nothing else, and the Bolna adapter parses no model field out of the execution payload.
A leg cost alone cannot identify a rung either — the two rates differ 2:1 but the
character count that would divide them out is exactly what is missing.

**AND THE VENDOR DOES PUBLISH BOTH — WITH ONE CAVEAT THAT DECIDES HOW FAR TO TRUST IT
(D-358).** This paragraph used to end "because none is documented (TRD §5: Bolna publishes
no OpenAPI spec)", which was wrong twice over: they publish a spec, and it defines a
`usage_breakdown` block carrying `synthesizer_model` and `synthesizer_characters` — the
model that spoke and the characters it spoke — beside `transcriber_model`,
`transcriber_duration`, `llm_tokens` and a per-model token map.

THE CAVEAT, and it is why this is not filed as VERIFIED-OAS: in the pinned spec
`ExecutionUsageBreakdown` is an **orphan schema**. It is declared in `components.schemas`
and referenced by NOTHING — `AgentExecution` does not carry it, and no path response
does. What attaches it to the execution payload is the vendor's PROSE
(`references/execution-payload.md`, which lists `usage_breakdown` among the top-level
fields and shows a populated example). So:

* the FIELD NAMES and their types are VERIFIED-OAS;
* the claim that an execution actually CARRIES the block is VERIFIED-VENDOR-REPO — prose,
  which the vendor's own precedence rule ranks below the spec, and here the spec is not
  contradicting it but is silent.

An orphan schema is exactly the shape of a field the server dropped and the spec never
cleaned up, so this one needs the live capture more than most, not less.

Either way the hole below is OURS before it is the vendor's: `ExecutionSnapshot` has no
field to carry these and the adapter reads none. Turning the tier from an assumption about
intent into a MEASUREMENT is a change to the normalized model, the adapter and this module
together — D-358 — gated on one captured payload showing the block populated on a live
account (OPERATIONS §2 gate 7), because a spec is what the vendor says the server does.

So the tier on a usage row is **the voice the agent was CONFIGURED with when the call was
metered**. That is an assumption about intent, not a measurement of what spoke, and every
row says which it is in `tts_tier_source`. If the engine silently fell back to a cheaper
voice — the precise scenario SURFACES §2b describes — we would not see it, and the client
would be billed premium for a call that did not get it. Closing that hole is a VENDOR
QUESTION, not a code change: *does the execution payload expose the synthesizer model (and
ideally the character count) that actually served the call?* Until it is answered,
`ENGINE_REPORTS_TTS_MODEL` stays False and the honesty rule below carries the weight.

THE HONESTY RULE
----------------
`billable_tier` returns **value** for anything it cannot prove is premium — no voice
configured, a voice outside the catalog, a string that differs in case. Billing the
premium rate requires evidence; the absence of evidence is not evidence of premium. The
asymmetry is deliberate and it always favours the client, which is the only direction an
unproven charge is allowed to be wrong in.

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

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final, Literal

from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
)

from apps.api.agents.voices import VoiceTier, get_voice
from apps.api.billing.models import MONEY

# Same two rungs as the voice catalog, by import rather than by restatement: a third
# tier added to D-36's ladder must not be able to appear in one file and not the other.
TtsTier = VoiceTier

# How we came to believe the tier. `agent_config` = the voice on the agent row when the
# call was metered (an assumption); `unproven` = nothing to go on, billed as value.
# There is deliberately no `engine_reported` member: nothing reports it (see the module
# docstring), and a value the code cannot produce would be a lie waiting to be told.
TierSource = Literal["agent_config", "unproven"]

# The vendor question, as a constant so it is greppable and testable rather than a note
# in a doc. Flip it only when an engine payload actually names the synthesizer model —
# `tests/tts_tier_metering_test.py` fails the moment such a field appears.
ENGINE_REPORTS_TTS_MODEL = False

# Sarvam's published rate card, read live on 11 Aug 2026 (D-35, TRD §10.1). Per 10,000
# characters, INR. NUMERIC, never floats.
#
# THIS IS THE HOME OF THE RATE, and TRD §10.1 is the doc that states it.
# `scripts/check_docs_drift.py` §4b diffs the two in both directions and also checks
# §10.1's two spellings of each rate (₹/10,000 in the Sarvam card, ₹/1,000 in the
# per-call-minute table) against each other. Before that check existed, a vendor price
# move could land in the doc and not here — the shape D-102/D-103/D-105 each paid for,
# on the axis where it moves money.
TTS_INR_PER_10K_CHARS: Mapping[TtsTier, Decimal] = MappingProxyType(
    {
        "premium": Decimal("30.0000"),  # Bulbul v3 — D-36's default
        "value": Decimal("15.0000"),  # Bulbul v2 — live at half the v3 rate (D-35)
    }
)

# THE OPEN VENDOR QUESTION ON THIS CARD, recorded here rather than left to be rediscovered
# — **REPORTED, NOT READ** (`billing/payments.py`'s three-rung ladder; `sarvam.ai` and
# `docs.sarvam.ai` are refused by this environment's egress proxy and no request has ever
# been made to them from this repository).
#
# Aug 2026 search summaries report that Sarvam has shipped **Bulbul v4** and describe it
# as the current TTS model, **at the same ₹30 / 10,000 chars**. So the MONEY above is
# unaffected and nothing here is wrong today. What is exposed is the IDENTIFIER: D-36
# names v3 as the premium rung and `apps/api/agents/voices.py` is the catalog that pins
# which voice sits on it. D-105 is the precedent for why that matters more than it looks
# — Sarvam retired an LLM identifier under us and requests naming it began to FAIL, with
# the symptom appearing at post-call time as "extraction is empty".
#
# Closing it needs two things NEITHER of which is a code change from here: a first-party
# read of the pricing and model pages (a vendor account, or an egress route to
# `docs.sarvam.ai`), and D-36's own decision about whether the canonical stack moves to
# v4. Until both exist this stays a marked assumption, not a silent premise.
ENGINE_TTS_MODEL_GENERATION_VERIFIED = False

# The rung an unproven call is billed on. Named rather than inlined because three
# call sites depend on it being the CHEAP one and that is the whole pattern.
UNPROVEN_TIER: TtsTier = "value"

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

#: Every model this deployment may run, priced in rupees per THOUSAND tokens, derived
#: from the one place the vendor's own dollar figure is written down
#: (`LLM_MODELS[model].price`) and the one exchange rate above.
#:
#: KEYED BY MODEL, and PRIVATE. The public way in is `llm_inr_per_ktok(model)`, which
#: refuses an unpriced identifier with a message naming the ones it knows. A bare mapping
#: exported under the old name (`LLM_INR_PER_KTOK`, a flat `{"in", "out"}` pair) would let
#: `LLM_INR_PER_KTOK["in"]` keep parsing after the shape changed and fail at RUNTIME with
#: a `KeyError` on a metering path; the rename is what turns every stale reader into an
#: ImportError at collection time instead.
#:
#: FOUR DECIMALS because `unit_cost_paid` is NUMERIC(12,4) — a price this ledger cannot
#: store is a price it cannot honour — and `ROUNDING` rather than the ambient decimal
#: context for the reason stated at that constant.
_LLM_INR_PER_KTOK: Final[Mapping[str, Mapping[str, Decimal]]] = MappingProxyType(
    {
        model: MappingProxyType(
            {
                leg: (usd * LIST_PRICE_USD_INR / Decimal("1000")).quantize(
                    MONEY_Q, rounding=ROUNDING
                )
                for leg, usd in (
                    ("in", LLM_MODELS[model].price.input_usd_per_mtok),
                    ("out", LLM_MODELS[model].price.output_usd_per_mtok),
                )
            }
        )
        # SELECTABLE, not every model the catalogue knows, and the distinction is a money
        # rule rather than a filter. D-456 admitted OpenAI and Google models whose list
        # prices are REPORTED and not verified — both vendors' pricing pages are
        # egress-blocked from this environment — and `LlmModelSpec` refuses to be
        # `selectable` on an unverified price for exactly that reason. Deriving the rate
        # card from the catalogue instead would put a number nobody read from the vendor
        # one step away from `unit_cost_paid`, which is hard rule 7's whole subject.
        #
        # It also keeps `PRICED_LLM_MODELS == AZURE_OPENAI_MODELS` true today, so every
        # assertion written against that identity still holds; the day a price is verified
        # and a model becomes selectable, the rate card grows with it and nothing here
        # changes.
        for model in SELECTABLE_LLM_MODELS
    }
)

#: The models this repository can put a rupee figure on, as a value.
#:
#: It must equal `AZURE_OPENAI_MODELS` and a test says so, in both directions. A model an
#: operator can select but nobody priced is a `ValueError` on the first assist after they
#: flip the switch; a price for a model nobody can select is a number that will rot
#: unnoticed. Derived from the table rather than retyped, so the two cannot drift by an
#: edit to one of them.
PRICED_LLM_MODELS: Final[frozenset[str]] = frozenset(_LLM_INR_PER_KTOK)


def llm_inr_per_ktok(model: str) -> Mapping[str, Decimal]:
    """`{"in": ₹, "out": ₹}` per 1,000 tokens for `model`. NO DEFAULT, deliberately.

    THE ARGUMENT IS THE POINT (D-410). Which model a deployment runs is a live console
    value, so the only correct price is the one for the model the caller actually used —
    and the caller is the only one who knows it. Every reachable call site therefore
    names it: the assist meter passes the model the request ran on, and the in-call cost
    model is asked about one model at a time.

    Refuses an unpriced identifier rather than falling back, because both fallbacks are
    worse than the error: the default's price silently under-bills the dearer model, and
    a zero makes a leg look free. A `ValueError` here is unreachable through
    `Settings.azure_openai_model` (a closed `Literal`, refused at the config boundary) —
    it is for the other way in, a model identifier read back off a historical
    `usage_events` row whose price we no longer publish.
    """
    try:
        return _LLM_INR_PER_KTOK[model]
    except KeyError:
        raise ValueError(
            f"{model!r} has no published price; this repository prices {sorted(PRICED_LLM_MODELS)}"
        ) from None


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

    Rounded ONCE, at the end. Quantizing per turn would round 6·N times and drift.
    """
    if minutes < 1:
        raise ValueError("a reference call is at least one minute")
    price = llm_inr_per_ktok(model)
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


def tts_rate_inr_per_char(tier: TtsTier) -> Decimal:
    """Exact, unquantized: ₹30/10,000 is ₹0.003 and dividing is where precision is lost
    if it is done twice. Callers multiply by a character count and quantize once."""
    return TTS_INR_PER_10K_CHARS[tier] / _CHARS_UNIT


def tts_cost_inr(tier: TtsTier, chars: int) -> Decimal:
    """What `chars` characters of speech cost us on this rung.

    A CHARACTER COUNT IS REQUIRED — there is no default and no estimate. TRD §10.1's
    "360-540 chars per call-minute" is explicitly an unmeasured assumption (pilot gate
    12), so imputing a count here would put a made-up number on a ledger row and let it
    be read back later as a fact. Callers that do not have a count do not get a price.
    """
    if chars < 0:
        raise ValueError("character count cannot be negative")
    return (tts_rate_inr_per_char(tier) * Decimal(chars)).quantize(MONEY_Q, rounding=ROUNDING)


def tier_of_voice(voice_id: str | None) -> TtsTier | None:
    """The catalog's tier for this voice id, or None if we do not recognise it.

    Exact match, no normalisation — `get_voice` is deliberately strict for the same
    reason: `agents.tts_voice` is pasted into the vendor request verbatim, so a string
    we had to "fix" to recognise is not the string the call ran on.
    """
    if not voice_id:
        return None
    voice = get_voice(voice_id)
    return voice.tier if voice else None


def billable_tier(voice_id: str | None) -> tuple[TtsTier, TierSource]:
    """(tier, provenance) for a call whose agent was configured with `voice_id`.

    THE honesty rule (SURFACES §2b): anything unrecognised bills as the VALUE tier and
    says `unproven`, so a call we cannot attribute is never charged the premium rate.
    """
    tier = tier_of_voice(voice_id)
    if tier is None:
        return UNPROVEN_TIER, "unproven"
    return tier, "agent_config"


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
    (₹6.00). The balance drained at a third of the advertised rate and Calevate booked
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
    """Is this model an upgrade on the one the plan's rate is struck at?

    Total and never raising, including on an identifier this repository no longer prices —
    a model read back off a historical `usage_events` row is exactly the input
    `llm_inr_per_ktok` refuses, and a month that cannot be re-priced is not an acceptable
    answer for a statement. Membership of the rate card is therefore NOT consulted: the
    question is which side of the base model this identifier is on, and only the base model
    is on the free side.

    `surchargeable_models_are_dearer()` below is what keeps that crude test honest — every
    other selectable model is verified to actually cost us MORE, so "not the base model"
    and "an upgrade" are the same set. The day a CHEAPER model is added they stop being the
    same set, and that predicate's test fails rather than a client being surcharged for
    saving us money.
    """
    return bool(model) and model != BASE_RATE_LLM_MODEL


def llm_surcharge_applies(*, model: str | None, source: str | None) -> bool:
    """Does the plan's model surcharge apply to a minute metered with this stamp?

    Both halves of the ledger stamp are read, and each refuses on its own:

    * an unrecognised, absent or base-rate `model` is not an upgrade (see above). A row
      written before D-454 stamped the model carries neither key and bills as base, which
      is the same asymmetry `billable_tier` applies to the TTS rung — the absence of
      evidence is never evidence of the dearer thing;
    * a `source` outside `CLIENT_CHOSEN_LLM_SOURCES` means the client did not choose it.

    **PRICED FROM THE STAMP, NEVER FROM `agents.llm_model`.** Both columns behind that
    stamp are editable from two screens in two realms, so reading them at invoice time
    would re-price every closed month the moment a client switched. The stamp is what
    `apps/workers/pipeline.py::_meter` writes for this exact reason.
    """
    return is_surchargeable_llm_model(model) and source in CLIENT_CHOSEN_LLM_SOURCES


def surchargeable_models_are_dearer() -> bool:
    """Is every model this surcharge would apply to actually dearer than the base?

    A PREDICATE rather than an assert at import, for the reason
    `agents/llm_models.every_selectable_model_is_priced` is one: a reader wants the
    invariant stated in words and `tests/llm_model_surcharge_test.py` wants a named
    failure. Compared on BOTH token legs, because a model cheaper on one and dearer on the
    other is not a straightforward upgrade and is a founder's decision rather than a
    predicate's.
    """
    base = _LLM_INR_PER_KTOK[BASE_RATE_LLM_MODEL]
    return all(
        price["in"] > base["in"] and price["out"] > base["out"]
        for model, price in _LLM_INR_PER_KTOK.items()
        if model != BASE_RATE_LLM_MODEL
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


def tier_correction_inr(*, chars: int, billed_tier: TtsTier, actual_tier: TtsTier) -> Decimal:
    """What must be ADDED to the ledger so the TTS leg reads at the tier that ran.

    Negative when a call was billed premium and ran on value — the usual direction, and
    the one SURFACES §2b cares about. Zero when the tiers agree, which the caller reads
    as "there is nothing to compensate for" rather than writing a ₹0 row.
    """
    return tts_cost_inr(actual_tier, chars) - tts_cost_inr(billed_tier, chars)


__all__ = [
    "BASE_RATE_LLM_MODEL",
    "CLIENT_CHOSEN_LLM_SOURCES",
    "ENGINE_REPORTS_TTS_MODEL",
    "ENGINE_TTS_MODEL_GENERATION_VERIFIED",
    "LIST_PRICE_USD_INR",
    "MONEY_Q",
    "PREPAID_TIERS",
    "PRICED_LLM_MODELS",
    "REFERENCE_CALL",
    "ROUNDING",
    "TTS_INR_PER_10K_CHARS",
    "UNPROVEN_TIER",
    "TierSource",
    "TtsTier",
    "billable_tier",
    "is_surchargeable_llm_model",
    "llm_cost_inr_per_minute",
    "llm_inr_per_ktok",
    "llm_surcharge_applies",
    "llm_surcharge_billed_inr",
    "prepaid_billed_inr",
    "surchargeable_models_are_dearer",
    "tier_correction_inr",
    "tier_of_voice",
    "tts_cost_inr",
    "tts_rate_inr_per_char",
]

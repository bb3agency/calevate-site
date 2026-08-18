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


def tier_correction_inr(*, chars: int, billed_tier: TtsTier, actual_tier: TtsTier) -> Decimal:
    """What must be ADDED to the ledger so the TTS leg reads at the tier that ran.

    Negative when a call was billed premium and ran on value — the usual direction, and
    the one SURFACES §2b cares about. Zero when the tiers agree, which the caller reads
    as "there is nothing to compensate for" rather than writing a ₹0 row.
    """
    return tts_cost_inr(actual_tier, chars) - tts_cost_inr(billed_tier, chars)


__all__ = [
    "ENGINE_REPORTS_TTS_MODEL",
    "ENGINE_TTS_MODEL_GENERATION_VERIFIED",
    "MONEY_Q",
    "PREPAID_TIERS",
    "ROUNDING",
    "TTS_INR_PER_10K_CHARS",
    "UNPROVEN_TIER",
    "TierSource",
    "TtsTier",
    "billable_tier",
    "prepaid_billed_inr",
    "tier_correction_inr",
    "tier_of_voice",
    "tts_cost_inr",
    "tts_rate_inr_per_char",
]

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
nothing else, and the Bolna adapter parses no model field out of the execution payload
because none is documented (TRD §5: Bolna publishes no OpenAPI spec). A leg cost alone
cannot identify a rung either — the two rates differ 2:1 but the character count that
would divide them out is exactly what is missing.

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
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Literal

from apps.api.agents.voices import VoiceTier, get_voice

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
TTS_INR_PER_10K_CHARS: Mapping[TtsTier, Decimal] = MappingProxyType(
    {
        "premium": Decimal("30.0000"),  # Bulbul v3 — D-36's default
        "value": Decimal("15.0000"),  # Bulbul v2 — live at half the v3 rate (D-35)
    }
)

# The rung an unproven call is billed on. Named rather than inlined because three
# call sites depend on it being the CHEAP one and that is the whole pattern.
UNPROVEN_TIER: TtsTier = "value"

_CHARS_UNIT = Decimal("10000")
# NUMERIC(12,4) is `unit_cost_paid`'s storage precision (billing/models.py MONEY), so a
# cost is quantized there and nowhere finer. ROUND_HALF_UP for the same reason
# `billing.service.ROUNDING` is: it is the convention an Indian invoice is checked
# against, and it is passed explicitly so no library's global context can change it.
MONEY_Q = Decimal("0.0001")
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


def tier_correction_inr(*, chars: int, billed_tier: TtsTier, actual_tier: TtsTier) -> Decimal:
    """What must be ADDED to the ledger so the TTS leg reads at the tier that ran.

    Negative when a call was billed premium and ran on value — the usual direction, and
    the one SURFACES §2b cares about. Zero when the tiers agree, which the caller reads
    as "there is nothing to compensate for" rather than writing a ₹0 row.
    """
    return tts_cost_inr(actual_tier, chars) - tts_cost_inr(billed_tier, chars)


__all__ = [
    "ENGINE_REPORTS_TTS_MODEL",
    "MONEY_Q",
    "ROUNDING",
    "TTS_INR_PER_10K_CHARS",
    "UNPROVEN_TIER",
    "TierSource",
    "TtsTier",
    "billable_tier",
    "tier_correction_inr",
    "tier_of_voice",
    "tts_cost_inr",
    "tts_rate_inr_per_char",
]

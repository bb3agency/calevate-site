"""Minutes of an engine that reports no cost, priced at an operator-attested rate (D-678).

ThinnestAI's call results carry no cost field (`thinnest-findings/mirror/pages/api-reference/
get-call.md:199-204`). What we pay is a per-minute fee billed in 30-second pulses
(`docs/evidence/thinnest-ai-evaluation.md` §2 — FOUNDER-RELAYED, not an invoice), so a
call's cost is

    billed minutes = ceil(seconds / 30) x 0.5
    cost           = billed minutes x the ₹/min attested for that call's rate key
                     x (1 + the wallet top-up fee), at `MONEY_Q`

THE FEE IS OURS TO ADD, NOT THE OPERATOR'S. The attested rate is the platform's posted price
per billed minute, which is what its price page and its per-call charge (`costMicro`) both
state, and neither includes the payment gateway's charge on every rupee loaded into the
wallet: 2.36% on every plan (`billing/rates.THINNEST_TOPUP_FEE`, VENDOR-STATED in
ThinnestAI's email of 12 Oct 2026). Every rupee a minute costs passed through that wallet
first, so the fee is part of the minute's cost on every rate key, `byok_voice` included.
Cartesia's synthesis on a Studio call is billed to our own key and never enters the wallet,
so its `tts_kchars` row carries no fee.
`topup_fee` is the one helper; the charge reconciler (`apps/workers/engine_charges.py`) uses
the same one, so what we meter and what we compare against cannot drift apart.

Hard rule 7's structural form, exactly as `ops/model_pricing.tts_price_is_billable` keeps
it for a voice: the ONLY figure that reaches `unit_cost_paid` is one an operator attested
(`platform_engine_minute_prices`). With none, a minute is UNPRICED — the meter records it
with a NULL cost and alarms — never priced at zero, and `engine_minute_is_billable` is the
door the offer and publish seams consult so a minute without a rate is not sold at all.

`rate_key`: `platform` is the engine's base minute (`THINNEST_INR_PER_MIN`, D-678 §7);
`standard` / `premium` / `studio` are ThinnestAI's voice tiers (`api-reference/
voices-and-models.md`), each priced separately if the agent speaks on it; `byok_voice` is a
minute spoken on our own voice key (BYOK scope `voice`, ₹1.50 a minute with their phone line,
`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:
19-24`), whose synthesis our voice provider bills us separately; `byok_llm_voice` is a minute
spoken on our voice key and answered on our model key (BYOK scope `llm_voice`, a flat ₹1.00 a
minute with their speech-to-text and phone line, `thinnest-findings/mirror/snapshots/
2026-10-13/pages/api-reference/bring-your-own-keys.md:18-20,26-29`), whose synthesis and model
tokens our providers bill us separately (D-764). A minute on our model key alone (scope `llm`)
is billed at the voice band's own rate (:21-24, :31-33), so it keeps that band's key. The key a
vendor agent runs on, and the model of our key it answers with, are stamped on its route row
(`engine_agent_routes.engine_rate_key`, `.engine_own_model`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal, get_args
from uuid import UUID

from calevate_shared.engine import CostBreakdown
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import rates
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

EngineRateKey = Literal["platform", "standard", "premium", "studio", "byok_voice", "byok_llm_voice"]
ENGINE_RATE_KEYS: Final[tuple[str, ...]] = get_args(EngineRateKey)
BASE_RATE_KEY: Final[EngineRateKey] = "platform"

#: The price of a call no agent ran on: one that ended before the agent spoke, or one a
#: number forward put through to a phone (D-813). It is the phone carrier's fee only, and a
#: price key, never a route's: no agent is published on it, so it is not an `EngineRateKey`.
#: ThinnestAI states ₹0.38 a minute (snapshots/2026-10-18/pages/api-reference/calls/
#: get-call.md:1236-1243, VENDOR-STATED 18 Oct 2026), which reaches money only once an
#: operator attests it here; until then such a minute is metered unpriced and alarmed.
CARRIER_RATE_KEY: Final = "carrier"
#: Every key a per-minute price may be attested for: the route keys and the carrier's fee.
PRICED_RATE_KEYS: Final[tuple[str, ...]] = (*ENGINE_RATE_KEYS, CARRIER_RATE_KEY)

#: Engines metered by attested minute, and their billing pulse in seconds. ThinnestAI's
#: 30-second pulse is FOUNDER-RELAYED (evaluation §2), the founder's call of 6 Oct 2026, and
#: documented since (get-call.md:1283-1292, "30-second steps ... at half of this each").
PULSE_SECONDS: Final[dict[str, int]] = {"thinnest": 30}
ATTESTED_MINUTE_ENGINES: Final = frozenset(PULSE_SECONDS)
#: The carrier's block a carrier-only call is charged in, in seconds: 30 on ThinnestAI
#: (get-call.md:1236-1243, "charged in 30-second blocks (₹0.19 each)"), so a 4-second call
#: bills 30 seconds (ThinnestAI email of 18 Oct 2026). A length, not a price.
CARRIER_BLOCK_SECONDS: Final[dict[str, int]] = {"thinnest": 30}

_SIXTY: Final = Decimal(60)

BYOK_VOICE_RATE_KEY: Final[EngineRateKey] = "byok_voice"
BYOK_LLM_VOICE_RATE_KEY: Final[EngineRateKey] = "byok_llm_voice"
#: The rate keys of a minute spoken on our own voice key: the Studio rung, with or without
#: our model (D-764).
OWN_VOICE_RATE_KEYS: Final[frozenset[str]] = frozenset({"byok_voice", "byok_llm_voice"})

#: Engines whose own voices are sold by band (D-687), keyed by the client rung map below.
BAND_SOLD_ENGINES: Final = frozenset({"thinnest"})

#: Engines paid from a prepaid wallet that charges a fee on each top-up.
WALLET_TOPUP_ENGINES: Final = frozenset({"thinnest"})

#: `usage_events.meta` key on a metered minute row: the top-up fee its cost includes. A row
#: without it was metered before the fee was added.
TOPUP_FEE_META_KEY: Final = "topup_fee"

#: Which plans each top-up fee applies to, for a sentence an operator reads. One fee on
#: every plan since ThinnestAI's email of 12 Oct 2026.
TOPUP_FEE_PLAN_LABELS: Final[Mapping[Decimal, str]] = MappingProxyType(
    {rates.THINNEST_TOPUP_FEE: "every plan"}
)


def thinnest_topup_fee() -> Decimal:
    """ThinnestAI's wallet top-up fee as a fraction: the payment gateway's charge, the same
    on every plan and every voice band (`billing/rates.THINNEST_TOPUP_FEE`)."""
    return rates.THINNEST_TOPUP_FEE


def topup_fee(engine: str) -> Decimal:
    """The fee on the rupees that pay for this engine's minutes, as a fraction; zero for an
    engine not paid from a topped-up wallet."""
    return thinnest_topup_fee() if engine in WALLET_TOPUP_ENGINES else Decimal(0)


def cost_with_fee(amount: Decimal, *, fee: Decimal) -> Decimal:
    """What `amount` paid from the wallet cost us once the top-up fee on it is added."""
    return (amount * (Decimal(1) + fee)).quantize(rates.MONEY_Q, rounding=rates.ROUNDING)


def client_rungs(engine: str) -> Mapping[str, rates.VoiceTier] | None:
    """Which of an engine's rate keys a client may be SOLD, and the client price rung each one
    bills on; None for an engine with no such rule (the agent's own voice decides).

    On ThinnestAI (D-688, founder, 8 Oct 2026) the Clear rung is the voice band
    `Settings.thinnest_clear_voice_band` names (Studio by default, D-792; Premium for an
    account without ThinnestAI Pro); the Studio rung is a voice of our own Cartesia key. No
    other band is sold. The rate key is the one publish stamped on the route row from the
    chosen voice (`engine_agent_routes.engine_rate_key`), so the rung and the cost come from
    one fact.
    """
    if engine not in BAND_SOLD_ENGINES:
        return None
    settings = get_settings()
    sold: dict[str, rates.VoiceTier] = {
        settings.thinnest_clear_voice_band: rates.VALUE_VOICE_TIER,
        BYOK_VOICE_RATE_KEY: rates.PREMIUM_VOICE_TIER,
    }
    # The Studio minute on our own model is sold only while that set-up is switched on
    # (D-764), so a deploy changes nothing a client is offered until the founder turns it on.
    if settings.thinnest_own_model:
        sold[BYOK_LLM_VOICE_RATE_KEY] = rates.PREMIUM_VOICE_TIER
    return MappingProxyType(sold)


def client_voice_tier(engine: str, rate_key: str) -> rates.VoiceTier | None:
    """The client price rung a minute on this engine and rate key bills on; None when the
    key is not sold (or the engine has no rule, so the agent's own voice decides).

    A minute that RAN on our own voice key bills on Studio whether or not that key is on sale
    today: a call placed on our model just before the switch went off is still a Studio call,
    and billing it at Clear would undercharge a minute we paid Cartesia for."""
    rungs = client_rungs(engine)
    if rungs is None:
        return None
    if rate_key in OWN_VOICE_RATE_KEYS:
        return rates.PREMIUM_VOICE_TIER
    return rungs.get(rate_key)


def billed_minutes(seconds: Decimal, *, pulse_s: int) -> Decimal:
    """Whole pulses, rounded UP, in minutes. A negative or zero duration bills nothing."""
    return rates.pulsed_seconds(seconds, pulse=Decimal(pulse_s)) / _SIXTY


@dataclass(frozen=True, slots=True)
class EngineMinutePrice:
    engine: str
    rate_key: str
    inr_per_min: Decimal
    effective_from: datetime
    attested_at: datetime
    attested_by: str
    source_note: str


def _require_engine(engine: str) -> None:
    if engine not in ATTESTED_MINUTE_ENGINES:
        raise ProblemError(
            kind="not_found",
            code="engine_minute_price_unknown_engine",
            title="This engine is not priced by the minute",
            detail=f"{engine!r} reports its own cost or is not an engine Calevate runs.",
        )


def _require_rate_key(rate_key: str, *, keys: tuple[str, ...] = PRICED_RATE_KEYS) -> None:
    if rate_key not in keys:
        raise ProblemError(
            kind="not_found",
            code="engine_minute_price_unknown_rate_key",
            title="No such rate",
            detail=f"{rate_key!r} is not one of {', '.join(keys)}.",
        )


async def attested_minute_prices(
    session: AsyncSession, *, engine: str, at: datetime
) -> dict[str, EngineMinutePrice]:
    """Every rate key's price effective at `at`. An unattested key is ABSENT."""
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware — a naive instant has no month")
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (rate_key) rate_key, inr_per_min, effective_from, "
                "attested_at, attested_by, source_note FROM platform_engine_minute_prices "
                "WHERE engine = :engine AND effective_from <= :at "
                "ORDER BY rate_key, effective_from DESC"
            ),
            {"engine": engine, "at": at},
        )
    ).all()
    return {
        str(row[0]): EngineMinutePrice(
            engine=engine,
            rate_key=str(row[0]),
            inr_per_min=Decimal(str(row[1])),
            effective_from=row[2],
            attested_at=row[3],
            attested_by=str(row[4]),
            source_note=str(row[5]),
        )
        for row in rows
    }


async def engine_minute_is_billable(
    session: AsyncSession, *, engine: str, rate_key: str, at: datetime
) -> bool:
    """May a minute on this engine and rate key be SOLD? THE one door (hard rule 7)."""
    _require_engine(engine)
    _require_rate_key(rate_key)
    return rate_key in await attested_minute_prices(session, engine=engine, at=at)


async def attested_rate_keys(session: AsyncSession, *, engine: str, at: datetime) -> frozenset[str]:
    """Every rate key a minute on `engine` may be sold at, asked through the one door."""
    return frozenset(
        [
            key
            for key in ENGINE_RATE_KEYS
            if await engine_minute_is_billable(session, engine=engine, rate_key=key, at=at)
        ]
    )


async def attest_engine_minute_price(
    session: AsyncSession,
    *,
    engine: str,
    rate_key: str,
    inr_per_min: Decimal,
    effective_from: datetime,
    source_note: str,
    actor_id: object,
) -> EngineMinutePrice:
    """Record one attested rate as a NEW effective-dated row. Never an UPDATE.

    The caller MUST be step-up confirmed and MUST write the audit row on this session —
    `ops/model_pricing.attest_tts_price`'s contract, because it is the same act.
    """
    _require_engine(engine)
    _require_rate_key(rate_key)
    if inr_per_min <= 0:
        raise ProblemError(
            kind="validation",
            code="engine_minute_price_not_positive",
            title="A price must be greater than zero",
            detail="The figure is rupees per billed minute and must be strictly positive.",
        )
    try:
        rates.assert_rate_is_meterable(
            inr_per_min, subject=f"the attested {engine} {rate_key} rate", unit="minute"
        )
    except ValueError as too_small:
        raise ProblemError(
            kind="validation",
            code="attested_price_not_meterable",
            title="This price is quoted in too small a unit to meter",
            detail=str(too_small),
        ) from too_small
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM platform_engine_minute_prices "
                "WHERE engine = :e AND rate_key = :k AND effective_from = :ef"
            ),
            {"e": engine, "k": rate_key, "ef": effective_from},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="engine_minute_price_duplicate_instant",
            title="A price already exists for this rate at this instant",
            detail="A correction is a NEW effective instant, never an edit of an existing one.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_engine_minute_prices "
                "(engine, rate_key, effective_from, inr_per_min, attested_by, source_note) "
                "VALUES (:e, :k, :ef, :rate, :by, :note) RETURNING attested_at"
            ),
            {
                "e": engine,
                "k": rate_key,
                "ef": effective_from,
                "rate": inr_per_min,
                "by": actor_id,
                "note": source_note,
            },
        )
    ).one()
    return EngineMinutePrice(
        engine=engine,
        rate_key=rate_key,
        inr_per_min=inr_per_min,
        effective_from=effective_from,
        attested_at=row[0],
        attested_by=str(actor_id),
        source_note=source_note,
    )


async def record_engine_rate_key(
    session: AsyncSession,
    *,
    engine: str,
    engine_agent_ref: str,
    rate_key: EngineRateKey,
    own_model: str | None = None,
) -> None:
    """Stamp which rate a vendor agent's minutes are metered at, and the model of our own
    key it answers with (None: the engine's own model). For the publish path, in the tenant
    session that wrote the route row."""
    _require_rate_key(rate_key, keys=ENGINE_RATE_KEYS)
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET engine_rate_key = :k, engine_own_model = :m, "
            "updated_at = now() WHERE engine = :e AND engine_agent_ref = :ref"
        ),
        {"k": rate_key, "m": own_model, "e": engine, "ref": engine_agent_ref},
    )


@dataclass(frozen=True, slots=True)
class MinuteCost:
    rate_key: str
    billed_minutes: Decimal
    #: The attested posted rate, before the top-up fee. None when the rate key is
    #: unattested: the minute is UNPRICED, not free.
    inr_per_min: Decimal | None
    #: The top-up fee `cost` includes, as a fraction.
    topup_fee: Decimal
    cost: CostBreakdown
    #: The rate key the CLIENT rung is read from: the agent's own, also on a carrier-only call.
    client_rate_key: str = ""
    #: The model of our own key the call answered with (D-764); None on the engine's own.
    own_model: str | None = None

    @property
    def priced(self) -> bool:
        return self.inr_per_min is not None


async def engine_minute_cost(
    session: AsyncSession,
    *,
    engine: str,
    tenant_id: UUID,
    call_id: UUID,
    seconds: Decimal,
    at: datetime,
    carrier_only: bool = False,
) -> MinuteCost:
    """This call's supplier cost at the rate attested for its vendor agent's rate key, or
    for the carrier's fee when no agent ran on it (`carrier_only`).

    The whole minute is ONE leg (`platform_inr`): ThinnestAI sells telephony, speech and
    model as one per-minute price (evaluation §2), so splitting it across our per-leg rows
    would invent a breakdown nobody quoted. The wallet's top-up fee is added on top of the
    attested rate (module docstring).
    """
    _require_engine(engine)
    # `currency_stated=True` on both returns below: the figure is an operator-attested
    # rupee rate, so no vendor amount is converted and no currency is assumed (gate 7).
    stamped = (
        await session.execute(
            text(
                "SELECT r.engine_rate_key, r.engine_own_model FROM calls c "
                "JOIN engine_agent_routes r "
                "ON r.agent_id = c.agent_id AND r.tenant_id = c.tenant_id AND r.engine = :e "
                "WHERE c.id = :cid AND c.tenant_id = :tid "
                "ORDER BY r.active DESC, r.updated_at DESC LIMIT 1"
            ),
            {"e": engine, "cid": call_id, "tid": tenant_id},
        )
    ).first()
    route_key = str(stamped[0]) if stamped is not None and stamped[0] else BASE_RATE_KEY
    own_model = str(stamped[1]) if stamped is not None and stamped[1] else None
    # A call no agent ran on is charged the carrier's fee only, by the carrier's block
    # (get-call.md:1236-1243; D-813). That replaces D-743's "standard voice rate" for a
    # forward, which channels/phone-numbers.md:567-570 still states: the call's own billing
    # schema, the 17 Oct changelog (whats-new/index.md:28-30) and ThinnestAI's email of
    # 18 Oct 2026 all say carrier fee, and `costMicro` decides it either way. The client's
    # rung stays the agent's.
    rate_key = CARRIER_RATE_KEY if carrier_only else route_key
    pulse = CARRIER_BLOCK_SECONDS[engine] if carrier_only else PULSE_SECONDS[engine]
    minutes = billed_minutes(seconds, pulse_s=pulse)
    price = (await attested_minute_prices(session, engine=engine, at=at)).get(rate_key)
    fee = topup_fee(engine)
    if price is None:
        return MinuteCost(
            rate_key=rate_key,
            client_rate_key=route_key,
            own_model=own_model,
            billed_minutes=minutes,
            inr_per_min=None,
            topup_fee=fee,
            cost=CostBreakdown(total_inr=Decimal(0), source_currency="INR", currency_stated=True),
        )
    total = cost_with_fee(minutes * price.inr_per_min, fee=fee)
    return MinuteCost(
        rate_key=rate_key,
        client_rate_key=route_key,
        own_model=own_model,
        billed_minutes=minutes,
        inr_per_min=price.inr_per_min,
        topup_fee=fee,
        cost=CostBreakdown(
            total_inr=total, platform_inr=total, source_currency="INR", currency_stated=True
        ),
    )


__all__ = [
    "ATTESTED_MINUTE_ENGINES",
    "BAND_SOLD_ENGINES",
    "BASE_RATE_KEY",
    "BYOK_LLM_VOICE_RATE_KEY",
    "BYOK_VOICE_RATE_KEY",
    "CARRIER_BLOCK_SECONDS",
    "CARRIER_RATE_KEY",
    "ENGINE_RATE_KEYS",
    "OWN_VOICE_RATE_KEYS",
    "PRICED_RATE_KEYS",
    "PULSE_SECONDS",
    "TOPUP_FEE_META_KEY",
    "TOPUP_FEE_PLAN_LABELS",
    "WALLET_TOPUP_ENGINES",
    "EngineMinutePrice",
    "EngineRateKey",
    "MinuteCost",
    "attest_engine_minute_price",
    "attested_minute_prices",
    "attested_rate_keys",
    "billed_minutes",
    "client_rungs",
    "client_voice_tier",
    "cost_with_fee",
    "engine_minute_cost",
    "engine_minute_is_billable",
    "record_engine_rate_key",
    "thinnest_topup_fee",
    "topup_fee",
]

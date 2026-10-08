"""Minutes of an engine that reports no cost, priced at an operator-attested rate (D-678).

ThinnestAI's call results carry no cost field (`thinnest-findings/mirror/pages/api-reference/
get-call.md:199-204`). What we pay is a per-minute fee billed in 30-second pulses
(`docs/evidence/thinnest-ai-evaluation.md` §2 — FOUNDER-RELAYED, not an invoice), so a
call's cost is

    billed minutes = ceil(seconds / 30) x 0.5
    cost           = billed minutes x the ₹/min attested for that call's rate key

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
19-24`), whose synthesis our voice provider bills us separately. The key a vendor agent runs on
is stamped on its route row (`engine_agent_routes.engine_rate_key`).
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

EngineRateKey = Literal["platform", "standard", "premium", "studio", "byok_voice"]
ENGINE_RATE_KEYS: Final[tuple[str, ...]] = get_args(EngineRateKey)
BASE_RATE_KEY: Final[EngineRateKey] = "platform"

#: Engines metered by attested minute, and their billing pulse in seconds. ThinnestAI's
#: 30-second pulse is FOUNDER-RELAYED (evaluation §2), the founder's call of 6 Oct 2026.
PULSE_SECONDS: Final[dict[str, int]] = {"thinnest": 30}
ATTESTED_MINUTE_ENGINES: Final = frozenset(PULSE_SECONDS)

_SIXTY: Final = Decimal(60)

#: Which of an engine's rate keys a client may be SOLD, and the client price rung each one
#: bills on (D-687, founder, 8 Oct 2026, superseding D-681's Premium band). On ThinnestAI the
#: Clear rung is their Studio voice band, catalogue voices and our clones alike; the Studio
#: rung is a voice of our own Cartesia key. Standard and Premium are not sold. The rate key is
#: the one publish stamped on the route row from the chosen voice
#: (`engine_agent_routes.engine_rate_key`), so the rung and the cost come from one fact.
BYOK_VOICE_RATE_KEY: Final[EngineRateKey] = "byok_voice"
CLIENT_RUNG_OF_RATE_KEY: Final[Mapping[str, Mapping[str, rates.VoiceTier]]] = MappingProxyType(
    {
        "thinnest": MappingProxyType(
            {"studio": rates.VALUE_VOICE_TIER, BYOK_VOICE_RATE_KEY: rates.PREMIUM_VOICE_TIER}
        )
    }
)


def client_voice_tier(engine: str, rate_key: str) -> rates.VoiceTier | None:
    """The client price rung a minute on this engine and rate key bills on; None when the
    key is not sold (or the engine has no rule, so the agent's own voice decides)."""
    rungs = CLIENT_RUNG_OF_RATE_KEY.get(engine)
    return None if rungs is None else rungs.get(rate_key)


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


def _require_rate_key(rate_key: str) -> None:
    if rate_key not in ENGINE_RATE_KEYS:
        raise ProblemError(
            kind="not_found",
            code="engine_minute_price_unknown_rate_key",
            title="No such rate",
            detail=f"{rate_key!r} is not one of {', '.join(ENGINE_RATE_KEYS)}.",
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
    session: AsyncSession, *, engine: str, engine_agent_ref: str, rate_key: EngineRateKey
) -> None:
    """Stamp which rate a vendor agent's minutes are metered at. For the publish path, in
    the tenant session that wrote the route row."""
    _require_rate_key(rate_key)
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET engine_rate_key = :k, updated_at = now() "
            "WHERE engine = :e AND engine_agent_ref = :ref"
        ),
        {"k": rate_key, "e": engine, "ref": engine_agent_ref},
    )


@dataclass(frozen=True, slots=True)
class MinuteCost:
    rate_key: str
    billed_minutes: Decimal
    #: None when the rate key is unattested: the minute is UNPRICED, not free.
    inr_per_min: Decimal | None
    cost: CostBreakdown

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
) -> MinuteCost:
    """This call's supplier cost at the rate attested for its vendor agent's rate key.

    The whole minute is ONE leg (`platform_inr`): ThinnestAI sells telephony, speech and
    model as one per-minute price (evaluation §2), so splitting it across our per-leg rows
    would invent a breakdown nobody quoted.
    """
    _require_engine(engine)
    stamped = (
        await session.execute(
            text(
                "SELECT r.engine_rate_key FROM calls c JOIN engine_agent_routes r "
                "ON r.agent_id = c.agent_id AND r.tenant_id = c.tenant_id AND r.engine = :e "
                "WHERE c.id = :cid AND c.tenant_id = :tid "
                "ORDER BY r.active DESC, r.updated_at DESC LIMIT 1"
            ),
            {"e": engine, "cid": call_id, "tid": tenant_id},
        )
    ).scalar()
    rate_key = str(stamped) if stamped else BASE_RATE_KEY
    minutes = billed_minutes(seconds, pulse_s=PULSE_SECONDS[engine])
    price = (await attested_minute_prices(session, engine=engine, at=at)).get(rate_key)
    if price is None:
        return MinuteCost(
            rate_key=rate_key,
            billed_minutes=minutes,
            inr_per_min=None,
            cost=CostBreakdown(total_inr=Decimal(0), source_currency="INR"),
        )
    total = minutes * price.inr_per_min
    return MinuteCost(
        rate_key=rate_key,
        billed_minutes=minutes,
        inr_per_min=price.inr_per_min,
        cost=CostBreakdown(total_inr=total, platform_inr=total, source_currency="INR"),
    )


__all__ = [
    "ATTESTED_MINUTE_ENGINES",
    "BASE_RATE_KEY",
    "BYOK_VOICE_RATE_KEY",
    "CLIENT_RUNG_OF_RATE_KEY",
    "ENGINE_RATE_KEYS",
    "PULSE_SECONDS",
    "EngineMinutePrice",
    "EngineRateKey",
    "MinuteCost",
    "attest_engine_minute_price",
    "attested_minute_prices",
    "attested_rate_keys",
    "billed_minutes",
    "client_voice_tier",
    "engine_minute_cost",
    "engine_minute_is_billable",
    "record_engine_rate_key",
]

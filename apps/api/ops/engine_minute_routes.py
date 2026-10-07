"""Operator-attested per-minute engine prices (D-678).

    GET  /v1/ops/engine-minute-prices                   every engine priced by the minute,
                                                         every rate key, attested or not
    POST /v1/ops/engine-minute-prices/{engine}/{rate}   attest one; step-up
                                                         `attest_engine_minute_price:<engine>:<rate>`

The same act as the TTS price on `ops/model_price_routes.py` — an operator reads a figure
off an invoice this deployment cannot fetch and puts their name to it — with the same
permission, step-up, audit-in-transaction and append-only history. Its own module because
the subject is an ENGINE's minute, not a model's token or a voice's character.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    ENGINE_RATE_KEYS,
    EngineMinutePrice,
    attest_engine_minute_price,
    attested_minute_prices,
    client_voice_tier,
)
from apps.api.billing.rates import VOICE_TIER_LABELS
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate

router = APIRouter(prefix="/v1/ops/engine-minute-prices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
PriceOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]
EngineId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")]
RateKeyId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_]*$")]

# NUMERIC(12,6): six integer digits.
_MAX_PRICE = Decimal("1000000")


def engine_minute_confirmation(engine: str, rate_key: str) -> str:
    """The step-up string, bound to the engine AND the rate so a captured header cannot
    re-price another tier."""
    return f"attest_engine_minute_price:{engine}:{rate_key}"


class EngineMinutePriceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    rate_key: str
    #: ₹ per billed minute as a decimal string, or null while unattested.
    inr_per_min: str | None
    effective_from: str | None
    attested_at: str | None
    source_note: str | None
    #: Whether a minute on this rate may be sold (hard rule 7's one door).
    billable: bool
    #: The client price rung a minute on this rate is sold on ("Clear"), or null when no
    #: client is sold this rate (D-681: on ThinnestAI only the Premium band is sold; the
    #: platform rate is still attested, because it opens the engine at all).
    sold_as: str | None


class EngineMinutePricesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[EngineMinutePriceOut]
    as_of: str


class EngineMinutePriceAttestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ₹ per billed minute as a decimal STRING, never a JSON number (hard rule 7).
    inr_per_min: str = Field(max_length=32)
    effective_from: datetime | None = None
    #: The invoice or written quote the figure was read from.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("say where this price came from — the invoice or written quote")
        return stripped

    @field_validator("effective_from")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("effective_from must carry a timezone")
        return value


def _sold_as(engine: str, rate_key: str) -> str | None:
    tier = client_voice_tier(engine, rate_key)
    return None if tier is None else VOICE_TIER_LABELS[tier]


def _row(engine: str, rate_key: str, price: EngineMinutePrice | None) -> EngineMinutePriceOut:
    return EngineMinutePriceOut(
        engine=engine,
        rate_key=rate_key,
        inr_per_min=str(price.inr_per_min) if price else None,
        effective_from=price.effective_from.isoformat() if price else None,
        attested_at=price.attested_at.isoformat() if price else None,
        source_note=price.source_note if price else None,
        billable=price is not None,
        sold_as=_sold_as(engine, rate_key),
    )


def _rate(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        value = Decimal("NaN")
    exponent = value.as_tuple().exponent if value.is_finite() else None
    if (
        not value.is_finite()
        or value <= 0
        or value >= _MAX_PRICE
        or (isinstance(exponent, int) and -exponent > 6)
    ):
        raise ProblemError(
            kind="validation",
            code="engine_minute_price_invalid",
            title="That is not a valid price",
            detail="Rupees per billed minute: a positive decimal with at most six decimals.",
            remediation="Type the figure from the invoice, like 1.00 or 2.50.",
        )
    return value


@router.get(
    "",
    response_model=EngineMinutePricesOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every engine priced by the minute, and each rate's attested price",
)
async def list_engine_minute_prices(
    session: GlobalSession, _: PriceOperator
) -> EngineMinutePricesOut:
    at = datetime.now(UTC)
    rows: list[EngineMinutePriceOut] = []
    for engine in sorted(ATTESTED_MINUTE_ENGINES):
        attested = await attested_minute_prices(session, engine=engine, at=at)
        rows.extend(_row(engine, key, attested.get(key)) for key in ENGINE_RATE_KEYS)
    return EngineMinutePricesOut(prices=rows, as_of=at.isoformat())


@router.post(
    "/{engine}/{rate_key}",
    response_model=EngineMinutePriceOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one engine rate per billed minute (step-up confirmed, audited)",
    description=(
        "Records what one billed minute on this engine and rate costs THIS account, read off "
        "your own invoice, as a NEW effective-dated row. Requires `X-Confirm-Action: "
        "attest_engine_minute_price:<engine>:<rate_key>`. Until a rate exists, minutes on it "
        "are not offered and any that run are metered with no cost and alarmed."
    ),
)
async def attest_engine_minute(
    payload: EngineMinutePriceAttestIn,
    session: GlobalSession,
    request: Request,
    principal: PriceOperator,
    engine: EngineId,
    rate_key: RateKeyId,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> EngineMinutePriceOut:
    step_up.require(x_confirm_action, engine_minute_confirmation(engine, rate_key))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="engine_minute_price_actor_unknown",
            title="This session has no admin identity",
            detail="A price attestation has to be attributable to an operator.",
        )
    attested = await attest_engine_minute_price(
        session,
        engine=engine,
        rate_key=rate_key,
        inr_per_min=_rate(payload.inr_per_min),
        effective_from=payload.effective_from or datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.engine_minute_price_attested",
        actor=principal,
        object_type="platform_engine_minute_prices",
        object_id=f"{engine}:{rate_key}",
        ip=client_request_ip(request),
        summary={
            "engine": engine,
            "rate_key": rate_key,
            "inr_per_min": str(attested.inr_per_min),
            "effective_from": attested.effective_from.isoformat(),
            "source_note": attested.source_note,
        },
    )
    current = (await attested_minute_prices(session, engine=engine, at=datetime.now(UTC))).get(
        rate_key
    )
    return _row(engine, rate_key, current)


__all__ = ["engine_minute_confirmation", "router"]

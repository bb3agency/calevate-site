"""Operator-attested per-minute engine prices (D-678) and the cost inputs beside them (D-840).

    GET  /v1/ops/engine-minute-prices                   every engine priced by the minute,
                                                         every rate key, attested or not, and
                                                         every attested cost input
    POST /v1/ops/engine-minute-prices/{engine}/{rate}   attest one; step-up
                                                         `attest_engine_minute_price:<engine>:<rate>`
    POST /v1/ops/cost-attestations/{subject}            attest a fee or a number rent; step-up
                                                         `attest_cost:<subject>`

The same act as the TTS price on `ops/model_price_routes.py` — an operator reads a figure
off an invoice this deployment cannot fetch and puts their name to it — with the same
permission, step-up, audit-in-transaction and append-only history. Its own module because
the subject is an ENGINE's minute, not a model's token or a voice's character. The cost
inputs (`billing/cost_attestations`) share it because the wallet top-up fee is added to
every minute priced here, and an operator reads the two together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.cost_attestations import (
    COST_SUBJECTS,
    FRACTION_SUBJECTS,
    SUBJECT_LABELS,
    WALLET_TOPUP_FEE_SUBJECTS,
    AttestedCost,
    attest_cost,
    attested_costs,
    parse_cost_value,
)
from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    PRICED_RATE_KEYS,
    EngineMinutePrice,
    attest_engine_minute_price,
    attested_minute_prices,
    client_rungs,
    cost_with_fee,
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
cost_router = APIRouter(prefix="/v1/ops/cost-attestations", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
PriceOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]
EngineId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")]
RateKeyId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_]*$")]
SubjectId = Annotated[str, Path(max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]

# NUMERIC(12,6): six integer digits.
_MAX_PRICE = Decimal("1000000")


def engine_minute_confirmation(engine: str, rate_key: str) -> str:
    """The step-up string, bound to the engine AND the rate so a captured header cannot
    re-price another tier."""
    return f"attest_engine_minute_price:{engine}:{rate_key}"


def cost_confirmation(subject: str) -> str:
    """The step-up string for one cost input, bound to its subject."""
    return f"attest_cost:{subject}"


class EngineMinutePriceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    rate_key: str
    #: The platform's posted ₹ per billed minute, BEFORE its wallet top-up fee, as a decimal
    #: string; null while unattested.
    inr_per_min: str | None
    #: The wallet top-up fee we add to every minute on this engine, in percent ("2.36"); "0"
    #: for an engine not paid from a topped-up wallet; null while the fee is unattested, when
    #: every minute is metered unpriced.
    topup_fee_percent: str | None
    #: What a billed minute costs us with the fee added, at the ledger's four decimals; this
    #: is the figure metered. Null while the rate or the fee is unattested.
    inr_per_min_with_fee: str | None
    effective_from: str | None
    attested_at: str | None
    source_note: str | None
    #: Whether a minute on this rate may be sold (hard rule 7's one door).
    billable: bool
    #: The client price rung a minute on this rate is sold on ("Clear"), or null when no
    #: client is sold this rate (on ThinnestAI only the band `thinnest_clear_voice_band` names,
    #: Studio by default, and our own-key voice minutes are sold, D-688, D-792; the platform
    #: rate is still attested, because it opens the engine at all).
    sold_as: str | None


class CostAttestationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    #: What the figure is, naming the vendor (admin realm only).
    label: str
    #: `percent` for a fee, typed and shown in percent; `inr_per_month` for a rent.
    unit: Literal["percent", "inr_per_month"]
    #: The figure in force, in `unit`, as a decimal string; null while unattested.
    value: str | None
    effective_from: str | None
    attested_at: str | None
    source_note: str | None


class EngineMinutePricesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[EngineMinutePriceOut]
    #: Every cost input (D-840), attested or not, in `COST_SUBJECTS` order.
    costs: list[CostAttestationOut]
    as_of: str


class _AttestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: datetime | None = None
    #: The invoice or written quote the figure was read from.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("say where this figure came from — the invoice or written quote")
        return stripped

    @field_validator("effective_from")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("effective_from must carry a timezone")
        return value


class EngineMinutePriceAttestIn(_AttestIn):
    #: The platform's posted ₹ per billed minute, before its wallet top-up fee, as a decimal
    #: STRING, never a JSON number (hard rule 7). The fee is added by the meter.
    inr_per_min: str = Field(max_length=32)


class CostAttestIn(_AttestIn):
    #: The figure as a decimal STRING: a fee in PERCENT ("2.36"), a rent in rupees a month.
    value: str = Field(max_length=32)


def _sold_as(engine: str, rate_key: str) -> str | None:
    tier = (client_rungs(engine) or {}).get(rate_key)
    return None if tier is None else VOICE_TIER_LABELS[tier]


def _percent(fee: Decimal) -> str:
    return format((fee * 100).normalize(), "f")


def _engine_fee(engine: str, costs: dict[str, AttestedCost]) -> Decimal | None:
    subject = WALLET_TOPUP_FEE_SUBJECTS.get(engine)
    if subject is None:
        return Decimal(0)
    found = costs.get(subject)
    return None if found is None else found.value


def _row(
    engine: str, rate_key: str, price: EngineMinutePrice | None, fee: Decimal | None = None
) -> EngineMinutePriceOut:
    return EngineMinutePriceOut(
        engine=engine,
        rate_key=rate_key,
        inr_per_min=str(price.inr_per_min) if price else None,
        topup_fee_percent=None if fee is None else _percent(fee),
        inr_per_min_with_fee=(
            str(cost_with_fee(price.inr_per_min, fee=fee))
            if price is not None and fee is not None
            else None
        ),
        effective_from=price.effective_from.isoformat() if price else None,
        attested_at=price.attested_at.isoformat() if price else None,
        source_note=price.source_note if price else None,
        billable=price is not None,
        sold_as=_sold_as(engine, rate_key),
    )


def _cost_row(subject: str, attested: AttestedCost | None) -> CostAttestationOut:
    fraction = subject in FRACTION_SUBJECTS
    value: str | None = None
    if attested is not None:
        value = _percent(attested.value) if fraction else str(attested.value.normalize())
    return CostAttestationOut(
        subject=subject,
        label=SUBJECT_LABELS[subject],
        unit="percent" if fraction else "inr_per_month",
        value=value,
        effective_from=attested.effective_from.isoformat() if attested else None,
        attested_at=attested.attested_at.isoformat() if attested else None,
        source_note=attested.source_note if attested else None,
    )


def parse_minute_rate(raw: str) -> Decimal:
    """An operator's typed per-minute figure as an exact Decimal, or this route's refusal.
    Pip's attestation (`copilot/admin_actions.py`) parses through here too."""
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


def _require_operator(principal: Principal) -> object:
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="engine_minute_price_actor_unknown",
            title="This session has no admin identity",
            detail="A price attestation has to be attributable to an operator.",
        )
    return principal.user_id


@router.get(
    "",
    response_model=EngineMinutePricesOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every engine priced by the minute, each rate's attested price, and the fees",
)
async def list_engine_minute_prices(
    session: GlobalSession, _: PriceOperator
) -> EngineMinutePricesOut:
    at = datetime.now(UTC)
    costs = await attested_costs(session, at=at)
    rows: list[EngineMinutePriceOut] = []
    for engine in sorted(ATTESTED_MINUTE_ENGINES):
        attested = await attested_minute_prices(session, engine=engine, at=at)
        fee = _engine_fee(engine, costs)
        rows.extend(_row(engine, key, attested.get(key), fee) for key in PRICED_RATE_KEYS)
    return EngineMinutePricesOut(
        prices=rows,
        costs=[_cost_row(subject, costs.get(subject)) for subject in COST_SUBJECTS],
        as_of=at.isoformat(),
    )


@router.post(
    "/{engine}/{rate_key}",
    response_model=EngineMinutePriceOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one engine rate per billed minute (step-up confirmed, audited)",
    description=(
        "Records the voice platform's posted rate per billed minute, before its wallet top-up "
        "fee, as a NEW effective-dated row. We add the attested fee when metering (each row's "
        "`topup_fee_percent` says what is added, and `inr_per_min_with_fee` is the figure "
        "metered). Requires `X-Confirm-Action: attest_engine_minute_price:<engine>:<rate_key>`. "
        "Until a rate exists, minutes on it are not offered and any that run are metered with "
        "no cost and alarmed."
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
    actor = _require_operator(principal)
    attested = await attest_engine_minute_price(
        session,
        engine=engine,
        rate_key=rate_key,
        inr_per_min=parse_minute_rate(payload.inr_per_min),
        effective_from=payload.effective_from or datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=actor,
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
    now = datetime.now(UTC)
    current = (await attested_minute_prices(session, engine=engine, at=now)).get(rate_key)
    fee = _engine_fee(engine, await attested_costs(session, at=now))
    return _row(engine, rate_key, current, fee)


@cost_router.post(
    "/{subject}",
    response_model=CostAttestationOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest a fee or a number rent (step-up confirmed, audited)",
    description=(
        "Records one cost input as a NEW effective-dated row: the voice platform's wallet "
        "top-up fee or the payment gateway's fee on a client's top-up, in PERCENT, or the "
        "monthly rent of a number rented in the voice platform's console, in rupees. Requires "
        "`X-Confirm-Action: attest_cost:<subject>`. Rows already metered are not re-priced."
    ),
)
async def attest_cost_input(
    payload: CostAttestIn,
    session: GlobalSession,
    request: Request,
    principal: PriceOperator,
    subject: SubjectId,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> CostAttestationOut:
    step_up.require(x_confirm_action, cost_confirmation(subject))
    actor = _require_operator(principal)
    attested = await attest_cost(
        session,
        subject=subject,
        value=parse_cost_value(subject, payload.value),
        effective_from=payload.effective_from or datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=actor,
    )
    await write_audit(
        session,
        action="platform.cost_attested",
        actor=principal,
        object_type="platform_cost_attestations",
        object_id=subject,
        ip=client_request_ip(request),
        summary={
            "subject": subject,
            "value": str(attested.value),
            "effective_from": attested.effective_from.isoformat(),
            "source_note": attested.source_note,
        },
    )
    current = (await attested_costs(session, at=datetime.now(UTC))).get(subject)
    return _cost_row(subject, current)


__all__ = [
    "cost_confirmation",
    "cost_router",
    "engine_minute_confirmation",
    "parse_minute_rate",
    "router",
]

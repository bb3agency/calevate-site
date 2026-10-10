"""The exchange rate an operator can see — what is in force, why, and how fresh it is.

    GET /v1/ops/fx-rate    the rate in force and its rung, the last check, the last N pulls

READ-ONLY. There is no route here that sets a rate. The pulled rate is a machine
observation with a source and a publication date — a thing that can be re-fetched and
checked — and letting a console overwrite it would produce a number with the authority
of a measurement and the provenance of a guess. An operator who distrusts the published
rate has the right control in the config panel: `usd_inr_rate` plus the
`usd_inr_rate_override` switch, which converts at the typed number and says so on every
row it converts (`configured:usd_inr_rate`).

WHY IT IS A SEPARATE ROUTER FROM `config_routes.py`. Same reason `model_price_routes.py`
is: this is not a `Settings` field. It is a table of dated observations, resolved from
the database at render time rather than layered onto `Settings`, so it has a different
reader and no write shape at all. Same realm, same permission, same audit discipline.

THE SERVER DECIDES EVERY WORD ON THE SCREEN, and the browser prints them. `basis`,
`state`, `last_checked_label` and the rupee figures are computed here — the doctrine
stated at `apps/web/src/lib/api/aiQuota.ts:1-26`: a browser that decided whether a rate
was stale would need the ceiling, and a ceiling in a bundle is a ceiling that is wrong the
day it changes. Money crosses the wire as a STRING for hard rule 7's reason — `88.4275`
sent as a JSON number has been through a binary double before the screen sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.fx import MAX_QUOTE_AGE, RateBasis, resolve_usd_inr_rate
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.ops.fx_rates import (
    BASE_CURRENCY,
    QUOTE_CURRENCY,
    FxCheck,
    FxObservation,
    last_check,
    latest_observation,
    recent_observations,
)

router = APIRouter(prefix="/v1/ops/fx-rate", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
FxOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

#: How many past observations the panel shows by default, and the most it will ever show.
#: BOUNDED at the boundary AND in the SQL (`check_list_bounds`): this table gains up to
#: 288 rows a day, so an unbounded history is a response whose size is a function of how
#: long the deployment has been up.
HISTORY_LIMIT = 12
MAX_HISTORY = 50


def _age_label(age_seconds: float) -> str:
    """ "2 hours ago", in the server's words. See the module docstring for why not the
    browser's: the same phrase renders beside a threshold only this side knows."""
    minutes = int(age_seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"


class FxObservationOut(BaseModel):
    """One pulled observation, as the panel lists it."""

    model_config = ConfigDict(extra="forbid")

    rate: str = Field(description="Units of quote currency per ONE unit of base, as a string")
    as_of: str = Field(description="The date the SOURCE published this rate (ISO)")
    source: str
    source_url: str
    observed_at: datetime = Field(description="When this deployment first stored it")

    @classmethod
    def of(cls, observation: FxObservation) -> FxObservationOut:
        return cls(
            rate=str(observation.rate),
            as_of=observation.as_of.isoformat(),
            source=observation.source,
            source_url=observation.source_url,
            observed_at=observation.observed_at,
        )


class FxRateOut(BaseModel):
    """The rate panel, whole. Every field is required — the config and pricing panels'
    rule: a fact the console must trust is never defaulted, and `null` carries a real
    state rather than an absence."""

    model_config = ConfigDict(extra="forbid")

    base_currency: str
    quote_currency: str
    #: What money is ACTUALLY converting at right now, whichever rung it came from. The one
    #: number on this screen that answers "what is a client being billed at".
    effective_rate: str
    #: Which rung of `core/fx.resolve_usd_inr_rate` produced `effective_rate`:
    #: `published` (inside the ceiling), `stale_published` (the newest published rate, past
    #: it), `manual_override` (the operator switched the override on), `manual_no_quote`
    #: (nothing has ever been published).
    basis: RateBasis
    #: The newest PUBLISHED rate's own state, independent of the override: `live` inside
    #: the ceiling, `stale` past it, `never_pulled` when nothing has been stored.
    state: Literal["live", "stale", "never_pulled"]
    #: The typed rate, always shown: an operator deciding whether to switch the override on
    #: needs it beside the published one.
    manual_rate: str
    manual_override: bool
    #: The newest published rate, even when it is stale. `null` only in `never_pulled`.
    published_rate: str | None
    published_as_of: str | None
    published_source: str | None
    #: When this deployment FIRST stored that publication. A repeat poll of the same
    #: publication stores nothing, so this does not move on every tick; `last_checked_at`
    #: does.
    observed_at: datetime | None
    #: When the five-minute pull last completed, or `null` if no completed tick is
    #: recorded. Read from `ops/fx_rates.last_check`.
    last_checked_at: datetime | None
    last_checked_label: str | None
    #: The ceiling, in days, so the screen can say WHY something is stale without knowing
    #: the constant.
    max_age_days: int
    history: list[FxObservationOut]


def _build(
    observation: FxObservation | None,
    *,
    now: datetime,
    manual_rate: Decimal,
    manual_override: bool,
    checked: FxCheck | None,
    history: list[FxObservation],
) -> FxRateOut:
    """Assemble the panel from the STORE, not from `core/fx`'s holder.

    Deliberately: the holder answers "what may this PROCESS convert at", and on a
    multi-process deployment that is one replica's answer to a question about the
    platform. The store is the shared truth, and the ladder applied to it here is
    `core/fx.resolve_usd_inr_rate`, the one every conversion applies, so the screen and
    the money cannot disagree about which rung is in force.
    """
    quote = observation.as_quote() if observation is not None else None
    resolved = resolve_usd_inr_rate(
        quote, manual=manual_rate, manual_override=manual_override, now=now
    )
    state: Literal["live", "stale", "never_pulled"] = (
        "never_pulled" if quote is None else "live" if quote.fresh(now) else "stale"
    )
    return FxRateOut(
        base_currency=BASE_CURRENCY,
        quote_currency=QUOTE_CURRENCY,
        effective_rate=str(resolved.rate),
        basis=resolved.basis,
        state=state,
        manual_rate=str(manual_rate),
        manual_override=manual_override,
        published_rate=str(observation.rate) if observation else None,
        published_as_of=observation.as_of.isoformat() if observation else None,
        published_source=observation.source if observation else None,
        observed_at=observation.observed_at if observation else None,
        last_checked_at=checked.checked_at if checked else None,
        last_checked_label=(
            _age_label((now - checked.checked_at).total_seconds()) if checked else None
        ),
        max_age_days=MAX_QUOTE_AGE.days,
        history=[FxObservationOut.of(row) for row in history],
    )


@router.get(
    "",
    response_model=FxRateOut,
    summary="The USD/INR rate in force, why, and when it was last checked",
    openapi_extra=permission_meta("platform:config"),
)
async def read_fx_rate(
    session: GlobalSession,
    _operator: FxOperator,
    limit: int = Query(HISTORY_LIMIT, ge=1, le=MAX_HISTORY),
) -> FxRateOut:
    """What vendor costs are being converted at, and whether anyone should worry."""
    now = datetime.now(UTC)
    observation = await latest_observation(session)
    history = await recent_observations(session, limit=limit)
    settings = get_settings()
    return _build(
        observation,
        now=now,
        manual_rate=settings.usd_inr_rate,
        manual_override=settings.usd_inr_rate_override,
        checked=await last_check(),
        history=history,
    )


__all__ = ["FxObservationOut", "FxRateOut", "router"]

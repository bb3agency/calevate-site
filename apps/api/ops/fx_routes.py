"""The exchange rate an operator can see — what it is, how old it is, where it came from.

    GET /v1/ops/fx-rate    the rate in force, its age, its source, and the last N pulls

READ-ONLY, AND THAT IS THE DESIGN. There is no route here that sets a rate. The pulled
rate is a machine observation with a source and a publication date — a thing that can be
re-fetched and checked — and letting a console overwrite it would produce a number with
the authority of a measurement and the provenance of a guess. An operator who needs to
override the rate already has the right control: `USD_INR_RATE` in the config panel,
which is the declared FALLBACK, is labelled as one, and is what money converts at
whenever the pull has nothing fresh.

WHY IT IS A SEPARATE ROUTER FROM `config_routes.py`. Same reason `model_price_routes.py`
is: this is not a `Settings` field. It is a table of dated observations, resolved from
the database at render time rather than layered onto `Settings`, so it has a different
reader and no write shape at all. Same realm, same permission, same audit discipline.

THE SERVER DECIDES EVERY WORD ON THE SCREEN, and the browser prints them. `state`,
`age_label` and the rupee figures are computed here — the doctrine stated at
`apps/web/src/lib/api/aiQuota.ts:1-26`: a browser that decided whether a rate was stale
would need the ceiling, and a ceiling in a bundle is a ceiling that is wrong the day it
changes. Money crosses the wire as a STRING for hard rule 7's reason — `88.4275` sent as
a JSON number has been through a binary double before the screen sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.fx import MAX_QUOTE_AGE, FxQuote
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.ops.fx_rates import (
    BASE_CURRENCY,
    QUOTE_CURRENCY,
    FxObservation,
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
    observed_at: datetime = Field(description="When this deployment fetched it")

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
    #: What money is ACTUALLY converting at right now, whichever door it came through.
    #: The one number on this screen that answers "what is a client being billed at".
    effective_rate: str
    #: `live` — a published rate inside its ceiling. `stale` — one past it, so the
    #: fallback is in force. `never_pulled` — nothing has ever been stored here.
    state: Literal["live", "stale", "never_pulled"]
    #: True when `effective_rate` is the configured `USD_INR_RATE` rather than a published
    #: figure. Named as a fact rather than left to be inferred from `state`, because it is
    #: the sentence an operator has to read: "you are billing off a typed number".
    using_fallback: bool
    #: The operator-set fallback, always shown — an operator comparing a stale published
    #: rate with what will replace it needs both on one screen.
    fallback_rate: str
    #: The published rate last stored, even when it is too old to use. `null` only in
    #: `never_pulled`.
    published_rate: str | None
    published_as_of: str | None
    published_source: str | None
    observed_at: datetime | None
    age_label: str | None
    #: The ceiling, in days, so the screen can say WHY something is stale without knowing
    #: the constant.
    max_age_days: int
    history: list[FxObservationOut]


def _build(
    observation: FxObservation | None, *, now: datetime, fallback: str, history: list[FxObservation]
) -> FxRateOut:
    """Assemble the panel from the STORE, not from `core/fx`'s holder.

    Deliberately: the holder answers "what may this PROCESS convert at", and on a
    multi-process deployment that is one replica's answer to a question about the
    platform. The store is the shared truth, and the freshness rule applied to it here is
    the same `FxQuote.usable` every conversion applies, so the screen and the money cannot
    disagree about what counts as stale.
    """
    if observation is None:
        return FxRateOut(
            base_currency=BASE_CURRENCY,
            quote_currency=QUOTE_CURRENCY,
            effective_rate=fallback,
            state="never_pulled",
            using_fallback=True,
            fallback_rate=fallback,
            published_rate=None,
            published_as_of=None,
            published_source=None,
            observed_at=None,
            age_label=None,
            max_age_days=MAX_QUOTE_AGE.days,
            history=[],
        )
    quote: FxQuote = observation.as_quote()
    usable = quote.usable(now)
    return FxRateOut(
        base_currency=observation.base_currency,
        quote_currency=observation.quote_currency,
        effective_rate=str(observation.rate) if usable else fallback,
        state="live" if usable else "stale",
        using_fallback=not usable,
        fallback_rate=fallback,
        published_rate=str(observation.rate),
        published_as_of=observation.as_of.isoformat(),
        published_source=observation.source,
        observed_at=observation.observed_at,
        age_label=_age_label((now - observation.observed_at).total_seconds()),
        max_age_days=MAX_QUOTE_AGE.days,
        history=[FxObservationOut.of(row) for row in history],
    )


@router.get(
    "",
    response_model=FxRateOut,
    summary="The USD/INR rate in force, its age and its source",
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
    return _build(
        observation,
        now=now,
        fallback=str(get_settings().usd_inr_rate),
        history=history,
    )


__all__ = ["FxObservationOut", "FxRateOut", "router"]

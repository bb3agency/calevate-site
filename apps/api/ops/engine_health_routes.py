"""Whether the voice engine is answering: the client banner's read and the operator panel.

What a client is shown comes from the dial hold (`engine/outage.hold_is_on`), the same fact
the dialler acts on, so the banner, the paused test-call button and a waiting campaign can
never disagree with whether calls are actually going out. The client is told that one fact
and when it began; not the route, the error class or the counts, which they cannot act on,
and never the provider's name (D-679).

The operator gets the hold beside the run of failures across every request
(`engine/answering.py`: what failed last, on which route, since when), the five-minute counts
behind the spike alarm, and whether the hold's own page is open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Instant
from apps.api.engine.answering import OUTAGE_MIN_FAILURES, engine_outage
from apps.api.engine.health import SPIKE_THRESHOLD, SPIKE_WINDOW_MINUTES
from apps.api.engine.outage import TRIP_AFTER_FAILURES, hold_is_on, hold_started_at

router = APIRouter(prefix="/v1/ops/engine-health", tags=["ops"])
client_router = APIRouter(prefix="/v1/phone-service", tags=["phone-service"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
#: Every client role holds `org:read`: knowing calls are paused is not a privilege.
AnyClient = Annotated[Principal, Depends(requires("org:read"))]

#: The page the dial hold raises on trip and resolves on lift (`engine/outage.py`).
HOLD_ALARM = "engine_dial_hold"


class PhoneServiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `not_answering` while calls and test calls are held.
    state: Literal["answering", "not_answering"]
    #: When the hold began; null while answering, or when it is on but its start is unknown.
    since: Instant | None = None


class EngineHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Our engine name (`thinnest`, `fake`).
    engine: str
    #: Dials are held: the fact clients are shown.
    held: bool
    #: When the hold began.
    held_since: Instant | None
    #: Failed dials in a row that trip the hold.
    hold_after_dial_failures: int
    #: Every request's run of failures (`engine/answering.py`), not only dials: an outage
    #: with no dial traffic shows here before, or without, a hold.
    run_is_outage: bool
    run_since: Instant | None
    consecutive_failures: int
    #: The run length `run_is_outage` needs.
    outage_after_failures: int
    last_failure_at: Instant | None
    #: `server_error` (it answered 5xx) or `unreachable` (no answer at all).
    last_kind: Literal["server_error", "unreachable"] | None
    #: The transport error's class (`ReadTimeout`, `ConnectError`) or `HTTP 503`.
    last_error: str | None
    #: Our route template (`/calls`, `/agents/{ref}`).
    last_route: str | None
    #: The last time an answer ended a run, and the last time an outage run ended.
    last_answer_at: Instant | None
    recovered_at: Instant | None
    #: The spike alarm's window and threshold, and the counts in that window now.
    window_minutes: int
    spike_threshold: int
    window_server_errors: int
    window_unreachable: int
    #: When the open `engine_dial_hold` page began; null when none is open.
    alarm_open_since: Instant | None


@client_router.get(
    "",
    response_model=PhoneServiceOut,
    openapi_extra=permission_meta("org:read"),
    summary="Is the phone service answering? Backs the 'calls are paused' banner",
)
async def phone_service(_: AnyClient) -> PhoneServiceOut:
    if not await hold_is_on():
        return PhoneServiceOut(state="answering")
    return PhoneServiceOut(state="not_answering", since=await hold_started_at())


@router.get(
    "",
    response_model=EngineHealthOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The voice engine's health now: the dial hold, the failing run, its last error",
)
async def engine_health(session: GlobalSession, _: Operator) -> EngineHealthOut:
    held = await hold_is_on()
    run = await engine_outage()
    window = (
        await session.execute(
            text(
                "SELECT coalesce(sum(server_errors), 0), coalesce(sum(unreachable), 0) "
                "FROM platform_engine_health WHERE engine = :engine "
                "AND bucket_start >= date_trunc('minute', now()) - make_interval(mins => :m)"
            ),
            {"engine": run.engine, "m": SPIKE_WINDOW_MINUTES},
        )
    ).one()
    alarm: datetime | None = (
        await session.execute(
            text(
                "SELECT min(first_seen_at) FROM platform_alerts "
                "WHERE code = :code AND cleared_at IS NULL"
            ),
            {"code": HOLD_ALARM},
        )
    ).scalar()
    return EngineHealthOut(
        engine=run.engine,
        held=held,
        held_since=await hold_started_at() if held else None,
        hold_after_dial_failures=TRIP_AFTER_FAILURES,
        run_is_outage=run.failing,
        run_since=run.since,
        consecutive_failures=run.consecutive_failures,
        outage_after_failures=OUTAGE_MIN_FAILURES,
        last_failure_at=run.last_failure_at,
        last_kind=run.last_kind,
        last_error=run.last_error,
        last_route=run.last_route,
        last_answer_at=run.last_answer_at,
        recovered_at=run.recovered_at,
        window_minutes=SPIKE_WINDOW_MINUTES,
        spike_threshold=SPIKE_THRESHOLD,
        window_server_errors=int(window[0]),
        window_unreachable=int(window[1]),
        alarm_open_since=alarm,
    )


__all__ = ["EngineHealthOut", "PhoneServiceOut", "client_router", "router"]

"""Whether the voice engine is answering: the client banner's read and the operator panel.

Both read `engine/outage.engine_outage()`, the one source every outage surface shares, so the
banner, the disabled test-call button and the operator panel cannot disagree.

The client is told one fact and the instant it began: whether calls can go through. Not the
route, the error class or the counts, which are operational detail a client cannot act on,
and never the provider's name (D-679). The operator gets the run, the five-minute counts
behind the paging alarm, and whether that alarm's episode is open.
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
from apps.api.engine.health import SPIKE_THRESHOLD, SPIKE_WINDOW_MINUTES
from apps.api.engine.outage import OUTAGE_MIN_FAILURES, engine_outage

router = APIRouter(prefix="/v1/ops/engine-health", tags=["ops"])
client_router = APIRouter(prefix="/v1/phone-service", tags=["phone-service"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
#: Every client role holds `org:read`: knowing calls are paused is not a privilege.
AnyClient = Annotated[Principal, Depends(requires("org:read"))]

SPIKE_CODE = "engine_error_spike"


class PhoneServiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `not_answering` while calls, test calls and putting changes live cannot go through.
    state: Literal["answering", "not_answering"]
    #: When it stopped answering; null while answering.
    since: Instant | None = None


class EngineHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Our engine name (`thinnest`, `fake`).
    engine: str
    #: The same fact clients see: a run of consecutive failures that is still fresh.
    failing: bool
    #: The first failure of the current run; null while answering.
    since: Instant | None
    consecutive_failures: int
    #: The run length that counts as an outage (clients see the banner from here).
    outage_after_failures: int
    last_failure_at: Instant | None
    #: `server_error` (it answered 5xx) or `unreachable` (no answer at all).
    last_kind: Literal["server_error", "unreachable"] | None
    #: The transport error's class (`ReadTimeout`, `ConnectError`) or `HTTP 503`.
    last_error: str | None
    #: Our route template (`/calls`, `/agents/{ref}`).
    last_route: str | None
    #: The last time an answer ended a run, and the last time an outage ended.
    last_answer_at: Instant | None
    recovered_at: Instant | None
    #: The paging alarm's window and threshold, and the counts in that window now.
    window_minutes: int
    spike_threshold: int
    window_server_errors: int
    window_unreachable: int
    #: When the open `engine_error_spike` episode began; null when none is open.
    alarm_open_since: Instant | None


@client_router.get(
    "",
    response_model=PhoneServiceOut,
    openapi_extra=permission_meta("org:read"),
    summary="Is the phone service answering? Backs the 'calls are paused' banner",
)
async def phone_service(_: AnyClient) -> PhoneServiceOut:
    outage = await engine_outage()
    if not outage.failing:
        return PhoneServiceOut(state="answering")
    return PhoneServiceOut(state="not_answering", since=outage.since)


@router.get(
    "",
    response_model=EngineHealthOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The voice engine's health now: the failing run, its last error, the alarm",
)
async def engine_health(session: GlobalSession, _: Operator) -> EngineHealthOut:
    outage = await engine_outage()
    window = (
        await session.execute(
            text(
                "SELECT coalesce(sum(server_errors), 0), coalesce(sum(unreachable), 0) "
                "FROM platform_engine_health WHERE engine = :engine "
                "AND bucket_start >= date_trunc('minute', now()) - make_interval(mins => :m)"
            ),
            {"engine": outage.engine, "m": SPIKE_WINDOW_MINUTES},
        )
    ).one()
    alarm: datetime | None = (
        await session.execute(
            text(
                "SELECT min(first_seen_at) FROM platform_alerts "
                "WHERE code = :code AND cleared_at IS NULL"
            ),
            {"code": SPIKE_CODE},
        )
    ).scalar()
    return EngineHealthOut(
        engine=outage.engine,
        failing=outage.failing,
        since=outage.since,
        consecutive_failures=outage.consecutive_failures,
        outage_after_failures=OUTAGE_MIN_FAILURES,
        last_failure_at=outage.last_failure_at,
        last_kind=outage.last_kind,
        last_error=outage.last_error,
        last_route=outage.last_route,
        last_answer_at=outage.last_answer_at,
        recovered_at=outage.recovered_at,
        window_minutes=SPIKE_WINDOW_MINUTES,
        spike_threshold=SPIKE_THRESHOLD,
        window_server_errors=int(window[0]),
        window_unreachable=int(window[1]),
        alarm_open_since=alarm,
    )


__all__ = ["EngineHealthOut", "PhoneServiceOut", "client_router", "router"]

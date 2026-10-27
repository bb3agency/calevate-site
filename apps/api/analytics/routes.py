"""`/v1/analytics/*` — the client realm's charts over a chosen IST range (D-869).

All reads are `calls:read`, the permission the dashboard and `/v1/performance` already
require: these are the same numbers drawn differently, and a reader who may see one may
see the other. Each route takes `days` (1-366, bounded here so `check_list_bounds` can see
the ceiling) and an optional `to` (an IST date, today by default).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.analytics import service
from apps.api.analytics.schemas import (
    CallGroupBy,
    CallGroupsOut,
    CampaignTimelinesOut,
    DurationGroupBy,
    DurationsOut,
    HeatmapMetric,
    HeatmapOut,
    StatsOut,
    SummaryBucket,
    SummaryOut,
    TimelineOut,
)
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta, role_has

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("calls:read"))]
Days = Annotated[
    int,
    Query(
        ge=1,
        le=service.MAX_RANGE_DAYS,
        description=f"How many IST calendar days, 1-{service.MAX_RANGE_DAYS}, ending on `to`.",
    ),
]
To = Annotated[
    date | None,
    Query(description="The last IST day of the range (YYYY-MM-DD). Today when left out."),
]
AgentFilter = Annotated[UUID | None, Query(description="Only this agent's calls and leads.")]
TestCalls = Annotated[
    bool, Query(description="False leaves out the owner's own test calls (D-697, D-859).")
]


@router.get(
    "/heatmap",
    response_model=HeatmapOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Calls or new leads per IST weekday and hour — always 168 cells",
)
async def get_heatmap(
    session: Session,
    _: Reader,
    days: Days = service.DEFAULT_RANGE_DAYS,
    to: To = None,
    metric: Annotated[HeatmapMetric, Query()] = "calls",
    agent_id: AgentFilter = None,
    test_calls: TestCalls = True,
) -> HeatmapOut:
    window = service.resolve_window(days=days, to=to)
    return await service.heatmap(
        session, window=window, metric=metric, agent_id=agent_id, test_calls=test_calls
    )


@router.get(
    "/durations",
    response_model=DurationsOut,
    openapi_extra=permission_meta("calls:read"),
    summary="How long completed calls lasted, binned per agent or per outcome",
)
async def get_durations(
    session: Session,
    _: Reader,
    days: Days = service.DEFAULT_RANGE_DAYS,
    to: To = None,
    group_by: Annotated[DurationGroupBy, Query()] = "agent",
    bin_s: Annotated[int, Query(description="Bin width in seconds: 15, 30, 60 or 120.")] = 30,
    limit: Annotated[int, Query(ge=1, le=service.MAX_DURATION_GROUPS)] = 8,
    agent_id: AgentFilter = None,
    test_calls: TestCalls = True,
) -> DurationsOut:
    if bin_s not in service.DURATION_BIN_WIDTHS:
        raise ProblemError(
            kind="validation",
            code="analytics_bin_width",
            title="That bin width is not offered",
            detail="`bin_s` is 15, 30, 60 or 120 seconds.",
            remediation="Send `bin_s` as one of 15, 30, 60 or 120.",
        )
    window = service.resolve_window(days=days, to=to)
    return await service.durations(
        session,
        window=window,
        group_by=group_by,
        bin_s=bin_s,
        limit=limit,
        agent_id=agent_id,
        test_calls=test_calls,
    )


@router.get(
    "/timeline",
    response_model=TimelineOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Calls, answered calls and new leads per IST day, zero-filled",
)
async def get_timeline(
    session: Session,
    _: Reader,
    days: Days = 90,
    to: To = None,
    agent_id: AgentFilter = None,
    test_calls: TestCalls = True,
) -> TimelineOut:
    window = service.resolve_window(days=days, to=to)
    return await service.timeline(session, window=window, agent_id=agent_id, test_calls=test_calls)


@router.get(
    "/campaigns",
    response_model=CampaignTimelinesOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Dials, connected calls and new leads per IST day for each campaign",
)
async def get_campaign_timelines(
    session: Session,
    _: Reader,
    days: Days = 90,
    to: To = None,
    campaign_id: Annotated[
        UUID | None, Query(description="One campaign; otherwise the busiest in the range.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_CAMPAIGN_SERIES)] = 5,
) -> CampaignTimelinesOut:
    window = service.resolve_window(days=days, to=to)
    return await service.campaign_timelines(
        session, window=window, campaign_id=campaign_id, limit=limit
    )


@router.get(
    "/stats",
    response_model=StatsOut,
    openapi_extra=permission_meta("calls:read"),
    summary="The stats band for a range, each figure beside the same length of time before",
)
async def get_stats(
    session: Session,
    _: Reader,
    days: Days = 7,
    to: To = None,
    agent_id: AgentFilter = None,
    test_calls: TestCalls = True,
) -> StatsOut:
    window = service.resolve_window(days=days, to=to)
    return await service.stats(session, window=window, agent_id=agent_id, test_calls=test_calls)


@router.get(
    "/call-groups",
    response_model=CallGroupsOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Every call in a range counted per caller, outcome or agent, most calls first",
    description=(
        "`min_calls=2` with `by=caller` lists repeat callers. The totals count every call; "
        "only `groups` is cut to `limit`. A caller is shown by lead and the number's last "
        "two digits, never the number."
    ),
)
async def get_call_groups(
    session: Session,
    _: Reader,
    by: Annotated[CallGroupBy, Query(description="caller, outcome or agent")] = "caller",
    days: Days = 7,
    to: To = None,
    agent_id: AgentFilter = None,
    test_calls: TestCalls = False,
    min_calls: Annotated[int, Query(ge=1, le=100)] = 1,
    limit: Annotated[int, Query(ge=1, le=service.MAX_CALL_GROUPS)] = 25,
) -> CallGroupsOut:
    window = service.resolve_window(days=days, to=to)
    return await service.call_groups(
        session,
        window=window,
        by=by,
        agent_id=agent_id,
        test_calls=test_calls,
        min_calls=min_calls,
        limit=limit,
    )


@router.get(
    "/summary",
    response_model=SummaryOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Calls, answered calls, new leads and spend per IST day, week or month",
    description=(
        "Weeks start on Monday; the first and last bucket are cut to the range. Spend is "
        "what left the wallet and is null with `spend_withheld` when the reader does not "
        "hold `billing:read` or one agent is picked."
    ),
)
async def get_summary(
    session: Session,
    principal: Reader,
    days: Days = 30,
    to: To = None,
    bucket: Annotated[SummaryBucket, Query(description="day, week or month")] = "week",
    agent_id: AgentFilter = None,
    test_calls: TestCalls = True,
) -> SummaryOut:
    assert principal.tenant_id is not None
    window = service.resolve_window(days=days, to=to)
    return await service.summary(
        session,
        tenant_id=principal.tenant_id,
        window=window,
        bucket=bucket,
        agent_id=agent_id,
        test_calls=test_calls,
        may_see_spend=principal.role is not None and role_has(principal.role, "billing:read"),
    )


__all__ = ["router"]

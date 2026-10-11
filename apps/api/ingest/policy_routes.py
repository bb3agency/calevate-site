"""`/v1/lead-calling` — a client's plan for calling new leads, and the leads held for it (D-716).

One plan per client (founder decision 10, 10 Oct 2026). What the screen shows beside it —
where leads come from, a test lead, recent arrivals — is the lead-sources API, unchanged
(`ingest/routes.py`). The rules no client can switch off are returned as sentences so the
screen states them rather than inventing its own wording.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import queue_live_apply
from apps.api.compliance.audit import write_audit
from apps.api.compliance.trial_access import TRIAL_REFUSALS, restricting_trial
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.ingest import lead_policy
from apps.api.ingest.lead_policy import LeadCallPlan

router = APIRouter(prefix="/v1/lead-calling", tags=["lead-ingest"])

SessionDep = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Manager = Annotated[Principal, Depends(requires("org:manage"))]

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
AfterHours = Literal["next_open", "open_plus_3h", "next_day", "hold"]
ALL_DAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: Applied on every call this plan times, and not switchable (hard rule 5).
ALWAYS_APPLIED: tuple[str, ...] = (
    "Numbers on your do-not-call list, or the national one, are never called.",
    "Calls go out only between 9 AM and 9 PM Indian time, whatever hours you set here.",
    "Every call passes the same compliance check as a campaign before it is placed.",
    "Your agent always says it is an AI and that the call is recorded when asked.",
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadCallingIn(Strict):
    #: Null: each lead source's own agent calls.
    calling_agent_id: UUID | None = None
    wait_seconds: int = Field(0, ge=0, le=3600)
    hours_start: time = time(9, 0)
    hours_end: time = time(21, 0)
    days: list[Weekday] = Field(default_factory=lambda: list(ALL_DAYS), min_length=1, max_length=7)
    holidays: list[date] = Field(default_factory=list, max_length=60)
    after_hours: AfterHours = "next_open"
    retry_attempts: int = Field(0, ge=0, le=3)
    retry_interval_minutes: int = Field(60, ge=10, le=1440)
    detect_machines: bool = False


class LeadCallingOut(BaseModel):
    calling_agent_id: UUID | None
    wait_seconds: int
    hours_start: time
    hours_end: time
    days: list[Weekday]
    holidays: list[date]
    after_hours: AfterHours
    retry_attempts: int
    retry_interval_minutes: int
    detect_machines: bool
    #: Null until the plan is first saved; the values above are then the defaults.
    updated_at: datetime | None
    #: The platform window the hours must sit inside (IST), for the screen's bounds.
    window_start: time
    window_end: time
    held_count: int
    #: The trial sentence when the account may only place test calls, else null.
    trial_notice: str | None
    always_applied: list[str]
    #: Live agents being given the new answering-machine setting by this save. They are
    #: updated straight after it commits (D-720); a call in progress finishes first.
    agents_updated: int = 0


class HeldLeadOut(BaseModel):
    id: UUID
    lead_id: UUID
    lead_name: str | None
    agent_id: UUID
    agent_name: str | None
    source: str
    held_at: datetime


class HeldLeadsOut(BaseModel):
    items: list[HeldLeadOut]


class ReleasedOut(BaseModel):
    callback_id: UUID
    due_at: datetime


async def _out(
    session: AsyncSession, tenant_id: UUID, plan: LeadCallPlan, agents_updated: int = 0
) -> LeadCallingOut:
    trial = await restricting_trial(session, tenant_id=tenant_id)
    return LeadCallingOut(
        calling_agent_id=plan.calling_agent_id,
        wait_seconds=plan.wait_seconds,
        hours_start=plan.hours_start,
        hours_end=plan.hours_end,
        days=list(plan.days),  # type: ignore[arg-type]
        holidays=list(plan.holidays),
        after_hours=plan.after_hours,  # type: ignore[arg-type]
        retry_attempts=plan.retry_attempts,
        retry_interval_minutes=plan.retry_interval_minutes,
        detect_machines=plan.detect_machines,
        updated_at=plan.updated_at,
        window_start=lead_policy.DEFAULT_PLAN.hours_start,
        window_end=lead_policy.DEFAULT_PLAN.hours_end,
        held_count=await lead_policy.count_held(session),
        trial_notice=TRIAL_REFUSALS["live_outbound"][1] if trial is not None else None,
        always_applied=list(ALWAYS_APPLIED),
        agents_updated=agents_updated,
    )


@router.get(
    "",
    response_model=LeadCallingOut,
    openapi_extra=permission_meta("org:read"),
    summary="How new leads are called: agent, wait, hours, after hours, retries",
)
async def get_lead_calling(session: SessionDep, principal: Reader) -> LeadCallingOut:
    assert principal.tenant_id is not None
    return await _out(session, principal.tenant_id, await lead_policy.load_plan(session))


@router.put(
    "",
    response_model=LeadCallingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save how new leads are called",
)
async def put_lead_calling(
    payload: LeadCallingIn,
    request: Request,
    principal: Manager,
) -> LeadCallingOut:
    """A changed answering-machine switch reaches every live agent of the client through the
    live-apply seam, queued in the save's own transaction (D-720)."""
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    async with tenant_session(tenant_id) as session:
        plan, machine_changed = await lead_policy.save_plan(
            session,
            tenant_id=tenant_id,
            plan=LeadCallPlan(
                calling_agent_id=payload.calling_agent_id,
                wait_seconds=payload.wait_seconds,
                hours_start=payload.hours_start,
                hours_end=payload.hours_end,
                days=tuple(payload.days),
                holidays=tuple(payload.holidays),
                after_hours=payload.after_hours,
                retry_attempts=payload.retry_attempts,
                retry_interval_minutes=payload.retry_interval_minutes,
                detect_machines=payload.detect_machines,
            ),
            user_id=principal.user_id,
        )
        await write_audit(
            session,
            action="lead_calling.saved",
            actor=principal,
            tenant_id=tenant_id,
            object_type="lead_call_policy",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "after_hours": plan.after_hours,
                "retry_attempts": plan.retry_attempts,
                "detect_machines": plan.detect_machines,
            },
        )
        updating = 0
        if machine_changed:
            # The answering-machine switch is part of every agent's call settings, so the
            # save brings this client's live agents onto it in the same transaction.
            updating = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM agents WHERE status = 'live' "
                            "AND engine_agent_ref IS NOT NULL AND deleted_at IS NULL"
                        )
                    )
                ).scalar()
                or 0
            )
            await queue_live_apply(
                session,
                scope="tenant",
                tenant_id=tenant_id,
                reason="lead_calling.detect_machines",
                requested_by=principal.user_id,
            )
        return await _out(session, tenant_id, plan, agents_updated=updating)


@router.get(
    "/held",
    response_model=HeldLeadsOut,
    openapi_extra=permission_meta("org:read"),
    summary="New leads held after hours for you to release",
)
async def list_held_leads(
    session: SessionDep,
    _: Reader,
    limit: int = Query(lead_policy.MAX_HELD_PAGE, ge=1, le=lead_policy.MAX_HELD_PAGE),
) -> HeldLeadsOut:
    return HeldLeadsOut(
        items=[
            HeldLeadOut(
                id=h.id,
                lead_id=h.lead_id,
                lead_name=h.lead_name,
                agent_id=h.agent_id,
                agent_name=h.agent_name,
                source=h.source,
                held_at=h.held_at,
            )
            for h in await lead_policy.list_held(session, limit=limit)
        ]
    )


@router.post(
    "/held/{hold_id}/release",
    response_model=ReleasedOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Call a held lead now (inside your hours and the platform window)",
)
async def release_held_lead(
    hold_id: UUID,
    session: SessionDep,
    principal: Manager,
) -> ReleasedOut:
    assert principal.tenant_id is not None
    callback_id, due = await lead_policy.release_held(
        session, tenant_id=principal.tenant_id, hold_id=hold_id, user_id=principal.user_id
    )
    return ReleasedOut(callback_id=callback_id, due_at=due)


@router.post(
    "/held/{hold_id}/drop",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Do not call a held lead; the lead itself is kept",
)
async def drop_held_lead(
    hold_id: UUID,
    session: SessionDep,
    principal: Manager,
) -> None:
    await lead_policy.drop_held(session, hold_id=hold_id, user_id=principal.user_id)


__all__ = ["ALWAYS_APPLIED", "router"]

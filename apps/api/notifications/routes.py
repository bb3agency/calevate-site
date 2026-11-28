"""`/v1/notifications` — the bell's feed and its read mark (D-869).

`leads:read`, the permission of the needs-attention queue the feed is built from
(`GET /v1/attention`): the bell shows the same items, so it answers to the same readers.
Marking the feed read is the reader's own act on their own mark; an operator viewing the
account has no mark there, and the call is answered without writing one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta, role_has
from apps.api.core.settings import get_settings
from apps.api.notifications import daily_summary, preferences, service
from apps.api.notifications.preferences import AlertPreferencesIn, AlertPreferencesOut
from apps.api.notifications.service import NotificationFeedOut, SeenIn, SeenOut
from apps.api.reliability.service import enqueue_outbox_once
from apps.workers.account_closure import account_recipients
from apps.workers.whatsapp import resolve_destination

#: The audit action the switch writes, here and from Pip's `account_switch_set`.
DAILY_SUMMARY_AUDIT: Final = "organization.daily_summary_set"
ALERT_PREFERENCES_AUDIT: Final = "notification.preferences_set"
#: The worker job a "Send me a sample" queues (`apps/workers/notifications.send_alert_sample`).
SAMPLE_JOB: Final = "send_alert_sample"
#: One sample per person per channel in this many minutes; a second press is answered
#: `queued: false` rather than sending again.
SAMPLE_EVERY_MINUTES: Final = 5

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read", realm="client"))]
#: Marking the bell read writes a per-person row, so it needs a mutating permission (D-22);
#: `leads:write` is the one every client role that works the queue holds.
Worker = Annotated[Principal, Depends(requires("leads:write", realm="client"))]


@router.get(
    "",
    response_model=NotificationFeedOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The bell: needs-attention items and announcements, newest first, with unread",
)
async def get_feed(
    session: Session,
    principal: Reader,
    limit: Annotated[int, Query(ge=1, le=service.MAX_FEED)] = 30,
) -> NotificationFeedOut:
    assert principal.tenant_id is not None
    return await service.feed(
        session, tenant_id=principal.tenant_id, user_id=principal.client_user_id, limit=limit
    )


@router.post(
    "/seen",
    response_model=SeenOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Mark the bell read up to an instant (now by default)",
)
async def mark_seen(payload: SeenIn, session: Session, principal: Worker) -> SeenOut:
    assert principal.tenant_id is not None
    person = principal.client_user_id
    if person is None:
        return SeenOut(seen_through=None)
    return SeenOut(
        seen_through=await service.mark_seen(
            session, tenant_id=principal.tenant_id, user_id=person, through=payload.through
        )
    )


def _may_manage(principal: Principal) -> bool:
    return principal.role is not None and role_has(principal.role, "org:manage")


def _person(principal: Principal) -> UUID:
    person = principal.client_user_id
    if person is None:
        raise ProblemError.forbidden("Alert choices belong to a person signed in to this account.")
    return person


@router.get(
    "/preferences",
    response_model=AlertPreferencesOut,
    openapi_extra=permission_meta("leads:read"),
    summary="This person's alert table: what reaches the bell, this computer, email, WhatsApp",
)
async def get_preferences(session: Session, principal: Reader) -> AlertPreferencesOut:
    return await preferences.view(
        session, user_id=principal.client_user_id, may_manage=_may_manage(principal)
    )


@router.put(
    "/preferences",
    response_model=AlertPreferencesOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Save this person's alert table, quiet hours and daily email limit",
    description=(
        "Always-on alerts cannot be switched off (`alert_always_on`). Email, WhatsApp, quiet "
        "hours and the daily limit are the account owner's (`alert_owner_only`)."
    ),
)
async def put_preferences(
    payload: AlertPreferencesIn, session: Session, request: Request, principal: Worker
) -> AlertPreferencesOut:
    assert principal.tenant_id is not None
    person = _person(principal)
    out = await preferences.save(
        session,
        tenant_id=principal.tenant_id,
        user_id=person,
        may_manage=_may_manage(principal),
        payload=payload,
    )
    await write_audit(
        session,
        action=ALERT_PREFERENCES_AUDIT,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="user",
        object_id=str(person),
        ip=client_request_ip(request),
        summary={
            "off": str(len(payload.off)),
            "quiet_enabled": payload.quiet_enabled,
            "daily_cap": payload.daily_cap,
        },
    )
    return out


class SampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["email", "whatsapp"]


class SampleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: False when a sample on this channel was already sent in the last few minutes.
    queued: bool


@router.post(
    "/preferences/sample",
    response_model=SampleOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Send me a sample alert on one channel, marked as a sample",
    description=(
        "Email goes to the signed-in person's own address. WhatsApp goes only to the owner "
        "who agreed to WhatsApp alerts. At most one per channel every few minutes."
    ),
)
async def send_sample(payload: SampleIn, session: Session, principal: Worker) -> SampleOut:
    assert principal.tenant_id is not None
    person = _person(principal)
    bucket = int(datetime.now(UTC).timestamp() // (SAMPLE_EVERY_MINUTES * 60))
    queued = await enqueue_outbox_once(
        session,
        job=SAMPLE_JOB,
        payload={
            "tenant_id": str(principal.tenant_id),
            "user_id": str(person),
            "channel": payload.channel,
        },
        dedupe_key=f"alert-sample:{person}:{payload.channel}:{bucket}",
    )
    return SampleOut(queued=queued is not None)


class DailySummaryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    #: `evening` (around 9 pm, the day so far) or `morning` (8 am, the day before). Left out,
    #: the current choice stays.
    slot: daily_summary.Slot | None = None


class DailySummaryOut(BaseModel):
    """The owner's daily summary switch (D-944) and where it would go."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    slot: daily_summary.Slot
    #: Addresses the email goes to (owners and the billing address).
    email_addresses: int
    #: WhatsApp also carries it: our WhatsApp is switched on and the owner opted in.
    whatsapp: bool


async def _daily_summary_out(session: AsyncSession, tenant_id: UUID) -> DailySummaryOut:
    destination = await resolve_destination(session, tenant_id)
    return DailySummaryOut(
        enabled=await daily_summary.read_switch(session),
        slot=await daily_summary.read_slot(session),
        email_addresses=len(await account_recipients(session, tenant_id=tenant_id)),
        whatsapp=get_settings().whatsapp_enabled
        and destination is not None
        and destination.opt_in_at is not None,
    )


@router.get(
    "/daily-summary",
    response_model=DailySummaryOut,
    # `org:read`, like the staff-curation switch: seeing it is not deciding it (D-22).
    openapi_extra=permission_meta("org:read"),
    summary="Whether the owner's daily summary is on, and where it goes",
)
async def get_daily_summary(
    session: Session, principal: Annotated[Principal, Depends(requires("org:read"))]
) -> DailySummaryOut:
    assert principal.tenant_id is not None
    return await _daily_summary_out(session, principal.tenant_id)


@router.put(
    "/daily-summary",
    response_model=DailySummaryOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Turn the owner's daily summary on or off",
    description=(
        "Off for every account until its owner turns it on. Once a day, in the evening (the "
        "day so far) or the morning (the day before), IST, it sends calls, leads, spend and "
        "waiting call-backs by email, and by WhatsApp where the owner opted in to WhatsApp "
        "alerts."
    ),
)
async def set_daily_summary(
    payload: DailySummaryIn,
    session: Session,
    request: Request,
    principal: Annotated[Principal, Depends(requires("org:manage"))],
) -> DailySummaryOut:
    assert principal.tenant_id is not None
    changed = await daily_summary.write_switch(session, enabled=payload.enabled)
    if payload.slot is not None:
        changed = await daily_summary.write_slot(session, slot=payload.slot) or changed
    await write_audit(
        session,
        action=DAILY_SUMMARY_AUDIT,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={
            "owner_digest_enabled": payload.enabled,
            "slot": payload.slot or "unchanged",
            "changed": changed,
        },
    )
    return await _daily_summary_out(session, principal.tenant_id)


__all__ = ["ALERT_PREFERENCES_AUDIT", "DAILY_SUMMARY_AUDIT", "SAMPLE_JOB", "router"]

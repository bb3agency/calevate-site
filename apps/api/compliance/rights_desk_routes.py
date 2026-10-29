"""The rights desk (D-943): log a customer's DPDP request, see the clock, mark it answered.

    GET  /v1/compliance/rights-requests              the desk, open first by deadline
    POST /v1/compliance/rights-requests              log one (phone in the BODY, never a URL)
    POST /v1/compliance/rights-requests/{id}/close   answer or refuse it, once

`org:read` to read, `org:manage` to write, like the erasure register beside it. A request
is named by `subject_ref`, never a number; logging and closing each write an audit row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import rights_desk
from apps.api.compliance.audit import write_audit
from apps.api.compliance.models import RIGHTS_REMINDER_DAYS, RIGHTS_RESPONSE_DAYS
from apps.api.compliance.subject_phone import SubjectPhone
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/rights-requests", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
DeskReader = Annotated[Principal, Depends(requires("org:read"))]
DeskWriter = Annotated[Principal, Depends(requires("org:manage"))]

Kind = Literal["access", "correction", "erasure", "nomination", "grievance"]
Channel = Literal["phone", "email", "whatsapp", "letter", "in_person", "other"]
Outcome = Literal[
    "exported",
    "erased",
    "corrected",
    "nominated",
    "explained",
    "identity_not_confirmed",
    "not_held",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RightsRequestIn(Strict):
    kind: Kind
    channel: Channel
    phone: SubjectPhone
    #: When the person asked. Empty: now. The 90 days run from here.
    received_at: datetime | None = None


class RightsRequestCloseIn(Strict):
    status: Literal["answered", "refused"]
    outcome: Outcome
    #: The erasure that answered an erasure request (its `request_id`).
    deletion_request_id: UUID | None = None


class RightsRequestOut(Strict):
    id: UUID
    kind: Kind
    channel: Channel
    subject_ref: str
    received_at: datetime
    due_at: datetime
    status: Literal["open", "answered", "refused"]
    outcome: Outcome | None
    closed_at: datetime | None
    deletion_request_id: UUID | None
    #: Whole days to the deadline; negative once passed. Open requests only.
    days_left: int | None
    due_soon: bool
    overdue: bool


class RightsDeskOut(Strict):
    items: list[RightsRequestOut]
    open: int
    due_soon: int
    overdue: int
    #: The response window and the reminder lead, so the screen never hard-codes either.
    response_days: int
    reminder_days: int


def _out(request: rights_desk.RightsRequest, now: datetime) -> RightsRequestOut:
    is_open = request.status == "open"
    return RightsRequestOut.model_validate(
        {
            "id": request.id,
            "kind": request.kind,
            "channel": request.channel,
            "subject_ref": request.subject_ref,
            "received_at": request.received_at,
            "due_at": request.due_at,
            "status": request.status,
            "outcome": request.outcome,
            "closed_at": request.closed_at,
            "deletion_request_id": request.deletion_request_id,
            "days_left": request.days_left(now) if is_open else None,
            "due_soon": request.due_soon(now),
            "overdue": is_open and request.due_at <= now,
        }
    )


@router.get(
    "",
    response_model=RightsDeskOut,
    openapi_extra=permission_meta("org:read"),
    summary="Your customers' data requests and the 90-day clock on each",
)
async def list_rights_requests(
    session: Session,
    _: DeskReader,
    limit: int = Query(default=100, ge=1, le=rights_desk.MAX_LIST),
) -> RightsDeskOut:
    now = datetime.now(UTC)
    counts = await rights_desk.counts(session)
    return RightsDeskOut(
        items=[_out(r, now) for r in await rights_desk.list_requests(session, limit=limit)],
        open=counts.open,
        due_soon=counts.due_soon,
        overdue=counts.overdue,
        response_days=RIGHTS_RESPONSE_DAYS,
        reminder_days=RIGHTS_REMINDER_DAYS,
    )


@router.post(
    "",
    response_model=RightsRequestOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Log a customer's request to see, correct or erase their data",
)
async def log_rights_request(
    payload: RightsRequestIn, session: Session, request: Request, principal: DeskWriter
) -> RightsRequestOut:
    assert principal.tenant_id is not None
    logged = await rights_desk.log_request(
        session,
        tenant_id=principal.tenant_id,
        kind=payload.kind,
        channel=payload.channel,
        phone_e164=payload.phone,
        received_at=payload.received_at,
        created_by=principal.client_user_id,
    )
    await write_audit(
        session,
        action="dpdp.rights_request_logged",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="data_subject",
        object_id=logged.subject_ref,
        ip=client_request_ip(request),
        summary={"request_id": str(logged.id), "kind": logged.kind, "channel": logged.channel},
    )
    return _out(logged, datetime.now(UTC))


@router.post(
    "/{request_id}/close",
    response_model=RightsRequestOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Mark a data request answered or refused",
)
async def close_rights_request(
    request_id: UUID,
    payload: RightsRequestCloseIn,
    session: Session,
    request: Request,
    principal: DeskWriter,
) -> RightsRequestOut:
    assert principal.tenant_id is not None
    closed = await rights_desk.close_request(
        session,
        request_id=request_id,
        status=payload.status,
        outcome=payload.outcome,
        deletion_request_id=payload.deletion_request_id,
        closed_by=principal.client_user_id,
    )
    await write_audit(
        session,
        action="dpdp.rights_request_closed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="data_subject",
        object_id=closed.subject_ref,
        ip=client_request_ip(request),
        summary={
            "request_id": str(closed.id),
            "status": closed.status,
            "outcome": closed.outcome or "",
        },
    )
    return _out(closed, datetime.now(UTC))


__all__ = ["router"]

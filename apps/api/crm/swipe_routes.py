"""The routes behind the phone swipe and the desktop ⋯ menu (D-869). `crm/swipe.py` says
which existing routes the other actions use and why.

Permissions follow the siblings: marking a call is `leads:write` (the call list's own edit,
the same holder as a lead's status); scheduling a call and sending a message are
`leads:dispatch`, the permission that governs causing a call to be placed, with an
`Idempotency-Key` REQUIRED because each rings a phone or delivers a message that cannot be
taken back. Every change is audited.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import swipe
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

router = APIRouter(prefix="/v1", tags=["crm"])

Session = Annotated[AsyncSession, Depends(db)]
Writer = Annotated[Principal, Depends(requires("leads:write"))]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
Reader = Annotated[Principal, Depends(requires("leads:read"))]

SCHEDULE_ROUTE = "/v1/leads/{lead_id}/callbacks"
WHATSAPP_ROUTE = "/v1/leads/{lead_id}/whatsapp"


def _require_key(request: Request, what: str) -> str:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ProblemError(
            kind="validation",
            status=400,
            code="idempotency_key_required",
            title=f"{what} needs an Idempotency-Key header",
            detail="A repeat of the same attempt is answered rather than done twice.",
            remediation="Send an `Idempotency-Key` header — one fresh value per attempt.",
        )
    return key


async def _release(tenant_id: UUID, record_id: UUID) -> None:
    async with tenant_session(tenant_id) as fail_session:
        await fail_idempotency(fail_session, record_id=record_id)


@router.put(
    "/calls/{call_id}/follow-up",
    response_model=swipe.CallFollowUpOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Mark a call resolved or needs-you, or clear the mark (undo with expected_state)",
)
async def put_call_follow_up(
    call_id: UUID,
    payload: swipe.CallFollowUpIn,
    session: Session,
    principal: Writer,
    request: Request,
) -> swipe.CallFollowUpOut:
    out = await swipe.set_call_follow_up(
        session,
        call_id,
        state=payload.state,
        expected=("expected_state" in payload.model_fields_set, payload.expected_state),
        user_id=principal.client_user_id,
    )
    if out.changed:
        await write_audit(
            session,
            action="call.follow_up_marked",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="call",
            object_id=str(call_id),
            ip=client_request_ip(request),
            summary={"state": out.state, "previous": out.previous_state},
        )
    return out


@router.post(
    "/leads/{lead_id}/callbacks",
    response_model=swipe.ScheduleCallbackOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Call this lead back at a chosen time, 09:00-21:00 IST — gated, idempotent",
)
async def schedule_callback(
    lead_id: UUID,
    payload: swipe.ScheduleCallbackIn,
    session: Session,
    principal: Dispatcher,
    request: Request,
) -> swipe.ScheduleCallbackOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    key = _require_key(request, "Scheduling a call")
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=SCHEDULE_ROUTE,
            method="POST",
            key=key,
            request_hash=body_hash({"lead_id": str(lead_id), **payload.model_dump(mode="json")}),
        )
    if claim.state == "replay" and claim.response_payload:
        return swipe.ScheduleCallbackOut.model_validate(claim.response_payload)
    try:
        out = await swipe.schedule_lead_callback(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            at=payload.at,
            note=payload.note,
            agent_id=payload.agent_id,
        )
        if out.status == "scheduled":
            await write_audit(
                session,
                action="lead.callback_scheduled",
                actor=principal,
                tenant_id=tenant_id,
                object_type="lead",
                object_id=str(lead_id),
                ip=client_request_ip(request),
                summary={
                    "callback_id": str(out.callback_id),
                    "at": payload.at.isoformat(),
                    "rescheduled": out.rescheduled,
                    "has_note": bool(payload.note),
                },
            )
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=out.model_dump(mode="json"),
        )
    except Exception:
        await _release(tenant_id, claim.record_id)
        raise
    return out


@router.get(
    "/leads/{lead_id}/whatsapp",
    response_model=swipe.WhatsAppOptionsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Can this lead be sent a WhatsApp follow-up now, and with which approved messages",
)
async def whatsapp_options(
    lead_id: UUID,
    session: Session,
    principal: Reader,
    agent_id: Annotated[
        UUID | None, Query(description="The agent the gate asks as; see `contact_agent`.")
    ] = None,
) -> swipe.WhatsAppOptionsOut:
    assert principal.tenant_id is not None
    return await swipe.whatsapp_options(
        session, tenant_id=principal.tenant_id, lead_id=lead_id, agent_id=agent_id
    )


@router.post(
    "/leads/{lead_id}/whatsapp",
    response_model=swipe.WhatsAppSendOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Send an approved WhatsApp message to this lead — consent-gated, idempotent",
)
async def send_whatsapp(
    lead_id: UUID,
    payload: swipe.WhatsAppSendIn,
    session: Session,
    principal: Dispatcher,
    request: Request,
) -> swipe.WhatsAppSendOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    key = _require_key(request, "Sending a WhatsApp message")
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=WHATSAPP_ROUTE,
            method="POST",
            key=key,
            request_hash=body_hash({"lead_id": str(lead_id), **payload.model_dump(mode="json")}),
        )
    if claim.state == "replay" and claim.response_payload:
        return swipe.WhatsAppSendOut.model_validate(claim.response_payload)
    try:
        out, template = await swipe.send_whatsapp_follow_up(
            session, tenant_id=tenant_id, lead_id=lead_id, payload=payload
        )
    except Exception:
        await _release(tenant_id, claim.record_id)
        raise
    # From here a message may have been delivered: the claim is completed, never released,
    # so a retry of this key is answered rather than sent again.
    await swipe.record_whatsapp_on_timeline(
        session, lead_id=lead_id, template=template, out=out, actor=str(principal.user_id)
    )
    await write_audit(
        session,
        action="lead.whatsapp_follow_up",
        actor=principal,
        tenant_id=tenant_id,
        object_type="lead",
        object_id=str(lead_id),
        ip=client_request_ip(request),
        summary={"status": out.status, "rule": out.rule, "template": template},
    )
    await complete_idempotency(
        session,
        record_id=claim.record_id,
        response_status=200,
        response_payload=out.model_dump(mode="json"),
    )
    return out


__all__ = ["SCHEDULE_ROUTE", "WHATSAPP_ROUTE", "router"]

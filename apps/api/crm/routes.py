"""Client-realm CRM endpoints (SURFACES §2).

Every route declares its permission twice on purpose: once as a dependency that
ENFORCES it, once in `openapi_extra` that DOCUMENTS it. The boot assertion
(`assert_policy_registry_complete`) reads the second and fails startup if a route
forgot — so a new endpoint cannot ship silently unguarded (BACKEND-PATTERNS §7).

Three routes here touch the compliance/PII rules directly and are commented in place:
raw transcript, recording link, and "call this lead".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import service as billing
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import service
from apps.api.crm.attention import attention_queue
from apps.api.crm.performance import performance
from apps.api.crm.schemas import (
    CallbackEligibilityOut,
    CallbackOut,
    CallDetailOut,
    CallLeadIn,
    CallLeadOut,
    CallSummaryOut,
    DashboardOut,
    LeadListOut,
    LeadOut,
    LeadUpdateIn,
    RecordingLinkOut,
)
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    scope_key,
)

router = APIRouter(prefix="/v1", tags=["crm"])

Session = Annotated[AsyncSession, Depends(db)]


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Headline numbers for the client dashboard",
)
async def get_dashboard(
    session: Session, _: Principal = Depends(requires("calls:read"))
) -> DashboardOut:
    return await service.dashboard(session)


@router.get(
    "/calls",
    response_model=list[CallSummaryOut],
    openapi_extra=permission_meta("calls:read"),
)
async def get_calls(
    session: Session,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    agent_id: UUID | None = None,
    _: Principal = Depends(requires("calls:read")),
) -> list[CallSummaryOut]:
    return await service.list_calls(
        session, limit=limit, offset=offset, status=status, agent_id=agent_id
    )


@router.get(
    "/calls/{call_id}",
    response_model=CallDetailOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Call detail — transcript is REDACTED by default (hard rule 5)",
)
async def get_call(
    call_id: UUID, session: Session, _: Principal = Depends(requires("calls:read"))
) -> CallDetailOut:
    return await service.get_call(session, call_id, raw=False)


@router.get(
    "/calls/{call_id}/transcript/raw",
    response_model=CallDetailOut,
    openapi_extra=permission_meta("calls:read_raw"),
    summary="Unredacted transcript — role-checked AND audit-logged on every read",
)
async def get_raw_transcript(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> CallDetailOut:
    # The audit row is written in the SAME transaction as the read, so there is no
    # window in which someone saw raw PII without it being recorded (hard rule 5).
    await write_audit(
        session,
        action="transcript.read_raw",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=request.client.host if request.client else None,
    )
    return await service.get_call(session, call_id, raw=True)


@router.get(
    "/calls/{call_id}/recording",
    response_model=RecordingLinkOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Short-lived presigned link to OUR copy of the recording",
)
async def get_recording(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read")),
) -> RecordingLinkOut:
    key = await service.recording_key_for(session, call_id)
    await write_audit(
        session,
        action="recording.read",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=request.client.host if request.client else None,
    )
    # Imported here, not at module scope: the presigner lives in the workers package
    # and pulling boto3 into every API import would slow cold starts for one route.
    from apps.workers.storage import PRESIGN_TTL_S, presigned_url

    url = presigned_url(key)
    if url is None:
        raise ProblemError(
            kind="dependency",
            code="recording_unavailable",
            title="Recording unavailable",
            detail="The recording could not be retrieved right now.",
        )
    return RecordingLinkOut(url=url, expires_in_s=PRESIGN_TTL_S)


@router.get("/leads", response_model=LeadListOut, openapi_extra=permission_meta("leads:read"))
async def get_leads(
    session: Session,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    search: str | None = Query(None, max_length=60),
    agent_id: UUID | None = None,
    _: Principal = Depends(requires("leads:read")),
) -> LeadListOut:
    items, total = await service.list_leads(
        session, limit=limit, offset=offset, status=status, search=search
    )
    return LeadListOut(
        items=items,
        # Columns travel with the rows so the frontend never hard-codes a client's
        # fields (TRD §7 (c)).
        columns=await service.lead_columns(session, agent_id),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/leads/export.csv",
    openapi_extra=permission_meta("leads:read"),
    summary="CSV export — full phone numbers, audit-logged",
    response_class=Response,
)
async def export_leads(
    session: Session,
    request: Request,
    agent_id: UUID | None = None,
    principal: Principal = Depends(requires("leads:read")),
) -> Response:
    csv_body = await service.export_leads_csv(session, agent_id=agent_id)
    # An export leaves our redaction behind (SEC-COMP §4 says redaction runs BEFORE any
    # transcript leaves the system — a lead export is contact data, not transcript, and
    # is the client's own data — so it is audited rather than masked).
    await write_audit(
        session,
        action="leads.export",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead_export",
        ip=request.client.host if request.client else None,
    )
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@router.get("/leads/{lead_id}", response_model=LeadOut, openapi_extra=permission_meta("leads:read"))
async def get_lead(
    lead_id: UUID, session: Session, _: Principal = Depends(requires("leads:read"))
) -> LeadOut:
    return await service.get_lead(session, lead_id)


@router.patch(
    "/leads/{lead_id}", response_model=LeadOut, openapi_extra=permission_meta("leads:write")
)
async def patch_lead(
    lead_id: UUID,
    payload: LeadUpdateIn,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> LeadOut:
    return await service.update_lead(
        session,
        lead_id,
        status=payload.status,
        name=payload.name,
        actor=str(principal.user_id),
    )


@router.post(
    "/leads/{lead_id}/call",
    response_model=CallLeadOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Dispatch one AI call to this lead (D-21) — compliance-gated, idempotent",
)
async def call_lead(
    lead_id: UUID,
    payload: CallLeadIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CallLeadOut:
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session

    # Idempotency: a double-click must not place two calls to a customer. The key is
    # required here precisely because the side effect is a real phone ringing.
    idem_key = request.headers.get("Idempotency-Key")
    claim = None
    if idem_key:
        claim = await claim_idempotency(
            session,
            scope=scope_key(tenant_id=principal.tenant_id, user_id=principal.user_id),
            route="/v1/leads/{lead_id}/call",
            method="POST",
            key=idem_key,
            request_hash=body_hash({"lead_id": str(lead_id), **payload.model_dump()}),
        )
        if claim.state == "replay" and claim.response_payload:
            return CallLeadOut.model_validate(claim.response_payload)

    phone, name = await service.lead_phone(session, lead_id)

    # THE COMPLIANCE GATE. D-21 is explicit that client-initiated dispatch runs the
    # same pre-checks as webhook dispatch; a decision (not an exception) comes back so
    # the UI can explain WHY the button is refusing (SURFACES §2b).
    decision = await check_dispatch(
        session, tenant_id=principal.tenant_id, agent_id=payload.agent_id, phone_e164=phone
    )
    if not decision.allowed:
        result = CallLeadOut(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        if claim is not None:
            await complete_idempotency(
                session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=result.model_dump(),
            )
        return result

    from apps.api.agents.service import dispatch_call

    handle = await dispatch_call(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        lead_id=lead_id,
        phone_e164=phone,
        lead_name=name,
        context_note=payload.context_note,
    )
    await write_audit(
        session,
        action="lead.call_dispatched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead",
        object_id=str(lead_id),
        ip=request.client.host if request.client else None,
        summary={"agent_id": str(payload.agent_id), "has_note": bool(payload.context_note)},
    )
    result = CallLeadOut(status="queued", call_handle=handle)
    if claim is not None:
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(),
        )
    return result


@router.get(
    "/performance",
    openapi_extra=permission_meta("calls:read"),
    summary="Connect rate, funnel, outcomes, busiest hours IST (teardown §5 floor)",
)
async def performance_panel(
    session: Session,
    days: int = 30,
    _: Principal = Depends(requires("calls:read")),
) -> dict[str, Any]:
    return await performance(session, days=days)


@router.get(
    "/attention",
    openapi_extra=permission_meta("leads:read"),
    summary="Everything that stopped, and what to do about it (SURFACES §2b)",
)
async def attention(
    session: Session,
    # Validated here rather than clamped in the service: an out-of-range limit is a bad
    # request, and `min(limit, 100)` turns a negative one into a silently short queue.
    limit: int = Query(50, ge=1, le=100),
    _: Principal = Depends(requires("leads:read")),
) -> dict[str, Any]:
    """`leads:read`, not an owner permission: staff work this queue — it is the daily
    operational surface, and gating it on billing-grade permissions would put the work
    on the one person least likely to be doing it."""
    return await attention_queue(session, limit=min(limit, 100))


@router.get(
    "/usage",
    openapi_extra=permission_meta("billing:read"),
    summary="This month's usage and what it costs (SURFACES §2b)",
)
async def usage_panel(
    session: Session,
    month: str | None = None,
    principal: Principal = Depends(requires("billing:read")),
) -> dict[str, Any]:
    """`billing:read`, which staff do not have (SEC-COMP §5) — spend is an owner's
    business. Our supplier cost never appears here; that is the admin margin panel."""
    assert principal.tenant_id is not None
    summary = await billing.usage_summary(session, tenant_id=principal.tenant_id, month=month)
    balance = await billing.get_balance(session, tenant_id=principal.tenant_id)
    tier = await billing.plan_tier_of(session, principal.tenant_id)
    return {
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
        "plan_tier": tier,
        # Credits only mean something for the self-serve motion (D-34); showing a
        # managed client a ₹0 wallet would invite a support ticket about a concept
        # that does not apply to them.
        "credit_balance_inr": str(balance.amount_inr) if tier in ("self_serve", "trial") else None,
    }


@router.get(
    "/calls/{call_id}/callback",
    response_model=CallbackEligibilityOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Whether this call may be followed up, and why not (D-21)",
)
async def callback_eligibility(
    call_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CallbackEligibilityOut:
    """A GET so the button renders disabled-with-a-reason on page load.

    Both the eligibility rules AND the compliance gate are evaluated, because a call
    that is eligible on our rules can still be un-dialable right now (outside calling
    hours, DNC, spend cap) — and "the button is greyed out and I do not know why" is
    the exact failure SURFACES §2b exists to prevent.
    """
    assert principal.tenant_id is not None
    try:
        plan = await service.plan_callback(session, call_id)
    except ProblemError as problem:
        if problem.kind != "business_rule":
            raise
        return CallbackEligibilityOut(eligible=False, reason=problem.detail, rule=problem.code)

    decision = await check_dispatch(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        phone_e164=plan.phone_e164,
    )
    if not decision.allowed:
        return CallbackEligibilityOut(eligible=False, reason=decision.reason, rule=decision.rule)
    return CallbackEligibilityOut(eligible=True, follow_up_number=plan.depth + 1)


@router.post(
    "/calls/{call_id}/callback",
    response_model=CallbackOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="AI callback with prior-call context (D-21) — same gate, bounded chain",
)
async def call_back(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CallbackOut:
    """Re-dispatch the same agent to the same lead, carrying what happened last time.

    Idempotency keys off the CALL, not a client-supplied header: the natural key for
    "follow up this call" is the call itself, and a double-click must not ring a
    customer twice even from two browser tabs.
    """
    assert principal.tenant_id is not None
    plan = await service.plan_callback(session, call_id)

    claim = await claim_idempotency(
        session,
        scope=scope_key(tenant_id=principal.tenant_id, user_id=principal.user_id),
        route="/v1/calls/{call_id}/callback",
        method="POST",
        key=str(call_id),
        request_hash=body_hash({"call_id": str(call_id)}),
    )
    if claim.state == "replay" and claim.response_payload:
        return CallbackOut.model_validate(claim.response_payload)

    decision = await check_dispatch(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        phone_e164=plan.phone_e164,
    )
    if not decision.allowed:
        result = CallbackOut(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(),
        )
        return result

    from apps.api.agents.service import dispatch_call

    handle = await dispatch_call(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        lead_id=plan.lead_id,
        phone_e164=plan.phone_e164,
        lead_name=plan.lead_name,
        context_note=plan.context_note,
    )
    await service.link_callback(session, handle=handle, parent_call_id=call_id)
    await write_audit(
        session,
        action="call.callback_dispatched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=request.client.host if request.client else None,
        summary={"follow_up_number": plan.depth + 1},
    )
    result = CallbackOut(status="queued", call_handle=handle, follow_up_number=plan.depth + 1)
    await complete_idempotency(
        session,
        record_id=claim.record_id,
        response_status=200,
        response_payload=result.model_dump(),
    )
    return result


__all__ = ["router"]

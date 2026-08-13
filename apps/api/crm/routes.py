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
from typing import Annotated
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
    AttentionOut,
    CallbackEligibilityOut,
    CallbackOut,
    CallDetailOut,
    CallLeadIn,
    CallLeadOut,
    CallSummaryOut,
    DashboardOut,
    LeadListOut,
    LeadOut,
    LeadTimelineOut,
    LeadUpdateIn,
    PerformanceOut,
    RecordingLinkOut,
    UsagePanelOut,
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
    # "My leads", as a real predicate on a real column. A UUID rather than a `me`
    # literal, for two reasons: the same parameter then answers "show me Priya's leads"
    # off the owner column without a second spelling, and `me` would have to mean
    # something for an admin viewing this account through D-22 impersonation, whose
    # `principal.user_id` is an `admin_users` row that can own no lead. The screen sends
    # its own id from `/v1/me` and says so where the control is.
    assigned_to: UUID | None = None,
    _: Principal = Depends(requires("leads:read")),
) -> LeadListOut:
    # `agent_id` filters the ROWS as well as choosing the columns. It used to do only
    # the latter, which meant this route and the export disagreed about what the same
    # query parameter meant, and a two-agent tenant read one agent's leads under the
    # other's capture list. See `service._lead_scope` for the reasoning.
    page = await service.list_leads_page(
        session,
        limit=limit,
        offset=offset,
        status=status,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
    )
    return LeadListOut(
        items=page.items,
        # Columns travel with the rows so the frontend never hard-codes a client's
        # fields (TRD §7 (c)).
        columns=await service.lead_columns(session, agent_id),
        total=page.total,
        limit=limit,
        offset=offset,
        status_counts_matching_search=page.status_counts,
    )


@router.get(
    "/leads/export.csv",
    # `calls:read_raw`, NOT `leads:read`. This is the one route where a client's contact
    # list leaves us with FULL phone numbers, and the redaction guardrail exempts it on
    # the stated grounds that it is role-gated and audited. `leads:read` is held by
    # `staff` — so the "role gate" was every logged-in employee, and the exemption was
    # describing a control that did not exist. `calls:read_raw` is the permission that
    # already means "you may see the unmasked artefact, and your having seen it is
    # recorded": owner in the client realm, superadmin in ours, never staff.
    openapi_extra=permission_meta("calls:read_raw"),
    summary="CSV export — full phone numbers, owner-only and audit-logged",
    response_class=Response,
)
async def export_leads(
    session: Session,
    request: Request,
    agent_id: UUID | None = None,
    # The SAME three filters `GET /v1/leads` takes, with the same meanings, so "export
    # what I am looking at" is expressible. It accepted `agent_id` alone, so a client
    # who filtered the table to `hot` and pressed Export downloaded every contact in the
    # account with full numbers — the widest possible read of the narrowest possible
    # request. Widening the filters does NOT widen the gate: this stays `calls:read_raw`
    # and stays audited, and a narrower request is not a cheaper permission.
    status: str | None = None,
    search: str | None = Query(None, max_length=60),
    # The fourth, added in the same change that added it to the list rather than a
    # release later — that gap is exactly how the status/search divergence above
    # happened, and it is the one route where the gap ships full phone numbers.
    assigned_to: UUID | None = None,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> Response:
    csv_body = await service.export_leads_csv(
        session, agent_id=agent_id, status=status, search=search, assigned_to=assigned_to
    )
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
        # WHAT was taken, now that it can vary. "Exported four hot leads" and "exported
        # the entire account" were the same audit row while `agent_id` was the only
        # filter; they are the two ends of an incident and the record should tell them
        # apart. `search` is recorded as a BOOLEAN and never as text — hard rule 6, and
        # the search box accepts a phone suffix.
        summary={
            "status": status,
            "agent_id": str(agent_id) if agent_id else None,
            "searched": bool(search),
            # An id, not a name (hard rule 6 logs ids) — and recorded for the same
            # reason `status` is: "exported my own eight leads" and "exported the
            # account" must not be the same audit row.
            "assigned_to": str(assigned_to) if assigned_to else None,
            "rows": max(csv_body.count("\n") - 1, 0),
        },
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
    "/leads/{lead_id}",
    response_model=LeadOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Edit one lead — status, name, and who owns it",
)
async def patch_lead(
    lead_id: UUID,
    payload: LeadUpdateIn,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> LeadOut:
    """Assignment rides on THIS route rather than on a `PUT /leads/{id}/assignee`.

    The choice was between one route that edits a lead and a second route that edits
    one of its fields, and "one way per problem" decides it: the status select and the
    assignee select sit in the same table row, need the same `leads:write`, and want
    the same cache invalidation — two endpoints would be two mutations, two hooks and
    two places for the next editable field to be added to the wrong one. `staff` holds
    `leads:write` deliberately (core/rbac.py): assignment is how a team divides work,
    not an owner-only setting.

    The one thing a shared PATCH costs is the null: `"assigned_to": null` must mean
    "unassign" while an ABSENT `assigned_to` means "leave the owner alone", and both
    arrive as `None` on the model. Pydantic v2's `model_fields_set` holds exactly the
    fields the request supplied, so it is what tells them apart
    (pydantic.dev/docs/validation/latest/concepts/models). `AssigneeChange` carries the
    answer onward as a value rather than as a second boolean parameter, so the service
    cannot read the two cases the same way by accident.
    """
    return await service.update_lead(
        session,
        lead_id,
        status=payload.status,
        name=payload.name,
        assignee=(
            service.AssigneeChange(user_id=payload.assigned_to)
            if "assigned_to" in payload.model_fields_set
            else None
        ),
        actor=str(principal.user_id),
    )


@router.get(
    "/leads/{lead_id}/timeline",
    response_model=LeadTimelineOut,
    # `leads:read`, and it has to be: D-22 refuses every MUTATING permission to a
    # read-only impersonating admin, so gating a lead's history on `leads:write` would
    # hide it from support at the exact moment support is looking
    # (`tests/impersonation_reads_test.py` asserts the rule over the whole route table).
    # Reading what happened to a lead is not the authority to change it.
    openapi_extra=permission_meta("leads:read"),
    summary="What happened to this lead, newest first — projected, never the raw payload",
)
async def lead_timeline(
    lead_id: UUID,
    session: Session,
    limit: int = Query(50, ge=1, le=service.MAX_TIMELINE_PAGE),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(requires("leads:read")),
) -> LeadTimelineOut:
    """The record existed and nobody could read it.

    `lead_events` is written by six producers across three deployables — the status
    change, the blocked dial, each call, each hot-lead alert, each WhatsApp attempt,
    each spent campaign ladder — and until now the only reader was the aggregate
    needs-attention query. "We called them twice, the WhatsApp was refused, the campaign
    gave up" was on record and invisible to the person it is about.

    Bounded rather than unbounded, and the bound is stated in the response: `limit` is
    validated HERE (1..100) rather than clamped in the service, for the reason
    `/v1/attention` gives — `min(limit, 100)` turns a negative limit into a silently
    short page instead of into a bad request.
    """
    return await service.lead_timeline(session, lead_id, limit=limit, offset=offset)


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
    response_model=PerformanceOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Connect rate, funnel, outcomes, busiest hours IST (teardown §5 floor)",
)
async def performance_panel(
    session: Session,
    days: int = 30,
    _: Principal = Depends(requires("calls:read")),
) -> PerformanceOut:
    # `model_validate`, not a passthrough: the model is `extra="forbid"`, so a key the
    # service grows without the schema growing with it fails HERE, loudly, instead of
    # reaching a browser as a field no generated type knows about.
    return PerformanceOut.model_validate(await performance(session, days=days))


@router.get(
    "/attention",
    response_model=AttentionOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Everything that stopped, and what to do about it (SURFACES §2b)",
)
async def attention(
    session: Session,
    # Validated here rather than clamped in the service: an out-of-range limit is a bad
    # request, and `min(limit, 100)` turns a negative one into a silently short queue.
    limit: int = Query(50, ge=1, le=100),
    _: Principal = Depends(requires("leads:read")),
) -> AttentionOut:
    """`leads:read`, not an owner permission: staff work this queue — it is the daily
    operational surface, and gating it on billing-grade permissions would put the work
    on the one person least likely to be doing it."""
    return AttentionOut.model_validate(await attention_queue(session, limit=min(limit, 100)))


@router.get(
    "/usage",
    response_model=UsagePanelOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This month's usage and what it costs (SURFACES §2b)",
)
async def usage_panel(
    session: Session,
    month: str | None = None,
    principal: Principal = Depends(requires("billing:read")),
) -> UsagePanelOut:
    """`billing:read`, which staff do not have (SEC-COMP §5) — spend is an owner's
    business. Our supplier cost never appears here; that is the admin margin panel."""
    assert principal.tenant_id is not None
    summary = await billing.usage_summary(session, tenant_id=principal.tenant_id, month=month)
    balance = await billing.get_balance(session, tenant_id=principal.tenant_id)
    tier = await billing.plan_tier_of(session, principal.tenant_id)
    return UsagePanelOut.model_validate(
        {
            # Decimal → string, never float (hard rule 7). The model declares each of
            # these `str` for the same reason.
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
            "plan_tier": tier,
            # Credits only mean something for the self-serve motion (D-34); showing a
            # managed client a ₹0 wallet would invite a support ticket about a concept
            # that does not apply to them.
            "credit_balance_inr": (
                str(balance.amount_inr) if tier in ("self_serve", "trial") else None
            ),
        }
    )


@router.get(
    "/calls/{call_id}/callback",
    response_model=CallbackEligibilityOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Whether this call may be followed up, and why not (D-21)",
)
async def callback_eligibility(
    call_id: UUID,
    session: Session,
    # `leads:read`, not `leads:dispatch`: this endpoint exists so a button can
    # render disabled WITH A REASON, and `leads:dispatch` is mutating, so D-22 hid
    # the reason from anyone viewing a client read-only. The POST that actually
    # places the call keeps `leads:dispatch` — reading why you cannot dial is not
    # the authority to dial.
    principal: Principal = Depends(requires("leads:read")),
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

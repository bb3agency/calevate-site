"""`/v1/forwarding` — the client's existing number forwarded to its Calevate number (D-746),
and `/v1/admin/forwarding` — the same, read by an operator.

Writes are `org:manage` (the owner, or an operator in the client's account). Adding a number
is also a personal confirmation that it is the business's own, which only a person of the
business can give (`service._attesting_user`); the test call may only ever dial a number so
confirmed.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import ClientActionCode, client_confirmation
from apps.api.db.session import tenant_session
from apps.api.forwarding import codes, save_number, service, testing
from apps.api.forwarding.models import MAX_LINES
from apps.api.forwarding.schemas import (
    AdminForwardingOut,
    CalevateNumberOut,
    CarrierGuideOut,
    CodeOut,
    CodeSetOut,
    CodesOut,
    ForwardingOut,
    ForwardingTestOut,
    LineChangeIn,
    LineIn,
    LineOut,
    SaveNumberIn,
    SaveNumberOut,
)

router = APIRouter(prefix="/v1/forwarding", tags=["forwarding"])
admin_router = APIRouter(prefix="/v1/admin/forwarding", tags=["admin"])

Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Writer = Annotated[Principal, Depends(requires("org:manage"))]
#: The client's own sign-in only: a view-as session is refused with
#: `impersonation_not_available_here` (adding a number is a personal confirmation, and the
#: test places a real call).
OwnWriter = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
ConfirmAction = Annotated[str | None, Header(alias="X-Confirm-Action")]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: How many past tests a screen shows.
MAX_TESTS_PAGE = 20
#: The client confirmation verbs (`<verb>:<org slug>`, D-730).
ADD_ACTION = "add_forwarded_number"
TEST_ACTION = "forwarding_test"
SAVE_NUMBER_ACTION = "save_number_message"


def _line_out(line: service.LineView) -> LineOut:
    return LineOut(
        id=line.id,
        e164=line.e164,
        line_kind=line.line_kind,  # type: ignore[arg-type]
        carrier=line.carrier,  # type: ignore[arg-type]
        mode=line.mode,  # type: ignore[arg-type]
        ring_seconds=line.ring_seconds,
        calevate_number_id=line.calevate_number_id,
        calevate_number_e164=line.calevate_number_e164,
        status=line.status,  # type: ignore[arg-type]
        attested_at=line.attested_at,
        last_tested_at=line.last_tested_at,
        caller_id_finding=line.caller_id_finding,  # type: ignore[arg-type]
        concurrency_finding=line.concurrency_finding,  # type: ignore[arg-type]
        last_test_outcome=line.last_test_outcome,  # type: ignore[arg-type]
        quiet_since=line.quiet_since,
    )


def _test_out(view: testing.ForwardingTestView) -> ForwardingTestOut:
    return ForwardingTestOut(
        id=view.id,
        line_id=view.line_id,
        status=view.status,  # type: ignore[arg-type]
        outcome=view.outcome,  # type: ignore[arg-type]
        legs_placed=view.legs_placed,
        caller_id_finding=view.caller_id_finding,  # type: ignore[arg-type]
        concurrency_finding=view.concurrency_finding,  # type: ignore[arg-type]
        failure_code=view.failure_code,
        created_at=view.created_at,
        settled_at=view.settled_at,
    )


@router.get(
    "",
    response_model=ForwardingOut,
    summary="Your existing numbers, how they forward, and whether the forward works",
    openapi_extra=permission_meta("org:read"),
)
async def get_forwarding(session: Session, principal: Reader) -> ForwardingOut:
    lines = await service.list_lines(session)
    numbers = await service.calevate_numbers(session)
    return ForwardingOut(
        lines=[_line_out(line) for line in lines],
        calevate_numbers=[
            CalevateNumberOut(id=n.id, e164=n.e164, answering=n.answering) for n in numbers
        ],
        testing_available=testing.forwarding_calls_ready(),
        concurrency_testable=get_settings().forwarding_test_second_number is not None,
        max_lines=MAX_LINES,
    )


@router.post(
    "/lines",
    response_model=LineOut,
    status_code=201,
    summary="Add the number your callers already know, confirming it is your business's",
    openapi_extra=permission_meta("org:manage"),
)
async def add_line(
    payload: LineIn,
    session: Session,
    principal: OwnWriter,
    request: Request,
    code: ClientActionCode,
    x_confirm_action: ConfirmAction = None,
) -> LineOut:
    # A code typed for this act: the number becomes one our test call may ring.
    await code.require(x_confirm_action, client_confirmation(request, ADD_ACTION))
    assert principal.tenant_id is not None
    line = await service.create_line(
        session,
        principal=principal,
        tenant_id=principal.tenant_id,
        number=payload.number,
        line_kind=payload.line_kind,
        carrier=payload.carrier,
        mode=payload.mode,
        ring_seconds=payload.ring_seconds,
        calevate_number_id=payload.calevate_number_id,
        attest=payload.attest,
        ip=client_request_ip(request),
    )
    return _line_out(line)


@router.patch(
    "/lines/{line_id}",
    response_model=LineOut,
    summary="Change how an existing number forwards",
    openapi_extra=permission_meta("org:manage"),
)
async def change_line(
    line_id: UUID, payload: LineChangeIn, session: Session, principal: Writer, request: Request
) -> LineOut:
    assert principal.tenant_id is not None
    line = await service.update_line(
        session,
        principal=principal,
        tenant_id=principal.tenant_id,
        line_id=line_id,
        line_kind=payload.line_kind,
        carrier=payload.carrier,
        mode=payload.mode,
        ring_seconds=payload.ring_seconds,
        calevate_number_id=payload.calevate_number_id,
        ip=client_request_ip(request),
    )
    return _line_out(line)


@router.delete(
    "/lines/{line_id}",
    status_code=204,
    summary="Stop tracking an existing number",
    openapi_extra=permission_meta("org:manage"),
)
async def remove_line(
    line_id: UUID, session: Session, principal: Writer, request: Request
) -> Response:
    assert principal.tenant_id is not None
    await service.delete_line(
        session,
        principal=principal,
        tenant_id=principal.tenant_id,
        line_id=line_id,
        ip=client_request_ip(request),
    )
    return Response(status_code=204)


@router.post(
    "/lines/{line_id}/tests",
    response_model=ForwardingTestOut,
    status_code=202,
    summary="Ring your existing number from our side to check it forwards to your agent",
    openapi_extra=permission_meta("org:manage"),
)
async def run_test(
    line_id: UUID,
    session: Session,
    principal: OwnWriter,
    request: Request,
    code: ClientActionCode,
    x_confirm_action: ConfirmAction = None,
) -> ForwardingTestOut:
    # A code typed for this act: it places a real call to the business's phone.
    await code.require(x_confirm_action, client_confirmation(request, TEST_ACTION))
    assert principal.tenant_id is not None
    view = await testing.start_test(
        session,
        principal=principal,
        tenant_id=principal.tenant_id,
        line_id=line_id,
        ip=client_request_ip(request),
    )
    return _test_out(view)


@router.get(
    "/lines/{line_id}/tests",
    response_model=list[ForwardingTestOut],
    summary="The latest forwarding tests of one number",
    openapi_extra=permission_meta("org:read"),
)
async def list_tests(
    line_id: UUID,
    session: Session,
    principal: Reader,
    limit: int = Query(5, ge=1, le=MAX_TESTS_PAGE),
) -> list[ForwardingTestOut]:
    await service.read_line(session, line_id)
    return [_test_out(v) for v in await testing.recent_tests(session, line_id, limit=limit)]


def _guide_out(guide: codes.CarrierGuide) -> CarrierGuideOut:
    def code_out(code: codes.Code) -> CodeOut:
        return CodeOut(
            condition=code.condition,
            activate=code.activate,
            deactivate=code.deactivate,
            evidence=code.evidence,
            source=code.source,
        )

    return CarrierGuideOut(
        carrier=guide.carrier,
        method=guide.method,
        codes=[code_out(c) for c in guide.codes],
        unconfirmed=[
            CodeSetOut(label=label, codes=[code_out(c) for c in group])
            for label, group in guide.unconfirmed
        ],
        app_path=guide.app_path,
        note=guide.note,
    )


@router.get(
    "/codes",
    response_model=CodesOut,
    summary="How to switch forwarding on and off, per carrier, with each code's source",
    openapi_extra=permission_meta("org:read"),
)
async def get_codes(principal: Reader) -> CodesOut:
    return CodesOut(
        carriers=[_guide_out(g) for g in codes.GUIDES.values()],
        provider=_guide_out(codes.PROVIDER_GUIDE),
        ring_time_source=codes.RING_TIME_SOURCE[0],
        read_on=codes.READ_ON,
    )


@router.get(
    "/save-number",
    response_model=SaveNumberOut,
    summary="Whether callers who book get one WhatsApp asking them to save your number",
    openapi_extra=permission_meta("org:read"),
)
async def get_save_number(session: Session, principal: Reader) -> SaveNumberOut:
    return SaveNumberOut(enabled=await save_number.read_switch(session))


@router.put(
    "/save-number",
    response_model=SaveNumberOut,
    summary="Switch the save-our-number WhatsApp on or off",
    openapi_extra=permission_meta("org:manage"),
)
async def put_save_number(
    payload: SaveNumberIn,
    session: Session,
    principal: Writer,
    request: Request,
    code: ClientActionCode,
    x_confirm_action: ConfirmAction = None,
) -> SaveNumberOut:
    # A code typed for this act: it decides whether we message the business's callers.
    await code.require(x_confirm_action, client_confirmation(request, SAVE_NUMBER_ACTION))
    assert principal.tenant_id is not None
    changed = await save_number.write_switch(session, enabled=payload.enabled)
    await write_audit(
        session,
        actor=principal,
        action="forwarding.save_number_switched",
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"enabled": payload.enabled, "changed": changed},
    )
    return SaveNumberOut(enabled=payload.enabled)


@admin_router.get(
    "/tenants/{tenant_id}",
    response_model=AdminForwardingOut,
    summary="One client's forwarded numbers, their findings and latest tests",
    openapi_extra=permission_meta("admin:tenants"),
)
async def admin_forwarding(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Operator,
    limit: int = Query(5, ge=1, le=MAX_TESTS_PAGE),
) -> AdminForwardingOut:
    """Read under the tenant's own RLS, and the read recorded (SEC-COMP §5)."""
    async with tenant_session(tenant_id) as scoped:
        lines = await service.list_lines(scoped)
        rows = (
            await scoped.execute(
                text("SELECT id FROM forwarding_tests ORDER BY created_at DESC LIMIT :limit"),
                {"limit": limit},
            )
        ).all()
        tests = [await testing.read_test(scoped, UUID(str(row[0]))) for row in rows]
        enabled = await save_number.read_switch(scoped)
        sent = int(
            (
                await scoped.execute(
                    text("SELECT count(*) FROM save_number_messages WHERE status = 'sent'")
                )
            ).scalar_one()
        )
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return AdminForwardingOut(
        lines=[_line_out(line) for line in lines],
        recent_tests=[_test_out(t) for t in tests],
        save_number_enabled=enabled,
        save_number_sent=sent,
    )


__all__ = ["admin_router", "router"]

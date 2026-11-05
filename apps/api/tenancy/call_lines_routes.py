"""How many calls one client may have at once (F7), and the client's requests for more.

    GET  /v1/admin/organizations/{org_id}/call-lines   the value in force, where it comes from,
                                                       and the client's open request
    PUT  /v1/admin/organizations/{org_id}/call-lines   set it, or null for Calevate's default;
                                                       a raise closes the open request once
                                                       the client's workspace holds it
    POST /v1/admin/organizations/{org_id}/call-lines/requests/{request_id}/decline
                                                       answer a request with "no", and why
    GET  /v1/admin/call-line-requests                  every open request, for the console bell
    GET  /v1/call-lines                                the client's own lines and its request
    POST /v1/call-lines/requests                       the client asks for more

The number is a commercial decision about the client, so only an operator sets it; the client
asks (`tenancy/call_line_requests`). The writer (`tenancy/call_lines.set_call_lines`) owes the
client's own workspace the new value in the saving transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.engine.dial_lines import engine_concurrency_cap
from apps.api.tenancy import call_line_requests as requests_
from apps.api.tenancy.call_line_requests import LineRequest, RequestStatus
from apps.api.tenancy.call_lines import (
    PAID_CALL_LINES_DEFAULT,
    TRIAL_CALL_LINES_DEFAULT,
    CallLines,
    EngineState,
    calls_in_progress,
    read_call_lines,
    set_call_lines,
)
from apps.api.tenancy.models import CALL_LINE_REQUEST_TEXT_MAX, CALL_LINES_MAX, CALL_LINES_MIN

Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
#: The bell's list is a read; `admin:tenants` is in `MUTATING_PERMISSIONS` and D-22 forbids
#: gating a GET on one (`admin/holds_routes.py` argues it). Both admin roles hold `org:read`.
QueueReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]

router = APIRouter(tags=["admin"])


class CallLineRequestAdminOut(BaseModel):
    """The client's open request, as the operator raising its lines reads it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    #: The person who asked: their name, else their email; null once they are gone.
    requested_by: str | None
    lines_at_request: int
    #: Null: the client asked for more without naming a number.
    wanted_lines: int | None
    note: str | None
    created_at: datetime


class CallLinesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The number of calls at once in force.
    call_lines: int
    #: The operator's choice; `null` is Calevate's default.
    call_lines_chosen: int | None
    #: `organization` when an operator chose it, `platform` for the default.
    source: Literal["organization", "platform"]
    #: A free-trial account: its default is the trial's, and Calevate's dial gate holds it.
    on_trial: bool
    min_lines: int
    max_lines: int
    paid_default: int
    trial_default: int
    #: Where the number in force holds (`tenancy/call_lines.EngineState`): `ours` at once,
    #: `applied` once the client's own workspace read it back, `applying` until then.
    engine_state: EngineState
    #: What the client's own workspace last read back, and when; null before a sync.
    applied_lines: int | None
    applied_at: datetime | None
    #: The voice platform account's ceiling on calls at once, shared by every client; null on
    #: an engine that holds none of ours.
    account_ceiling: int | None
    #: Calls at once granted to every other active client, counting a client on the default
    #: as a paying one (a trial's default is lower), so it is an upper bound.
    lines_elsewhere_at_most: int
    #: The client's request for more, while it waits on us.
    open_request: CallLineRequestAdminOut | None = None


class CallLinesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `null` goes back to Calevate's default.
    call_lines: int | None


def call_lines_confirmation(org_id: UUID) -> str:
    """The `X-Confirm-Action` for changing one client's calls at once (D-731): more lines is
    more calls billed at the same moment, so it is confirmed like the other commercial levers."""
    return f"set_call_lines:{org_id}"


_LINES_ELSEWHERE = text(
    "SELECT COALESCE(sum(COALESCE(call_lines, :paid_default)), 0) FROM organizations "
    "WHERE id <> :tid AND deleted_at IS NULL AND status IN ('onboarding', 'active')"
)


async def lines_elsewhere(directory: AsyncSession, *, tenant_id: UUID) -> int:
    """`CallLinesOut.lines_elsewhere_at_most`, on the admin session: `organizations` is the one
    table `app.admin` reads across clients, and `call_lines` lives on it."""
    return int(
        (
            await directory.execute(
                _LINES_ELSEWHERE, {"tid": tenant_id, "paid_default": PAID_CALL_LINES_DEFAULT}
            )
        ).scalar_one()
    )


def _out(
    state: CallLines, open_request: CallLineRequestAdminOut | None, *, elsewhere: int
) -> CallLinesOut:
    return CallLinesOut(
        call_lines=state.lines,
        call_lines_chosen=state.chosen,
        source=state.source,
        on_trial=state.on_trial,
        min_lines=CALL_LINES_MIN,
        max_lines=CALL_LINES_MAX,
        paid_default=PAID_CALL_LINES_DEFAULT,
        trial_default=TRIAL_CALL_LINES_DEFAULT,
        engine_state=state.engine_state,
        applied_lines=state.applied,
        applied_at=state.applied_at,
        account_ceiling=engine_concurrency_cap(),
        lines_elsewhere_at_most=elsewhere,
        open_request=open_request,
    )


async def _admin_request(
    scoped: AsyncSession, *, tenant_id: UUID
) -> CallLineRequestAdminOut | None:
    found = await requests_.open_request_for(scoped, tenant_id=tenant_id)
    if found is None:
        return None
    return CallLineRequestAdminOut(
        id=found.id,
        requested_by=await requests_.requester_name(scoped, user_id=found.requested_by),
        lines_at_request=found.lines_at_request,
        wanted_lines=found.wanted_lines,
        note=found.note,
        created_at=found.created_at,
    )


_DESCRIPTION = (
    "How many calls this client may have at once. `null` is Calevate's default: "
    f"{PAID_CALL_LINES_DEFAULT} for a paying client, {TRIAL_CALL_LINES_DEFAULT} on a free "
    f"trial; a chosen value is {CALL_LINES_MIN}-{CALL_LINES_MAX}. A paying client's own voice "
    "workspace is capped at it; a free trial's calls are counted by our dial gate, which "
    "refuses one more with `call_lines_busy`. `open_request` is the client's request for "
    "more, if one waits; raising the lines above what the client had closes it, at once when "
    "the cap is ours and once the client's own workspace reads it back otherwise "
    "(`engine_state`)."
)


@router.get(
    "/v1/admin/organizations/{org_id}/call-lines",
    response_model=CallLinesOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="How many calls one client may have at once",
    description=_DESCRIPTION,
)
async def admin_get_call_lines(
    org_id: UUID, request: Request, principal: Operator, directory: AdminSession
) -> CallLinesOut:
    elsewhere = await lines_elsewhere(directory, tenant_id=org_id)
    async with tenant_session(org_id) as scoped:
        state = await read_call_lines(scoped, tenant_id=org_id)
        open_request = await _admin_request(scoped, tenant_id=org_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=org_id
        )
    return _out(state, open_request, elsewhere=elsewhere)


@router.put(
    "/v1/admin/organizations/{org_id}/call-lines",
    response_model=CallLinesOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set how many calls one client may have at once",
    description=_DESCRIPTION,
)
async def admin_set_call_lines(
    org_id: UUID,
    payload: CallLinesIn,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    directory: AdminSession,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> CallLinesOut:
    step_up.require(x_confirm_action, call_lines_confirmation(org_id))
    elsewhere = await lines_elsewhere(directory, tenant_id=org_id)
    async with tenant_session(org_id) as scoped:
        state, moved, closed = await set_call_lines(
            scoped, tenant_id=org_id, lines=payload.call_lines, admin_id=principal.user_id
        )
        ip = client_request_ip(request)
        await write_audit(
            scoped,
            action="admin.call_lines_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=ip,
            summary={"call_lines": payload.call_lines, "in_force": state.lines, "moved": moved},
        )
        if closed is not None:
            await write_audit(
                scoped,
                action="call_lines_request.done",
                actor=principal,
                tenant_id=org_id,
                object_type="call_line_request",
                object_id=str(closed.id),
                ip=ip,
                summary={"lines_granted": closed.lines_granted},
            )
        open_request = await _admin_request(scoped, tenant_id=org_id)
    return _out(state, open_request, elsewhere=elsewhere)


class DeclineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The client reads this on its bell, so it is written to them.
    reason: str = Field(min_length=1, max_length=CALL_LINE_REQUEST_TEXT_MAX)


class CallLineRequestOut(BaseModel):
    """A request for more calls at once, as its client sees it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: RequestStatus
    lines_at_request: int
    wanted_lines: int | None
    created_at: datetime
    resolved_at: datetime | None
    #: The lines in force when a raise answered it.
    lines_granted: int | None
    #: Calevate's reason, when it was declined.
    decline_reason: str | None


def _client_request(found: LineRequest) -> CallLineRequestOut:
    return CallLineRequestOut(
        id=found.id,
        status=found.status,
        lines_at_request=found.lines_at_request,
        wanted_lines=found.wanted_lines,
        created_at=found.created_at,
        resolved_at=found.resolved_at,
        lines_granted=found.lines_granted,
        decline_reason=found.decline_reason,
    )


@router.post(
    "/v1/admin/organizations/{org_id}/call-lines/requests/{request_id}/decline",
    response_model=CallLineRequestOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Decline a client's request for more calls at once, saying why",
    description=(
        "Closes the open request as declined; the client reads the reason on its bell. "
        "409 `call_lines_request_not_open` when it was already answered."
    ),
)
async def admin_decline_call_lines_request(
    org_id: UUID, request_id: UUID, payload: DeclineIn, request: Request, principal: Operator
) -> CallLineRequestOut:
    async with tenant_session(org_id) as scoped:
        declined = await requests_.decline(
            scoped,
            tenant_id=org_id,
            request_id=request_id,
            admin_id=principal.user_id,
            reason=payload.reason,
        )
        await write_audit(
            scoped,
            action="call_lines_request.declined",
            actor=principal,
            tenant_id=org_id,
            object_type="call_line_request",
            object_id=str(request_id),
            ip=client_request_ip(request),
            summary={"lines_at_request": declined.lines_at_request},
        )
    return _client_request(declined)


class OpenCallLineRequestOut(BaseModel):
    """One client waiting for more lines. Account facts only: who asked and their note stay
    on the client's own page, behind the permission that opens it (hard rule 6)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    lines_at_request: int
    wanted_lines: int | None
    created_at: datetime


#: The bell lists every open request; one per client, so the client count bounds it.
_OPEN_REQUEST_SCAN = (
    "SELECT scanned_tenant_id, lines_at_request, wanted_lines, created_at "
    "FROM open_call_line_request_scan()"
)
_NAMES = "SELECT id, name FROM organizations WHERE id = ANY(:ids)"


@router.get(
    "/v1/admin/call-line-requests",
    response_model=list[OpenCallLineRequestOut],
    openapi_extra=permission_meta("org:read"),
    summary="Clients waiting for more calls at once, oldest request first",
    description=(
        "Every open request for more calls at once. Raising the client's lines, or "
        "declining the request on its numbers page, removes it from this list."
    ),
)
async def list_open_call_line_requests(
    directory: AdminSession, principal: QueueReader
) -> list[OpenCallLineRequestOut]:
    del principal
    # `app.admin` widens `organizations` and nothing else, so each client's open request is
    # read under that client's own policy inside `open_call_line_request_scan()` (migration
    # f2c6a8d4b1e3): one statement, not a session per client (A7-21). The names are a second
    # statement rather than a JOIN, so `organizations` is never read in the statement whose
    # scan re-scopes the tenant GUC.
    found = (await directory.execute(text(_OPEN_REQUEST_SCAN))).all()
    names = {
        UUID(str(r[0])): str(r[1])
        for r in await directory.execute(text(_NAMES), {"ids": [row[0] for row in found]})
    }
    waiting = [
        OpenCallLineRequestOut(
            tenant_id=UUID(str(row[0])),
            name=names[UUID(str(row[0]))],
            lines_at_request=int(row[1]),
            wanted_lines=None if row[2] is None else int(row[2]),
            created_at=row[3],
        )
        for row in found
        if UUID(str(row[0])) in names
    ]
    waiting.sort(key=lambda w: w.created_at)
    return waiting


ClientReader = Annotated[Principal, Depends(requires("org:read"))]
#: Asking commits the account to a conversation about more calls billed at once, which is
#: the owner's to start: `org:manage`, the permission billing and account settings carry.
ClientOwner = Annotated[Principal, Depends(requires("org:manage", realm="client"))]


class ClientCallLinesOut(BaseModel):
    """What the client sees of its own lines: the number in force, how many are busy now,
    and its request for more. Choosing the number stays the operator's (a commercial
    decision), so the client asks rather than sets."""

    model_config = ConfigDict(extra="forbid")

    call_lines: int
    in_progress: int
    on_trial: bool
    #: The most an account can have; a request asks for at most this.
    max_lines: int
    #: True while a change to `call_lines` is sent to the voice platform and not yet confirmed:
    #: until then the account still has its previous number.
    being_applied: bool
    #: The open request, or one answered in the last week; null when there is neither.
    request: CallLineRequestOut | None = None


@router.get(
    "/v1/call-lines",
    response_model=ClientCallLinesOut,
    openapi_extra=permission_meta("org:read"),
    summary="How many calls your account can have at once, how many are on now, and your ask",
    tags=["numbers"],
)
async def get_my_call_lines(principal: ClientReader) -> ClientCallLinesOut:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as scoped:
        state = await read_call_lines(scoped, tenant_id=principal.tenant_id)
        busy = await calls_in_progress(scoped, tenant_id=principal.tenant_id)
        latest = await requests_.latest_request(scoped, tenant_id=principal.tenant_id)
    return ClientCallLinesOut(
        call_lines=state.lines,
        in_progress=busy,
        on_trial=state.on_trial,
        max_lines=CALL_LINES_MAX,
        being_applied=state.engine_state == "applying",
        request=_client_request(latest) if latest is not None else None,
    )


class CallLineRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: How many calls at once the account wants; null for "more" with no number.
    wanted: int | None = Field(default=None, ge=CALL_LINES_MIN + 1, le=CALL_LINES_MAX)
    note: str | None = Field(default=None, max_length=CALL_LINE_REQUEST_TEXT_MAX)


@router.post(
    "/v1/call-lines/requests",
    response_model=CallLineRequestOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask Calevate for more calls at once",
    description=(
        "Opens a request and tells Calevate's operators. One request is open at a time: "
        "asking again while one waits answers that one with 200 and tells nobody twice. "
        "Refused on a free trial (`call_lines_request_on_trial`), at the most an account can "
        "have (`call_lines_at_most`), and for a day after a decline "
        "(`call_lines_request_too_soon`)."
    ),
    tags=["numbers"],
)
async def ask_for_more_call_lines(
    payload: CallLineRequestIn, request: Request, response: Response, principal: ClientOwner
) -> CallLineRequestOut:
    assert principal.tenant_id is not None
    person = principal.client_user_id
    if person is None:
        # An operator viewing the account would be asking themselves.
        raise ProblemError.forbidden("Only the account's own people can ask for more lines.")
    async with tenant_session(principal.tenant_id) as scoped:
        state = await read_call_lines(scoped, tenant_id=principal.tenant_id)
        found, created = await requests_.ask_for_more(
            scoped,
            tenant_id=principal.tenant_id,
            user_id=person,
            lines_now=state.lines,
            on_trial=state.on_trial,
            wanted=payload.wanted,
            note=payload.note,
        )
        if created:
            await write_audit(
                scoped,
                action="call_lines_request.opened",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="call_line_request",
                object_id=str(found.id),
                ip=client_request_ip(request),
                summary={"lines_at_request": state.lines, "wanted": payload.wanted},
            )
    if not created:
        response.status_code = 200
    return _client_request(found)


__all__ = [
    "CallLineRequestAdminOut",
    "CallLineRequestIn",
    "CallLineRequestOut",
    "CallLinesIn",
    "CallLinesOut",
    "ClientCallLinesOut",
    "DeclineIn",
    "OpenCallLineRequestOut",
    "call_lines_confirmation",
    "router",
]

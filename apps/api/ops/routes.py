"""Operator endpoints — the big red switch, the outbox DLQ, the audit chain, and
Calevate's own DLT telemarketer registration.

That last one is a legal fact rather than an operational lever, and it is here because
it has the same SHAPE as the levers: one value, global, true or false for every tenant
at the same instant. SEC-COMP §3's first bullet makes it the company-level campaign
blocker — while it is not `active`, `campaigns.service.launch_blockers` refuses every
tenant's launch with `tm_registration_missing`, however complete that client's own
Principal Entity registration is. A per-tenant copy of it would be N copies of one fact
that eventually disagree, so it lives in `platform_state` beside the halt.

Two properties hold for every route in this file:

1. **Never shed.** `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES`, so putting the platform
   into `maintenance` does not remove the ability to take it back out.
2. **Step-up confirmation for the dangerous ones** (BACKEND-PATTERNS §7). Halting all
   outbound calling and raising a cap are actions a stolen session must not be able to
   perform, so they require a fresh confirmation bound to the specific action.

Step-up is currently a required `X-Confirm-Action` header that must echo the action
being taken. That is not a strong second factor and is not pretending to be one — it
stops the accidental and the drive-by, and the Clerk re-auth binding replaces it when
the admin realm's MFA lands (TRD §2). It is here now because adding it later would
mean changing the callers, and because a switch this size should never have been
reachable by a single unconfirmed POST.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import verify_chain, write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import LoadShedMode, get_platform_status, set_platform_status
from apps.api.core.rbac import permission_meta
from apps.api.ops.service import TmRegistration, read_tm_registration, set_tm_registration
from apps.api.reliability.service import replay_dead_letters

router = APIRouter(prefix="/v1/ops", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]


class TmRegistrationOut(BaseModel):
    """Calevate's own telemarketer registration (SEC-COMP §3, company half).

    `is_live` is computed rather than left to the reader: "is `submitted` good enough"
    is exactly the question a console must not answer for itself, and the launch gate
    and this response must never disagree about it — both read
    `ops.service.TmRegistration.is_live`.
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    tm_id: str | None
    registered_at: datetime | None
    verified_at: datetime | None
    is_live: bool


class PlatformStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: str
    outbound_halted: bool
    # The third global switch on this row, and the only one that is a legal fact rather
    # than an operational one: when it is not live, no tenant may launch a campaign.
    tm_registration: TmRegistrationOut


class TmRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_registered", "submitted", "active", "suspended", "revoked"]
    # Required in practice for `active` (service + DB CHECK); optional in the schema
    # because the other four states legitimately have no number yet, or no longer do.
    tm_id: str | None = Field(default=None, max_length=120)
    registered_at: datetime | None = None
    # Same requirement as the load-shed switch: an operator changing a platform-wide
    # compliance fact says why, in the audit row, at the time.
    reason: str = Field(min_length=3, max_length=500)


class PlatformStateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: LoadShedMode | None = None
    outbound_halted: bool | None = None
    reason: str


class ReplayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replayed: int


class ChainVerifyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    first_bad_entry_id: str | None = None
    checked: Literal["audit_log"] = "audit_log"


def _require_step_up(confirm: str | None, action: str) -> None:
    if confirm != action:
        raise ProblemError(
            kind="permission",
            code="step_up_required",
            title="Confirmation required",
            detail="This action needs an explicit confirmation.",
            remediation=f"Repeat the request with the header X-Confirm-Action: {action}",
        )


def _tm_out(registration: TmRegistration) -> TmRegistrationOut:
    return TmRegistrationOut(
        status=registration.status,
        tm_id=registration.tm_id,
        registered_at=registration.registered_at,
        verified_at=registration.verified_at,
        is_live=registration.is_live,
    )


@router.get(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
)
async def read_platform(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> PlatformStateOut:
    status = await get_platform_status(force_refresh=True)
    # Read from Postgres on this session, never from the load-shed cache: the TM
    # registration is a compliance fact and a 15-second-stale copy of it is a campaign
    # that launched after the registrar suspended us.
    return PlatformStateOut(
        load_shed_mode=status.mode,
        outbound_halted=status.outbound_halted,
        tm_registration=_tm_out(await read_tm_registration(session)),
    )


@router.post(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Load-shed mode and the big red switch (step-up confirmed, audited)",
)
async def set_platform(
    payload: PlatformStateIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> PlatformStateOut:
    # KNOWN GAP (audited, not fixed here): releasing the halt shares the generic
    # `set_platform_state` confirmation and audit action with a routine load-shed
    # change, so BACKEND-PATTERNS §7's "bound to the specific action" only really holds
    # for pulling the switch, not for lifting it. Splitting it out needs the admin
    # console (apps/web/src/lib/api/admin.ts) and runbooks/campaign-stall.md to move in
    # the same change, or the un-halt button and the documented incident step both 403.
    action = "halt_outbound" if payload.outbound_halted else "set_platform_state"
    _require_step_up(x_confirm_action, action)

    status = await set_platform_status(
        mode=payload.load_shed_mode,
        outbound_halted=payload.outbound_halted,
        actor_id=str(principal.user_id) if principal.user_id else None,
    )
    await write_audit(
        session,
        action=f"ops.{action}",
        actor=principal,
        object_type="platform_state",
        object_id="1",
        ip=request.client.host if request.client else None,
        summary={
            "load_shed_mode": status.mode,
            "outbound_halted": status.outbound_halted,
            "reason": payload.reason,
        },
    )
    return PlatformStateOut(
        load_shed_mode=status.mode,
        outbound_halted=status.outbound_halted,
        tm_registration=_tm_out(await read_tm_registration(session)),
    )


@router.post(
    "/platform/tm-registration",
    response_model=TmRegistrationOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Record Calevate's own DLT telemarketer registration (step-up confirmed, audited)",
    description=(
        "The company half of SEC-COMP §3's first bullet. While this is not `active`, "
        "NO tenant can launch an outbound campaign, however complete their own "
        "Principal Entity registration is. Inbound answering is unaffected."
    ),
)
async def set_tm_registration_route(
    payload: TmRegistrationIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> TmRegistrationOut:
    """Step-up confirmed in BOTH directions, with the action naming which one.

    Marking the registration active is the more dangerous write, not the less: it is
    the one that turns the platform-wide launch gate green, and a stolen admin session
    that could do it silently would have every tenant dialling on a registration that
    does not exist. Taking it away halts all outbound launching, which is the big red
    switch by another route. Neither belongs behind a single unconfirmed POST, so the
    confirmation is bound to the direction — `record_tm_registration` to make it live,
    `withdraw_tm_registration` to take it out of `active` — and an operator who meant
    one cannot perform the other by replaying a header.
    """
    action = "record_tm_registration" if payload.status == "active" else "withdraw_tm_registration"
    _require_step_up(x_confirm_action, action)

    registration = await set_tm_registration(
        session,
        status=payload.status,
        tm_id=payload.tm_id,
        registered_at=payload.registered_at,
    )
    # Same transaction as the write (`global_db` commits at the end of the request):
    # the row is mutable by design, so `audit_log` is the only history of who changed
    # a platform-wide compliance fact and why.
    await write_audit(
        session,
        action=f"ops.{action}",
        actor=principal,
        object_type="platform_state",
        object_id="1",
        ip=request.client.host if request.client else None,
        summary={
            "tm_registration_status": registration.status,
            "tm_id": registration.tm_id,
            "reason": payload.reason,
        },
    )
    return _tm_out(registration)


@router.post(
    "/outbox/replay",
    response_model=ReplayOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Flip dead-lettered outbox messages back to pending (audited)",
)
async def replay_outbox(
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
) -> ReplayOut:
    count = await replay_dead_letters(session)
    # BACKEND-PATTERNS §4 requires the replay to carry an audit note — a message that
    # was delivered twice needs a record of who asked for the second attempt.
    await write_audit(
        session,
        action="ops.outbox_replay",
        actor=principal,
        object_type="outbox_messages",
        ip=request.client.host if request.client else None,
        summary={"replayed": count},
    )
    return ReplayOut(replayed=count)


@router.get(
    "/audit/verify",
    response_model=ChainVerifyOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Recompute the audit hash chain and report the first broken link",
)
async def verify_audit_chain(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> ChainVerifyOut:
    ok, bad = await verify_chain(session)
    return ChainVerifyOut(ok=ok, first_bad_entry_id=bad)


__all__ = ["router"]

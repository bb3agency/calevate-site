"""Operator endpoints — the big red switch, the outbox DLQ, the audit chain.

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

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import verify_chain, write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import LoadShedMode, get_platform_status, set_platform_status
from apps.api.core.rbac import permission_meta
from apps.api.reliability.service import replay_dead_letters

router = APIRouter(prefix="/v1/ops", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]


class PlatformStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: str
    outbound_halted: bool


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


@router.get(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
)
async def read_platform(
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> PlatformStateOut:
    status = await get_platform_status(force_refresh=True)
    return PlatformStateOut(load_shed_mode=status.mode, outbound_halted=status.outbound_halted)


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
    return PlatformStateOut(load_shed_mode=status.mode, outbound_halted=status.outbound_halted)


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

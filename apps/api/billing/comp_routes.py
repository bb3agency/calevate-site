"""Making a client account paid with no payment behind it (D-890).

    GET  /v1/admin/tenants/{tenant_id}/paid   is this account paid, since when, and how
    POST /v1/admin/tenants/{tenant_id}/paid   make it paid (super admin), optionally with credit

Founder, 26 Oct 2026: only a super admin may move a client from the free trial to a paid
account, from any state (a running trial, one that ended, or none), and may add any amount of
credit in the same step. Industry practice for value issued from nothing is a narrow role, a
reason on every act, a second factor bound to the act, an append-only trail, and the act
announced to the people who would object; each is here:

* `billing:comp`, held by super admins only (`core/rbac.SUPERADMIN_ONLY_PERMISSIONS`);
* a mandatory reason, kept on the account (`organizations.first_paid_reason`), since
  `audit_log` records who and what but not the words;
* `X-Confirm-Action: convert_to_paid:<tenant>:<grant to two decimals or 0>`, so a
  confirmation for one client or one amount cannot be replayed for another;
* `account.made_paid` in `audit_log`, in the transaction that made it paid;
* the client's owner told (email and dashboard notice) and every super admin emailed
  (`billing/comp_notices`).

What "paid" unlocks is exactly what a first payment unlocks (`first_payment._unlock`): the
trial ends converted or keeps its data, the agents are refreshed, the client's own calling
account is queued and the go-live guide is owed. It is recorded as `complimentary`, never as
a payment, so revenue figures and payment reports never count it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.comp_notices import owe_comp_notices
from apps.api.billing.credit_routes import (
    GrantIn,
    GrantOut,
    check_grant_amount,
    record_grant,
)
from apps.api.billing.first_payment import on_complimentary_conversion
from apps.api.billing.service import lock_tenant_credits, to_paise
from apps.api.billing.trials import TRIAL_ACTIVE, read_trial
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/paid", tags=["admin"])

CompWrite = Annotated[Principal, Depends(requires("billing:comp", realm="admin"))]
PaidRead = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]

TrialState = Literal["running", "ended", "none"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaidStatusOut(_Strict):
    tenant_id: UUID
    paid: bool
    paid_at: datetime | None
    #: How it became paid: wallet_topup, manual_topup, before_d697, operator_conversion or
    #: complimentary. None while unpaid.
    via: str | None
    #: Why a super admin made it paid, for a complimentary account; None otherwise.
    reason: str | None
    trial: TrialState


class MakePaidIn(_Strict):
    #: Why, in the super admin's own words: kept on the account and sent in the alert email.
    reason: str = Field(min_length=3, max_length=500)
    #: Credit to add in the same step, or none.
    grant: GrantIn | None = None

    @field_validator("reason")
    @classmethod
    def _said(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this account is being made paid")
        return trimmed


class MakePaidOut(_Strict):
    status: PaidStatusOut
    #: True when a running trial was converted; False for one that had ended, or none.
    trial_converted: bool
    #: True when the client's own calling account was queued by this act.
    workspace_queued: bool
    grant: GrantOut | None


def make_paid_confirmation(tenant_id: UUID, grant_inr: Decimal | None) -> str:
    """The step-up string, bound to the client and to the credit added with it."""
    amount = to_paise(grant_inr) if grant_inr is not None else Decimal("0.00")
    return f"convert_to_paid:{tenant_id}:{amount}"


async def _status(scoped: AsyncSession, tenant_id: UUID) -> PaidStatusOut:
    row = (
        await scoped.execute(
            text(
                "SELECT first_paid_at, first_paid_via, first_paid_reason FROM organizations "
                "WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Client")
    trial = await read_trial(scoped, tenant_id=tenant_id)
    state: TrialState = (
        "none" if trial is None else ("running" if trial.status == TRIAL_ACTIVE else "ended")
    )
    return PaidStatusOut(
        tenant_id=tenant_id,
        paid=row[0] is not None,
        paid_at=row[0],
        via=row[1],
        reason=row[2],
        trial=state,
    )


@router.get(
    "",
    response_model=PaidStatusOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Whether a client's account is paid, since when, and how",
)
async def get_paid_status(tenant_id: UUID, request: Request, principal: PaidRead) -> PaidStatusOut:
    async with tenant_session(tenant_id) as scoped:
        out = await _status(scoped, tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return out


@router.post(
    "",
    response_model=MakePaidOut,
    openapi_extra=permission_meta("billing:comp"),
    summary="Make a client's account paid without a payment (super admin)",
    description=(
        "Moves the account from the free trial to a paid account from any state: a running "
        "trial is converted, an ended one keeps its data, an account with none simply "
        "becomes paid. Unlocks what a first payment unlocks; recorded as complimentary, "
        "never as a payment. Optionally adds credit in the same step. Requires "
        "`X-Confirm-Action: convert_to_paid:<tenant_id>:<grant amount to two decimals, or "
        "0.00>`. The client is told and every super admin is emailed. 409 when the account "
        "is already paid."
    ),
)
async def make_paid(
    tenant_id: UUID,
    payload: MakePaidIn,
    request: Request,
    principal: CompWrite,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> MakePaidOut:
    grant = payload.grant
    if grant is not None:
        check_grant_amount(grant.amount_inr, grant.amount_confirmation)
    step_up.require(
        x_confirm_action,
        make_paid_confirmation(tenant_id, grant.amount_inr if grant is not None else None),
    )
    ip = client_request_ip(request)
    async with tenant_session(tenant_id) as scoped:
        # `credit:` before anything else, because the conversion ends the trial, which takes
        # `spend_state:`, and the grant below takes `credit:`. The meter takes them in that
        # order (`caps.lock_tenant_spend_state`), so the reverse here deadlocks against a
        # call finishing at the same moment.
        await lock_tenant_credits(scoped, tenant_id)
        before = await _status(scoped, tenant_id)
        unlocked = await on_complimentary_conversion(
            scoped, tenant_id=tenant_id, reason=payload.reason
        )
        if unlocked is None:
            raise ProblemError.conflict(
                "account_already_paid",
                "This account is already a paid account.",
                remediation=("To give it credit, use Grant credit on its credits page instead."),
            )
        trial_converted, workspace_queued = unlocked
        granted = (
            await record_grant(
                scoped,
                tenant_id=tenant_id,
                amount=grant.amount_inr,
                grant_reference=grant.grant_ref,
                reason=grant.reason,
                principal=principal,
                ip=ip,
                notify=False,
            )
            if grant is not None
            else None
        )
        await write_audit(
            scoped,
            action="account.made_paid",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organizations",
            object_id=str(tenant_id),
            ip=ip,
            summary={
                "via": "complimentary",
                "trial_before": before.trial,
                "trial_converted": str(trial_converted),
                "workspace_queued": str(workspace_queued),
                "grant_inr": str(to_paise(granted.amount_inr)) if granted is not None else "",
                "reason": payload.reason,
            },
        )
        await owe_comp_notices(
            scoped,
            tenant_id=tenant_id,
            kind="paid",
            act_ref="made_paid",
            actor_id=principal.user_id,
            reason=payload.reason,
            amount_inr=granted.amount_inr if granted is not None else None,
        )
        after = await _status(scoped, tenant_id)
    log.info(
        "account_made_paid",
        extra={
            "tenant_id": str(tenant_id),
            "trial_converted": trial_converted,
            "granted": granted is not None,
        },
    )
    return MakePaidOut(
        status=after,
        trial_converted=trial_converted,
        workspace_queued=workspace_queued,
        grant=granted,
    )


__all__ = [
    "MakePaidIn",
    "MakePaidOut",
    "PaidStatusOut",
    "make_paid_confirmation",
    "router",
]

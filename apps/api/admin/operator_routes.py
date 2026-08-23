"""Who may use the admin console — the superadmin's own surface (`/v1/admin/operators`).

    GET    /v1/admin/operators                    every live operator account
    POST   /v1/admin/operators                    add one, and mail its setup link
    PATCH  /v1/admin/operators/{id}               promote or demote
    POST   /v1/admin/operators/{id}/revocation    end the account, the password, the sessions
    POST   /v1/admin/operators/{id}/setup-link    re-send the setup link

**EVERY ROUTE HERE IS `admin:operators`, WHICH ONLY `superadmin` HOLDS.** That single fact
is what makes the two admin tiers real rather than cosmetic: a normal admin cannot reach
the table that decides who is a normal admin, so there is no request they can send that
widens their own authority. `core/rbac.py` argues it at the permission and
`authn/operators.py` argues the two further properties that hold the invariant up (no
self-administration, authority re-read per request).

**WHY A `POST .../revocation` AND NOT A `DELETE`.** Nothing is deleted. Eight tables
reference `admin_users` `ON DELETE RESTRICT` because they record which operator approved a
campaign or installed a credential, so the row survives its account and `deactivated_at`
is what ends it (migration f2c74b81a9d3). A `DELETE` verb would promise an erasure this
surface must not perform — and it would have nowhere to carry the required reason, since a
request body on `DELETE` is the one shape HTTP intermediaries feel free to drop.

**STEP-UP ON ALL FOUR MUTATIONS** (BACKEND-PATTERNS §7). The list of high-risk admin
actions there — the big red switch, cap raises, tenant erasure, entry into a client's
account — is a list of things one compromised console session should not be able to do
silently, and handing somebody an administrator account belongs on it: it is the only act
here whose effect OUTLIVES the session that performed it. Each confirmation is bound to
what makes the act dangerous, and the two bindings differ on purpose (see the builders).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from apps.api.authn.operators import (
    AdminRole,
    OperatorAccount,
    create_operator,
    list_operators,
    reissue_setup_link,
    revoke_operator,
    set_operator_role,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate

router = APIRouter(prefix="/v1/admin/operators", tags=["admin"])

#: The one dependency in this file. `realm="admin"` is not decoration: `ROLE_PERMISSIONS`
#: is one flat dict over both realms, so what keeps a client `owner` out of a console
#: surface is the resolution against `admin_users`, never the permission string.
SuperAdmin = Annotated[Principal, Depends(requires("admin:operators", realm="admin"))]

OperatorId = Annotated[UUID, Path(description="The operator account's `admin_users.id`.")]


def add_operator_confirmation(role: str) -> str:
    """The step-up string for creating an operator account.

    BOUND TO THE ROLE, NOT TO THE ADDRESS, and the address is the tempting choice. Two
    reasons: `X-Confirm-Action` travels in a header, so binding it to an email would put a
    person's address into access logs, `Referer` chains and browser history — the same
    hard-rule-6 argument `SUPPRESS_GLOBALLY_CONFIRMATION` makes about phone numbers — and
    the ROLE is what actually decides the blast radius. Consent to add a colleague who can
    onboard clients is not consent to add a second holder of every platform secret.
    """
    return f"add_operator:{role}"


def operator_role_confirmation(operator_id: UUID) -> str:
    """The step-up string for promoting or demoting ONE operator account.

    Bound to the SUBJECT here rather than to the new role, which is the opposite choice
    from `add_operator_confirmation` and is right for the opposite reason: creation has no
    subject yet (the account does not exist), while a role change has a subject and no
    freedom about it — a confirmation typed to promote Asha must not lift Ravi.
    """
    return f"set_operator_role:{operator_id}"


def operator_revocation_confirmation(operator_id: UUID) -> str:
    return f"revoke_operator:{operator_id}"


def operator_setup_link_confirmation(operator_id: UUID) -> str:
    return f"reissue_operator_setup_link:{operator_id}"


class OperatorOut(BaseModel):
    """One operator account. No credential, no token, no setup link — see below."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    #: Nullable only for Clerk-era rows (D-177). Every account created here has one.
    email: str | None
    name: str | None
    role: str
    created_at: str
    #: False while the setup link is outstanding: the account exists and cannot sign in.
    #: This is the ONLY thing any response here says about a password, and there is
    #: deliberately no field a setup link could be assigned to — the link goes to the
    #: invited mailbox and nowhere else (D-190: a token visible to the inviter is an
    #: account squat, and it cost a whole decision entry on the client realm).
    activated: bool


class OperatorsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operators: list[OperatorOut]


class OperatorReasonIn(BaseModel):
    """The stated reason every mutation here carries.

    A NAMED, PUBLIC model rather than a private base, because two routes take it as their
    whole body — a leading underscore would put `_Reasoned` in the OpenAPI schema and in
    the generated TypeScript client.

    REQUIRED WITH CONTENT, and the bounds are copied from `ConfigSetIn` rather than
    re-argued: whoever reads this ledger row later has to be able to decide whether the
    decision still holds, and "" tells them nothing. One base class so four routes cannot
    disagree about what a reason is.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say why this person's access changes")
        return stripped


class OperatorCreateIn(OperatorReasonIn):
    #: `EmailStr` so an undeliverable address is refused at the boundary rather than
    #: discovered by an outbox row that can never be delivered.
    email: EmailStr
    name: str | None = Field(default=None, max_length=120)
    #: DEFAULTS TO THE NARROW TIER. The founder's sentence for this surface is "I can add
    #: more admins who are NOT super admins", and a default of `operator` is what makes the
    #: common act the safe one — a superadmin is created only by naming the role.
    role: AdminRole = "operator"


class OperatorRoleIn(OperatorReasonIn):
    role: AdminRole


def _out(account: OperatorAccount) -> OperatorOut:
    return OperatorOut(
        id=account.id,
        email=account.email,
        name=account.name,
        role=account.role,
        created_at=account.created_at.isoformat(),
        activated=account.activated,
    )


@router.get(
    "",
    response_model=OperatorsOut,
    openapi_extra=permission_meta("admin:operators"),
    summary="Every live operator account and its tier",
    description=(
        "The operator allowlist: who may sign in to the admin console, which tier they "
        "are in, and whether they have finished setting a password. Revoked accounts are "
        "not listed — their rows survive only as the record of what they decided, and "
        "'who was removed and when' is a question for the audit log."
    ),
)
async def read_operators(_: SuperAdmin) -> OperatorsOut:
    """No session dependency: this reads no tenant table and `Depends(db)` would drag in
    `tenant_of`, which has no tenant to give an admin principal (`admin/routes.py::
    admin_me` argues the same shape)."""
    return OperatorsOut(operators=[_out(account) for account in await list_operators()])


@router.post(
    "",
    response_model=OperatorOut,
    status_code=201,
    openapi_extra=permission_meta("admin:operators"),
    summary="Add an operator account and mail its setup link (step-up confirmed, audited)",
    description=(
        "Creates the account and mails a single-use link the person uses to set their own "
        "password; no password is chosen, generated or returned here. Requires "
        "`X-Confirm-Action: add_operator:<role>`. The address must not already belong to "
        "a live operator account."
    ),
)
async def add_operator(
    payload: OperatorCreateIn,
    request: Request,
    principal: SuperAdmin,
    # Resolved BEFORE the handler body, so the credential read cannot happen inside an
    # open transaction (`core/stepup.py` on `max_overflow=0`).
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> OperatorOut:
    step_up.require(x_confirm_action, add_operator_confirmation(payload.role))
    return _out(
        await create_operator(
            actor=principal,
            email=str(payload.email),
            name=payload.name,
            role=payload.role,
            reason=payload.reason,
            ip=client_request_ip(request),
        )
    )


@router.patch(
    "/{operator_id}",
    response_model=OperatorOut,
    openapi_extra=permission_meta("admin:operators"),
    summary="Promote or demote an operator (step-up confirmed, audited)",
    description=(
        "Moves one account between the two tiers and ends its live sessions. Requires "
        "`X-Confirm-Action: set_operator_role:<operator_id>`. An operator may not change "
        "their own role — every change to the allowlist names two people. A request that "
        "sets the role it already has is a no-op: no ledger row, no sign-out."
    ),
)
async def change_operator_role(
    payload: OperatorRoleIn,
    request: Request,
    principal: SuperAdmin,
    step_up: StepUpGate,
    operator_id: OperatorId,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> OperatorOut:
    step_up.require(x_confirm_action, operator_role_confirmation(operator_id))
    return _out(
        await set_operator_role(
            actor=principal,
            operator_id=operator_id,
            role=payload.role,
            reason=payload.reason,
            ip=client_request_ip(request),
        )
    )


@router.post(
    "/{operator_id}/revocation",
    response_model=OperatorOut,
    openapi_extra=permission_meta("admin:operators"),
    summary="End an operator's access (step-up confirmed, audited)",
    description=(
        "Deactivates the account and destroys its password, its live sessions and any "
        "outstanding setup link. The row itself is kept: eight tables record which "
        "operator approved a campaign or installed a credential, and an erased decider "
        "turns those into anonymous decisions. Requires "
        "`X-Confirm-Action: revoke_operator:<operator_id>`. An operator may not revoke "
        "their own account."
    ),
)
async def revoke_operator_route(
    payload: OperatorReasonIn,
    request: Request,
    principal: SuperAdmin,
    step_up: StepUpGate,
    operator_id: OperatorId,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> OperatorOut:
    step_up.require(x_confirm_action, operator_revocation_confirmation(operator_id))
    return _out(
        await revoke_operator(
            actor=principal,
            operator_id=operator_id,
            reason=payload.reason,
            ip=client_request_ip(request),
        )
    )


@router.post(
    "/{operator_id}/setup-link",
    response_model=OperatorOut,
    openapi_extra=permission_meta("admin:operators"),
    summary="Re-send an operator's setup link (step-up confirmed, audited)",
    description=(
        "Mails a fresh single-use link to an account that has not set a password yet, and "
        "invalidates the previous one. Refused for an account that is already activated — "
        "this is not a password reset, and cannot be used as one: somebody who has "
        "forgotten their password uses the sign-in page, which mails the link to them. "
        "Requires `X-Confirm-Action: reissue_operator_setup_link:<operator_id>`."
    ),
)
async def resend_operator_setup_link(
    payload: OperatorReasonIn,
    request: Request,
    principal: SuperAdmin,
    step_up: StepUpGate,
    operator_id: OperatorId,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> OperatorOut:
    step_up.require(x_confirm_action, operator_setup_link_confirmation(operator_id))
    return _out(
        await reissue_setup_link(
            actor=principal,
            operator_id=operator_id,
            reason=payload.reason,
            ip=client_request_ip(request),
        )
    )


__all__ = [
    "add_operator_confirmation",
    "operator_revocation_confirmation",
    "operator_role_confirmation",
    "operator_setup_link_confirmation",
    "router",
]

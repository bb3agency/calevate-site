"""Session/identity endpoints.

`/v1/me` is the first call every frontend makes. It exists so the browser never has to
infer who it is talking as: the realm, the resolved tenant, the role and the permission
set all come from the server, and the UI renders from them rather than from a decoded
JWT it might read differently than we do.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import current_identity, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import ROLE_PERMISSIONS, permission_meta
from apps.api.db.session import invite_session, tenant_session

router = APIRouter(prefix="/v1", tags=["tenancy"])

Session = Annotated[AsyncSession, Depends(db)]


class OrganizationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    status: str
    vertical_template: str | None = None


class MeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realm: str
    user_id: UUID | None
    role: str | None
    permissions: list[str]
    # D-22: the client UI renders a persistent banner when this is true, because a
    # read-only admin session must never look like the client's own session.
    impersonating: bool
    organization: OrganizationOut | None = None


@router.get(
    "/me",
    response_model=MeOut,
    openapi_extra=permission_meta("org:read"),
    summary="Who am I, in which account, with what permissions",
)
async def me(session: Session, principal: Principal = Depends(requires("org:read"))) -> MeOut:
    """`requires("org:read")`, not `current_any`: the declaration in `openapi_extra`
    above and the dependency here must name the same permission.

    Nothing about who gets in changes — `requires()` defaults to `realm="any"` and so
    resolves the identical principal, `org:read` is not in `MUTATING_PERMISSIONS` so an
    impersonating admin is still admitted (D-22), and every role the DB enums allow
    holds `org:read`. What changes is that the route now enforces what it advertises,
    which is the property `assert_policy_registry_complete` checks at boot and
    `tests/authz_audit_test.py` asserts for every route at once. A declaration with no
    lock behind it reads as protected in the OpenAPI schema and the generated TS
    client; this was the last route where that was true.
    """
    org = None
    row = (
        await session.execute(
            text("SELECT id, name, slug, status, vertical_template FROM organizations LIMIT 1")
        )
    ).first()
    if row is not None:
        org = OrganizationOut(
            id=row[0], name=row[1], slug=row[2], status=row[3], vertical_template=row[4]
        )
    return MeOut(
        realm=principal.realm,
        user_id=principal.user_id,
        role=principal.role,
        permissions=sorted(ROLE_PERMISSIONS.get(principal.role or "", frozenset())),
        impersonating=principal.impersonating,
        organization=org,
    )


class AcceptInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The raw token from the emailed link. Only its hash is stored, so this value
    # cannot be recovered from our database — it exists in the email and nowhere else.
    token: str = Field(min_length=20, max_length=200)


class AcceptInviteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    slug: str
    role: str


@router.post(
    "/invitations/accept",
    response_model=AcceptInviteOut,
    summary="Accept an emailed invitation and create the membership (FLOWS §1 step 8)",
)
async def accept_invitation(
    payload: AcceptInviteIn,
    request: Request,
    identity: tuple[UUID, str] = Depends(current_identity),
) -> AcceptInviteOut:
    """The one authenticated route that does NOT require a membership — creating one is
    the point (see `current_identity`).

    The burn is a CAS on `used_at IS NULL`, so two clicks on the same emailed link
    produce one membership rather than two.
    """
    user_id, _clerk_id = identity

    # The token names its own tenant, so the lookup runs under `app.invite_hash` —
    # a read-only widening scoped to the single row the caller can already name.
    token_hash = sha256(payload.token.encode()).hexdigest()
    # No JOIN to `organizations` here: the invite GUC widens `invitations` and nothing
    # else, so joining would silently return zero rows. The slug is read below, once
    # the tenant is known and a normal tenant session applies.
    async with invite_session(token_hash) as lookup:
        row = (
            await lookup.execute(
                text(
                    "SELECT tenant_id FROM invitations WHERE token_hash = :hash "
                    "AND used_at IS NULL AND expires_at > now()"
                ),
                {"hash": token_hash},
            )
        ).first()
    if row is None:
        # Deliberately indistinguishable from "already used" and "expired": an
        # attacker guessing tokens learns nothing from the difference.
        raise ProblemError(
            kind="business_rule",
            code="invitation_invalid",
            title="Invitation is not usable",
            detail="This invitation has already been used or has expired.",
            remediation="Ask your account manager for a fresh invite.",
        )
    tenant_id = UUID(str(row[0]))

    async with tenant_session(tenant_id) as scoped:
        await admin_service.accept_invitation(scoped, raw_token=payload.token, user_id=user_id)
        role = (
            await scoped.execute(
                text("SELECT role FROM memberships WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()
        slug = (
            await scoped.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar()
        await write_audit(
            scoped,
            action="invitation.accepted",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="membership",
            object_id=str(user_id),
            ip=request.client.host if request.client else None,
        )
    return AcceptInviteOut(tenant_id=tenant_id, slug=str(slug), role=str(role or "owner"))


__all__ = ["router"]

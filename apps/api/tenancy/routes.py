"""Session/identity endpoints.

`/v1/me` is the first call every frontend makes. It exists so the browser never has to
infer who it is talking as: the realm, the resolved tenant, the role and the permission
set all come from the server, and the UI renders from them rather than from a decoded
JWT it might read differently than we do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.service import enqueue_invitation_email
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires, tenant_of
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import ROLE_PERMISSIONS, permission_meta
from apps.api.tenancy import members as members_service

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


class MemberOut(BaseModel):
    """One colleague, as a control that has to NAME them needs them.

    **No email, and that is a rule rather than a preference.** `email` is in
    `scripts/check_redaction_exposure.py`'s `RAW_PII_FIELDS`, so a response model
    declaring it fails the guardrail unless the route is allowlisted as role-checked and
    audited — which an assignee picker is not, and should not have to be. Nothing on
    this surface needs it either: the control writes an id and prints a name.

    `name` is nullable because `users.name` is: an invitation carries an address and,
    optionally, a name, so a colleague who typed neither has NULL
    (`authn/invitations.py`). The screen says "Unnamed member" rather than falling
    back to an address — a fallback that leaks is not a fallback.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str | None = None
    # `owner` or `staff` (DATA-MODEL §2). Present because the picker is also the place a
    # person answers "who can actually do this?" — and because a role is a fact about
    # our account, not about the person.
    role: str


@router.get(
    "/members",
    response_model=list[MemberOut],
    # `org:read`: every role in both realms holds it, it is not in MUTATING_PERMISSIONS,
    # and D-22 therefore leaves it readable to an impersonating operator — who needs to
    # see the same team list the client sees in order to explain a lead's owner. Not
    # `org:manage`: reading who is on the team is not the authority to change it.
    openapi_extra=permission_meta("org:read"),
    summary="Who is on this account's team — ids and display names, never emails",
)
async def list_members(
    session: Session,
    # BOUNDED, like every other list this API serves (D-302). A team picker's page is not
    # where a tenant's row count belongs: the whole result is materialised in memory and
    # serialised, so an account that grew past what a picker can render was an allocation
    # decided by somebody else's data. Two hundred is the house ceiling (`GET /v1/calls`,
    # `GET /v1/leads`), and it is the DEFAULT here rather than fifty because a picker that
    # silently shows half a team is a worse failure than a long list.
    limit: int = Query(200, ge=1, le=200),
    _: Principal = Depends(requires("org:read")),
) -> list[MemberOut]:
    """The team, for any control that has to name a colleague (M3 lead assignment).

    THE TENANCY CONTROL IS THE JOIN. `users` is a GLOBAL table with no RLS — identity
    crosses tenants (DATA-MODEL §2) — so `SELECT id, name FROM users` under a tenant
    session would return every user of the platform. `memberships` is FORCE-RLS'd on
    `tenant_id`, so driving the query from it is what scopes the answer, and there is no
    `WHERE tenant_id` here for the reason the whole codebase gives: a hand-written
    filter is a filter that can be forgotten, and its presence invites trusting it
    instead of the policy.

    Deactivated accounts are excluded. A deactivated user is refused at the auth guard
    on every request (BACKEND-PATTERNS §7), so offering them as an assignee would be
    offering work to somebody who cannot open the account — and `crm.service` refuses
    the assignment for the same reason, so a picker that listed them would be a control
    whose options the server rejects.
    """
    rows = (
        await session.execute(
            text(
                "SELECT m.user_id, u.name, m.role FROM memberships m "
                "JOIN users u ON u.id = m.user_id "
                "WHERE u.deactivated_at IS NULL "
                # Named people first, then by seniority of joining: a picker whose order
                # changes between renders is a picker people mis-click.
                "ORDER BY u.name NULLS LAST, m.created_at LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return [MemberOut(id=row[0], name=row[1], role=row[2]) for row in rows]


# --- Team management (ROADMAP M3, "client staff roles") -----------------------------
#
# THE PERMISSION SPLIT IS THE DESIGN. Every read on this surface is `org:read`; every
# write is `org:manage`. That is not symmetry for its own sake — it is D-22. `org:manage`
# is in `MUTATING_PERMISSIONS`, so an impersonating operator is refused it, and a GET
# that asked for it would vanish from a support session at exactly the moment support is
# needed (`tests/impersonation_reads_test.py` walks the live route table and says so).
# A support engineer must be able to SEE who is on a client's team and must not be able
# to promote anyone; those two sentences are these two permissions.
#
# AUDIT ACTIONS CARRY THE TRANSITION IN THEIR NAME. `audit_log` has no detail column —
# `write_audit(summary=...)` goes to the log stream, NOT into the hashed row (see its
# docstring) — so "from what to what" has to live in a column that is actually persisted
# and hashed. `action` is that column, hence `member.role_changed:staff->owner`. The
# alternative, a `detail JSONB` column on `audit_log`, is a better answer and belongs to
# a migration on `apps/api/compliance/`, which this slice does not own.


class MemberRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["owner", "staff"]
    # The role the caller's screen was showing. Not redundant with `role`: it turns the
    # write into a CAS (BACKEND-PATTERNS §5) so a change another owner made in the
    # meantime is reported instead of overwritten.
    expected_role: Literal["owner", "staff"]


class MemberRemovedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    previous_role: str
    # Leads this person still owns. Removing them does NOT unassign their work (see
    # `members.remove_member`), so the number is stated rather than left to be
    # discovered — an owner who removes a colleague and is told nothing has just made
    # some number of leads nobody's business without knowing it.
    leads_still_assigned: int


class InvitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Literal["owner", "staff"]


class InvitationOut(BaseModel):
    """A pending invitation — a live key to this account sitting in an inbox.

    `email` is the whole address (D-436): an owner has to be able to see that the
    address they typed is the one they meant, and to tell two invites at one domain
    apart. `org:read` gates the list; `PendingInvitation` records what the dots cost.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    role: str
    invited_at: datetime
    expires_at: datetime


class InvitationCreatedOut(InvitationOut):
    """The one response that carries the raw token, exactly once.

    It is never stored (only its SHA-256 is) and never logged, so this response is the
    only place it will ever exist outside the invitee's browser. The client realm has no
    mailer of its own — `apps/workers/notifications.py` owns email delivery and
    registering a job there is outside this slice — so the owner is handed the link and
    sends it. When that job exists this field should stop being returned, because a
    token that is displayed is a token that can be pasted into the wrong window.
    """

    #: WAS `token: str`, and its removal is the point of D-190.
    #:
    #: This handed the raw invitation token back to the INVITER, because the client realm
    #: had no mailer when it was written and the owner was expected to forward the link.
    #: The realm has had a mailer since D-170, and the gap cost D-185: anyone able to issue
    #: an invitation could invite an address they do not control, read the token out of
    #: their own 201 and redeem it — taking the one global `users` row for that address.
    #: D-185 stopped that becoming somebody else's account and could NOT stop the squat,
    #: because the squat lives for exactly as long as anyone but the invitee sees the token.
    #:
    #: `delivery` replaces it: whether the link was queued, so the screen can say "we have
    #: emailed them" or "email is not configured — the link is in the outbox" rather than
    #: rendering a secret. Nothing in this response is a credential any more.
    delivery: str


@router.post(
    "/invitations",
    response_model=InvitationCreatedOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Invite a colleague to this account (owner only)",
)
async def invite_member(
    payload: InvitationIn,
    session: Session,
    request: Request,
    # `tenant_of`, not `principal.tenant_id`: the same dependency `deps.db` already
    # resolved (so it is cached, not re-authenticated) and the one that TYPES the value
    # as present. `Principal.tenant_id` is `UUID | None` because an admin principal
    # outside a tenant is a real shape; on a route whose session is tenant-scoped it
    # cannot be None, and saying so with a dependency beats saying so with a cast.
    tenant_id: UUID = Depends(tenant_of),
    principal: Principal = Depends(requires("org:manage")),
) -> InvitationCreatedOut:
    invitation_id, token = await members_service.create_team_invitation(
        session,
        tenant_id=tenant_id,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        email=str(payload.email),
        role=payload.role,
    )
    await write_audit(
        session,
        action=f"member.invited:{payload.role}",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="invitation",
        object_id=str(invitation_id),
        ip=client_request_ip(request),
    )
    row = (
        await session.execute(
            text("SELECT email, created_at, expires_at FROM invitations WHERE id = :i"),
            {"i": invitation_id},
        )
    ).one()
    # ENQUEUED IN THE REQUEST'S OWN TRANSACTION, so the invitation row and its email share
    # one fate: an invitation committed without its mail is a person who is never told, and
    # a mail sent for a row that rolled back is a link that does not work. The outbox is
    # what makes that atomic (BACKEND-PATTERNS §4).
    await enqueue_invitation_email(session, to=str(row[0]), token=token)
    return InvitationCreatedOut(
        id=invitation_id,
        email=str(row[0]),
        role=payload.role,
        invited_at=row[1],
        expires_at=row[2],
        delivery="queued",
    )


@router.get(
    "/invitations",
    response_model=list[InvitationOut],
    openapi_extra=permission_meta("org:read"),
    summary="Invitations that can still be redeemed",
)
async def list_invitations(
    session: Session,
    # Bounded for the reason `list_members` is, with one more: an unused invitation is a
    # row the CALLER mints, so the length of this list is caller-controlled.
    limit: int = Query(200, ge=1, le=200),
    _: Principal = Depends(requires("org:read")),
) -> list[InvitationOut]:
    """`org:read`, deliberately. Who currently holds a key to this account is part of
    "who has access", which is the question a support session exists to answer; the
    authority to hand one out is the separate thing, and it is `org:manage` above."""
    return [
        InvitationOut(
            id=row.id,
            email=row.email,
            role=row.role,
            invited_at=row.invited_at,
            expires_at=row.expires_at,
        )
        for row in await members_service.list_pending_invitations(session, limit=limit)
    ]


@router.delete(
    "/invitations/{invitation_id}",
    response_model=InvitationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Revoke an unused invitation (owner only)",
)
async def revoke_invitation(
    invitation_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> InvitationOut:
    # Read before the delete: the response has to name what was revoked, and after the
    # DELETE the row is gone. Same transaction, so a failed delete returns nothing.
    row = (
        await session.execute(
            text("SELECT email, role, created_at, expires_at FROM invitations WHERE id = :i"),
            {"i": invitation_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Invitation")
    await members_service.revoke_invitation(session, invitation_id)
    await write_audit(
        session,
        action=f"member.invitation_revoked:{row[1]}",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="invitation",
        object_id=str(invitation_id),
        ip=client_request_ip(request),
    )
    return InvitationOut(
        id=invitation_id,
        email=str(row[0]),
        role=str(row[1]),
        invited_at=row[2],
        expires_at=row[3],
    )


@router.patch(
    "/members/{user_id}",
    response_model=MemberOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Change a colleague's role (owner only)",
)
async def set_member_role(
    user_id: UUID,
    payload: MemberRoleIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> MemberOut:
    previous = await members_service.change_member_role(
        session,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        target_user_id=user_id,
        new_role=payload.role,
        expected_role=payload.expected_role,
    )
    if previous != payload.role:
        await write_audit(
            session,
            action=f"member.role_changed:{previous}->{payload.role}",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="membership",
            # The TARGET's `users.id`. `users` rows outlive memberships, so this stays
            # resolvable after the person is removed — which is exactly the case a
            # reader asking "why did they have access?" is asking about.
            object_id=str(user_id),
            ip=client_request_ip(request),
        )
    name = (
        await session.execute(
            text(
                "SELECT u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = :u"
            ),
            {"u": user_id},
        )
    ).scalar()
    return MemberOut(id=user_id, name=name, role=payload.role)


@router.delete(
    "/members/{user_id}",
    response_model=MemberRemovedOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Remove a colleague from this account (owner only)",
)
async def remove_member(
    user_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> MemberRemovedOut:
    previous, still_assigned = await members_service.remove_member(
        session, actor_user_id=principal.user_id, target_user_id=user_id
    )
    await write_audit(
        session,
        # The role they HELD when access was taken away — the fact a later reader needs,
        # and the one the deleted row can no longer supply.
        action=f"member.removed:{previous}",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="membership",
        object_id=str(user_id),
        ip=client_request_ip(request),
    )
    return MemberRemovedOut(
        user_id=user_id, previous_role=previous, leads_still_assigned=still_assigned
    )


# THE CLERK-ERA INVITATION-ACCEPT ENDPOINT WAS HERE, AND IT IS GONE (D-177).
#
# `POST /v1/invitations/accept` took a token from an already-signed-in caller, compared
# the invitation's address against the `users` row Clerk had mirrored, and created the
# membership. It was correct for the world it was written in and it is a SECOND way to do
# one thing in this one: `POST /v1/auth/client/invitations/accept` takes `{token,
# password, name}`, creates the `users` row, sets the password, burns the invitation
# through the same `admin_service.accept_invitation` this route called, and issues a
# session — one call where there used to be a vendor sign-up followed by this.
#
# It is also strictly stronger, which is why the collapse loses nothing. The address comes
# from the INVITATION rather than from whatever address the caller had signed in with, so
# `invitation_wrong_recipient` — the refusal an honest invitee met when their vendor
# account used their other address — cannot arise. There is no comparison left to get
# wrong, and the recipient binding this route argued for is now structural.
#
# `admin_service.accept_invitation` and its CAS on `used_at` are untouched and still the
# only burner; `tests/member_invitations_test.py` drives them through the surviving route.

__all__ = ["MemberOut", "router"]

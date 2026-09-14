"""Who currently holds a key to ONE client's account, and taking one back (D-602).

    GET    /v1/admin/tenants/{tenant_id}/members            the roster
    PATCH  /v1/admin/tenants/{tenant_id}/members/{user_id}  owner <-> staff
    DELETE /v1/admin/tenants/{tenant_id}/members/{user_id}  take their access away

═══ THE GAP THIS CLOSES, AND WHY IT SURVIVED D-546 ═══

D-546 gave client account management its screens and every one of them is about the
ACCOUNT: its business details, its state, its closure, and the invitations to it. The
PEOPLE were the half nobody had — the console could mint a key
(`POST .../invitations`), list the keys still sitting in an inbox and cancel one, and then
lost sight of a person the moment they redeemed it. Three sentences already in this tree
say so by accident, each pointing at a surface that did not exist:

- `admin/routes.revoke_tenant_invitation`: an invitation accepted between the click and
  the request is not deleted, because "the person is now a member and removing them is a
  different act on a different surface".
- `admin/service.create_invitation`, refusing a duplicate: "Change their role from the
  team list instead of inviting them again" — a list the operator realm did not have.
- `admin/routes.list_tenant_invitations`: "an impersonating support session may already
  see every member of the account, and an outstanding invitation is the same fact one
  step earlier". The read was reachable only by BORROWING the client's own session.

That last one is the argument for this module rather than for a documentation fix.
Reading the roster through view-as worked; acting on it did not, and could not —
`rbac.VIEW_AS_WITHHELD_ACTS["org.membership"]` withholds the membership surface from an
impersonating session on purpose (D-587), so an operator could see the problem and had no
door to fix it. The support case is not hypothetical and it is the one this business will
meet first: the client's only owner has left the company, so nobody there can sign in as
an owner and every client-realm control — each of which needs a live owner — is dead. The
operator could already restore access by inviting a new owner. What they could not do was
take the departed person's access away.

═══ WHAT IS DELIBERATELY NOT HERE ═══

**Deactivating the PERSON.** `users` is global and crosses tenants (DATA-MODEL §2), so
`users.deactivated_at` is a fact about a human being rather than about this client's
account, and switching it from a screen headed with one client's name would be the wrong
scope printed over the right button. A deactivated user IS shown on the roster
(`deactivated` below) — the client-realm picker hides them and an operator must not,
because a deactivated owner still holds a membership row and still counts toward the
last-owner rule, which is a fact an operator needs before they can explain a refusal.

**Adding a member.** That is an invitation, it already exists one screen away, and a
membership minted without one would be an access grant with no redeemed token behind it.

**Reassigning their leads.** `members.remove_member` argues at length why removal is not
an unassignment. What this surface adds is that the count is on the screen BEFORE the
decision as well as in the answer after it.

═══ THE PERMISSION SPLIT, AND THE STEP-UP ON EXACTLY ONE ROUTE ═══

`org:read` on the read and `admin:tenants` on both writes, which is D-22 applied the way
`list_tenant_invitations` and `read_tenant_profile` apply it: `admin:tenants` is in
`MUTATING_PERMISSIONS`, so gating the READ on it would hide "who can get into this
account" from exactly the support session whose job is to answer that on a telephone call.

The REMOVAL takes the composed step-up (`core/stepup.py`) and the role change does not.
The line between them is not the word "destructive" — it is whether the operator who was
wrong can put it back. A role change is undone by the same operator, on the same screen,
in one click, and the census in `tests/authn_stepup_test.py` records what ceremony on a
reversible act costs: it teaches an operator to type past ceremony, which is why the
reversible half of `set_tenant_status` lost its gate. A removal cannot be undone by us at
all. The way back is a NEW invitation that the person themselves must receive and redeem,
so an operator who removes the wrong person has handed the repair to somebody who can no
longer sign in. That asymmetry buys the second factor.

The confirmation string carries BOTH ids. A header captured while looking at one person
on one account must not be replayable against the colleague listed beneath them — on this
screen that is one row's distance, and the difference between a tidy-up and a client who
cannot sign in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.tenancy import members as members_service

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/members", tags=["admin"])

# The WRITE gate. `core.deps.db` resolves the tenant from the PRINCIPAL and an admin
# principal has none, so every route here opens `tenant_session(tenant_id)` on the path
# parameter by hand — the house pattern for admin-realm work on one client
# (`closure_routes.py`), and the only shape that puts hard rule 1's policy rather than a
# `WHERE` clause in charge.
Manager = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
Reader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]

#: The house ceiling for a list this API serves (D-302), and the same one the client's own
#: `GET /v1/members` takes. A client team is a handful of people; the bound exists because
#: a response whose length is decided by somebody else's row count is not ours to decide.
MEMBER_LIMIT = 200

#: The roster, ordered as a rule rather than by accident: owners first, then named people,
#: then by seniority of joining. An operator scanning for "who can actually authorise
#: this" reads the top of the list, and an order that changes between renders is a list
#: people mis-click. ONE statement, used by the read AND by the PATCH's read-back, so the
#: two can never disagree about what a member row contains.
#:
#: THE LEAD COUNT CARRIES NO `deleted_at IS NULL`, and that is deliberate rather than
#: overlooked: `members.remove_member` counts with exactly this predicate and its number
#: is the one the removal's answer states out loud. A roster that filtered and an answer
#: that did not would disagree in front of the operator at the moment they are deciding,
#: which is worse than either number on its own. A soft-deleted lead still names an
#: assignee, and removal still does not clear it.
#:
#: `:user_id` NARROWS IT TO ONE ROW when it is not NULL, which is how the PATCH reads back
#: the person it just changed. The alternative — fetching the page and scanning it — makes
#: the read-back silently depend on `LIMIT`, so on an account with more members than the
#: ceiling a successful write would answer 404 because the person sorted past the cut. One
#: statement with a nullable filter keeps that impossible AND keeps the two reads agreeing
#: about what a member row contains, which is why this is not two SQL strings.
_ROSTER_SQL = (
    "SELECT m.user_id, u.name, u.email, m.role, m.created_at, u.email_verified_at, "
    "       u.deactivated_at, "
    "       (SELECT count(*) FROM leads l WHERE l.assigned_to = m.user_id) AS leads "
    "FROM memberships m JOIN users u ON u.id = m.user_id "
    # CAST, because the parameter is NULL on the roster read and Postgres cannot infer a
    # type for a bare placeholder compared against nothing — "could not determine data
    # type of parameter" rather than a wrong answer, but a 500 either way.
    "WHERE (CAST(:user_id AS uuid) IS NULL OR m.user_id = CAST(:user_id AS uuid)) "
    "ORDER BY (m.role <> 'owner'), u.name NULLS LAST, m.created_at "
    "LIMIT :limit"
)


def remove_member_confirmation(tenant_id: UUID, user_id: UUID) -> str:
    """The `X-Confirm-Action` for taking ONE person's access to ONE account away.

    A named function rather than an inline f-string, for the reason
    `closure_routes.close_account_confirmation` gives: the value is part of an operator
    procedure, so changing its shape has to be a deliberate edit that fails a test rather
    than a reformat that leaves the console sending a header the API refuses.
    """
    return f"remove_member_access:{tenant_id}:{user_id}"


class TeamMemberOut(BaseModel):
    """One person who can sign in to this client's account right now.

    **The address is here in full, and that is the same disclosure `PendingInviteOut`
    already makes one screen away** — not a widening of it. `email` is a
    `CONTACT_PII_FIELD`, which `scripts/check_redaction_exposure.py` permits on a route
    that declares a permission (D-436), and this read declares one, runs in the tenant's
    own RLS scope and records an impersonation read. It is here because the operator is
    about to revoke somebody's access BY NAME and `name` cannot carry that weight: it is
    NULLABLE (an invitee who typed no name has none) and it is not unique, so a console
    offering "Remove Ramesh" against a team with two would be a control whose target the
    operator cannot verify. The client-realm `MemberOut` omits the address for the
    opposite reason and both are right — that one is an assignee picker for colleagues
    who already know each other, and nothing on it acts on a person.

    `leads_assigned` is on the ROSTER and not only in the removal's answer, because it is
    the fact that decides the act. Removal does not unassign anybody's work
    (`members.remove_member` argues why), so an operator who sees the number afterwards
    has already made a pile of leads nobody's business; seeing it first is how that
    becomes a conversation with the client instead.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    #: `users.name`, which is nullable — the console prints "Unnamed member" rather than
    #: falling back to the address, because a fallback that leaks is not a fallback.
    name: str | None
    email: str
    role: str
    #: When this membership was created — i.e. when they redeemed their invitation.
    joined_at: datetime
    #: Whether they have proved the address above (D-185). An unverified owner is the
    #: commonest reason a client says our notices never arrive, and this is the only
    #: place in the console it can be read.
    email_verified: bool
    #: The PERSON is deactivated platform-wide, so the auth guard refuses them on every
    #: request. Their membership row survives, still counts toward the last-owner rule
    #: and is still what has to be removed to take the grant away — which is why they are
    #: listed rather than filtered out.
    deactivated: bool
    #: Leads in THIS account currently assigned to them. RLS scopes the count; removal
    #: does not clear it.
    leads_assigned: int


class TeamMemberRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["owner", "staff"]
    #: The role the operator's screen was SHOWING. Not redundant with `role`: it makes the
    #: write a CAS (BACKEND-PATTERNS §5), so a change the client made themselves in the
    #: intervening seconds — this is a live account whose own owners press their own
    #: buttons — is reported instead of silently overwritten.
    expected_role: Literal["owner", "staff"]


class TeamMemberRemovedOut(BaseModel):
    """What the removal did, in the words the operator has to read back to the client.

    NAMED `Team...` RATHER THAN `MemberRemovedOut`, which is what it was called for one
    commit. `tenancy/routes.py` already exports a model of that name and a structurally
    identical shape, and two same-named models make the generator emit BOTH under
    collision-qualified keys (`apps__api__tenancy__routes__MemberRemovedOut`) — which
    silently breaks every `components["schemas"]["MemberRemovedOut"]` alias already
    written in `lib/api/members.ts`. That is the exact failure `scripts/
    check_openapi_fresh.py` records in its own docstring, and it is invisible to
    `tsc` on the branch that causes it, because the frontend compiles against a snapshot
    nobody regenerated.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    previous_role: str
    #: Leads they still own. Restated in the ANSWER as well as on the roster, because the
    #: number can move between the screen being drawn and the button being pressed, and
    #: this one was counted inside the removing transaction.
    leads_still_assigned: int


async def _roster(
    session: AsyncSession, *, limit: int, user_id: UUID | None = None
) -> list[TeamMemberOut]:
    """`_ROSTER_SQL` in the caller's tenant scope, mapped by NAME rather than by index.

    By name because this select has eight columns and two of them are timestamps that
    mean opposite things (`email_verified_at` is good news, `deactivated_at` is not) — an
    off-by-one in a positional unpack would swap them silently, and the screen would read
    plausibly either way round.

    `user_id` narrows it to one person. It is a filter on top of the policy and never
    instead of it: RLS still decides which memberships exist on this session, so naming a
    foreign id here returns nothing rather than somebody else's row.
    """
    rows = (
        (
            await session.execute(
                text(_ROSTER_SQL), {"limit": limit, "user_id": str(user_id) if user_id else None}
            )
        )
        .mappings()
        .all()
    )
    return [
        TeamMemberOut(
            user_id=row["user_id"],
            name=row["name"],
            email=row["email"],
            role=row["role"],
            joined_at=row["created_at"],
            email_verified=row["email_verified_at"] is not None,
            deactivated=row["deactivated_at"] is not None,
            leads_assigned=row["leads"],
        )
        for row in rows
    ]


@router.get(
    "",
    response_model=list[TeamMemberOut],
    openapi_extra=permission_meta("org:read"),
    summary="Who can sign in to this client's account right now",
    description=(
        "Everyone holding a membership of this account: their role, when they redeemed "
        "their invitation, whether they have verified their address, whether the person "
        "has been deactivated platform-wide, and how many of this client's leads are "
        "assigned to them. This is the surface the invitation list stops at — an "
        "invitation is a key in an inbox, and this is a key that has been used. A tenant "
        "id that names no client answers 404 rather than an empty list, because 'nobody "
        "has access to this account' is a claim that must not be made about a typo."
    ),
)
async def list_tenant_members(
    tenant_id: UUID,
    request: Request,
    # BEFORE `limit`, which carries a default: the `Annotated` alias is this repo's idiom
    # for a dependency (a `Depends(...)` default is refused by ruff's B008 outside files
    # literally named `routes.py`) and an annotated parameter has no default to sit after
    # one.
    principal: Reader,
    limit: int = Query(MEMBER_LIMIT, ge=1, le=MEMBER_LIMIT),
) -> list[TeamMemberOut]:
    """`org:read`, NOT `admin:tenants` — see the module docstring for D-22's rule.

    THE TENANCY CONTROL IS THE JOIN, and it is the same one `tenancy/routes.list_members`
    argues: `users` is a GLOBAL table with no RLS, so a query driven from it would return
    every user of the platform; `memberships` is FORCE-RLS'd on `tenant_id`, so driving
    from it is what scopes the answer. There is no `WHERE tenant_id` here, deliberately —
    a hand-written filter is a filter that can be forgotten, and its presence invites
    trusting it instead of the policy. `tenant_session` sets only `app.tenant_id`, so the
    membership policy's second clause (`user_id = app.user_id`, the auth bootstrap's one
    widening) evaluates to NULL on this session and grants it nothing.

    The lead count is a correlated subquery over `leads`, which is tenant-policied on the
    same session: an operator cannot learn from this screen how much work somebody does
    for a DIFFERENT client, even when the person is on both.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        members = await _roster(scoped, limit=limit)
        # D-482 L-1: who works at this business, and their addresses, is the client's own
        # data being looked at by us.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return members


@router.patch(
    "/{user_id}",
    response_model=TeamMemberOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Move somebody between owner and staff on this client's account",
    description=(
        "Changes one person's role. `expected_role` must be the role the console was "
        "showing: if the client changed it themselves in the meantime the request is "
        "refused with 409 `member_role_changed_elsewhere` rather than applying a click "
        "made against a stale picture. Demoting the last owner is refused with 409 "
        "`last_owner_protected` — an account with no owner cannot invite anybody, change "
        "a role or manage its own settings. Setting the role somebody already holds is a "
        "no-op and writes no audit row."
    ),
)
async def set_tenant_member_role(
    tenant_id: UUID,
    user_id: UUID,
    payload: TeamMemberRoleIn,
    request: Request,
    principal: Manager,
) -> TeamMemberOut:
    """No step-up: reversible by the same operator on the same screen (module docstring).

    `actor_user_id` is the OPERATOR's own `users.id` where they have one. Operators
    authenticate against `admin_users`, so it is ordinarily `None` here and
    `members._refuse_self` is then vacuous — but the founder's account can be both, and
    passing the id means "nobody acts on themselves" keeps holding for the one person on
    this platform for whom it can bite.

    The role change and its audit row share one transaction, for the reason every write in
    this package gives: a grant of authority whose record failed to commit is a grant
    nobody can later account for.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        previous = await members_service.assign_member_role(
            scoped,
            actor_user_id=principal.user_id,
            target_user_id=user_id,
            new_role=payload.role,
            expected_role=payload.expected_role,
        )
        if previous != payload.role:
            await write_audit(
                scoped,
                # THE TRANSITION IS IN THE ACTION NAME, because `audit_log` has no detail
                # column that is hashed — `summary` goes to the log stream and not into
                # the row (see `write_audit`). `tenancy/routes.set_member_role` spells its
                # own the same way; the `admin.` prefix is what says an OPERATOR did this
                # rather than one of the client's owners, which is the question a client
                # asking "who promoted them?" is actually asking.
                action=f"admin.member_role_changed:{previous}->{payload.role}",
                actor=principal,
                tenant_id=tenant_id,
                object_type="membership",
                # The TARGET's `users.id`. `users` rows outlive memberships, so this stays
                # resolvable after the person is removed — which is exactly the case a
                # reader asking "why did they have access?" is asking about.
                object_id=str(user_id),
                ip=client_request_ip(request),
            )
        # ONE row, read back inside the same transaction as the write it describes, so the
        # answer cannot be a stale picture and cannot depend on where this person sorted
        # in a bounded page.
        changed = await _roster(scoped, limit=1, user_id=user_id)
    if not changed:
        # Unreachable in practice: the write above 404s on a user who is not a member of
        # this account, and it holds the same transaction. Raised rather than asserted so
        # that if it ever does happen the operator gets a sentence, not an IndexError.
        raise ProblemError.not_found("Member")
    return changed[0]


@router.delete(
    "/{user_id}",
    response_model=TeamMemberRemovedOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Take somebody's access to this client's account away",
    description=(
        "Deletes the membership: the person can no longer sign in to this account, from "
        "their very next request. Their user account, the leads they own and the "
        "timeline entries naming them all survive — the leads stay assigned to them, and "
        "the count is returned so it can be said out loud. Needs the header "
        "`X-Confirm-Action: remove_member_access:<tenant_id>:<user_id>` and a second "
        "factor proved recently. Refused with 409 `last_owner_protected` for the only "
        "owner, and with 409 `member_removed_elsewhere` if somebody removed them first. "
        "THERE IS NO UNDO: the way back is a fresh invitation the person must redeem "
        "themselves."
    ),
)
async def remove_tenant_member(
    tenant_id: UUID,
    user_id: UUID,
    request: Request,
    principal: Manager,
    # Resolved BEFORE this handler body runs, so its session read cannot happen inside an
    # open transaction (`core/stepup.py` on `max_overflow=0`).
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TeamMemberRemovedOut:
    """The step-up first, then the work — so a refused confirmation changed nothing.

    `members.remove_member` holds every invariant: nobody removes themselves, the last
    owner cannot be removed, the lead count is taken BEFORE the delete, and the delete is
    a CAS so two operators removing one person is one removal and one 409.
    """
    step_up.require(x_confirm_action, remove_member_confirmation(tenant_id, user_id))

    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        previous, still_assigned = await members_service.remove_member(
            scoped, actor_user_id=principal.user_id, target_user_id=user_id
        )
        await write_audit(
            scoped,
            # The role they HELD when access was taken away — the fact a later reader
            # needs, and the one the deleted row can no longer supply.
            action=f"admin.member_removed:{previous}",
            actor=principal,
            tenant_id=tenant_id,
            object_type="membership",
            object_id=str(user_id),
            ip=client_request_ip(request),
            summary={"leads_still_assigned": still_assigned},
        )
    return TeamMemberRemovedOut(
        user_id=user_id, previous_role=previous, leads_still_assigned=still_assigned
    )


__all__ = ["MEMBER_LIMIT", "remove_member_confirmation", "router"]

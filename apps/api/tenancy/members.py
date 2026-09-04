"""Client-realm team management: who is on this account, and who may change that.

ROADMAP M3's third leg. Lead assignment and the `lead_events` timeline shipped first
and both NAME colleagues; until this module existed the only way to add, promote or
remove one of those colleagues was a Calevate operator running SQL. That is a support
ticket for a routine act, and — worse — an audit trail whose actor is always "us".

Everything here is one of two shapes: a check that stops a privilege from being
granted, or a write that records who granted it. The CRUD is incidental.

## The escalation surface, enumerated (each defence is named beside the code)

1. `staff` promoting themselves — `org:manage` is owner-only, so the route is refused
   before this module runs.
2. an owner acting on THEMSELVES — refused outright (`_refuse_self`), so neither a
   mis-click nor a clickjacked owner can demote or remove the person holding the
   session. Every act on this surface is other-directed.
3. tenant A touching tenant B — the RLS policy on `memberships` is the whole control:
   every statement below runs under `deps.db`'s tenant session and carries NO
   `WHERE tenant_id`, exactly as `list_members` argues. A foreign user id simply
   matches no row and 404s.
4. granting a role the granter does not hold — `assert_role_is_grantable`, expressed as
   a permission-set subset rather than a role name list, so it stays right when a third
   role lands.
5. an invitation redeemed by the wrong person — the accept route binds the invitation to
   the address it was issued to (see `tenancy/routes.py::accept_invitation`).
6. an invitation replayed after revocation or use — revocation DELETES the row, and the
   burn is already a CAS on `used_at IS NULL` (`admin.service.accept_invitation`).
7. two owners demoting each other concurrently — `lock_owner_ids`, below.

## What is deliberately NOT here

Reassigning a removed member's leads. See `remove_member`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.db.result import rowcount_of

# The roles a client account can hold. Mirrors `tenancy.models.MEMBER_ROLES` and the
# `ck_memberships_role_enum` CHECK; imported from there rather than retyped so the two
# cannot drift.
from apps.api.tenancy.models import MEMBER_ROLES

__all__ = [
    "MEMBER_ROLES",
    "PendingInvitation",
    "assert_role_is_grantable",
    "change_member_role",
    "create_team_invitation",
    "list_pending_invitations",
    "lock_owner_ids",
    "remove_member",
    "revoke_invitation",
]


def assert_role_is_grantable(actor_role: str | None, target_role: str) -> None:
    """You may only hand out authority you hold.

    Written as a SUBSET of permission sets, not as a list of allowed (from, to) pairs.
    Today the only client roles are `owner` and `staff` and an owner outranks staff on
    every permission, so any pair-list would be correct and would silently become wrong
    the day a third role lands that holds something `owner` does not. The subset test
    keeps answering the question that actually matters — "could the granter do this
    themselves?" — for whatever the role table grows into.

    This is the check that stops an invitation from carrying a role its sender does not
    hold, which is the same escalation as a role change and must not have a second,
    weaker implementation on the invite path.
    """
    if target_role not in MEMBER_ROLES:
        raise ProblemError(
            kind="validation",
            code="member_role_unknown",
            title="Unknown role",
            detail=f"{target_role!r} is not a role on this account.",
            remediation=f"Use one of: {', '.join(MEMBER_ROLES)}.",
        )
    granted = ROLE_PERMISSIONS.get(target_role, frozenset())
    held = ROLE_PERMISSIONS.get(actor_role or "", frozenset())
    if not granted <= held:
        raise ProblemError.forbidden(
            "You cannot give someone access wider than your own.",
        )


def _refuse_self(actor_user_id: UUID | None, target_user_id: UUID) -> None:
    """Nobody changes their own role or removes themselves.

    Two reasons, and the second is the one that generalises. The obvious one: an owner
    who demotes themselves by mis-click has no way back — the permission they would need
    to undo it is the one they just gave up. The general one: every act on this surface
    being OTHER-directed makes a whole class of attack uninteresting. A clickjacked or
    socially-engineered owner cannot be made to reduce their own access, and the
    last-owner rule below can never be defeated by a self-inflicted change (the classic
    "the only owner leaves and locks the tenant" bug).

    The cost is real and accepted: a sole owner who wants to leave must first promote a
    colleague. That is one extra step, and it is the step that keeps the account
    governable.
    """
    if actor_user_id is not None and actor_user_id == target_user_id:
        raise ProblemError.business_rule(
            "member_self_change_refused",
            "You cannot change your own role or remove yourself from this account.",
            remediation="Ask another owner to make this change for you.",
        )


async def lock_owner_ids(session: AsyncSession) -> set[UUID]:
    """Lock every owner row of THIS tenant and return their user ids.

    THE LAST-OWNER RULE IS A LOCK, NOT A COUNT. The naive form —
    `SELECT count(*) ... WHERE role='owner'`, then UPDATE if it is greater than one — is
    read-then-write, and under READ COMMITTED two transactions demoting two different
    owners each read `2`, each decide they are safe, and the account commits its way to
    zero owners. That tenant can then never invite, re-role or change its own caps
    again; only we can fix it, by hand, in SQL.

    `SELECT ... FOR UPDATE` closes it because of a property of READ COMMITTED that is
    worth stating rather than assuming: when a locked row has been concurrently updated,
    Postgres waits for the other transaction, then RE-EVALUATES the WHERE clause against
    the new row version and drops the row if it no longer matches (PostgreSQL docs §13.2
    "Read Committed Isolation Level"; the EvalPlanQual recheck,
    https://www.postgresql.org/docs/current/transaction-iso.html). So the second demoter
    blocks here, and when it resumes the owner the first one demoted is simply no longer
    in the set — it sees one owner, and refuses.

    That recheck has a documented limitation — it re-examines only the LOCKED rows and
    is blind to changes in rows the query never selected
    (https://www.cybertec-postgresql.com/en/transaction-anomalies-with-select-for-update/).
    It does not bite here, and the reason is the reason this locks the whole set rather
    than the one row being changed: every write that can REDUCE the owner count is a
    write to a row where `role = 'owner'`, and this statement locks all of them. The
    writes it does not lock — a staff member being promoted, a new owner accepting an
    invitation — only ever move the count up.

    `ORDER BY user_id` so that concurrent callers take the locks in the same order and
    queue instead of deadlocking (`LockRows` sits above the sort in the plan).

    The tenancy control is the RLS policy on `memberships`, not a WHERE clause: this runs
    under the request's tenant session, so "every owner" means every owner of the caller's
    own account and cannot be made to mean anything else.
    """
    rows = (
        await session.execute(
            text("SELECT user_id FROM memberships WHERE role = 'owner' ORDER BY user_id FOR UPDATE")
        )
    ).all()
    return {UUID(str(row[0])) for row in rows}


def _assert_an_owner_remains(owner_ids: set[UUID], losing_owner: UUID) -> None:
    if owner_ids - {losing_owner}:
        return
    raise ProblemError.business_rule(
        "last_owner_protected",
        "This is the only owner on the account, so their access cannot be reduced.",
        remediation=(
            "Make someone else an owner first — an account with no owner cannot invite "
            "people, change roles or manage its own settings."
        ),
    )


async def _member_role(session: AsyncSession, user_id: UUID) -> str:
    """The target's current role, or 404. RLS scopes it; a foreign user id is a 404 for
    the same reason another tenant's lead id is (`ProblemError.not_found` says why)."""
    row = (
        await session.execute(
            text("SELECT role FROM memberships WHERE user_id = :u"), {"u": user_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Member")
    return str(row[0])


async def change_member_role(
    session: AsyncSession,
    *,
    actor_user_id: UUID | None,
    actor_role: str | None,
    target_user_id: UUID,
    new_role: str,
    expected_role: str,
) -> str:
    """Move one colleague between roles. Returns the role they held before.

    `expected_role` is a CAS on what the caller was LOOKING at when they clicked
    (BACKEND-PATTERNS §5: write the guard into the WHERE clause and treat
    `rowcount == 0` as having lost the race). It costs the caller nothing — the value is
    already on their screen — and it buys two things a bare `SET role = :new` does not:
    a second owner's change in the intervening seconds is reported instead of silently
    overwritten, and a request replayed against a team that has since changed is refused
    rather than reapplied.
    """
    _refuse_self(actor_user_id, target_user_id)
    assert_role_is_grantable(actor_role, new_role)

    # Locks BEFORE reading the target's role, so the value this decision rests on cannot
    # move underneath it. Also the ordering that keeps concurrent callers from
    # deadlocking: every writer on this surface takes this same lock first.
    owner_ids = await lock_owner_ids(session)
    current = await _member_role(session, target_user_id)
    if current == new_role:
        # Not an error: two owners clicking the same promotion is one promotion. Returned
        # as a no-op so the caller's screen agrees with the database, and deliberately
        # NOT audited — an audit row saying nothing changed is noise in the one log that
        # must stay readable a year later.
        return current
    if current == "owner":
        _assert_an_owner_remains(owner_ids, target_user_id)

    changed = await session.execute(
        text(
            "UPDATE memberships SET role = :new, updated_at = now() "
            "WHERE user_id = :u AND role = :expected"
        ),
        {"new": new_role, "u": target_user_id, "expected": expected_role},
    )
    if rowcount_of(changed) == 0:
        raise ProblemError.conflict(
            "member_role_changed_elsewhere",
            "This person's role was changed by someone else while you were looking.",
            remediation="Reload the team list and try again.",
        )
    return current


async def remove_member(
    session: AsyncSession, *, actor_user_id: UUID | None, target_user_id: UUID
) -> tuple[str, int]:
    """Take someone off the account. Returns (role they held, leads still assigned).

    ## Removal is not deletion, and this deletes exactly one row

    The membership row goes; the `users` row, the leads they own and the `lead_events`
    they appear on all stay. That is not laziness, it is the shape the rest of the
    codebase was already written for:

    - **The lead's owner name** resolves through `memberships`, not `users`
      (`crm.service._LEAD_OWNER_JOIN`), precisely so that an id this account can no
      longer vouch for renders as "no longer on this account" instead of naming a
      stranger. The same is true of the timeline's actor names
      (`crm.service._member_names`). Removing the membership therefore makes every
      surface tell the truth by itself: the work is still there, attributed to somebody
      who is no longer here.
    - **`leads.assigned_to` is NOT cleared.** It is a foreign key to `users` with
      `ON DELETE SET NULL`, and we delete no user, so nothing is silently unassigned.
      The rejected alternative was to `UPDATE leads SET assigned_to = NULL` here: it
      would erase the answer to "who was working this?" from every lead at once, it
      would do so with no `lead_events` row to explain it (writing one from this module
      would be a second producer of an event `crm.service` owns), and the leads would
      quietly become nobody's. Instead the COUNT is returned, the screen states it, and
      reassignment stays where reassignment lives.
    - **The audit row survives the join that would lose it.** `audit_log.object_id`
      carries the removed person's `users.id`, which outlives their membership — so
      "why did this person have access, and who took it away" is answerable a year
      later. A reader who joins `audit_log` to `memberships` sees nothing for exactly
      the people they are most likely to be asking about; `users` is the join that
      keeps working.

    A soft `revoked_at` column was considered and rejected: the auth guard, the assignee
    check, the lead-owner join and the WhatsApp notifier would each have to learn to
    exclude it, and any one of them forgetting is a removed person who still has access.
    A row that is gone cannot be forgotten about.
    """
    _refuse_self(actor_user_id, target_user_id)

    owner_ids = await lock_owner_ids(session)
    role = await _member_role(session, target_user_id)
    if role == "owner":
        _assert_an_owner_remains(owner_ids, target_user_id)

    # Counted BEFORE the delete, and counted through `leads` directly: the number is
    # what the screen has to say out loud, so that removing someone can never quietly
    # orphan a pile of work.
    still_assigned = (
        await session.execute(
            text("SELECT count(*) FROM leads WHERE assigned_to = :u"), {"u": target_user_id}
        )
    ).scalar_one()

    removed = await session.execute(
        text("DELETE FROM memberships WHERE user_id = :u"), {"u": target_user_id}
    )
    if rowcount_of(removed) == 0:
        # Lost a race with another owner removing the same person. Same answer as the
        # role CAS, for the same reason.
        raise ProblemError.conflict(
            "member_removed_elsewhere",
            "This person was already removed by someone else.",
            remediation="Reload the team list.",
        )
    return role, int(still_assigned)


async def create_team_invitation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    actor_role: str | None,
    email: str,
    role: str,
) -> tuple[UUID, str]:
    """Invite a colleague. Returns (invitation id, RAW token — shown exactly once).

    The invitation itself is `admin.service.create_invitation`, reused rather than
    rewritten: it is single-use, 72h, `secrets.token_urlsafe(32)`, SHA-256 at rest, and
    burned by a CAS on accept. A second invitation mechanism for the client realm would
    be a second thing to get wrong, and the one that gets less scrutiny is the one that
    rots — the 2026 guidance on invite links (single use, short-lived, bound to the
    recipient's address) is met by that implementation plus the binding on the accept
    route.

    THE TWO REFUSALS MOVED INTO IT. "Already on this team" and "a live invitation for
    this address already exists" used to live here, which meant the admin wizard's
    invite path — the other caller — enforced neither, and its Create-invite button
    pressed twice minted two live owner credentials for one client. They are properties
    of minting an invitation, not of the client realm, so they now sit with the INSERT
    and both callers inherit them. What is left here is the one question that genuinely
    differs: an owner may only grant a role they hold, and an admin-realm operator has
    no membership role to compare against.
    """
    assert_role_is_grantable(actor_role, role)

    from apps.api.admin import service as admin_service

    return await admin_service.create_invitation(
        session, tenant_id=tenant_id, email=email, role=role, created_by=actor_user_id
    )


@dataclass(frozen=True, slots=True)
class PendingInvitation:
    """One live invitation. The route's response model mirrors these fields.

    `email` is the whole address (D-436). It used to be `p••••@clinic.in`, on the
    argument that an owner only has to RECOGNISE the invite they sent — which fails the
    moment two people at one domain are invited a week apart, and left the owner unable
    to see that the address they typed has a typo in it. Reading this list is
    `org:read`; nothing here is logged.
    """

    id: UUID
    email: str
    role: str
    invited_at: datetime
    expires_at: datetime
    #: WHEN THE LINK WAS LAST PUT IN THAT INBOX, and how many times it has been (D-536).
    #:
    #: `invited_at` alone answered the wrong question once a resend existed: it is when the
    #: invitation was MINTED, and after a resend the link in the mailbox is younger than
    #: that. An owner or an operator looking at "why has this person not signed up" needs
    #: the send, not the mint — and `send_count` is what turns "they still have not" into
    #: "we have sent this five times, telephone them instead".
    last_sent_at: datetime
    send_count: int


async def list_pending_invitations(
    session: AsyncSession, *, limit: int = 200
) -> list[PendingInvitation]:
    """Invitations that are still redeemable — the keys to this account that exist in
    somebody's inbox right now.

    Used ones are excluded because the person they created is on the team list, and an
    expired one is not a key. Both would otherwise turn this into a list of everyone
    ever invited, which is a different question and one nobody asked.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, email, role, created_at, expires_at, last_sent_at, send_count "
                "FROM invitations "
                "WHERE used_at IS NULL AND expires_at > now() ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return [
        PendingInvitation(
            id=UUID(str(row[0])),
            email=str(row[1]),
            role=str(row[2]),
            invited_at=row[3],
            expires_at=row[4],
            last_sent_at=row[5],
            send_count=int(row[6]),
        )
        for row in rows
    ]


async def revoke_invitation(session: AsyncSession, invitation_id: UUID) -> str:
    """Cancel an unused invitation. Returns the role it would have granted.

    DELETE, not a `revoked_at` column. An invitation exists to be redeemed once; a
    second terminal state would be a state every reader of the table has to remember,
    for a row whose only purpose is already over. The record that it happened lives
    where records of decisions live — `audit_log`, keyed to this id — which is the
    append-only side of hard rule 4 doing its job instead of a status column pretending
    to be history.

    `used_at IS NULL` in the WHERE clause makes this a CAS: an invitation accepted
    between the click and the request is NOT deleted, and the caller is told that the
    person is now on the team rather than being told the link is gone.
    """
    row = (
        await session.execute(
            text("DELETE FROM invitations WHERE id = :i AND used_at IS NULL RETURNING role"),
            {"i": invitation_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Invitation")
    return str(row[0])

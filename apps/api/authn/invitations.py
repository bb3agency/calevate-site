"""Redeeming an invitation without a vendor in the middle (D-170).

═══ THE URL CONTRACT THIS HAS TO FIT ═══

`apps/web/src/app/invite/page.tsx` already exists and already takes `/invite?token=...`.
That page is not changing in this slice (`apps/web` is out of scope), so the invariant this
module has to respect is: **the token still travels in the `token` query parameter of
`/invite`, and the page still POSTs it to the API.** What changes is which API call it
makes, and what else it has to send.

Today: the invitee signs up with Clerk FIRST, arrives at `/invite` already authenticated,
and `POST /v1/invitations/accept` takes `{token}` and reads the identity off the Clerk
session. The address binding is `users.email` (populated from Clerk's verified addresses)
compared against `invitations.email`.

First-party: there is no vendor to sign up with, so the invitee has NO ACCOUNT when they
open the link. The single call therefore has to do what the two calls used to:
`POST /v1/auth/client/invitations/accept` takes `{token, password, name}`, and it creates
the user, sets the password, creates the membership and issues a session — in that order,
and with the address taken from the INVITATION rather than from anything the caller typed.

**`POST /v1/invitations/accept` is untouched and still works.** Both paths coexist until
the cutover, which is the whole point of the flag; deleting the Clerk one is
AUTH-MIGRATION §5 step 6.

═══ WHY THE ADDRESS IS NEVER TAKEN FROM THE REQUEST ═══

The old flow had to COMPARE two addresses, because the account already existed and might
have been created with a different one — hence `invitation_wrong_recipient`, and hence that
refusal being a documented exception to this repo's non-disclosure rule.

Here there is nothing to compare: the account is being created now, and its address is the
one the invitation was sent to, full stop. The caller does not supply an address and could
not influence one if they tried. That is strictly stronger than the binding it replaces, it
removes the one enumeration-adjacent refusal from the flow, and it means a forwarded invite
link creates an account belonging to the ORIGINAL invitee's address — which is what
"single-use, bound to the recipient" is supposed to mean.

The address is also marked verified on creation, and that is sound rather than convenient:
possession of a token that was emailed to it IS proof the mailbox receives mail. That is the
same evidence an `email_verify` round trip produces, arrived at one step earlier.

═══ AN INVITATION FOR SOMEBODY WHO ALREADY HAS AN ACCOUNT ═══

Real and ordinary: one person can be staff at two client businesses (`memberships` is the
many-to-many). The user row is reused and **the password is NOT touched** — `has_password`
is checked first, and an existing credential is left exactly as it is. Overwriting it would
mean anybody who can get an invitation issued to your address can reset your password,
which turns an invite into an account takeover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import text

from apps.api.admin import service as admin_service
from apps.api.authn.credentials import set_password
from apps.api.authn.service import has_password
from apps.api.authn.sessions import IssuedSession, issue_session
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import (
    credential_session,
    invite_session,
    tenant_session,
    untenanted_session,
)

log = get_logger(__name__)

#: The client realm, spelled once. An invitation is always a CLIENT-realm artifact —
#: operators are added by `scripts/bootstrap_admin.py` and the ops console, never by an
#: emailed link, because `admin_users` is an allowlist and auto-creating a row in it is the
#: "privilege escalation wearing a race condition's clothes" `core/clerk_identity.py` names.
INVITE_REALM = "client"


@dataclass(frozen=True, slots=True)
class AcceptedInvitation:
    """What redeeming produced: the membership, and a session to walk in with."""

    tenant_id: UUID
    slug: str
    role: str
    user_id: UUID
    session: IssuedSession


def _invalid() -> ProblemError:
    """Unknown, used, expired — one answer, matching the existing Clerk path's wording so
    the two flows are indistinguishable to somebody probing tokens."""
    return ProblemError(
        kind="business_rule",
        code="invitation_invalid",
        title="Invitation is not usable",
        detail="This invitation has already been used or has expired.",
        remediation="Ask your account manager for a fresh invite.",
    )


async def accept_with_password(
    *, token: str, password: str, name: str | None, ip: str | None, now: datetime | None = None
) -> AcceptedInvitation:
    """Redeem an invitation, creating the account if there is not one already.

    ORDER MATTERS AND IS NOT NEGOTIABLE:

      1. read the invitation under `app.invite_hash` — the token names its own tenant, so
         this must happen before any tenant is known (the same widening
         `tenancy/routes.py::accept_invitation` uses);
      2. find or create the `users` row, OUTSIDE any tenant session, because `users` is
         global and creating it inside a tenant transaction would tie an identity's
         existence to one tenant's write succeeding;
      3. set the password only if there is not one already (see the module docstring);
      4. burn the invitation and create the membership under `tenant_session`, via the
         EXISTING `admin_service.accept_invitation` — one implementation of the CAS burn,
         not a second one that has to be kept in step;
      5. issue the session last, so a failure anywhere above leaves nobody signed in.
    """
    at = now or datetime.now(UTC)
    token_hash = sha256(token.encode()).hexdigest()

    async with invite_session(token_hash) as lookup:
        row = (
            await lookup.execute(
                text(
                    "SELECT tenant_id, email FROM invitations WHERE token_hash = :hash "
                    "AND used_at IS NULL AND expires_at > now()"
                ),
                {"hash": token_hash},
            )
        ).first()
    if row is None:
        log.info("auth_invitation_rejected")
        raise _invalid()
    tenant_id = UUID(str(row[0]))
    invited_email = str(row[1]).strip()

    user_id, created = await _find_or_create_user(email=invited_email, name=name, at=at)

    if not await has_password(INVITE_REALM, user_id):
        async with credential_session() as session:
            await set_password(
                session, realm=INVITE_REALM, subject_id=user_id, password=password, now=at
            )

    async with tenant_session(tenant_id) as scoped:
        await admin_service.accept_invitation(scoped, raw_token=token, user_id=user_id)
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
        # In the tenant transaction, exactly as the Clerk path does it, so the membership
        # and its evidence commit together.
        await write_audit(
            scoped,
            action="auth.invitation_accepted",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="membership",
            object_id=str(user_id),
            ip=ip,
            summary={"account_created": created},
        )

    async with credential_session() as session:
        issued = await issue_session(session, realm=INVITE_REALM, subject_id=user_id, now=at)
    return AcceptedInvitation(
        tenant_id=tenant_id,
        slug=str(slug),
        role=str(role or "owner"),
        user_id=user_id,
        session=issued,
    )


async def _find_or_create_user(*, email: str, name: str | None, at: datetime) -> tuple[UUID, bool]:
    """The `users` row for this address, creating it if this is a new person.

    `clerk_user_id` is left NULL, which migration `b3d9f6a2c815` made possible: a
    first-party account has no vendor id and inventing a placeholder would put a fake value
    under a UNIQUE constraint that the Clerk mirror still relies on.

    `email_verified_at` is set on creation — see the module docstring on why possession of
    the emailed token is the proof.

    The INSERT is guarded by a re-read rather than by `ON CONFLICT`, because there is no
    unique constraint on `users.email` to conflict against (migration `b3d9f6a2c815` says
    why it could not safely add one). Two simultaneous redemptions of the same invitation
    are already impossible — `accept_invitation`'s CAS admits one — so the only race this
    could lose is two DIFFERENT invitations to the same address arriving in the same
    millisecond, which yields a duplicate `users` row that `subjects.resolve_by_email`
    refuses loudly rather than resolving wrongly. That is the honest failure mode, and it
    is named here so the next reader does not have to derive it.
    """
    needle = email.casefold()
    async with untenanted_session() as session:
        existing = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = :e AND deactivated_at IS NULL"),
                {"e": needle},
            )
        ).first()
        if existing is not None:
            return UUID(str(existing[0])), False
        user_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, email_verified_at, "
                "created_at, updated_at) "
                "VALUES (:id, NULL, :email, :name, :at, :at, :at)"
            ),
            {"id": user_id, "email": email, "name": name, "at": at},
        )
    log.info("auth_user_created_from_invitation", extra={"user_id": str(user_id)})
    return user_id, True


__all__ = ["INVITE_REALM", "AcceptedInvitation", "accept_with_password"]

"""Redeeming an invitation without a vendor in the middle (D-170).

═══ THE URL CONTRACT ═══

The token travels in the `token` query parameter and the page POSTs it here. The page is
`apps/web/src/app/(auth)/auth/accept-invitation` (D-174); the Clerk-era `/invite?token=`
now answers `410 Gone` and points at it, rather than rotting as a second door
(D-177).

The vendor flow this replaced: the invitee signed up with Clerk FIRST, arrived at `/invite`
already authenticated, and `POST /v1/invitations/accept` took `{token}` and read the
identity off the Clerk session, binding on a comparison between `users.email` and
`invitations.email`.

First-party: there is no vendor to sign up with, so the invitee has NO ACCOUNT when they
open the link. The single call therefore does what the two calls used to:
`POST /v1/auth/client/invitations/accept` takes `{token, password, name}`, and it creates
the user, sets the password, creates the membership and issues a session — in that order,
and with the address taken from the INVITATION rather than from anything the caller typed.
It is the ONLY invitation-redemption endpoint this API has (D-177).

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

═══ THE ADDRESS IS *NOT* MARKED VERIFIED HERE, AND THIS PARAGRAPH USED TO SAY IT WAS ═══

The claim was: "possession of a token that was emailed to it IS proof the mailbox receives
mail — the same evidence an `email_verify` round trip produces, arrived at one step
earlier." Every clause of that is sound except its premise, and the premise is false in this
tree (D-185).

**The token was not emailed.** `InvitationCreatedOut.token` handed the raw token back to
the INVITER in the API response, because the client realm had no invitation mailer and the
owner was expected to send the link themselves. So possession of the token proved the
mailbox OR being the person who issued the invitation, and those are not the same fact.
`email_verified_at = now()` was therefore asserting something nobody had established, and
the vendor whose console used to establish it is gone (D-177): S-2's question survived the
deletion of the file S-2 pointed at.

**BOTH MINTING ROUTES NOW MAIL IT** — the client realm's since D-190, the admin realm's
`POST /v1/admin/tenants/{tenant_id}/invitations` since D-198 — so the premise has changed
and the paragraph below on what stays open has changed with it. The address still starts
UNVERIFIED, and that is now a considered position rather than a consequence: an invitation
mailed to a mailbox is evidence about that mailbox, but the only thing that makes it
evidence is a delivery this repo cannot yet observe (no mail provider is signed up —
`ConsoleTransport` is what runs). One round trip the invitee completes themselves is
evidence we hold; a send we cannot confirm is not.

What it bought an attacker, end to end, and none of the steps needs a defect anywhere else:
an owner of ANY tenant — a trial signup is enough — issues an invitation to
`victim@target.example`, reads the token out of their own 201 response, redeems it, and
gets a GLOBAL `users` row on an address they do not control, marked verified, holding a
password they chose. `uq_users_email_lower` guarantees that is the ONLY row for that
address. When the real target tenant later invites the real victim, the block below finds
that row, leaves the squatter's password alone (correctly — see the next section), and
attaches the membership to it. The squatter then signs in with their own password. The
client realm has no second factor (`service.MFA_REQUIRED_REALMS` is `{"admin"}`), so a
password is the entire credential.

So the address starts UNVERIFIED and becomes verified the way every other address in this
system does: an `email_verify` OTP round trip (`POST /v1/auth/client/otp/request` +
`/otp/verify` → `subjects.mark_email_verified`), which is already built, already registered
with the mailer, and already the thing `SessionOut.email_verified` reports.

WHAT WAS STILL OPEN AFTER D-185, and what closed it: a squatter could still take an address
hostage — the real person's redemption was refused instead of hijacked, which is a denial of
service rather than an account takeover, and that was a strict improvement rather than a
closure. D-185 named the one thing it did not do: stop the token being returned to the
inviter. **D-190 did it for the client realm's route and D-198 for the admin realm's**, so
the token now exists in the invited mailbox and nowhere else and there is nobody left who
can squat an address they do not control.

What that leaves is the ordinary residue of any emailed link: whoever reads the mailbox can
redeem it. That is the trust level the mechanism is FOR, and it is the reason the address
still has to be proved separately before the account may join a second organisation.

═══ AN INVITATION FOR SOMEBODY WHO ALREADY HAS AN ACCOUNT ═══

Real and ordinary: one person can be staff at two client businesses (`memberships` is the
many-to-many). The user row is reused and **the password is NOT touched** — `has_password`
is checked first, and an existing credential is left exactly as it is. Overwriting it would
mean anybody who can get an invitation issued to your address can reset your password,
which turns an invite into an account takeover.

That refusal to overwrite is right, and it is also what makes the squat stick: the honest
invitee cannot displace a credential somebody else set. So reuse now carries a condition —
**an account that already has a password may only take on a NEW membership once its address
has been proven.** A first membership still rides on the inviter vouching inside their own
tenant, which is the tenant they already control and where the invitation grants nothing
they could not grant anyway; a SECOND organisation asks for the mailbox.
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
from apps.api.authn.subjects import load_subject
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
#: "privilege escalation wearing a race condition's clothes" the retired Clerk mirror named.
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
    """Unknown, used, expired — one answer, keeping the wording the Clerk-era path used so
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

    # D-185. The one condition on reuse. Reached ONLY when this redemption did not create
    # the row and the row already carries a credential — i.e. somebody has signed in as this
    # address before, and it was not proved to be theirs. Ordered before the membership and
    # before the session so a refusal leaves nothing behind: the invitation is not burned
    # (`admin_service.accept_invitation` has not run), so the real owner can still redeem it
    # after verifying.
    #
    # `created` is checked first and is not redundant with `has_password`: a row this call
    # just inserted has no password yet, so the second clause would pass anyway — but only
    # by accident of ordering, and a later change that set the password earlier would
    # silently start refusing every first-time invitee.
    if not created and await has_password(INVITE_REALM, user_id):
        subject = await load_subject(INVITE_REALM, user_id)
        if subject is None or subject.email_verified_at is None:
            log.info("auth_invitation_refused_unverified_account", extra={"user_id": str(user_id)})
            raise ProblemError(
                kind="business_rule",
                code="invitation_account_unverified",
                title="Confirm your email address first",
                detail=(
                    "An account already exists for this address and its email address has "
                    "not been confirmed. It has to be confirmed before the account can join "
                    "another organisation."
                ),
                remediation=(
                    "Sign in to the account you already have, confirm the email address "
                    "from your account settings, then open this invitation again."
                ),
            )

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
        # In the tenant transaction, as the Clerk-era path did, so the membership
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

    UNDERSCORED, AND IT STAYS UNDERSCORED. It has two callers outside this module —
    `tests/authn_email_uniqueness_test.py` and `scripts/seed_dev.py` — and neither is a
    reason to drop the prefix, because the prefix is not hiding the function from them.
    What it marks is the SECOND return value: `created` answers "was this address already
    an account", which is precisely the enumeration oracle the `subjects.py` docstring
    exists to argue must not be reachable from any endpoint. The underscore is the signal
    to whoever next reaches for this from a route handler. A test and a local-only seed
    script import it deliberately; a request handler must not.

    `clerk_user_id` is not written, which migration `b3d9f6a2c815` made possible and D-177
    made permanent: nothing anywhere writes that column any more, and the column itself
    survives one more release under hard rule 8's two-step (recorded in
    `scripts/check_wiring.UNWIRED_BASELINE`).

    `email_verified_at` is NOT set here (D-185) — see the module docstring on why possession
    of the token is not proof of the mailbox while the token is handed to the inviter. The
    column is left NULL and an `email_verify` OTP round trip is what fills it.

    THE INSERT IS GUARDED BY `ON CONFLICT`, WHICH IT WAS NOT (D-178). It was a read then a
    write, because there was no unique constraint on `users.email` to conflict against; the
    race it could lose was two DIFFERENT invitations to the same address arriving in the same
    millisecond, and what it lost was a duplicate `users` row — after which
    `subjects.resolve_by_email` refused that address for BOTH people, loudly and forever, and
    a human had to merge rows before either could sign in. Migration `c7a1e93d40b8` adds
    `uq_users_email_lower` (unique on `lower(email)` where the row is live), so the race is
    now decided by the database: the loser's INSERT returns nothing, it re-reads, and it
    finds the winner's row. One live account per address, upheld by the constraint rather
    than by two callers arriving in a convenient order.

    The re-read after a conflict is not the old read repeated — `ON CONFLICT DO NOTHING`
    tells us a row exists but not which, and its id is the whole return value.
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
        inserted = (
            await session.execute(
                text(
                    # `clerk_user_id` is absent from the column list rather than written as
                    # NULL: D-177 says nothing writes it, and naming it here — even to say
                    # NULL — is what would have to be found and removed when hard rule 8's
                    # second step drops the column.
                    # `email_verified_at` is absent from the column list, not written as
                    # NULL: the default IS NULL, and naming it would read as a deliberate
                    # value rather than as the absence of a fact (D-185).
                    "INSERT INTO users (id, email, name, created_at, updated_at) "
                    "VALUES (:id, :email, :name, :at, :at) "
                    # The index predicate is repeated so Postgres can INFER the partial
                    # unique index; without it the statement is rejected outright rather
                    # than silently matching a different constraint.
                    "ON CONFLICT (lower(email)) WHERE deactivated_at IS NULL DO NOTHING "
                    "RETURNING id"
                ),
                {"id": user_id, "email": email, "name": name, "at": at},
            )
        ).first()
        if inserted is None:
            winner = (
                await session.execute(
                    text("SELECT id FROM users WHERE lower(email) = :e AND deactivated_at IS NULL"),
                    {"e": needle},
                )
            ).first()
            if winner is None:  # pragma: no cover — the conflicting row was deactivated
                # between the INSERT and this read, which no application path does.
                raise ProblemError.conflict(
                    "account_address_contended",
                    "That address is being claimed by another request right now.",
                    remediation="Try the invitation link again in a moment.",
                )
            log.info("auth_user_insert_lost_race", extra={"user_id": str(winner[0])})
            return UUID(str(winner[0])), False
    log.info("auth_user_created_from_invitation", extra={"user_id": str(user_id)})
    return user_id, True


__all__ = ["INVITE_REALM", "AcceptedInvitation", "accept_with_password"]

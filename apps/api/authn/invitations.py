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
`POST /v1/admin/tenants/{tenant_id}/invitations` since D-198 — so the token exists in the
invited mailbox and nowhere else, and redeeming it proves the mailbox (D-955's premise).
**So the address IS marked proved when a redemption sets the account's first password**
(audit of 8 Nov 2026). Leaving it unproved made every invitee's real account look like a
squat to the reclaim below, and the holder of any later invitation to that address could
replace its password.

What D-185's world bought an attacker, while the inviter could read the token: an owner of
ANY tenant — a trial signup is enough — issues an invitation to
`victim@target.example`, reads the token out of their own 201 response, redeems it, and
gets a GLOBAL `users` row on an address they do not control, marked verified, holding a
password they chose. `uq_users_email_lower` guarantees that is the ONLY row for that
address. When the real target tenant later invites the real victim, the block below finds
that row, leaves the squatter's password alone (correctly — see the next section), and
attaches the membership to it. The squatter then signs in with their own password. The
client realm has no second factor (`service.MFA_REQUIRED_REALMS` is `{"admin"}`), so a
password is the entire credential.

D-190 and D-198 closed that squat: the token now exists in the invited mailbox and nowhere
else, so whoever redeems it reads that mailbox. An unproved account with a password is
therefore one made before then (or a self-serve signup from before D-703), which is what the
reclaim below is for.

═══ AN INVITATION FOR SOMEBODY WHO ALREADY HAS AN ACCOUNT ═══

Real and ordinary: one person can be staff at two client businesses (`memberships` is the
many-to-many). What happens depends on whether that account's address is proved.

**Proved address, with a password: the password is NOT touched.** Overwriting it would mean
anybody holding an invitation to your address — a forwarded link — could reset your
password. The typed password must BE that account's (`_prove_existing_account`), because the
session issued below is a session as that account in every organisation it belongs to.

**Unproved address, with a password: the mailbox owner reclaims it (D-955, amending
D-185).** Such a credential is exactly what an account pre-hijacker leaves behind — register
the victim's address with a password of your choosing and wait (Sudhodanan & Paverd,
"Pre-hijacked accounts", USENIX Security 2022, §6.2: verify the identifier before the
account is usable, and invalidate other sessions and credentials when the owner proves
it). D-185 refused this redemption instead, which kept the squatter out and the owner out
with them: the honest invitee was told to sign in to an account whose password they may
never have set. The redeemed token is the better claim of the two — it reached the mailbox,
the unproved password never proved anything — so the typed password REPLACES the old one,
every session of the account is revoked in the same transaction, and the address is marked
proved. The account's earlier memberships stay; a reclaim changes who holds the account, not
what it belongs to.

**No password, proved address (a Google account): refused** — it accepts with Google.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.authn.credentials import set_password
from apps.api.authn.service import has_password
from apps.api.authn.sessions import IssuedSession, issue_session, revoke_subject_sessions
from apps.api.authn.subjects import load_subject, mark_email_verified
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
from apps.api.tenancy.lifecycle import assert_account_open

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
    business_name: str | None = None


@dataclass(frozen=True, slots=True)
class JoinedWorkspace:
    """A membership created for somebody who is already signed in."""

    tenant_id: UUID
    slug: str
    role: str


def invitation_unusable() -> ProblemError:
    """Unknown, used, expired — one answer, keeping the wording the Clerk-era path used so
    the two flows are indistinguishable to somebody probing tokens."""
    return ProblemError(
        kind="business_rule",
        code="invitation_invalid",
        title="Invitation is not usable",
        detail="This invitation has already been used or has expired.",
        remediation="Ask us for a fresh invite.",
    )


async def accept_with_password(
    *, token: str, password: str, name: str | None, ip: str | None, now: datetime | None = None
) -> AcceptedInvitation:
    """Redeem an invitation, creating the account if there is not one already.

    ORDER MATTERS AND IS NOT NEGOTIABLE:

      1. read the invitation under `app.invite_hash` — the token names its own tenant, so
         this must happen before any tenant is known (the same widening
         `tenancy/routes.py::accept_invitation` uses), then open the tenant transaction
         that burns it, take the invitation's redemption lock there and read it again
         (`_hold_redemption`); steps 2-4 run while that lock is held;
      2. find or create the `users` row, OUTSIDE any tenant session, because `users` is
         global and creating it inside a tenant transaction would tie an identity's
         existence to one tenant's write succeeding;
      3. set the password only if there is not one already, or replace an unproved one
         and revoke its sessions (see the module docstring), then mark the address proved
         — all before anything below, so a refused password changes
         nothing and the invitation stays redeemable;
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
                    "SELECT tenant_id, email, invitee_name, invitee_phone FROM invitations "
                    "WHERE token_hash = :hash "
                    "AND used_at IS NULL AND expires_at > now()"
                ),
                {"hash": token_hash},
            )
        ).first()
    if row is None:
        log.info("auth_invitation_rejected")
        raise invitation_unusable()
    tenant_id = UUID(str(row[0]))
    invited_email = str(row[1]).strip()

    async with tenant_session(tenant_id) as scoped:
        await _hold_redemption(scoped, token_hash)
        # Refused BEFORE any credential is written. `admin_service.accept_invitation` asks
        # the same question again at the burn, but by then a password has been set and
        # sessions revoked in their own transaction, and the refusal rolls back only the
        # burn — so an invitation to a closed account stayed redeemable and every replay
        # rewrote a password.
        await assert_account_open(scoped, tenant_id=tenant_id)
        # The name typed at acceptance wins; the operator's copy fills a blank one (D-695).
        user_id, created = await _find_or_create_user(
            email=invited_email, name=name or row[2], phone=row[3], at=at
        )

        # D-955 (amends D-185). An existing account with a password whose address was
        # never proved is RECLAIMED by the mailbox owner rather than refused: this token was
        # mailed to the address and nowhere else (D-190, D-198), so redeeming it proves the
        # mailbox, and the unproved credential may be a pre-hijacker's (Sudhodanan & Paverd,
        # USENIX Security 2022, §6.2). The typed password replaces it and every session it
        # opened is revoked. A PROVED account keeps D-185's rule: the typed password must be
        # its current one.
        #
        # `created` is checked first and is not redundant with `has_password`: a row this
        # call just inserted has no password yet, so the second clause would pass anyway —
        # but only by accident of ordering, and a later change that set the password earlier
        # would silently start treating every first-time invitee as a reclaim.
        reclaiming = (
            not created
            and await has_password(INVITE_REALM, user_id)
            and not await _address_proved(user_id)
        )

        if not created and not reclaiming:
            await _prove_existing_account(user_id, password=password, at=at, ip=ip)

        revoked = 0
        first_password = not reclaiming and not await has_password(INVITE_REALM, user_id)
        if reclaiming or first_password:
            async with credential_session() as session:
                await set_password(
                    session,
                    realm=INVITE_REALM,
                    subject_id=user_id,
                    password=password,
                    # The address the invitation was issued to, which IS this account's
                    # identity — the blocklist refuses a password that is nothing but a
                    # decorated form of it (NIST §3.1.1.2's "username, and derivatives
                    # thereof"). Taken from the invitation row rather than re-read, because
                    # `_find_or_create_user` may have written that row moments ago.
                    email=invited_email,
                    now=at,
                )
                # Same transaction as the write (`set_password`'s contract). Zero rows for
                # an account that never had a password; on a reclaim, every session the
                # unproved credential opened, so a pre-hijacker's live cookie dies with
                # their password.
                revoked = await revoke_subject_sessions(
                    session, realm=INVITE_REALM, subject_id=user_id, now=at
                )
        if reclaiming or first_password:
            # After the password, so a password the policy refuses leaves the address
            # exactly as unproved as it was and the invitation unburned for the retry.
            #
            # A FIRST password is marked proved too, on D-955's own premise: the token
            # reached this mailbox and nowhere else. Leaving it unproved is what made the
            # reclaim above a takeover: the invitee's real, in-use account looked like a
            # squat, and the holder of any LATER invitation to the address (a forwarded
            # link is enough) replaced its password and signed in as it in every
            # organisation it belongs to.
            await mark_email_verified(INVITE_REALM, user_id, at=at)
            if reclaiming:
                log.info(
                    "auth_invitation_reclaimed_unverified_account",
                    extra={"user_id": str(user_id)},
                )

        await admin_service.accept_invitation(scoped, raw_token=token, user_id=user_id)
        role = (
            await scoped.execute(
                text("SELECT role FROM memberships WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()
        org = (
            await scoped.execute(
                text("SELECT slug, name FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).one()
        slug, business_name = org[0], org[1]
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
        if reclaiming:
            await write_audit(
                scoped,
                action="auth.invitation_reclaimed_unverified_account",
                actor_type="user",
                tenant_id=tenant_id,
                object_type="auth_subject",
                object_id=str(user_id),
                ip=ip,
                summary={"sessions_revoked": revoked},
            )

    async with credential_session() as session:
        issued = await issue_session(session, realm=INVITE_REALM, subject_id=user_id, now=at)
    return AcceptedInvitation(
        tenant_id=tenant_id,
        slug=str(slug),
        role=str(role or "owner"),
        user_id=user_id,
        session=issued,
        business_name=str(business_name) if business_name else None,
    )


async def _hold_redemption(scoped: AsyncSession, token_hash: str) -> None:
    """Serialise redemptions of one invitation, and refuse the ones that arrive too late.

    Called first in the tenant transaction that burns the invitation, so the lock is
    released by exactly the COMMIT or ROLLBACK that decides whether it was burned. The burn
    is a CAS, but the credential writes before it commit in their own transactions
    (`credential_session` is a separate connection by design, D-165), so without this a
    second press of the same link set the password again and revoked every session of the
    account before losing the CAS, and could land that revoke after the winner's
    `issue_session`, signing the new member out. Claiming the invitation first instead
    would burn it before the password policy has spoken, and a refused password must leave
    it redeemable.

    The second read is the one that counts: under READ COMMITTED it runs after the
    winner's commit, so the loser sees the burn and writes nothing.
    """
    await scoped.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"invitation_accept:{token_hash}"},
    )
    redeemable = (
        await scoped.execute(
            text(
                "SELECT 1 FROM invitations WHERE token_hash = :hash "
                "AND used_at IS NULL AND expires_at > now()"
            ),
            {"hash": token_hash},
        )
    ).first()
    if redeemable is None:
        log.info("auth_invitation_rejected")
        raise invitation_unusable()


async def _address_proved(user_id: UUID) -> bool:
    subject = await load_subject(INVITE_REALM, user_id)
    return subject is not None and subject.email_verified_at is not None


async def _prove_existing_account(
    user_id: UUID, *, password: str, at: datetime, ip: str | None
) -> None:
    """An invitation adds a membership to an account that already exists; it must not also
    sign the link holder in as that account, or give it a password.

    The link is a key to the MEMBERSHIP, and it gets forwarded. Before this check a holder
    redeeming against an existing account had the password they typed ignored and was handed
    a session for every organisation that account belongs to; against a Google-only account
    the typed password was stored, a lasting credential nobody was told about. So:

    - an account with a password: the typed password must be that account's, metered
      against the same password budgets sign-in spends, so this is no unmetered oracle;
    - an account with no password whose address is already proved (Google, D-703): refused
      — it accepts with Google, the way it signs in;
    - an account with no password and an unproved address is the row an earlier redemption
      of THIS flow created before its password was refused, and the retry sets it as before.
    """
    from apps.api.authn.credentials import authenticate_subject
    from apps.api.authn.service import _equalise
    from apps.api.authn.throttle import clear_password, reserve_password

    if await has_password(INVITE_REALM, user_id):
        attempt = await reserve_password(realm=INVITE_REALM, subject_id=user_id, source=ip)
        async with credential_session() as session:
            ok = await authenticate_subject(
                session, realm=INVITE_REALM, subject_id=user_id, password=password, now=at
            )
        if not ok:
            await _equalise(attempt)
            log.info("auth_invitation_existing_password_wrong", extra={"user_id": str(user_id)})
            raise ProblemError(
                kind="auth",
                code="invitation_existing_account_password",
                title="Enter the password of your existing account",
                detail=(
                    "An account already exists for this address. Joining with this "
                    "invitation needs that account's current password."
                ),
                remediation=(
                    "Type the password you sign in with, or reset it from the sign-in page "
                    "and open this invitation again."
                ),
            )
        await clear_password(realm=INVITE_REALM, subject_id=user_id, source=ip)
        return
    subject = await load_subject(INVITE_REALM, user_id)
    if subject is not None and subject.email_verified_at is not None:
        log.info("auth_invitation_password_on_proved_account", extra={"user_id": str(user_id)})
        raise ProblemError(
            kind="business_rule",
            code="invitation_use_google",
            title="Accept with Google",
            detail=(
                "An account already exists for this address and signs in with Google, so "
                "this invitation cannot give it a password."
            ),
            remediation="Choose 'Accept with Google' on this page.",
        )


async def invited_address(token: str) -> str | None:
    """The address a still-redeemable invitation was sent to, or None. Read-only.

    For the Google path, which must decide whether a person with no account may have one
    made BEFORE the invitation is burned: an invitation to the address Google has just
    vouched for is the owner's leave to create that account, whatever the self-serve switch
    says. Nothing is returned to the caller of the route, so this is no token oracle.
    """
    token_hash = sha256(token.encode()).hexdigest()
    async with invite_session(token_hash) as lookup:
        email = (
            await lookup.execute(
                text(
                    "SELECT email FROM invitations WHERE token_hash = :hash "
                    "AND used_at IS NULL AND expires_at > now()"
                ),
                {"hash": token_hash},
            )
        ).scalar()
    return str(email).strip() if email is not None else None


async def accept_for_verified_address(
    *, token: str, user_id: UUID, verified_email: str, ip: str | None
) -> JoinedWorkspace | None:
    """Redeem an invitation for a person who just proved `verified_email` another way (D-703).

    The Google sign-in path: Google has said the address is verified and `google.finish`
    has already signed the person in, so no password is set here. The invitation must be
    addressed to that same address; a mismatch returns None and leaves the invitation
    unused, so the person who was really invited can still redeem it.
    """
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
        raise invitation_unusable()
    if str(row[1]).strip().casefold() != verified_email.strip().casefold():
        log.info("auth_invitation_address_mismatch", extra={"user_id": str(user_id)})
        return None
    tenant_id = UUID(str(row[0]))
    async with tenant_session(tenant_id) as scoped:
        # Waits out a password redemption of the same link that is mid-way through its
        # credential writes, rather than burning the invitation under it.
        await _hold_redemption(scoped, token_hash)
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
        await write_audit(
            scoped,
            action="auth.invitation_accepted",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="membership",
            object_id=str(user_id),
            ip=ip,
            summary={"method": "google"},
        )
    return JoinedWorkspace(tenant_id=tenant_id, slug=str(slug), role=str(role or "owner"))


async def _find_or_create_user(
    *, email: str, name: str | None, at: datetime, phone: str | None = None
) -> tuple[UUID, bool]:
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

    `email_verified_at` is NOT set here (D-185) — see the module docstring. The column is
    left NULL here and `accept_with_password` marks it once the password is set, so a
    password the policy refuses leaves the address unproved.

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
                    "INSERT INTO users (id, email, name, phone, created_at, updated_at) "
                    "VALUES (:id, :email, :name, :phone, :at, :at) "
                    # The index predicate is repeated so Postgres can INFER the partial
                    # unique index; without it the statement is rejected outright rather
                    # than silently matching a different constraint.
                    "ON CONFLICT (lower(email)) WHERE deactivated_at IS NULL DO NOTHING "
                    "RETURNING id"
                ),
                {"id": user_id, "email": email, "name": name, "phone": phone, "at": at},
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


__all__ = [
    "INVITE_REALM",
    "AcceptedInvitation",
    "JoinedWorkspace",
    "accept_for_verified_address",
    "accept_with_password",
    "invitation_unusable",
    "invited_address",
]

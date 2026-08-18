"""Who a credential belongs to, and whether that person may still sign in (D-170).

Everything else in this package works on a `(realm, subject_id)` pair and never asks what
is on the other end of it. This module is the one that asks, and it exists as its own file
because two of the reference implementation's defects live exactly here.

═══ DEFECT: A TOKEN THAT OUTLIVES ITS ACCOUNT ═══

`auth.service.ts:996` completes a password reset with `tx.user.update({ where: { id:
resetToken.userId } ... })` and never checks that the user is still there or still active.
Prisma raises `P2025` when the row is gone, which nothing catches, so the reset of a
deleted account is a raw driver error rendered as a 500. Two things are wrong with that and
only one of them is the status code: a 500 tells the caller to retry something that can
never succeed, and it means the DELETED-ACCOUNT case was never considered on a path that
sets passwords. An account that is gone, disabled, or suspended must be refused CLEANLY on
every flow, and the refusal must be the same one an unknown account gets.

So every flow in `service.py` goes through `load_subject` or `resolve_by_email`, both of
which return `None` for absent-or-inactive rather than raising, and neither of which has a
way to say "present but disabled" to a caller. There is no code path in this package that
reads a `users` row directly.

═══ DEFECT: THE ENUMERATION ORACLE ═══

`/api/v1/auth/check-identifier` (their `routes.ts:236`) answers `{ exists: true|false }`
for any email or phone anybody asks about. The same codebase is careful to return a generic
response from `requestPasswordReset` — so it KNOWS enumeration matters — and then hands the
whole directory away from a different endpoint. That is the shape this class of bug always
takes: the property is enforced per-endpoint by whoever remembered, rather than by the
type the endpoints share.

Here, uniformity is a property of the RETURN TYPE. `resolve_by_email` returns
`Subject | None` and the `None` is indistinguishable at every call site: no exception
carries the reason, no log line the caller can see distinguishes them, and the throttle in
`throttle.py` counts the attempt either way so the rate-limit headers cannot be
differenced. What remains is TIMING, which is dealt with where it arises —
`hashing.verify_password_blocking(pw, None)` performs a real Argon2 verification against
`_dummy_hash` so the no-such-user path costs the same 20-30ms as the wrong-password path —
and `tests/authn_enumeration_test.py` measures that property rather than trusting it.

**There is deliberately no identifier-existence endpoint of any kind**, and there never
should be: a "is this email taken" check for a signup form is the same oracle wearing a
usability argument.

═══ WHY THIS DOES NOT USE `credential_session` ═══

`users` and `admin_users` are ordinary global tables, not credential storage — `users` has
no RLS at all. Opening `app.auth` to read them would widen the credential GUC's blast
radius for no gain, so this module uses `untenanted_session` and the credential tables are
never joined to the identity tables in one statement. Two reads, two sessions, and the
narrow one stays narrow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from apps.api.authn.models import AUTHN_REALMS
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Subject:
    """A person who may currently sign in, in one realm.

    Constructing one is a STATEMENT that the lifecycle check passed — there is no
    `is_active` field, because a `Subject` that could be inactive would put the check back
    at every call site, which is the defect this module exists to remove. An inactive
    account produces `None`, not a `Subject` with a flag.
    """

    realm: str
    subject_id: UUID
    email: str
    email_verified_at: datetime | None


def _refuse_unknown_realm(realm: str) -> None:
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm ({', '.join(AUTHN_REALMS)})")


#: The client realm's liveness rule: a row that exists and has not been deactivated.
#: `deactivated_at` is the column `core/auth.py` already re-reads on every request
#: (BACKEND-PATTERNS §7), so signing in and staying signed in agree about what "active"
#: means — a person deactivated mid-session is refused by the verifier AND cannot obtain a
#: new session, rather than one of the two.
_CLIENT_SELECT = (
    "SELECT id, email, email_verified_at FROM users WHERE {predicate} AND deactivated_at IS NULL"
)

#: The admin realm's liveness rule is ROW PRESENCE, and that is not an oversight.
#: `admin_users` is an ops-managed allowlist rather than a mirror — the retired Clerk
#: mirror was explicit that auto-creating one would be "privilege escalation wearing a race
#: condition's clothes" — so an operator is removed by deleting the row. There is no
#: `deactivated_at` to check and adding one would create a second way to express the same
#: fact — the exact drift CLAUDE.md's "one way per problem" forbids.
_ADMIN_SELECT = "SELECT id, email, NULL AS email_verified_at FROM admin_users WHERE {predicate}"


def _statement(realm: str, predicate: str) -> str:
    template = _CLIENT_SELECT if realm == "client" else _ADMIN_SELECT
    return template.format(predicate=predicate)


async def load_subject(realm: str, subject_id: UUID) -> Subject | None:
    """The subject behind an id, or `None` if there is nobody who may sign in.

    `None` covers: never existed, hard-deleted, soft-deleted, removed from the operator
    allowlist. The caller cannot tell which and must not need to — see the module
    docstring on `auth.service.ts:996`.
    """
    _refuse_unknown_realm(realm)
    async with untenanted_session() as session:
        row = (
            await session.execute(text(_statement(realm, "id = :sid")), {"sid": subject_id})
        ).first()
    if row is None:
        # An id that resolves to nothing is either a stale token or a deleted account.
        # Logged because the OPERATOR wants to know a reset link outlived its account;
        # the caller is told nothing (hard rule 6: an id, never an address).
        log.info("auth_subject_not_live", extra={"realm": realm, "subject_id": str(subject_id)})
        return None
    return Subject(
        realm=realm,
        subject_id=UUID(str(row[0])),
        email=str(row[1]) if row[1] is not None else "",
        email_verified_at=row[2],
    )


async def resolve_by_email(realm: str, email: str) -> Subject | None:
    """The subject who signs in with this address, or `None`. Never says which.

    The match is on `lower(email)` because addresses are compared casefolded everywhere in
    this repo already (`accept_invitation` does), and because the admin realm's unique
    index is on the lowered value — matching raw here would let a row be findable by the
    index and not by this query.

    AMBIGUITY IS A REFUSAL, NOT A PICK. `users.email` has never had a unique constraint
    (the migration `b3d9f6a2c815` docstring says why it cannot safely acquire one in that
    revision), so two rows CAN share an address. Signing the first one in would mean the
    account somebody reaches depends on physical row order. The caller gets the same
    `None` every other failure produces; the operator gets a `WARNING` naming the ids,
    which is the one thing that makes the data fixable.
    """
    _refuse_unknown_realm(realm)
    needle = email.strip().casefold()
    if not needle:
        # An empty identifier cannot match and must not become `lower(email) = ''`, which
        # would match any row whose address is blank.
        return None
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(_statement(realm, "lower(email) = :email") + " LIMIT 2"), {"email": needle}
            )
        ).all()
    if not rows:
        return None
    if len(rows) > 1:
        log.warning(
            "auth_identifier_ambiguous",
            extra={"realm": realm, "subject_ids": [str(row[0]) for row in rows]},
        )
        return None
    row = rows[0]
    return Subject(
        realm=realm,
        subject_id=UUID(str(row[0])),
        email=str(row[1]) if row[1] is not None else "",
        email_verified_at=row[2],
    )


async def mark_email_verified(realm: str, subject_id: UUID, *, at: datetime) -> None:
    """Record that this mailbox has been proved. Client realm only.

    The admin realm has no `email_verified_at` and needs none: an operator's address is
    entered by another operator through `scripts/bootstrap_admin.py` or the ops console,
    so it is verified by the act of an existing operator vouching for it, not by an email
    round trip. Silently doing nothing on the admin realm would be the wrong shape — this
    returns early and says so — but raising would be worse, because the caller
    (`service.confirm_otp`) is realm-generic by design.
    """
    _refuse_unknown_realm(realm)
    if realm != "client":
        return
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE users SET email_verified_at = :at, updated_at = :at "
                "WHERE id = :sid AND email_verified_at IS NULL"
            ),
            {"at": at, "sid": subject_id},
        )
    log.info("auth_email_verified", extra={"realm": realm, "subject_id": str(subject_id)})


__all__ = ["Subject", "load_subject", "mark_email_verified", "resolve_by_email"]

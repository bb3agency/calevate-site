"""The password store: set one, prove one (D-165).

`hashing.py` is pure arithmetic and `sessions.py` is pure session state; this is the
thin layer that puts a hash in a row and takes it out again. It is separate from both so
that the KDF can be tested without Postgres and the session machinery without a password.

WHAT THIS DELIBERATELY DOES NOT DO. It does not issue a session, and
`authenticate_subject` returning `True` is not a sign-in — the caller decides what a
proved password entitles someone to, because on the admin realm it entitles them to a
second-factor prompt and nothing else (TRD §2: MFA is mandatory there). Collapsing the
two would make "the password was right" and "you are signed in" the same call, which is
the shape of mistake that turns an MFA requirement into a suggestion.

It also does not throttle. Credential stuffing is a property of a CALLER, not of a
password, and `core/ratelimit.py` already owns callers.

Every function here requires a `credential_session()`. Under any other session the FORCEd
policy on `auth_credentials` yields zero rows, so a missing context manager surfaces as
"no such credential" rather than as a silent read of somebody else's row — the fail-closed
direction, and `tests/authn_rls_test.py` pins it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.hashing import hash_password, verify_password
from apps.api.authn.models import AUTHN_REALMS
from apps.api.authn.policy import assert_password_allowed
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)


def _refuse_unknown_realm(realm: str) -> None:
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm ({', '.join(AUTHN_REALMS)})")


async def set_password(
    session: AsyncSession,
    *,
    realm: str,
    subject_id: UUID,
    password: str,
    email: str | None = None,
    now: datetime | None = None,
) -> None:
    """Install or replace one subject's password.

    THE PASSWORD POLICY IS APPLIED HERE, at the store, and not at any of the four routes
    that reach it (`invitations.accept_with_password`, `service.confirm_password_reset`,
    `bootstrap.confirm`, `scripts/seed_dev`). `authn/policy.py` carries the standard it
    implements; this is the placement argument. A rule enforced per-endpoint is enforced
    by whoever remembered, which is precisely how the reference implementation ended up
    with a careful generic response on `requestPasswordReset` and an enumeration oracle on
    `check-identifier` (see `subjects.py`). There is no path to a stored password that does
    not pass through this function, so there is no route to forget.

    `email` is optional and is the subject's own address, used for nothing but the
    context-specific half of the blocklist — NIST names "the username, and derivatives
    thereof" among what a blocklist should hold. It is a PARAMETER rather than a lookup
    because the invitation path writes the `users` row in this same uncommitted
    transaction, so a second session could not see it. It is never logged and never
    stored (hard rule 6).

    An UPSERT on `(realm, subject_id)` rather than a read-then-write: two concurrent
    resets must produce one row and a definite winner, not a primary-key error on the
    second (BACKEND-PATTERNS §5).

    THE CALLER MUST REVOKE THE SUBJECT'S SESSIONS in the same transaction —
    `sessions.revoke_subject_sessions(...)`. It is not done here on purpose: a password
    change during ONBOARDING (nobody is signed in) and a password change during a
    SUSPECTED COMPROMISE (sign everything out, including the browser doing the changing)
    want different answers, and a function that silently picked one would be wrong half
    the time with no way for the caller to see it. AUTH-MIGRATION §1 lists it as a
    capability with its own test rather than as a side effect of this call.
    """
    _refuse_unknown_realm(realm)
    assert_password_allowed(password, realm=realm, email=email)
    at = now or datetime.now(UTC)
    digest = await hash_password(password)
    await session.execute(
        text(
            "INSERT INTO auth_credentials (id, realm, subject_id, password_hash, "
            "password_set_at, created_at, updated_at) "
            "VALUES (:id, :realm, :sub, :hash, :now, :now, :now) "
            "ON CONFLICT (realm, subject_id) DO UPDATE SET password_hash = EXCLUDED."
            "password_hash, password_set_at = EXCLUDED.password_set_at, updated_at = :now"
        ),
        {"id": uuid7(), "realm": realm, "sub": subject_id, "hash": digest, "now": at},
    )
    # Ids and a realm. Never the password, never the hash (hard rule 6's spirit: the
    # hash is not PII, it is worse — it is the thing an offline attack needs).
    log.info("password_set", extra={"realm": realm, "subject_id": str(subject_id)})


async def authenticate_subject(
    session: AsyncSession,
    *,
    realm: str,
    subject_id: UUID,
    password: str,
    now: datetime | None = None,
) -> bool:
    """Does this plaintext match this subject's stored password?

    A subject with NO credential row is answered `False` — after a full-cost dummy
    verification, so that "this account has no password yet" and "wrong password" take the
    same time. The equalisation lives in `hashing.verify_password_blocking`, which is
    where it can be tested without a database; this function's only job is to hand it
    `None` rather than returning early.

    A successful verification under stale parameters or a retired pepper generation
    re-hashes the row IN THIS TRANSACTION, which is the only moment the plaintext is
    legitimately in hand. The re-hash is guarded on the hash we just read, so a concurrent
    `set_password` cannot be overwritten by an upgrade of the value it replaced.

    AND THE RE-HASH CAN NEVER FAIL THE SIGN-IN. `hash_password` enforces the length
    bounds, which `verify_password` deliberately does not — that asymmetry exists so
    raising `MIN_PASSWORD_CHARS` does not lock out everyone whose password predates the
    new rule. Without the guard below it would do exactly that by the back door: the
    upgrade path would refuse the very password the verification just accepted, and the
    person would meet a 400 about length on a correct sign-in. So a refusal here is
    logged and skipped; the row keeps its old hash and the account keeps working.
    """
    _refuse_unknown_realm(realm)
    at = now or datetime.now(UTC)
    row = (
        await session.execute(
            text(
                "SELECT password_hash FROM auth_credentials "
                "WHERE realm = :realm AND subject_id = :sub"
            ),
            {"realm": realm, "sub": subject_id},
        )
    ).first()
    stored = str(row[0]) if row is not None else None

    verdict = await verify_password(password, stored)
    if not verdict.ok:
        log.info("password_rejected", extra={"realm": realm, "subject_id": str(subject_id)})
        return False
    if verdict.needs_rehash and stored is not None:
        try:
            fresh = await hash_password(password)
        except ProblemError:
            # See the docstring: a rule that arrived after this password must not turn a
            # correct sign-in into a refusal. WARNING rather than INFO because a row that
            # cannot be upgraded is one the next parameter bump will not reach either.
            log.warning(
                "password_rehash_refused", extra={"realm": realm, "subject_id": str(subject_id)}
            )
            return True
        await session.execute(
            text(
                "UPDATE auth_credentials SET password_hash = :fresh, updated_at = :now "
                "WHERE realm = :realm AND subject_id = :sub AND password_hash = :stale"
            ),
            {
                "fresh": fresh,
                "now": at,
                "realm": realm,
                "sub": subject_id,
                "stale": stored,
            },
        )
        log.info("password_rehashed", extra={"realm": realm, "subject_id": str(subject_id)})
    return True


async def subjects_with_password(
    session: AsyncSession, *, realm: str, subject_ids: Sequence[UUID]
) -> frozenset[UUID]:
    """Which of these subjects have a first-party password. Ids in, ids out.

    THE SET-SHAPED SIBLING OF `service.has_password`, and it exists rather than a loop over
    it because the operator directory asks the question about every row it renders — one
    query per operator is the N+1 that turns a five-row console screen into five
    transactions, each opening its own `credential_session`.

    NOTHING BUT IDS CROSSES THIS BOUNDARY. The caller learns whether a password exists and
    never touches the hash, which is what lets `admin/operator_routes.py` render an
    "invitation outstanding" badge without the console module reaching into the credential
    store at all.

    An empty `subject_ids` short-circuits: `IN ()` is not valid SQL, and a round trip that
    can only answer "none" is a round trip worth not taking.
    """
    _refuse_unknown_realm(realm)
    if not subject_ids:
        return frozenset()
    rows = (
        await session.execute(
            text(
                "SELECT subject_id FROM auth_credentials "
                "WHERE realm = :realm AND subject_id = ANY(:ids)"
            ),
            {"realm": realm, "ids": list(subject_ids)},
        )
    ).all()
    return frozenset(UUID(str(row[0])) for row in rows)


async def delete_password(session: AsyncSession, *, realm: str, subject_id: UUID) -> bool:
    """Destroy one subject's password. Returns whether there was one.

    THE COUNTERPART TO `set_password`, and the only caller is a REVOCATION
    (`operators.revoke_operator`). It is deliberately not exposed as "disable an account":
    an account with no password is an account that has not finished being created, which
    is a different state entirely — what ends an operator account is `deactivated_at`, and
    this runs beside it so that no authentication material outlives the account it
    belonged to. Calling it alone would leave somebody who can complete a fresh setup link
    and sign straight back in.

    THE CALLER MUST ALSO REVOKE THE SUBJECT'S SESSIONS, in the same transaction — the same
    contract `set_password` states, for the same reason: a live session does not consult
    the password store.
    """
    _refuse_unknown_realm(realm)
    result = await session.execute(
        text("DELETE FROM auth_credentials WHERE realm = :realm AND subject_id = :sub"),
        {"realm": realm, "sub": subject_id},
    )
    removed = rowcount_of(result) > 0
    log.warning(
        "auth_password_deleted",
        extra={"realm": realm, "subject_id": str(subject_id), "had_password": removed},
    )
    return removed


__all__ = ["authenticate_subject", "delete_password", "set_password", "subjects_with_password"]

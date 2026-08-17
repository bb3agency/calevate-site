"""The first administrator: how a bare deployment acquires somebody who can use it (D-167).

═══ THE PROBLEM, WHICH IS SPECIFIC AND TOTAL ═══

`admin_users` is the allowlist the whole admin realm resolves against. After
`alembic upgrade head` on a fresh host it is EMPTY, so every admin-realm request 403s: no
organization can be created, no platform setting written, no vendor credential stored, no
first campaign approved. The deploy comes up green and the product cannot onboard anybody.
It fails closed — this was never a security hole — but it is a deployment with no way in,
and with Clerk gone there is no vendor dashboard to make the first account in either.

═══ THE SHAPE: AN EMAILED INVITE, NOT A SEEDED PASSWORD ═══

The founder's decision, and the reference implementation supplies both shapes so it is
worth naming which one this is and which one it deliberately is not.

**Copied — `backend/scripts/admin-newuser.mjs`:** 32 random bytes, stored as a hash, mailed
as a setup link, single-use, consumed to set a password. That is exactly `tokens.py`'s
existing doctrine, so this module mints an `auth_email_tokens` row of purpose
`admin_bootstrap` and adds no new table and no new hashing path.

**NOT copied — `backend/scripts/seed-admin.mjs`:** it creates an admin with a fixed password
and then prints `Admin created: ${admin.email} / ${PASSWORD}`. Writing a live credential to
a log stream is a hard rule 6 violation outright, `scripts/check_redaction_exposure.py`
would fail the build on it, and a fixed password in a repository is a backdoor with a
changelog entry. **There is no password anywhere in this module or its script.** The local
development convenience it provides is served instead by printing the LINK — which is a
single-use token that expires — and by `ConsoleTransport`, which already logs mail to the
terminal when no mail provider is configured.

═══ IDEMPOTENCY, AND WHY THE ANSWER IS "REFUSE" RATHER THAN A FLAG ═══

Running this twice must not mint a second god-account. Three states, three answers:

  1. **No operator at all** → create the `admin_users` row (no credential) and mint a link.
     This is the bootstrap.
  2. **An operator with this address exists but has NO password** → mint a fresh link for
     that same row. This is a RESEND, not a second account: the previous link expired, or
     the mail bounced, and the deploy is still not finished. It is the reference's
     reactivation case, and it is idempotent in the way that matters — the row count does
     not change.
  3. **Any operator anywhere already has a password** → **REFUSE.** The deployment is
     bootstrapped; adding a second operator is an ordinary, audited act that belongs to the
     ops console where one existing operator vouches for the next.

**There is deliberately NO `--force` flag for case 3.** A flag that mints an unattached
administrator from the command line is precisely the back door this is supposed not to be,
and it would be reachable by anyone who has ever had database credentials — a contractor, a
restored backup, a compromised CI runner. The honest escape hatch for "we lost every
operator" is a database-level act by whoever holds the owner role, performed knowingly, and
it leaves the same audit trail this does because the audit chain is in the database too.

═══ WHY A SCRIPT AND NOT A ROUTE ═══

Unchanged from the reasoning the previous `scripts/bootstrap_admin.py` carried: a bootstrap
ENDPOINT is a route that exists to be unauthenticated exactly once, which is a window an
attacker can race on a public host and a permanent piece of code whose whole value is that
it can never be reached again. Whoever runs the deploy already has database credentials;
the smallest correct thing is to write the row from there.

The REDEMPTION half is a route (`POST /v1/auth/admin/bootstrap/confirm`), and that is not
the same hazard: it is reachable only by presenting a 256-bit single-use token that was
mailed to an address a deploying operator named.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from apps.api.authn import tokens
from apps.api.authn.credentials import set_password
from apps.api.authn.models import AUTHN_REALMS
from apps.api.authn.sessions import revoke_subject_sessions
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import credential_session, untenanted_session

log = get_logger(__name__)

#: The admin realm, spelled once. `AUTHN_REALMS` is imported so a future rename of the
#: realm vocabulary breaks here loudly rather than leaving a string that matches nothing.
ADMIN_REALM = AUTHN_REALMS[0]

#: The two roles `ck_admin_users_role_enum` admits.
ADMIN_ROLES = ("superadmin", "operator")


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """What a bootstrap run did, and the one-time link it produced.

    `token` is the ONLY place the secret exists — it is hashed at rest like every other
    one-time token in this package. The script prints the LINK built from it and nothing
    else; there is no password to print, by design.
    """

    admin_id: UUID
    email: str
    #: True when this run inserted the `admin_users` row; False when it re-issued a link
    #: for a row that was already there awaiting its first password.
    created: bool
    token: str
    expires_at: datetime


def _already_bootstrapped() -> ProblemError:
    return ProblemError(
        kind="conflict",
        code="already_bootstrapped",
        title="This deployment already has an administrator",
        detail=(
            "An operator account with a password already exists, so the bootstrap has "
            "already been completed."
        ),
        remediation=(
            "Add further operators from the admin console, where an existing operator "
            "vouches for the new one and the change is audited."
        ),
    )


async def bootstrap_first_admin(
    *, email: str, name: str | None, role: str = "superadmin", now: datetime | None = None
) -> BootstrapResult:
    """Create the first operator and mint their setup link. See the module docstring.

    Raises `already_bootstrapped` in state 3. Returns in states 1 and 2, and the caller
    cannot tell which from the token — only from `created`, which the script reports so the
    operator knows whether they just made an account or resent a link.
    """
    if role not in ADMIN_ROLES:
        raise ValueError(f"{role!r} is not an admin role ({', '.join(ADMIN_ROLES)})")
    address = email.strip()
    if not address or "@" not in address:
        raise ValueError("a bootstrap needs a deliverable email address")
    at = now or datetime.now(UTC)

    # ── the three-state decision, in ONE transaction ────────────────────────
    #
    # The check and the insert must not be separated: two concurrent runs that both saw an
    # empty table would both insert, and the whole point of this function is that the
    # second one does not. `credential_session` is what can see `auth_credentials`, and the
    # existence question is asked about credentials rather than about rows — an
    # `admin_users` row with no password is not yet somebody who can sign in.
    async with credential_session() as session:
        # LOCK THE TABLE for the duration. A heavier hammer than this repo normally
        # reaches for, and correct here for a reason that does not apply anywhere else:
        # this runs at most a handful of times in a deployment's life, holds the lock for
        # microseconds, and the thing it is protecting is the uniqueness of the most
        # privileged account in the system. A CAS is not available — the invariant is
        # "zero rows match", and there is no row to compare-and-swap on.
        await session.execute(text("LOCK TABLE admin_users IN SHARE ROW EXCLUSIVE MODE"))
        bootstrapped = (
            await session.execute(
                text(
                    "SELECT 1 FROM auth_credentials WHERE realm = :realm "
                    "AND subject_id IN (SELECT id FROM admin_users) LIMIT 1"
                ),
                {"realm": ADMIN_REALM},
            )
        ).first()
        if bootstrapped is not None:
            log.warning("admin_bootstrap_refused_already_done")
            raise _already_bootstrapped()

        existing = (
            await session.execute(
                text("SELECT id FROM admin_users WHERE lower(email) = :e"),
                {"e": address.casefold()},
            )
        ).first()
        if existing is not None:
            admin_id, created = UUID(str(existing[0])), False
        else:
            admin_id, created = uuid7(), True
            await session.execute(
                text(
                    "INSERT INTO admin_users (id, clerk_user_id, email, name, role, "
                    "created_at, updated_at) "
                    "VALUES (:id, NULL, :email, :name, :role, :now, :now)"
                ),
                {
                    "id": admin_id,
                    "email": address,
                    "name": name,
                    "role": role,
                    "now": at,
                },
            )

        # Only the newest link works, exactly as a password reset behaves. A resend must
        # not leave the previous link live.
        await tokens.invalidate_outstanding(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=admin_id,
            now=at,
        )
        issued = await tokens.issue_token(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=admin_id,
            now=at,
        )

    # THE MOST PRIVILEGED ACT IN THE SYSTEM'S LIFE, so it leaves a record naming when and
    # to what address — the address is the one fact that makes the entry useful to whoever
    # reads it later, and `audit_log.summary` goes through `redact_mapping` before it
    # reaches the log stream. Its own transaction because the one above is closed; a
    # failure to audit must not roll back an account somebody is about to be emailed a link
    # for, and the link is single-use so the worst case is a re-run.
    async with untenanted_session() as session:
        await write_audit(
            session,
            action="auth.admin_bootstrapped",
            actor_type="system",
            object_type="admin_user",
            object_id=str(admin_id),
            summary={"email": address, "role": role, "account_created": created},
        )
    # NOT `created`: `logging.LogRecord` already owns that attribute name, and passing it
    # in `extra` raises `KeyError: Attempt to overwrite 'created' in LogRecord` — a crash on
    # the bootstrap path, found by `tests/authn_bootstrap_test.py`. The same rename applies
    # to the audit summary above, which reaches a log record through `redact_mapping`.
    log.warning(
        "admin_bootstrap_issued",
        extra={"admin_id": str(admin_id), "account_created": created, "role": role},
    )
    return BootstrapResult(
        admin_id=admin_id,
        email=address,
        created=created,
        token=issued.token,
        expires_at=issued.expires_at,
    )


async def confirm_bootstrap(
    *, token: str, password: str, ip: str | None, now: datetime | None = None
) -> UUID:
    """Redeem a setup link and install the first operator's password. Returns their id.

    THE TOKEN IS BURNED FIRST AND THE ACCOUNT IS RE-READ AFTER, the same order
    `service.confirm_password_reset` uses and for the same reason — reference defect
    `auth.service.ts:996`. A bootstrap token naming an `admin_users` row that has since
    been deleted must be a clean refusal, not a driver error.

    IT ALSO REFUSES AN ACCOUNT THAT ALREADY HAS A PASSWORD, which the reset path does not
    need to. That is what makes this endpoint unable to act as an unaudited password reset
    for an established operator: a leaked bootstrap token from a completed deploy opens
    nothing, even before it expires.

    Sessions are revoked on success for completeness rather than necessity — a brand-new
    account has none — because the state where it matters is a re-run after a partial
    bootstrap, and a rule that holds only sometimes is a rule somebody will remove.
    """
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        redeemed = await tokens.redeem_token(
            session, purpose="admin_bootstrap", token=token, now=at
        )
    if redeemed is None or redeemed.subject_id is None or redeemed.realm != ADMIN_REALM:
        raise _bad_bootstrap_token()
    admin_id = redeemed.subject_id

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM admin_users WHERE id = :id"), {"id": admin_id}
            )
        ).first()
    if row is None:
        log.warning("admin_bootstrap_subject_missing", extra={"admin_id": str(admin_id)})
        raise _bad_bootstrap_token()

    async with credential_session() as session:
        has_credential = (
            await session.execute(
                text("SELECT 1 FROM auth_credentials WHERE realm = :realm AND subject_id = :sub"),
                {"realm": ADMIN_REALM, "sub": admin_id},
            )
        ).first()
        if has_credential is not None:
            # See the docstring: this endpoint sets a FIRST password and nothing else.
            log.warning("admin_bootstrap_already_has_password", extra={"admin_id": str(admin_id)})
            raise _bad_bootstrap_token()
        await set_password(
            session, realm=ADMIN_REALM, subject_id=admin_id, password=password, now=at
        )
        await revoke_subject_sessions(session, realm=ADMIN_REALM, subject_id=admin_id, now=at)

    async with untenanted_session() as session:
        await write_audit(
            session,
            action="auth.admin_bootstrap_completed",
            actor_type="admin",
            object_type="admin_user",
            object_id=str(admin_id),
            ip=ip,
        )
    log.warning("admin_bootstrap_completed", extra={"admin_id": str(admin_id)})
    return admin_id


def _bad_bootstrap_token() -> ProblemError:
    """One refusal for unknown, expired, spent, wrong-realm, orphaned, and
    already-has-a-password. Distinguishing them would tell somebody holding a link they
    should not have whether a deployment is mid-bootstrap."""
    return ProblemError(
        kind="business_rule",
        code="invalid_bootstrap_token",
        title="That setup link is no longer usable",
        detail="This link has already been used or has expired.",
        remediation=(
            "Ask whoever deployed this environment to run the administrator bootstrap "
            "again — it issues a fresh link."
        ),
    )


__all__ = [
    "ADMIN_REALM",
    "ADMIN_ROLES",
    "BootstrapResult",
    "bootstrap_first_admin",
    "confirm_bootstrap",
]

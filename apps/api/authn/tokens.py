"""Single-use emailed tokens: issue one, redeem one, invalidate the rest (D-170).

Three purposes over one table (`EMAIL_TOKEN_PURPOSES`), because they differ in lifetime
and in what they name, and in nothing else. The purpose is inside the hash domain — see
`codes._fingerprint_under` — so a verification token presented at the reset endpoint is
not "the wrong purpose", it is 32 bytes that match no row.

═══ LIFETIMES, AND WHY THEY DIFFER ═══

OWASP's Forgot Password Cheat Sheet (github.com/OWASP/CheatSheetSeries,
`cheatsheets/Forgot_Password_Cheat_Sheet.md`, read 2026-08-17) requires a CSPRNG token
"long enough to protect against brute-force", expiry "after an appropriate period",
invalidation after use, hashed storage, and session invalidation on reset. It declines to
name a number for the period, so the three below are argued rather than cited:

* `password_reset` — **1 hour**. AUTH-MIGRATION C-13 already fixed this. It is the token
  with the most authority (it mints a new password on a live account) and the one most
  likely to sit in a mailbox somebody else can reach.
* `email_verify` — **24 hours**. Lower authority: it proves a mailbox, it does not open an
  account. A day survives somebody signing up in the evening and reading mail the next
  morning, which is the whole population this product has.
* `invite_password` — **72 hours**, matching the `invitations` row it is bound to. A
  different number would mean one of the two expires while the other is live, and the
  person meets a refusal whose reason depends on which. One clock.

═══ REDEMPTION IS A COMPARE-AND-SWAP ═══

`UPDATE ... WHERE used_at IS NULL` and check the row count, exactly as `invitations` is
already burned (`admin.service.accept_invitation`). Two clicks on the same link produce one
password change and one clean refusal, not two changes or a race. Reading the row and then
updating it would be the check-then-act that BACKEND-PATTERNS §5 names as the defect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.codes import code_fingerprint, code_fingerprints, new_url_token
from apps.api.authn.locks import lock_subject_credentials
from apps.api.authn.models import AUTHN_REALMS, EMAIL_TOKEN_PURPOSES
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)

TOKEN_LIFETIMES: Final[dict[str, timedelta]] = {
    "password_reset": timedelta(hours=1),
    "email_verify": timedelta(hours=24),
    "invite_password": timedelta(hours=72),
    # THE FIRST ADMINISTRATOR (D-171). Sixty minutes, and the number is argued rather than
    # inherited: the reference implementation's `admin-newuser.mjs` uses
    # `INVITE_TTL_MS = 10 * 60 * 1000`, which is defensible for an invite handed to
    # somebody already watching their inbox and wrong for a deployment bootstrap. This link
    # is minted by a script during a deploy, and if it expires before the operator reaches
    # the mailbox there is NO OTHER WAY INTO THE PLATFORM — every admin route 403s until an
    # admin exists. Ten minutes turns an ordinary mail delay into a re-run of a deployment
    # step, and OWASP's Forgot Password Cheat Sheet asks only for "an appropriate period"
    # rather than a number.
    #
    # Sixty covers a deploy window plus greylisting (the classic 15-minute retry) with room
    # to spare, and is bounded by the fact that an unconsumed link is the only way in — so
    # a link that outlives the deploy is a live path to the widest authority in the system.
    # It is the same hour a password reset gets, which is the right comparison: both set a
    # password on an account that already exists, and neither should be alive overnight.
    # Re-running the script is the recovery, and it is safe by design (`authn/bootstrap.py`).
    "admin_bootstrap": timedelta(minutes=60),
}


def _domain(purpose: str) -> str:
    """The hash domain for one purpose. Versioned alongside the rest of this package."""
    return f"calevate/auth-email-token/v1/{purpose}"


def _refuse_unknown(purpose: str, realm: str) -> None:
    if purpose not in EMAIL_TOKEN_PURPOSES:
        raise ValueError(f"{purpose!r} is not an email-token purpose")
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A new token: the row's id, and the ONE moment the secret exists in clear.

    Like `sessions.IssuedSession`, the plaintext is returned and never stored, so this
    object is the single point at which a caller can put it in an email. It must never be
    logged — it is not PII, it is the credential.
    """

    token_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RedeemedToken:
    """What a burnt token named. Ids only — no address, no plaintext."""

    token_id: UUID
    realm: str
    subject_id: UUID | None
    invitation_id: UUID | None


async def issue_token(
    session: AsyncSession,
    *,
    purpose: str,
    realm: str,
    subject_id: UUID | None = None,
    invitation_id: UUID | None = None,
    now: datetime | None = None,
) -> IssuedToken:
    """Mint one token. Requires a `credential_session()`.

    Exactly one of `subject_id`/`invitation_id`, mirroring the CHECK constraint — refused
    here too rather than left to the database, because a caller that passes both has a bug
    the constraint would report as an opaque integrity error three frames away.
    """
    _refuse_unknown(purpose, realm)
    if (subject_id is None) == (invitation_id is None):
        raise ValueError("an email token names exactly one of subject_id / invitation_id")
    at = now or datetime.now(UTC)
    expires_at = at + TOKEN_LIFETIMES[purpose]
    token = new_url_token()
    token_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO auth_email_tokens (id, purpose, realm, subject_id, invitation_id, "
            "token_hash, expires_at, created_at, updated_at) "
            "VALUES (:id, :purpose, :realm, :sub, :inv, :hash, :exp, :now, :now)"
        ),
        {
            "id": token_id,
            "purpose": purpose,
            "realm": realm,
            "sub": subject_id,
            "inv": invitation_id,
            "hash": code_fingerprint(token, domain=_domain(purpose)),
            "exp": expires_at,
            "now": at,
        },
    )
    log.info(
        "auth_email_token_issued",
        extra={"purpose": purpose, "realm": realm, "token_id": str(token_id)},
    )
    return IssuedToken(token_id=token_id, token=token, expires_at=expires_at)


async def redeem_token(
    session: AsyncSession, *, purpose: str, token: str, now: datetime | None = None
) -> RedeemedToken | None:
    """Burn a token and say what it named, or `None` for every way it can fail.

    `None` covers unknown, wrong purpose, already used, and expired — one answer, because
    telling a caller "that token was real but expired" tells somebody holding a stolen link
    that they found a real account. The distinction is not even computed: the CAS predicate
    carries all of it, so there is no branch to leak.

    The KEK ring is walked because a rotation between issue and redemption must not
    invalidate a link somebody is about to click; see `codes.code_fingerprints`.

    THE BURN AND THE READ ARE ONE STATEMENT. `UPDATE ... RETURNING` rather than a SELECT
    followed by an UPDATE: the returning form makes "this call is the one that burnt it"
    and "here is what it named" the same fact, so two concurrent clicks cannot both be told
    they won.
    """
    if purpose not in EMAIL_TOKEN_PURPOSES:
        raise ValueError(f"{purpose!r} is not an email-token purpose")
    at = now or datetime.now(UTC)
    row = (
        await session.execute(
            text(
                "UPDATE auth_email_tokens SET used_at = :now, updated_at = :now "
                "WHERE token_hash = ANY(:hashes) AND purpose = :purpose "
                "AND used_at IS NULL AND expires_at > :now "
                "RETURNING id, realm, subject_id, invitation_id"
            ),
            {
                "now": at,
                "purpose": purpose,
                "hashes": code_fingerprints(token, domain=_domain(purpose)),
            },
        )
    ).first()
    if row is None:
        log.info("auth_email_token_rejected", extra={"purpose": purpose})
        return None
    log.info("auth_email_token_redeemed", extra={"purpose": purpose, "token_id": str(row[0])})
    return RedeemedToken(
        token_id=UUID(str(row[0])),
        realm=str(row[1]),
        subject_id=UUID(str(row[2])) if row[2] is not None else None,
        invitation_id=UUID(str(row[3])) if row[3] is not None else None,
    )


async def invalidate_outstanding(
    session: AsyncSession,
    *,
    purpose: str,
    realm: str,
    subject_id: UUID,
    now: datetime | None = None,
) -> int:
    """Burn every live token of one purpose for one subject. Returns how many.

    Called after a successful password change, and it is not optional. Without it, a reset
    link issued before the change stays live for the rest of its hour — so an attacker who
    triggered a reset, then watched the victim change their password by other means, still
    holds a working key. The same reasoning covers the ordinary case of a person clicking
    "forgot password" three times: only the newest link should work, and this is what makes
    that true.

    **IT TAKES THE SUBJECT LOCK, AND THAT IS WHAT MAKES "ONLY THE NEWEST" TRUE** (D-320).
    Both promises above are retire-then-issue across two statements, and under READ
    COMMITTED two overlapping reset requests each retired nothing and each issued a link:
    two live keys in one mailbox, which is the state this function exists to prevent. The
    lock lives here rather than in `issue_token` because this is the statement the
    exclusivity is ABOUT — every caller that needs "only mine survives" already calls this
    first, in the same transaction, and the lock is held through their INSERT by being
    transaction-scoped (`authn.locks`).
    """
    _refuse_unknown(purpose, realm)
    at = now or datetime.now(UTC)
    await lock_subject_credentials(session, realm=realm, subject_id=subject_id)
    result = await session.execute(
        text(
            "UPDATE auth_email_tokens SET used_at = :now, updated_at = :now "
            "WHERE purpose = :purpose AND realm = :realm AND subject_id = :sub "
            "AND used_at IS NULL"
        ),
        {"now": at, "purpose": purpose, "realm": realm, "sub": subject_id},
    )
    count = rowcount_of(result)
    if count:
        log.info(
            "auth_email_tokens_invalidated",
            extra={
                "purpose": purpose,
                "realm": realm,
                "subject_id": str(subject_id),
                "count": count,
            },
        )
    return count


__all__ = [
    "TOKEN_LIFETIMES",
    "IssuedToken",
    "RedeemedToken",
    "invalidate_outstanding",
    "issue_token",
    "redeem_token",
]

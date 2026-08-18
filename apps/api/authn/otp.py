"""The emailed numeric challenge — the reference implementation's worst table, rebuilt.

A six-digit code has about twenty bits of entropy. Everything in this module follows from
that one number, and the reference implementation (`auth.service.ts:165-168`) is the
cautionary case for what happens when it is not taken seriously:

  * it stored `sha256(code)`, UNSALTED and UNKEYED, so 900,000 precomputed digests turned
    any read of that table into every live code. Ours is HMAC under a `PLATFORM_KEK`-derived
    key that is not in this database (`codes.py` argues it at length);
  * its generator never returned its own stated maximum (`codes.new_otp_code` and its
    exhaustive test);
  * and its guess budget was the request limiter, which counts requests rather than wrong
    answers.

This module supplies the third: a challenge carries its OWN attempt ceiling on the row, so
the budget survives a Redis flush and an attacker who can reset the caller-keyed counter
still cannot spend more than `OTP_MAX_ATTEMPTS` guesses against one code. NIST SP 800-63B
requires a rate-limiting mechanism outright when an authenticator output has fewer than 64
bits of entropy; two independent mechanisms is what taking that seriously looks like.

═══ LIFETIME ═══

Ten minutes. Long enough to survive mail delivery — the outbox dispatcher ticks every ten
seconds and a transactional mail typically lands inside a minute — and short enough that
the guessing window is bounded even if every other control failed. NIST's own framing is
that a one-time secret's validity should be as short as usability allows; ten minutes is
the number this repo can defend without measuring a mail provider it has not signed up
with yet.

═══ ONE LIVE CHALLENGE PER (SUBJECT, PURPOSE) ═══

Issuing a new code invalidates the previous one. Without that rule, "resend the code"
becomes an attempt-budget reset: an attacker requests twenty codes and gets twenty lots of
five guesses against a moving target, and the per-row ceiling means nothing. With it, the newest
code is the only live one and the budget is per code, as intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.codes import code_fingerprints, new_otp_code
from apps.api.authn.locks import lock_subject_credentials
from apps.api.authn.models import AUTHN_REALMS, OTP_PURPOSES
from apps.api.authn.throttle import OTP_MAX_ATTEMPTS
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: How long an emailed code stays usable. See the module docstring.
OTP_LIFETIME: Final = timedelta(minutes=10)


def _domain(purpose: str) -> str:
    return f"calevate/auth-otp/v1/{purpose}"


def _refuse_unknown(purpose: str, realm: str) -> None:
    if purpose not in OTP_PURPOSES:
        raise ValueError(f"{purpose!r} is not an OTP purpose")
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")


@dataclass(frozen=True, slots=True)
class IssuedChallenge:
    """A new challenge, and the one moment its code exists in clear."""

    challenge_id: UUID
    code: str
    expires_at: datetime


async def issue_challenge(
    session: AsyncSession,
    *,
    purpose: str,
    realm: str,
    subject_id: UUID,
    now: datetime | None = None,
) -> IssuedChallenge:
    """Mint a code, retiring any previous live one. Requires a `credential_session()`.

    The retirement is `consumed_at = now` rather than a DELETE, so the row survives to be
    counted: a burst of unconsumed challenges for one subject is what a "resend" abuse
    pattern looks like, and deleting the evidence would make it invisible.

    **THE RETIREMENT AND THE MINT ARE ONE CRITICAL SECTION** (D-320). They are two
    statements, and two overlapping calls used to interleave into two live challenges with
    both codes valid — measured, not argued — which is precisely the "resend resets the
    attempt budget" failure the module docstring says this rule prevents.
    `authn.locks.lock_subject_credentials` is why that can no longer happen; the partial
    unique index behind it (`ux_auth_otp_challenges_live`) is why a future caller cannot
    reintroduce it silently.
    """
    _refuse_unknown(purpose, realm)
    at = now or datetime.now(UTC)
    await lock_subject_credentials(session, realm=realm, subject_id=subject_id)
    await session.execute(
        text(
            "UPDATE auth_otp_challenges SET consumed_at = :now, updated_at = :now "
            "WHERE realm = :realm AND subject_id = :sub AND purpose = :purpose "
            "AND consumed_at IS NULL"
        ),
        {"now": at, "realm": realm, "sub": subject_id, "purpose": purpose},
    )
    code = new_otp_code()
    challenge_id = uuid7()
    expires_at = at + OTP_LIFETIME
    await session.execute(
        text(
            "INSERT INTO auth_otp_challenges (id, purpose, realm, subject_id, code_hash, "
            "expires_at, attempts, created_at, updated_at) "
            "VALUES (:id, :purpose, :realm, :sub, :hash, :exp, 0, :now, :now)"
        ),
        {
            "id": challenge_id,
            "purpose": purpose,
            "realm": realm,
            "sub": subject_id,
            # Written under the ACTIVE key generation only; verification walks the ring.
            "hash": code_fingerprints(code, domain=_domain(purpose))[0],
            "exp": expires_at,
            "now": at,
        },
    )
    # The CODE is never logged. It is a credential with twenty bits of entropy — a log
    # line carrying it is a log line that authenticates somebody.
    log.info(
        "auth_otp_issued",
        extra={"purpose": purpose, "realm": realm, "challenge_id": str(challenge_id)},
    )
    return IssuedChallenge(challenge_id=challenge_id, code=code, expires_at=expires_at)


async def verify_challenge(
    session: AsyncSession,
    *,
    purpose: str,
    realm: str,
    subject_id: UUID,
    code: str,
    now: datetime | None = None,
) -> bool:
    """Spend one guess against this subject's live challenge.

    ONE STATEMENT CONSUMES IT, and that is what makes a correct code single-use under
    concurrency: `UPDATE ... WHERE consumed_at IS NULL ... RETURNING` means two simultaneous
    submissions of the same correct code produce one winner. OWASP's MFA cheat sheet asks
    for exactly this ("invalidate the OTP on successful verification"), and doing it as a
    read-then-write would leave the window it is asking us to close.

    A WRONG code costs one attempt, and the attempt is counted even when the challenge has
    already run out of budget — the increment and the ceiling are in the same statement, so
    there is no ordering in which a guess is free.

    Returns a bool rather than raising: the caller has a throttle to update and an audit row
    to write on the failure path, and an exception here would make both of those things the
    caller's job to remember inside an `except`.
    """
    _refuse_unknown(purpose, realm)
    at = now or datetime.now(UTC)
    hashes = code_fingerprints(code, domain=_domain(purpose))
    consumed = (
        await session.execute(
            text(
                "UPDATE auth_otp_challenges SET consumed_at = :now, updated_at = :now "
                "WHERE realm = :realm AND subject_id = :sub AND purpose = :purpose "
                "AND consumed_at IS NULL AND expires_at > :now "
                "AND attempts < :max AND code_hash = ANY(:hashes) "
                "RETURNING id"
            ),
            {
                "now": at,
                "realm": realm,
                "sub": subject_id,
                "purpose": purpose,
                "max": OTP_MAX_ATTEMPTS,
                "hashes": hashes,
            },
        )
    ).first()
    if consumed is not None:
        log.info(
            "auth_otp_verified",
            extra={"purpose": purpose, "realm": realm, "challenge_id": str(consumed[0])},
        )
        return True

    # Wrong, expired, already spent, or out of budget — one answer to the caller, and one
    # increment so that "wrong" costs something. Guarded on `consumed_at IS NULL` so a
    # guess arriving after a successful verification does not inflate the count of a
    # challenge that is already closed.
    await session.execute(
        text(
            "UPDATE auth_otp_challenges SET attempts = attempts + 1, updated_at = :now "
            "WHERE realm = :realm AND subject_id = :sub AND purpose = :purpose "
            "AND consumed_at IS NULL"
        ),
        {"now": at, "realm": realm, "sub": subject_id, "purpose": purpose},
    )
    log.info("auth_otp_rejected", extra={"purpose": purpose, "realm": realm})
    return False


__all__ = ["OTP_LIFETIME", "IssuedChallenge", "issue_challenge", "verify_challenge"]

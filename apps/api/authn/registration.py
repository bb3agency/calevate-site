"""Self-serve account creation by email: prove the mailbox, then choose a password (D-703).

Two calls, because the account must not exist until the mailbox is proved:

1. `start_signup(email)` mails a six-digit `signup` code. It answers the same way whether
   or not the address already has an account (OWASP's guidance for any form that takes a
   stranger's address): an existing account gets a different email instead — "you already
   have an account, sign in or choose a new password" with a live reset link — so the real
   owner learns of the attempt and has a way in, and the caller learns nothing.
2. `complete_signup(email, code, password, name)` spends one guess against that code; on
   success it creates the person already verified, sets the password and starts a session.

The code is keyed on `throttle.pseudo_subject("client", email)` because no `users` row
exists yet; the same derivation keys the throttle, so an address that has an account and
one that does not are counted identically.

Nothing here opens a workspace: `tenancy/signup.py` does that for a signed-in person, and
the kill switch `self_serve_signup_enabled` is checked by the routes before either call.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from apps.api.authn import otp, tokens
from apps.api.authn.credentials import set_password
from apps.api.authn.policy import assert_password_allowed
from apps.api.authn.service import (
    RESET_RESPONSE_FLOOR_S,
    _audit,
    _code_refused,
    _enqueue_auth_email,
    _equalise,
)
from apps.api.authn.sessions import IssuedSession, issue_session
from apps.api.authn.subjects import create_verified_client, resolve_by_email
from apps.api.authn.throttle import OTP_BUDGET, SIGNUP_BUDGET, clear, pseudo_subject, reserve
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import credential_session

log = get_logger(__name__)

SIGNUP_REALM: Final = "client"
SIGNUP_PURPOSE: Final = "signup"


@dataclass(frozen=True, slots=True)
class CreatedAccount:
    subject_id: UUID
    session: IssuedSession


async def start_signup(*, email: str, ip: str | None, now: datetime | None = None) -> None:
    """Mail a signup code, or tell an existing owner someone tried. Returns nothing either way.

    Answers no sooner than `RESET_RESPONSE_FLOOR_S`, the password-reset floor, for the same
    reason: the two arms do different amounts of database work, and the gap would otherwise
    be an account-existence oracle.
    """
    started = time.monotonic()
    try:
        await _start_signup(email=email, ip=ip, now=now)
    finally:
        remaining = RESET_RESPONSE_FLOOR_S - (time.monotonic() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)


async def _start_signup(*, email: str, ip: str | None, now: datetime | None) -> None:
    at = now or datetime.now(UTC)
    address = email.strip()
    subject = await resolve_by_email(SIGNUP_REALM, address)
    pending = pseudo_subject(SIGNUP_REALM, address)
    await reserve(SIGNUP_BUDGET, realm=SIGNUP_REALM, subject_id=pending)

    if subject is not None:
        # The owner gets a working way in rather than a dead end: the reset link is the
        # same single-use, one-hour token "Forgot password" mints.
        async with credential_session() as session:
            await tokens.invalidate_outstanding(
                session,
                purpose="password_reset",
                realm=SIGNUP_REALM,
                subject_id=subject.subject_id,
                now=at,
            )
            issued = await tokens.issue_token(
                session,
                purpose="password_reset",
                realm=SIGNUP_REALM,
                subject_id=subject.subject_id,
                now=at,
            )
            await _enqueue_auth_email(
                session,
                kind="signup_existing_account",
                realm=SIGNUP_REALM,
                to=subject.email,
                secret=issued.token,
            )
        await _audit(
            action="auth.signup_existing_account",
            realm=SIGNUP_REALM,
            subject_id=subject.subject_id,
            ip=ip,
        )
        return

    async with credential_session() as session:
        # A resend inside the cooldown is a quiet no-op rather than a refusal: a refusal
        # here would differ from the existing-account arm, which has no cooldown to report.
        if await otp.resend_wait_s(
            session, purpose=SIGNUP_PURPOSE, realm=SIGNUP_REALM, subject_id=pending, now=at
        ):
            log.info("auth_signup_resend_skipped")
            return
        challenge = await otp.issue_challenge(
            session, purpose=SIGNUP_PURPOSE, realm=SIGNUP_REALM, subject_id=pending, now=at
        )
        await _enqueue_auth_email(
            session, kind="otp_signup", realm=SIGNUP_REALM, to=address, secret=challenge.code
        )
    log.info("auth_signup_code_sent")


def _address_taken() -> ProblemError:
    return ProblemError.conflict(
        "account_exists",
        "There is already a Calevate account for this email address.",
        remediation="Sign in instead, or choose a new password from the sign-in page.",
    )


async def complete_signup(
    *,
    email: str,
    code: str,
    password: str,
    name: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> CreatedAccount:
    """Spend one guess; on success create the verified account, its password and a session.

    The password is checked against the policy BEFORE the code is spent, so a weak choice
    costs the person a retype rather than a fresh code.
    """
    at = now or datetime.now(UTC)
    address = email.strip()
    assert_password_allowed(password, realm=SIGNUP_REALM, email=address)

    pending = pseudo_subject(SIGNUP_REALM, address)
    attempt = await reserve(OTP_BUDGET, realm=SIGNUP_REALM, subject_id=pending)
    async with credential_session() as session:
        outcome = await otp.check_challenge(
            session,
            purpose=SIGNUP_PURPOSE,
            realm=SIGNUP_REALM,
            subject_id=pending,
            code=code,
            now=at,
        )
    if outcome != "accepted":
        await _equalise(attempt)
        raise _code_refused(outcome, code="invalid_code")
    await clear(OTP_BUDGET, realm=SIGNUP_REALM, subject_id=pending)

    subject_id = await create_verified_client(email=address, name=name, at=at)
    if subject_id is None:
        raise _address_taken()
    async with credential_session() as session:
        await set_password(
            session,
            realm=SIGNUP_REALM,
            subject_id=subject_id,
            password=password,
            email=address,
            now=at,
        )
        issued = await issue_session(session, realm=SIGNUP_REALM, subject_id=subject_id, now=at)
    await _audit(
        action="auth.signup_completed",
        realm=SIGNUP_REALM,
        subject_id=subject_id,
        ip=ip,
        object_id=str(issued.session_id),
        summary={"method": "email"},
    )
    return CreatedAccount(subject_id=subject_id, session=issued)


__all__ = [
    "SIGNUP_PURPOSE",
    "SIGNUP_REALM",
    "CreatedAccount",
    "complete_signup",
    "start_signup",
]

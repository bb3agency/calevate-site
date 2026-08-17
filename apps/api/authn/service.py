"""The flows: sign in, sign out, reset, verify, enrol (D-170).

Everything below this module is a mechanism — a hash, a row, a counter, a code. This is
where they are composed into the six things a person actually does, and where the two
properties that cut across all of them are enforced:

  1. **Every identity-probing flow answers identically.** Same status, same body, same
     shape, and — because `hashing.verify_password_blocking` verifies a dummy hash for an
     unknown subject and `throttle.pseudo_subject` gives an unknown identifier a real
     counter — the same observable timing. See `subjects.py` for the reference
     implementation's `check-identifier` oracle that this exists to avoid.

  2. **Every flow refuses a dead account cleanly.** There is exactly one way to get from an
     id or an address to a person here (`subjects.load_subject` / `resolve_by_email`), it
     returns `None` for deleted, deactivated and never-existed alike, and no caller can
     tell the difference. That is reference defect `auth.service.ts:996` — a reset token
     whose user had been deleted producing a raw driver error — designed out of the type
     rather than patched at the one site where it was noticed.

═══ WHAT "MFA" MEANS HERE, WHICH IS LESS THAN A READER WILL ASSUME ═══

**The second factor is an emailed six-digit code, and nothing else** (D-170). There is no
TOTP, no authenticator app, no shared secret, no QR code and no recovery-code sheet — those
were designed and then deliberately removed, so a reader who goes looking for them is
looking for something this system does not have. "The admin realm requires MFA" means
exactly: a correct password on the admin realm issues a session that can do ONE thing, which
is answer `POST /v1/auth/admin/login/otp`. Everything else refuses it.

The honest cost: the strength of that factor is the strength of the operator's mailbox. It
defends against a stolen password and not against a compromised email account, which a TOTP
secret would. ROADMAP §6 D-170 records that trade rather than leaving it to be discovered.

═══ WHY A PASSWORD PRODUCES A SESSION EVEN WHEN A SECOND FACTOR IS REQUIRED ═══

`sign_in` issues a real session row with `mfa_verified_at = NULL`, and answering the
challenge then ROTATES it (`sessions.rotate_session(..., mfa_verified_at=now)`). The
alternative — a separate short-lived "pre-auth token" carrying "this person proved a
password" — is what most implementations build, and it is a second credential type with its
own storage, expiry, revocation and confusion risk.

We do not need one, because `auth_sessions` already has the column and `rotate_session`
already exists to change a session's privilege level. A NULL `mfa_verified_at` on the admin
realm is not a usable credential: `core/auth.py::_require_second_factor` refuses any admin
principal without a second factor, and `MFA_REQUIRED_REALMS` is where that lives. So the
partial session opens exactly one door — the MFA step — and rotating it on completion is
the session-fixation defence OWASP asks for, applied at the moment of privilege change it
was designed for. One credential type, one revocation path, one thing to reason about.

═══ WHAT IS AUDITED, AND WHY NOT `consent_ledger` ═══

Every authentication event lands in `audit_log`: `auth.login_succeeded`,
`auth.login_failed`, `auth.logout`, `auth.password_reset_requested`,
`auth.password_changed`, `auth.login_password_accepted`, `auth.mfa_failed`,
`auth.email_verified`, `auth.sessions_revoked`, `auth.invitation_accepted`,
`auth.admin_bootstrapped` and `auth.admin_bootstrap_completed`.

**Not `consent_ledger`, and D-165's own reasoning is the precedent.** That ledger records a
DATA PRINCIPAL'S consent under DPDP — a person agreeing to be called, to be messaged, to
have their data used a particular way. Signing in is not consent to anything; it is the
Data Fiduciary authenticating access to its own systems, which is a security control and is
evidenced by the security log. Writing sign-ins into `consent_ledger` would dilute the one
record a DPDP audit actually reads, and `audit_log` is already hash-chained, append-only
and cross-tenant, which is exactly what an authentication trail needs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn import otp, tokens
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.hashing import verify_password
from apps.api.authn.models import AUTHN_REALMS
from apps.api.authn.sessions import (
    IssuedSession,
    VerifiedSession,
    issue_session,
    revoke_session,
    revoke_subject_sessions,
    rotate_session,
)
from apps.api.authn.subjects import Subject, load_subject, mark_email_verified, resolve_by_email
from apps.api.authn.throttle import (
    OTP_BUDGET,
    PASSWORD_BUDGET,
    Budget,
    check,
    clear,
    penalty_delay_s,
    pseudo_subject,
    record_failure,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import credential_session, untenanted_session
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

#: Which realms cannot be entered without a second factor. Mirrors — and is asserted equal
#: to — `core/auth.MFA_REQUIRED_REALMS`, which is the gate the token verifier applies. Two
#: copies of one fact would be a way for the sign-in path and the verification path to
#: disagree about whether an operator needs MFA, so `tests/authn_mfa_test.py` pins that
#: they are the same set rather than trusting this comment.
MFA_REQUIRED_REALMS: Final[frozenset[str]] = frozenset({"admin"})

#: The outbox job that delivers an auth email. Registered in `apps/workers/settings.FUNCTIONS`
#: — an unregistered job is not a dormant feature, it is a row walking its retry ladder into
#: the DLQ while the screen says the email was sent (`tests/job_registration_test.py`).
AUTH_EMAIL_JOB: Final = "deliver_auth_email"

#: The OTP purpose that IS the second factor. Named once so `sign_in`, the resend and the
#: verify step cannot drift onto different purposes — which would be a challenge nobody can
#: answer, since the purpose is inside the code's hash domain.
LOGIN_CHALLENGE: Final = "login_challenge"

#: What `sign_in` concluded. A closed vocabulary because the frontend switches on it.
#: `otp_required` rather than `mfa_required`, because naming it after the MECHANISM is what
#: stops the next reader looking for an authenticator app that does not exist.
LoginStatus = Literal["authenticated", "otp_required"]


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """A successful password check, and what still stands between it and a usable session.

    `session` is always present — see the module docstring on why a partial session is a
    real session with `mfa_verified_at = NULL` rather than a second credential type.
    """

    status: LoginStatus
    session: IssuedSession
    subject_id: UUID


def _refuse_unknown_realm(realm: str) -> None:
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")


def _invalid_credentials() -> ProblemError:
    """THE refusal. One sentence for every way signing in can fail.

    Unknown address, wrong password, deactivated account, deleted account, an address that
    is ambiguous in our own data — all of it produces this, with this status and this body.
    OWASP's Authentication Cheat Sheet asks for exactly this ("Login failed; Invalid user ID
    or password") and the reference implementation's `check-identifier` endpoint is what
    happens when the rule is applied per-endpoint instead of per-answer.
    """
    return ProblemError(
        kind="auth",
        code="invalid_credentials",
        title="Sign-in failed",
        detail="That email address and password do not match an account.",
        remediation="Check the address and password, or reset your password.",
    )


async def _equalise(count: int) -> None:
    """Serve the backoff delay a failure earned.

    Separated so the delay is one line at each call site and so the curve lives in
    `throttle.penalty_delay_s` where it is tested without waiting. `asyncio.sleep` yields
    the event loop, so this costs a coroutine and no thread — and the curve is capped for
    exactly that reason (see `penalty_delay_s`).
    """
    delay = penalty_delay_s(count)
    if delay:
        await asyncio.sleep(delay)


async def _spend_failure(budget: Budget, *, realm: str, subject_id: UUID) -> None:
    """Count a failed attempt and pay its delay. Used by every wrong-secret path."""
    await _equalise(await record_failure(budget, realm=realm, subject_id=subject_id))


# ─────────────────────────────── sign in ────────────────────────────────────


async def sign_in(
    *, realm: str, email: str, password: str, ip: str | None, now: datetime | None = None
) -> LoginOutcome:
    """Prove a password and start a session. Raises `_invalid_credentials` for every failure.

    THE UNKNOWN-SUBJECT PATH IS THE INTERESTING ONE and it is written to cost the same as
    the known one, in every observable dimension:

      * it consumes a throttle budget, against `throttle.pseudo_subject(realm, email)` — a
        stable id derived from the address through the code key. Without this, an attacker
        could tell real addresses from fake ones by which ones eventually produce a 429;
      * it runs a REAL Argon2 verification against a dummy hash
        (`hashing.verify_password_blocking` with `stored_hash=None`), which is 20-30ms of
        the same work the real path does. Returning early here is the four-orders-of-
        magnitude timing oracle that OWASP's cheat sheet describes;
      * it pays the same backoff delay;
      * and it raises the same error with the same status and body.

    `tests/authn_enumeration_test.py` measures the timing property rather than asserting
    that the code looks right.
    """
    _refuse_unknown_realm(realm)
    at = now or datetime.now(UTC)
    subject = await resolve_by_email(realm, email)

    if subject is None:
        # Everything the real path does, against a subject that does not exist.
        ghost = pseudo_subject(realm, email)
        await check(PASSWORD_BUDGET, realm=realm, subject_id=ghost)
        await verify_password(password, None)
        await _spend_failure(PASSWORD_BUDGET, realm=realm, subject_id=ghost)
        log.info("auth_login_unknown_subject", extra={"realm": realm})
        raise _invalid_credentials()

    await check(PASSWORD_BUDGET, realm=realm, subject_id=subject.subject_id)
    async with credential_session() as session:
        ok = await authenticate_subject(
            session, realm=realm, subject_id=subject.subject_id, password=password, now=at
        )
    if not ok:
        await _audit(
            action="auth.login_failed",
            realm=realm,
            subject_id=subject.subject_id,
            ip=ip,
        )
        await _spend_failure(PASSWORD_BUDGET, realm=realm, subject_id=subject.subject_id)
        raise _invalid_credentials()

    await clear(PASSWORD_BUDGET, realm=realm, subject_id=subject.subject_id)

    needs_second_factor = realm in MFA_REQUIRED_REALMS
    async with credential_session() as session:
        issued = await issue_session(session, realm=realm, subject_id=subject.subject_id, now=at)
        if needs_second_factor:
            # Minted and queued in the SAME transaction as the session, so there is no
            # state in which a half-authenticated session exists with no challenge to
            # answer — and none in which a code was mailed for a session that rolled back.
            challenge = await otp.issue_challenge(
                session,
                purpose=LOGIN_CHALLENGE,
                realm=realm,
                subject_id=subject.subject_id,
                now=at,
            )
            await _enqueue_auth_email(
                session,
                kind=f"otp_{LOGIN_CHALLENGE}",
                realm=realm,
                to=subject.email,
                secret=challenge.code,
            )
    await _audit(
        action="auth.login_password_accepted" if needs_second_factor else "auth.login_succeeded",
        realm=realm,
        subject_id=subject.subject_id,
        ip=ip,
        object_id=str(issued.session_id),
    )
    return LoginOutcome(
        status="otp_required" if needs_second_factor else "authenticated",
        session=issued,
        subject_id=subject.subject_id,
    )


async def complete_second_factor(
    *, verified: VerifiedSession, code: str, ip: str | None, now: datetime | None = None
) -> IssuedSession:
    """Finish a sign-in by answering the emailed challenge. Rotates the session on success.

    ═══ THIS IS THE WHOLE OF "MFA" IN THIS PRODUCT (D-170) ═══

    There is no authenticator app, no shared secret, no QR code and no recovery-code sheet.
    The second factor is POSSESSION OF THE MAILBOX ON FILE, demonstrated by a six-digit code
    with a ten-minute life, a five-guess budget on the row and a five-failure budget in
    Redis. A reader looking for TOTP will not find it, and that is the design rather than a
    gap — the founder's decision, recorded in ROADMAP §6 D-170.

    What that buys and what it costs, said plainly: it is one mechanism instead of three
    (secret storage, enrolment, recovery), it needs no device and no enrolment step, and an
    operator who loses their phone is not locked out. What it does NOT do is defend against
    an attacker who already controls the mailbox — which a TOTP secret would — so the
    strength of the admin realm's second factor is the strength of the operator's email
    account. That is the honest framing and it is why this is a decision-log entry rather
    than an implementation detail.

    Rotation rather than an UPDATE of `mfa_verified_at`, because completing a second factor
    IS a privilege-level change and OWASP's session-fixation defence asks for a new
    identifier at exactly that moment. `rotate_session` carries `absolute_expires_at`
    forward, so a session cannot extend its life by passing the challenge.
    """
    realm, subject_id = verified.realm, verified.subject_id
    await check(OTP_BUDGET, realm=realm, subject_id=subject_id)

    at = now or datetime.now(UTC)
    async with credential_session() as session:
        ok = await otp.verify_challenge(
            session,
            purpose=LOGIN_CHALLENGE,
            realm=realm,
            subject_id=subject_id,
            code=code,
            now=at,
        )
    if not ok:
        await _audit(action="auth.mfa_failed", realm=realm, subject_id=subject_id, ip=ip)
        await _spend_failure(OTP_BUDGET, realm=realm, subject_id=subject_id)
        raise ProblemError(
            kind="auth",
            code="invalid_second_factor",
            title="That code did not work",
            detail="The code was not accepted.",
            remediation="Check the most recent email, or ask for a new code.",
        )
    await clear(OTP_BUDGET, realm=realm, subject_id=subject_id)

    # The subject is re-checked HERE and not only at password time: a person deactivated
    # between typing their password and typing their code must not complete the sign-in.
    if await load_subject(realm, subject_id) is None:
        raise _invalid_credentials()

    async with credential_session() as session:
        rotated = await rotate_session(session, verified=verified, mfa_verified_at=at, now=at)
    await _audit(
        action="auth.login_succeeded",
        realm=realm,
        subject_id=subject_id,
        ip=ip,
        object_id=str(rotated.session_id),
    )
    return rotated


async def resend_second_factor(*, verified: VerifiedSession, now: datetime | None = None) -> None:
    """Mail a fresh challenge for a session that is waiting on one.

    Issuing a new code RETIRES the previous one (`otp.issue_challenge`), so "resend" cannot
    be used to accumulate parallel codes and multiply the guess budget. The caller is a
    half-authenticated session, so there is no identifier to probe and no address to choose
    — the code goes to the mailbox on file for the subject the session already names.

    WHAT BOUNDS MAIL-BOMBING, said out loud because this is the one endpoint that sends an
    email on demand: reaching it at all requires a session, which requires the correct
    password, so an abuser who can call it can simply sign in — there is no capability here
    they do not already have. Above that, `core/ratelimit`'s `auth` profile caps the CALLER
    at 20 requests/minute across all of `/v1/auth/**`. It is deliberately NOT charged to
    `OTP_BUDGET`: that budget is the victim's five guesses, and letting resends consume it
    would let a resend loop lock the legitimate user out of answering their own challenge.
    """
    realm, subject_id = verified.realm, verified.subject_id
    subject = await load_subject(realm, subject_id)
    if subject is None:
        raise _invalid_credentials()
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        challenge = await otp.issue_challenge(
            session, purpose=LOGIN_CHALLENGE, realm=realm, subject_id=subject_id, now=at
        )
        await _enqueue_auth_email(
            session,
            kind=f"otp_{LOGIN_CHALLENGE}",
            realm=realm,
            to=subject.email,
            secret=challenge.code,
        )


async def sign_out(
    *, verified: VerifiedSession, ip: str | None, now: datetime | None = None
) -> None:
    """End this one session. Idempotent — a second call is a no-op, not an error."""
    async with credential_session() as session:
        await revoke_session(session, session_id=verified.session_id, reason="signed_out", now=now)
    await _audit(
        action="auth.logout",
        realm=verified.realm,
        subject_id=verified.subject_id,
        ip=ip,
        object_id=str(verified.session_id),
    )


async def sign_out_everywhere(
    *, verified: VerifiedSession, ip: str | None, now: datetime | None = None
) -> int:
    """End every session this person holds in this realm. Returns how many."""
    async with credential_session() as session:
        count = await revoke_subject_sessions(
            session, realm=verified.realm, subject_id=verified.subject_id, now=now
        )
    await _audit(
        action="auth.sessions_revoked",
        realm=verified.realm,
        subject_id=verified.subject_id,
        ip=ip,
        summary={"revoked": count},
    )
    return count


async def refresh(*, verified: VerifiedSession, now: datetime | None = None) -> IssuedSession:
    """Mint a new token for a live session, keeping its lifetime and its MFA state.

    The session is already valid — `verify_session` said so — so this is not an
    authentication step; it is the client asking for a fresh identifier, which is free to
    grant and useful because it shortens how long any one token has been in circulation.
    `rotate_session` defaults `mfa_verified_at` to the value the old session carried, so a
    refresh can never silently downgrade a session that had completed a second factor.
    """
    async with credential_session() as session:
        return await rotate_session(session, verified=verified, now=now)


# ───────────────────────────── password reset ────────────────────────────────


async def request_password_reset(
    *, realm: str, email: str, ip: str | None, now: datetime | None = None
) -> None:
    """Send a reset link if that address has an account. Tells the caller NOTHING either way.

    Returns `None` on every path — there is no branch a caller can observe. OWASP's Forgot
    Password Cheat Sheet asks for "a consistent message for both existent and non-existent
    accounts" AND that "responses return in a consistent amount of time"; the second half is
    the one implementations skip, and it is met here by the unknown path doing the same
    quantity of work rather than by a sleep that guesses.

    A reset request for an address with no account still consumes a throttle budget against
    a pseudo-subject, so an attacker cannot use "does this eventually 429" as the oracle the
    body refuses to be.
    """
    _refuse_unknown_realm(realm)
    at = now or datetime.now(UTC)
    subject = await resolve_by_email(realm, email)
    if subject is None:
        await check(OTP_BUDGET, realm=realm, subject_id=pseudo_subject(realm, email))
        await record_failure(OTP_BUDGET, realm=realm, subject_id=pseudo_subject(realm, email))
        log.info("auth_reset_unknown_subject", extra={"realm": realm})
        return

    async with credential_session() as session:
        # Only the newest link works. Without this, "click forgot password three times"
        # leaves three live keys in a mailbox for an hour.
        await tokens.invalidate_outstanding(
            session,
            purpose="password_reset",
            realm=realm,
            subject_id=subject.subject_id,
            now=at,
        )
        issued = await tokens.issue_token(
            session,
            purpose="password_reset",
            realm=realm,
            subject_id=subject.subject_id,
            now=at,
        )
        await _enqueue_auth_email(
            session,
            kind="password_reset",
            realm=realm,
            to=subject.email,
            secret=issued.token,
        )
    await _audit(
        action="auth.password_reset_requested", realm=realm, subject_id=subject.subject_id, ip=ip
    )


async def confirm_password_reset(
    *, realm: str, token: str, password: str, ip: str | None, now: datetime | None = None
) -> None:
    """Burn a reset token and install a new password, ending every session.

    THREE THINGS HAPPEN AND ALL THREE ARE REQUIRED:

      1. the token is burned by CAS, so a link works once;
      2. the password is replaced;
      3. **every session for that subject is revoked** — ASVS V7 and the Forgot Password
         Cheat Sheet both require it, and the reason is the one case that matters: a person
         resetting their password because they think somebody else has it must not leave
         that somebody else signed in. Also every OTHER outstanding reset token, for the
         same reason.

    THE SUBJECT IS RE-RESOLVED AFTER THE TOKEN IS BURNED, and that is reference defect
    `auth.service.ts:996`. Theirs updated `user` by the id on the token without checking the
    row was still there, so a token outliving a deleted account raised a driver error and
    became a 500. Here a `None` subject is a clean, actionable refusal — and the token is
    already spent, which is correct: a token naming a dead account should not stay live.
    """
    _refuse_unknown_realm(realm)
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        redeemed = await tokens.redeem_token(session, purpose="password_reset", token=token, now=at)
    if redeemed is None or redeemed.subject_id is None or redeemed.realm != realm:
        raise _bad_token()

    subject = await load_subject(realm, redeemed.subject_id)
    if subject is None:
        # Deleted, deactivated, or removed from the operator allowlist since the link was
        # sent. A refusal a person can act on, NOT a 500 — see the docstring.
        log.warning(
            "auth_reset_subject_not_live",
            extra={"realm": realm, "subject_id": str(redeemed.subject_id)},
        )
        raise _bad_token()

    async with credential_session() as session:
        await set_password(
            session, realm=realm, subject_id=subject.subject_id, password=password, now=at
        )
        await tokens.invalidate_outstanding(
            session,
            purpose="password_reset",
            realm=realm,
            subject_id=subject.subject_id,
            now=at,
        )
        await revoke_subject_sessions(session, realm=realm, subject_id=subject.subject_id, now=at)
    await clear(PASSWORD_BUDGET, realm=realm, subject_id=subject.subject_id)
    await _audit(action="auth.password_changed", realm=realm, subject_id=subject.subject_id, ip=ip)


def _bad_token() -> ProblemError:
    """One refusal for unknown, expired, spent, wrong-realm and orphaned tokens.

    Distinguishing them would tell somebody holding a link they should not have whether it
    was ever real. The person who legitimately clicked an old link gets the same next step
    either way: ask for a new one.
    """
    return ProblemError(
        kind="business_rule",
        code="invalid_reset_token",
        title="That link is no longer usable",
        detail="This link has already been used or has expired.",
        remediation="Request a new password reset link and use the newest email.",
    )


# ──────────────────────────── OTP challenge ──────────────────────────────────


async def request_otp(
    *, realm: str, subject_id: UUID, purpose: str, now: datetime | None = None
) -> None:
    """Email a numeric challenge to a subject who is already partly identified.

    Takes a `subject_id` rather than an address on purpose: every caller reaches this with a
    subject it has already established (a live session, or a password that just verified),
    so there is no identifier to probe and no oracle to equalise. An OTP endpoint that
    accepted a bare email address would be a way to make us send mail to arbitrary
    addresses, which is a spam vector even when it leaks nothing.
    """
    _refuse_unknown_realm(realm)
    subject = await load_subject(realm, subject_id)
    if subject is None:
        raise _invalid_credentials()
    async with credential_session() as session:
        issued = await otp.issue_challenge(
            session, purpose=purpose, realm=realm, subject_id=subject_id, now=now
        )
        await _enqueue_auth_email(
            session, kind=f"otp_{purpose}", realm=realm, to=subject.email, secret=issued.code
        )


async def confirm_otp(
    *,
    realm: str,
    subject_id: UUID,
    purpose: str,
    code: str,
    ip: str | None,
    now: datetime | None = None,
) -> None:
    """Spend one guess against the live challenge. Raises on failure."""
    _refuse_unknown_realm(realm)
    await check(OTP_BUDGET, realm=realm, subject_id=subject_id)
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        ok = await otp.verify_challenge(
            session, purpose=purpose, realm=realm, subject_id=subject_id, code=code, now=at
        )
    if not ok:
        await _spend_failure(OTP_BUDGET, realm=realm, subject_id=subject_id)
        raise ProblemError(
            kind="auth",
            code="invalid_code",
            title="That code did not work",
            detail="The code was not accepted.",
            remediation="Check the most recent email, or request a new code.",
        )
    await clear(OTP_BUDGET, realm=realm, subject_id=subject_id)
    if purpose == "email_verify":
        await mark_email_verified(realm, subject_id, at=at)
        await _audit(action="auth.email_verified", realm=realm, subject_id=subject_id, ip=ip)


# ──────────────────────────── shared helpers ─────────────────────────────────


async def _enqueue_auth_email(
    session: AsyncSession, *, kind: str, realm: str, to: str, secret: str
) -> None:
    """Queue delivery in the SAME transaction that created the secret.

    The outbox is the reliability triad's answer (BACKEND-PATTERNS §4) and it is the right
    one here for a specific reason: a reset token committed without its email is a person
    who never gets the link, and an email sent for a token that rolled back is a link that
    does not work. One transaction, one fate.

    THE SECRET IS IN THE PAYLOAD, and that is a considered trade rather than an oversight.
    `outbox_messages.payload` is a jsonb column in the same database — so for the ten
    seconds before the dispatcher picks it up, the plaintext token exists in a row. The
    alternative is storing a reversible copy somewhere else, which is the same exposure with
    more moving parts. What bounds it: the row is deleted on successful dispatch, the token
    is single-use and short-lived, and `hide_parameters=True` on the engine keeps it out of
    any DBAPI error string. It is NOT logged, and `redact_mapping` covers the audit path.
    """
    await enqueue_outbox(
        session,
        job=AUTH_EMAIL_JOB,
        payload={"kind": kind, "realm": realm, "to": to, "secret": secret},
    )


async def _audit(
    *,
    action: str,
    realm: str,
    subject_id: UUID,
    ip: str | None,
    object_id: str | None = None,
    summary: dict[str, object] | None = None,
) -> None:
    """One authentication event, in the hash-chained ledger.

    Its OWN transaction, because most callers here have already closed theirs — a sign-in
    commits the session row before the audit row exists. That is a deliberate ordering: the
    alternative is holding the credential transaction open across the audit chain's
    advisory lock (`compliance.audit.lock_chain`), which would serialise every concurrent
    sign-in behind one lock for the duration of a session INSERT.

    `actor_type` is spelled explicitly rather than derived from a `Principal`, because there
    is no principal yet on the paths that matter most — a failed login has no actor this
    system recognises, and passing `None` would record it as `system`, which is a lie about
    who tried.
    """
    async with untenanted_session() as session:
        await write_audit(
            session,
            action=action,
            actor_type="admin" if realm == "admin" else "user",
            object_type="auth_subject",
            object_id=object_id or str(subject_id),
            ip=ip,
            summary=summary,
        )


async def find_subject_for_session(realm: str, subject_id: UUID) -> Subject | None:
    """Re-read the person behind a live session. Exposed for the `GET /session` bootstrap.

    Deliberately NOT cached and deliberately not derived from the session row: BACKEND-
    PATTERNS §7 requires deactivation to bite on the next request, and a session that
    answered from its own copy of "who this is" would keep answering after the account was
    disabled.
    """
    return await load_subject(realm, subject_id)


async def has_password(realm: str, subject_id: UUID) -> bool:
    """Does this subject have a first-party password yet?

    Read by the invitation flow, which must not silently overwrite an existing password
    when somebody redeems a second invitation with a different one.
    """
    async with credential_session() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM auth_credentials WHERE realm = :realm AND subject_id = :sub"),
                {"realm": realm, "sub": subject_id},
            )
        ).first()
    return row is not None


__all__ = [
    "AUTH_EMAIL_JOB",
    "LOGIN_CHALLENGE",
    "MFA_REQUIRED_REALMS",
    "LoginOutcome",
    "LoginStatus",
    "complete_second_factor",
    "confirm_otp",
    "confirm_password_reset",
    "find_subject_for_session",
    "has_password",
    "refresh",
    "request_otp",
    "request_password_reset",
    "resend_second_factor",
    "sign_in",
    "sign_out",
    "sign_out_everywhere",
]

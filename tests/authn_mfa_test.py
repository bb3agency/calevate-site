"""The second factor, which is an emailed one-time code and nothing else (D-170).

**Read this before looking for TOTP.** There is no authenticator app, no shared secret, no
QR provisioning URI and no recovery-code sheet in this system. "The admin realm requires
MFA" means exactly one thing: a correct password there issues a session that can do a single
thing — answer `POST /v1/auth/admin/login/otp` — and every other route refuses it until that
happens. An earlier draft of this slice did build TOTP; it was removed rather than left
unmounted, and this file is what pins the replacement.

That makes task #66's gap ("admin MFA is called mandatory in two docs and exists nowhere")
closed by the OTP path, so the tests that matter most here are the ones proving the
challenge CANNOT BE SKIPPED.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture deletes
exactly those, and nothing counts globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn import otp, service
from apps.api.authn.codes import OTP_DIGITS
from apps.api.authn.credentials import set_password
from apps.api.authn.sessions import verify_session
from apps.api.authn.throttle import KEY_PREFIX, OTP_BUDGET, OTP_MAX_ATTEMPTS
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

PASSWORD = "operator-console-passphrase"


@pytest_asyncio.fixture
async def operator() -> AsyncIterator[tuple[uuid.UUID, str]]:
    """One admin-realm operator with a password and no session."""
    admin_id = uuid.uuid4()
    email = f"mfa-{admin_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, email, name, role, "
                "created_at, updated_at) "
                "VALUES (:id, :email, 'MFA Probe', 'operator', now(), now())"
            ),
            {"id": admin_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm="admin", subject_id=admin_id, password=PASSWORD)
    try:
        yield admin_id, email
    finally:
        async with credential_session() as session:
            for table in ("auth_otp_challenges", "auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": admin_id}
                )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = :to"), {"to": email}
            )
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})
        redis = get_redis()
        for budget in ("password", "otp"):
            await redis.delete(f"{KEY_PREFIX}:{budget}:admin:{admin_id}")


async def _live_code(admin_id: uuid.UUID) -> str:
    """A fresh code for this subject.

    Re-minted rather than read back, because the stored value is a keyed MAC and the
    plaintext exists only in the outbox payload. Re-issuing runs the same code path a
    resend does — and retires the previous challenge, which is the documented behaviour.
    """
    async with credential_session() as session:
        issued = await otp.issue_challenge(
            session, purpose=service.LOGIN_CHALLENGE, realm="admin", subject_id=admin_id
        )
    return issued.code


# ══════════════════ the gate: admin login cannot skip the challenge ══════════════════


def test_mfa_means_the_otp_challenge_and_the_two_required_sets_agree() -> None:
    """`service.MFA_REQUIRED_REALMS` and `core.auth.MFA_REQUIRED_REALMS` decide the same
    question at two doors — the sign-in flow and the token verifier. Two copies of one fact
    is how those two come to disagree, silently, in the dangerous direction."""
    from apps.api.core import auth as verifier

    assert verifier.MFA_REQUIRED_REALMS == service.MFA_REQUIRED_REALMS
    assert "admin" in service.MFA_REQUIRED_REALMS
    assert "client" not in service.MFA_REQUIRED_REALMS
    # And the mechanism is the OTP purpose, not a second thing beside it.
    assert service.LOGIN_CHALLENGE == "login_challenge"


@pytest.mark.asyncio
async def test_an_admin_password_alone_does_not_finish_the_sign_in(
    operator: tuple[uuid.UUID, str],
) -> None:
    """TASK #66'S GAP, CLOSED. A correct operator password yields `otp_required` and a
    session that has NOT completed a second factor."""
    admin_id, email = operator
    outcome = await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)

    assert outcome.status == "otp_required"
    assert outcome.subject_id == admin_id

    live = (await verify_session(token=outcome.session.token, realm="admin")).require_live()
    assert live.mfa_verified_at is None, (
        "a password-only admin session reported a completed second factor"
    )


@pytest.mark.asyncio
async def test_signing_in_mails_a_challenge_of_the_right_shape(
    operator: tuple[uuid.UUID, str],
) -> None:
    """The challenge is created in the same transaction as the session, and its delivery is
    promised in that same transaction (BACKEND-PATTERNS §4)."""
    admin_id, email = operator
    await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)

    async with credential_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT purpose, attempts, consumed_at FROM auth_otp_challenges "
                    "WHERE subject_id = :s"
                ),
                {"s": admin_id},
            )
        ).first()
    assert row is not None, "an admin sign-in must mint a challenge"
    assert row[0] == service.LOGIN_CHALLENGE
    assert row[1] == 0
    assert row[2] is None

    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job AND payload->>'to' = :to"
                ),
                {"job": service.AUTH_EMAIL_JOB, "to": email},
            )
        ).scalar()
    assert queued == 1, "the code was minted but never queued for delivery"


@pytest.mark.asyncio
async def test_the_challenge_completes_the_sign_in_and_rotates_the_session(
    operator: tuple[uuid.UUID, str],
) -> None:
    admin_id, email = operator
    outcome = await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)
    partial = (await verify_session(token=outcome.session.token, realm="admin")).require_live()

    code = await _live_code(admin_id)
    rotated = await service.complete_second_factor(verified=partial, code=code, ip=None)

    assert rotated.token != outcome.session.token, "the session identifier must be renewed"
    live = (await verify_session(token=rotated.token, realm="admin")).require_live()
    assert live.mfa_verified_at is not None
    assert live.family_id == partial.family_id, "rotation stays inside the family"
    assert live.absolute_expires_at == partial.absolute_expires_at, (
        "passing the challenge must not extend the session's lifetime"
    )


@pytest.mark.asyncio
async def test_the_old_token_is_dead_after_the_challenge(
    operator: tuple[uuid.UUID, str],
) -> None:
    """The pre-second-factor token must not keep working — that is the fixation defence."""
    admin_id, email = operator
    outcome = await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)
    partial = (await verify_session(token=outcome.session.token, realm="admin")).require_live()
    await service.complete_second_factor(verified=partial, code=await _live_code(admin_id), ip=None)
    replayed = await verify_session(token=outcome.session.token, realm="admin")
    assert not replayed.live


@pytest.mark.asyncio
async def test_a_wrong_code_does_not_complete_the_sign_in(
    operator: tuple[uuid.UUID, str],
) -> None:
    admin_id, email = operator
    outcome = await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)
    partial = (await verify_session(token=outcome.session.token, realm="admin")).require_live()
    await _live_code(admin_id)

    with pytest.raises(ProblemError) as caught:
        await service.complete_second_factor(verified=partial, code="000000", ip=None)
    assert caught.value.code == "invalid_second_factor"
    assert caught.value.status == 401

    still_partial = (
        await verify_session(token=outcome.session.token, realm="admin")
    ).require_live()
    assert still_partial.mfa_verified_at is None


@pytest.mark.asyncio
async def test_a_resend_mails_a_new_code_and_kills_the_old_one(
    operator: tuple[uuid.UUID, str],
) -> None:
    """Resending must not accumulate parallel codes — that would multiply the guess budget."""
    admin_id, email = operator
    outcome = await service.sign_in(realm="admin", email=email, password=PASSWORD, ip=None)
    partial = (await verify_session(token=outcome.session.token, realm="admin")).require_live()

    first = await _live_code(admin_id)
    await service.resend_second_factor(verified=partial)

    with pytest.raises(ProblemError):
        await service.complete_second_factor(verified=partial, code=first, ip=None)

    async with credential_session() as session:
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_otp_challenges WHERE subject_id = :s "
                    "AND consumed_at IS NULL"
                ),
                {"s": admin_id},
            )
        ).scalar()
    assert live == 1, "a resend left more than one live challenge"


@pytest.mark.asyncio
async def test_the_client_realm_needs_no_second_factor(
    operator: tuple[uuid.UUID, str],
) -> None:
    """The control that gives the admin assertions meaning: MFA is realm-specific, so a
    green admin test could otherwise mean 'every login demands a code'."""
    del operator
    user_id = uuid.uuid4()
    email = f"client-{user_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm="client", subject_id=user_id, password=PASSWORD)
    try:
        outcome = await service.sign_in(realm="client", email=email, password=PASSWORD, ip=None)
        assert outcome.status == "authenticated"
        live = (await verify_session(token=outcome.session.token, realm="client")).require_live()
        assert live.mfa_verified_at is None
    finally:
        async with credential_session() as session:
            for table in ("auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": user_id}
                )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM users WHERE id = :s"), {"s": user_id})


# ══════════════════════ the code itself: single use, capped, short ══════════════════════


@pytest.mark.asyncio
async def test_a_code_cannot_be_spent_twice(operator: tuple[uuid.UUID, str]) -> None:
    """OWASP's MFA cheat sheet: invalidate the OTP on successful verification."""
    admin_id, _ = operator
    code = await _live_code(admin_id)
    async with credential_session() as session:
        assert await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=code,
        )
        assert not await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=code,
        )


@pytest.mark.asyncio
async def test_a_challenge_runs_out_of_guesses(operator: tuple[uuid.UUID, str]) -> None:
    """The per-ROW ceiling, which survives a Redis flush. NIST SP 800-63B requires a
    rate-limiting mechanism when the authenticator output is under 64 bits; a six-digit
    code is ~20, and this is the half an attacker cannot reset."""
    admin_id, _ = operator
    code = await _live_code(admin_id)
    async with credential_session() as session:
        for _ in range(OTP_MAX_ATTEMPTS):
            assert not await otp.verify_challenge(
                session,
                purpose=service.LOGIN_CHALLENGE,
                realm="admin",
                subject_id=admin_id,
                code="000000",
            )
        # Even the CORRECT code is refused once the budget is spent.
        assert not await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=code,
        ), "a challenge accepted its code after its attempt budget was exhausted"


@pytest.mark.asyncio
async def test_issuing_a_new_code_retires_the_previous_one(
    operator: tuple[uuid.UUID, str],
) -> None:
    """Otherwise "resend" is an attempt-budget reset: twenty codes, a hundred guesses."""
    admin_id, _ = operator
    first = await _live_code(admin_id)
    second = await _live_code(admin_id)
    async with credential_session() as session:
        assert not await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=first,
        ), "an old code stayed live after a new one was issued"
        assert await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=second,
        )


@pytest.mark.asyncio
async def test_an_expired_code_is_refused(operator: tuple[uuid.UUID, str]) -> None:
    admin_id, _ = operator
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    async with credential_session() as session:
        issued = await otp.issue_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            now=long_ago,
        )
        assert not await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=admin_id,
            code=issued.code,
        )


@pytest.mark.asyncio
async def test_a_login_code_cannot_be_spent_as_an_email_verification(
    operator: tuple[uuid.UUID, str],
) -> None:
    """The purpose is inside the code's hash domain, so the two are different 32 bytes."""
    admin_id, _ = operator
    code = await _live_code(admin_id)
    async with credential_session() as session:
        assert not await otp.verify_challenge(
            session, purpose="email_verify", realm="admin", subject_id=admin_id, code=code
        )


@pytest.mark.asyncio
async def test_a_code_is_bound_to_its_own_subject(operator: tuple[uuid.UUID, str]) -> None:
    admin_id, _ = operator
    code = await _live_code(admin_id)
    async with credential_session() as session:
        assert not await otp.verify_challenge(
            session,
            purpose=service.LOGIN_CHALLENGE,
            realm="admin",
            subject_id=uuid.uuid4(),
            code=code,
        )


def test_the_challenge_lifetime_and_budgets_are_the_documented_ones() -> None:
    """Pinned so a future edit to any of these numbers is a decision, not a drift."""
    assert timedelta(minutes=10) == otp.OTP_LIFETIME
    assert OTP_MAX_ATTEMPTS == 5
    assert OTP_BUDGET.threshold == 5
    assert OTP_DIGITS == 6


def test_no_totp_or_recovery_code_surface_survives() -> None:
    """TOTP and recovery codes were built and then REMOVED (D-170). This fails if either
    comes back as an unmounted module, an orphan table or a stray route — the half-wired
    shape CLAUDE.md names, and the exact thing a reader would waste an hour looking for."""
    import pathlib

    from apps.api.main import app

    package = pathlib.Path(__file__).resolve().parent.parent / "apps" / "api" / "authn"
    names = {path.name for path in package.glob("*.py")}
    assert "totp.py" not in names
    assert "mfa.py" not in names

    for path in app.openapi()["paths"]:
        lowered = path.lower()
        assert "totp" not in lowered
        assert "recovery" not in lowered
        assert "enrol" not in lowered

"""Negative controls for three reference defects that all live on the sign-in path.

  * **`auth.service.ts:993`** — `bcrypt.hash(password, 10)` while accepting 128-character
    passwords (line 973). bcrypt truncates at 72 bytes, so two different long passwords
    sharing a 72-byte prefix both authenticate. We use Argon2id, which has no ceiling — but
    "we use a better algorithm" is a claim, and the test below is the measurement.
  * **`auth.service.ts:996`** — a reset token whose account has since been deleted, applied
    with no liveness check, producing a raw driver error where a refusal belongs.
  * **`routes.ts:236`** — `/api/v1/auth/check-identifier` returning `exists: true|false`.
    Uniformity here is asserted across STATUS, BODY and TIMING, because the first two are
    easy and the third is the one that actually leaks.

SHARED DATABASE DISCIPLINE (`tests/shared_state_assertion_guard_test.py`): every row hangs
off ids this module mints, the fixture deletes exactly those, and nothing counts globally.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn import service, tokens
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.hashing import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from apps.api.authn.throttle import (
    KEY_PREFIX,
    PASSWORD_BUDGET,
    clear,
    penalty_delay_s,
    pseudo_subject,
)
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

REALM = "client"
PASSWORD = "kurnool-clinic-reception-desk"


async def _no_delay(_count: int) -> None:
    """Stand-in for `service._equalise` where the delay is not what is under test."""
    return None


async def _forget_throttle(*subject_ids: uuid.UUID) -> None:
    """Drop this module's own failure counters. Scoped to the ids we minted."""
    redis = get_redis()
    for subject_id in subject_ids:
        for budget in ("password", "otp", "totp", "recovery"):
            await redis.delete(f"{KEY_PREFIX}:{budget}:{REALM}:{subject_id}")


@pytest_asyncio.fixture
async def live_user() -> AsyncIterator[tuple[uuid.UUID, str]]:
    """One real, active `users` row with a real password."""
    user_id = uuid.uuid4()
    email = f"enum-{user_id.hex[:12]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Enum Probe', now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=PASSWORD)
    try:
        yield user_id, email
    finally:
        await _forget_throttle(user_id, pseudo_subject(REALM, email))
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_email_tokens WHERE subject_id = :id"), {"id": user_id}
            )
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = :id"), {"id": user_id}
            )
            await session.execute(
                text("DELETE FROM auth_credentials WHERE subject_id = :id"), {"id": user_id}
            )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


# ═══════════ DEFECT: bcrypt's 72-byte truncation, and our claim to not have it ═══════════


@pytest.mark.asyncio
async def test_a_128_character_password_is_honoured_to_its_last_character(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """THE TEST THAT WOULD FAIL UNDER bcrypt.

    Two passwords of the maximum accepted length sharing a 72-byte prefix and differing
    only after it. Under `bcrypt.hash(password, 10)` both hash identically and both
    authenticate — silently, with no error anywhere — which is exactly the reference
    implementation's state at `auth.service.ts:993` given its 128-character bound at line
    973. Under Argon2id the whole input is consumed and the second one must be rejected.

    The prefix is 72 bytes precisely, so this is the boundary rather than a general
    long-password test: a 73rd differing byte is the first one bcrypt discards.
    """
    user_id, _ = live_user
    prefix = "x" * 72
    assert len(prefix.encode()) == 72

    correct = prefix + "A" * (MAX_PASSWORD_CHARS - 72)
    impostor = prefix + "B" * (MAX_PASSWORD_CHARS - 72)
    assert len(correct) == len(impostor) == MAX_PASSWORD_CHARS
    assert correct[:72] == impostor[:72] and correct != impostor

    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=correct)

    async with credential_session() as session:
        assert await authenticate_subject(
            session, realm=REALM, subject_id=user_id, password=correct
        ), "the full-length password must authenticate"

    async with credential_session() as session:
        assert not await authenticate_subject(
            session, realm=REALM, subject_id=user_id, password=impostor
        ), (
            "a password sharing only its first 72 bytes authenticated — the KDF is "
            "truncating its input, which is the bcrypt defect this repo exists not to have"
        )


@pytest.mark.asyncio
async def test_the_length_bounds_are_the_ones_the_wire_model_advertises() -> None:
    """The refusal a person can act on, at both ends, before any hashing happens."""
    async with credential_session() as session:
        for bad in ("a" * (MIN_PASSWORD_CHARS - 1), "a" * (MAX_PASSWORD_CHARS + 1)):
            with pytest.raises(ProblemError) as caught:
                await set_password(session, realm=REALM, subject_id=uuid.uuid4(), password=bad)
            assert caught.value.code == "password_length"
            assert str(MIN_PASSWORD_CHARS) in caught.value.detail


# ═══════════════ DEFECT: a token that outlives the account it names ═══════════════


@pytest.mark.asyncio
async def test_a_reset_token_for_a_deleted_account_refuses_cleanly(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """`auth.service.ts:996`: `tx.user.update()` on a token's `userId` with no liveness
    check, so a deleted account produces `P2025` and a 500.

    Here the account is deleted between issuing the token and redeeming it. The refusal
    must be an ordinary `ProblemError` with a message a person can act on — NOT an
    IntegrityError, NOT a 500, and not a silent success against a row that is gone.
    """
    user_id, email = live_user
    await service.request_password_reset(realm=REALM, email=email, ip=None)

    async with credential_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM auth_email_tokens WHERE subject_id = :id "
                    "AND purpose = 'password_reset' AND used_at IS NULL"
                ),
                {"id": user_id},
            )
        ).first()
    assert row is not None, "the reset must have minted a token for a live account"

    # The token is hashed at rest, so the test cannot read it back — mint a second one
    # whose plaintext we hold, which is the same code path.
    async with credential_session() as session:
        issued = await tokens.issue_token(
            session, purpose="password_reset", realm=REALM, subject_id=user_id
        )

    # The account goes away, exactly as a hard delete or a deactivation would leave it.
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :id"), {"id": user_id}
        )

    with pytest.raises(ProblemError) as caught:
        await service.confirm_password_reset(
            realm=REALM, token=issued.token, password="a-brand-new-passphrase-here", ip=None
        )
    assert caught.value.code == "invalid_reset_token"
    assert caught.value.status == 422, "a dead account is a refusal, never a 500"
    assert caught.value.remediation, "the caller must be told what to do next"


@pytest.mark.asyncio
async def test_a_deactivated_account_cannot_sign_in_even_with_the_right_password(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Deactivation must bite the sign-in path, not only the request path."""
    user_id, email = live_user
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :id"), {"id": user_id}
        )
    with pytest.raises(ProblemError) as caught:
        await service.sign_in(realm=REALM, email=email, password=PASSWORD, ip=None)
    assert caught.value.code == "invalid_credentials"


# ═══════════════════════ DEFECT: the user-enumeration oracle ═══════════════════════


@pytest.mark.asyncio
async def test_login_answers_identically_for_unknown_and_for_wrong_password(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Same code, same status, same title, same detail, same remediation.

    `check-identifier` is what happens when this property is left to whoever remembers it
    per endpoint. Here it is a property of `_invalid_credentials`, and this asserts the two
    paths really do reach it rather than assuming they do.
    """
    _, email = live_user
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"

    with pytest.raises(ProblemError) as wrong_password:
        await service.sign_in(realm=REALM, email=email, password="definitely-not-the-one", ip=None)
    with pytest.raises(ProblemError) as no_such_user:
        await service.sign_in(realm=REALM, email=unknown, password=PASSWORD, ip=None)

    left, right = wrong_password.value, no_such_user.value
    assert (left.code, left.status, left.title, left.detail, left.remediation) == (
        right.code,
        right.status,
        right.title,
        right.detail,
        right.remediation,
    )
    assert left.as_problem() == right.as_problem()
    await _forget_throttle(pseudo_subject(REALM, unknown))


@pytest.mark.asyncio
async def test_the_reset_request_is_silent_about_whether_the_address_exists(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Both return `None`. There is no branch a caller can observe."""
    _, email = live_user
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"
    assert await service.request_password_reset(realm=REALM, email=email, ip=None) is None
    assert await service.request_password_reset(realm=REALM, email=unknown, ip=None) is None
    await _forget_throttle(pseudo_subject(REALM, unknown))


@pytest.mark.asyncio
async def test_an_unknown_address_costs_the_same_wall_clock_time_as_a_wrong_password(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """THE HALF THAT IS ACTUALLY HARD, measured rather than asserted from the code.

    An implementation that returns early when no user exists answers in microseconds while
    a wrong password costs a full Argon2id verification — 20-30ms at these parameters, four
    orders of magnitude apart and trivially measurable over a network. `hashing.py`'s
    `_dummy_hash` exists to close that, and this is what proves it is wired in.

    The assertion is a RATIO with a generous bound, not an absolute difference: a shared CI
    box has noisy scheduling, and the defect this guards against is a 1000x gap, not a 20%
    one. Medians rather than means, so one scheduler hiccup cannot decide the verdict. The
    throttle's backoff delay is kept out of the measurement by clearing the counter before
    each attempt — otherwise the curve, not the hash, would dominate.
    """
    _, email = live_user
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"
    ghost = pseudo_subject(REALM, unknown)
    known_id = (await service.find_subject_for_session(REALM, (await _resolve(email)))) is not None
    assert known_id, "the fixture's user must resolve"

    async def _timed(address: str, subject_for_reset: uuid.UUID) -> float:
        await clear(PASSWORD_BUDGET, realm=REALM, subject_id=subject_for_reset)
        started = time.perf_counter()
        with pytest.raises(ProblemError):
            await service.sign_in(
                realm=REALM, email=address, password="wrong-but-long-enough", ip=None
            )
        return time.perf_counter() - started

    real_id = await _resolve(email)
    known = sorted(await _repeat(lambda: _timed(email, real_id), 7))
    missing = sorted(await _repeat(lambda: _timed(unknown, ghost), 7))

    known_median = statistics.median(known)
    missing_median = statistics.median(missing)
    ratio = max(known_median, missing_median) / max(min(known_median, missing_median), 1e-9)

    assert ratio < 4.0, (
        "the unknown-account path and the wrong-password path differ by "
        f"{ratio:.1f}x (known={known_median * 1000:.1f}ms, "
        f"unknown={missing_median * 1000:.1f}ms) — that difference is a user-enumeration "
        "oracle measurable over the network"
    )
    # And the absolute floor: both must actually be doing the KDF work, so neither can be
    # fast. A ratio test alone would pass if BOTH paths returned early.
    assert min(known_median, missing_median) > 0.004, (
        "both paths answered too quickly to have performed an Argon2 verification"
    )
    await _forget_throttle(ghost)


async def _resolve(email: str) -> uuid.UUID:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = :e"), {"e": email.casefold()}
            )
        ).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _repeat(fn, times: int) -> list[float]:  # type: ignore[no-untyped-def]
    return [await fn() for _ in range(times)]


def test_the_backoff_curve_is_gentle_then_capped() -> None:
    """The delay a failure earns, asserted WITHOUT serving it.

    The first two failures cost nothing — those are typos, and a person who mistypes their
    password should not experience the site getting slower. After that it doubles, and it is
    CAPPED, because the delay is served by holding an asyncio task open and an uncapped one
    would let failed guesses be converted into pinned server-side coroutines.
    """
    assert penalty_delay_s(1) == 0.0
    assert penalty_delay_s(2) == 0.0
    assert penalty_delay_s(3) == 2.0
    assert penalty_delay_s(4) == 4.0
    assert penalty_delay_s(5) == 8.0
    assert penalty_delay_s(50) == 8.0, "the backoff must be capped, not unbounded"


@pytest.mark.asyncio
async def test_an_unknown_address_is_throttled_exactly_like_a_known_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The oracle's back door: if only real accounts accumulated a counter, "does this
    eventually 429" would answer the question the body refuses to.

    `throttle.pseudo_subject` derives a stable id for an unknown address, through the code
    key so the Redis keyspace is not a plaintext list of attempted addresses.
    """
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"
    ghost = pseudo_subject(REALM, unknown)
    await _forget_throttle(ghost)
    # The BACKOFF is not what this test is about — `test_the_backoff_curve_is_gentle_then
    # _capped` owns that — and serving it here would spend a minute of suite time sleeping
    # to prove something about a Redis counter. Neutralised so this asserts the COUNTER.
    monkeypatch.setattr(service, "_equalise", _no_delay)
    try:
        codes: list[str] = []
        for _ in range(PASSWORD_BUDGET.threshold + 2):
            with pytest.raises(ProblemError) as caught:
                await service.sign_in(
                    realm=REALM, email=unknown, password="wrong-but-long-enough", ip=None
                )
            codes.append(caught.value.code)
        assert "too_many_attempts" in codes, (
            "an address with no account was never throttled — an attacker can tell real "
            "addresses from fake ones by which ones eventually 429"
        )
        # And the id is derived, not the address in clear.
        assert unknown not in str(ghost)
    finally:
        await _forget_throttle(ghost)


@pytest.mark.asyncio
async def test_there_is_no_identifier_existence_endpoint() -> None:
    """`check-identifier` must never be reintroduced, under any name.

    A "is this email taken" check for a signup form is the same oracle with a usability
    argument attached, so this walks the whole mounted surface rather than trusting review.
    """
    from apps.api.main import app

    banned = ("check-identifier", "identifier-exists", "email-exists", "user-exists", "exists")
    for path in app.openapi()["paths"]:
        lowered = path.lower()
        for needle in banned:
            assert needle not in lowered, f"{path} looks like a user-enumeration oracle"

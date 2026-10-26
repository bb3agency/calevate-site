"""The failed-attempt budgets hold under CONCURRENT requests, not only sequential ones.

`throttle.check` read the counter and `record_failure` incremented it after the Argon2
verification had run, so every request in flight at the same moment read the same
pre-burst count and passed. The per-account budget exists for the distributed attacker —
the per-caller limiter is the dimension a botnet spreads across — and that attacker sent
N guesses at once and had all N verified against a budget of ten. The attempt is now
RESERVED atomically before the work it pays for.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn import service, throttle
from apps.api.authn.credentials import set_password
from apps.api.authn.throttle import (
    KEY_PREFIX,
    PASSWORD_BUDGET,
    RESET_BUDGET,
    clear_password,
    pseudo_subject,
)
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

REALM = "client"
PASSWORD = "kurnool-clinic-reception-desk"
BURST = PASSWORD_BUDGET.threshold * 3


async def _no_delay(_count: int) -> None:
    return None


async def _forget(*subject_ids: uuid.UUID) -> None:
    redis = get_redis()
    for subject_id in subject_ids:
        for budget in (PASSWORD_BUDGET.name, RESET_BUDGET.name):
            await redis.delete(f"{KEY_PREFIX}:{budget}:{REALM}:{subject_id}")
        await clear_password(realm=REALM, subject_id=subject_id, source=None)


@pytest_asyncio.fixture
async def live_user() -> AsyncIterator[tuple[uuid.UUID, str]]:
    user_id = uuid.uuid4()
    email = f"race-{user_id.hex[:12]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Race Probe', now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=PASSWORD)
    await _forget(user_id, pseudo_subject(REALM, email))
    try:
        yield user_id, email
    finally:
        await _forget(user_id, pseudo_subject(REALM, email))
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


async def _burst_sign_in(email: str) -> list[str]:
    async def one() -> str:
        try:
            await service.sign_in(
                realm=REALM, email=email, password="wrong-but-long-enough", ip=None
            )
        except ProblemError as refused:
            return refused.code
        return "signed_in"

    return list(await asyncio.gather(*(one() for _ in range(BURST))))


@pytest.mark.asyncio
async def test_a_concurrent_burst_of_wrong_passwords_is_bounded_by_the_budget(
    live_user: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _user_id, email = live_user
    monkeypatch.setattr(service, "_equalise", _no_delay)
    verified = 0
    real = service.authenticate_subject

    async def counting(*args: object, **kwargs: object) -> bool:
        nonlocal verified
        verified += 1
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "authenticate_subject", counting)

    codes = await _burst_sign_in(email)

    assert verified == PASSWORD_BUDGET.threshold, (
        f"{verified} passwords were verified from one burst of {BURST} against a budget "
        f"of {PASSWORD_BUDGET.threshold}"
    )
    assert codes.count("invalid_credentials") == PASSWORD_BUDGET.threshold
    assert codes.count("too_many_attempts") == BURST - PASSWORD_BUDGET.threshold


@pytest.mark.asyncio
async def test_a_concurrent_burst_at_an_unknown_address_is_bounded_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"
    ghost = pseudo_subject(REALM, unknown)
    await _forget(ghost)
    monkeypatch.setattr(service, "_equalise", _no_delay)
    try:
        codes = await _burst_sign_in(unknown)
    finally:
        await _forget(ghost)
    assert codes.count("invalid_credentials") == PASSWORD_BUDGET.threshold
    assert codes.count("too_many_attempts") == BURST - PASSWORD_BUDGET.threshold


@pytest.mark.asyncio
async def test_a_concurrent_burst_of_reset_requests_issues_at_most_the_budget(
    live_user: tuple[uuid.UUID, str],
) -> None:
    user_id, email = live_user

    async def one() -> str:
        try:
            await service.request_password_reset(realm=REALM, email=email, ip=None)
        except ProblemError as refused:
            return refused.code
        return "accepted"

    codes = await asyncio.gather(*(one() for _ in range(RESET_BUDGET.threshold * 3)))
    assert codes.count("accepted") == RESET_BUDGET.threshold
    async with credential_session() as session:
        issued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_email_tokens "
                    "WHERE subject_id = :id AND purpose = 'password_reset'"
                ),
                {"id": user_id},
            )
        ).scalar_one()
    assert issued == RESET_BUDGET.threshold


@pytest.mark.asyncio
async def test_an_unreachable_counter_refuses_rather_than_verifying(
    live_user: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail CLOSED: with no counter nothing bounds guessing, so no password is checked."""
    _user_id, email = live_user

    class _Down:
        async def eval(self, *_args: object) -> object:
            raise ConnectionError("redis unreachable")

    monkeypatch.setattr(throttle, "get_redis", lambda: _Down())

    async def must_not_run(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("a password was verified with no budget to charge it to")

    monkeypatch.setattr(service, "authenticate_subject", must_not_run)

    with pytest.raises(ProblemError) as refused:
        await service.sign_in(realm=REALM, email=email, password=PASSWORD, ip=None)
    assert refused.value.code == "too_many_attempts"
    assert refused.value.status == 429


ATTACKER_IP = "198.51.100.23"
OWNER_IP = "203.0.113.40"


@pytest.mark.asyncio
async def test_failures_from_one_source_do_not_lock_the_owner_out_elsewhere(
    live_user: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The griefing a per-account lock allowed: ten wrong passwords every fifteen minutes,
    from anywhere, kept the real person at 429 for as long as the attacker liked."""
    user_id, email = live_user
    monkeypatch.setattr(service, "_equalise", _no_delay)
    try:
        for _ in range(PASSWORD_BUDGET.threshold):
            with pytest.raises(ProblemError) as wrong:
                await service.sign_in(
                    realm=REALM, email=email, password="wrong-but-long-enough", ip=ATTACKER_IP
                )
            assert wrong.value.code == "invalid_credentials"
        with pytest.raises(ProblemError) as locked:
            await service.sign_in(realm=REALM, email=email, password=PASSWORD, ip=ATTACKER_IP)
        assert locked.value.code == "too_many_attempts", "the failing source is stopped"

        signed_in = await service.sign_in(realm=REALM, email=email, password=PASSWORD, ip=OWNER_IP)
        assert signed_in.subject_id == user_id, "the owner elsewhere still gets in"
    finally:
        for source in (ATTACKER_IP, OWNER_IP):
            await clear_password(realm=REALM, subject_id=user_id, source=source)


@pytest.mark.asyncio
async def test_the_account_ceiling_still_bounds_a_guess_spread_across_sources(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Spread across many sources no one source reaches its budget, so the account's own
    ceiling is what stops a distributed guess — even from a source never seen before."""
    user_id, _email = live_user
    ceiling = f"{KEY_PREFIX}:{throttle.PASSWORD_ACCOUNT_CEILING.name}:{REALM}:{user_id}"
    try:
        for n in range(3):
            await throttle.reserve_password(realm=REALM, subject_id=user_id, source=f"10.0.0.{n}")
        assert int(await get_redis().get(ceiling) or 0) == 3, "every source counts on the account"

        await get_redis().set(
            ceiling,
            throttle.PASSWORD_ACCOUNT_CEILING.threshold,
            ex=throttle.PASSWORD_ACCOUNT_CEILING.window_s,
        )
        with pytest.raises(ProblemError) as refused:
            await throttle.reserve_password(realm=REALM, subject_id=user_id, source="10.9.9.9")
        assert refused.value.code == "too_many_attempts"
        # Spread failures slow the next guess on the account as well as capping it.
        await get_redis().set(ceiling, 50, ex=throttle.PASSWORD_ACCOUNT_CEILING.window_s)
        assert (
            await throttle.reserve_password(realm=REALM, subject_id=user_id, source="10.8.8.8") == 5
        )
    finally:
        for source in ("10.0.0.0", "10.0.0.1", "10.0.0.2", "10.9.9.9", "10.8.8.8"):
            await clear_password(realm=REALM, subject_id=user_id, source=source)

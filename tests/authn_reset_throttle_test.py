"""The reset form's own enumeration oracle, and the mail bomb behind it (D-198).

`tests/authn_enumeration_test.py` measures the SIGN-IN path's uniformity — status, body and
wall clock — and it measures the reset path's body ("both return `None`"). Nobody measured
the reset path's LIMITER, and that is where the difference was:

    eight requests for a real address   -> eight 202s and eight queued emails
    six requests for an unknown address -> 429 too_many_attempts

`throttle.pseudo_subject`'s docstring names this exact back door on the sign-in path — "an
attacker could tell real addresses from fake ones by whether a burst of attempts eventually
produced a 429" — and the reset form is the worse place to have it, because taking an
arbitrary stranger's address is its entire input: there is no password to guess first and
no account to hold.

The same asymmetry meant nothing bounded reset mail to a KNOWN address at all. The
caller-keyed request limiter is the dimension a botnet spreads across; the per-account
budget is the one it cannot.

THE FIX IS SYMMETRY, NOT A SECOND RULE: the budget key is chosen before the branch and both
paths spend it identically. It is `RESET_BUDGET` and deliberately not `OTP_BUDGET` — that
constant argues why, and `test_reset_requests_do_not_spend_the_second_factor_budget` below
is what would go red if somebody merged them, because merging them would let five
unauthenticated requests lock an operator out of finishing a sign-in.

SHARED DATABASE DISCIPLINE (`tests/shared_state_assertion_guard_test.py`): every row hangs
off ids this module mints, the fixture deletes exactly those, and nothing counts globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn import service
from apps.api.authn.credentials import set_password
from apps.api.authn.throttle import KEY_PREFIX, OTP_BUDGET, RESET_BUDGET, pseudo_subject
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

REALM = "client"
PASSWORD = "vijayawada-clinic-front-desk"


async def _forget(*subject_ids: uuid.UUID) -> None:
    """Drop this module's own counters. Scoped to the ids it minted."""
    redis = get_redis()
    for subject_id in subject_ids:
        for budget in (RESET_BUDGET.name, OTP_BUDGET.name, "password"):
            await redis.delete(f"{KEY_PREFIX}:{budget}:{REALM}:{subject_id}")


async def _count(budget_name: str, subject_id: uuid.UUID) -> int:
    raw = await get_redis().get(f"{KEY_PREFIX}:{budget_name}:{REALM}:{subject_id}")
    return 0 if raw is None else int(raw)


@pytest_asyncio.fixture
async def live_user() -> AsyncIterator[tuple[uuid.UUID, str]]:
    """One real, active `users` row with a real password."""
    user_id = uuid.uuid4()
    email = f"reset-{user_id.hex[:12]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Reset Probe', now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=PASSWORD)
    try:
        yield user_id, email
    finally:
        await _forget(user_id, pseudo_subject(REALM, email))
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_email_tokens WHERE subject_id = :id"), {"id": user_id}
            )
            await session.execute(
                text("DELETE FROM auth_credentials WHERE subject_id = :id"), {"id": user_id}
            )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = :e"), {"e": email}
            )
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def _drive(email: str, times: int) -> list[str]:
    """Ask for a reset `times` over, recording what each attempt answered."""
    answers: list[str] = []
    for _ in range(times):
        try:
            await service.request_password_reset(realm=REALM, email=email, ip=None)
            answers.append("accepted")
        except ProblemError as refusal:
            answers.append(refusal.code)
    return answers


# ═══════════════ the oracle ═══════════════


@pytest.mark.asyncio
async def test_a_known_address_is_throttled_exactly_like_an_unknown_one(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """THE REGRESSION. The two sequences must be character-identical.

    Before the fix the known address answered `accepted` for every attempt while the
    unknown one turned to `too_many_attempts` at the sixth — a difference an attacker reads
    straight off the status code, without timing anything and without holding an account.
    """
    _, email = live_user
    unknown = f"nobody-{uuid.uuid4().hex[:12]}@calevate-test.example"
    ghost = pseudo_subject(REALM, unknown)
    attempts = RESET_BUDGET.threshold + 3
    try:
        known = await _drive(email, attempts)
        missing = await _drive(unknown, attempts)
        assert known == missing, (
            "the reset form answers a real address and a fake one differently once the "
            f"budget is spent — known={known}, unknown={missing}. That is a user-"
            "enumeration oracle readable from the status code alone."
        )
        assert "too_many_attempts" in known, (
            "neither path was ever throttled, so this test is measuring nothing — the "
            "budget must actually bite"
        )
    finally:
        await _forget(ghost)


@pytest.mark.asyncio
async def test_reset_mail_to_one_address_is_bounded(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """The other half of the same asymmetry: unbounded reset mail to any known address.

    A reset token is only minted on the path that also queues the email, so counting the
    tokens counts the emails. It must stop at the budget rather than at the attacker's
    patience.
    """
    user_id, email = live_user
    await _drive(email, RESET_BUDGET.threshold + 5)
    async with credential_session() as session:
        minted = (
            await session.execute(
                text("SELECT count(*) FROM auth_email_tokens WHERE subject_id = :id"),
                {"id": user_id},
            )
        ).scalar()
    assert minted is not None and int(minted) <= RESET_BUDGET.threshold, (
        f"{minted} reset emails were queued for one address — nothing bounds the mail "
        "an attacker can aim at a mailbox"
    )


# ═══════════════ and the budget it must NOT spend ═══════════════


@pytest.mark.asyncio
async def test_reset_requests_do_not_spend_the_second_factor_budget(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Symmetry must not be bought with a denial of service against the admin realm.

    `OTP_BUDGET` is the five guesses a person has against their own emailed second factor.
    If an unauthenticated reset request spent it, five requests aimed at an operator's
    address would stop that operator completing a sign-in for ten minutes — a remote lockout
    of this product's only second factor, introduced by the fix for an oracle.
    """
    user_id, email = live_user
    await _drive(email, RESET_BUDGET.threshold)
    assert await _count(OTP_BUDGET.name, user_id) == 0, (
        "reset requests are charged to the second-factor budget, so anyone can lock an "
        "operator out of answering their own sign-in code"
    )
    assert await _count(RESET_BUDGET.name, user_id) == RESET_BUDGET.threshold


@pytest.mark.asyncio
async def test_redeeming_a_link_forgives_the_requests_it_took_to_find_it(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Completing a reset proves the mailbox, so the request counter is cleared.

    Without this, somebody who needed three attempts to find the right email is refused
    their next legitimate reset for the rest of the window — the rolling-total penalty
    `throttle.clear` exists to prevent.
    """
    user_id, email = live_user
    await _drive(email, 3)
    assert await _count(RESET_BUDGET.name, user_id) == 3

    # The newest link is the only live one (`tokens.invalidate_outstanding`), so redeem the
    # token this last request minted. It is the one row still unused.
    async with credential_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT token_hash FROM auth_email_tokens WHERE subject_id = :id "
                    "AND used_at IS NULL"
                ),
                {"id": user_id},
            )
        ).all()
    assert len(rows) == 1, "only the newest reset link should be live"

    # Redeeming needs the PLAINTEXT, which is never stored — so drive the flow end to end
    # by minting one more and reading it back from the outbox payload the same transaction
    # queued. That payload is the only place the secret exists outside the browser.
    await _forget(user_id)
    await service.request_password_reset(realm=REALM, email=email, ip=None)
    async with untenanted_session() as session:
        secret = (
            await session.execute(
                text(
                    "SELECT payload->>'secret' FROM outbox_messages "
                    "WHERE payload->>'to' = :e AND payload->>'kind' = 'password_reset' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"e": email},
            )
        ).scalar()
    assert isinstance(secret, str) and secret

    await service.confirm_password_reset(
        realm=REALM, token=secret, password="a-brand-new-passphrase", ip=None
    )
    assert await _count(RESET_BUDGET.name, user_id) == 0, (
        "a completed reset left the request counter spent, so the person who just proved "
        "their mailbox is refused their next reset"
    )

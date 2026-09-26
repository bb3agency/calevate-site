"""A reset link survives a password the policy refuses.

`ResetConfirmIn` bounds the password at `hashing.MIN_PASSWORD_CHARS` (12), the absolute
floor, while `authn/policy.py` holds the client realm to 15 and refuses blocklisted
passwords whatever their length. So a request can pass the schema and still be refused by
`set_password`. The refusal tells the person to choose a longer passphrase; the link they
are holding must still work when they do. It did not: the token was burned in its own
committed transaction before the policy ran, so the retry answered
`invalid_reset_token` and sent them back to their mailbox.

SHARED DATABASE DISCIPLINE: every row hangs off an id this module mints and the fixture
deletes exactly those.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn import service, tokens
from apps.api.authn.credentials import set_password
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

REALM = "client"
OLD_PASSWORD = "vijayawada-clinic-front-desk"
NEW_PASSWORD = "guntur-dental-evening-shift"
#: 12 characters: passes `ResetConfirmIn`, below the client realm's floor of 15.
TOO_SHORT = "tenali-rice1"
#: Long enough, but the service's own name wearing decoration — refused by the blocklist.
BLOCKLISTED = "calevate2026!!!!!"


@pytest_asyncio.fixture
async def live_user() -> AsyncIterator[tuple[uuid.UUID, str]]:
    user_id = uuid.uuid4()
    email = f"reset-policy-{user_id.hex[:12]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Reset Policy Probe', now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=OLD_PASSWORD)
    try:
        yield user_id, email
    finally:
        redis = get_redis()
        async for key in redis.scan_iter(f"{KEY_PREFIX}:*:{REALM}:{user_id}"):
            await redis.delete(key)
        async with credential_session() as session:
            for table in ("auth_email_tokens", "auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :id"),
                    {"id": user_id},
                )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def _reset_link(user_id: uuid.UUID) -> str:
    async with credential_session() as session:
        issued = await tokens.issue_token(
            session, purpose="password_reset", realm=REALM, subject_id=user_id
        )
    return issued.token


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refused", "code"),
    [(TOO_SHORT, "password_length"), (BLOCKLISTED, "password_unacceptable")],
)
async def test_a_policy_refusal_does_not_spend_the_link(
    live_user: tuple[uuid.UUID, str], refused: str, code: str
) -> None:
    user_id, email = live_user
    link = await _reset_link(user_id)

    with pytest.raises(ProblemError) as caught:
        await service.confirm_password_reset(realm=REALM, token=link, password=refused, ip=None)
    assert caught.value.code == code

    # The same link, with a password the policy accepts, must now succeed.
    await service.confirm_password_reset(realm=REALM, token=link, password=NEW_PASSWORD, ip=None)
    outcome = await service.sign_in(realm=REALM, email=email, password=NEW_PASSWORD, ip=None)
    assert outcome.subject_id == user_id

    # And it is spent now.
    with pytest.raises(ProblemError) as replay:
        await service.confirm_password_reset(
            realm=REALM, token=link, password="a-third-passphrase-entirely", ip=None
        )
    assert replay.value.code == "invalid_reset_token"


@pytest.mark.asyncio
async def test_a_policy_refusal_leaves_the_old_password_and_sessions_alone(
    live_user: tuple[uuid.UUID, str],
) -> None:
    """Nothing of the reset's effects may land when the password is refused."""
    user_id, email = live_user
    signed_in = await service.sign_in(realm=REALM, email=email, password=OLD_PASSWORD, ip=None)
    link = await _reset_link(user_id)

    with pytest.raises(ProblemError):
        await service.confirm_password_reset(realm=REALM, token=link, password=TOO_SHORT, ip=None)

    async with credential_session() as session:
        revoked = (
            await session.execute(
                text("SELECT revoked_at FROM auth_sessions WHERE id = :id"),
                {"id": signed_in.session.session_id},
            )
        ).scalar_one()
    assert revoked is None
    again = await service.sign_in(realm=REALM, email=email, password=OLD_PASSWORD, ip=None)
    assert again.subject_id == user_id

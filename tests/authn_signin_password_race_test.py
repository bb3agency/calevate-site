"""A sign-in that overlaps a password change does not keep a session the change ended.

`service.sign_in` proves the password in one transaction and issues the session in a
later one. A reset or change committing in between revokes every session that exists at
that moment, and the new one did not exist yet, so before the re-check it survived the
change for its whole lifetime, opened with the old password.

Both orders are driven rather than hoped for:

* the change commits first: the sign-in is refused and leaves no live session;
* the change arrives while the session is being issued: it waits on the credential row
  (`credentials.credential_still_holds` holds it `FOR SHARE`), then revokes the new session
  with the others. The waiting is measured, so a pass cannot come from the two never
  having met.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, and the fixture
deletes exactly those.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from apps.api.authn import credentials, service
from apps.api.authn.credentials import set_password
from apps.api.authn.sessions import revoke_subject_sessions
from apps.api.authn.throttle import KEY_PREFIX, clear_password
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

REALM = "client"
OLD_PASSWORD = "nellore-front-desk-morning"
NEW_PASSWORD = "nellore-front-desk-evening"
HOLD_S = 1.0
STAGGER_S = 0.15


@pytest_asyncio.fixture
async def account() -> AsyncIterator[tuple[uuid.UUID, str]]:
    user_id = uuid.uuid4()
    email = f"race-signin-{user_id.hex[:12]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Race Probe', now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=OLD_PASSWORD)
    try:
        yield user_id, email
    finally:
        await get_redis().delete(f"{KEY_PREFIX}:password:{REALM}:{user_id}")
        await clear_password(realm=REALM, subject_id=user_id, source=None)
        async with credential_session() as session:
            for table in ("auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": user_id}
                )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM users WHERE id = :s"), {"s": user_id})


async def _change_password(user_id: uuid.UUID) -> None:
    """What `confirm_password_reset` and `change_password` do to the store and the sessions."""
    async with credential_session() as session:
        await set_password(session, realm=REALM, subject_id=user_id, password=NEW_PASSWORD)
        await revoke_subject_sessions(session, realm=REALM, subject_id=user_id)


async def _live_sessions(user_id: uuid.UUID) -> int:
    async with credential_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM auth_sessions "
                        "WHERE subject_id = :s AND revoked_at IS NULL"
                    ),
                    {"s": user_id},
                )
            ).scalar_one()
        )


async def test_a_change_committed_after_the_check_refuses_the_sign_in(
    account: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, email = account
    real_clear = service.clear_password

    async def change_meanwhile(**kwargs: Any) -> None:
        await real_clear(**kwargs)
        await _change_password(user_id)

    monkeypatch.setattr(service, "clear_password", change_meanwhile)
    with pytest.raises(ProblemError):
        await service.sign_in(realm=REALM, email=email, password=OLD_PASSWORD, ip=None)

    assert await _live_sessions(user_id) == 0


async def test_without_an_overlap_the_same_sign_in_succeeds(
    account: tuple[uuid.UUID, str],
) -> None:
    """The control: the harness above refuses because of the change, not because of it."""
    user_id, email = account
    outcome = await service.sign_in(realm=REALM, email=email, password=OLD_PASSWORD, ip=None)
    assert outcome.status == "authenticated"
    assert await _live_sessions(user_id) == 1


async def test_a_change_arriving_during_the_issue_waits_and_then_revokes_it(
    account: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, email = account
    holding = asyncio.Event()
    real_issue = service.issue_session

    async def issue_and_hold(*args: Any, **kwargs: Any) -> Any:
        issued = await real_issue(*args, **kwargs)
        holding.set()
        await asyncio.sleep(HOLD_S)
        return issued

    async def change_when_held() -> float:
        await holding.wait()
        await asyncio.sleep(STAGGER_S)
        started = time.monotonic()
        await _change_password(user_id)
        return time.monotonic() - started

    monkeypatch.setattr(service, "issue_session", issue_and_hold)
    outcome, waited = await asyncio.gather(
        service.sign_in(realm=REALM, email=email, password=OLD_PASSWORD, ip=None),
        change_when_held(),
    )

    assert outcome.status == "authenticated"
    assert waited >= HOLD_S - STAGGER_S - 0.1, "the change never waited on the sign-in"
    assert await _live_sessions(user_id) == 0


async def test_an_upgrade_beaten_by_a_change_answers_the_hash_it_proved(
    account: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-hash that loses to a concurrent `set_password` keeps nothing of its own: the
    answer is the hash the plaintext matched, which no longer holds."""
    user_id, _email = account
    async with credential_session() as session:
        stored = (
            await session.execute(
                text("SELECT password_hash FROM auth_credentials WHERE subject_id = :s"),
                {"s": user_id},
            )
        ).scalar_one()

    real_verify = credentials.verify_password
    real_hash = credentials.hash_password

    async def stale_verdict(password: str, stored_hash: str | None) -> Any:
        verdict = await real_verify(password, stored_hash)
        return type(verdict)(ok=verdict.ok, needs_rehash=True)

    async def hash_after_a_change(password: str) -> str:
        # `set_password` hashes through the same module name, so the change runs on the
        # real one.
        monkeypatch.setattr(credentials, "hash_password", real_hash)
        await _change_password(user_id)
        return await real_hash(password)

    monkeypatch.setattr(credentials, "verify_password", stale_verdict)
    monkeypatch.setattr(credentials, "hash_password", hash_after_a_change)
    async with credential_session() as session:
        proved = await credentials.proved_password_hash(
            session, realm=REALM, subject_id=user_id, password=OLD_PASSWORD
        )
    assert proved == stored

    async with credential_session() as session:
        assert not await credentials.credential_still_holds(
            session, realm=REALM, subject_id=user_id, password_hash=str(proved)
        )

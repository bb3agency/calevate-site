"""Two credential mints for one person, overlapping (D-320).

`authn` states its exclusivity rules in prose and implemented every one of them as a
RETIRE followed by an ISSUE — two statements, one transaction, nothing serializing them:

* `otp.issue_challenge` — "Issuing a new code invalidates the previous one. Without that
  rule, 'resend the code' becomes an attempt-budget reset";
* `service.request_password_reset` — "Only the newest link works. Without this, 'click
  forgot password three times' leaves three live keys in a mailbox for an hour".

Under READ COMMITTED two overlapping calls each retire what the other has not yet
committed, and each insert. This file drives the overlap rather than describing it, and
the last test in each pair is the NEGATIVE CONTROL: it removes the lock and asserts the
same harness breaks, because a concurrent test that never actually raced is the commonest
way to be fooled (`tests/postcall_concurrency_test.py` makes the same argument).

WHAT "BREAKS" MEANS DIFFERS BY TABLE, and the asymmetry is deliberate rather than untidy:
`auth_otp_challenges` also carries `ux_auth_otp_challenges_live` (migration
`f1c8b7d5a903`), so without the lock the loser is refused BY THE DATABASE — a 500 where a
person pressed "resend" twice, which is why the lock and not the index is the fix.
`auth_email_tokens` has no such index (an `email_verify` resend may legitimately leave
two), so without the lock it simply ends with two live reset links.

THE OVERLAP IS FORCED, NOT HOPED FOR. The first writer's INSERT is held behind an
`asyncio.Event` while its transaction — and therefore its lock — stays open, and the
second writer starts only once the first has taken the lock. The fixed runs additionally
assert the second writer WAITED, so a pass cannot come from the two never having met.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture deletes
exactly those, and nothing counts globally.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from apps.api.authn import otp, service, tokens
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

#: How long the first writer holds its transaction open after taking the lock. Generous
#: relative to the second writer's head start below, so the interleave does not depend on
#: scheduler luck; short enough that the file costs a second.
HOLD_S = 1.0

#: How long the second writer waits before starting. Only has to be smaller than `HOLD_S`.
STAGGER_S = 0.15


@pytest_asyncio.fixture
async def operator() -> AsyncIterator[tuple[uuid.UUID, str]]:
    """One admin-realm operator with no credentials of any kind yet."""
    admin_id = uuid.uuid4()
    email = f"race-{admin_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, email, name, role, created_at, updated_at) "
                "VALUES (:id, :email, 'Race Probe', 'operator', now(), now())"
            ),
            {"id": admin_id, "email": email},
        )
    try:
        yield admin_id, email
    finally:
        async with credential_session() as session:
            for table in ("auth_otp_challenges", "auth_email_tokens", "auth_sessions"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": admin_id}
                )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = :to"), {"to": email}
            )
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})


async def _live_challenges(admin_id: uuid.UUID) -> int:
    async with credential_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM auth_otp_challenges "
                        "WHERE subject_id = :s AND consumed_at IS NULL"
                    ),
                    {"s": admin_id},
                )
            ).scalar_one()
        )


async def _live_reset_tokens(admin_id: uuid.UUID) -> int:
    async with credential_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM auth_email_tokens WHERE subject_id = :s "
                        "AND purpose = 'password_reset' AND used_at IS NULL"
                    ),
                    {"s": admin_id},
                )
            ).scalar_one()
        )


# ═══════════════════════ the emailed second factor ═══════════════════════


async def _issue_holding(admin_id: uuid.UUID, took_lock: asyncio.Event) -> None:
    """Mint a challenge and keep the transaction — and its lock — open for `HOLD_S`."""
    async with credential_session() as session:
        await otp.issue_challenge(
            session, purpose=service.LOGIN_CHALLENGE, realm="admin", subject_id=admin_id
        )
        took_lock.set()
        await asyncio.sleep(HOLD_S)


async def _issue_second(admin_id: uuid.UUID, took_lock: asyncio.Event) -> float:
    """The overlapping resend. Returns how long it took, which is how we know it waited."""
    await took_lock.wait()
    await asyncio.sleep(STAGGER_S)
    started = time.monotonic()
    async with credential_session() as session:
        await otp.issue_challenge(
            session, purpose=service.LOGIN_CHALLENGE, realm="admin", subject_id=admin_id
        )
    return time.monotonic() - started


@pytest.mark.asyncio
async def test_two_overlapping_resends_leave_one_live_challenge(
    operator: tuple[uuid.UUID, str],
) -> None:
    admin_id, _email = operator
    took_lock = asyncio.Event()

    _held, elapsed = await asyncio.gather(
        _issue_holding(admin_id, took_lock), _issue_second(admin_id, took_lock)
    )

    assert await _live_challenges(admin_id) == 1, (
        "two overlapping issues left more than one live challenge — the OTP module's "
        "'ONE LIVE CHALLENGE PER (SUBJECT, PURPOSE)' rule, and the guess budget that "
        "rests on it, are only true if the retire and the mint are one critical section"
    )
    # The lock is what produced that 1, not a scheduler that happened to serialize us:
    # the second writer sat behind the first for the rest of its hold.
    assert elapsed > (HOLD_S - STAGGER_S) / 2, (
        f"the second resend returned in {elapsed:.3f}s, so it never waited for the first "
        "— this run did not reproduce the overlap and proves nothing"
    )


@pytest.mark.asyncio
async def test_without_the_lock_the_same_harness_breaks(
    operator: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEGATIVE CONTROL. Remove the lock; the overlap that the test above survives now
    reaches the database, which refuses it — `ux_auth_otp_challenges_live` catching what
    the lock is there to prevent.

    Before BOTH existed this pair left two live challenges and both codes authenticated
    (measured; see `alembic/versions/f1c8b7d5a903_*`). The index alone turns that silent
    corruption into a loud refusal, which is better and is still not the answer: a person
    who presses "resend" twice would get a 500.
    """

    async def _no_lock(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(otp, "lock_subject_credentials", _no_lock)
    admin_id, _email = operator
    took_lock = asyncio.Event()

    with pytest.raises(IntegrityError):
        await asyncio.gather(
            _issue_holding(admin_id, took_lock), _issue_second(admin_id, took_lock)
        )


# ═══════════════════════ the password-reset link ═══════════════════════


@pytest.mark.asyncio
async def test_two_overlapping_reset_requests_leave_one_live_link(
    operator: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real service function, twice, overlapping.

    `request_password_reset` opens its own transaction, so the hold is applied where the
    test can reach it: `issue_token` is delayed for the FIRST caller only, after
    `invalidate_outstanding` has run and taken the lock and before anything is inserted.
    That is precisely the window the two statements leave open.
    """
    admin_id, email = operator
    real_issue = tokens.issue_token
    took_lock = asyncio.Event()
    first = True

    async def _slow_issue(session: Any, **kwargs: Any) -> Any:
        nonlocal first
        if first:
            first = False
            took_lock.set()
            await asyncio.sleep(HOLD_S)
        return await real_issue(session, **kwargs)

    monkeypatch.setattr(service.tokens, "issue_token", _slow_issue)

    async def _second() -> float:
        await took_lock.wait()
        await asyncio.sleep(STAGGER_S)
        started = time.monotonic()
        await service.request_password_reset(realm="admin", email=email, ip=None)
        return time.monotonic() - started

    _first, elapsed = await asyncio.gather(
        service.request_password_reset(realm="admin", email=email, ip=None), _second()
    )

    assert await _live_reset_tokens(admin_id) == 1, (
        "two overlapping reset requests left more than one live link — 'only the newest "
        "link works' is the sentence that bounds how long a stolen mailbox stays useful"
    )
    assert elapsed > (HOLD_S - STAGGER_S) / 2, (
        f"the second reset request returned in {elapsed:.3f}s, so it never waited for the "
        "first — this run did not reproduce the overlap and proves nothing"
    )


@pytest.mark.asyncio
async def test_without_the_lock_two_reset_links_stay_live(
    operator: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEGATIVE CONTROL, and the shape the OTP table's index hides.

    `auth_email_tokens` carries no partial unique index — an `email_verify` resend may
    legitimately leave two live tokens — so with the lock removed there is nothing to
    refuse the second insert and the mailbox simply ends up with two working keys. This is
    the raw defect, reproduced.
    """

    async def _no_lock(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(tokens, "lock_subject_credentials", _no_lock)
    admin_id, email = operator
    real_issue = tokens.issue_token
    took_lock = asyncio.Event()
    first = True

    async def _slow_issue(session: Any, **kwargs: Any) -> Any:
        nonlocal first
        if first:
            first = False
            took_lock.set()
            await asyncio.sleep(HOLD_S)
        return await real_issue(session, **kwargs)

    monkeypatch.setattr(service.tokens, "issue_token", _slow_issue)

    async def _second() -> None:
        await took_lock.wait()
        await asyncio.sleep(STAGGER_S)
        await service.request_password_reset(realm="admin", email=email, ip=None)

    await asyncio.gather(
        service.request_password_reset(realm="admin", email=email, ip=None), _second()
    )

    assert await _live_reset_tokens(admin_id) == 2, (
        "the unguarded harness was expected to leave two live reset links; it did not, so "
        "the test above is not proving what it claims"
    )

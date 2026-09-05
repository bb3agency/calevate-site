"""Does the browser KEEP the session cookie, and can keeping it outlive the row? (D-539.)

The reported defect: a client whose session row is good for fourteen days was signed out
by closing the browser, and on a phone by backgrounding the tab, because the cookie
carried no `Max-Age` and died with the browser session. The fix is a `Max-Age` DERIVED
from the row's own `absolute_expires_at` — never a number of the cookie layer's own — so
the two cannot disagree in the dangerous direction.

WHAT THIS FILE IS FOR, and it is the security half rather than the convenience half:

  * a persisted cookie is still a token, and the ROW is still the only clock — revoked,
    absolute-expired and idle-expired rows are refused with the cookie in perfect health;
  * the cookie can never be asked to live past the row's absolute bound, including across
    a rotation (which carries the bound forward) and across the idle slide (which does
    not move the bound at all);
  * the two realms are decided SEPARATELY and the admin realm is deliberately NOT
    persisted, so a change to one cannot silently move the other.

`apps/api/authn/cookies.py`'s module docstring carries the argument; this file is what
fails if somebody takes it back.

SHARED DATABASE DISCIPLINE (`tests/shared_state_assertion_guard_test.py`): the cookie half
touches nothing. The row half hangs every row off a `subject_id` this module minted with
`uuid4` and deletes exactly those, the same discipline `tests/authn_session_test.py` keeps;
no assertion counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn.cookies import (
    COOKIE_PERSISTENCE,
    cookie_name,
    session_cookie_max_age,
    set_session_cookie,
)
from apps.api.authn.models import AUTHN_REALMS
from apps.api.authn.sessions import (
    REALM_TIMEOUTS,
    issue_session,
    revoke_session,
    rotate_session,
    verify_session,
)
from apps.api.db.session import credential_session
from fastapi import Response
from sqlalchemy import text
from starlette.requests import Request

REALMS = sorted(AUTHN_REALMS)


@pytest_asyncio.fixture
async def subjects() -> AsyncIterator[list[uuid.UUID]]:
    """Subject ids this file owns, and their cleanup. `tests/authn_session_test.py`'s
    fixture, kept identical deliberately: two files inventing two cleanup shapes for one
    table is how a suite comes to leave rows behind."""
    owned: list[uuid.UUID] = []
    yield owned
    if owned:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = ANY(:ids)"), {"ids": owned}
            )


def _subject(owned: list[uuid.UUID]) -> uuid.UUID:
    subject_id = uuid.uuid4()
    owned.append(subject_id)
    return subject_id


def _request(scheme: str = "https") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "path": "/v1/auth/client/session",
            "headers": [],
            "query_string": b"",
            "server": ("api.calevate.tech", 443),
        }
    )


def _set_cookie_header(realm: str, *, absolute_expires_at: datetime, now: datetime) -> str:
    response = Response()
    set_session_cookie(
        response,
        realm=realm,
        token="a-token",
        request=_request(),
        absolute_expires_at=absolute_expires_at,
        now=now,
    )
    return response.headers["set-cookie"]


# ═══════════════════ the split, and that it is a decision per realm ═══════════════════


def test_every_realm_has_a_recorded_persistence_decision() -> None:
    """A third realm cannot arrive and inherit whichever answer happens to be the default.

    The map is the posture, in the same sense `REALM_TIMEOUTS` is: equality against
    `AUTHN_REALMS` is what makes adding a realm a decision rather than an omission.
    """
    assert set(COOKIE_PERSISTENCE) == set(AUTHN_REALMS)


def test_the_client_realm_persists_and_the_admin_realm_does_not() -> None:
    """THE decision this file exists for, asserted as a value rather than read off a header.

    They differ because their risk differs (`cookies.py`, `Max-Age`): a business owner on a
    phone with a fourteen-day bound is the reported defect; an operator with a thirty-minute
    idle window and an eight-hour bound is a shift, and a persisted operator credential on
    whatever laptop is to hand buys at most the rest of that shift.
    """
    assert COOKIE_PERSISTENCE["client"] is True
    assert COOKIE_PERSISTENCE["admin"] is False


def test_the_admin_cookie_carries_no_max_age_at_all() -> None:
    """A browser-session cookie, exactly as before D-539. Asserted on the HEADER, because
    that is what a browser reads, and because `max_age=None` and `max_age=0` differ by the
    whole meaning of the attribute."""
    now = datetime.now(UTC)
    header = _set_cookie_header(
        "admin", absolute_expires_at=now + REALM_TIMEOUTS["admin"].absolute, now=now
    )
    assert "max-age" not in header.lower()
    assert "expires" not in header.lower()


def test_the_client_cookie_carries_the_rows_remaining_lifetime() -> None:
    now = datetime.now(UTC)
    absolute = now + REALM_TIMEOUTS["client"].absolute
    header = _set_cookie_header("client", absolute_expires_at=absolute, now=now)
    assert f"Max-Age={int(REALM_TIMEOUTS['client'].absolute.total_seconds())}" in header
    # Still every attribute the prefix and the CSRF argument depend on. A persistence
    # change that quietly dropped one of these would be the expensive kind.
    assert cookie_name("client", secure=True) in header
    assert "HttpOnly" in header
    assert "secure" in header.lower()
    assert "samesite=strict" in header.lower()


# ═══════════════════ the bound: the cookie cannot outlive the row ═══════════════════


@pytest.mark.parametrize("realm", REALMS)
def test_the_cookie_is_never_asked_to_outlive_the_absolute_bound(realm: str) -> None:
    """The property the whole design rests on, over the realm's own bound and past it.

    `None` (the admin realm) passes trivially and is included on purpose: the assertion is
    "no realm asks for more than the row has left", and a realm that asks for nothing meets
    it.
    """
    now = datetime.now(UTC)
    for offset in (timedelta(seconds=1), timedelta(hours=6), REALM_TIMEOUTS[realm].absolute):
        max_age = session_cookie_max_age(realm, absolute_expires_at=now + offset, now=now)
        if max_age is None:
            continue
        assert max_age <= int(offset.total_seconds())


def test_a_dead_row_asks_the_browser_to_drop_the_cookie_rather_than_hold_it() -> None:
    """Past the absolute bound, the answer is zero and not a clamped-up second.

    Handing out a credential we already know the server will refuse would be a sign-in
    that fails on the next request for a reason nobody can see. Zero is the truth.
    """
    now = datetime.now(UTC)
    assert (
        session_cookie_max_age("client", absolute_expires_at=now - timedelta(seconds=1), now=now)
        == 0
    )


def test_the_lifetime_does_not_slide_with_the_idle_window() -> None:
    """THE deliberate half. The row's idle window slides on every request; its absolute
    bound does not, and the cookie is pinned to the bound.

    So a session re-issued six hours in gets a SHORTER `Max-Age`, converging on one fixed
    instant. A lifetime that slid instead is the second, client-controlled authority the
    pre-D-539 comment was right to refuse — it could outrun the only clock able to stop it.
    """
    issued_at = datetime.now(UTC)
    absolute = issued_at + REALM_TIMEOUTS["client"].absolute
    first = session_cookie_max_age("client", absolute_expires_at=absolute, now=issued_at)
    later = session_cookie_max_age(
        "client", absolute_expires_at=absolute, now=issued_at + timedelta(hours=6)
    )
    assert first is not None and later is not None
    assert later == first - int(timedelta(hours=6).total_seconds())


def test_an_unknown_realm_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError):
        session_cookie_max_age("ops", absolute_expires_at=datetime.now(UTC))


# ═════════════ and the row is still the only clock, per realm, over the wire ═════════════


@pytest.mark.parametrize("realm", REALMS)
@pytest.mark.asyncio
async def test_a_persisted_cookie_is_refused_once_the_row_is_revoked(
    realm: str, subjects: list[uuid.UUID]
) -> None:
    """Sign-out revokes the ROW. The browser keeping the cookie for another fortnight is
    not a way back in — which is the whole reason a `Max-Age` is affordable."""
    subject_id = _subject(subjects)
    async with credential_session() as session:
        issued = await issue_session(
            session, realm=realm, subject_id=subject_id, mfa_verified_at=datetime.now(UTC)
        )
    assert (await verify_session(token=issued.token, realm=realm)).live

    async with credential_session() as session:
        assert await revoke_session(session, session_id=issued.session_id, reason="signed_out")

    outcome = await verify_session(token=issued.token, realm=realm)
    assert not outcome.live
    assert outcome.refusal == "revoked"


@pytest.mark.parametrize("realm", REALMS)
@pytest.mark.asyncio
async def test_a_persisted_cookie_is_refused_past_the_absolute_bound(
    realm: str, subjects: list[uuid.UUID]
) -> None:
    """The cookie's `Max-Age` reaches the bound; a request one second past it is refused.

    Driven with an injected clock rather than by moving the row, so what is asserted is the
    same predicate a real request runs.
    """
    subject_id = _subject(subjects)
    async with credential_session() as session:
        issued = await issue_session(
            session, realm=realm, subject_id=subject_id, mfa_verified_at=datetime.now(UTC)
        )
    past = issued.absolute_expires_at + timedelta(seconds=1)
    outcome = await verify_session(token=issued.token, realm=realm, now=past)
    assert not outcome.live
    assert outcome.refusal == "absolute_expired"


@pytest.mark.parametrize("realm", REALMS)
@pytest.mark.asyncio
async def test_a_persisted_cookie_is_refused_once_the_idle_window_lapses(
    realm: str, subjects: list[uuid.UUID]
) -> None:
    """The bound that makes a persistent cookie on a SHARED device acceptable.

    Twelve hours of no requests ends a client session whatever the browser still holds, and
    thirty minutes ends an operator's. A cookie on disk is not a session.
    """
    subject_id = _subject(subjects)
    async with credential_session() as session:
        issued = await issue_session(
            session, realm=realm, subject_id=subject_id, mfa_verified_at=datetime.now(UTC)
        )
    idled = datetime.now(UTC) + REALM_TIMEOUTS[realm].idle + timedelta(seconds=1)
    outcome = await verify_session(token=issued.token, realm=realm, now=idled)
    assert not outcome.live
    assert outcome.refusal == "idle_expired"


@pytest.mark.parametrize("realm", REALMS)
@pytest.mark.asyncio
async def test_the_idle_window_slides_while_the_cookies_bound_stays_put(
    realm: str, subjects: list[uuid.UUID]
) -> None:
    """Both halves of the sliding argument, on one session.

    The row's idle window moves forward on a verification an hour later — so a person who
    keeps using the console keeps their session — while `absolute_expires_at`, which is
    what the cookie's lifetime is derived from, is unchanged. That is why the cookie's
    remaining lifetime SHRINKS rather than sliding.
    """
    timeouts = REALM_TIMEOUTS[realm]
    subject_id = _subject(subjects)
    async with credential_session() as session:
        issued = await issue_session(
            session, realm=realm, subject_id=subject_id, mfa_verified_at=datetime.now(UTC)
        )
    # Comfortably inside the idle window for both realms, and enough to beat
    # `IDLE_WRITE_FLOOR` so the slide is actually written.
    later = datetime.now(UTC) + timeouts.idle - timedelta(minutes=5)
    live = (await verify_session(token=issued.token, realm=realm, now=later)).require_live()
    assert live.absolute_expires_at == issued.absolute_expires_at

    async with credential_session() as session:
        row = (
            await session.execute(
                text("SELECT idle_expires_at FROM auth_sessions WHERE id = :id"),
                {"id": issued.session_id},
            )
        ).first()
    assert row is not None
    assert row[0] > issued.absolute_expires_at - timeouts.absolute + timeouts.idle

    remaining = session_cookie_max_age(
        realm, absolute_expires_at=live.absolute_expires_at, now=later
    )
    if remaining is not None:
        assert remaining < int(timeouts.absolute.total_seconds())


@pytest.mark.parametrize("realm", REALMS)
@pytest.mark.asyncio
async def test_rotation_shortens_the_cookie_rather_than_renewing_it(
    realm: str, subjects: list[uuid.UUID]
) -> None:
    """`rotate_session` carries the absolute bound forward, so the re-issued cookie asks
    for LESS time than the first one did. A session that rotates cannot live forever, and
    neither can the cookie that carries it."""
    issued_at = datetime.now(UTC)
    subject_id = _subject(subjects)
    async with credential_session() as session:
        issued = await issue_session(
            session, realm=realm, subject_id=subject_id, mfa_verified_at=issued_at, now=issued_at
        )
    verified = (await verify_session(token=issued.token, realm=realm, now=issued_at)).require_live()
    rotated_at = issued_at + timedelta(minutes=10)
    async with credential_session() as session:
        rotated = await rotate_session(session, verified=verified, now=rotated_at)

    assert rotated.absolute_expires_at == issued.absolute_expires_at
    first = session_cookie_max_age(
        realm, absolute_expires_at=issued.absolute_expires_at, now=issued_at
    )
    second = session_cookie_max_age(
        realm, absolute_expires_at=rotated.absolute_expires_at, now=rotated_at
    )
    if first is None:
        assert second is None
    else:
        assert second is not None and second < first


@pytest.mark.asyncio
async def test_the_two_realms_bounds_are_independent(subjects: list[uuid.UUID]) -> None:
    """A client session and an operator session issued at the same instant get different
    absolute bounds, so the cookie lifetimes derived from them differ too. The negative
    control for "both realms want the same answer"."""
    at = datetime.now(UTC)
    subject_id = _subject(subjects)
    async with credential_session() as session:
        client = await issue_session(session, realm="client", subject_id=subject_id, now=at)
        admin = await issue_session(session, realm="admin", subject_id=subject_id, now=at)
    assert client.absolute_expires_at > admin.absolute_expires_at
    assert session_cookie_max_age("client", absolute_expires_at=client.absolute_expires_at, now=at)
    assert (
        session_cookie_max_age("admin", absolute_expires_at=admin.absolute_expires_at, now=at)
        is None
    )

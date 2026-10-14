"""An operator's "Stay signed in" switch (D-766): the bounds, the cookie, and who may move it.

Off, an admin session keeps 30 minutes idle and 8 hours absolute and a browser-session
cookie. On, a second-factor-complete session takes the client realm's 12 hours and 14 days
and a cookie with a `Max-Age`. The switch is read on every verification, so switching it off
shortens a live session on its next request.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints with `uuid4`, the
fixture deletes exactly those, and nothing counts rows globally (audit rows are counted by
this module's own object ids).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn import stay_signed_in
from apps.api.authn.cookies import cookie_name, session_cookie_max_age
from apps.api.authn.sessions import (
    REALM_TIMEOUTS,
    STAY_SIGNED_IN_TIMEOUTS,
    IssuedSession,
    issue_session,
    revoke_session,
    rotate_session,
    session_policy,
    verify_session,
)
from apps.api.authn.stepup import REAUTH_MAX_AGE
from apps.api.core.errors import ProblemError
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

ADMIN = REALM_TIMEOUTS["admin"]
LONG = STAY_SIGNED_IN_TIMEOUTS
PATH = "/v1/auth/admin/stay-signed-in"


@pytest_asyncio.fixture
async def operators() -> AsyncIterator[list[uuid.UUID]]:
    """Operator ids this file owns; `_operator` mints them."""
    owned: list[uuid.UUID] = []
    yield owned
    if owned:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = ANY(:ids)"), {"ids": owned}
            )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM admin_users WHERE id = ANY(:ids)"), {"ids": owned}
            )


async def _operator(owned: list[uuid.UUID], *, switch_on: bool = False) -> uuid.UUID:
    operator_id = uuid.uuid4()
    owned.append(operator_id)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, email, name, role, stay_signed_in, created_at, "
                "updated_at) VALUES (:id, :email, 'Stay Probe', 'operator', :on, now(), now())"
            ),
            {
                "id": operator_id,
                "email": f"stay-{operator_id.hex[:10]}@calevate-test.example",
                "on": switch_on,
            },
        )
    return operator_id


async def _set_switch(operator_id: uuid.UUID, on: bool) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE admin_users SET stay_signed_in = :on WHERE id = :id"),
            {"on": on, "id": operator_id},
        )


async def _switch(operator_id: uuid.UUID) -> bool:
    async with untenanted_session() as session:
        value = (
            await session.execute(
                text("SELECT stay_signed_in FROM admin_users WHERE id = :id"), {"id": operator_id}
            )
        ).scalar()
    return value is True


async def _issue(
    operator_id: uuid.UUID, at: datetime, *, factor_age: timedelta | None = timedelta(0)
) -> IssuedSession:
    """An admin session issued at `at`; `factor_age=None` leaves the second factor unproved."""
    async with credential_session() as session:
        return await issue_session(
            session,
            realm="admin",
            subject_id=operator_id,
            mfa_verified_at=None if factor_age is None else at - factor_age,
            now=at,
        )


async def _row(session_id: uuid.UUID) -> tuple[datetime, datetime]:
    async with credential_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT idle_expires_at, absolute_expires_at FROM auth_sessions WHERE id = :id"
                ),
                {"id": session_id},
            )
        ).one()
    return row[0], row[1]


async def _active_at(session_id: uuid.UUID, last_seen: datetime) -> None:
    """Pretend the session was last used at `last_seen`, with a long stored idle bound, so a
    test can reach the ABSOLUTE bound without sliding the idle one through many requests."""
    async with credential_session() as session:
        await session.execute(
            text(
                "UPDATE auth_sessions SET last_seen_at = :seen, idle_expires_at = :idle "
                "WHERE id = :id"
            ),
            {"seen": last_seen, "idle": last_seen + LONG.idle, "id": session_id},
        )


async def _refusal(token: str, at: datetime) -> str | None:
    return (await verify_session(token=token, realm="admin", now=at)).refusal


async def _audits(operator_id: uuid.UUID) -> list[str | None]:
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT actor_id::text FROM audit_log "
                "WHERE action = :action AND object_id = :oid ORDER BY at"
            ),
            {"action": stay_signed_in.AUDIT_ACTION, "oid": str(operator_id)},
        )
        return [row[0] for row in rows]


def _client() -> AsyncClient:
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)),
        base_url="https://api.calevate.tech",
    )


async def _send(token: str | None, on: bool) -> Response:
    cookies = {cookie_name("admin", secure=True): token} if token else {}
    async with _client() as http:
        return await http.post(PATH, json={"stay_signed_in": on}, cookies=cookies)


def _max_age(response: Response) -> int | None:
    header = response.headers["set-cookie"]
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "max-age":
            return int(value)
    return None


# ═══════════════ the policy ═══════════════


def test_the_long_bounds_are_the_client_realms_and_need_the_switch_and_the_second_factor() -> None:
    assert REALM_TIMEOUTS["client"] == LONG
    on = session_policy("admin", switch_on=True, second_factor_proved=True)
    assert on.timeouts == LONG and on.stay_signed_in
    for switch_on, proved in ((False, True), (True, False), (False, False)):
        policy = session_policy("admin", switch_on=switch_on, second_factor_proved=proved)
        assert policy.timeouts == ADMIN and not policy.stay_signed_in
    client = session_policy("client", switch_on=True, second_factor_proved=True)
    assert client.timeouts == REALM_TIMEOUTS["client"] and not client.stay_signed_in


def test_only_a_stay_signed_in_session_gets_a_persistent_admin_cookie() -> None:
    now = datetime.now(UTC)
    expires = now + LONG.absolute
    assert session_cookie_max_age("admin", absolute_expires_at=expires, now=now) is None
    assert session_cookie_max_age(
        "admin", absolute_expires_at=expires, now=now, stay_signed_in=True
    ) == int(LONG.absolute.total_seconds())


# ═══════════════ the bounds, off and on ═══════════════


async def test_off_an_admin_session_idles_out_at_30_minutes_and_ends_at_8_hours(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators)
    t0 = datetime.now(UTC)
    idle = await _issue(operator_id, t0)
    assert idle.absolute_expires_at == t0 + ADMIN.absolute
    assert not idle.policy.stay_signed_in
    present = await _issue(operator_id, t0)
    assert await _refusal(present.token, t0 + ADMIN.idle - timedelta(minutes=1)) is None
    assert await _refusal(idle.token, t0 + ADMIN.idle + timedelta(minutes=1)) == "idle_expired"

    busy = await _issue(operator_id, t0)
    await _active_at(busy.session_id, t0 + ADMIN.absolute - timedelta(minutes=5))
    assert (
        await _refusal(busy.token, t0 + ADMIN.absolute + timedelta(minutes=1)) == "absolute_expired"
    )


async def test_on_a_session_idles_for_12_hours_and_lives_14_days(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    quiet = await _issue(operator_id, t0)
    assert quiet.policy.stay_signed_in
    assert quiet.absolute_expires_at == t0 + LONG.absolute
    assert await _refusal(quiet.token, t0 + LONG.idle - timedelta(minutes=1)) is None
    # That verification slid the idle window by twelve hours, not thirty minutes.
    idle_at, _ = await _row(quiet.session_id)
    assert idle_at == t0 + LONG.idle - timedelta(minutes=1) + LONG.idle

    left = await _issue(operator_id, t0)
    assert await _refusal(left.token, t0 + LONG.idle + timedelta(minutes=1)) == "idle_expired"

    busy = await _issue(operator_id, t0)
    await _active_at(busy.session_id, t0 + LONG.absolute - timedelta(minutes=10))
    assert await _refusal(busy.token, t0 + LONG.absolute - timedelta(minutes=5)) is None
    assert (
        await _refusal(busy.token, t0 + LONG.absolute + timedelta(minutes=1)) == "absolute_expired"
    )


async def test_on_a_session_still_waiting_for_its_code_stays_short(
    operators: list[uuid.UUID],
) -> None:
    """A password alone must not buy fourteen days, though the row is born with them so the
    rotation that answers the code can carry them forward."""
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    waiting = await _issue(operator_id, t0, factor_age=None)
    assert not waiting.policy.stay_signed_in
    assert waiting.absolute_expires_at == t0 + LONG.absolute
    assert await _refusal(waiting.token, t0 + ADMIN.idle + timedelta(minutes=1)) == "idle_expired"

    busy = await _issue(operator_id, t0, factor_age=None)
    await _active_at(busy.session_id, t0 + ADMIN.absolute - timedelta(minutes=5))
    assert (
        await _refusal(busy.token, t0 + ADMIN.absolute + timedelta(minutes=1)) == "absolute_expired"
    )


async def test_answering_the_code_moves_a_session_onto_the_long_bounds(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    waiting = await _issue(operator_id, t0, factor_age=None)
    verified = (await verify_session(token=waiting.token, realm="admin", now=t0)).require_live()
    async with credential_session() as session:
        rotated = await rotate_session(session, verified=verified, mfa_verified_at=t0, now=t0)
    assert rotated.policy.stay_signed_in
    assert rotated.absolute_expires_at == t0 + LONG.absolute
    assert await _refusal(rotated.token, t0 + timedelta(hours=11)) is None


async def test_switching_off_shortens_a_live_session_on_its_next_request(
    operators: list[uuid.UUID],
) -> None:
    """Resolution at verify time: the row still says fourteen days, and the request is
    refused anyway, measured from the sign-in and from the last activity."""
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    old = await _issue(operator_id, t0)
    idle = await _issue(operator_id, t0)
    await _active_at(old.session_id, t0 + ADMIN.absolute - timedelta(minutes=5))
    await _set_switch(operator_id, False)

    assert (
        await _refusal(old.token, t0 + ADMIN.absolute + timedelta(minutes=1)) == "absolute_expired"
    )
    assert await _refusal(idle.token, t0 + ADMIN.idle + timedelta(minutes=1)) == "idle_expired"
    _, stored = await _row(old.session_id)
    assert stored == t0 + LONG.absolute


# ═══════════════ the operator's own switch, over HTTP ═══════════════


async def test_switching_on_needs_a_fresh_second_factor(operators: list[uuid.UUID]) -> None:
    operator_id = await _operator(operators)
    stale = await _issue(
        operator_id, datetime.now(UTC), factor_age=REAUTH_MAX_AGE + timedelta(minutes=1)
    )

    response = await _send(stale.token, True)

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")
    assert "stay_signed_in" in response.json()["remediation"]
    assert not await _switch(operator_id)
    assert await _audits(operator_id) == []


async def test_switching_on_lengthens_this_session_persists_its_cookie_and_is_audited(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators)
    issued = await _issue(operator_id, datetime.now(UTC))

    response = await _send(issued.token, True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stay_signed_in"] is True
    assert body["idle_timeout_seconds"] == int(LONG.idle.total_seconds())
    assert await _switch(operator_id)
    idle_at, absolute = await _row(issued.session_id)
    assert absolute == issued.absolute_expires_at - ADMIN.absolute + LONG.absolute
    assert idle_at > datetime.now(UTC) + LONG.idle - timedelta(minutes=1)
    # The same token, now kept by the browser until the row's absolute bound.
    assert issued.token in response.headers["set-cookie"]
    max_age = _max_age(response)
    assert max_age is not None
    assert abs(max_age - (absolute - datetime.now(UTC)).total_seconds()) < 60
    assert await _audits(operator_id) == [str(operator_id)]

    # Already on: the session is left as it is and nothing new is audited.
    again = await _send(issued.token, True)
    assert again.status_code == 200, again.text
    assert await _audits(operator_id) == [str(operator_id)]


async def test_switching_off_needs_no_code_shortens_every_session_and_is_audited(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    # Stale factor on purpose: switching OFF only shortens, so it asks for no code.
    caller = await _issue(operator_id, t0, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))
    other = await _issue(operator_id, t0)

    response = await _send(caller.token, False)

    assert response.status_code == 200, response.text
    assert response.json()["stay_signed_in"] is False
    assert response.json()["idle_timeout_seconds"] == int(ADMIN.idle.total_seconds())
    assert _max_age(response) is None
    assert not await _switch(operator_id)
    for session in (caller, other):
        idle_at, absolute = await _row(session.session_id)
        assert absolute == t0 + ADMIN.absolute
        assert idle_at <= t0 + ADMIN.idle
    assert await _audits(operator_id) == [str(operator_id)]


async def test_a_session_ended_before_the_switch_moves_rolls_the_switch_back(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators)
    issued = await _issue(operator_id, datetime.now(UTC))
    verified = (await verify_session(token=issued.token, realm="admin")).require_live()
    async with credential_session() as session:
        await revoke_session(session, session_id=issued.session_id, reason="signed_out")

    with pytest.raises(ProblemError) as caught:
        await stay_signed_in.set_own(verified=verified, on=True, ip=None)

    assert caught.value.status == 401
    assert not await _switch(operator_id)


async def test_the_switch_needs_a_session_cookie(operators: list[uuid.UUID]) -> None:
    response = await _send(None, True)
    assert response.status_code == 401, response.text


async def test_the_session_read_reports_the_idle_bound_the_server_enforces(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators)
    issued = await _issue(operator_id, datetime.now(UTC))
    cookies = {cookie_name("admin", secure=True): issued.token}

    async with _client() as http:
        off = (await http.get("/v1/auth/admin/session", cookies=cookies)).json()
    await _set_switch(operator_id, True)
    async with _client() as http:
        on = (await http.get("/v1/auth/admin/session", cookies=cookies)).json()

    assert (off["idle_timeout_seconds"], off["stay_signed_in"]) == (
        int(ADMIN.idle.total_seconds()),
        False,
    )
    assert (on["idle_timeout_seconds"], on["stay_signed_in"]) == (
        int(LONG.idle.total_seconds()),
        True,
    )


# ═══════════════ a superadmin, on someone else's account ═══════════════


async def _superadmin() -> str:
    from tests.admin_security_test import _make_admin

    return await _make_admin()


async def test_a_superadmin_can_switch_another_operator_off_and_it_is_audited(
    operators: list[uuid.UUID],
) -> None:
    operator_id = await _operator(operators, switch_on=True)
    t0 = datetime.now(UTC)
    live = await _issue(operator_id, t0)
    superadmin = await _superadmin()
    path = f"/v1/admin/operators/{operator_id}/stay-signed-in/revocation"
    headers = {"Authorization": f"Bearer {superadmin}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = await http.get("/v1/admin/operators", headers=headers)
        unconfirmed = await http.post(path, headers=headers, json={"reason": "lost phone"})
        confirmed = await http.post(
            path,
            headers={**headers, "X-Confirm-Action": f"end_stay_signed_in:{operator_id}"},
            json={"reason": "lost phone"},
        )

    mine = [o for o in listed.json()["operators"] if o["id"] == str(operator_id)]
    assert mine and mine[0]["stay_signed_in"] is True
    assert unconfirmed.status_code == 403, unconfirmed.text
    assert unconfirmed.json()["type"].endswith("/step_up_required")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["stay_signed_in"] is False
    assert not await _switch(operator_id)
    _, absolute = await _row(live.session_id)
    assert absolute == t0 + ADMIN.absolute
    assert await _audits(operator_id) == [superadmin.rsplit(":", 1)[1]]

"""`POST /v1/auth/{realm}/password/change` — the signed-in credential change (ASVS 5.0).

WHY THE ROUTE EXISTS. Until it did, a person who believed their password was compromised
had to sign OUT and use the emailed reset link — which depends on their mailbox being
reachable and uncompromised, the exact thing in doubt. `POST /logout/all` covered half of
it and the wrong half: it ends the sessions and leaves the attacker holding a credential
that still signs in.

THE TWO REQUIREMENTS THIS FILE DRIVES, both from OWASP ASVS 5.0 (read 2026-09-07):

  * §6.2.3 — "Verify that password change functionality requires the user's current and
    new password" (`5.0/en/0x15-V6-Authentication.md`).
  * §7.4.3 — "Verify that the application gives the option to terminate all other active
    sessions after a successful change or removal of any authentication factor"
    (`5.0/en/0x16-V7-Session-Management.md`). We do not offer it as an option; every other
    session dies, because the audience for this endpoint is somebody who thinks they are
    compromised and an unticked box would be the default that fails them.
  * §7.2.4 — "a new session token on user authentication, including re-authentication" is
    why the caller's own session is ROTATED rather than merely spared: a stolen cookie is a
    copy of the victim's OWN token, so sparing "the caller's row" would spare precisely the
    session the thief is using.

Everything is driven over ASGI against the real app, because the parts most likely to be
wrong are the parts a service-level test does not touch: which dependency guards the route,
whether the new cookie is actually set, and whether the old one is dead afterwards.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints with `uuid4`, the
fixtures delete exactly those, and nothing counts rows globally. The throttle keys are
deleted too — `PASSWORD_BUDGET` is per `(realm, subject)`, so a leftover counter from a
wrong-password test would 429 an unrelated one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn.cookies import cookie_name
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.sessions import issue_session, verify_session
from apps.api.authn.stepup import REAUTH_MAX_AGE
from apps.api.authn.throttle import KEY_PREFIX, PASSWORD_BUDGET
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.asyncio]

#: Both realms have a floor (`authn/policy.MIN_CHARS_BY_REALM`) and the client realm's is
#: the higher of the two at 15, so these clear both.
OLD_PASSWORD = "chinnamma-clinic-front-desk"
NEW_PASSWORD = "kondapalli-toy-shop-evening"


def _path(realm: str) -> str:
    return f"/v1/auth/{realm}/password/change"


def _client() -> AsyncClient:
    """A caller on a RUN-UNIQUE documentation address (RFC 3849), so no two tests in this
    file — or in another suite running beside it — share a rate-limit bucket."""
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)),
        base_url="https://api.calevate.tech",
    )


async def _cookies(realm: str, token: str) -> dict[str, str]:
    """The cookie jar a browser would present. `secure=True` because `_client` speaks
    https, and the `__Host-` name is the only one a TLS request is allowed to use
    (`tests/authn_cookie_fixation_e2e_test.py` is why)."""
    return {cookie_name(realm, secure=True): token}


@pytest_asyncio.fixture
async def subject_ids() -> AsyncIterator[dict[str, uuid.UUID]]:
    """One live subject per realm, each with `OLD_PASSWORD` installed."""
    admin_id, user_id = uuid.uuid4(), uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, email, name, role, created_at, "
                "updated_at) VALUES (:id, NULL, :email, 'Change Probe', 'superadmin', "
                "now(), now())"
            ),
            {"id": admin_id, "email": f"pwchange-{admin_id.hex[:10]}@calevate-test.example"},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Change Probe', now(), now())"
            ),
            {"id": user_id, "email": f"pwchange-{user_id.hex[:10]}@calevate-test.example"},
        )
    async with credential_session() as session:
        for realm, subject_id in (("admin", admin_id), ("client", user_id)):
            await set_password(session, realm=realm, subject_id=subject_id, password=OLD_PASSWORD)
    try:
        yield {"admin": admin_id, "client": user_id}
    finally:
        async with credential_session() as session:
            for table in ("auth_otp_challenges", "auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = ANY(:s)"),
                    {"s": [admin_id, user_id]},
                )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})
            await session.execute(text("DELETE FROM users WHERE id = :s"), {"s": user_id})
        redis = get_redis()
        for realm, subject_id in (("admin", admin_id), ("client", user_id)):
            await redis.delete(f"{KEY_PREFIX}:password:{realm}:{subject_id}")


async def _token(realm: str, subject_id: uuid.UUID, *, factor_age: timedelta | None = None) -> str:
    """A live session for this realm.

    On the admin realm `mfa_verified_at` is stamped, or every request is refused for the
    OTHER reason (`second_factor_required`) and the test would prove nothing. `factor_age`
    ages that stamp, which is how the step-up freshness branch is reached without winding a
    clock — the same idiom as `tests/authn_stepup_test.py`.
    """
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm=realm, subject_id=subject_id, now=at)
        if realm == "admin":
            await session.execute(
                text("UPDATE auth_sessions SET mfa_verified_at = :when WHERE id = :id"),
                {"when": at - (factor_age or timedelta(0)), "id": issued.session_id},
            )
    return issued.token


async def _password_is(realm: str, subject_id: uuid.UUID, password: str) -> bool:
    async with credential_session() as session:
        return await authenticate_subject(
            session, realm=realm, subject_id=subject_id, password=password
        )


async def _live(realm: str, token: str) -> bool:
    return (await verify_session(token=token, realm=realm)).session is not None


# ═══════════════ the happy path, and what it kills ═══════════════


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_a_change_replaces_the_password_and_ends_every_other_session(
    realm: str, subject_ids: dict[str, uuid.UUID]
) -> None:
    """ASVS §6.2.3 and §7.4.3 together, plus the thing they are for: the old password
    stops working, and so does every session that was not the one asking."""
    subject_id = subject_ids[realm]
    caller = await _token(realm, subject_id)
    elsewhere = await _token(realm, subject_id)
    stolen = await _token(realm, subject_id)

    async with _client() as http:
        response = await http.post(
            _path(realm),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies(realm, caller),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"revoked": 3}, (
        "three rows should die: the two other sessions, and the caller's OWN row, which "
        "rotation superseded and which the thief may still be holding a copy of"
    )
    assert not await _live(realm, elsewhere)
    assert not await _live(realm, stolen)
    assert await _password_is(realm, subject_id, NEW_PASSWORD)
    assert not await _password_is(realm, subject_id, OLD_PASSWORD)


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_the_caller_keeps_working_on_a_new_token_and_the_old_one_is_dead(
    realm: str, subject_ids: dict[str, uuid.UUID]
) -> None:
    """The half that makes this usable, and the half that makes it safe.

    A person must not be signed out of the browser they are sitting at — and the token that
    browser presented must not survive, because a stolen cookie is a copy of it (ASVS
    §7.2.4). The response therefore carries a NEW cookie, and only that one still verifies.
    """
    subject_id = subject_ids[realm]
    caller = await _token(realm, subject_id)

    async with _client() as http:
        response = await http.post(
            _path(realm),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies(realm, caller),
        )

    assert response.status_code == 200, response.text
    fresh = response.cookies.get(cookie_name(realm, secure=True))
    assert fresh and fresh != caller, "the response must set a rotated session cookie"
    assert await _live(realm, fresh)
    assert not await _live(realm, caller), "the token the browser presented must not survive"


# ═══════════════ the refusals, each with the state it must not have changed ═══════════════


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_the_current_password_is_required_and_a_wrong_one_changes_nothing(
    realm: str, subject_ids: dict[str, uuid.UUID]
) -> None:
    """ASVS §6.2.3. A live cookie alone must not be enough — that is the whole point of
    demanding the current password, and the negative control is that a wrong one leaves the
    stored password AND the other sessions exactly as they were."""
    subject_id = subject_ids[realm]
    caller = await _token(realm, subject_id)
    elsewhere = await _token(realm, subject_id)

    async with _client() as http:
        response = await http.post(
            _path(realm),
            json={"current_password": "not-the-right-passphrase", "new_password": NEW_PASSWORD},
            cookies=await _cookies(realm, caller),
        )

    assert response.status_code == 401, response.text
    assert response.json()["type"].endswith("/invalid_current_password"), response.text
    assert response.json()["remediation"], "a failure a user reaches needs a next step"
    assert await _password_is(realm, subject_id, OLD_PASSWORD)
    assert not await _password_is(realm, subject_id, NEW_PASSWORD)
    assert await _live(realm, elsewhere), "a refused change must not revoke anything"
    assert await _live(realm, caller)


async def test_a_new_password_below_the_realm_floor_is_refused_by_the_policy(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """The policy lives in `credentials.set_password`, which is why this route did not have
    to re-implement it — and this asserts the placement rather than assuming it. Sixteen
    characters clears the router's absolute `MIN_PASSWORD_CHARS` bound, so a 422 here can
    only have come from the store's per-realm floor being applied."""
    subject_id = subject_ids["client"]
    caller = await _token("client", subject_id)

    async with _client() as http:
        response = await http.post(
            _path("client"),
            json={"current_password": OLD_PASSWORD, "new_password": "kondapalli-toy"},
            cookies=await _cookies("client", caller),
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/password_length"), response.text
    assert await _password_is("client", subject_id, OLD_PASSWORD)


async def test_submitting_the_same_password_twice_is_refused_rather_than_congratulated(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """The dangerous no-op. Without this the caller is told "done", every other session is
    revoked, and they walk away believing the credential an attacker holds is dead."""
    subject_id = subject_ids["client"]
    caller = await _token("client", subject_id)
    elsewhere = await _token("client", subject_id)

    async with _client() as http:
        response = await http.post(
            _path("client"),
            json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
            cookies=await _cookies("client", caller),
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/password_unchanged"), response.text
    assert await _live("client", elsewhere), "nothing was changed, so nothing may be revoked"


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_no_session_no_change(realm: str) -> None:
    """The route is not a way to change a password by knowing one."""
    async with _client() as http:
        response = await http.post(
            _path(realm),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
    assert response.status_code == 401, response.text


# ═══════════════ the admin realm's extra gate ═══════════════


async def test_an_admin_session_that_never_proved_a_factor_cannot_change_the_password(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """A password-only admin session may do exactly one thing — answer its OTP. If it could
    change the password, the second factor would be a suggestion: a stolen password alone
    would be enough to replace itself."""
    subject_id = subject_ids["admin"]
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=subject_id)

    async with _client() as http:
        response = await http.post(
            _path("admin"),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies("admin", issued.token),
        )

    assert response.status_code == 401, response.text
    assert response.json()["type"].endswith("/second_factor_required"), response.text
    assert await _password_is("admin", subject_id, OLD_PASSWORD)


async def test_an_admin_whose_second_factor_is_stale_is_sent_to_step_up(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """`authn/stepup.REAUTH_MAX_AGE`, applied to a credential change. The refusal names the
    two endpoints that clear it, which is what an operator at 3am needs."""
    subject_id = subject_ids["admin"]
    caller = await _token("admin", subject_id, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))

    async with _client() as http:
        response = await http.post(
            _path("admin"),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies("admin", caller),
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required"), response.text
    assert "step-up" in response.json()["remediation"]
    assert await _password_is("admin", subject_id, OLD_PASSWORD)


async def test_the_client_realm_has_no_freshness_gate_to_apply(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """The asymmetry, asserted rather than left to be discovered.

    `service.MFA_REQUIRED_REALMS` never stamps `mfa_verified_at` on the client realm, so
    there is no freshness evidence a gate could read — a shared check would be vacuously
    true there and would read as protection that is not present. What stands in is the
    current password, which is demanded on both realms. A client session as old as the one
    the admin realm just refused therefore succeeds.
    """
    subject_id = subject_ids["client"]
    caller = await _token("client", subject_id)
    async with credential_session() as session:
        row = (
            await session.execute(
                text("SELECT mfa_verified_at FROM auth_sessions WHERE subject_id = :s"),
                {"s": subject_id},
            )
        ).first()
    assert row is not None and row[0] is None, "the premise: no factor is ever stamped here"

    async with _client() as http:
        response = await http.post(
            _path("client"),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies("client", caller),
        )

    assert response.status_code == 200, response.text


# ═══════════════ the counter that stops it being an oracle ═══════════════


async def test_a_wrong_current_password_spends_the_same_budget_a_sign_in_does(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """Somebody holding a stolen cookie but not the password must not get an unmetered
    guessing oracle here that the sign-in form denies them: the failure lands on the SAME
    `(realm, subject)` counter `service.sign_in` spends."""
    subject_id = subject_ids["client"]
    caller = await _token("client", subject_id)
    key = f"{KEY_PREFIX}:{PASSWORD_BUDGET.name}:client:{subject_id}"
    await get_redis().delete(key)

    async with _client() as http:
        response = await http.post(
            _path("client"),
            json={"current_password": "wrong-passphrase-entirely", "new_password": NEW_PASSWORD},
            cookies=await _cookies("client", caller),
        )

    assert response.status_code == 401, response.text
    assert int(await get_redis().get(key) or 0) == 1


async def test_a_spent_budget_refuses_before_any_verification_happens(
    subject_ids: dict[str, uuid.UUID],
) -> None:
    """The gate is `throttle.check`, applied BEFORE the Argon2 verification — so a spent
    budget does not also buy the attacker 30ms of our CPU per guess.

    The counter is planted rather than earned: driving eleven real failures would pay
    `service._equalise`'s backoff eleven times, which is a minute of wall clock for a
    property that is about which call comes first. `tests/authn_reset_throttle_test.py`
    takes the same shortcut for the same reason.
    """
    subject_id = subject_ids["client"]
    caller = await _token("client", subject_id)
    key = f"{KEY_PREFIX}:{PASSWORD_BUDGET.name}:client:{subject_id}"
    await get_redis().set(key, PASSWORD_BUDGET.threshold, ex=PASSWORD_BUDGET.window_s)

    async with _client() as http:
        response = await http.post(
            _path("client"),
            # The RIGHT password: a spent budget must refuse even a caller who could have
            # succeeded, or it is not a budget.
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            cookies=await _cookies("client", caller),
        )

    assert response.status_code == 429, response.text
    assert await _password_is("client", subject_id, OLD_PASSWORD)

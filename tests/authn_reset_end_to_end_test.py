"""Forgot password, end to end, on both realms — over HTTP against the real app.

Request a link, take the token from the queued email (the only place its plaintext
exists), confirm a new password, and check what the reset is for: the old password and
every old session are dead, the new password signs in, and on the admin realm the
second factor is still demanded. Then the refusals: a spent link, an expired link, and a
link from the other realm.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture deletes
exactly those (the hash-chained `audit_log` is append-only and keeps its rows), and the
throttle keys for these subjects are removed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from apps.api.authn import tokens
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.sessions import issue_session, verify_session
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core import console_links
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from apps.workers.email_render import render
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

REALMS = ("client", "admin")
OLD_PASSWORD = "vijayawada-front-desk-ledger"
#: Eight characters and not on the blocklist: the D-765 floor, exactly.
NEW_PASSWORD = "rhubarb9"


def _client() -> AsyncClient:
    """A run-unique documentation address (RFC 3849), so no rate-limit bucket is shared."""
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)),
        base_url="https://api.calevate.tech",
    )


@pytest_asyncio.fixture
async def accounts() -> AsyncIterator[dict[str, tuple[uuid.UUID, str]]]:
    """One live subject per realm, each with `OLD_PASSWORD`."""
    admin_id, user_id = uuid.uuid4(), uuid.uuid4()
    admin_email = f"reset-e2e-{admin_id.hex[:10]}@calevate-test.example"
    user_email = f"reset-e2e-{user_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, email, name, role, created_at, "
                "updated_at) VALUES (:id, NULL, :email, 'Reset Probe', 'operator', now(), now())"
            ),
            {"id": admin_id, "email": admin_email},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified_at, created_at, updated_at) "
                "VALUES (:id, :email, 'Reset Probe', now(), now(), now())"
            ),
            {"id": user_id, "email": user_email},
        )
    async with credential_session() as session:
        await set_password(session, realm="admin", subject_id=admin_id, password=OLD_PASSWORD)
        await set_password(session, realm="client", subject_id=user_id, password=OLD_PASSWORD)
    try:
        yield {"admin": (admin_id, admin_email), "client": (user_id, user_email)}
    finally:
        ids = [admin_id, user_id]
        async with credential_session() as session:
            for table in (
                "auth_email_tokens",
                "auth_otp_challenges",
                "auth_sessions",
                "auth_credentials",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = ANY(:s)"), {"s": ids}
                )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = ANY(:to)"),
                {"to": [admin_email, user_email]},
            )
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})
            await session.execute(text("DELETE FROM users WHERE id = :s"), {"s": user_id})
        redis = get_redis()
        for subject_id in ids:
            async for key in redis.scan_iter(f"{KEY_PREFIX}:*:{subject_id}"):
                await redis.delete(key)


async def _session(realm: str, subject_id: uuid.UUID) -> str:
    """A live, fully signed-in session — on the admin realm, with the second factor done."""
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm=realm, subject_id=subject_id, now=at)
        if realm == "admin":
            await session.execute(
                text("UPDATE auth_sessions SET mfa_verified_at = :at WHERE id = :id"),
                {"at": at, "id": issued.session_id},
            )
    return issued.token


async def _mailed_secret(email: str) -> tuple[str, str]:
    """The newest reset email queued for `email`: its realm and its token."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT payload->>'realm', payload->>'secret' FROM outbox_messages "
                    "WHERE payload->>'to' = :to AND payload->>'kind' = 'password_reset' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"to": email},
            )
        ).first()
    assert row is not None, "a reset request for a real address must queue its email"
    return str(row[0]), str(row[1])


async def _password_is(realm: str, subject_id: uuid.UUID, password: str) -> bool:
    async with credential_session() as session:
        return await authenticate_subject(
            session, realm=realm, subject_id=subject_id, password=password
        )


@pytest.mark.parametrize("realm", REALMS)
async def test_a_reset_from_request_to_sign_in(
    realm: str, accounts: dict[str, tuple[uuid.UUID, str]]
) -> None:
    subject_id, email = accounts[realm]
    signed_in_elsewhere = await _session(realm, subject_id)

    async with _client() as http:
        requested = await http.post(
            f"/v1/auth/{realm}/password/reset/request", json={"email": email}
        )
        assert requested.status_code == 202, requested.text
        assert requested.content == b""

        mailed_realm, secret = await _mailed_secret(email)
        assert mailed_realm == realm
        # The email links to THIS realm's page on THIS realm's host.
        link = urlsplit(console_links.password_reset_link(realm, secret))
        expected_path = (
            console_links.ADMIN_RESET_PASSWORD_PATH
            if realm == "admin"
            else console_links.CLIENT_RESET_PASSWORD_PATH
        )
        assert link.netloc == ("admin.calevate.tech" if realm == "admin" else "app.calevate.tech")
        assert link.path == expected_path
        assert (
            console_links.password_reset_link(realm, secret)
            in render("password_reset", realm, secret).text
        )

        confirmed = await http.post(
            f"/v1/auth/{realm}/password/reset/confirm",
            json={"token": secret, "password": NEW_PASSWORD},
        )
        assert confirmed.status_code == 204, confirmed.text

        # Every session that existed before the reset is dead.
        assert (await verify_session(token=signed_in_elsewhere, realm=realm)).session is None
        assert await _password_is(realm, subject_id, NEW_PASSWORD)
        assert not await _password_is(realm, subject_id, OLD_PASSWORD)

        # The link worked once.
        replay = await http.post(
            f"/v1/auth/{realm}/password/reset/confirm",
            json={"token": secret, "password": "a-different-passphrase"},
        )
        assert replay.status_code == 422, replay.text
        assert replay.json()["type"].endswith("/invalid_reset_token")

        signed_in = await http.post(
            f"/v1/auth/{realm}/login", json={"email": email, "password": NEW_PASSWORD}
        )
        assert signed_in.status_code == 200, signed_in.text
        # A reset replaces the password and nothing else: the admin second factor is still
        # demanded at the next sign-in.
        assert signed_in.json()["status"] == (
            "otp_required" if realm == "admin" else "authenticated"
        )

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'auth.password_changed' "
                    "AND object_id = :s"
                ),
                {"s": str(subject_id)},
            )
        ).scalar_one()
    assert audited == 1


@pytest.mark.parametrize("realm", REALMS)
async def test_a_link_from_the_other_realm_is_refused(
    realm: str, accounts: dict[str, tuple[uuid.UUID, str]]
) -> None:
    other = "client" if realm == "admin" else "admin"
    subject_id, _ = accounts[other]
    async with credential_session() as session:
        issued = await tokens.issue_token(
            session, purpose="password_reset", realm=other, subject_id=subject_id
        )

    async with _client() as http:
        response = await http.post(
            f"/v1/auth/{realm}/password/reset/confirm",
            json={"token": issued.token, "password": NEW_PASSWORD},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/invalid_reset_token")
    assert await _password_is(other, subject_id, OLD_PASSWORD)


@pytest.mark.parametrize("realm", REALMS)
async def test_an_expired_link_is_refused(
    realm: str, accounts: dict[str, tuple[uuid.UUID, str]]
) -> None:
    subject_id, _ = accounts[realm]
    async with credential_session() as session:
        issued = await tokens.issue_token(
            session,
            purpose="password_reset",
            realm=realm,
            subject_id=subject_id,
            now=datetime.now(UTC) - tokens.TOKEN_LIFETIMES["password_reset"] - timedelta(minutes=1),
        )

    async with _client() as http:
        response = await http.post(
            f"/v1/auth/{realm}/password/reset/confirm",
            json={"token": issued.token, "password": NEW_PASSWORD},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/invalid_reset_token")
    assert await _password_is(realm, subject_id, OLD_PASSWORD)

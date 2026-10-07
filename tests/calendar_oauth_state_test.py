"""The Google Calendar OAuth callback refuses a code from a consent this person did not start.

The attack (RFC 6749 §10.12, RFC 9700 §4.7): an attacker completes Google's consent for
THEIR OWN account through our client id, keeps the authorization code, and gets a signed-in
owner's browser to hand it to `POST /v1/actions/calendar/callback`. Before the fix the
callback took no `state` at all, so the owner's account stored the attacker's refresh token
and every calendar booking the agent made — callers' names and numbers — went to the
attacker's calendar. These tests drive the route itself, and none of them lets the code
reach Google: the refusal must come before the exchange.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.actions import calendar
from apps.api.admin import service as admin_service
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

CALLBACK = "/v1/actions/calendar/callback"
CONNECT = "/v1/actions/calendar/connect"


def _client() -> AsyncClient:
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)), base_url="http://api"
    )


async def _owner() -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
    org = await admin_service.create_organization(
        name="Calendar Clinic",
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(org["id"]))
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, user_id, {"Authorization": f"Bearer dev:client:{user_id}"}


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The platform OAuth client configured, and Google's token endpoint replaced by a
    recorder, so a test can assert the code was NEVER exchanged."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://app.test/cb")
    exchanged: list[str] = []
    real_client = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        exchanged.append(request.content.decode())
        return httpx.Response(
            200, json={"refresh_token": "attacker-refresh-token", "scope": "calendar"}
        )

    def _fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client)
    return exchanged


_CALENDAR_CREDENTIALS = (
    "SELECT count(*) FROM integration_credentials WHERE kind = 'google_calendar'"
)


async def _credentials(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text(_CALENDAR_CREDENTIALS))).scalar_one())


@pytest.mark.asyncio
async def test_a_callback_without_state_is_refused_before_the_exchange(google: list[str]) -> None:
    tenant_id, _, headers = await _owner()
    async with _client() as client:
        response = await client.post(CALLBACK, json={"code": "planted-code"}, headers=headers)
    assert response.status_code == 422
    assert google == [], "the planted code was exchanged with Google"
    assert await _credentials(tenant_id) == 0


@pytest.mark.asyncio
async def test_a_state_minted_for_another_account_is_refused(google: list[str]) -> None:
    """The attacker's own consent carries the attacker's state. Presented in the victim's
    session, it names the wrong account and the wrong person."""
    victim_tenant, _, victim_headers = await _owner()
    attacker_tenant, attacker_user, _ = await _owner()
    attacker_state = calendar.mint_oauth_state(tenant_id=attacker_tenant, user_id=attacker_user)
    async with _client() as client:
        response = await client.post(
            CALLBACK,
            json={"code": "planted-code", "state": attacker_state},
            headers=victim_headers,
        )
    assert response.status_code == 403
    assert response.json()["type"].endswith("/calendar_oauth_state_invalid")
    assert google == []
    assert await _credentials(victim_tenant) == 0


@pytest.mark.asyncio
async def test_a_bare_tenant_id_is_not_a_state(google: list[str]) -> None:
    """The old `state` was the tenant id. It is public, so it must not verify."""
    tenant_id, _, headers = await _owner()
    async with _client() as client:
        response = await client.post(
            CALLBACK, json={"code": "planted-code", "state": str(tenant_id)}, headers=headers
        )
    assert response.status_code == 403
    assert google == []


@pytest.mark.asyncio
async def test_an_expired_state_is_refused(google: list[str]) -> None:
    tenant_id, user_id, headers = await _owner()
    stale = calendar.mint_oauth_state(
        tenant_id=tenant_id,
        user_id=user_id,
        now=datetime.now(UTC) - calendar.OAUTH_STATE_TTL - timedelta(minutes=1),
    )
    async with _client() as client:
        response = await client.post(
            CALLBACK, json={"code": "real-code", "state": stale}, headers=headers
        )
    assert response.status_code == 403
    assert google == []


@pytest.mark.asyncio
async def test_the_state_from_connect_completes_the_connection(google: list[str]) -> None:
    """The happy path still works end to end: connect mints the state Google echoes back."""
    tenant_id, _, headers = await _owner()
    async with _client() as client:
        started = await client.get(CONNECT, headers=headers)
        assert started.status_code == 200
        query = httpx.URL(started.json()["authorize_url"]).params
        state = query["state"]
        assert state != str(tenant_id)
        finished = await client.post(
            CALLBACK, json={"code": "real-code", "state": state}, headers=headers
        )
    assert finished.status_code == 200, finished.text
    assert len(google) == 1
    assert await _credentials(tenant_id) == 1

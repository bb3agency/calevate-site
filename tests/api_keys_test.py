"""Tenant API keys (D-1047, W2.1): made by the owner with a code, used only on `/api/v1/`,
never more than their creator, and stopped at once by revocation or expiry."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from apps.api.api_keys import tokens
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.conftest import add_receptionist_for_tests
from tests.lead_dial_routes_test import _client, _dialable_tenant, _member_of

READ = ["org:read", "agents:read", "calls:read", "leads:read"]
DIAL = [*READ, "leads:dispatch", "wallet:read"]


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.one_call_test import _DAYTIME

    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _DAYTIME)


async def make_key(
    headers: dict[str, str], slug: str, *, scopes: list[str] | None = None, **extra: Any
) -> str:
    async with _client() as http:
        response = await http.post(
            "/v1/api-keys",
            json={"name": "n8n box", "scopes": scopes or DIAL, **extra},
            headers={**headers, "X-Confirm-Action": f"create_api_key:{slug}"},
        )
    assert response.status_code == 201, response.text
    return str(response.json()["secret"])


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def test_a_minted_key_carries_its_prefix_and_a_checksum_that_catches_a_typo() -> None:
    secret = tokens.mint()
    assert secret.startswith("cvk_live_") and len(secret) == tokens.TOKEN_LEN
    assert tokens.well_formed(secret)
    flipped = secret[:12] + ("A" if secret[12] != "A" else "B") + secret[13:]
    assert not tokens.well_formed(flipped)
    assert not tokens.well_formed("cvk_test_" + secret[9:])
    assert len(tokens.digest(secret)) == 64


async def test_making_a_key_needs_the_code_and_the_secret_is_shown_once() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    async with _client() as http:
        refused = await http.post(
            "/v1/api-keys", json={"name": "k", "scopes": READ}, headers=headers
        )
    assert refused.status_code == 403
    assert refused.json()["type"].endswith("step_up_required")

    secret = await make_key(headers, slug, scopes=READ)
    async with _client() as http:
        listed = await http.get("/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert secret not in listed.text
    (key,) = listed.json()["keys"]
    assert key["display_prefix"] == secret[: tokens.DISPLAY_LEN]
    assert key["state"] == "active"
    async with tenant_session(tenant_id) as session:
        stored = (await session.execute(text("SELECT secret_sha256 FROM api_keys"))).scalar_one()
    assert stored == tokens.digest(secret) and secret not in stored


async def test_staff_cannot_make_a_key_and_raw_transcripts_are_never_grantable() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    staff = await _member_of(tenant_id, slug, "staff")
    async with _client() as http:
        as_staff = await http.post(
            "/v1/api-keys",
            json={"name": "k", "scopes": READ},
            headers={**staff, "X-Confirm-Action": f"create_api_key:{slug}"},
        )
        raw = await http.post(
            "/v1/api-keys",
            json={"name": "k", "scopes": [*READ, "calls:read_raw"]},
            headers={**headers, "X-Confirm-Action": f"create_api_key:{slug}"},
        )
    assert as_staff.status_code == 403
    assert raw.status_code == 422
    assert raw.json()["type"].endswith("api_key_scope_not_grantable")


async def test_a_key_without_the_dial_permission_is_refused_naming_it() -> None:
    _tenant, agent_id, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug, scopes=READ)
    async with _client() as http:
        response = await http.post(
            "/api/v1/calls",
            json={"phone": "9876500001", "agent_id": str(agent_id), "reason": "Hello"},
            headers={**bearer(secret), "Idempotency-Key": "k1"},
        )
    assert response.status_code == 403
    body = response.json()
    assert body["type"].endswith("scope_missing")
    assert "leads:dispatch" in body["detail"]


async def test_a_cookie_route_refuses_a_valid_key_and_a_key_route_refuses_a_session() -> None:
    _tenant, _agent, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug)
    async with _client() as http:
        cookie_route = await http.get("/v1/me", headers={**bearer(secret), "X-Org-Slug": slug})
        key_route = await http.get("/api/v1/me", headers=headers)
        good = await http.get("/api/v1/me", headers=bearer(secret))
    assert cookie_route.status_code == 401
    assert key_route.status_code == 401
    assert key_route.json()["type"].endswith("api_key_invalid")
    assert good.status_code == 200, good.text


async def test_a_key_bound_to_one_agent_cannot_dial_through_another() -> None:
    tenant_id, agent_id, slug, headers = await _dialable_tenant()
    other, _schema = await add_receptionist_for_tests(
        tenant_id, name="Second", vertical_template="clinic"
    )
    secret = await make_key(headers, slug, agent_ids=[str(agent_id)])
    async with _client() as http:
        response = await http.post(
            "/api/v1/calls",
            json={"phone": "9876500002", "agent_id": str(other), "reason": "Hello"},
            headers={**bearer(secret), "Idempotency-Key": "k2"},
        )
        listed = await http.get("/api/v1/agents", headers=bearer(secret))
    assert response.status_code == 403
    assert response.json()["type"].endswith("api_key_agent_refused")
    assert [a["id"] for a in listed.json()["data"]] == [str(agent_id)]


async def test_a_revoked_or_expired_key_is_refused_on_its_next_request() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    revoked = await make_key(headers, slug)
    expired = await make_key(headers, slug)
    async with tenant_session(tenant_id) as session:
        ids = dict((await session.execute(text("SELECT secret_sha256, id FROM api_keys"))).all())
        await session.execute(
            text(
                "UPDATE api_keys SET created_at = now() - interval '100 days', "
                "expires_at = now() - interval '1 day' WHERE id = :id"
            ),
            {"id": ids[tokens.digest(expired)]},
        )
    async with _client() as http:
        assert (await http.get("/api/v1/me", headers=bearer(revoked))).status_code == 200
        done = await http.post(
            f"/v1/api-keys/{ids[tokens.digest(revoked)]}/revoke", headers=headers
        )
        assert done.status_code == 200 and done.json()["state"] == "revoked"
        after = await http.get("/api/v1/me", headers=bearer(revoked))
        late = await http.get("/api/v1/me", headers=bearer(expired))
    assert after.status_code == 401 and after.json()["type"].endswith("api_key_revoked")
    assert late.status_code == 401 and late.json()["type"].endswith("api_key_expired")


async def test_a_key_never_holds_more_than_its_creator_does_today() -> None:
    tenant_id, agent_id, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug)
    user_id = uuid.UUID(headers["Authorization"].rsplit(":", 1)[1])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE memberships SET role = 'staff' WHERE user_id = :u"), {"u": user_id}
        )
    async with _client() as http:
        demoted = await http.post(
            "/api/v1/dnc",
            json={"numbers": ["9876500003"]},
            headers=bearer(secret),
        )
    assert demoted.status_code == 403 and demoted.json()["type"].endswith("scope_missing")
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": user_id})
    async with _client() as http:
        gone = await http.get("/api/v1/me", headers=bearer(secret))
    assert gone.status_code == 401 and gone.json()["type"].endswith("api_key_creator_gone")
    del agent_id


async def test_a_request_from_a_web_page_is_refused() -> None:
    _tenant, _agent, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug)
    async with _client() as http:
        with_origin = await http.get(
            "/api/v1/me", headers={**bearer(secret), "Origin": "https://evil.example"}
        )
        fetched = await http.get(
            "/api/v1/me", headers={**bearer(secret), "Sec-Fetch-Site": "cross-site"}
        )
    for response in (with_origin, fetched):
        assert response.status_code == 403
        assert response.json()["type"].endswith("api_key_browser_refused")


async def test_a_key_bound_to_addresses_refuses_any_other() -> None:
    _tenant, _agent, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug, ip_cidrs=["203.0.113.0/24"])
    async with _client() as http:
        response = await http.get("/api/v1/me", headers=bearer(secret))
    assert response.status_code == 403
    assert response.json()["type"].endswith("api_key_address_refused")


async def test_an_act_by_a_key_is_audited_as_the_key() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    secret = await make_key(headers, slug)
    async with _client() as http:
        response = await http.post(
            "/api/v1/dnc", json={"numbers": ["9876500004"]}, headers=bearer(secret)
        )
    assert response.status_code == 201, response.text
    async with tenant_session(tenant_id) as session:
        key_id = (
            await session.execute(
                text("SELECT id FROM api_keys WHERE secret_sha256 = :d"),
                {"d": tokens.digest(secret)},
            )
        ).scalar_one()
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'dnc.added'"
                ),
                {"t": tenant_id},
            )
        ).one()
    assert row[0] == "api_key" and row[1] == key_id


async def test_the_secret_never_reaches_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    _tenant, agent_id, slug, headers = await _dialable_tenant()
    caplog.set_level(logging.DEBUG)
    secret = await make_key(headers, slug)
    async with _client() as http:
        await http.get("/api/v1/me", headers=bearer(secret))
        await http.post(
            "/api/v1/calls",
            json={"phone": "9876500005", "agent_id": str(agent_id), "reason": "Hi"},
            headers={**bearer(secret), "Idempotency-Key": "log-1"},
        )
        await http.get("/api/v1/me", headers=bearer(secret[:-1] + "x"))
    every_line = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert secret not in every_line
    assert secret[len(tokens.LIVE_PREFIX) : -7] not in every_line


async def test_another_account_sees_none_of_these_keys_or_requests() -> None:
    tenant_a, _agent, slug, headers = await _dialable_tenant()
    tenant_b, _agent_b, _slug_b, _headers_b = await _dialable_tenant()
    secret = await make_key(headers, slug)
    async with _client() as http:
        await http.get("/api/v1/me", headers=bearer(secret))
    from apps.api.public_api import activity

    await activity.flush()
    async with tenant_session(tenant_a) as session:
        own_keys = (await session.execute(text("SELECT count(*) FROM api_keys"))).scalar_one()
        own_logs = (await session.execute(text("SELECT count(*) FROM api_requests"))).scalar_one()
    async with tenant_session(tenant_b) as session:
        keys = (await session.execute(text("SELECT count(*) FROM api_keys"))).scalar_one()
        logs = (await session.execute(text("SELECT count(*) FROM api_requests"))).scalar_one()
    async with untenanted_session() as session:
        bare = (await session.execute(text("SELECT count(*) FROM api_keys"))).scalar_one()
    assert own_keys == 1 and own_logs >= 1
    assert keys == 0 and logs == 0 and bare == 0

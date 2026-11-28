"""The public API v1 surface (D-1047, W2.2, W2.3, W2.8, W2.13): thin doors over the
console's own, so every call still meets the gate, a retry rings once, money is a string,
lists page by cursor, and each answer says its version and its limits."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.public_api import activity, deps
from apps.api.public_api.version import CURRENT_VERSION
from sqlalchemy import text
from tests.api_keys_test import DIAL, bearer, make_key
from tests.lead_dial_routes_test import _client, _dialable_tenant, _lead, _outbound_calls


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.one_call_test import _DAYTIME

    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _DAYTIME)


def _number() -> str:
    return f"9876{uuid.uuid4().int % 1000000:06d}"


async def _keyed() -> tuple[uuid.UUID, uuid.UUID, dict[str, str], dict[str, str]]:
    tenant_id, agent_id, slug, headers = await _dialable_tenant()
    return tenant_id, agent_id, headers, bearer(await make_key(headers, slug))


async def test_every_answer_says_its_version_and_its_limits() -> None:
    _t, _a, _h, key = await _keyed()
    async with _client() as http:
        response = await http.get("/api/v1/me", headers=key)
        unknown = await http.get("/api/v1/me", headers={**key, "Calevate-Version": "1999-01-01"})
    assert response.status_code == 200, response.text
    assert response.headers["Calevate-Version"] == CURRENT_VERSION
    assert response.headers["RateLimit-Policy"].startswith('"per-key";q=')
    assert response.headers["RateLimit"].startswith('"per-key";r=')
    assert "no-store" in response.headers["Cache-Control"]
    assert response.json()["api_version"] == CURRENT_VERSION
    assert unknown.status_code == 400 and unknown.json()["type"].endswith("api_version_unknown")


async def test_a_call_goes_through_the_gate_and_a_retry_rings_once() -> None:
    tenant_id, agent_id, _h, key = await _keyed()
    body = {"phone": _number(), "agent_id": str(agent_id), "reason": "Confirm the visit"}
    async with _client() as http:
        missing = await http.post("/api/v1/calls", json=body, headers=key)
        first = await http.post(
            "/api/v1/calls", json=body, headers={**key, "Idempotency-Key": "same-attempt"}
        )
        again = await http.post(
            "/api/v1/calls", json=body, headers={**key, "Idempotency-Key": "same-attempt"}
        )
    assert missing.status_code == 400
    assert missing.json()["type"].endswith("idempotency_key_required")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert again.json()["call_id"] == first.json()["call_id"]
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert len(await _outbound_calls(tenant_id)) == 1
    assert '"calls-today";r=' in first.headers["RateLimit"]

    async with _client() as http:
        detail = await http.get(f"/api/v1/calls/{first.json()['call_id']}?wait=1", headers=key)
    assert detail.status_code == 200
    assert detail.json()["phone"].endswith(body["phone"])
    assert detail.json()["finished"] is False


DIAL_ROUTES = {
    ("POST", "/api/v1/calls"),
    ("POST", "/api/v1/leads"),
    ("POST", "/api/v1/campaigns/{campaign_id}/launch"),
}
#: `leads:dispatch` writes that ring nobody, and why.
NOT_DIALS = {
    ("POST", "/api/v1/dnc"): "adds suppressions",
    ("DELETE", "/api/v1/dnc/{entry_id}"): "removes a hand-added suppression",
    ("POST", "/api/v1/campaigns/{campaign_id}/contacts"): "adds to a list; launch dials",
    ("POST", "/api/v1/campaigns/{campaign_id}/pause"): "stops dialling",
    ("POST", "/api/v1/campaigns/{campaign_id}/stop"): "stops dialling",
    ("POST", "/api/v1/campaigns/{campaign_id}/resume"): "each call meets check_dispatch",
}


def test_every_public_write_that_can_dial_is_named() -> None:
    from apps.api.main import app

    writes = {
        (method, route.path)
        for route in iter_api_routes(app)
        if route.path.startswith("/api/v1/")
        and (route.openapi_extra or {}).get("x-calevate-permission") == "leads:dispatch"
        for method in route.methods or ()
    }
    assert writes == DIAL_ROUTES | set(NOT_DIALS)


async def test_each_dialling_route_asks_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route walk: every public route that can ring a phone reaches the gate."""
    from apps.api.campaigns import service as campaigns
    from apps.api.compliance import service as compliance

    asked: list[str] = []
    real_check = compliance.check_dispatch

    async def spy_check(*args: Any, **kwargs: Any) -> Any:
        asked.append("check_dispatch")
        return await real_check(*args, **kwargs)

    async def spy_launch(*args: Any, **kwargs: Any) -> Any:
        asked.append("launch_blockers")
        return [campaigns.LaunchBlocker(rule="test_gate", reason="Held by the test.")]

    for module in (
        "apps.api.compliance.service",
        "apps.api.crm.one_call",
        "apps.api.crm.lead_dial",
        "apps.api.ingest.service",
    ):
        monkeypatch.setattr(f"{module}.check_dispatch", spy_check, raising=False)
    monkeypatch.setattr(campaigns, "launch_blockers", spy_launch)

    tenant_id, agent_id, _h, key = await _keyed()
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Check-ups', 'service', 'draft')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        source_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, agent_id, source, secret_ref, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, :a, 'website_form', "
                "'s', CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"i": source_id, "t": tenant_id, "a": agent_id},
        )
    async with _client() as http:
        await http.post(
            "/api/v1/calls",
            json={"phone": _number(), "agent_id": str(agent_id), "reason": "Hi"},
            headers={**key, "Idempotency-Key": "walk-1"},
        )
        assert asked and set(asked) == {"check_dispatch"}, asked
        asked.clear()
        lead = await http.post(
            "/api/v1/leads",
            json={"source_id": str(source_id), "lead": {"phone": _number(), "name": "Asha"}},
            headers={**key, "Idempotency-Key": "walk-2"},
        )
        assert lead.status_code == 202, lead.text
        assert "check_dispatch" in asked or lead.json()["blocked_rule"], (asked, lead.json())
        asked.clear()
        launch = await http.post(f"/api/v1/campaigns/{campaign_id}/launch", headers=key)
    assert "launch_blockers" in asked, (asked, launch.text)
    assert launch.status_code >= 400


async def test_lists_page_by_cursor_and_respect_the_key() -> None:
    tenant_id, agent_id, _h, key = await _keyed()
    made = [(await _lead(tenant_id, agent_id))[0] for _ in range(3)]
    async with _client() as http:
        first = await http.get("/api/v1/leads?limit=2", headers=key)
        page = first.json()
        second = await http.get(f"/api/v1/leads?limit=2&after={page['next_cursor']}", headers=key)
        one = await http.get(f"/api/v1/leads/{made[0]}", headers=key)
    assert first.status_code == 200, first.text
    assert page["has_more"] is True and len(page["data"]) == 2
    assert second.json()["has_more"] is False
    seen = [lead["id"] for lead in page["data"] + second.json()["data"]]
    assert sorted(seen) == sorted(str(m) for m in made)
    assert one.status_code == 200 and isinstance(one.json()["fields"], list)


async def test_balance_is_a_string_of_rupees() -> None:
    _t, _a, _h, key = await _keyed()
    async with _client() as http:
        response = await http.get("/api/v1/balance", headers=key)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["balance_inr"], str) and "." in body["balance_inr"]
    assert body["daily_call_budget"] in (deps.DAILY_CALLS_PAID, deps.DAILY_CALLS_TRIAL)


async def test_do_not_call_add_check_and_remove_with_a_reason() -> None:
    tenant_id, _a, _h, key = await _keyed()
    number = _number()
    async with _client() as http:
        added = await http.post("/api/v1/dnc", json={"numbers": [number]}, headers=key)
        checked = await http.post("/api/v1/dnc/check", json={"phone": number}, headers=key)
        listed = await http.get("/api/v1/dnc", headers=key)
        (entry,) = [e for e in listed.json()["data"] if e["phone"].endswith(number)]
        no_reason = await http.request("DELETE", f"/api/v1/dnc/{entry['id']}", headers=key)
        removed = await http.request(
            "DELETE",
            f"/api/v1/dnc/{entry['id']}",
            json={"reason": "Typed the wrong number"},
            headers=key,
        )
    assert added.status_code == 201 and added.json()["added"] == 1
    assert checked.json()["suppressed"] is True
    assert no_reason.status_code == 422
    assert removed.status_code == 204, removed.text

    async with tenant_session(tenant_id) as session:
        optout = uuid7()
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:i, :t, :p, 'tenant', 'call_optout', now(), now())"
            ),
            {"i": optout, "t": tenant_id, "p": f"+91{_number()}"},
        )
    async with _client() as http:
        refused = await http.request(
            "DELETE",
            f"/api/v1/dnc/{optout}",
            json={"reason": "They changed their mind"},
            headers=key,
        )
    assert refused.status_code == 422 and refused.json()["type"].endswith("dnc_consumer_optout")


async def test_the_daily_call_budget_refuses_and_a_blocked_call_is_given_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "DAILY_CALLS_PAID", 1)
    monkeypatch.setattr(deps, "DAILY_CALLS_TRIAL", 1)
    tenant_id, agent_id, _h, key = await _keyed()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:i, :t, '+919876000111', 'tenant', 'manual', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
    async with _client() as http:
        blocked = await http.post(
            "/api/v1/calls",
            json={"phone": "9876000111", "agent_id": str(agent_id), "reason": "Hi"},
            headers={**key, "Idempotency-Key": "budget-1"},
        )
        placed = await http.post(
            "/api/v1/calls",
            json={"phone": _number(), "agent_id": str(agent_id), "reason": "Hi"},
            headers={**key, "Idempotency-Key": "budget-2"},
        )
        over = await http.post(
            "/api/v1/calls",
            json={"phone": _number(), "agent_id": str(agent_id), "reason": "Hi"},
            headers={**key, "Idempotency-Key": "budget-3"},
        )
    assert blocked.json()["status"] == "blocked", blocked.text
    assert placed.json()["status"] == "queued", placed.text
    assert over.status_code == 429 and over.json()["type"].endswith("api_daily_call_budget")
    assert "Retry-After" in over.headers


async def test_the_activity_log_keeps_route_templates_never_numbers() -> None:
    _t, _a, headers, key = await _keyed()
    number = _number()
    async with _client() as http:
        await http.post("/api/v1/dnc", json={"numbers": [number]}, headers=key)
        listed = await http.get("/api/v1/dnc", headers=key)
        (entry,) = [e for e in listed.json()["data"] if e["phone"].endswith(number)]
        await http.request(
            "DELETE", f"/api/v1/dnc/{entry['id']}", json={"reason": "Wrong digit"}, headers=key
        )
        await http.get("/api/v1/calls/not-a-uuid", headers=key)
    await activity.flush()
    async with _client() as http:
        log = await http.get("/v1/api-keys/activity", headers=headers)
        failed = await http.get("/v1/api-keys/activity?failed=true", headers=headers)
        keys = await http.get("/v1/api-keys", headers=headers)
    assert log.status_code == 200, log.text
    routes = {row["route"] for row in log.json()["requests"]}
    assert {"/api/v1/dnc", "/api/v1/dnc/{entry_id}"} <= routes
    assert number not in log.text and entry["id"] not in log.text
    assert all(row["status"] >= 400 for row in failed.json()["requests"])
    assert any(row["remediation"] for row in failed.json()["requests"])
    assert keys.json()["keys"][0]["health"]["requests_24h"] >= 3


async def test_a_neighbours_key_finds_nothing() -> None:
    """Every `/api/v1/` route that takes an id, driven with ANOTHER account's real ids:
    each answers 404, because the row is not visible to the key's tenant session."""
    from apps.api.main import app

    tenant_a, agent_a, _ha, _key_a = await _keyed()
    _tb, _ab, slug_b, headers_b = await _dialable_tenant()
    # Every scope a route here asks, so each refusal is the row's absence, not the key's.
    key_b = bearer(await make_key(headers_b, slug_b, scopes=[*DIAL, "org:manage"]))
    lead_id, phone = await _lead(tenant_a, agent_a)
    ids = {
        "agent_id": agent_a,
        "lead_id": lead_id,
        "call_id": uuid7(),
        "entry_id": uuid7(),
        "campaign_id": uuid7(),
        "webhook_id": uuid7(),
    }
    async with tenant_session(tenant_a) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, lead_id, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                ":p, 'completed', :l, now(), now())"
            ),
            {
                "i": ids["call_id"],
                "t": tenant_a,
                "a": agent_a,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "p": phone,
                "l": lead_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:i, :t, :p, 'tenant', 'manual', now(), now())"
            ),
            {"i": ids["entry_id"], "t": tenant_a, "p": phone},
        )
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Check-ups', 'service', 'paused')"
            ),
            {"id": ids["campaign_id"], "t": tenant_a, "a": agent_a},
        )
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:i, :t, 'webhook', "
                "'https://crm.example/hook', 'whsec_x', ARRAY['lead.created'], true, now(), now())"
            ),
            {"i": ids["webhook_id"], "t": tenant_a},
        )
    bodies: dict[str, dict[str, Any]] = {
        "DELETE /api/v1/dnc/{entry_id}": {"reason": "Not theirs to remove"},
        "POST /api/v1/campaigns/{campaign_id}/contacts": {"contacts": [{"phone": "9876500099"}]},
    }
    routes = sorted(
        (method, route.path)
        for route in iter_api_routes(app)
        if route.path.startswith("/api/v1/") and "{" in route.path
        for method in route.methods or ()
    )
    assert len(routes) >= 11
    offenders = []
    async with _client() as http:
        for method, template in routes:
            path = template
            for name, value in ids.items():
                path = path.replace("{" + name + "}", str(value))
            assert "{" not in path, template
            response = await http.request(
                method, path, headers=key_b, json=bodies.get(f"{method} {template}")
            )
            body = response.json() if response.content else {}
            code = str(body.get("type", "")).rsplit("/", 1)[-1]
            if response.status_code != 404 or code != "not_found":
                offenders.append(f"{method} {template} -> {response.status_code} {code}")
    assert not offenders, offenders

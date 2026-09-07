"""The two-speed publishing endpoints over HTTP.

Three contracts that live at the router level. `publishing_routes.py` IS mounted in
`main.py` (before `agents.routes.router` — see contract 2), so the route-table sweeps
now cover these paths too; this file keeps asserting them against the assembled router
directly, which is what catches a break at the moment it is written rather than after
someone remembers to mount it:

1. **D-22.** `GET /v1/agents/{id}/pending` and `GET /v1/agents/lanes` are the views a
   client opens when an edit has not taken effect and a support person opens while
   looking at that client's screen. A GET gated on `agents:write` is invisible to
   read-only impersonation — the bug `tests/impersonation_reads_test.py` was written
   for, three times over. That file asserts the rule across `main.py`'s route table
   and therefore cannot see these routes until they are mounted; this file asserts the
   same rule against the assembled router now, so the routes cannot land already
   broken.
2. **Mount order.** `/v1/agents/{agent_id}` matches the literal segment `lanes`, so a
   router mounted after `agents.routes.router` turns `GET /v1/agents/lanes` into a 422
   about a UUID nobody sent. Same hazard as `/v1/agents/voices`.
3. **The error shape.** RFC-9457: the machine code is the last segment of `type`, and
   there is no `code` key.
"""

from __future__ import annotations

import uuid

from apps.api.agents.publishing_routes import router as publishing_router
from apps.api.agents.routes import router as agents_router
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import (
    MUTATING_PERMISSIONS,
    assert_policy_registry_complete,
    iter_api_routes,
)
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.credit_lots_helpers import GROWTH, PLUS, add_lot
from tests.two_speed_publishing_test import _live_agent_with_a_staged_draft


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    # ORDER IS THE CONTRACT: the literal `/v1/agents/lanes` before
    # `/v1/agents/{agent_id}`, or FastAPI matches the parameterised route first.
    application.include_router(publishing_router)
    application.include_router(agents_router)
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _admin_token(role: str = "superadmin") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _slug(tenant_id: uuid.UUID) -> str:
    # `organizations` is tenant-scoped: an untenanted session sees zero rows.
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).first()
    assert row is not None
    return str(row[0])


# --- D-22 ---------------------------------------------------------------------


def test_no_publishing_read_is_gated_on_a_mutating_permission() -> None:
    """The rule `tests/impersonation_reads_test.py` enforces over `main.py`, applied
    to a router it cannot yet see."""
    offenders = [
        (route.path, (route.openapi_extra or {}).get("x-calevate-permission"))
        for route in iter_api_routes(_app())
        if route.methods in ({"GET"}, {"GET", "HEAD"})
        and (route.openapi_extra or {}).get("x-calevate-permission") in MUTATING_PERMISSIONS
    ]
    assert not offenders, (
        "These GETs require a MUTATING permission, so D-22 hides them from read-only "
        f"impersonation — and they exist to explain why an edit is not live: {offenders}"
    )


async def test_a_client_can_read_what_is_pending_on_their_own_agent() -> None:
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    token, slug = await _member(tenant_id), await _slug(tenant_id)

    async with _client(_app()) as client:
        response = await client.get(
            f"/v1/agents/{agent_id}/pending",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_pending"] is True
    assert body["pending"][0]["field"] == "script"
    assert body["precedence_rule"].startswith("Script decides content")
    # Version numbers, never the script (hard rule 6).
    assert "body" not in body["pending"][0]


async def test_the_pending_view_prices_each_voice_off_the_clients_own_lots() -> None:
    """The voice picker's price column, on the read BOTH voice screens already make (D-547).

    It rides `/pending` rather than a new endpoint because that is where `voice` already
    lives — a second request and a second cache key for one screen is how the two get out
    of step. What it publishes is the rate frozen on the client's OLDEST OPEN LOT, not the
    card's: a client who bought a ₹15,000 pack pays ₹4.70, and a picker quoting today's
    card would quote a price they do not pay.

    Both tiers are always present and each carries its CLIENT-FACING label — no
    client-facing surface names a vendor as a product tier (founder, 7 Sep 2026) — sent
    from `billing/rates.voice_tier_label` rather than kept in the browser, so the two
    cannot drift into a client meeting both names. The frontend validates the set strictly
    and drops all of it if one row is malformed, which is why this asserts the whole shape
    rather than one field.
    """
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    token, slug = await _member(tenant_id), await _slug(tenant_id)
    await add_lot(tenant_id, credits_inr="3200.00", rates=PLUS, pack_id="plus")
    await add_lot(tenant_id, credits_inr="2000.00", rates=GROWTH, pack_id="growth")

    async with _client(_app()) as client:
        response = await client.get(
            f"/v1/agents/{agent_id}/pending",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    assert response.json()["voice_tier_rates"] == [
        {
            "provider": "sarvam",
            "label": "Clear",
            "inr_per_min": "4.7000",
            "further_open_lots": 1,
        },
        {
            "provider": "cartesia",
            "label": "Studio",
            "inr_per_min": "6.5000",
            "further_open_lots": 1,
        },
    ]


async def test_the_pending_view_quotes_no_rate_at_all_on_an_unfunded_wallet() -> None:
    """`null` is the answer when there is no open lot to price a minute from. The
    alternative — falling back to the card — quotes a rate the client has not bought."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    token, slug = await _member(tenant_id), await _slug(tenant_id)

    async with _client(_app()) as client:
        response = await client.get(
            f"/v1/agents/{agent_id}/pending",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    assert [row["inr_per_min"] for row in response.json()["voice_tier_rates"]] == [None, None]


async def test_the_lane_table_is_readable_and_does_not_collide_with_the_agent_route() -> None:
    tenant_id, _agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    token, slug = await _member(tenant_id), await _slug(tenant_id)

    async with _client(_app()) as client:
        response = await client.get(
            "/v1/agents/lanes",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, "mount order regressed: `lanes` was eaten by {agent_id}"
    lanes = {entry["field"]: entry["lane"] for entry in response.json()["lanes"]}
    assert lanes["script"] == "staged"
    assert lanes["voice"] == "live"
    assert response.json()["call_cap_default_s"] == 600


# --- the buttons --------------------------------------------------------------


async def test_apply_publishes_and_undo_discards_over_http() -> None:
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    admin = await _admin_token()
    base = f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}"

    async with _client(_app()) as client:
        applied = await client.post(
            f"{base}/apply", json={}, headers={"Authorization": f"Bearer {admin}"}
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] is True
        assert engine._agents[ref].system_prompt.startswith("Staged script")

        # Nothing left to apply: 200 with applied=false, not a 409. A double-clicked
        # button is the same intent, already satisfied.
        again = await client.post(
            f"{base}/apply", json={}, headers={"Authorization": f"Bearer {admin}"}
        )
        assert again.status_code == 200
        assert again.json()["applied"] is False

        undone = await client.post(f"{base}/undo", headers={"Authorization": f"Bearer {admin}"})
        assert undone.status_code == 200
        assert undone.json()["undone"] is False, "nothing was staged after the apply"


async def test_a_stale_apply_is_a_conflict_in_rfc_9457_shape() -> None:
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    admin = await _admin_token()

    async with _client(_app()) as client:
        response = await client.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/apply",
            json={"expected_version": 99},
            headers={"Authorization": f"Bearer {admin}"},
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["type"].endswith("/stale_pending_change")
    assert "code" not in problem, "RFC-9457 carries the machine code in `type`"
    assert problem["kind"] == "conflict"


async def test_the_call_cap_endpoint_refuses_zero_in_rfc_9457_shape() -> None:
    """Zero is not "unlimited". It is refused by the request model's bound before it
    reaches the service, which is a 422 `validation_failed` naming the field."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    admin = await _admin_token()

    async with _client(_app()) as client:
        response = await client.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": 0},
            headers={"Authorization": f"Bearer {admin}"},
        )

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"].endswith("/validation_failed")
    assert "code" not in problem
    assert [f["field"] for f in problem["fields"]] == ["max_call_duration_s"]


async def test_setting_a_cap_over_http_reaches_the_engine_and_quotes_the_cost() -> None:
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    admin = await _admin_token()

    async with _client(_app()) as client:
        response = await client.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": 120},
            headers={"Authorization": f"Bearer {admin}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effective_call_cap_s"] == 120
    assert body["is_platform_default"] is False
    assert body["engine_synced"] is True
    assert engine._agents[ref].max_call_duration_s == 120
    # The fast lane did not drag the staged script live.
    assert engine._agents[ref].system_prompt.startswith("Applied script")

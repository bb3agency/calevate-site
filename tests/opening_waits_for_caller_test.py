"""The opening waits for the person's "Hello" (D-871): `agents.opening_waits_for_caller`.

Default by direction at creation and in the migration's backfill, sent as ThinnestAI's
`voice.openingWaitsForCaller` on every write, reported and repaired as drift, and set per
agent through the call-handling routes with their permission, audit and live apply.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from apps.api.agents import lifecycle, prompts
from apps.api.agents.call_handling import opening_waits_default
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _load_agent, _to_config
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from sqlalchemy import text
from tests.authz_audit_test import _client as _full_client
from tests.authz_audit_test import _make_admin
from tests.call_handling_test import _client, _make_live, _runs, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.impersonation_grant_test import view_as_headers
from tests.thinnest_engine_test import WS, _cfg, tools_state

pytestmark = [pytest.mark.rls]

AGENT = f"ag_1@{WS}"
REVISION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "f4b8c1d6a273_agents_opening_waits_for_caller.py"
)


def _revision() -> ModuleType:
    """The migration loaded by path: `alembic/versions` is not a package."""
    spec = importlib.util.spec_from_file_location("opening_waits_revision", REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the default ----------------------------------------------------------------------


def test_only_an_agent_that_only_places_calls_waits_by_default() -> None:
    assert opening_waits_default("outbound") is True
    assert opening_waits_default("inbound") is False
    assert opening_waits_default("both") is False


async def test_a_new_agent_takes_the_default_of_its_direction() -> None:
    tenant_id, _agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        made = {
            direction: await lifecycle.create_agent(
                session,
                tenant_id=tenant_id,
                name=f"Agent {direction}",
                direction=direction,
                language_primary="te-IN",
            )
            for direction in ("outbound", "inbound", "both")
        }
        held = {
            direction: (
                await session.execute(
                    text("SELECT opening_waits_for_caller FROM agents WHERE id = :id"),
                    {"id": agent_id},
                )
            ).scalar_one()
            for direction, agent_id in made.items()
        }
    assert held == {"outbound": True, "inbound": False, "both": False}


async def test_the_backfill_switches_on_only_agents_that_only_place_calls() -> None:
    """The revision's own statement, run per client: its predicate, and that one client's
    run cannot reach another's rows."""
    tenant_a, agent_a, _ = await _tenant()
    tenant_b, agent_b, _ = await _tenant()
    for tenant_id, agent_id, direction in (
        (tenant_a, agent_a, "outbound"),
        (tenant_b, agent_b, "outbound"),
    ):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE agents SET direction = :d, opening_waits_for_caller = false "
                    "WHERE id = :id"
                ),
                {"d": direction, "id": agent_id},
            )
    async with tenant_session(tenant_a) as session:
        inbound = await lifecycle.create_agent(
            session, tenant_id=tenant_a, name="In", direction="inbound", language_primary="te-IN"
        )
        both = await lifecycle.create_agent(
            session, tenant_id=tenant_a, name="Both", direction="both", language_primary="te-IN"
        )
        await session.execute(text(_revision()._BACKFILL))

    async def held(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
        async with tenant_session(tenant_id) as session:
            return bool(
                (
                    await session.execute(
                        text("SELECT opening_waits_for_caller FROM agents WHERE id = :id"),
                        {"id": agent_id},
                    )
                ).scalar_one()
            )

    assert await held(tenant_a, agent_a) is True
    assert await held(tenant_a, inbound) is False
    assert await held(tenant_a, both) is False
    assert await held(tenant_b, agent_b) is False, "a client's run reached another client"


# --- ThinnestAI: body, read-back, repair -------------------------------------------------


@pytest.mark.parametrize("waits", [True, False])
def test_every_write_states_the_switch(waits: bool) -> None:
    voice = ThinnestEngine(api_key="ta_live_test")._agent_body(
        _cfg(opening_waits_for_caller=waits)
    )["voice"]
    assert voice["openingWaitsForCaller"] is waits
    # Excluded from dumps, so stored configs and their digests do not move.
    assert "opening_waits_for_caller" not in _cfg(opening_waits_for_caller=waits).model_dump()


async def test_the_drift_sweep_reports_and_repairs_the_switch() -> None:
    assert "opening_waits_for_caller" in AGENT_SETTING_LABELS
    cfg = _cfg(opening_waits_for_caller=True)
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    # A live agent published before D-871 holds the vendor default.
    held = {**wanted, "voice": {**wanted["voice"], "openingWaitsForCaller": False}}
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["opening_waits_for_caller"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {"openingWaitsForCaller": True}}]
    assert thinnest._settings_drift(wanted, wanted) == []


async def test_publish_reads_the_agents_column() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET opening_waits_for_caller = true WHERE id = :id"),
            {"id": agent_id},
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        cfg = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert cfg.opening_waits_for_caller is True


# --- the routes ---------------------------------------------------------------------------


async def test_the_owner_sets_it_it_is_audited_and_reaches_the_live_agent() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    path = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        before = await client.get(path, headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["opening_waits_for_caller"] is False
        set_on = await client.patch(path, headers=headers, json={"opening_waits_for_caller": True})
        assert set_on.status_code == 200, set_on.text
        assert set_on.json()["opening_waits_for_caller"] is True
        after = await client.get(path, headers=headers)
        assert after.json()["opening_waits_for_caller"] is True
        # A sibling change leaves it where it is.
        other = await client.patch(path, headers=headers, json={"turn_silence_ms": 700})
        assert other.json()["opening_waits_for_caller"] is True
        # It inherits nothing, so null is refused rather than read as "inherit".
        null = await client.patch(path, headers=headers, json={"opening_waits_for_caller": None})
        assert null.status_code == 422, null.text
    assert ("agent", agent_id, ["call_handling"]) in await _runs(tenant_id)
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT actor_type, object_id FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'agent.call_handling_set'"
                ),
                {"t": tenant_id},
            )
        ).all()
    # One row per save, the refused null included in none.
    assert [tuple(row) for row in audited] == [("user", str(agent_id))] * 2


async def test_staff_may_read_but_not_change_it() -> None:
    _tenant_id, agent_id, headers = await _tenant(role="staff")
    async with _client() as client:
        write = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"opening_waits_for_caller": True},
        )
    assert write.status_code == 403, write.text


async def test_one_client_cannot_move_anothers() -> None:
    tenant_a, agent_a, _ = await _tenant()
    _tenant_b, _agent_b, headers_b = await _tenant()
    async with _client() as client:
        write = await client.patch(
            f"/v1/agents/{agent_a}/call-handling",
            headers=headers_b,
            json={"opening_waits_for_caller": True},
        )
    assert write.status_code == 404, write.text
    async with tenant_session(tenant_a) as session:
        held = (
            await session.execute(
                text("SELECT opening_waits_for_caller FROM agents WHERE id = :id"), {"id": agent_a}
            )
        ).scalar_one()
    assert held is False


async def test_a_view_as_session_changes_it_as_the_operator_like_its_siblings() -> None:
    """D-587: a view-as session may make the writes its siblings may, each attributed to
    the operator and the grant, never to the client."""
    tenant_id, agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :id"), {"id": tenant_id}
            )
        ).scalar_one()
    token = await _make_admin(role="operator")
    async with _full_client() as http:
        headers = await view_as_headers(http, token, str(slug))
        read = await http.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)
        write = await http.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"opening_waits_for_caller": True},
        )
    assert read.status_code == 200, read.text
    assert write.status_code == 200, write.text
    assert write.json()["opening_waits_for_caller"] is True
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT actor_type, via_grant_id IS NOT NULL FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'agent.call_handling_set'"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert [tuple(row) for row in audited] == [("admin", True)]


async def test_an_operator_sets_it_through_the_admin_door() -> None:
    from tests.call_handling_test import _operator

    tenant_id, agent_id, _ = await _tenant()
    headers = await _operator()
    async with _client() as client:
        response = await client.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
            headers=headers,
            json={"opening_waits_for_caller": True},
        )
    assert response.status_code == 200, response.text
    assert response.json()["opening_waits_for_caller"] is True

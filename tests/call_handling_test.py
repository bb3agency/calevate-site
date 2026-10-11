"""The pause before an agent replies and hanging up when it has finished (D-751).

Storage and the agent -> organisation -> Calevate resolution, the range, the ThinnestAI body
and its read-back drift, the routes in both realms, the live apply each save queues, and
that one client cannot read or move another's.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.call_handling import (
    END_CALL_ON_FINISH_DEFAULT,
    TURN_SILENCE_DEFAULT_MS,
    resolve_end_call_on_finish,
    resolve_turn_silence,
)
from apps.api.agents.call_handling_routes import admin_router, router
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, thinnest
from apps.api.engine.thinnest import ThinnestEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import accept_agreements
from tests.thinnest_engine_test import WS, _cfg, _engine, _recorder

# --- resolution ----------------------------------------------------------------------


def test_each_setting_resolves_agent_then_account_then_calevate() -> None:
    assert resolve_turn_silence(700, 500).ms == 700
    assert resolve_turn_silence(700, 500).source == "agent"
    assert resolve_turn_silence(None, 500).source == "organization"
    platform = resolve_turn_silence(None, None)
    assert (platform.ms, platform.source) == (TURN_SILENCE_DEFAULT_MS, "platform")
    assert TURN_SILENCE_DEFAULT_MS == 250
    # False on the agent is a choice, not an absence.
    assert resolve_end_call_on_finish(False, True).enabled is False
    assert resolve_end_call_on_finish(None, False).source == "organization"
    assert resolve_end_call_on_finish(None, None).enabled is END_CALL_ON_FINISH_DEFAULT is True


# --- ThinnestAI: body, read-back, repair -------------------------------------------------


def test_the_agent_body_states_both_settings() -> None:
    voice = ThinnestEngine(api_key="ta_live_test")._agent_body(
        _cfg(turn_silence_ms=700, end_call_on_finish=False)
    )["voice"]
    assert voice["turnSilenceSeconds"] == 0.7
    assert voice["endCallOnFinish"] is False
    # Excluded from dumps, so stored configs and their digests do not move.
    assert "turn_silence_ms" not in _cfg(turn_silence_ms=700).model_dump()


@pytest.mark.parametrize(
    ("held", "drifted"),
    [
        (0.7, []),
        (0.70, []),
        (0.5, ["turn_silence"]),
        # A console reset reads back null: drift, because we always state the value.
        (None, ["turn_silence"]),
        (True, ["turn_silence"]),
    ],
)
def test_a_pause_that_differs_from_ours_is_drift(held: object, drifted: list[str]) -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(turn_silence_ms=700))
    live = {**body, "voice": {**body["voice"], "turnSilenceSeconds": held}}
    assert thinnest._settings_drift(body, live) == drifted


def test_whole_seconds_read_back_as_an_integer_match() -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(turn_silence_ms=1000))
    live = {**body, "voice": {**body["voice"], "turnSilenceSeconds": 1}}
    assert thinnest._settings_drift(body, live) == []


def test_a_hang_up_switched_in_the_vendor_console_is_drift() -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(end_call_on_finish=False))
    live = {**body, "voice": {**body["voice"], "endCallOnFinish": True}}
    assert thinnest._settings_drift(body, live) == ["end_call_on_finish"]


def test_both_labels_are_ours() -> None:
    assert {"turn_silence", "end_call_on_finish"} <= AGENT_SETTING_LABELS


async def test_a_repair_rewrites_only_the_drifted_voice_fields() -> None:
    handler, seen = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
    engine = _engine(handler)
    cfg = _cfg(turn_silence_ms=700, end_call_on_finish=False)
    await engine.repair_settings(f"ag_1@{WS}", cfg, ["turn_silence", "end_call_on_finish"])
    patch = next(r for r in seen if r.method == "PATCH")
    assert json.loads(patch.content) == {
        "voice": {"turnSilenceSeconds": 0.7, "endCallOnFinish": False}
    }


async def test_the_read_back_reports_and_the_sweep_repairs() -> None:
    cfg = _cfg(turn_silence_ms=700)
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    held = {**body, "id": "ag_1", "voice": {**body["voice"], "turnSilenceSeconds": None}}
    handler, _seen = _recorder({("GET", "/agents/ag_1"): httpx.Response(200, json=held)})
    assert await _engine(handler).settings_drift(f"ag_1@{WS}", cfg) == ["turn_silence"]


# --- storage, routes and live apply ---------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    application.include_router(admin_router)
    assert_policy_registry_complete(application)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
    created = await admin_service.create_organization(
        name="Call Handling Store",
        slug=f"ch-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
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
    return tenant_id, agent_id, {"Authorization": f"Bearer dev:client:{user_id}"}


async def _operator() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _make_live(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', engine_agent_ref = :ref WHERE id = :aid"),
            {"ref": f"fake-{agent_id}", "aid": agent_id},
        )


async def _runs(tenant_id: uuid.UUID) -> list[tuple[str, uuid.UUID | None, list[str]]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scope, agent_id, reasons FROM live_apply_runs "
                    "WHERE tenant_id = :tid AND status = 'pending' ORDER BY created_at"
                ),
                {"tid": tenant_id},
            )
        ).all()
    return [(str(r[0]), r[1], list(r[2])) for r in rows]


async def test_the_columns_hold_the_vendor_range_and_null_inherits() -> None:
    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.turn_silence_ms, a.end_call_on_finish, o.default_turn_silence_ms, "
                    "o.default_end_call_on_finish FROM agents a JOIN organizations o "
                    "ON o.id = a.tenant_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()
    assert tuple(row) == (None, None, None, None)
    for table, column, where in (
        ("agents", "turn_silence_ms", "id = :id"),
        ("organizations", "default_turn_silence_ms", "id = :id"),
    ):
        for bad in (199, 3001):
            with pytest.raises(IntegrityError):
                async with tenant_session(tenant_id) as session:
                    await session.execute(
                        text(f"UPDATE {table} SET {column} = :v WHERE {where}"),
                        {"v": bad, "id": agent_id if table == "agents" else tenant_id},
                    )


async def test_the_published_config_resolves_each_level() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )

    async def config() -> tuple[int, bool]:
        async with tenant_session(tenant_id) as session:
            row = await _load_agent(session, tenant_id, agent_id)
        cfg = _to_config(tenant_id, row, engine=get_engine())
        return cfg.turn_silence_ms, cfg.end_call_on_finish

    assert await config() == (250, True)
    async with _client() as client:
        put = await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": 500, "end_call_on_finish": False},
        )
        assert put.status_code == 200, put.text
        assert await config() == (500, False)
        patched = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"turn_silence_ms": 700},
        )
        assert patched.status_code == 200, patched.text
    assert await config() == (700, False)


async def test_the_routes_say_where_each_value_comes_from() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        first = await client.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)
        assert first.status_code == 200, first.text
        got = first.json()
        assert got["turn_silence_ms"] is None
        assert got["turn_silence_ms_effective"] == 250
        assert got["turn_silence_source"] == "platform"
        assert got["end_call_on_finish_effective"] is True
        assert got["end_call_on_finish_source"] == "platform"
        assert got["bounds"] == {
            "turn_silence_min_ms": 200,
            "turn_silence_max_ms": 3000,
            "platform_turn_silence_ms": 250,
            "platform_end_call_on_finish": True,
        }

        org = await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": 500, "end_call_on_finish": None},
        )
        assert org.status_code == 200, org.text
        assert org.json()["turn_silence_ms_effective"] == 500
        inherited = (
            await client.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)
        ).json()
        assert inherited["turn_silence_source"] == "organization"
        assert inherited["organization_turn_silence_ms"] == 500

        own = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"end_call_on_finish": False},
        )
        assert own.json()["end_call_on_finish"] is False
        assert own.json()["end_call_on_finish_source"] == "agent"
        # A field left out is untouched.
        assert own.json()["turn_silence_source"] == "organization"

        cleared = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"end_call_on_finish": None},
        )
        assert cleared.json()["end_call_on_finish_source"] == "platform"

        org_read = await client.get("/v1/organization/call-handling", headers=headers)
        assert org_read.json()["turn_silence_ms"] == 500
    async with untenanted_session() as session:
        actions = set(
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            ).scalars()
        )
    assert {"agent.call_handling_set", "organization.call_handling_set"} <= actions


@pytest.mark.parametrize("bad", [199, 3001, 0])
async def test_a_pause_out_of_range_is_refused_as_problem_json(bad: int) -> None:
    _tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        for method, path, body in (
            ("PATCH", f"/v1/agents/{agent_id}/call-handling", {"turn_silence_ms": bad}),
            (
                "PUT",
                "/v1/organization/call-handling",
                {"turn_silence_ms": bad, "end_call_on_finish": None},
            ),
        ):
            response = await client.request(method, path, headers=headers, json=body)
            assert response.status_code == 422, response.text
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["type"].endswith("/turn_silence_out_of_range")


async def test_staff_may_read_but_not_change_them() -> None:
    _tenant_id, agent_id, headers = await _tenant(role="staff")
    async with _client() as client:
        read = await client.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)
        assert read.status_code == 200, read.text
        write = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"end_call_on_finish": False},
        )
        assert write.status_code == 403, write.text


async def test_an_agent_change_queues_its_live_apply_and_a_repeat_does_not() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        draft = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"turn_silence_ms": 700},
        )
        assert draft.status_code == 200
        # Not live: nothing to apply.
        assert await _runs(tenant_id) == []
        await _make_live(tenant_id, agent_id)
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"end_call_on_finish": False},
        )
        assert await _runs(tenant_id) == [("agent", agent_id, ["call_handling"])]
        # The same values again move nothing and queue nothing more.
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"turn_silence_ms": 700, "end_call_on_finish": False},
        )
        assert len(await _runs(tenant_id)) == 1


async def test_an_account_default_queues_the_client_only_when_a_live_agent_inherits() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    async with _client() as client:
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"turn_silence_ms": 700},
        )
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE live_apply_runs SET status = 'superseded' WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        # The agent has its own pause, so the account's moves no line.
        await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": 500, "end_call_on_finish": None},
        )
        assert await _runs(tenant_id) == []
        # It inherits the hang-up, so switching that off moves it.
        await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": 500, "end_call_on_finish": False},
        )
        assert await _runs(tenant_id) == [("tenant", None, ["call_handling"])]


async def test_one_client_cannot_read_or_move_anothers() -> None:
    _tenant_a, agent_a, _ = await _tenant()
    tenant_b, _agent_b, headers_b = await _tenant()
    async with _client() as client:
        read = await client.get(f"/v1/agents/{agent_a}/call-handling", headers=headers_b)
        assert read.status_code == 404, read.text
        write = await client.patch(
            f"/v1/agents/{agent_a}/call-handling",
            headers=headers_b,
            json={"end_call_on_finish": False},
        )
        assert write.status_code == 404, write.text
    async with tenant_session(_tenant_a) as session:
        held = (
            await session.execute(
                text("SELECT end_call_on_finish FROM agents WHERE id = :aid"), {"aid": agent_a}
            )
        ).scalar()
    assert held is None
    # Under B's scope A's agent row is invisible.
    async with tenant_session(tenant_b) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM agents WHERE id = :aid"), {"aid": agent_a}
            )
        ).scalar()
    assert seen == 0


async def test_an_operator_reads_and_sets_both_levels() -> None:
    tenant_id, agent_id, _ = await _tenant()
    headers = await _operator()
    async with _client() as client:
        org = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-handling",
            headers=headers,
            json={"turn_silence_ms": 700, "end_call_on_finish": True},
        )
        assert org.status_code == 200, org.text
        agent = await client.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
            headers=headers,
            json={"end_call_on_finish": False},
        )
        assert agent.status_code == 200, agent.text
        read = await client.get(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling", headers=headers
        )
        assert read.json()["turn_silence_source"] == "organization"
        assert read.json()["end_call_on_finish_effective"] is False
        org_read = await client.get(
            f"/v1/admin/organizations/{tenant_id}/call-handling", headers=headers
        )
        assert org_read.json()["turn_silence_ms"] == 700
        missing = await client.get(
            f"/v1/admin/tenants/{uuid.uuid4()}/agents/{agent_id}/call-handling", headers=headers
        )
        assert missing.status_code == 404

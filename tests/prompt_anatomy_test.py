"""What the agent is told, by layer, for the operator console (D-882)."""

from __future__ import annotations

import uuid
from typing import get_args

from apps.api.agents import prompts
from apps.api.agents.prompt_anatomy import LAYER_GUIDE
from apps.api.agents.prompt_routes import router
from apps.api.core.auth import ADMIN_TENANT_READ_ACTION
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session
from calevate_shared.engine import LAYER_SEPARATOR, PromptLayer, compose_engine_prompt
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.call_handling_test import _operator, _tenant

SCRIPT = "Greet the caller warmly and take their order for the bakery."


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


def _path(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt/layers"


async def _with_script(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )


def test_every_layer_has_an_owner_and_a_purpose() -> None:
    assert set(LAYER_GUIDE) == set(get_args(PromptLayer))
    assert all(guide.purpose for guide in LAYER_GUIDE.values())


async def test_the_layers_join_into_exactly_what_a_publish_sends() -> None:
    from apps.api.agents.prompt_size import publish_config
    from apps.api.engine import get_engine

    tenant_id, agent_id, _headers = await _tenant()
    await _with_script(tenant_id, agent_id)
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=await _operator())
    assert got.status_code == 200, got.text
    body = got.json()
    async with tenant_session(tenant_id) as session:
        cfg = await publish_config(
            session, tenant_id=tenant_id, agent_id=agent_id, engine=get_engine()
        )
    layers = body["layers"]
    assert LAYER_SEPARATOR.join(layer["text"] for layer in layers) == compose_engine_prompt(cfg)
    assert all(layer["chars"] == len(layer["text"]) for layer in layers)
    assert body["total_chars"] == sum(x["chars"] for x in layers) + body["separator_chars"]
    keys = [layer["key"] for layer in layers]
    assert keys[0] == "preamble" and "truthful_answers" in keys
    [script] = [layer for layer in layers if layer["key"] == "client_script"]
    assert SCRIPT in script["text"]
    assert (script["owner"], script["title"]) == ("client", "The client's script")
    assert body["has_script"] is True
    # Never checked by the sweep, and no engine object yet.
    assert (body["on_engine"], body["drift_state"], body["drift_checked_at"]) == (
        False,
        None,
        None,
    )


async def test_the_last_sweep_verdict_on_the_agents_own_object_is_shown() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    await _with_script(tenant_id, agent_id)
    ref = f"fake_layers_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"), {"r": ref, "a": agent_id}
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, drift_state, drift_checked_at, created_at, updated_at) "
                "VALUES ('fake', :r, :t, :a, true, 'applied', now(), now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=await _operator())
    body = got.json()
    assert (body["on_engine"], body["drift_state"]) == (True, "applied")
    assert body["drift_checked_at"] is not None


async def test_an_agent_with_nothing_written_answers_empty_not_an_error() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET system_prompt_id = NULL, live_prompt_id = NULL WHERE id = :a"),
            {"a": agent_id},
        )
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=await _operator())
    assert got.status_code == 200, got.text
    assert (got.json()["has_script"], got.json()["layers"]) == (False, [])


async def test_the_read_is_recorded_in_the_tenants_audit_ledger() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    await _with_script(tenant_id, agent_id)
    async with _client() as client:
        await client.get(_path(tenant_id, agent_id), headers=await _operator())
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :tid AND action = :action"),
                {"tid": tenant_id, "action": ADMIN_TENANT_READ_ACTION},
            )
        ).scalar_one()
    assert rows >= 1


async def test_a_client_cannot_reach_it() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _with_script(tenant_id, agent_id)
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=headers)
    assert got.status_code in (401, 403)


async def test_another_clients_agent_under_this_tenant_is_not_found() -> None:
    tenant_a, _agent_a, _ = await _tenant()
    tenant_b, agent_b, _ = await _tenant()
    await _with_script(tenant_b, agent_b)
    async with _client() as client:
        got = await client.get(_path(tenant_a, agent_b), headers=await _operator())
    assert got.status_code == 404, got.text
    assert SCRIPT not in got.text

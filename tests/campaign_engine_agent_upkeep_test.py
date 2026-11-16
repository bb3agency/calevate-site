"""A campaign's own engine agent follows the campaign while it runs, and goes when it ends (D-1003).

1. A campaign that completes gives its engine agent back in the completing transaction, as
   Stop does, so the workspace's allowance is free for the next Start at once.
2. A script saved on a running (or paused) campaign is put live on its engine agent, as a
   settings or notes save is: Resume does not republish, so nothing else would.
3. A campaign without a script of its own whose setting overrides are all cleared while it
   runs has its engine agent republished on the agent's defaults, not left on the old ones.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns.workspace_routes import router as workspace_router
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session
from apps.workers.campaign_dispatch import _settle_finished_campaign
from calevate_shared.call_script import CallScript
from fastapi import FastAPI
from sqlalchemy import text
from tests.agent_lifecycle_test import _client, _fresh_engine, _move, _tenant, _write_script
from tests.campaign_engine_agents_test import _campaign, _publish

pytestmark = pytest.mark.rls

NEW = CallScript(opening_line="Namaste, Lifecycle Clinic here about the Sunday camp.")


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(workspace_router)
    assert_policy_registry_complete(application)
    return application


async def _live_agent_and_token() -> tuple[UUID, UUID, str]:
    tenant_id, agent_id, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both' WHERE id = :a"), {"a": agent_id}
        )
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    return tenant_id, agent_id, token


async def _put(token: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    async with _client(_app()) as http:
        response = await http.put(path, json=body, headers={"Authorization": f"Bearer {token}"})
    return response.status_code, response.json()


async def test_a_completed_campaign_gives_its_engine_agent_back_as_it_completes() -> None:
    _fresh_engine()
    tenant_id, agent_id, _token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        # No contact left to dial: the run is over.
        assert await _settle_finished_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    async with tenant_session(tenant_id) as session:
        status, held = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = 'retire_moved_engine_agent' "
                    "AND payload->>'old_ref' = :r"
                ),
                {"r": ref},
            )
        ).scalar_one()
    assert status == "completed"
    assert held is None, "a completed campaign kept its engine agent until the hourly sweep"
    assert owed == 1


async def test_a_script_saved_on_a_running_campaign_reaches_its_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)
    assert "Sunday camp" not in engine._agents[ref].system_prompt

    code, body = await _put(
        token, f"/v1/campaigns/{campaign_id}/script", {"script": NEW.model_dump(mode="json")}
    )

    assert code == 200, body
    assert "Sunday camp" in engine._agents[ref].system_prompt, (
        "the running campaign kept calling with the script from before the save"
    )


async def test_a_script_saved_on_a_draft_waits_for_its_start() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id)
    before = set(engine._agents)

    code, body = await _put(
        token, f"/v1/campaigns/{campaign_id}/script", {"script": NEW.model_dump(mode="json")}
    )

    assert code == 200, body
    assert set(engine._agents) == before, "a draft's save made an engine agent"


async def test_clearing_every_override_of_a_running_campaign_republishes_its_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(
        tenant_id, agent_id, script=None, status="running", overrides={"max_call_duration_s": 300}
    )
    ref = await _publish(tenant_id, campaign_id)
    assert engine._agents[ref].max_call_duration_s == 300

    code, body = await _put(token, f"/v1/campaigns/{campaign_id}/settings", {})

    assert code == 200, body
    assert engine._agents[ref].max_call_duration_s != 300, (
        "the cleared override stayed on the running campaign's calls"
    )

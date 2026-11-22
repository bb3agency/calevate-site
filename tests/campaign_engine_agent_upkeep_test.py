"""A campaign's own engine agent follows the campaign while it runs, and goes when it ends (D-1003).

1. A campaign that completes gives its engine agent back in the completing transaction, as
   Stop does, so the workspace's allowance is free for the next Start at once.
2. A script saved on a running (or paused) campaign is put live on its engine agent, as a
   settings or notes save is: Resume does not republish, so nothing else would.
3. A campaign without a script of its own whose setting overrides are all cleared while it
   runs has its engine agent republished on the agent's defaults, not left on the old ones.
4. A "What it notes" save the platform refused to put live is kept, and pressing Save again
   puts it live: the list the editor still shows is already stored, so the retry is neither a
   conflict nor a no-op that skips the publish.
5. Putting back the script from before Pip's draft reaches a running campaign's calls the
   same way, and a refused put-live keeps the restore.
6. Keeping Pip's draft settles it in the save's own transaction, so a refused put-live does
   not leave it standing; a draft the campaign does not hold refuses the whole save.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns import notes, workspace_routes
from apps.api.campaigns.workspace_routes import router as workspace_router
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.campaign_dispatch import _settle_finished_campaign
from calevate_shared.call_script import CallScript
from calevate_shared.extraction import ExtractionField
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
        tenant_id, agent_id, script=None, status="running", overrides={"language_primary": "hi-IN"}
    )
    ref = await _publish(tenant_id, campaign_id)
    assert engine._agents[ref].language_primary == "hi-IN"

    code, body = await _put(token, f"/v1/campaigns/{campaign_id}/settings", {})

    assert code == 200, body
    assert engine._agents[ref].language_primary != "hi-IN", (
        "the cleared override stayed on the running campaign's calls"
    )


async def test_saving_what_it_notes_again_puts_a_refused_save_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    await _publish(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        shown = await notes.read_notes(session, "campaign", campaign_id)
    real = workspace_routes.put_campaign_live
    tries: list[UUID] = []

    async def platform_refuses_once(
        *, tenant_id: UUID, campaign_id: UUID, require_holding: bool = False
    ) -> str | None:
        tries.append(campaign_id)
        if len(tries) == 1:
            raise ProblemError.business_rule(
                "engine_unavailable", "The calling platform did not answer."
            )
        return await real(
            tenant_id=tenant_id, campaign_id=campaign_id, require_holding=require_holding
        )

    monkeypatch.setattr(workspace_routes, "put_campaign_live", platform_refuses_once)
    field = ExtractionField(key="visit_day", label="Visit day", type="text")
    # The editor sends the digest of the list it was showing, on both presses.
    body = {"fields": [field.model_dump(mode="json")], "expected_digest": shown.digest}
    path = f"/v1/campaigns/{campaign_id}/notes"

    code, refused = await _put(token, path, body)
    assert code != 200 and refused["title"] == "Saved, but not on its calls yet", refused

    code, again = await _put(token, path, body)

    assert code == 200, again
    assert len(tries) == 2, "Save again did not put the kept list on the campaign's calls"
    assert [f["key"] for f in again["fields"]] == ["visit_day"]


async def _post(token: str, path: str) -> tuple[int, dict[str, Any]]:
    async with _client(_app()) as http:
        response = await http.post(path, headers={"Authorization": f"Bearer {token}"})
    return response.status_code, response.json()


async def _hold_before_pip(tenant_id: UUID, campaign_id: UUID, script: CallScript) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET script_before_pip = CAST(:s AS jsonb), "
                "script_before_pip_at = now() WHERE id = :c"
            ),
            {"s": script.model_dump_json(), "c": campaign_id},
        )


async def _draft(tenant_id: UUID, campaign_id: UUID) -> UUID:
    draft_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script_proposal = CAST(:p AS jsonb) WHERE id = :c"),
            {"p": json.dumps({"id": str(draft_id), "status": "ready"}), "c": campaign_id},
        )
    return draft_id


async def _stored(tenant_id: UUID, campaign_id: UUID) -> tuple[Any, Any]:
    async with tenant_session(tenant_id) as session:
        script, proposal = (
            await session.execute(
                text("SELECT script, script_proposal FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()
    return script, proposal


async def _platform_refuses(
    *, tenant_id: UUID, campaign_id: UUID, require_holding: bool = False
) -> str | None:
    raise ProblemError.business_rule("engine_unavailable", "The calling platform did not answer.")


async def test_putting_back_the_script_before_pip_reaches_a_running_campaigns_calls() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)
    await _hold_before_pip(tenant_id, campaign_id, NEW)
    assert "Sunday camp" not in engine._agents[ref].system_prompt

    code, body = await _post(token, f"/v1/campaigns/{campaign_id}/script/restore-before-pip")

    assert code == 200, body
    assert "Sunday camp" in engine._agents[ref].system_prompt, (
        "the running campaign kept calling with Pip's script after the owner put theirs back"
    )


async def test_a_restore_whose_put_live_is_refused_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="paused")
    await _publish(tenant_id, campaign_id)
    await _hold_before_pip(tenant_id, campaign_id, NEW)
    monkeypatch.setattr(workspace_routes, "put_campaign_live", _platform_refuses)

    code, refused = await _post(token, f"/v1/campaigns/{campaign_id}/script/restore-before-pip")

    assert code != 200 and refused["title"] == "Saved, but not on its calls yet", refused
    script, _ = await _stored(tenant_id, campaign_id)
    assert script["opening_line"] == NEW.opening_line, "the refused put-live undid the restore"


async def test_keeping_pips_draft_settles_it_even_when_its_put_live_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    await _publish(tenant_id, campaign_id)
    draft_id = await _draft(tenant_id, campaign_id)
    monkeypatch.setattr(workspace_routes, "put_campaign_live", _platform_refuses)

    code, refused = await _put(
        token,
        f"/v1/campaigns/{campaign_id}/script",
        {"script": NEW.model_dump(mode="json"), "proposal_id": str(draft_id)},
    )

    assert code != 200 and refused["title"] == "Saved, but not on its calls yet", refused
    script, proposal = await _stored(tenant_id, campaign_id)
    assert script["opening_line"] == NEW.opening_line
    assert proposal is None, "the kept draft stood over the saved script after a refused put-live"


async def test_a_save_naming_a_draft_this_campaign_does_not_hold_is_refused_whole() -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent_and_token()
    campaign_id = await _campaign(tenant_id, agent_id)
    draft_id = await _draft(tenant_id, campaign_id)
    other = await _campaign(tenant_id, agent_id)
    elsewhere = await _draft(tenant_id, other)

    code, body = await _put(
        token,
        f"/v1/campaigns/{campaign_id}/script",
        {"script": NEW.model_dump(mode="json"), "proposal_id": str(elsewhere)},
    )

    assert code == 404, body
    script, proposal = await _stored(tenant_id, campaign_id)
    assert script["opening_line"] != NEW.opening_line, "the refused save still stored its script"
    assert proposal["id"] == str(draft_id)
    _, untouched = await _stored(tenant_id, other)
    assert untouched["id"] == str(elsewhere), "a save settled another campaign's draft"

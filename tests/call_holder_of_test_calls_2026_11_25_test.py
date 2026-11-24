"""Which job a call was spoken from, for the paths that act on the call's script (D-1019,
D-1028): a campaign's Test call is kept out of `calls.campaign_id` and found through
`campaigns.test_call_ids`; a campaign's call-back placed through a line carries both ids and
was spoken from the line's script.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.agents import call_mistakes
from apps.api.campaigns.notes import call_job
from apps.api.crm.step_progress import holder_script
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from calevate_shared.call_script import CallScript, ConversationStage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.healer_call_mistake_fix_2026_11_12_test import (
    KIND,
    _agent,
    _campaign,
    _line,
    _repair_queued,
    _settings,  # noqa: F401  (autouse: the healer on, its playbooks live)
    _step,
)

pytestmark = [pytest.mark.rls]


def _named(stage: str) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Namaste, this is Asha from Sunrise Homes.",
        stages=[
            ConversationStage(id=stage, name=stage.title(), instruction="Ask what they need."),
            ConversationStage(id="close", name="Close", instruction="Thank them and end the call."),
        ],
    )


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
    tested_campaign: UUID | None = None,
) -> tuple[UUID, datetime]:
    started = datetime.now(UTC) - timedelta(minutes=5)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, inbound_line_id, campaign_id, paid_test_call, created_at, "
                "updated_at) VALUES (:id, :t, :a, :e, 'outbound', 'completed', :s, :line, "
                ":campaign, :test, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"x_{call_id.hex}",
                "s": started,
                "line": line_id,
                "campaign": campaign_id,
                "test": tested_campaign is not None,
            },
        )
        if tested_campaign is not None:
            await session.execute(
                text(
                    "UPDATE campaigns SET test_call_ids = array_append(test_call_ids, :call) "
                    "WHERE id = :c"
                ),
                {"call": call_id, "c": tested_campaign},
            )
    return call_id, started


async def test_a_mistake_on_a_campaigns_test_call_is_repaired_on_that_campaign() -> None:
    """FAILS IF: a mistake heard on a campaign's Test call is settled as "on no Inbound line or
    campaign" because the test call is not in `calls.campaign_id`."""
    tenant_id, agent_id = await _agent("testcall")
    campaign_id = await _campaign(tenant_id, agent_id)
    call_id, started = await _call(tenant_id, agent_id, tested_campaign=campaign_id)
    await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        call_started_at=started,
        found={KIND: 0},
    )
    fix = await _step(tenant_id, agent_id)
    assert (fix.campaign_id, fix.inbound_line_id) == (campaign_id, None)
    assert fix.ended_because != "no_job"
    assert await _repair_queued(tenant_id, "campaign", campaign_id)


async def test_the_call_page_reads_a_test_calls_repair_on_the_campaign_it_tested() -> None:
    """FAILS IF: "What went wrong" on a campaign's Test call says "Our team has been told"
    while the campaign's script has been repaired of that mistake."""
    tenant_id, agent_id = await _agent("testpage", pip_on=False)
    campaign_id = await _campaign(tenant_id, agent_id)
    call_id, started = await _call(tenant_id, agent_id, tested_campaign=campaign_id)
    await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        call_started_at=started,
        found={"said_again": 0},
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script_heal_fixed = CAST(:f AS jsonb) WHERE id = :c"),
            {"f": json.dumps({"said_again": datetime.now(UTC).isoformat()}), "c": campaign_id},
        )
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        mistakes = (await http.get(f"/v1/calls/{call_id}", headers=headers)).json()["mistakes"]
    assert [(m["kind"], m["fix"]) for m in mistakes] == [("said_again", "repaired")]


async def test_a_campaign_call_back_through_a_line_is_read_against_the_lines_script() -> None:
    """FAILS IF: a campaign's call-back that rang through a line's engine agent is read
    against the campaign's steps, or its repair state is read on the campaign, while the
    caller heard the line's script and the fix goes to the line."""
    tenant_id, agent_id = await _agent("callback", pip_on=False)
    campaign_id = await _campaign(tenant_id, agent_id, _named("visit"))
    line_id = await _line(tenant_id, agent_id, _named("desk"))
    call_id, started = await _call(tenant_id, agent_id, line_id=line_id, campaign_id=campaign_id)
    async with tenant_session(tenant_id) as session:
        script = await holder_script(session, call_id)
    assert script is not None and script.stages[0].id == "desk"
    await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        call_started_at=started,
        found={"said_again": 0},
    )
    fixed = json.dumps({"said_again": datetime.now(UTC).isoformat()})
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_heal_fixed = CAST(:f AS jsonb) WHERE id = :h"),
            {"f": fixed, "h": line_id},
        )
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        mistakes = (await http.get(f"/v1/calls/{call_id}", headers=headers)).json()["mistakes"]
    assert [(m["kind"], m["fix"]) for m in mistakes] == [("said_again", "repaired")]


async def test_call_job_names_the_campaign_a_test_call_tested() -> None:
    tenant_id, agent_id = await _agent("job", pip_on=False)
    campaign_id = await _campaign(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    tested, _ = await _call(tenant_id, agent_id, tested_campaign=campaign_id)
    on_line, _ = await _call(tenant_id, agent_id, line_id=line_id)
    bare, _ = await _call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert await call_job(session, tested) == ("campaign", campaign_id)
        assert await call_job(session, on_line) == ("line", line_id)
        assert await call_job(session, bare) is None

"""The first run on the new model (Phase 3b): the agent is staff, the work holds the script.

1. "About your business": the owner's words become the company training's overview, until a
   training is saved.
2. "Name and voice": the agent is made with no script of its own, its AI notice is switched
   on by a job, and Pip's training is asked for with `auto_save`.
3. "What first?": a draft inbound line (no number) or a draft campaign, its main task the
   owner's words, Pip's script asked for with `auto_save`; the agent takes the work's
   direction while it is a draft.
4. Pip's drafts asked for with `auto_save` are saved at once while the holder has none, and
   never over what the owner saved.

Every case makes its own tenant; no model is reached.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.agents import company_training
from apps.api.agents.default_agent import read_default_agent
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import routes as first_run_routes
from apps.api.first_run import work
from apps.api.first_run.names import FIRST_AGENT_NAME
from apps.api.first_run.work import NOTICE_JOB
from apps.api.inbound import lines
from apps.workers import campaign_script
from apps.workers import company_training_draft as training_worker
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.first_run_test import LONG_BRIEF, _client, _owner, _tenant

SCRIPT = CallScript(opening_line="Namaste, Madhav Homes. How can I help?")


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(_tenant_id: uuid.UUID, _language: str) -> None:
        return None

    monkeypatch.setattr(first_run_routes, "pick_voice", _none)


async def _one(tenant_id: uuid.UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _outbox(job: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT payload FROM outbox_messages WHERE job = :j AND payload->>'tenant_id' = :t"
            ),
            {"j": job, "t": str(tenant_id)},
        )
        return [dict(r[0]) for r in rows.all()]


async def _made(tenant_id: uuid.UUID, headers: dict[str, str]) -> dict[str, Any]:
    async with _client() as http:
        brief = await http.put("/v1/first-run/brief", headers=headers, json={"brief": LONG_BRIEF})
        assert brief.status_code == 200, brief.text
        made = await http.put(
            "/v1/first-run/agent",
            headers=headers,
            json={"name": "Anjali", "language_primary": "te-IN", "languages_extra": ["en-IN"]},
        )
    assert made.status_code == 200, made.text
    body: dict[str, Any] = made.json()
    return body


async def test_the_default_agent_is_todays_starter() -> None:
    async with untenanted_session() as session:
        default = await read_default_agent(session)
    assert (default.name, default.voice_id, default.gender) == (FIRST_AGENT_NAME, None, "female")


async def test_the_owners_words_become_the_training_overview_until_one_is_saved() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        await http.put("/v1/first-run/brief", headers=headers, json={"brief": LONG_BRIEF})
    async with tenant_session(tenant_id) as session:
        assert (await company_training.read_training(session, tenant_id)).overview == LONG_BRIEF
        await company_training.save_training(session, tenant_id, "Be kind.", saved_by=None)
    async with _client() as http:
        await http.put("/v1/first-run/brief", headers=headers, json={"brief": "Something else"})
    async with tenant_session(tenant_id) as session:
        assert (await company_training.read_training(session, tenant_id)).overview == LONG_BRIEF


async def test_name_and_voice_makes_an_agent_with_no_script_and_asks_for_the_training() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    body = await _made(tenant_id, headers)
    assert body["default_agent"] == {"name": FIRST_AGENT_NAME, "voice_id": None, "gender": "female"}
    agent_id = uuid.UUID(body["agent_id"])
    agent = await _one(
        tenant_id,
        "SELECT name, direction, status, system_prompt_id, languages_extra FROM agents "
        "WHERE id = :a",
        a=agent_id,
    )
    assert (agent.name, agent.direction, agent.status) == ("Anjali", "inbound", "draft")
    assert agent.system_prompt_id is None, "the agent has no script of its own"
    assert agent.languages_extra == ["en-IN"]
    assert await _outbox(NOTICE_JOB, tenant_id) == [
        {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    ]
    async with tenant_session(tenant_id) as session:
        training = await company_training.read_training(session, tenant_id)
        record = (
            await session.execute(text("SELECT proposal FROM company_trainings"))
        ).scalar_one()
    assert training.proposal is not None and training.proposal.status == "drafting"
    assert record["auto_save"] is True

    async with _client() as http:
        renamed = await http.put(
            "/v1/first-run/agent",
            headers=headers,
            json={"name": "Priya", "language_primary": "te-IN", "languages_extra": []},
        )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["agent_id"] == str(agent_id), "the same agent, renamed"
    assert (await _one(tenant_id, "SELECT name FROM agents WHERE id = :a", a=agent_id)).name == (
        "Priya"
    )
    assert len(await _outbox(NOTICE_JOB, tenant_id)) == 1


async def test_what_first_drafts_a_line_with_no_number_and_pip_writes_it() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    body = await _made(tenant_id, headers)
    async with _client() as http:
        drafted = await http.post(
            "/v1/first-run/work", headers=headers, json={"job": "answer_calls"}
        )
        again = await http.post("/v1/first-run/work", headers=headers, json={"job": "answer_calls"})
    assert drafted.status_code == 200, drafted.text
    line_id = drafted.json()["line_id"]
    assert line_id is not None and again.json()["line_id"] == line_id
    assert drafted.json()["jobs"] == ["answer_calls"]
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, uuid.UUID(line_id))
        record = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
        count = (await session.execute(text("SELECT count(*) FROM inbound_lines"))).scalar()
    assert count == 1, "a second press drafts nothing more"
    assert line.main_task == LONG_BRIEF and line.numbers == () and not line.live
    assert str(line.agent_id) == body["agent_id"]
    assert record["status"] == "drafting" and record["auto_save"] is True


async def test_call_people_drafts_a_campaign_and_the_agent_places_calls() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    body = await _made(tenant_id, headers)
    async with _client() as http:
        drafted = await http.post("/v1/first-run/work", headers=headers, json={"job": "call_leads"})
    assert drafted.status_code == 200, drafted.text
    campaign_id = drafted.json()["campaign_id"]
    campaign = await _one(
        tenant_id,
        "SELECT name, status, main_task, agent_id, script_proposal FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert (campaign.name, campaign.status) == (work.FIRST_CAMPAIGN_NAME, "draft")
    assert campaign.main_task == LONG_BRIEF and str(campaign.agent_id) == body["agent_id"]
    assert campaign.script_proposal["auto_save"] is True
    direction = await _one(
        tenant_id, "SELECT direction FROM agents WHERE id = :a", a=body["agent_id"]
    )
    assert direction.direction == "outbound"


async def test_what_first_before_a_name_is_refused() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        refused = await http.post("/v1/first-run/work", headers=headers, json={"job": "call_leads"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/first_run_no_agent")


async def _drafted_line(tenant_id: uuid.UUID, headers: dict[str, str]) -> uuid.UUID:
    await _made(tenant_id, headers)
    async with _client() as http:
        drafted = await http.post(
            "/v1/first-run/work", headers=headers, json={"job": "answer_calls"}
        )
    return uuid.UUID(drafted.json()["line_id"])


async def _written(tenant_id: uuid.UUID, line_id: uuid.UUID) -> None:
    """What the writer's last step does with a ready draft."""
    async with tenant_session(tenant_id) as session:
        record = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
        holder = campaign_script._line(tenant_id, line_id, uuid.UUID(record["id"]))
        await campaign_script._store(session, holder, {"status": "ready"})
        await campaign_script._save_if_asked(session, holder, SCRIPT)


async def test_a_draft_asked_to_save_becomes_the_lines_script_at_once() -> None:
    tenant_id = await _tenant()
    line_id = await _drafted_line(tenant_id, await _owner(tenant_id))
    await _written(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script == SCRIPT and line.proposal is None and line.version == 1


async def test_a_draft_never_replaces_a_script_the_owner_saved() -> None:
    tenant_id = await _tenant()
    line_id = await _drafted_line(tenant_id, await _owner(tenant_id))
    own = CallScript(opening_line="Hello, this is Madhav Homes.")
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, own)
    await _written(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script == own and line.proposal is not None, "kept for the owner to review"


@pytest.mark.parametrize("saved_before", [False, True])
async def test_the_first_runs_training_is_saved_as_version_one(saved_before: bool) -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await company_training.save_overview(session, tenant_id, LONG_BRIEF)
        if saved_before:
            await company_training.save_training(session, tenant_id, "The owner's.", saved_by=None)
        proposal = await company_training.request_proposal(
            session, tenant_id=tenant_id, requested_by=None, auto_save=True
        )
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = proposal || CAST(:u AS jsonb) "
                "WHERE tenant_id = :t"
            ),
            {"u": json.dumps({"status": "ready", "training": "Pip's."}), "t": tenant_id},
        )
        await training_worker._save_if_asked(session, tenant_id, proposal.id, "Pip's.")
    async with tenant_session(tenant_id) as session:
        training = await company_training.read_training(session, tenant_id)
    if saved_before:
        assert (training.training, training.version) == ("The owner's.", 1)
        assert training.proposal is not None
    else:
        assert (training.training, training.version, training.proposal) == ("Pip's.", 1, None)

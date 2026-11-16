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
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import company_training
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import routes as first_run_routes
from apps.api.first_run import work
from apps.api.first_run.work import NOTICE_JOB
from apps.api.inbound import lines
from apps.workers import campaign_script
from apps.workers import company_training_draft as training_worker
from calevate_shared.call_script import CallScript
from calevate_shared.config import Settings
from sqlalchemy import text
from tests.first_run_test import LONG_BRIEF, _client, _owner, _tenant

SCRIPT = CallScript(opening_line="Namaste, Madhav Homes. How can I help?")


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(_tenant_id: uuid.UUID, _language: str, **_kw: object) -> None:
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
    assert body["default_agent"] == {
        "name": Settings.model_fields["default_agent_name"].default,
        "voice_id": None,
        "gender": "female",
    }
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


def _no_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _spent(_session: object, *, tenant_id: uuid.UUID) -> SimpleNamespace:
        del tenant_id
        return SimpleNamespace(at_ceiling=True, platform_paused=False)

    monkeypatch.setattr(work, "read_ai_quota", _spent)


@pytest.mark.parametrize("job", ["answer_calls", "call_leads"])
async def test_with_no_ai_allowance_the_work_gets_the_ready_made_script(
    monkeypatch: pytest.MonkeyPatch, job: str
) -> None:
    """Pip is not asked, and the flow still reaches its test call: the build this replaced
    fell back to the same ready-made script."""
    _no_allowance(monkeypatch)
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    await _made(tenant_id, headers)
    async with _client() as http:
        drafted = await http.post("/v1/first-run/work", headers=headers, json={"job": job})
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    script_step = next(s for s in body["build"]["steps"] if s["step"] == "script")
    assert script_step["state"] == work.READY_MADE
    table, holder = (
        ("inbound_lines", body["line_id"])
        if job == "answer_calls"
        else ("campaigns", body["campaign_id"])
    )
    row = await _one(
        tenant_id, f"SELECT script, script_proposal FROM {table} WHERE id = :h", h=holder
    )
    assert row.script_proposal is None, "Pip was not asked"
    script = CallScript.model_validate(row.script)
    assert script.stages and script.identity.startswith("Your name is Anjali.")


async def test_a_view_as_session_drafts_with_the_ready_made_script() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    await _made(tenant_id, headers)
    async with tenant_session(tenant_id) as session:
        await work.start_work(
            session, tenant_id=tenant_id, job="answer_calls", user_id=None, may_spend_ai=False
        )
        state = await work.read_state(session, tenant_id=tenant_id)
        assert state.line_id is not None
        line = await lines.read_line(session, state.line_id)
    assert line.script is not None and line.proposal is None


async def _failed(tenant_id: uuid.UUID, line_id: uuid.UUID, reason: str) -> None:
    """What the writer does when no model gives a usable draft."""
    async with tenant_session(tenant_id) as session:
        record = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    holder = campaign_script._line(tenant_id, line_id, uuid.UUID(record["id"]))
    await campaign_script._fail(holder, "Pip could not write it.", reason=reason)
    await campaign_script._ready_made_if_asked(holder)


@pytest.mark.parametrize("reason", ["crashed", "answer_unusable"])
async def test_a_failed_first_run_draft_leaves_the_ready_made_script(reason: str) -> None:
    tenant_id = await _tenant()
    line_id = await _drafted_line(tenant_id, await _owner(tenant_id))
    await _failed(tenant_id, line_id, reason)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        state = await work.read_state(session, tenant_id=tenant_id)
    assert line.script is not None and line.proposal is None
    assert state.build_steps["script"] == {"state": work.READY_MADE}


async def test_a_failed_draft_never_replaces_a_script_the_owner_saved() -> None:
    tenant_id = await _tenant()
    line_id = await _drafted_line(tenant_id, await _owner(tenant_id))
    own = CallScript(opening_line="Hello, this is Madhav Homes.")
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, own)
    await _failed(tenant_id, line_id, "crashed")
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script == own and line.proposal is not None


async def test_the_first_run_asks_at_most_three_profile_questions_and_the_one_thing() -> None:
    from apps.api.first_run.models import MAX_ASKED, MAX_QUESTIONS
    from apps.api.first_run.questions import MAX_WRITTEN, ONE_THING

    assert MAX_QUESTIONS == MAX_WRITTEN == 3 and MAX_ASKED == 4
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        short = await http.put("/v1/first-run/brief", headers=headers, json={"brief": "Shop"})
    items = short.json()["questions"]["items"]
    assert 0 < len(items) <= MAX_ASKED and items[-1]["id"] == ONE_THING.id


async def test_go_live_is_done_once_a_line_is_live_on_a_number() -> None:
    """The first run's draft line on the bought number answers nobody until it is put live,
    so the guide's last step stays open until then, though no agent is ever switched on."""
    from apps.api.go_live.guide import read_go_live

    tenant_id = await _tenant()
    line_id = await _drafted_line(tenant_id, await _owner(tenant_id))
    async with tenant_session(tenant_id) as session:
        agent_id = (await lines.read_line(session, line_id)).agent_id
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, inbound_line_id, e164, "
                "series, dlt_status, engine_number_ref, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :lid, :e, '160', 'registered', :ref, now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "lid": line_id,
                "e": f"+91160{uuid.uuid4().int % 10_000_000:07d}",
                "ref": f"num_{uuid.uuid4().hex[:8]}",
            },
        )
        draft = await read_go_live(session, tenant_id=tenant_id)
        await session.execute(
            text(
                "UPDATE inbound_lines SET published_at = now(), engine_agent_ref = 'ag_line' "
                "WHERE id = :l"
            ),
            {"l": line_id},
        )
        live = await read_go_live(session, tenant_id=tenant_id)
    assert (draft.switch_on, draft.live_lines, draft.live_agents) == ("todo", 0, 0)
    assert (live.switch_on, live.live_lines, live.live_agents) == ("done", 1, 0)

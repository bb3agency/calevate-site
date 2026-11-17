"""A practice test's script fix is a Pip draft on the agent's Inbound line or campaign
(D-1017, following D-1005): one holder is used without asking, several need a choice, none
says so, and facts from the same round still wait on the Training tab for the knowledge."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.agents import test_conversations, test_fixes
from apps.api.agents.mistake_fixes import Holder
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound.lines import create_line
from apps.workers import agent_test_conversations as worker
from apps.workers import chat
from calevate_shared.call_script import CallScript, ConversationStage
from sqlalchemy import text
from tests.agent_test_loop_test import NOT_INTERESTED, _agent, _edit, _failed_run, _model

SCRIPT = CallScript(
    schema_version=2,
    opening_line="Namaskaram, Raghava Organics.",
    stages=[ConversationStage(id="s1", name="Greet", instruction="Greet them.")],
)
FACT = {
    "action": "add",
    "fact_id": None,
    "question": "Do you deliver on Sunday?",
    "answer": "",
    "because": "k1",
    "why": "Callers ask.",
}
OBJECTION = _edit("set_objection", objection="Not interested", text="Thank them and end politely.")
OPENING = _edit("set_part", part="opening_line", text="Hello, Raghava Organics here.")


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


async def _line(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            script=SCRIPT,
            created_by=None,
        )


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Reminders', 'service', CAST(:s AS jsonb))"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id, "s": SCRIPT.model_dump_json()},
        )
    return campaign_id


async def _proposal(tenant_id: uuid.UUID, table: str, holder_id: uuid.UUID) -> Any:
    assert table in ("inbound_lines", "campaigns")
    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text(f"SELECT script_proposal FROM {table} WHERE id = :h"), {"h": holder_id}
            )
        ).scalar_one()
    return json.loads(raw) if isinstance(raw, str) else raw


async def test_one_line_gets_the_script_fix_as_a_pip_draft_and_facts_stay_on_the_run(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF a practice test's script fix is written anywhere but the agent's line, goes
    live by itself, carries an opening-line edit (the notices are said there, D-971), or the
    facts of the same round stop reaching the Training tab."""
    tenant_id, agent_id = await _agent()
    line_id = await _line(tenant_id, agent_id, "Main line")
    async with tenant_session(tenant_id) as session:
        version_before = (
            await session.execute(
                text("SELECT system_prompt_id FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    run_id = await _failed_run(tenant_id, agent_id, [NOT_INTERESTED])
    monkeypatch.setattr(
        chat, "complete", _model([{"edits": [OBJECTION, OPENING], "facts": [FACT]}])
    )

    stop, record = await worker.improve_run(tenant_id, agent_id, run_id, keys=None)

    assert stop == "completed" and record is not None
    assert record["script_fixes"] == "drafted"
    assert record["holder"] == {"kind": "inbound_line", "id": str(line_id), "name": "Main line"}
    assert [e["op"] for e in record["edits"]] == ["set_objection"]
    assert record["facts"][0]["question"] == "Do you deliver on Sunday?"
    draft = await _proposal(tenant_id, "inbound_lines", line_id)
    assert draft["status"] == "ready" and draft["id"] == record["draft_id"]
    assert draft["from_tests"] is True
    assert draft["fix_label"] == "the practice test “Not interested”"
    drafted = CallScript.model_validate(draft["script"])
    assert drafted.objections[0].response == "Thank them and end politely."
    assert drafted.opening_line == SCRIPT.opening_line
    async with tenant_session(tenant_id) as session:
        line_script = (
            await session.execute(
                text("SELECT script FROM inbound_lines WHERE id = :h"), {"h": line_id}
            )
        ).scalar_one()
        version_after = (
            await session.execute(
                text("SELECT system_prompt_id FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    # Nothing is live: the line keeps its script and the agent's own is not touched.
    assert CallScript.model_validate(line_script) == SCRIPT
    assert version_after == version_before


async def test_several_holders_need_a_choice_and_the_chosen_campaign_gets_the_draft(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF a request with several lines or campaigns guesses one, the named one is not
    where the draft lands, or one not this agent's is accepted."""
    tenant_id, agent_id = await _agent()
    line_id = await _line(tenant_id, agent_id, "Main line")
    campaign_id = await _campaign(tenant_id, agent_id)
    run_id = await _failed_run(tenant_id, agent_id, [NOT_INTERESTED])

    async with tenant_session(tenant_id) as session:
        holders = await test_fixes.fix_holders(session, agent_id)
        assert [(h.kind, h.id) for h in holders] == [
            ("inbound_line", line_id),
            ("campaign", campaign_id),
        ]
        with pytest.raises(ProblemError) as asked:
            await test_conversations.request_improvement(
                session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, keys=None
            )
        assert asked.value.code == test_fixes.CHOOSE_HOLDER_CODE
        with pytest.raises(ProblemError) as unknown:
            await test_conversations.request_improvement(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                run_id=run_id,
                keys=None,
                holder=Holder("campaign", uuid.uuid4()),
            )
        assert unknown.value.code == test_fixes.UNKNOWN_HOLDER_CODE
        await test_conversations.request_improvement(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            keys=None,
            holder=Holder("campaign", campaign_id),
        )
        queued = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :j "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"j": test_conversations.IMPROVE_JOB},
            )
        ).scalar_one()
    payload = json.loads(queued) if isinstance(queued, str) else queued
    assert (payload["holder_kind"], payload["holder_id"]) == ("campaign", str(campaign_id))

    monkeypatch.setattr(chat, "complete", _model([{"edits": [OBJECTION], "facts": []}]))
    await worker.improve_agent_test_run({}, payload)

    assert (await _proposal(tenant_id, "campaigns", campaign_id))["status"] == "ready"
    assert await _proposal(tenant_id, "inbound_lines", line_id) is None


async def test_auto_improve_with_several_holders_offers_facts_and_asks_where(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _agent()
    first = await _line(tenant_id, agent_id, "Main line")
    second = await _line(tenant_id, agent_id, "After hours")
    run_id = await _failed_run(tenant_id, agent_id, [NOT_INTERESTED])
    monkeypatch.setattr(chat, "complete", _model([{"edits": [OBJECTION], "facts": [FACT]}]))

    stop, record = await worker.improve_run(tenant_id, agent_id, run_id, keys=None)

    assert stop == "completed" and record is not None
    assert record["script_fixes"] == "choose" and record["edits"] == []
    assert record["facts"][0]["question"] == "Do you deliver on Sunday?"
    for line_id in (first, second):
        assert await _proposal(tenant_id, "inbound_lines", line_id) is None


async def test_no_holder_offers_facts_and_says_where_script_fixes_would_go(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _agent()
    run_id = await _failed_run(tenant_id, agent_id, [NOT_INTERESTED])
    monkeypatch.setattr(chat, "complete", _model([{"edits": [OBJECTION], "facts": []}]))

    stop, record = await worker.improve_run(tenant_id, agent_id, run_id, keys=None)

    assert stop == "no_change" and record is not None
    assert record["script_fixes"] == "no_holder" and record["holder"] is None
    async with tenant_session(tenant_id) as session:
        stored = await test_conversations.get_run(session, agent_id, run_id)
    assert stored.improve_note == worker.NO_HOLDER_NOTE


async def test_a_draft_already_waiting_is_never_replaced(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF a practice fix overwrites a Pip draft the owner has not reviewed, or the
    round is then remembered as answered, so asking again after the review is refused."""
    tenant_id, agent_id = await _agent()
    line_id = await _line(tenant_id, agent_id, "Main line")
    waiting = {"id": str(uuid.uuid4()), "status": "ready", "requested_at": "2026-11-17T10:00:00+00:00"}
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_proposal = CAST(:p AS jsonb) WHERE id = :h"),
            {"p": json.dumps(waiting), "h": line_id},
        )
    run_id = await _failed_run(tenant_id, agent_id, [NOT_INTERESTED])
    monkeypatch.setattr(chat, "complete", _model([{"edits": [OBJECTION], "facts": []}]))

    stop, record = await worker.improve_run(tenant_id, agent_id, run_id, keys=None)

    assert stop == "no_change" and record is not None
    assert record["script_fixes"] == "draft_open" and record["input_hash"] is None
    assert (await _proposal(tenant_id, "inbound_lines", line_id))["id"] == waiting["id"]

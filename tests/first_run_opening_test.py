"""The first run's agent says its AI notice on every job mix (D-864), as its introduction
before its opening line (D-865), both founder 23 Oct 2026.

The Sri Estates trial call opened with no AI notice although the build ticked "Adding its AI
notice": every agent is created with both notices off (D-669) and the notice step only read
back that the sentence was on file. These build the first agent through the worker, as the
screen does, and read what callers hear first the way the agent screen does
(`roster.agent_by_id`), which is `join_first_words` over the agent's switches and script.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import roster
from apps.api.agents.publishing import set_disclosure_posture
from apps.api.agents.service import _load_agent, trial_call_first_words
from apps.api.compliance.audit import write_audit
from apps.api.compliance.disclosure import ai_disclosure_for
from apps.api.db.session import tenant_session
from apps.api.first_run import service as first_run
from apps.workers import first_run as worker
from calevate_shared.spoken_guard import opens_with_greeting
from sqlalchemy import text

JOBS = ("answer_calls", "call_new_leads", "call_leads")
#: Every mix the job step allows, in the owner's order as given.
JOB_MIXES = [mix for n in (1, 2, 3) for mix in itertools.combinations(JOBS, n)]


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Sri Estates",
        slug=f"open-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _no_voice(_tenant_id: uuid.UUID, _language: str) -> None:
    return None


async def _build(
    tenant_id: uuid.UUID, jobs: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, build: int = 1
) -> Any:
    async with tenant_session(tenant_id) as session:
        if build == 1:
            await first_run.save_job(
                session,
                tenant_id=tenant_id,
                jobs=list(jobs),
                language_primary="te-IN",
                languages_extra=[],
            )
            # Too short for the script writer: the ready-made starter, no model needed.
            await first_run.save_brief(session, tenant_id=tenant_id, brief="Flats")
        await first_run.request_build(session, tenant_id=tenant_id, user_id=None)
        run = (await session.execute(text("SELECT id FROM first_runs"))).one()
    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    payload = {"tenant_id": str(tenant_id), "run_id": str(run.id), "build": build}
    assert await worker.build_first_agent({}, payload) == "built"
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text("SELECT agent_id, build_steps FROM first_runs"))).one()


@pytest.mark.parametrize("jobs", JOB_MIXES, ids=["+".join(mix) for mix in JOB_MIXES])
async def test_the_first_agent_introduces_itself_then_says_its_opening_line(
    jobs: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _tenant()
    run = await _build(tenant_id, jobs, monkeypatch)
    assert run.build_steps["notice"]["state"] == "done"
    async with tenant_session(tenant_id) as session:
        agent = await roster.agent_by_id(session, run.agent_id)
        audited = (
            (
                await session.execute(
                    text("SELECT actor_type FROM audit_log WHERE action = :a AND object_id = :o"),
                    {"a": "agent.ai_disclosure_enabled", "o": str(run.agent_id)},
                )
            )
            .scalars()
            .all()
        )
    assert agent is not None
    assert agent.ai_disclosure_enabled
    assert not agent.recording_notice_enabled, "the recording notice stays the owner's choice"
    notice = agent.ai_disclosure_line.strip()
    assert notice == ai_disclosure_for(language="te-IN", business="Sri Estates", name="Anjali")
    assert notice in agent.opening_line
    # The salutation, the introduction, then the opening line, in one turn (D-865); the
    # opening line neither greets again nor repeats who is calling.
    opening = agent.script_opening_line.strip()
    assert agent.first_words == f"నమస్కారం అండి, {notice} {opening}"
    assert not opens_with_greeting(opening)
    assert "Anjali" not in opening
    # A call it places says why after the introduction (D-945): the founder's own "we are
    # calling from Sri Estates", while no written reason clause exists for Telugu.
    assert "Sri Estates" not in opening or opening.startswith("మేము Sri Estates నుండి కాల్ చేస్తున్నాము.")
    assert agent.greeting_budget is None or len(agent.first_words) <= agent.greeting_budget.limit
    assert audited == ["system"]


async def test_an_answering_agents_test_call_carries_the_notice_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    run = await _build(tenant_id, ("answer_calls",), monkeypatch)
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, run.agent_id)
    words = trial_call_first_words(agent, call_is_recorded=True)
    notice = str(agent["ai_disclosure_line"]).strip()
    assert words == (f"నమస్కారం అండి, {notice} ఇది మీ కొత్త రిసెప్షనిస్ట్ టెస్ట్ కాల్. ఇప్పుడు మాట్లాడొచ్చా?")


async def test_a_rebuild_keeps_the_ai_notice_off_when_the_owner_switched_it_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    run = await _build(tenant_id, ("call_leads",), monkeypatch)
    await set_disclosure_posture(
        tenant_id=tenant_id,
        agent_id=run.agent_id,
        ai_disclosure_enabled=False,
        recording_notice_enabled=None,
    )
    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action="agent.ai_disclosure_disabled",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(run.agent_id),
            ip="203.0.113.7",
        )
    again = await _build(tenant_id, ("call_leads",), monkeypatch, build=2)
    assert again.build_steps["notice"]["state"] == "off"
    async with tenant_session(tenant_id) as session:
        agent = await roster.agent_by_id(session, run.agent_id)
    assert agent is not None and not agent.ai_disclosure_enabled
    # With no introduction, the opening line greets and says who is calling again.
    assert agent.first_words == agent.script_opening_line.strip()
    assert opens_with_greeting(agent.first_words) and "Sri Estates" in agent.first_words

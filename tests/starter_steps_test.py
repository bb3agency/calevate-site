"""Each business's own steps for the ready-made jobs.

What is under test:

1. **The rule.** A written plan keeps every step, in order: the wrong count, a blank title or
   two steps with one title is no plan, and the platform's instruction and "done when" stay.
2. **The preview.** "Pick a job" shows the business's steps once they are written, and the
   job's own until then.
3. **The agent.** A new agent's first script names its sections with them, the script writer
   is told to keep them, and a retype still recognises the unedited starter.
4. **The writing.** Queued when what the business sells changes, stored only for the list it
   was written for, and a refusal stores nothing.
5. **Tenancy (hard rule 1).** One business's steps never reach another's preview.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import starter_plans, starters
from apps.api.agents.starter_plans import PlanStep, clean_plan, plans_to_json, with_focus
from apps.api.agents.trade_playbooks import VALUE_STEP_TITLE, playbook_guidance
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.workers import starter_steps as worker
from apps.workers.extraction import AssistCapability
from apps.workers.script_assist import JsonAnswer
from calevate_shared.call_script import STAGE_DETAIL_MAX, CallScript
from sqlalchemy import text
from tests.agent_starters_test import _agent_rows, _create, _starters, _tenant

COUNTS = starters.JOB_STEP_COUNTS


def _raw(job: str, prefix: str = "Step") -> list[dict[str, str]]:
    return [
        {"title": f"{prefix} {i} of {job.replace('_', ' ')}", "focus": f"focus {i}"}
        for i in range(1, COUNTS[job] + 1)
    ]


def _all_raw(prefix: str = "Step") -> dict[str, list[dict[str, str]]]:
    return {job: _raw(job, prefix) for job in starters.STARTER_JOBS}


def test_a_plan_keeps_every_step_or_is_no_plan() -> None:
    steps = COUNTS["call_leads"]
    assert clean_plan(_raw("call_leads"), steps=steps) is not None
    assert clean_plan(_raw("call_leads")[:-1], steps=steps) is None
    blank = _raw("call_leads")
    blank[0]["title"] = "  "
    assert clean_plan(blank, steps=steps) is None
    twice = _raw("call_leads")
    twice[1]["title"] = twice[0]["title"].upper()
    assert clean_plan(twice, steps=steps) is None
    long = _raw("call_leads")
    long[0]["title"] = "x" * 200
    cleaned = clean_plan(long, steps=steps)
    assert cleaned is not None and len(cleaned[0].title) == starter_plans.STEP_TITLE_MAX


def test_only_the_title_and_focus_are_the_businesss() -> None:
    starter = starters.starter_for("custom", "call_leads")
    plan = clean_plan(_raw("call_leads"), steps=len(starter.steps))
    mine = starter.planned(plan)
    for ours, theirs, own in zip(starter.steps, mine.steps, plan or (), strict=True):
        assert theirs.title == own.title
        assert theirs.instruction == f"{ours.instruction} For this business: {own.focus}"
        assert theirs.exit_when == ours.exit_when
    # A plan of another shape changes nothing.
    assert starter.planned((PlanStep("Only one"),)) is starter
    # A focus that would push the section past its limit is left out.
    assert with_focus("x" * STAGE_DETAIL_MAX, "more") == "x" * STAGE_DETAIL_MAX


def test_the_writer_keeps_the_businesss_titles_and_finds_its_value_step() -> None:
    plan = clean_plan(_raw("call_leads"), steps=COUNTS["call_leads"])
    assert plan is not None
    guidance = playbook_guidance("custom", "outbound", {"call_leads": plan})
    assert "Use these step titles as written" in guidance
    for step in plan:
        assert step.title in guidance
    value_index = [s.title for s in starters.starter_for("custom", "call_leads").steps].index(
        VALUE_STEP_TITLE
    )
    assert f"(none for {plan[value_index].title!r})" in guidance
    assert "Step plan for this kind of business" in playbook_guidance("custom", "outbound")


def test_the_model_answer_is_all_jobs_or_none() -> None:
    assert worker.plans_from_model(_all_raw(), vertical=None) is not None
    partial = _all_raw()
    partial["call_leads"] = partial["call_leads"][:-1]
    assert worker.plans_from_model(partial, vertical=None) is None
    # The rules of every AI-written line a client reads: no provider, no medical words
    # outside a clinic, no markdown.
    # A line that breaks those is put back, not the whole answer lost: a title to the
    # platform's own for that step, a focus to none.
    platform = starters.starter_for("custom", "answer_calls").steps[0].title
    for broken in ("Ask what Gemini thinks", "Book an appointment", "**Close**"):
        bad = _all_raw()
        bad["answer_calls"][0]["title"] = broken
        bad["answer_calls"][1]["focus"] = broken
        plans = worker.plans_from_model(bad, vertical=None)
        assert plans is not None
        assert plans["answer_calls"][0].title == platform
        assert plans["answer_calls"][1].focus == ""
        assert plans["answer_calls"][2].title == bad["answer_calls"][2]["title"]
    medical = _all_raw()
    medical["answer_calls"][0]["title"] = "Book an appointment"
    plans = worker.plans_from_model(medical, vertical="clinic")
    assert plans is not None and plans["answer_calls"][0].title == "Book an appointment"
    # A put-back title that collides with another step's is no plan at all.
    clash = _all_raw()
    clash["answer_calls"][0]["title"] = "**x**"
    clash["answer_calls"][1]["title"] = platform
    assert worker.plans_from_model(clash, vertical=None) is None


async def _services(tenant_id: uuid.UUID, services: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id, services) VALUES "
                "(:id, :tid, CAST(:services AS jsonb)) "
                "ON CONFLICT (tenant_id) DO UPDATE SET services = EXCLUDED.services"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "services": services},
        )


async def _services_hash(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT md5(services::text) FROM business_profiles WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )


async def _write(tenant_id: uuid.UUID, prefix: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET starter_plans = CAST(:p AS jsonb) WHERE id = :t"),
            {
                "t": tenant_id,
                "p": plans_to_json(
                    {
                        job: clean_plan(_raw(job, prefix), steps=COUNTS[job]) or ()
                        for job in starters.STARTER_JOBS
                    }
                ),
            },
        )


def _answer(raw: dict[str, Any]) -> Any:
    async def answered(*_args: Any, parse: Any, **_kwargs: Any) -> JsonAnswer[Any]:
        return JsonAnswer(
            value=parse(raw),
            capability=AssistCapability(available=True, provider="gemini"),
            model="gemini-2.5-flash-lite",
        )

    return answered


@pytest.mark.rls
async def test_the_preview_shows_the_businesss_steps_once_written() -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    code, body = await _starters(token, "?job=call_leads")
    assert code == 200, body
    generic = [s.title for s in starters.starter_for("custom", "call_leads").steps]
    assert body["starters"][0]["step_titles"] == generic
    assert body["starters"][0]["steps_written"] is False

    await _write(tenant_id, "Crop")
    code, body = await _starters(token, "?job=call_leads")
    assert code == 200, body
    assert body["starters"][0]["step_titles"] == [s["title"] for s in _raw("call_leads", "Crop")]
    assert body["starters"][0]["steps_written"] is True


@pytest.mark.rls
async def test_a_new_agent_is_made_with_the_steps_the_owner_saw() -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    await _write(tenant_id, "Crop")
    code, body = await _create(token, {"name": "Follow-up", "starter": "call_leads"})
    assert code == 201, body
    row = await _agent_rows(tenant_id, uuid.UUID(body["id"]))
    script = CallScript.model_validate(row[5])
    assert [s.name for s in script.stages] == [s["title"] for s in _raw("call_leads", "Crop")]
    # Still recognised as an unedited starter, so a business-type change can retype it.
    plans = {job: clean_plan(_raw(job, "Crop"), steps=COUNTS[job]) for job in starters.STARTER_JOBS}
    assert (
        starters.starter_vertical_of(
            row[5],
            job="call_leads",
            business="Rytu Khata",
            language="te-IN",
            plan=plans["call_leads"],
        )
        == "custom"
    )


@pytest.mark.rls
async def test_steps_are_written_for_what_it_sells_and_never_for_an_older_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    await _services(tenant_id, "[]")
    async with tenant_session(tenant_id) as session:
        assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id) is False
    await _services(tenant_id, '[{"name": "Crop records"}]')
    async with tenant_session(tenant_id) as session:
        assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id) is True
        assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id) is False
    older = await _services_hash(tenant_id)

    monkeypatch.setattr(worker, "ask_json", _answer(_all_raw("Crop")))
    payload = {"tenant_id": str(tenant_id), "services": older}
    assert await worker.write_starter_steps({}, payload) == "written"
    code, body = await _starters(token, "?job=answer_calls")
    assert code == 200, body
    assert body["starters"][0]["steps_written"] is True

    # What it sells changed: a new writing is queued, and an answer for the old list is
    # not stored over it.
    await _services(tenant_id, '[{"name": "Crop records"}, {"name": "Soil tests"}]')
    async with tenant_session(tenant_id) as session:
        assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id) is True
    monkeypatch.setattr(worker, "ask_json", _answer(_all_raw("Stale")))
    assert await worker.write_starter_steps({}, payload) == "superseded"
    code, body = await _starters(token, "?job=answer_calls")
    assert body["starters"][0]["step_titles"][0].startswith("Crop")


@pytest.mark.rls
async def test_a_refusal_stores_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, token = await _tenant("custom", "Beta Traders")
    await _services(tenant_id, '[{"name": "Rice"}]')

    async def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise ProblemError.business_rule("assist_answer_unusable", "Nothing usable came back.")

    monkeypatch.setattr(worker, "ask_json", refused)
    payload = {"tenant_id": str(tenant_id), "services": await _services_hash(tenant_id)}
    assert await worker.write_starter_steps({}, payload) == "refused"
    code, body = await _starters(token)
    assert code == 200, body
    assert not any(s["steps_written"] for s in body["starters"])


@pytest.mark.rls
async def test_one_business_never_sees_anothers_steps() -> None:
    tenant_a, _ = await _tenant("custom", "Rytu Khata")
    _, token_b = await _tenant("custom", "Beta Traders")
    await _write(tenant_a, "Crop")
    code, body = await _starters(token_b, "?job=call_leads")
    assert code == 200, body
    assert body["starters"][0]["steps_written"] is False
    assert not any(t.startswith("Crop") for t in body["starters"][0]["step_titles"])

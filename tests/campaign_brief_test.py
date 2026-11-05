"""A campaign's purpose and goal: taken on create and edit, carried by every campaign dial as
the call's reason, and the goal judged on each answered call and counted per person."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from apps.api.campaigns import brief, controls, results
from apps.api.campaigns import service as campaigns
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from apps.workers import extraction as extraction_module
from apps.workers.extraction import build_response_schema, extract_call
from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.engine import CALL_VARIABLE_VALUE_MAX, call_reason_value
from calevate_shared.extraction import ExtractionSchemaSpec, build_extraction_prompt
from sqlalchemy import text
from tests.campaign_controls_test import _account, _call, _campaign, _client, _one
from tests.campaign_dispatch_audit_test import _daytime as _daytime
from tests.campaign_dispatch_audit_test import _launched, _tick_one_campaign
from tests.campaign_dispatch_audit_test import _roomy_platform_pool as _roomy_platform_pool
from tests.campaign_dispatch_audit_test import (
    _settle_what_this_module_started as _settle_what_this_module_started,
)
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage

SPEC = ExtractionSchemaSpec(fields=[])
PURPOSE = "Our new drip irrigation subsidy for cotton farmers"
GOAL = "They book a free soil test visit"


# --- the two lines --------------------------------------------------------------------


def test_the_longest_purpose_and_goal_fit_one_call_variable_uncut() -> None:
    reason = brief.campaign_call_reason("p" * brief.PURPOSE_MAX, "g" * brief.GOAL_MAX)
    assert reason is not None and len(reason) == brief.REASON_MAX <= CALL_VARIABLE_VALUE_MAX
    assert call_reason_value(reason) == reason, "the adapter's cut never shortens it"


def test_the_reason_reads_as_one_sentence_with_either_half_alone() -> None:
    assert brief.campaign_call_reason(PURPOSE + ".", GOAL) == f"{PURPOSE}. Aim: {GOAL}."
    assert brief.campaign_call_reason(PURPOSE, None) == f"{PURPOSE}."
    assert brief.campaign_call_reason(None, GOAL) == f"Aim: {GOAL}."
    assert brief.campaign_call_reason(None, " ") is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("ab", "few more words"),
        ("x" * 91, "90 characters"),
        ("**Book** a visit", "plain words"),
        ("- book a visit", "plain words"),
        ("Book {{name}} in", "plain words"),
        ("Book a visit \U0001f600", "plain words"),
    ],
)
def test_a_purpose_that_cannot_be_spoken_is_refused_by_name(value: str, problem: str) -> None:
    with pytest.raises(brief.BriefLineError, match=problem):
        brief.clean_purpose(value)


def test_a_line_is_trimmed_to_one_line_and_blank_is_none() -> None:
    assert brief.clean_goal("  book   a\nvisit ") == "book a visit"
    assert brief.clean_goal("   ") is None and brief.clean_goal(None) is None


# --- create, edit, read, copy ---------------------------------------------------------


async def test_create_and_edit_carry_purpose_and_goal_and_progress_reads_them() -> None:
    account = await _account()
    async with _client() as client:
        made = await client.post(
            "/v1/campaigns",
            headers=account.headers,
            json={
                "agent_id": str(account.agent_id),
                "name": "Drip subsidy",
                "classification": "service",
                "purpose": f"  {PURPOSE} ",
                "goal": GOAL,
            },
        )
        assert made.status_code == 201, made.text
        campaign_id = made.json()["id"]
        read = (await client.get(f"/v1/campaigns/{campaign_id}", headers=account.headers)).json()
        assert read["purpose"] == PURPOSE and read["goal"] == GOAL

        edited = await client.patch(
            f"/v1/campaigns/{campaign_id}",
            headers=account.headers,
            json={"goal": "They agree to a visit", "purpose": None},
        )
        assert edited.status_code == 204, edited.text
    row = await _one(
        account.tenant_id, "SELECT purpose, goal FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] is None and row[1] == "They agree to a visit"


@pytest.mark.parametrize(
    "body",
    [{"goal": "x" * 51}, {"purpose": "# Heading"}, {"goal": "ok"}],
)
async def test_a_line_the_agent_could_not_speak_is_a_422(body: dict[str, Any]) -> None:
    account = await _account()
    async with _client() as client:
        response = await client.post(
            "/v1/campaigns",
            headers=account.headers,
            json={
                "agent_id": str(account.agent_id),
                "name": "Bad lines",
                "classification": "service",
                **body,
            },
        )
    assert response.status_code == 422, response.text


async def test_the_database_refuses_an_overlong_goal_written_around_the_api() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    with pytest.raises(Exception, match="goal_line"):
        async with tenant_session(account.tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET goal = :g WHERE id = :c"),
                {"g": "x" * 51, "c": campaign_id},
            )


async def test_another_account_cannot_read_or_change_them() -> None:
    owner, other = await _account(), await _account()
    campaign_id = await _campaign(owner)
    async with tenant_session(owner.tenant_id) as session:
        await controls.update_draft(
            session, campaign_id=campaign_id, changes={"purpose": PURPOSE, "goal": GOAL}
        )
    async with tenant_session(other.tenant_id) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert seen == 0
    async with _client() as client:
        read = await client.get(f"/v1/campaigns/{campaign_id}", headers=other.headers)
        edit = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=other.headers, json={"goal": "Taken over"}
        )
    assert read.status_code == 404 and edit.status_code == 404
    row = await _one(owner.tenant_id, "SELECT goal FROM campaigns WHERE id = :c", c=campaign_id)
    assert row[0] == GOAL


async def test_a_copy_keeps_the_purpose_and_goal() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    async with tenant_session(account.tenant_id) as session:
        await controls.update_draft(
            session, campaign_id=campaign_id, changes={"purpose": PURPOSE, "goal": GOAL}
        )
        copy_id, _ = await controls.duplicate_campaign(
            session,
            tenant_id=account.tenant_id,
            source_id=campaign_id,
            name=None,
            with_unreached=False,
        )
    row = await _one(
        account.tenant_id, "SELECT purpose, goal FROM campaigns WHERE id = :c", c=copy_id
    )
    assert tuple(row) == (PURPOSE, GOAL)


# --- every campaign dial carries them --------------------------------------------------


async def test_a_campaign_dial_carries_the_purpose_and_goal_as_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent, campaign_id, _number, _template = await _launched(phones=("9876611001",))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET purpose = :p, goal = :g WHERE id = :c"),
            {"p": PURPOSE, "g": GOAL, "c": campaign_id},
        )
    sent: list[str | None] = []
    real = campaign_dispatch.dispatch_call

    async def spy(*args: Any, **kwargs: Any) -> str:
        sent.append(kwargs.get("context_note"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(campaign_dispatch, "dispatch_call", spy)
    assert (await _tick_one_campaign(tenant_id, campaign_id))["dialled"] == 1
    assert sent == [f"{PURPOSE}. Aim: {GOAL}."]


# --- the goal is judged on each answered call -------------------------------------------


class _Runner:
    """A model runner that reads the goal and answers with `answer`."""

    model_name = "fake-model"
    reads_goal = True

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.asked: str | None = None

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        outcomes: Sequence[BusinessOutcome] = (),
        goal: str | None = None,
    ) -> dict[str, Any]:
        self.asked = goal
        return dict(self.answer)


def test_the_prompt_and_schema_ask_for_the_goal_only_when_there_is_one() -> None:
    plain = build_extraction_prompt(SPEC, "caller: avunu")
    asked = build_extraction_prompt(SPEC, "caller: avunu", goal='Book a "free" visit')
    assert "goal_reached" not in plain
    assert '"goal_reached"' in asked and "Book a \N{RIGHT DOUBLE QUOTATION MARK}free" in asked
    section = asked[asked.index('- "goal_reason"') : asked.index('- "out_of_scope"')]
    assert asked.replace(section, "") == plain, "the goal adds one block and changes nothing else"
    schema = build_response_schema(SPEC, goal=GOAL)
    assert schema["properties"]["goal_reached"] == {
        "type": "string",
        "enum": ["yes", "no", "unclear"],
    }
    assert "goal_reached" in schema["required"]
    assert "goal_reached" not in build_response_schema(SPEC)["properties"]


async def test_the_verdict_is_kept_only_when_it_was_asked_and_is_one_we_offered() -> None:
    runner = _Runner({"summary": "s", "outcome_tag": "answered", "goal_reached": "Yes"})
    out = await extract_call(SPEC, "caller: avunu", extractor=runner, goal=GOAL)
    assert out.goal_reached == "yes" and runner.asked == GOAL
    assert (await extract_call(SPEC, "caller: avunu", extractor=runner)).goal_reached is None
    runner.answer["goal_reached"] = "maybe"
    assert (
        await extract_call(SPEC, "caller: avunu", extractor=runner, goal=GOAL)
    ).goal_reached is None


async def test_a_campaign_call_is_judged_against_its_goal_and_stored_on_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner(
        {"summary": "Agreed to a soil test.", "outcome_tag": "answered", "goal_reached": "yes"}
    )
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("goal")
    agent_id = await _scalar(tenant_id, "SELECT agent_id FROM calls WHERE id = :c", c=call_id)
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"Goal {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            purpose=PURPOSE,
            goal=GOAL,
        )
        await session.execute(
            text("UPDATE calls SET campaign_id = :g WHERE id = :c"),
            {"g": campaign_id, "c": call_id},
        )
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert runner.asked == GOAL
    assert await _scalar(tenant_id, "SELECT goal_reached FROM calls WHERE id = :c", c=call_id) == (
        "yes"
    )
    # A re-drive reuses the stored reading and keeps the verdict.
    runner.answer["goal_reached"] = "no"
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert await _scalar(tenant_id, "SELECT goal_reached FROM calls WHERE id = :c", c=call_id) == (
        "yes"
    )


async def test_a_call_outside_a_campaign_is_never_asked_about_a_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner({"summary": "s", "outcome_tag": "answered", "goal_reached": "yes"})
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("nogoal")
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert runner.asked is None
    assert await _scalar(tenant_id, "SELECT goal_reached FROM calls WHERE id = :c", c=call_id) is (
        None
    )


# --- counted per person ---------------------------------------------------------------


async def test_the_results_count_people_by_their_latest_answered_verdict() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=3, status="running")
    async with tenant_session(account.tenant_id) as session:
        assert (await results.summary(session, campaign_id=campaign_id, include_spend=False))[
            "goal"
        ] is None, "no goal, no goal count"
        await session.execute(
            text("UPDATE campaigns SET goal = :g WHERE id = :c"), {"g": GOAL, "c": campaign_id}
        )
    first = await _call(account, campaign_id, status="completed", to="+919876500000", duration=60)
    later = await _call(account, campaign_id, status="completed", to="+919876500000", duration=60)
    other = await _call(account, campaign_id, status="completed", to="+919876500001", duration=60)
    await _call(account, campaign_id, status="no_answer", to="+919876500002")
    async with tenant_session(account.tenant_id) as session:
        for call_id, verdict, minutes in (
            (first, "no", 10),
            (later, "yes", 1),
            (other, "unclear", 5),
        ):
            await session.execute(
                text(
                    "UPDATE calls SET goal_reached = :v, "
                    "started_at = now() - make_interval(mins => :m) WHERE id = :c"
                ),
                {"v": verdict, "m": minutes, "c": call_id},
            )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'connected', attempts = 1, "
                "last_call_id = CASE phone_e164 WHEN '+919876500000' THEN CAST(:a AS uuid) "
                "ELSE CAST(:b AS uuid) END WHERE campaign_id = :c "
                "AND phone_e164 IN ('+919876500000', '+919876500001')"
            ),
            {"a": str(first), "b": str(other), "c": campaign_id},
        )
        found = await results.summary(session, campaign_id=campaign_id, include_spend=False)
        page = await results.contacts_page(
            session, campaign_id=campaign_id, outcome=None, search=None, limit=10, offset=0
        )
    assert found["people_answered"] == 2
    assert found["goal"] == {"reached": 1, "not_reached": 0, "unclear": 1, "not_judged": 0}
    by_phone = {item["phone_e164"]: item["goal_reached"] for item in page.items}
    assert by_phone == {"+919876500000": "yes", "+919876500001": "unclear", "+919876500002": None}

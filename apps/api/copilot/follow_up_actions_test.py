"""D-940: Pip builds, publishes, pauses, resumes, turns off and starts Follow-ups.

Each action's planner refuses with the server's own problems, its confirm runs the function
the `/v1/follow-ups` route runs with the route's audit action, and the permission, view-as
and one-click rules every Pip action follows hold here too.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _client, _lead, _tenant

from apps.api.copilot import plans, undo, write_tools
from apps.api.copilot.actions import ToolActor, WriteRefusedError
from apps.api.copilot.follow_up_actions import FOLLOW_UP_READ, FOLLOW_UPS_LIST, FORMAT
from apps.api.copilot.tools import ToolContext
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.follow_ups import service
from apps.workers import copilot_plans as worker

STEPS: list[dict[str, Any]] = [
    {"id": "s1", "kind": "wait", "hours": 2, "next": "s2"},
    {"id": "s2", "kind": "set_status", "status": "hot", "next": "s3"},
    {"id": "s3", "kind": "end", "goal": True},
]


def _actor(t: Tenant, *, role: str = "owner", impersonating: bool = False) -> ToolActor:
    return ToolActor(
        tenant_id=t.tenant_id, user_id=_user_of(t.token), role=role, impersonating=impersonating
    )


async def _propose(t: Tenant, name: str, args: dict[str, Any], **who: Any) -> Any:
    return await write_tools.plan_write(name, json.dumps(args), actor=_actor(t, **who))


async def _done(t: Tenant, proposal: Any) -> Any:
    return await _confirm(t.tenant_id, _user_of(t.token), proposal.token)


async def _row(t: Tenant, follow_up_id: UUID | str) -> service.Row:
    async with tenant_session(t.tenant_id) as session:
        return await service.get(session, UUID(str(follow_up_id)))


async def _read(t: Tenant, tool: Any, args: dict[str, Any]) -> str:
    async with tenant_session(t.tenant_id) as session:
        return str(await tool.run(session, ToolContext(tenant_id=t.tenant_id, role="owner"), args))


async def _make_callable(t: Tenant) -> None:
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET direction = 'both', engine_agent_ref = 'fake-ref' WHERE id = :a"
            ),
            {"a": t.agent_id},
        )


async def _draft(t: Tenant, **args: Any) -> UUID:
    proposal = await _propose(
        t,
        "follow_up_draft",
        {"name": "Warm up", "trigger": {"kind": "manual"}, "steps": STEPS, **args},
    )
    done = await _done(t, proposal)
    return UUID(str(done.object_id))


# --- reads -------------------------------------------------------------------------------


async def test_the_list_names_starters_what_steps_may_use_and_the_format() -> None:
    t = await _tenant()
    listed = await _read(t, FOLLOW_UPS_LIST, {})
    assert "No Follow-ups yet." in listed
    assert "missed_call_callback" in listed and "needs a published agent that makes calls" in listed
    assert f"agent [{t.agent_id}] Sales (answers only)" in listed
    assert FORMAT in listed
    follow_up_id = await _draft(t)
    listed = await _read(t, FOLLOW_UPS_LIST, {})
    assert f"[{follow_up_id}] Warm up · Draft · You start it for chosen leads" in listed

    one = await _read(t, FOLLOW_UP_READ, {"follow_up_id": str(follow_up_id)})
    assert "- Wait 2 hours · " in one and '"kind":"set_status"' in one
    assert "No problems." in one
    assert "No Follow-up" in await _read(t, FOLLOW_UP_READ, {"follow_up_id": str(uuid.uuid4())})


# --- follow_up_draft ---------------------------------------------------------------------


async def test_a_draft_card_lists_the_step_summaries_and_confirm_saves_a_draft() -> None:
    t = await _tenant()
    proposal = await _propose(
        t, "follow_up_draft", {"name": "Warm up", "trigger": {"kind": "manual"}, "steps": STEPS}
    )
    assert proposal.title == "Make a Follow-up"
    assert proposal.proposed == "1. Wait 2 hours\n2. Mark the lead hot\n3. Finish (goal reached)"
    assert "nothing runs until it is published" in proposal.summary
    async with tenant_session(t.tenant_id) as session:
        assert await service.list_all(session) == [], "a proposal changes nothing"
    done = await _done(t, proposal)
    row = await _row(t, done.object_id)
    assert (row.name, row.status, len(row.steps)) == ("Warm up", "draft", 3)
    assert ("follow_up.created", "follow_up", str(row.id)) in await _audit(t.tenant_id)
    with pytest.raises(ProblemError):
        await _done(t, proposal)


@pytest.mark.parametrize(
    ("steps", "code"),
    [
        ([{"id": "s1", "kind": "set_status", "status": "hot", "next": "s1"}], "step_goes_back"),
        ([{"id": "s1", "kind": "whatsapp", "template_id": str(uuid.uuid4())}], "template_unknown"),
        ([{"id": "s1", "kind": "assign", "user_id": str(uuid.uuid4())}], "teammate_unknown"),
        ([{"id": "s1", "kind": "call", "agent_id": str(uuid.uuid4())}], "agent_unknown"),
        ([{"id": "s1", "kind": "teleport"}], "step_invalid"),
    ],
)
async def test_a_draft_with_problems_is_refused_with_them_before_any_card(
    steps: list[dict[str, Any]], code: str
) -> None:
    t = await _tenant()
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(
            t, "follow_up_draft", {"name": "X", "trigger": {"kind": "manual"}, "steps": steps}
        )
    assert f"({code})" in refused.value.reason
    assert "How to write one" in refused.value.reason


async def test_a_rewrite_replaces_the_draft_and_the_name() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    proposal = await _propose(
        t,
        "follow_up_draft",
        {
            "follow_up_id": str(follow_up_id),
            "name": "Warmer",
            "trigger": json.dumps({"kind": "manual"}),
            "steps": [{"id": "s1", "kind": "end"}],
        },
    )
    assert proposal.title == "Rewrite a Follow-up's draft"
    assert proposal.current.startswith("1. Wait 2 hours")
    assert proposal.proposed == "1. Finish"
    await _done(t, proposal)
    row = await _row(t, follow_up_id)
    assert (row.name, [s.kind for s in row.steps]) == ("Warmer", ["end"])
    assert ("follow_up.draft_saved", "follow_up", str(follow_up_id)) in await _audit(t.tenant_id)


async def test_a_starter_explains_what_the_account_lacks_then_is_made() -> None:
    t = await _tenant()
    with pytest.raises(WriteRefusedError, match="a published agent that makes calls"):
        await _propose(t, "follow_up_draft", {"starter": "missed_call_callback"})
    with pytest.raises(WriteRefusedError, match="the keys are"):
        await _propose(t, "follow_up_draft", {"starter": "nonsense"})
    await _make_callable(t)
    proposal = await _propose(t, "follow_up_draft", {"starter": "missed_call_callback"})
    assert "Call with Sales" in proposal.proposed
    row = await _row(t, (await _done(t, proposal)).object_id)
    assert row.starter == "missed_call_callback"


# --- publish, pause, resume, turn off ----------------------------------------------------


async def test_the_lifecycle_and_pause_is_undone_by_resuming() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    args = {"follow_up_id": str(follow_up_id)}
    with pytest.raises(WriteRefusedError, match="only a Follow-up that is on"):
        await _propose(t, "follow_up_pause", args)
    publish = await _propose(t, "follow_up_publish", args)
    assert publish.proposed.startswith("1. Wait 2 hours") and publish.cost is None
    await _done(t, publish)
    assert (await _row(t, follow_up_id)).status == "live"
    with pytest.raises(WriteRefusedError, match="nothing new to publish"):
        await _propose(t, "follow_up_publish", args)

    await _done(t, await _propose(t, "follow_up_pause", args))
    assert (await _row(t, follow_up_id)).status == "paused"
    async with tenant_session(t.tenant_id) as session:
        action_id = (
            await session.execute(
                text("SELECT id FROM copilot_actions WHERE tool = 'follow_up_pause'")
            )
        ).scalar_one()
        undone = await undo.undo_client_action(
            session,
            UUID(str(action_id)),
            principal=_principal(t.tenant_id, _user_of(t.token)),
            ip=None,
        )
    assert "on again" in undone.detail
    assert (await _row(t, follow_up_id)).status == "live"

    await _done(t, await _propose(t, "follow_up_turn_off", args))
    assert (await _row(t, follow_up_id)).status == "off"
    resume = await _propose(t, "follow_up_resume", args)
    assert "do not restart" in resume.summary
    await _done(t, resume)
    assert (await _row(t, follow_up_id)).status == "live"
    actions = [a for a, _t, o in await _audit(t.tenant_id) if o == str(follow_up_id)]
    for action in ("follow_up.published", "follow_up.paused", "follow_up.turned_off"):
        assert action in actions
    assert actions.count("follow_up.resumed") == 1


async def test_publish_is_refused_with_the_drafts_problems_and_binds_what_it_showed() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    async with tenant_session(t.tenant_id) as session:
        row = await service.get(session, follow_up_id)
        await service.save_draft(
            session,
            follow_up_id,
            trigger=row.trigger,
            steps=row.steps[:1],
            settings=row.settings,
        )
    with pytest.raises(WriteRefusedError, match=r"s1 \(step_missing\)"):
        await _propose(t, "follow_up_publish", {"follow_up_id": str(follow_up_id)})
    async with tenant_session(t.tenant_id) as session:
        await service.save_draft(
            session, follow_up_id, trigger=row.trigger, steps=row.steps, settings=row.settings
        )
    publish = await _propose(t, "follow_up_publish", {"follow_up_id": str(follow_up_id)})
    async with tenant_session(t.tenant_id) as session:
        row = await service.get(session, follow_up_id)
        await service.save_draft(
            session, follow_up_id, trigger=row.trigger, steps=row.steps, settings=row.settings
        )
    with pytest.raises(ProblemError) as moved:
        await _done(t, publish)
    assert moved.value.code == "follow_up_changed"


async def test_staff_and_view_as_are_refused_and_another_account_sees_nothing() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    args = {"follow_up_id": str(follow_up_id)}
    with pytest.raises(WriteRefusedError, match="role may not"):
        await _propose(t, "follow_up_publish", args, role="staff")
    with pytest.raises(WriteRefusedError):
        await _propose(t, "follow_up_publish", args, impersonating=True)
    other = await _tenant()
    with pytest.raises(WriteRefusedError, match="not a Follow-up of this account"):
        await _propose(other, "follow_up_publish", args)
    for name in ("follow_up_draft", "follow_up_publish", "follow_up_start"):
        assert write_tools.tier_of(name) == "confirm"


# --- follow_up_start (plan) --------------------------------------------------------------


async def _plan_run(t: Tenant, plan_id: str) -> plans.PlanRow:
    await worker.run_copilot_plan({}, {"tenant_id": str(t.tenant_id), "plan_id": plan_id})
    async with tenant_session(t.tenant_id) as session:
        row = await plans.read_plan(session, UUID(plan_id))
    assert row is not None
    return row


async def _runs(t: Tenant, follow_up_id: UUID) -> int:
    async with tenant_session(t.tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM follow_up_runs WHERE follow_up_id = :f"),
                    {"f": follow_up_id},
                )
            ).scalar_one()
        )


async def test_start_is_a_plan_that_leaves_out_leads_already_in_it() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    lead_a, lead_b = await _lead(t), await _lead(t)
    args = {"follow_up_id": str(follow_up_id), "lead_ids": [str(lead_a), str(lead_b)]}
    with pytest.raises(WriteRefusedError, match="must be on"):
        await _propose(t, "follow_up_start", args)
    await _done(t, await _propose(t, "follow_up_publish", {"follow_up_id": str(follow_up_id)}))
    async with tenant_session(t.tenant_id) as session:
        await service.start_leads(session, follow_up_id, tenant_id=t.tenant_id, lead_ids=[lead_a])
    proposal = await _propose(t, "follow_up_start", args)
    assert proposal.plan_id is not None and "Already going through it. (1)" in proposal.summary
    assert proposal.cost == "It places no calls."
    await _done(t, proposal)
    finished = await _plan_run(t, proposal.plan_id)
    assert (finished.status, finished.done_count, finished.skipped_count) == ("done", 1, 1)
    assert await _runs(t, follow_up_id) == 2


async def test_the_route_starts_more_than_200_leads_as_an_approved_plan() -> None:
    t = await _tenant()
    follow_up_id = await _draft(t)
    await _done(t, await _propose(t, "follow_up_publish", {"follow_up_id": str(follow_up_id)}))
    for _ in range(201):
        await _lead(t)
    async with _client() as http:
        answer = await http.post(
            f"/v1/follow-ups/{follow_up_id}/start",
            json={"lens": {"status": "new"}, "expected_count": 201},
            headers=t.headers,
        )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["started"], body["skipped"]) == (0, 0) and body["plan_id"]
    finished = await _plan_run(t, body["plan_id"])
    assert (finished.tool, finished.origin, finished.done_count) == (
        "follow_up_start",
        "console",
        201,
    )
    assert await _runs(t, follow_up_id) == 201
    assert ("copilot.plan_approved", "copilot_plan", body["plan_id"]) in await _audit(t.tenant_id)

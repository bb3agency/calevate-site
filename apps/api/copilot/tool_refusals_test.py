"""Pip's tools refuse what the model got wrong in a way the model can correct, and never
hide from Pip an object the person can see.

The production failure this guards (24 Nov 2026): Pip passed a campaign's id where an
agent's goes, the planner raised "Agent not found", the loop relayed it as the platform's
final word, and the owner read "I could not finish this in one go". The campaign was also
cancelled, and the read Pip used to find it listed only open campaigns.

ENFORCED HERE:
- every model-facing planner call goes through `id_kinds.plan_correctably` (AST);
- across the whole client registry, an unknown id is never a `not_found` or `validation`
  `ProblemError` from planning (behavioural, one fresh tenant);
- the count of refusals with no person-facing `plain` only shrinks, per module (AST).

NOT ENFORCEABLE HERE, AND WHY: whether a `plain` sentence is short, actionable and names
no provider is prose judged by a reader; whether a status filter in a service hides
something a screen shows depends on the screen. The cases found are pinned one by one
below instead.
"""

from __future__ import annotations

import ast
import json
import uuid
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.conftest import make_tenant_with_pip as _make_tenant

from apps.api.copilot import areas, id_kinds, service, tools, write_tools
from apps.api.copilot.actions import REFUSED_PLAIN, WriteRefusedError
from apps.api.copilot.write_tools_test import _actor, _make_campaign, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import chat

_COPILOT = Path(__file__).parent


def _modules() -> list[Path]:
    return sorted(p for p in _COPILOT.glob("*.py") if not p.name.endswith("_test.py"))


def _enclosing_calls(tree: ast.AST, attr: str) -> list[tuple[str, ast.Call]]:
    """(enclosing function name, call) for every `<x>.<attr>(...)` call."""
    found: list[tuple[str, ast.Call]] = []

    def walk(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = (
                child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else owner
            )
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == attr
            ):
                found.append((owner, child))
            walk(child, name)

    walk(tree, "<module>")
    return found


# --- structural guards -------------------------------------------------------------------

#: Re-plans of a card the person already holds: its ids were checked when it was planned,
#: and a 404 now means the object went away, which is the platform's answer to relay.
_REPLANS_OF_A_HELD_CARD = {
    ("approval_preview.py", "preview_approval"),
    ("write_tools.py", "approve"),
}


def test_every_model_facing_plan_goes_through_plan_correctably() -> None:
    stray = sorted(
        (path.name, owner)
        for path in _modules()
        for owner, _call in _enclosing_calls(ast.parse(path.read_text("utf-8")), "plan")
        if (path.name, owner) not in _REPLANS_OF_A_HELD_CARD
    )
    assert stray == [], (
        "these call a planner directly, so a model's wrong id reaches the person as the "
        f"platform's final word; route them through `id_kinds.plan_correctably`: {stray}"
    )


#: Refusals per module that still fall back to `REFUSED_PLAIN` for the person. ONLY SHRINKS:
#: a new refusal carries its own `plain`, and a module not listed here must have none.
_PLAINLESS_BUDGET: dict[str, int] = {
    "account_actions.py": 20,
    "actions.py": 2,
    "admin_actions.py": 28,
    "agent_actions.py": 6,
    "agent_setup_actions.py": 19,
    "agent_tool_actions.py": 13,
    "assist_actions.py": 8,
    "call_actions.py": 10,
    "campaign_actions.py": 7,
    "console_actions.py": 28,
    "coverage_actions.py": 12,
    "fact_actions.py": 6,
    "follow_up_actions.py": 15,
    "knowledge_actions.py": 7,
    "lead_actions.py": 17,
    "pin_actions.py": 6,
    "plans.py": 1,
    "question_actions.py": 14,
    "routine_actions.py": 6,
    "service.py": 5,
    "set_actions.py": 6,
    "write_tools.py": 25,
}


def _plainless() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "WriteRefusedError")
                    or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "WriteRefusedError"
                    )
                )
                and not any(keyword.arg == "plain" for keyword in node.keywords)
            ):
                counts[path.name] += 1
    return counts


def test_refusals_without_a_plain_sentence_only_shrink() -> None:
    now = _plainless()
    grown = {
        name: (count, _PLAINLESS_BUDGET.get(name, 0))
        for name, count in now.items()
        if count > _PLAINLESS_BUDGET.get(name, 0)
    }
    assert grown == {}, (
        "new refusals with no `plain=` sentence for the person (now, allowed): "
        f"{grown}. Give each a short sentence that says what to do."
    )
    shrunk = {
        name: (now.get(name, 0), allowed)
        for name, allowed in _PLAINLESS_BUDGET.items()
        if now.get(name, 0) < allowed
    }
    assert shrunk == {}, f"lower `_PLAINLESS_BUDGET` to the new counts: {shrunk}"


def test_an_action_sent_to_the_wrong_area_is_told_which_area_has_it() -> None:
    surface = service.area_surface()
    owner = next(area for area, acts in surface.actions.items() if "campaign_launch" in acts)
    other = next(area for area, acts in surface.actions.items() if "campaign_launch" not in acts)
    call = chat.ToolCall(
        id="c1", name=other, arguments=json.dumps({"action": "campaign_launch", "args": {}})
    )
    with pytest.raises(areas.AreaCallError) as wrong:
        surface.resolve(call)
    assert f"it is in `{owner}`" in str(wrong.value)


# --- the whole registry: an unknown id is a correction, never the final word -----------


def _id_args(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Every property null except the ids, which are fresh uuids; None for a tool with no id."""
    props = schema["function"]["parameters"].get("properties", {})
    args: dict[str, Any] = {}
    any_id = False
    for key, spec in props.items():
        if key.endswith("_id"):
            args[key], any_id = str(uuid.uuid4()), True
        elif key.endswith("_ids") and "array" in json.dumps(spec):
            args[key], any_id = [str(uuid.uuid4())], True
        else:
            args[key] = None
    return args if any_id else None


async def test_no_client_tool_answers_an_unknown_id_with_the_platforms_final_word() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    escaped: list[str] = []
    for tool in write_tools.WRITE_TOOLS:
        args = _id_args(dict(tool.schema))
        if args is None:
            continue
        try:
            if tool.tier == "confirm":
                await write_tools.plan_write(
                    tool.name, json.dumps(args), actor=_actor(tenant_id, user_id)
                )
            else:
                await write_tools.run_immediate(
                    tool.name,
                    json.dumps(args),
                    principal=_principal(tenant_id, user_id),
                    seed=str(uuid.uuid4()),
                    ip=None,
                )
        except WriteRefusedError:
            continue
        except ProblemError as problem:
            if problem.kind in ("not_found", "validation"):
                escaped.append(f"{tool.name}: {problem.kind}")
        else:
            escaped.append(f"{tool.name}: planned against ids that name nothing")
    assert escaped == []


# --- wrong-kind ids name what they are and the way back -----------------------------------


async def _agent_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def test_a_campaign_id_where_an_agent_id_goes_names_the_campaigns_agent() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="cancelled")
    agent_id = await _agent_of(tenant_id)

    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "agent_deactivate",
            json.dumps({"agent_id": str(campaign_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "`agent_id` is the campaign “Winter checkup”, not an agent" in refused.value.reason
    assert f"its agent is agent_id {agent_id}" in refused.value.reason
    assert refused.value.plain == id_kinds.WRONG_ITEM_PLAIN


async def test_an_agent_id_where_a_campaign_id_goes_says_so() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)

    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_pause",
            json.dumps({"campaign_id": str(agent_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "`campaign_id` is the agent “" in refused.value.reason
    assert "not a campaign" in refused.value.reason


async def test_a_read_names_what_a_wrong_id_is_rather_than_saying_nothing_exists() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="cancelled")
    said = await _read("agent_detail", tenant_id, agent_id=str(campaign_id))
    assert "is the campaign “Winter checkup”, not an agent" in said


async def test_a_read_that_raises_a_problem_is_an_answer_not_an_outage() -> None:
    tenant_id, _slug, _token = await _make_tenant()

    async def missing(*_: Any) -> str:
        raise ProblemError.not_found("Campaign")

    tool = replace(tools.READ_TOOLS[0], run=missing)
    said = await tools.run_read_tool(
        tool.name,
        "{}",
        context=tools.ToolContext(tenant_id=tenant_id, role="owner"),
        registry={tool.name: tool},
    )
    assert said.startswith("Not read: Campaign not found.")
    assert "could not be read just now" not in said


# --- what the person sees on screen, Pip can find ---------------------------------------


async def _read(name: str, tenant_id: UUID, **args: Any) -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=tenant_id, role="owner"),
        registry=service._read_tool_registry("client"),
    )


async def test_campaigns_list_gives_the_ids_and_the_archived_campaigns() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    live = await _make_campaign(tenant_id, status="draft")
    archived = await _make_campaign(tenant_id, status="cancelled")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET archived_at = now(), archived_by_realm = 'client' "
                "WHERE id = :i"
            ),
            {"i": archived},
        )
    said = await _read("campaigns_list", tenant_id)
    assert f"[campaign_id {live}]" in said
    assert "Archived (restore one with `campaign_restore`" in said
    assert f"[campaign_id {archived}]" in said


async def test_an_agents_script_read_names_its_cancelled_campaign() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="cancelled")
    agent_id = await _agent_of(tenant_id)
    said = await _read("agent_settings", tenant_id, agent_id=str(agent_id), part="script")
    assert f"campaign “Winter checkup”, cancelled (campaign {campaign_id})" in said


async def test_leads_and_calls_lookups_print_the_ids_their_actions_take() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        lead = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar_one()
    said = await _read("leads_search", tenant_id)
    assert f"[lead_id {lead}]" in said


# --- statuses: refused with the reason and the way forward, before any card -------------


async def test_pausing_a_campaign_that_is_not_dialling_is_refused_before_the_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="cancelled")
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_pause",
            json.dumps({"campaign_id": str(campaign_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "cancelled" in refused.value.reason
    assert refused.value.plain == "That campaign was stopped, so there is nothing to pause."


async def test_launching_a_paused_campaign_points_to_resume() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="paused")
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_launch",
            json.dumps({"campaign_id": str(campaign_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "`campaign_resume`" in refused.value.reason
    assert refused.value.plain != REFUSED_PLAIN


async def test_a_repeating_running_campaign_can_be_stopped_from_repeating() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="running")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :i"),
            {"i": campaign_id, "s": json.dumps({"kind": "weekly", "days": [1], "at": "10:00"})},
        )
    proposal = await write_tools.plan_write(
        "campaign_unschedule",
        json.dumps({"campaign_id": str(campaign_id)}),
        actor=_actor(tenant_id, _user_of(token)),
    )
    assert proposal.title == "Stop this campaign repeating"


async def test_scheduling_beyond_the_horizon_asks_for_another_time_before_the_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    far = (datetime.now(UTC) + timedelta(days=400)).strftime("%Y-%m-%dT10:30")
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_schedule",
            json.dumps({"campaign_id": str(campaign_id), "start_at": far}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "ask the person for another time" in refused.value.reason


async def test_resuming_an_archived_campaign_is_refused_before_the_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="paused")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET archived_at = now(), archived_by_realm = 'client' "
                "WHERE id = :i"
            ),
            {"i": campaign_id},
        )
    with pytest.raises(ProblemError) as refused:
        await write_tools.plan_write(
            "campaign_resume",
            json.dumps({"campaign_id": str(campaign_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert refused.value.code == "campaign_archived"


async def test_deleting_an_agent_a_running_campaign_dials_through_is_refused_before_the_card() -> (
    None
):
    tenant_id, _slug, token = await _make_tenant()
    await _make_campaign(tenant_id, status="running")
    agent_id = await _agent_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :i"), {"i": agent_id}
        )
    with pytest.raises(ProblemError) as refused:
        await write_tools.plan_write(
            "agent_delete",
            json.dumps({"agent_id": str(agent_id)}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert refused.value.code == "agent_has_active_campaigns"


async def test_people_can_be_added_to_a_running_service_campaign() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="running")
    proposal = await write_tools.plan_write(
        "campaign_contacts_add",
        json.dumps(
            {
                "campaign_id": str(campaign_id),
                "contacts": [{"phone": "+919000000123", "name": "Asha", "columns": None}],
            }
        ),
        actor=_actor(tenant_id, _user_of(token)),
    )
    assert "They are called as the campaign goes on." in proposal.summary


async def test_people_are_not_added_to_a_started_promotional_campaign() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="running")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET classification = 'promotional' WHERE id = :i"),
            {"i": campaign_id},
        )
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_contacts_add",
            json.dumps(
                {
                    "campaign_id": str(campaign_id),
                    "contacts": [{"phone": "+919000000123", "name": "Asha", "columns": None}],
                }
            ),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "`campaign_clone`" in refused.value.reason


async def test_ticked_ids_that_are_not_leads_are_named_rather_than_dropped() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "campaign_add_leads",
            json.dumps(
                {"campaign_id": str(campaign_id), "lens": None, "lead_ids": [str(campaign_id)]}
            ),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "1 of the 1 `lead_ids` are not leads" in refused.value.reason
    assert "the campaign “Winter checkup”" in refused.value.reason


async def test_ticked_ids_that_are_not_call_backs_are_named_rather_than_dropped() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "callbacks_change_bulk",
            json.dumps(
                {
                    "change": "cancel",
                    "at": None,
                    "lens": None,
                    "callback_ids": [str(campaign_id)],
                }
            ),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert "are not call-backs of this account" in refused.value.reason


async def test_an_expired_invitation_says_to_invite_again() -> None:
    tenant_id, _slug, token = await _make_tenant()
    invitation_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
                "created_at) VALUES (:id, :t, 'late@example.com', 'staff', :h, "
                "now() - interval '1 day', now() - interval '4 days')"
            ),
            {"id": invitation_id, "t": tenant_id, "h": uuid.uuid4().hex},
        )
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "team_invitation",
            json.dumps({"invitation_id": str(invitation_id), "action": "resend"}),
            actor=_actor(tenant_id, _user_of(token)),
        )
    assert refused.value.plain == "That invitation has expired. Send a new one."


async def test_a_routine_past_the_cap_is_refused_before_the_card() -> None:
    from apps.api.copilot import routines

    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    async with tenant_session(tenant_id) as session:
        for n in range(routines.MAX_ROUTINES_PER_USER):
            await session.execute(
                text(
                    "INSERT INTO copilot_routines (id, tenant_id, user_id, name, instruction, "
                    "days, at_minute, enabled, created_at, updated_at) VALUES (:id, :t, :u, "
                    ":n, 'Tell me the day', 127, 600, false, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "u": user_id, "n": f"Routine {n}"},
            )
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.plan_write(
            "routine_create",
            json.dumps(
                {
                    "name": "One more",
                    "instruction": "Tell me the day",
                    "days": ["mon"],
                    "time": "09:00",
                }
            ),
            actor=_actor(tenant_id, user_id),
        )
    assert "`routine_delete`" in refused.value.reason

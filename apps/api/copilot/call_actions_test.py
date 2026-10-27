"""D-893 lane L1: Pip's call and call-back actions, each through its button's own function.

For every tool: the tier and permission the button has, the planner's refusal before a card,
the change through `confirm`, `run_immediate` or an approved plan with the button's audit
row, and an Undo where the tool is immediate. Plus the screen's door to a plan
(`POST /v1/copilot/plans`), which the Calls page's "call them again" uses.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.call_translation_test import _outbox_rows, _state, _telugu_call
from tests.lead_dial_routes_test import (  # reuse, never re-implement
    _daytime,  # noqa: F401  (an autouse fixture: 11:00 IST, so the clock never refuses)
    _dialable_tenant,
    _finished_call,
    _lead,
    _outbound_calls,
    _settle_calls,
)
from tests.swipe_actions_test import _grant_whatsapp_consent, _stub_whatsapp

from apps.api.billing.plans import IST
from apps.api.copilot import areas, call_actions, plans, write_tools
from apps.api.copilot.write_tools_test import _actor, _audit, _confirm, _principal, _user_of
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.workers.copilot_plans import run_copilot_plan


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _token_of(headers: dict[str, str]) -> str:
    return headers["Authorization"].split(" ", 1)[1]


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(_principal(tenant_id, _user_of(token)))
    )


def _tomorrow(hour: int) -> datetime:
    day = (datetime.now(IST) + timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, hour, tzinfo=IST)


# --- the registry ------------------------------------------------------------------------


def test_each_action_has_its_buttons_tier_permission_and_area() -> None:
    expected = {
        "call_back": ("confirm", "leads:dispatch", "calls"),
        "call_follow_up_set": ("immediate", "leads:write", "calls"),
        "call_translate": ("confirm", "org:manage", "calls"),
        "lead_whatsapp_send": ("confirm", "leads:dispatch", "calls"),
        "callbacks_change_bulk": ("confirm", "leads:dispatch", "callbacks"),
    }
    assert {tool.name for tool in call_actions.CALL_ACTIONS} == set(expected)
    for tool in call_actions.CALL_ACTIONS:
        tier, permission, area = expected[tool.name]
        assert (tool.tier, tool.permission, areas.AREA_OF[tool.name]) == (tier, permission, area)
    assert plans.set_action_of("callbacks_change_bulk") is call_actions.CHANGE_CALLBACKS
    start = write_tools.WRITE_TOOLS.index(call_actions.CALL_ACTIONS[0])
    assert (
        write_tools.WRITE_TOOLS[start : start + len(call_actions.CALL_ACTIONS)]
        == call_actions.CALL_ACTIONS
    )


# --- call_back ---------------------------------------------------------------------------


async def test_call_back_rings_through_the_buttons_function_once_per_call() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    token = _token_of(headers)
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)

    proposal = await _propose(tenant_id, token, "call_back", {"call_id": str(parent)})
    assert "cannot be taken back" in proposal.reversal
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert await _outbound_calls(tenant_id) == [(phone, "completed"), (phone, "queued")]
    actions = [action for action, _o, _i in await _audit(tenant_id)]
    assert "call.callback_dispatched" in actions and "call.callback_requested" in actions

    # The button pressed after Pip is answered from the same claim: one ring, not two.
    async with _client() as http:
        pressed = await http.post(f"/v1/calls/{parent}/callback", headers=headers)
    assert pressed.json()["status"] == "queued", pressed.text
    assert len(await _outbound_calls(tenant_id)) == 2
    await _settle_calls(tenant_id)


async def test_call_back_is_refused_with_the_gates_reason_before_any_card() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, created_at) "
                "VALUES (:id, :t, :p, 'tenant', 'manual', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
    with pytest.raises(write_tools.WriteRefusedError, match="cannot be placed"):
        await _propose(tenant_id, _token_of(headers), "call_back", {"call_id": str(parent)})
    assert await _outbound_calls(tenant_id) == [(phone, "completed")]


# --- call_follow_up_set ------------------------------------------------------------------


async def test_a_follow_up_mark_runs_at_once_and_undoes_with_a_compare_and_swap() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) SELECT :id, :t, id, :e, 'inbound', "
                "'completed', now(), now(), now() FROM agents LIMIT 1"
            ),
            {"id": call_id, "t": tenant_id, "e": f"fu-{uuid.uuid4().hex}"},
        )
    receipt = await write_tools.run_immediate(
        "call_follow_up_set",
        json.dumps({"call_id": str(call_id), "state": "resolved"}),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"l1-{uuid.uuid4()}",
        ip=None,
    )
    async with tenant_session(tenant_id) as session:
        mark = (
            await session.execute(
                text("SELECT follow_up_state FROM calls WHERE id = :i"), {"i": call_id}
            )
        ).scalar()
    assert mark == "resolved"
    assert "call.follow_up_marked" in [action for action, _o, _i in await _audit(tenant_id)]

    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        undone = await http.post(f"/v1/copilot/actions/{receipt.action_id}/undo", headers=headers)
    assert undone.status_code == 200, undone.text
    async with tenant_session(tenant_id) as session:
        mark = (
            await session.execute(
                text("SELECT follow_up_state FROM calls WHERE id = :i"), {"i": call_id}
            )
        ).scalar()
    assert mark is None

    # Someone marking it since makes the next Undo refuse rather than overwrite them.
    again = await write_tools.run_immediate(
        "call_follow_up_set",
        json.dumps({"call_id": str(call_id), "state": "needs_you"}),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"l1-{uuid.uuid4()}",
        ip=None,
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET follow_up_state = 'resolved' WHERE id = :i"), {"i": call_id}
        )
    async with _client() as http:
        refused = await http.post(f"/v1/copilot/actions/{again.action_id}/undo", headers=headers)
    assert refused.status_code >= 400, refused.text


# --- call_translate ----------------------------------------------------------------------


async def test_call_translate_queues_the_english_once_and_refuses_when_there_is_nothing() -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    token = _token_of(headers)
    proposal = await _propose(tenant_id, token, "call_translate", {"call_id": str(call_id)})
    assert proposal.cost is not None
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert await _state(tenant_id, call_id) == "pending"
    assert await _outbox_rows(call_id) == 1
    assert "call.translation_requested" in [action for action, _o, _i in await _audit(tenant_id)]
    with pytest.raises(write_tools.WriteRefusedError, match="nothing to make again"):
        await _propose(tenant_id, token, "call_translate", {"call_id": str(call_id)})


# --- lead_whatsapp_send ------------------------------------------------------------------


async def test_whatsapp_lists_the_approved_messages_then_sends_one_through_the_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_id, sent = _stub_whatsapp(monkeypatch)
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        lead = (await session.execute(text("SELECT id, phone_e164 FROM leads LIMIT 1"))).one()
    lead_id, phone = UUID(str(lead[0])), str(lead[1])

    with pytest.raises(write_tools.WriteRefusedError, match="not agreed"):
        await _propose(
            tenant_id,
            token,
            "lead_whatsapp_send",
            {"lead_id": str(lead_id), "template_id": None, "values": []},
        )
    await _grant_whatsapp_consent(tenant_id, phone)
    with pytest.raises(write_tools.WriteRefusedError) as menu:
        await _propose(
            tenant_id,
            token,
            "lead_whatsapp_send",
            {"lead_id": str(lead_id), "template_id": None, "values": []},
        )
    assert str(template_id) in menu.value.reason and "Business" in menu.value.reason
    with pytest.raises(write_tools.WriteRefusedError, match="1 blank"):
        await _propose(
            tenant_id,
            token,
            "lead_whatsapp_send",
            {"lead_id": str(lead_id), "template_id": str(template_id), "values": []},
        )
    proposal = await _propose(
        tenant_id,
        token,
        "lead_whatsapp_send",
        {"lead_id": str(lead_id), "template_id": str(template_id), "values": ["Sri Homes"]},
    )
    assert "Hi, this is Sri Homes following up." in proposal.summary
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True and len(sent) == 1
    actions = [action for action, _o, _i in await _audit(tenant_id)]
    assert "lead.whatsapp_follow_up" in actions and "lead.whatsapp_requested" in actions


# --- callbacks_change_bulk ---------------------------------------------------------------


async def _waiting_callbacks(tenant_id: UUID, n: int) -> list[UUID]:
    """`n` waiting call-backs on the account's own lead, each a client booking."""
    ids = [uuid7() for _ in range(n)]
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET direction = 'outbound', status = 'live'"))
        for index, callback_id in enumerate(ids):
            await session.execute(
                text(
                    "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, "
                    "source_execution_id, lead_id, phone_e164, requested_at, booked_at, status, "
                    "attempts, created_at, updated_at) SELECT :id, l.tenant_id, l.agent_id, :ex, "
                    "l.id, l.phone_e164, :at, now(), 'scheduled', 0, now(), now() "
                    "FROM leads l LIMIT 1"
                ),
                {
                    "id": callback_id,
                    "ex": f"client-schedule:{callback_id}",
                    "at": _tomorrow(10 + index),
                },
            )
    return ids


async def _statuses(tenant_id: UUID, ids: list[UUID]) -> list[tuple[str, datetime]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, status, requested_at FROM scheduled_callbacks WHERE id = ANY(:i)"),
                {"i": ids},
            )
        ).all()
    by_id = {UUID(str(r[0])): (str(r[1]), r[2]) for r in rows}
    return [by_id[i] for i in ids]


async def test_many_call_backs_are_moved_as_one_plan_and_an_ended_one_is_left_out() -> None:
    tenant_id, _slug, token = await _make_tenant()
    actor = _actor(tenant_id, _user_of(token))
    ids = await _waiting_callbacks(tenant_id, 3)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE scheduled_callbacks SET status = 'cancelled', settled_at = now() "
                "WHERE id = :i"
            ),
            {"i": ids[2]},
        )
    at = _tomorrow(15)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(write_tools.WriteRefusedError, match="9am and 9pm"):
            await plans.build_plan(
                session,
                actor,
                tool="callbacks_change_bulk",
                action=call_actions.CHANGE_CALLBACKS,
                args={"change": "move", "at": "2026-11-01T22:00", "callback_ids": [str(ids[0])]},
                origin="pip",
            )
        plan = await plans.build_plan(
            session,
            actor,
            tool="callbacks_change_bulk",
            action=call_actions.CHANGE_CALLBACKS,
            args={
                "change": "move",
                "at": at.strftime("%Y-%m-%dT%H:%M"),
                "callback_ids": [str(i) for i in ids],
            },
            origin="pip",
        )
        assert (plan.target_count, plan.excluded_count) == (3, 1)
        await plans.approve(session, actor, plan_id=plan.id, expected_hash=plan.plan_hash)
    await run_copilot_plan({}, {"tenant_id": str(tenant_id), "plan_id": str(plan.id)})
    after = await _statuses(tenant_id, ids)
    assert [status for status, _at in after] == ["scheduled", "scheduled", "cancelled"]
    assert after[0][1] == after[1][1] == at.astimezone(UTC)


async def test_a_move_whose_time_has_passed_by_approval_leaves_the_call_back_alone() -> None:
    tenant_id, _slug, token = await _make_tenant()
    actor = _actor(tenant_id, _user_of(token))
    ids = await _waiting_callbacks(tenant_id, 1)
    before = await _statuses(tenant_id, ids)
    gone = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    async with tenant_session(tenant_id) as session:
        outcome = await call_actions._run_change(
            session, actor, {"change": "move", "at": gone}, ids[0]
        )
    assert outcome == plans.TargetOutcome("skipped", "That time has passed.")
    assert await _statuses(tenant_id, ids) == before


async def test_waiting_call_backs_of_a_lens_are_called_off() -> None:
    tenant_id, _slug, token = await _make_tenant()
    actor = _actor(tenant_id, _user_of(token))
    ids = await _waiting_callbacks(tenant_id, 2)
    async with tenant_session(tenant_id) as session:
        plan = await plans.build_plan(
            session,
            actor,
            tool="callbacks_change_bulk",
            action=call_actions.CHANGE_CALLBACKS,
            args={"change": "cancel", "lens": {"callback_open": True}},
            origin="pip",
        )
        assert plan.target_count == 2 and plan.estimate_inr == 0
        await plans.approve(session, actor, plan_id=plan.id, expected_hash=plan.plan_hash)
    await run_copilot_plan({}, {"tenant_id": str(tenant_id), "plan_id": str(plan.id)})
    assert [status for status, _at in await _statuses(tenant_id, ids)] == ["cancelled"] * 2


# --- a screen's door to a plan -----------------------------------------------------------


async def test_a_screen_proposes_the_same_plan_and_nothing_runs_until_approved() -> None:
    tenant_id, slug, token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    ids = await _waiting_callbacks(tenant_id, 1)
    async with _client() as http:
        unknown = await http.post(
            "/v1/copilot/plans", headers=headers, json={"tool": "call_place", "args": {}}
        )
        empty = await http.post(
            "/v1/copilot/plans",
            headers=headers,
            json={
                "tool": "callbacks_change_bulk",
                "args": {"change": "cancel", "lens": {"status": "won"}},
            },
        )
        proposed = await http.post(
            "/v1/copilot/plans",
            headers=headers,
            json={
                "tool": "callbacks_change_bulk",
                "args": {"change": "cancel", "callback_ids": [str(ids[0])]},
            },
        )
    assert unknown.status_code == 422, unknown.text
    assert empty.status_code == 422 and empty.json()["type"].endswith("copilot_plan_refused")
    assert "tell the person" not in empty.json()["detail"]
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    assert body["status"] == "proposed" and body["origin"] == "console"
    assert [status for status, _at in await _statuses(tenant_id, ids)] == ["scheduled"]

"""D-893 F4: the security fixes found in the Pip inventory, each proved.

1. `callback_book` / `callback_reschedule` go through the call-back route's own function, so
   the 09:00-21:00 India window and the standing refusals apply before a card and at the
   click.
2. A Pip action whose console button needs an emailed code needs the same code at confirm
   (`ActionTool.action_code`); the proposal tells the browser which.
3. Confirmed actions with an exact inverse record `prior_state` and offer Undo.
4. `copilot_memories` holding a number's digits are reached by `execute_deletion_request`.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.deletion_request_test import _jobs
from tests.lead_dial_routes_test import _daytime  # noqa: F401  (autouse: 11:00 IST)

from apps.api.billing.plans import IST
from apps.api.compliance.deletion import request_erasure
from apps.api.copilot import write_tools
from apps.api.copilot.write_tools_test import _actor, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.workers.retention import execute_deletion_request


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _at(days: int, hour: int, minute: int = 0) -> str:
    when = (datetime.now(IST) + timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return when.strftime("%Y-%m-%dT%H:%M")


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _ids(tenant_id: UUID) -> tuple[UUID, UUID]:
    lead = await _one(tenant_id, "SELECT id FROM leads LIMIT 1")
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET direction = 'outbound', status = 'live'"))
    agent = await _one(tenant_id, "SELECT id FROM agents LIMIT 1")
    return UUID(str(lead[0])), UUID(str(agent[0]))


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=_actor(tenant_id, _user_of(token))
    )


async def _undo(token: str, slug: str, action_id: str) -> Any:
    async with _client() as http:
        return await http.post(
            f"/v1/copilot/actions/{action_id}/undo", headers=_headers(token, slug)
        )


async def _latest_action(tenant_id: UUID, tool: str) -> Any:
    return await _one(
        tenant_id,
        "SELECT id, prior_state, result_state, undoable_until FROM copilot_actions "
        "WHERE tool = :t ORDER BY created_at DESC LIMIT 1",
        t=tool,
    )


# --- 1. call-backs through the route's own function ---------------------------------------


async def test_a_callback_outside_the_window_is_refused_before_a_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, agent_id = await _ids(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError, match="9am and 9pm"):
        await _propose(
            tenant_id,
            token,
            "callback_book",
            {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(1, 22), "note": None},
        )


async def test_a_callback_to_a_number_on_do_not_call_is_refused_before_a_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, agent_id = await _ids(tenant_id)
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source) "
                "VALUES (:id, :t, :p, 'tenant', 'manual')"
            ),
            {"id": uuid7(), "t": tenant_id, "p": phone},
        )
    with pytest.raises(write_tools.WriteRefusedError, match="whatever the time"):
        await _propose(
            tenant_id,
            token,
            "callback_book",
            {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(1, 11), "note": None},
        )


async def test_a_booked_callback_is_the_routes_kind_and_its_undo_cancels_it() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id, agent_id = await _ids(tenant_id)
    proposal = await _propose(
        tenant_id,
        token,
        "callback_book",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(1, 11), "note": "price"},
    )
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied
    booked = await _one(
        tenant_id,
        "SELECT id, source_execution_id, status FROM scheduled_callbacks WHERE lead_id = :l",
        l=lead_id,
    )
    assert str(booked[1]).startswith("client-schedule:"), "the route's own booking"
    action = await _latest_action(tenant_id, "callback_book")
    assert action[1] == {"callback_id": None, "requested_at": None}
    assert action[2]["callback_id"] == str(booked[0]) and action[3] is not None
    response = await _undo(token, slug, str(action[0]))
    assert response.status_code == 200, response.text
    assert response.json()["detail"] == "The call-back is cancelled."
    status = await _one(
        tenant_id, "SELECT status FROM scheduled_callbacks WHERE id = :i", i=booked[0]
    )
    assert status[0] == "cancelled"


async def test_booking_again_moves_the_waiting_one_and_undo_moves_it_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id, agent_id = await _ids(tenant_id)
    first = await _propose(
        tenant_id,
        token,
        "callback_book",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(1, 11), "note": None},
    )
    await _confirm(tenant_id, _user_of(token), first.token)
    second = await _propose(
        tenant_id,
        token,
        "callback_book",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(2, 15), "note": None},
    )
    moved = await _confirm(tenant_id, _user_of(token), second.token)
    assert "moved" in moved.detail
    rows = await _one(
        tenant_id, "SELECT count(*) FROM scheduled_callbacks WHERE lead_id = :l", l=lead_id
    )
    assert rows[0] == 1, "moved, not doubled"
    action = await _latest_action(tenant_id, "callback_book")
    response = await _undo(token, slug, str(action[0]))
    assert response.status_code == 200, response.text
    assert response.json()["detail"].startswith("The call-back is back at")
    when = await _one(
        tenant_id, "SELECT requested_at FROM scheduled_callbacks WHERE lead_id = :l", l=lead_id
    )
    assert when[0].astimezone(IST).hour == 11


async def test_moving_a_callback_keeps_the_window_and_its_undo_moves_it_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id, agent_id = await _ids(tenant_id)
    booked = await _propose(
        tenant_id,
        token,
        "callback_book",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _at(1, 11), "note": None},
    )
    await _confirm(tenant_id, _user_of(token), booked.token)
    callback = await _one(
        tenant_id, "SELECT id FROM scheduled_callbacks WHERE lead_id = :l", l=lead_id
    )
    with pytest.raises(write_tools.WriteRefusedError, match="9am and 9pm"):
        await _propose(
            tenant_id,
            token,
            "callback_reschedule",
            {"callback_id": str(callback[0]), "at": _at(1, 6)},
        )
    move = await _propose(
        tenant_id, token, "callback_reschedule", {"callback_id": str(callback[0]), "at": _at(3, 16)}
    )
    await _confirm(tenant_id, _user_of(token), move.token)
    action = await _latest_action(tenant_id, "callback_reschedule")
    response = await _undo(token, slug, str(action[0]))
    assert response.status_code == 200, response.text
    when = await _one(
        tenant_id, "SELECT requested_at FROM scheduled_callbacks WHERE id = :i", i=callback[0]
    )
    assert when[0].astimezone(IST).hour == 11


# --- 2. the emailed code on Pip's confirm -------------------------------------------------


def test_buying_a_number_through_pip_asks_for_the_buttons_code() -> None:
    tool = write_tools.tool_named("number_buy")
    assert tool is not None and tool.action_code is not None
    assert tool.action_code({}) == "buy_number:{org}"


async def test_a_coded_action_is_refused_without_a_code_and_its_card_stays_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The code is demanded before the token is spent: a refusal for a missing code leaves
    the same card confirmable once the code is typed."""
    tenant_id, _slug, token = await _make_tenant()
    lead_id = (await _ids(tenant_id))[0]
    tool = write_tools.tool_named("lead_rename")
    assert tool is not None
    monkeypatch.setitem(
        write_tools._BY_NAME,
        "lead_rename",
        dataclasses.replace(tool, action_code=lambda _a: "rename_lead:{org}"),
    )
    proposal = await _propose(
        tenant_id, token, "lead_rename", {"lead_id": str(lead_id), "name": "Ravi K"}
    )
    assert proposal.confirm_action == "rename_lead:{org}"
    with pytest.raises(ProblemError) as missing:
        await _confirm(tenant_id, _user_of(token), proposal.token)
    assert missing.value.code == "step_up_required"

    asked: list[str] = []

    async def wrong(template: str) -> None:
        asked.append(template)
        raise ProblemError(kind="permission", code="action_code_required", title="x", detail="x")

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError):
            await write_tools.confirm(
                session,
                proposal.token,
                principal=_principal(tenant_id, _user_of(token)),
                ip=None,
                code_check=wrong,
            )
    assert asked == ["rename_lead:{org}"]

    async def right(template: str) -> None:
        asked.append(template)

    async with tenant_session(tenant_id) as session:
        done = await write_tools.confirm(
            session,
            proposal.token,
            principal=_principal(tenant_id, _user_of(token)),
            ip=None,
            code_check=right,
        )
    assert done.applied


async def test_the_confirm_route_sends_the_header_through_the_account_code_gate() -> None:
    """Over HTTP the template's `{org}` is this request's account slug, and a header for any
    other string is refused before anything runs."""
    from starlette.requests import Request

    from apps.api.core.stepup import ActionCode, account_code_check

    scope = {
        "type": "http",
        "headers": [(b"x-org-slug", b"acme")],
        "method": "POST",
        "path": "/",
    }
    check = account_code_check(ActionCode(realm="client", subject_id=None), Request(scope), "x")
    with pytest.raises(ProblemError) as refused:
        await check("buy_number:{org}")
    assert refused.value.code == "step_up_required"
    assert "buy_number:acme" in (refused.value.remediation or "")
    await account_code_check(
        ActionCode(realm="client", subject_id=None), Request(scope), "buy_number:acme"
    )("buy_number:{org}")


# --- 3. Undo on confirmed actions ----------------------------------------------------------


async def test_new_business_hours_can_be_undone_while_unchanged() -> None:
    tenant_id, slug, token = await _make_tenant()
    week = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    def hours(opens: str) -> list[dict[str, Any]]:
        return [{"day": d, "opens": opens, "closes": "18:00", "closed": False} for d in week]

    first = await _propose(tenant_id, token, "business_hours_set", {"hours": hours("09:00")})
    await _confirm(tenant_id, _user_of(token), first.token)
    second = await _propose(tenant_id, token, "business_hours_set", {"hours": hours("10:00")})
    await _confirm(tenant_id, _user_of(token), second.token)
    action = await _latest_action(tenant_id, "business_hours_set")
    assert action[1]["hours"]["mon"] == {"opens": "09:00", "closes": "18:00"}
    response = await _undo(token, slug, str(action[0]))
    assert response.status_code == 200, response.text
    stored = await _one(tenant_id, "SELECT hours FROM business_profiles")
    assert stored[0]["mon"]["opens"] == "09:00"
    again = await _undo(token, slug, str(action[0]))
    assert again.status_code == 409


async def test_a_campaign_schedule_can_be_undone_back_to_a_draft() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = (await _ids(tenant_id))[1]
    created = await write_tools.run_immediate(
        "campaign_create",
        json.dumps({"name": "Later", "agent_id": str(agent_id), "classification": "service"}),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"s-{uuid.uuid4()}",
        ip=None,
    )
    scheduled = await _propose(
        tenant_id,
        token,
        "campaign_schedule",
        {"campaign_id": created.object_id, "start_at": _at(2, 11)},
    )
    await _confirm(tenant_id, _user_of(token), scheduled.token)
    status = await _one(
        tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=UUID(created.object_id)
    )
    assert status[0] == "scheduled"
    action = await _latest_action(tenant_id, "campaign_schedule")
    response = await _undo(token, slug, str(action[0]))
    assert response.status_code == 200, response.text
    status = await _one(
        tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=UUID(created.object_id)
    )
    assert status[0] == "draft"


def test_every_immediate_action_has_an_undo_and_only_reviewed_confirm_ones_do() -> None:
    reviewed = {
        "callback_book",
        "callback_reschedule",
        "business_hours_set",
        "campaign_schedule",
        # D-893 L2: the previous field list is the exact inverse, restored under a CAS.
        "lead_source_mapping",
    }
    for tool in write_tools.WRITE_TOOLS:
        if tool.tier == "immediate":
            assert tool.undo is not None, tool.name
        else:
            assert (tool.undo is not None) == (tool.name in reviewed), tool.name


# --- 4. the assistant's notes are reached by a person's erasure ------------------------------


async def test_a_note_carrying_the_number_is_erased_with_the_person() -> None:
    tenant_id, _slug, token = await _make_tenant()
    phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        for content in (f"Call back {phone[3:]} about the quote", "Sunday opening is 10am"):
            await session.execute(
                text(
                    "INSERT INTO copilot_memories (id, tenant_id, user_id, kind, content, "
                    "screen_route, created_at, updated_at) VALUES (:id, :t, :u, 'semantic', "
                    ":c, NULL, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "u": _user_of(token), "c": content},
            )
        await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, (await _jobs(tenant_id))[0])
    async with tenant_session(tenant_id) as session:
        left = (await session.execute(text("SELECT content FROM copilot_memories"))).scalars().all()
    assert left == ["Sunday opening is 10am"]

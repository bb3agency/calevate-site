"""D-893 L7: Pip lists, sets up, changes, pauses and deletes the person's own routines.

Held to `docs/COPILOT-CONTRACT.md` §5: each planner's canonical arguments and refusals, the
confirm through `copilot/routines.py` (the Routines screen's functions) with the routes'
own audit actions, and the person scoping a routine carries.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.teach_questions_test import _owner, _tenant

from apps.api.copilot import routine_actions, routines, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.tools import ToolContext
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.db.session import tenant_session


async def _person(tenant_id: UUID) -> UUID:
    return _user_of(await _owner(tenant_id))


async def _propose(tenant_id: UUID, user_id: UUID, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(_principal(tenant_id, user_id))
    )


async def _routines(tenant_id: UUID, user_id: UUID) -> list[routines.RoutineRow]:
    async with tenant_session(tenant_id) as session:
        return await routines.list_routines(session, user_id=user_id, limit=20)


async def _list(tenant_id: UUID, user_id: UUID | None) -> str:
    async with tenant_session(tenant_id) as session:
        return await routine_actions.ROUTINES_LIST.run(
            session, ToolContext(tenant_id=tenant_id, role="owner", user_id=user_id), {}
        )


async def test_create_is_confirmed_then_saved_redacted_on_the_schedule_asked() -> None:
    tenant_id, _agent, _slug = await _tenant()
    user_id = await _person(tenant_id)
    proposal = await _propose(
        tenant_id,
        user_id,
        "routine_create",
        {
            "name": "Morning list",
            "instruction": "List yesterday's missed calls and ring 9876543210 back",
            "days": ["fri", "mon"],
            "time": "09:30",
        },
    )
    assert "Mon, Fri at 09:30 IST" in proposal.summary
    assert "9876543210" not in proposal.proposed
    assert await _routines(tenant_id, user_id) == []
    await _confirm(tenant_id, user_id, proposal.token)
    [row] = await _routines(tenant_id, user_id)
    assert (row.name, row.days, row.at_minute, row.enabled) == (
        "Morning list",
        0b0010001,
        570,
        True,
    )
    assert "9876543210" not in row.instruction
    assert ("copilot.routine_created", "copilot_routine") in [
        a[:2] for a in await _audit(tenant_id)
    ]
    listed = await _list(tenant_id, user_id)
    assert f"[{row.id}] Morning list · Mon, Fri at 09:30 IST · on, next" in listed


async def test_edit_pauses_and_resumes_and_delete_removes_it() -> None:
    tenant_id, _agent, _slug = await _tenant()
    user_id = await _person(tenant_id)
    created = await _propose(
        tenant_id,
        user_id,
        "routine_create",
        {
            "name": "Daily",
            "instruction": "Summarise calls",
            "days": list(routines.WEEKDAYS),
            "time": "18:00",
        },
    )
    await _confirm(tenant_id, user_id, created.token)
    [row] = await _routines(tenant_id, user_id)

    pause = await _propose(
        tenant_id, user_id, "routine_edit", {"routine": str(row.id), "on": False}
    )
    assert pause.title == "Switch a routine off"
    assert "every day at 18:00 IST, switched off" in pause.proposed
    await _confirm(tenant_id, user_id, pause.token)
    [paused] = await _routines(tenant_id, user_id)
    assert not paused.enabled and paused.next_run_at is None
    assert "switched off" in await _list(tenant_id, user_id)

    resume = await _propose(
        tenant_id, user_id, "routine_edit", {"routine": str(row.id), "on": True, "time": "07:05"}
    )
    await _confirm(tenant_id, user_id, resume.token)
    [resumed] = await _routines(tenant_id, user_id)
    assert resumed.enabled and resumed.at_minute == 425

    gone = await _propose(tenant_id, user_id, "routine_delete", {"routine": str(row.id)})
    assert "cannot be undone" in gone.reversal
    await _confirm(tenant_id, user_id, gone.token)
    assert await _routines(tenant_id, user_id) == []
    actions = [a for a, _t, _o in await _audit(tenant_id)]
    assert actions.count("copilot.routine_updated") == 2
    assert "copilot.routine_deleted" in actions


async def test_another_persons_routine_is_refused_and_not_listed() -> None:
    tenant_id, _agent, _slug = await _tenant()
    author = await _person(tenant_id)
    other = await _person(tenant_id)
    created = await _propose(
        tenant_id,
        author,
        "routine_create",
        {"name": "Mine", "instruction": "Check leads", "days": ["tue"], "time": "10:00"},
    )
    await _confirm(tenant_id, author, created.token)
    [row] = await _routines(tenant_id, author)
    with pytest.raises(WriteRefusedError, match="not one of this person's"):
        await _propose(tenant_id, other, "routine_delete", {"routine": str(row.id)})
    assert "no routines yet" in await _list(tenant_id, other)
    assert "none is asking" in await _list(tenant_id, None)


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"days": [], "time": "09:00"}, "each weekday"),
        ({"days": ["mon", "mon"], "time": "09:00"}, "each weekday"),
        ({"days": ["mon"], "time": "9am"}, "HH:MM"),
    ],
)
async def test_a_bad_schedule_is_refused_with_a_fix(args: dict[str, Any], reason: str) -> None:
    tenant_id, _agent, _slug = await _tenant()
    user_id = await _person(tenant_id)
    with pytest.raises(WriteRefusedError, match=reason):
        await _propose(
            tenant_id, user_id, "routine_create", {"name": "X", "instruction": "Do it", **args}
        )


async def test_an_edit_that_changes_nothing_is_refused() -> None:
    tenant_id, _agent, _slug = await _tenant()
    user_id = await _person(tenant_id)
    created = await _propose(
        tenant_id,
        user_id,
        "routine_create",
        {"name": "R", "instruction": "Check leads", "days": ["wed"], "time": "10:00"},
    )
    await _confirm(tenant_id, user_id, created.token)
    [row] = await _routines(tenant_id, user_id)
    with pytest.raises(WriteRefusedError, match="say what changes"):
        await _propose(tenant_id, user_id, "routine_edit", {"routine": str(row.id)})


async def test_routines_are_confirm_tier_and_tenant_scoped() -> None:
    for name in ("routine_create", "routine_edit", "routine_delete"):
        assert write_tools.tier_of(name) == "confirm"
    tenant_a, _a, _s = await _tenant()
    tenant_b, _b, _t = await _tenant()
    user_a = await _person(tenant_a)
    created = await _propose(
        tenant_a,
        user_a,
        "routine_create",
        {"name": "A", "instruction": "Check leads", "days": ["thu"], "time": "11:00"},
    )
    await _confirm(tenant_a, user_a, created.token)
    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM copilot_routines"))).scalar()
    assert seen == 0

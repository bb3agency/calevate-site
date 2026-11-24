"""Inbound lines (D-997): what a number says, in one agent's voice, on its own engine agent.

1. Lines and their sources are invisible across tenants (hard rule 1).
2. A line's engine agent is its own: published beside its agent's, never over it, routed for
   intake, and its numbers answer with it.
3. A silence on the voice agent (credit stop, compliance) silences its lines' numbers, and a
   restore gives each number back to its line.
4. Every number always has a line: one still answering cannot be archived.
5. A call its engine agent took is stamped with the line.
6. A number on a line, draft or live, is moved only from Inbound: Phone numbers and Pip
   refuse it by the line's name (D-1008).

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import _name_tag
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live
from apps.api.main import app
from apps.workers.pipeline import _STAMP_LINE_SQL
from calevate_shared.call_script import CallScript
from calevate_shared.engine import AgentConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _move, _number, _tenant, _write_script

pytestmark = pytest.mark.rls

SCRIPT = CallScript(opening_line="Namaste, Lifecycle Clinic. How can I help you today?")


async def _live_agent() -> tuple[UUID, UUID, str]:
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    return tenant_id, agent_id, token


async def _line(tenant_id: UUID, agent_id: UUID, *, script: bool = True) -> UUID:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        if script:
            await lines.save_script(session, line_id, SCRIPT, author="owner")
    return line_id


async def _attach(tenant_id: UUID, line_id: UUID, number_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await lines.assign_number(session, line_id, number_id)


def test_the_name_tag_keys_on_the_holder_and_leaves_the_agents_own_unchanged() -> None:
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Asha",
        direction="inbound",
        system_prompt="x",
        opening_line="",
    )
    own = _name_tag(cfg)
    line = _name_tag(cfg.model_copy(update={"holder": "line-1"}))
    other = _name_tag(cfg.model_copy(update={"holder": "line-2"}))
    assert len({own, line, other}) == 3
    # The agent's own tag is what it always was, so no live agent is renamed.
    assert own == _name_tag(cfg.model_copy(update={"holder": None}))


async def test_lines_and_their_sources_are_invisible_across_tenants() -> None:
    tenant_a, agent_a, _ = await _tenant()
    tenant_b, _agent_b, _ = await _tenant()
    line_id = await _line(tenant_a, agent_a)
    async with tenant_session(tenant_b) as session:
        assert await lines.list_lines(session) == []
        with pytest.raises(ProblemError) as missing:
            await lines.read_line(session, line_id)
        assert missing.value.status == 404
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM inbound_lines), "
                    "(SELECT count(*) FROM inbound_line_sources)"
                )
            )
        ).one()
    assert tuple(counts) == (0, 0)


async def test_a_live_line_answers_its_numbers_on_its_own_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    await _number(tenant_id, agent_id, ref="num_line_1")
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert agent_ref is not None
    line_id = await _line(tenant_id, agent_id)
    number_id = await _number_id(tenant_id, "num_line_1")
    await _attach(tenant_id, line_id, number_id)

    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    assert ref != agent_ref, "the line's engine agent was written over its agent's own"
    assert engine.inbound_agent_for("num_line_1") == ref
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        route = (
            await session.execute(
                text(
                    "SELECT agent_id, inbound_line_id FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    assert line.live and line.engine_agent_ref == ref
    assert (route.agent_id, route.inbound_line_id) == (agent_id, line_id)


async def test_a_silenced_voice_silences_its_lines_and_a_restore_gives_them_back() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    await _number(tenant_id, agent_id, ref="num_line_2")
    line_id = await _line(tenant_id, agent_id)
    await _attach(tenant_id, line_id, await _number_id(tenant_id, "num_line_2"))
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
        await agents_service.route_inbound_numbers(
            session, engine, agent_id=agent_id, ref=agent_ref, answers=False
        )
    assert engine.inbound_agent_for("num_line_2") is None
    async with tenant_session(tenant_id) as session:
        await agents_service.route_inbound_numbers(
            session, engine, agent_id=agent_id, ref=agent_ref, answers=True
        )
    assert engine.inbound_agent_for("num_line_2") == ref


async def test_a_line_that_still_answers_a_number_cannot_be_archived() -> None:
    tenant_id, agent_id, _ = await _tenant()
    line_id = await _line(tenant_id, agent_id, script=False)
    number_id = await _number(tenant_id, agent_id, ref="num_line_3")
    await _attach(tenant_id, line_id, number_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await lines.archive_line(session, line_id)
    assert refused.value.code == "line_answers_numbers"


async def test_a_call_its_engine_agent_took_is_stamped_with_the_line() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                "now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"exec-{uuid.uuid4().hex}"},
        )
        await session.execute(text(_STAMP_LINE_SQL), {"cid": call_id, "ref": ref, "tid": tenant_id})
        stamped = (
            await session.execute(
                text("SELECT inbound_line_id FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert stamped == line_id


async def test_a_line_with_no_script_is_refused_by_name() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id, script=False)
    with pytest.raises(ProblemError) as refused:
        await put_line_live(tenant_id=tenant_id, line_id=line_id)
    assert refused.value.code == "line_has_no_script"


async def _number_id(tenant_id: UUID, ref: str) -> UUID:
    async with tenant_session(tenant_id) as session:
        return UUID(
            str(
                (
                    await session.execute(
                        text("SELECT id FROM phone_numbers WHERE engine_number_ref = :r"),
                        {"r": ref},
                    )
                ).scalar_one()
            )
        )


async def _call(token: str, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.request(
            method,
            f"/v1/inbound-lines{path}",
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
    return response.status_code, response.json() if response.content else None


async def test_the_owner_starts_a_line_names_it_and_pip_needs_a_main_task() -> None:
    _tenant_id, agent_id, token = await _tenant()
    code, made = await _call(token, "POST", "", json={"agent_id": str(agent_id)})
    assert code == 201, made
    assert (made["name"], made["live"], made["numbers"]) == (lines.DEFAULT_NAME, False, [])
    code, refused = await _call(token, "POST", f"/{made['id']}/proposal")
    assert code == 422, refused
    assert refused["type"].endswith("/main_task_required")
    code, patched = await _call(
        token, "PATCH", f"/{made['id']}", json={"name": "Front desk", "main_task": "Book visits."}
    )
    assert code == 200, patched
    assert (patched["name"], patched["main_task"]) == ("Front desk", "Book visits.")
    code, listed = await _call(token, "GET", "")
    assert [line["id"] for line in listed["lines"]] == [made["id"]]


async def test_the_backfill_gives_every_answering_agents_numbers_a_draft_line() -> None:
    """The migration's backfill (`d8b2f5a7c3e1._BACKFILL`), run as the migration runs it:
    an agent answering a number gets one draft line carrying its live script, and the number
    is put on it; a released number and an agent with no number get nothing."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic" / "versions" / "d8b2f5a7c3e1_inbound_lines.py"
    spec = importlib.util.spec_from_file_location("inbound_lines_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    tenant_id, agent_id, _ = await _tenant()
    await _write_script(tenant_id, agent_id)
    number_id = await _number(tenant_id, agent_id, ref=f"num_bf_{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(text(migration._BACKFILL))
    async with tenant_session(tenant_id) as session:
        found = await lines.list_lines(session)
        on_number = (
            await session.execute(
                text("SELECT inbound_line_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
            )
        ).scalar_one()
    assert [(line.agent_id, line.live) for line in found] == [(agent_id, False)]
    assert on_number == found[0].id


async def _second_live_agent(tenant_id: UUID, token: str) -> UUID:
    from apps.api.agents import lifecycle

    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session, tenant_id=tenant_id, name="Ravi", direction="both", language_primary="te-IN"
        )
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    return agent_id


async def _own_ref(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar_one()
        )


async def test_a_draft_lines_numbers_follow_it_to_another_voice() -> None:
    """A draft line's numbers are answered by its voice agent's own engine agent, so giving
    the line another voice moves them there at once, not at that agent's next publish."""
    engine = _fresh_engine()
    tenant_id, first, token = await _live_agent()
    second = await _second_live_agent(tenant_id, token)
    number_id = await _number(tenant_id, first, ref="num_line_voice")
    line_id = await _line(tenant_id, first, script=False)
    code, body = await _call(
        token, "POST", f"/{line_id}/numbers", json={"number_id": str(number_id)}
    )
    assert code == 200, body
    assert engine.inbound_agent_for("num_line_voice") == await _own_ref(tenant_id, first)

    code, body = await _call(token, "PATCH", f"/{line_id}", json={"agent_id": str(second)})

    assert code == 200, body
    assert engine.inbound_agent_for("num_line_voice") == await _own_ref(tenant_id, second), (
        "the draft line's number still rings the voice it was moved off"
    )


async def test_a_live_lines_test_call_counts_only_numbers_its_engine_agent_answers() -> None:
    """A number counted as routed is rung from with no lend. While the voice is switched off
    the line's numbers answer nothing, so its test call must borrow one instead."""
    from apps.api.inbound.publish import line_test_dial

    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref="num_line_test_routed")
    line_id = await _line(tenant_id, agent_id)
    await _attach(tenant_id, line_id, number_id)
    await put_line_live(tenant_id=tenant_id, line_id=line_id)
    assert (await line_test_dial(tenant_id=tenant_id, line_id=line_id)).routed_number_ids == {
        number_id
    }

    code, body = await _move(token, agent_id, "deactivate")
    assert code == 200, body

    dial = await line_test_dial(tenant_id=tenant_id, line_id=line_id)
    assert dial.routed_number_ids == frozenset(), "a released number was dialled from unlent"


async def _assign(token: str, number_id: UUID, agent_id: UUID | None) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/numbers/{number_id}/assign",
            headers={"Authorization": f"Bearer {token}"},
            json={"agent_id": None if agent_id is None else str(agent_id), "direction": None},
        )
    return response.status_code, response.json()


async def _number_agent(tenant_id: UUID, number_id: UUID) -> UUID | None:
    async with tenant_session(tenant_id) as session:
        found: UUID | None = (
            await session.execute(
                text("SELECT agent_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
            )
        ).scalar_one()
    return found


async def test_a_number_on_a_live_line_is_refused_on_phone_numbers_by_the_lines_name() -> None:
    """FAILS IF: picking another agent for a live line's number on Phone numbers binds it to
    that agent's own engine agent while Inbound still lists it on the line (D-1008)."""
    engine = _fresh_engine()
    tenant_id, first, token = await _live_agent()
    second = await _second_live_agent(tenant_id, token)
    number_id = await _number(tenant_id, first, ref="num_line_clash")
    line_id = await _line(tenant_id, first)
    await _attach(tenant_id, line_id, number_id)
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    for agent_id in (second, None):
        code, body = await _assign(token, number_id, agent_id)
        assert code == 422, body
        assert body["type"].endswith("/number_on_inbound_line")
        assert "“Front desk”" in body["detail"] and "Inbound" in body["remediation"]
    assert await _number_agent(tenant_id, number_id) == first
    assert engine.inbound_agent_for("num_line_clash") == ref


async def test_a_number_on_a_draft_line_is_refused_too() -> None:
    """A draft line's numbers already answer with its voice, so the picker would split them
    from the line exactly as on a live one."""
    _fresh_engine()
    tenant_id, first, token = await _live_agent()
    second = await _second_live_agent(tenant_id, token)
    number_id = await _number(tenant_id, first, ref="num_draft_clash")
    line_id = await _line(tenant_id, first, script=False)
    await _attach(tenant_id, line_id, number_id)

    code, body = await _assign(token, number_id, second)

    assert code == 422, body
    assert body["type"].endswith("/number_on_inbound_line")
    assert await _number_agent(tenant_id, number_id) == first


async def test_inbound_still_moves_a_number_from_one_line_onto_another() -> None:
    engine = _fresh_engine()
    tenant_id, first, token = await _live_agent()
    second = await _second_live_agent(tenant_id, token)
    number_id = await _number(tenant_id, first, ref="num_line_move")
    old_line = await _line(tenant_id, first)
    await _attach(tenant_id, old_line, number_id)
    new_line = await _line(tenant_id, second, script=False)

    code, body = await _call(
        token, "POST", f"/{new_line}/numbers", json={"number_id": str(number_id)}
    )

    assert code == 200, body
    assert await _number_agent(tenant_id, number_id) == second
    assert engine.inbound_agent_for("num_line_move") == await _own_ref(tenant_id, second)


async def test_the_numbers_list_names_each_numbers_line() -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref="num_line_listed")
    line_id = await _line(tenant_id, agent_id, script=False)
    await _attach(tenant_id, line_id, number_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(
            "/v1/campaigns/numbers", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    (listed,) = [n for n in response.json() if n["id"] == str(number_id)]
    assert (listed["inbound_line_id"], listed["inbound_line_name"]) == (str(line_id), "Front desk")


async def test_pip_refuses_to_move_a_lines_number_in_words_before_any_card() -> None:
    from apps.api.copilot import write_tools
    from apps.api.copilot.write_tools_test import _principal, _user_of

    _fresh_engine()
    tenant_id, first, token = await _live_agent()
    second = await _second_live_agent(tenant_id, token)
    number_id = await _number(tenant_id, first, ref="num_line_pip")
    line_id = await _line(tenant_id, first, script=False)
    await _attach(tenant_id, line_id, number_id)

    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            "number_assign",
            json.dumps({"number_id": str(number_id), "agent_id": str(second), "direction": None}),
            actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
        )

    assert f"inbound_line {line_id}" in refused.value.reason
    assert "answers with your Inbound line “Front desk”" in refused.value.plain
    assert "Change it in Inbound" in refused.value.plain


async def test_a_bought_number_skips_a_line_in_a_deleted_agents_voice() -> None:
    """A bought number goes to the first line that can be put live. The oldest line spoke for
    an agent since deleted, which `publish_line` refuses, so the number rang nothing."""
    from apps.api.agents import lifecycle
    from apps.api.inbound.publish import onto_first_line

    _fresh_engine()
    tenant_id, deleted_id, _token = await _tenant()
    old_line = await _line(tenant_id, deleted_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": deleted_id},
        )
    number_id = await _number(tenant_id, deleted_id, f"num_buy_{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET agent_id = NULL WHERE id = :n"), {"n": number_id}
        )

    # Only the deleted agent's line: the number is left for the owner to put on a line.
    assert await onto_first_line(tenant_id=tenant_id, number_id=number_id) is None

    async with tenant_session(tenant_id) as session:
        voice_id = await lifecycle.create_agent(
            session, tenant_id=tenant_id, name="Ravi", direction="both", language_primary="te-IN"
        )
    new_line = await _line(tenant_id, voice_id)
    assert await onto_first_line(tenant_id=tenant_id, number_id=number_id) == new_line
    async with tenant_session(tenant_id) as session:
        on = (
            await session.execute(
                text("SELECT inbound_line_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
            )
        ).scalar_one()
    assert on == new_line != old_line


async def test_a_number_pip_buys_to_take_calls_goes_to_the_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pip's `number_buy` is the Buy button's twin: a number bought to take calls lands on the
    first line, since only a line answers a number (D-997, D-1019). One bought to call out
    only stays off every line."""
    from types import SimpleNamespace

    from apps.api.campaigns import engine_number_purchase
    from apps.api.copilot import console_actions, write_tools

    _fresh_engine()
    tenant_id, agent_id, _token = await _tenant()
    line_id = await _line(tenant_id, agent_id, script=False)
    answering = await _number(tenant_id, agent_id, f"num_pip_{uuid.uuid4().hex[:6]}")
    calling = await _number(tenant_id, agent_id, f"num_pip_{uuid.uuid4().hex[:6]}")
    bought = iter([answering, calling])

    async def purchase(**_kwargs: Any) -> Any:
        return SimpleNamespace(
            replayed=False,
            client_inr_per_month=None,
            attachment="not_applicable",
            number_id=next(bought),
        )

    monkeypatch.setattr(engine_number_purchase, "purchase_engine_number", purchase)
    actor = write_tools.ToolActor(
        tenant_id=tenant_id, user_id=uuid.uuid4(), role="owner", impersonating=False
    )
    for direction in ("both", "outbound"):
        await console_actions._execute_number_buy(
            None,  # type: ignore[arg-type]
            actor,
            {
                "city": "Hyderabad",
                "agent_id": None,
                "direction": direction,
                "number": "918012345671",
                "attempt": str(uuid.uuid4()),
            },
        )

    async with tenant_session(tenant_id) as session:
        placed = dict(
            (
                await session.execute(
                    text("SELECT id, inbound_line_id FROM phone_numbers WHERE id = ANY(:ids)"),
                    {"ids": [answering, calling]},
                )
            ).all()
        )
    assert placed == {answering: line_id, calling: None}

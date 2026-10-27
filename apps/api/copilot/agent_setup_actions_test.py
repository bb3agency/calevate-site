"""D-893 (L4): Pip's agent set-up actions, each held to `docs/COPILOT-CONTRACT.md` §5 —
the planner's canonical arguments and refusals, the change through `run_immediate` or
`confirm` with its audit row, the Undo where there is one, the permission inside the tool,
and another tenant's agent answered 404.

Every test mints its own tenant; `_make_tenant`'s agent is live with a script.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import accept_agreements, business_contact

from apps.api.agents import script_builder
from apps.api.copilot import write_tools
from apps.api.copilot.agent_reads import AGENT_SETTINGS_READ
from apps.api.copilot.tools import READ_TOOLS, ToolContext
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"setup-{name}-{json.dumps(args, sort_keys=True)}",
        ip=None,
    )


async def _propose(
    tenant_id: UUID, token: str, name: str, args: dict[str, Any], *, role: str = "owner"
) -> Any:
    return await write_tools.plan_write(
        name,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token), role=role)),
    )


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _agent(tenant_id: UUID) -> UUID:
    return UUID(str((await _one(tenant_id, "SELECT id FROM agents LIMIT 1"))[0]))


async def _status(tenant_id: UUID, agent_id: UUID) -> str:
    return str((await _one(tenant_id, "SELECT status FROM agents WHERE id = :a", a=agent_id))[0])


async def _set_status(tenant_id: UUID, agent_id: UUID, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = :s WHERE id = :a"), {"s": status, "a": agent_id}
        )


async def _archived(tenant_id: UUID, token: str) -> UUID:
    agent_id = await _agent(tenant_id)
    for name in ("agent_deactivate", "agent_delete"):
        proposal = await _propose(tenant_id, token, name, {"agent_id": str(agent_id)})
        await _confirm(tenant_id, _user_of(token), proposal.token)
    assert await _status(tenant_id, agent_id) == "archived"
    return agent_id


# --- agent_restore (immediate) ------------------------------------------------------------


async def test_restore_brings_a_deleted_agent_back_paused_and_undo_deletes_it_again() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _archived(tenant_id, token)

    receipt = await _run(tenant_id, token, "agent_restore", {"agent_id": str(agent_id)})
    assert receipt.applied is True
    assert await _status(tenant_id, agent_id) == "paused"
    assert "agent.restored" in {a for a, _o, _i in await _audit(tenant_id)}

    async with _client() as http:
        headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        undone = await http.post(f"/v1/copilot/actions/{receipt.action_id}/undo", headers=headers)
        assert undone.status_code == 200, undone.text
        again = await http.post(f"/v1/copilot/actions/{receipt.action_id}/undo", headers=headers)
    assert again.status_code == 409
    assert await _status(tenant_id, agent_id) == "archived"


async def test_restore_undo_is_refused_once_the_agent_has_moved_on() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _archived(tenant_id, token)
    receipt = await _run(tenant_id, token, "agent_restore", {"agent_id": str(agent_id)})
    await _set_status(tenant_id, agent_id, "live")
    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert undone.status_code == 409
    assert await _status(tenant_id, agent_id) == "live"


async def test_restore_refuses_an_agent_that_is_not_deleted() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_restore", {"agent_id": str(await _agent(tenant_id))})
    assert "not deleted" in refused.value.reason


# --- agent_prepare (confirm) --------------------------------------------------------------


async def test_prepare_publishes_a_draft_without_taking_calls() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await accept_agreements(tenant_id, _user_of(token))
    agent_id = await _agent(tenant_id)
    await _version(tenant_id, agent_id, "Hello.")
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "agent_prepare", {"agent_id": str(agent_id)})
    await _set_status(tenant_id, agent_id, "draft")
    proposal = await _propose(tenant_id, token, "agent_prepare", {"agent_id": str(agent_id)})
    assert "no calls" in proposal.summary
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert await _status(tenant_id, agent_id) == "paused"
    assert "agent.prepared" in {a for a, _o, _i in await _audit(tenant_id)}


# --- the Script tab's buttons ---------------------------------------------------------------


async def _save_draft(tenant_id: UUID, agent_id: UUID, identity: str) -> None:
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(
            session, agent_id, CallScript(schema_version=2, identity=identity)
        )


async def _version(tenant_id: UUID, agent_id: UUID, identity: str) -> None:
    """A saved script version: applied on an agent with none yet, staged on a live one."""
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(schema_version=2, identity=identity),
            notes=identity,
            created_by=None,
        )


async def _staged(tenant_id: UUID, agent_id: UUID) -> bool:
    row = await _one(
        tenant_id,
        "SELECT system_prompt_id IS DISTINCT FROM live_prompt_id FROM agents WHERE id = :a",
        a=agent_id,
    )
    return bool(row[0])


async def test_put_live_saves_the_reviewed_draft_as_a_version() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    args = {"agent_id": str(agent_id), "summary": "New greeting"}
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "agent_script_put_live", args)
    assert "nothing to put live" in refused.value.reason

    await _save_draft(tenant_id, agent_id, "Hello from Pip.")
    proposal = await _propose(tenant_id, token, "agent_script_put_live", args)
    assert "New greeting" in proposal.summary
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        assert await script_builder.read_draft(session, agent_id) is None
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.script.identity == "Hello from Pip."
    assert "agent.script_published" in {a for a, _o, _i in await _audit(tenant_id)}


async def test_put_live_refuses_a_draft_changed_after_the_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    await _save_draft(tenant_id, agent_id, "First.")
    proposal = await _propose(
        tenant_id, token, "agent_script_put_live", {"agent_id": str(agent_id), "summary": "x"}
    )
    await _save_draft(tenant_id, agent_id, "Changed since.")
    with pytest.raises(ProblemError) as moved:
        await _confirm(tenant_id, _user_of(token), proposal.token)
    assert moved.value.code == "script_changed_elsewhere"


async def test_discard_drops_a_saved_change_callers_never_heard() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    args = {"agent_id": str(agent_id)}
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "agent_script_discard", args)
    await _version(tenant_id, agent_id, "Live.")
    # On the calling system, so the next save is staged rather than applied.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_staged_test' WHERE id = :a"),
            {"a": agent_id},
        )
    await _version(tenant_id, agent_id, "Staged.")
    assert await _staged(tenant_id, agent_id)
    proposal = await _propose(tenant_id, token, "agent_script_discard", args)
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert not await _staged(tenant_id, agent_id)
    assert "agent.changes_undone" in {a for a, _o, _i in await _audit(tenant_id)}


async def test_version_restore_copies_a_version_into_the_draft() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    await _version(tenant_id, agent_id, "First.")
    first = await _one(
        tenant_id, "SELECT min(version) FROM prompt_versions WHERE agent_id = :a", a=agent_id
    )
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "agent_script_version_restore",
            {"agent_id": str(agent_id), "version": 999},
        )
    proposal = await _propose(
        tenant_id,
        token,
        "agent_script_version_restore",
        {"agent_id": str(agent_id), "version": int(first[0])},
    )
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        assert await script_builder.read_draft(session, agent_id) is not None
    assert "agent.script_version_restored" in {a for a, _o, _i in await _audit(tenant_id)}


# --- agent_settings_set -----------------------------------------------------------------------


def _settings(agent_id: UUID, **changes: str) -> dict[str, Any]:
    return {
        "agent_id": str(agent_id),
        "changes": [{"setting": k, "value": v} for k, v in changes.items()],
    }


async def test_settings_are_shown_then_written_through_each_writer() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    proposal = await _propose(
        tenant_id,
        token,
        "agent_settings_set",
        _settings(
            agent_id,
            speed="1.1",
            turn_silence_ms="900",
            longest_call_minutes="5",
            caller_memory="off",
            ai_model="default",
        ),
    )
    assert "speaking speed: 1.1" in proposal.proposed
    assert "longest one call may run: 5 min" in proposal.proposed
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    row = await _one(
        tenant_id,
        "SELECT studio_voice_speed, turn_silence_ms, max_call_duration_s FROM agents WHERE id = :a",
        a=agent_id,
    )
    assert (str(row[0]), row[1], row[2]) == ("1.10", 900, 300)
    assert "agent.settings_set" in {a for a, _o, _i in await _audit(tenant_id)}


async def test_settings_refusals_are_handed_back_before_any_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    cases = [
        (_settings(agent_id, volume="1.2"), "Studio voice"),
        (_settings(agent_id, caller_memory="on"), "confirm what these calls collect"),
        (_settings(agent_id, end_call_on_finish="maybe"), "`on` or `off`"),
        (_settings(agent_id, longest_call_minutes="500"), "longest_call_minutes"),
        (_settings(agent_id, ambience="loud"), "`ambience`"),
    ]
    for args, words in cases:
        with pytest.raises(write_tools.WriteRefusedError) as refused:
            await _propose(tenant_id, token, "agent_settings_set", args)
        assert words in refused.value.reason, args
    with pytest.raises(ProblemError) as out_of_range:
        await _propose(
            tenant_id, token, "agent_settings_set", _settings(agent_id, turn_silence_ms="10")
        )
    assert out_of_range.value.code == "turn_silence_out_of_range"


async def test_staff_may_change_the_longest_call_and_nothing_else() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    allowed = await _propose(
        tenant_id,
        token,
        "agent_settings_set",
        _settings(agent_id, longest_call_minutes="7"),
        role="staff",
    )
    done = await _confirm(tenant_id, _user_of(token), allowed.token, role="staff")
    assert done.applied is True
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "agent_settings_set",
            _settings(agent_id, speed="1.1"),
            role="staff",
        )
    assert "only the account owner" in refused.value.reason


async def test_settings_for_all_agents_go_through_the_all_agents_writer() -> None:
    """The Settings tab's "All my agents": the shared value is set and every agent's own is
    dropped, by the one writer the page's save calls."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ambience = 'office', ambience_volume_pct = 40 WHERE id = :a"),
            {"a": agent_id},
        )
    args = {**_settings(agent_id, ambience="office-quiet"), "scope": "all_agents"}
    proposal = await _propose(tenant_id, token, "agent_settings_set", args)
    assert proposal.title == "Change how your agents handle calls"
    assert "every agent's background sound: office-quiet" in proposal.proposed
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    own = await _one(tenant_id, "SELECT ambience FROM agents WHERE id = :a", a=agent_id)
    assert own[0] is None
    shared = await _one(tenant_id, "SELECT default_ambience FROM organizations")
    assert shared[0] == "office-quiet"


async def test_waiting_for_hello_is_never_set_for_all_agents() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    args = {**_settings(agent_id, opening_waits_for_caller="on"), "scope": "all_agents"}
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "agent_settings_set", args)
    assert "set per agent" in refused.value.reason


# --- agent_handover_set ------------------------------------------------------------------------


async def test_handover_names_people_never_numbers_and_saves_the_list() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    contact = await business_contact(tenant_id, phone="+919000000711", label="Priya")
    args = {
        "agent_id": str(agent_id),
        "enabled": True,
        "trigger": None,
        "members": [{"contact_id": str(contact), "active": True}],
    }
    proposal = await _propose(tenant_id, token, "agent_handover_set", args)
    assert "Priya" in proposal.summary
    assert "9000000711" not in json.dumps(proposal.model_dump(mode="json"))
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    row = await _one(
        tenant_id,
        "SELECT a.handoff_enabled, m.contact_id FROM agents a "
        "JOIN agent_handoff_members m ON m.agent_id = a.id WHERE a.id = :a",
        a=agent_id,
    )
    assert (row[0], UUID(str(row[1]))) == (True, contact)

    other_id, _s, _t = await _make_tenant()
    foreign = await business_contact(other_id, phone="+919000000712", label="Ravi")
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "agent_handover_set",
            {**args, "members": [{"contact_id": str(foreign), "active": True}]},
        )


# --- every action: another tenant's agent, and the read --------------------------------------


async def test_a_neighbours_agent_is_a_404_for_every_setup_action() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _s, _t = await _make_tenant()
    foreign = str(await _agent(other_id))
    calls: dict[str, dict[str, Any]] = {
        "agent_prepare": {"agent_id": foreign},
        "agent_script_put_live": {"agent_id": foreign, "summary": "x"},
        "agent_script_discard": {"agent_id": foreign},
        "agent_script_version_restore": {"agent_id": foreign, "version": 1},
        "agent_settings_set": _settings(UUID(foreign), speed="1.1"),
        "agent_handover_set": {
            "agent_id": foreign,
            "enabled": False,
            "trigger": None,
            "members": None,
        },
    }
    for name, args in calls.items():
        with pytest.raises(ProblemError) as crossed:
            await _propose(tenant_id, token, name, args)
        assert crossed.value.status == 404, name


@pytest.mark.parametrize("part", ["settings", "script", "handover", "actions", "lead_fields"])
async def test_agent_settings_reads_each_part_without_a_phone_number(part: str) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    await business_contact(tenant_id, phone="+919000000713", label="Asha")
    async with tenant_session(tenant_id) as session:
        answer = await AGENT_SETTINGS_READ.run(
            session,
            ToolContext(tenant_id=tenant_id, role="owner"),
            {"agent_id": str(agent_id), "part": part},
        )
    assert f"[agent_id {agent_id}]" in answer
    assert "9000000713" not in answer
    if part == "handover":
        assert "Asha" in answer


async def test_agents_list_gives_each_agent_its_id_and_names_the_deleted_ones() -> None:
    """FAILS IF: Pip, asked from the dashboard to act on an agent by name, has no id to act
    on, or cannot find a deleted agent to restore."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _archived(tenant_id, token)
    (agents_list,) = [tool for tool in READ_TOOLS if tool.name == "agents_list"]
    async with tenant_session(tenant_id) as session:
        answer = await agents_list.run(
            session, ToolContext(tenant_id=tenant_id, role="owner"), {"limit": None}
        )
    assert f"[agent_id {agent_id}]" in answer
    assert "agent_restore" in answer

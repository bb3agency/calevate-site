"""D-893 (L4): Pip's in-call action and lead-detail actions, held to
`docs/COPILOT-CONTRACT.md` §5: canonical arguments and refusals, the change through `confirm`
with its audit row, and another tenant's objects answered as absent.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.action_save_trial_test import BOOK_A_TIME
from tests.api_security_test import _make_tenant
from tests.lead_fields_test import _business_keys, _request, _run_worker
from tests.lead_fields_test import _tenant as _lead_fields_tenant
from tests.lead_suggestions_test import _bhk_agent, _fields, _item, _seed

from apps.api.actions import credentials as creds
from apps.api.copilot import write_tools
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
    )


async def _yes(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    proposal = await _propose(tenant_id, token, name, args)
    return await _confirm(tenant_id, _user_of(token), proposal.token)


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _agent_with_calendar() -> tuple[UUID, str, UUID, UUID]:
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = UUID(str((await session.execute(text("SELECT id FROM agents"))).scalar()))
        calendar = await creds.create_credential(
            session,
            tenant_id=tenant_id,
            kind="google_calendar",
            label="Google Calendar",
            secret="1//test-refresh-token",
            non_secret={},
        )
    return tenant_id, token, agent_id, calendar.id


def _new_action(agent_id: UUID, connection: UUID, **overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "agent_id": str(agent_id),
        "action_id": None,
        "kind": BOOK_A_TIME["kind"],
        "provider": BOOK_A_TIME["provider"],
        "name": BOOK_A_TIME["name"],
        "description": BOOK_A_TIME["description"],
        "trigger": "during_call",
        "pre_call_message": None,
        "connection_id": str(connection),
        "params_json": json.dumps(BOOK_A_TIME["params"]),
        "config_json": json.dumps(BOOK_A_TIME["config"]),
    }
    return {**args, **overrides}


def _unchanged(agent_id: UUID, action_id: str, **changes: Any) -> dict[str, Any]:
    keep = dict.fromkeys(
        (
            "kind",
            "provider",
            "name",
            "description",
            "trigger",
            "pre_call_message",
            "connection_id",
            "params_json",
            "config_json",
        )
    )
    return {"agent_id": str(agent_id), "action_id": action_id, **keep, **changes}


async def test_an_action_is_added_changed_switched_and_removed_through_the_tab_writers() -> None:
    tenant_id, token, agent_id, calendar = await _agent_with_calendar()

    added = await _yes(tenant_id, token, "agent_action_set", _new_action(agent_id, calendar))
    assert added.applied is True
    row = await _one(tenant_id, "SELECT id, kind, enabled FROM action_tools")
    action_id = str(row[0])
    assert (row[1], row[2]) == ("calendar", True)

    await _yes(
        tenant_id,
        token,
        "agent_action_set",
        _unchanged(agent_id, action_id, description="Book a slot once the caller picks a time."),
    )
    row = await _one(tenant_id, "SELECT kind, description FROM action_tools")
    assert tuple(row) == ("calendar", "Book a slot once the caller picks a time.")

    switch = {"agent_id": str(agent_id), "action_id": action_id, "enabled": False}
    await _yes(tenant_id, token, "agent_action_switch", switch)
    assert (await _one(tenant_id, "SELECT enabled FROM action_tools"))[0] is False
    await _yes(tenant_id, token, "agent_action_switch", {**switch, "action_id": None})
    master = await _one(
        tenant_id, "SELECT api_actions_enabled FROM agents WHERE id = :a", a=agent_id
    )
    assert master[0] is False

    await _yes(
        tenant_id, token, "agent_action_remove", {"agent_id": str(agent_id), "action_id": action_id}
    )
    assert await _one(tenant_id, "SELECT id FROM action_tools") is None
    audited = {a for a, _o, _i in await _audit(tenant_id)}
    assert {"action_tool.saved", "action_tool.switched", "action_tool.deleted"} <= audited


async def test_an_action_the_tab_would_refuse_is_refused_before_a_card() -> None:
    tenant_id, token, agent_id, calendar = await _agent_with_calendar()
    with pytest.raises(write_tools.WriteRefusedError) as missing:
        await _propose(
            tenant_id, token, "agent_action_set", _new_action(agent_id, calendar, kind=None)
        )
    assert "`kind`" in missing.value.reason
    with pytest.raises(ProblemError) as bad:
        await _propose(
            tenant_id,
            token,
            "agent_action_set",
            _new_action(agent_id, calendar, config_json=json.dumps({"operation": "book"})),
        )
    assert bad.value.code == "action_config_invalid"
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "agent_action_switch",
            {"agent_id": str(agent_id), "action_id": str(agent_id), "enabled": True},
        )


async def test_another_tenants_connection_or_agent_is_absent() -> None:
    tenant_id, token, agent_id, _calendar = await _agent_with_calendar()
    _other, _t, other_agent, other_calendar = await _agent_with_calendar()
    with pytest.raises(ProblemError) as crossed:
        await _propose(tenant_id, token, "agent_action_set", _new_action(agent_id, other_calendar))
    assert crossed.value.status == 404
    with pytest.raises(ProblemError) as foreign:
        await _propose(
            tenant_id,
            token,
            "agent_action_switch",
            {"agent_id": str(other_agent), "action_id": None, "enabled": False},
        )
    assert foreign.value.status == 404


# --- lead details ------------------------------------------------------------------------------


async def test_the_drafted_lead_details_are_kept_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, token = await _lead_fields_tenant("custom")
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "lead_fields_keep_draft", {"keep": ["produce"]})
    await _request(tenant_id)
    await _run_worker(tenant_id, monkeypatch)
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "lead_fields_keep_draft", {"keep": ["nonsense"]})
    proposal = await _propose(tenant_id, token, "lead_fields_keep_draft", {"keep": ["produce"]})
    assert "Produce" in proposal.summary
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert all("produce" in keys for keys in await _business_keys(tenant_id))
    with pytest.raises(write_tools.WriteRefusedError) as again:
        await _propose(tenant_id, token, "lead_fields_keep_draft", {"keep": []})
    assert "already" in again.value.reason
    assert "lead_fields.draft_reviewed" in {a for a, _o, _i in await _audit(tenant_id)}


async def test_reset_puts_the_standard_set_on_every_agent() -> None:
    tenant_id, token = await _lead_fields_tenant("retail")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE extraction_schemas SET fields = '[]'::jsonb WHERE id IN "
                "(SELECT extraction_schema_id FROM agents)"
            )
        )
    done = await _yes(tenant_id, token, "lead_fields_reset", {"agent_ids": None})
    assert done.applied is True
    assert all(keys for keys in await _business_keys(tenant_id))
    with pytest.raises(ProblemError):
        custom_id, custom_token = await _lead_fields_tenant("custom")
        await _propose(custom_id, custom_token, "lead_fields_reset", {"agent_ids": None})


async def test_a_suggestion_is_accepted_or_turned_down() -> None:
    tenant_id, _slug, token, agent_id = await _bhk_agent()
    add, new = await _seed(
        tenant_id,
        agent_id,
        _item("add_choices", values=["6BHK"], reason="3 callers asked for 6BHK."),
        _item("new_field", label="Facing", values=["East", "West"], source="script"),
    )
    before, _fields_before = await _fields(tenant_id, agent_id)
    base = {"agent_id": str(agent_id)}
    accepted = await _yes(
        tenant_id,
        token,
        "lead_suggestion_answer",
        {**base, "suggestion_id": add.id, "accept": True},
    )
    assert accepted.applied is True
    after, fields = await _fields(tenant_id, agent_id)
    assert after == before + 1
    assert "6BHK" in json.dumps(fields)
    await _yes(
        tenant_id,
        token,
        "lead_suggestion_answer",
        {**base, "suggestion_id": new.id, "accept": False},
    )
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "lead_suggestion_answer",
            {**base, "suggestion_id": new.id, "accept": True},
        )
    assert "agent.lead_suggestion_answered" in {a for a, _o, _i in await _audit(tenant_id)}

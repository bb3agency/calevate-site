"""D-698: the console actions, each held to `docs/COPILOT-CONTRACT.md` §5.

For every tool: the planner's canonical arguments and refusals; the change through
`run_immediate` or `confirm` with its `audit_log` and `copilot_actions` rows; for an
immediate tool the Undo, its compare-and-swap refusal, a second Undo and another tenant's
id; the permission refused inside the tool; and the tier, enumerated from the registry.

Every test mints its own tenant. Redis holds only per-proposal `jti` markers.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.lead_dial_routes_test import (  # reuse, never re-implement
    _daytime,  # noqa: F401  (an autouse fixture: 11:00 IST, so the clock never refuses)
    _dialable_tenant,
    _lead,
    _settle_calls,
)

from apps.api.copilot import action_log, write_tools
from apps.api.copilot.console_actions import CONSOLE_ACTIONS
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import Permission, role_has
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app

IST = ZoneInfo("Asia/Kolkata")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"console-{uuid.uuid4()}",
        ip=None,
    )


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
    )


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _agent_of(tenant_id: UUID) -> UUID:
    row = await _one(tenant_id, "SELECT id FROM agents LIMIT 1")
    return UUID(str(row[0]))


async def _lead_of(tenant_id: UUID) -> UUID:
    row = await _one(tenant_id, "SELECT id FROM leads LIMIT 1")
    return UUID(str(row[0]))


async def _action_row(tenant_id: UUID, action_id: str) -> Any:
    return await _one(
        tenant_id,
        "SELECT status, tier, prior_state, result_state FROM copilot_actions WHERE id = :i",
        i=UUID(action_id),
    )


def _later(days: int = 2, hour: int = 11) -> str:
    when = (datetime.now(IST) + timedelta(days=days)).replace(hour=hour, minute=0, second=0)
    return when.strftime("%Y-%m-%dT%H:%M")


# --- the registry ------------------------------------------------------------------------


#: The console actions that run without a click, each with the reason it is safe.
_IMMEDIATE = {
    "lead_assign": "an owner pointer; the prior owner's id is the exact inverse",
    "campaign_create": "a draft dials nobody; Undo cancels it while empty",
    "campaign_clone": "a draft copy without contacts; Undo cancels it while empty",
    "agent_edit": "refuses a live agent, so no caller hears it; prior settings restored",
    "agent_capture_fields_set": "field definitions, not a call; the prior list is restored",
}

#: Every one that dials, spends, publishes, deletes, changes DNC or reaches a caller.
_MUST_CONFIRM = {
    "call_place",
    "callback_book",
    "callback_reschedule",
    "callback_cancel",
    "campaign_add_leads",
    "campaign_schedule",
    "campaign_resume",
    "agent_edit_live",
    "agent_changes_apply",
    "agent_deactivate",
    "agent_delete",
    "business_hours_set",
    "dnc_remove",
    "knowledge_link_add",
    "knowledge_remove",
    "number_buy",
    "number_release",
    "agent_test_call",
    "business_profile_set",
}


def test_the_console_actions_are_appended_after_the_earlier_ones() -> None:
    names = [tool.name for tool in write_tools.WRITE_TOOLS]
    console = [tool.name for tool in CONSOLE_ACTIONS]
    assert names[-len(console) :] == console
    assert len(set(names)) == len(names)


def test_only_the_reviewed_console_actions_skip_the_click() -> None:
    immediate = {tool.name for tool in CONSOLE_ACTIONS if tool.tier == "immediate"}
    assert immediate == set(_IMMEDIATE)
    for name in _MUST_CONFIRM:
        assert write_tools.tier_of(name) == "confirm", name
    for tool in CONSOLE_ACTIONS:
        assert (tool.undo is not None) == (tool.tier == "immediate"), tool.name


def test_no_tool_accepts_terms_the_pledge_or_uploads_kyc() -> None:
    """D-694: only the owner accepts legal documents or the pledge, and nobody uploads KYC
    through the assistant. No such tool may exist in either registry."""
    for tool in write_tools.WRITE_TOOLS:
        lowered = tool.name.lower()
        for word in ("pledge", "accept", "agreement", "kyc", "upload", "legal"):
            assert word not in lowered, tool.name


# --- permission, inside the tool -----------------------------------------------------------


def _role_without(permission: Permission) -> str:
    # `kb:write` for staff is also the owner's curation switch, so it is not a clean "no".
    if permission != "kb:write" and not role_has("staff", permission):
        return "staff"
    return "ghost"


@pytest.mark.parametrize("tool", CONSOLE_ACTIONS, ids=lambda tool: tool.name)
async def test_a_role_without_the_buttons_permission_is_refused_inside_the_tool(tool: Any) -> None:
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token), role=_role_without(tool.permission))
    args = json.dumps({"agent_id": str(await _agent_of(tenant_id))})
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        if tool.tier == "immediate":
            await write_tools.run_immediate(tool.name, args, principal=principal, seed="s", ip=None)
        else:
            await write_tools.plan_write(tool.name, args, actor=write_tools.actor_for(principal))
    assert "role may not" in refused.value.reason


# --- lead_assign (immediate) ---------------------------------------------------------------


async def test_lead_assign_runs_logs_its_prior_owner_and_undoes() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    owner = _user_of(token)

    receipt = await _run(
        tenant_id, token, "lead_assign", {"lead_id": str(lead_id), "user_id": str(owner)}
    )
    assert receipt.applied is True
    assert (await _one(tenant_id, "SELECT assigned_to FROM leads WHERE id = :i", i=lead_id))[
        0
    ] == owner
    status, tier, prior, result = await _action_row(tenant_id, receipt.action_id)
    assert (status, tier) == ("done", "immediate")
    assert prior == {"assigned_to": None}
    assert result == {"assigned_to": str(owner)}
    assert ("lead.assigned", "lead", str(lead_id)) in await _audit(tenant_id)

    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
        again = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert undone.status_code == 200, undone.text
    assert (await _one(tenant_id, "SELECT assigned_to FROM leads WHERE id = :i", i=lead_id))[
        0
    ] is None
    assert again.status_code == 409
    assert again.json()["type"].endswith("/copilot_action_already_undone")


async def test_lead_assign_undo_refuses_after_a_concurrent_change_and_across_tenants() -> None:
    tenant_id, slug, token = await _make_tenant()
    _other, other_slug, other_token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    receipt = await _run(
        tenant_id, token, "lead_assign", {"lead_id": str(lead_id), "user_id": str(_user_of(token))}
    )
    async with _client() as http:
        crossed = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo",
            headers=_headers(other_token, other_slug),
        )
    assert crossed.status_code == 404
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET assigned_to = NULL WHERE id = :i"), {"i": lead_id}
        )
    async with _client() as http:
        refused = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_action_changed_since")


async def test_lead_assign_refuses_a_stranger_and_a_neighbours_lead() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _other_slug, _other_token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as stranger:
        await _run(
            tenant_id, token, "lead_assign", {"lead_id": str(lead_id), "user_id": str(uuid.uuid4())}
        )
    assert "not on this account's team" in stranger.value.reason
    with pytest.raises(ProblemError) as crossed:
        await _run(
            tenant_id,
            token,
            "lead_assign",
            {"lead_id": str(await _lead_of(other_id)), "user_id": None},
        )
    assert crossed.value.status == 404


# --- lead_rename, leads_bulk_update, dnc_remove (confirm) -------------------------------------


async def test_lead_rename_is_proposed_then_confirmed_without_quoting_the_old_name() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    proposal = await _propose(
        tenant_id, token, "lead_rename", {"lead_id": str(lead_id), "name": "Ravi Kumar"}
    )
    assert "Ravi Kumar" in proposal.summary and proposal.current is None
    assert (await _one(tenant_id, "SELECT name FROM leads WHERE id = :i", i=lead_id))[0] == "Ravi"
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert (await _one(tenant_id, "SELECT name FROM leads WHERE id = :i", i=lead_id))[
        0
    ] == "Ravi Kumar"
    assert ("lead.renamed", "lead", str(lead_id)) in await _audit(tenant_id)


async def test_bulk_update_previews_the_count_and_changes_each_lead() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    proposal = await _propose(
        tenant_id,
        token,
        "leads_bulk_update",
        {
            "lead_ids": [str(lead_id), str(uuid.uuid4())],
            "action": "status",
            "status": "hot",
            "user_id": None,
        },
    )
    assert proposal.title == "Change 1 leads"
    assert "1 of the ids named no lead" in proposal.summary
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert (await _one(tenant_id, "SELECT status FROM leads WHERE id = :i", i=lead_id))[0] == "hot"


async def _suppress(tenant_id: UUID, lead_id: UUID, source: str) -> None:
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source) "
                "VALUES (:id, :t, :p, 'tenant', :s)"
            ),
            {"id": uuid7(), "t": tenant_id, "p": phone, "s": source},
        )


async def test_dnc_remove_lifts_a_hand_added_entry_and_never_a_callers_opt_out() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    await _suppress(tenant_id, lead_id, "customer_request")
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "dnc_remove", {"lead_id": str(lead_id)})
    assert "asked not to be called" in refused.value.reason

    other_id, _s, other_token = await _make_tenant()
    other_lead = await _lead_of(other_id)
    await _suppress(other_id, other_lead, "manual")
    proposal = await _propose(other_id, other_token, "dnc_remove", {"lead_id": str(other_lead)})
    await _confirm(other_id, _user_of(other_token), proposal.token)
    assert (await _one(other_id, "SELECT count(*) FROM dnc_list WHERE tenant_id = :t", t=other_id))[
        0
    ] == 0
    assert any(action == "dnc.removed" for action, _o, _i in await _audit(other_id))


# --- call_place (confirm) ------------------------------------------------------------------


async def test_call_place_is_refused_with_the_gates_reason_before_any_card() -> None:
    """A fresh account has no verification: the dial gate refuses, so no card is drawn."""
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "call_place",
            {
                "lead_id": str(await _lead_of(tenant_id)),
                "agent_id": str(await _agent_of(tenant_id)),
                "note": None,
            },
        )
    assert "cannot be placed right now" in refused.value.reason


async def test_call_place_dials_through_the_buttons_own_function() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    token = headers["Authorization"].split(" ", 1)[1]
    lead_id, _phone = await _lead(tenant_id, agent_id)
    proposal = await _propose(
        tenant_id,
        token,
        "call_place",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "note": "quote"},
    )
    assert proposal.cost is not None and "cannot be taken back" in proposal.reversal
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    actions = [action for action, _o, _i in await _audit(tenant_id)]
    assert "lead.call_dispatched" in actions and "lead.call_requested" in actions
    await _settle_calls(tenant_id)


# --- call-backs (confirm) ------------------------------------------------------------------


async def test_a_callback_is_booked_moved_and_cancelled() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, agent_id = await _lead_of(tenant_id), await _agent_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "callback_book",
            {
                "lead_id": str(lead_id),
                "agent_id": str(agent_id),
                "at": "2020-01-01T10:00",
                "note": None,
            },
        )
    booked = await _propose(
        tenant_id,
        token,
        "callback_book",
        {"lead_id": str(lead_id), "agent_id": str(agent_id), "at": _later(), "note": "a quote"},
    )
    await _confirm(tenant_id, _user_of(token), booked.token)
    row = await _one(tenant_id, "SELECT id, status, requested_at FROM scheduled_callbacks")
    callback_id, status, first = UUID(str(row[0])), row[1], row[2]
    assert status == "scheduled"

    moved = await _propose(
        tenant_id, token, "callback_reschedule", {"callback_id": str(callback_id), "at": _later(3)}
    )
    await _confirm(tenant_id, _user_of(token), moved.token)
    later = (
        await _one(
            tenant_id, "SELECT requested_at FROM scheduled_callbacks WHERE id = :i", i=callback_id
        )
    )[0]
    assert later > first

    cancel = await _propose(tenant_id, token, "callback_cancel", {"callback_id": str(callback_id)})
    await _confirm(tenant_id, _user_of(token), cancel.token)
    assert (
        await _one(tenant_id, "SELECT status FROM scheduled_callbacks WHERE id = :i", i=callback_id)
    )[0] == "cancelled"
    assert {"callback.booked", "callback.rescheduled", "callback.cancelled"} <= {
        action for action, _o, _i in await _audit(tenant_id)
    }


# --- campaigns -----------------------------------------------------------------------------


async def test_campaign_create_makes_a_draft_and_undo_cancels_it_while_empty() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    receipt = await _run(
        tenant_id,
        token,
        "campaign_create",
        {"name": "Winter recall", "agent_id": str(agent_id), "classification": "service"},
    )
    campaign_id = UUID(receipt.object_id)
    assert (await _one(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=campaign_id))[
        0
    ] == "draft"
    _status, _tier, prior, result = await _action_row(tenant_id, receipt.action_id)
    assert prior == {"exists": False}
    assert result == {"exists": True, "name": "Winter recall", "status": "draft"}

    with pytest.raises(write_tools.WriteRefusedError):
        await _run(
            tenant_id,
            token,
            "campaign_create",
            {"name": "winter RECALL", "agent_id": str(agent_id), "classification": "service"},
        )

    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert undone.status_code == 200, undone.text
    assert (await _one(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=campaign_id))[
        0
    ] == "cancelled"


async def test_campaign_create_undo_refuses_once_contacts_were_added() -> None:
    tenant_id, slug, token = await _make_tenant()
    receipt = await _run(
        tenant_id,
        token,
        "campaign_create",
        {
            "name": "Spring recall",
            "agent_id": str(await _agent_of(tenant_id)),
            "classification": "service",
        },
    )
    added = await _propose(
        tenant_id,
        token,
        "campaign_add_leads",
        {"campaign_id": receipt.object_id, "lead_ids": [str(await _lead_of(tenant_id))]},
    )
    assert "Add 1 lead(s)" in added.summary
    await _confirm(tenant_id, _user_of(token), added.token)
    async with _client() as http:
        refused = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_action_changed_since")


async def test_campaign_clone_copies_the_settings_and_not_the_contacts() -> None:
    tenant_id, _slug, token = await _make_tenant()
    source = await _run(
        tenant_id,
        token,
        "campaign_create",
        {
            "name": "Autumn",
            "agent_id": str(await _agent_of(tenant_id)),
            "classification": "transactional",
        },
    )
    copy = await _run(
        tenant_id, token, "campaign_clone", {"source_campaign_id": source.object_id, "name": None}
    )
    row = await _one(
        tenant_id,
        "SELECT name, classification, status FROM campaigns WHERE id = :i",
        i=UUID(copy.object_id),
    )
    assert tuple(row) == ("Copy of Autumn", "transactional", "draft")


async def test_a_campaign_is_scheduled_unscheduled_and_resumed_by_confirm_only() -> None:
    tenant_id, _slug, token = await _make_tenant()
    created = await _run(
        tenant_id,
        token,
        "campaign_create",
        {
            "name": "Recall",
            "agent_id": str(await _agent_of(tenant_id)),
            "classification": "service",
        },
    )
    cid = created.object_id
    scheduled = await _propose(
        tenant_id, token, "campaign_schedule", {"campaign_id": cid, "start_at": _later()}
    )
    assert "Every launch check runs again" in scheduled.summary
    await _confirm(tenant_id, _user_of(token), scheduled.token)
    assert (await _one(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=UUID(cid)))[
        0
    ] == "scheduled"
    back = await _propose(tenant_id, token, "campaign_unschedule", {"campaign_id": cid})
    await _confirm(tenant_id, _user_of(token), back.token)
    assert (await _one(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=UUID(cid)))[
        0
    ] == "draft"

    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "campaign_resume", {"campaign_id": cid})
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET status = 'paused' WHERE id = :i"), {"i": UUID(cid)}
        )
    resumed = await _propose(tenant_id, token, "campaign_resume", {"campaign_id": cid})
    await _confirm(tenant_id, _user_of(token), resumed.token)
    assert (await _one(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=UUID(cid)))[
        0
    ] == "running"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET status = 'paused' WHERE id = :i"), {"i": UUID(cid)}
        )


# --- agents --------------------------------------------------------------------------------


async def _draft_agent(tenant_id: UUID) -> UUID:
    agent_id = await _agent_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'draft' WHERE id = :a"), {"a": agent_id}
        )
    return agent_id


async def test_agent_edit_changes_a_draft_and_undo_puts_it_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _draft_agent(tenant_id)
    before = await _one(
        tenant_id,
        "SELECT language_primary, ai_disclosure_enabled FROM agents WHERE id = :a",
        a=agent_id,
    )
    receipt = await _run(
        tenant_id,
        token,
        "agent_edit",
        {
            "agent_id": str(agent_id),
            "language_primary": "en-IN",
            "voice_id": None,
            "ai_disclosure_enabled": not before[1],
            "recording_notice_enabled": None,
        },
    )
    assert receipt.applied is True
    after = await _one(
        tenant_id,
        "SELECT language_primary, ai_disclosure_enabled FROM agents WHERE id = :a",
        a=agent_id,
    )
    assert tuple(after) == ("en-IN", not before[1])
    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert undone.status_code == 200, undone.text
    restored = await _one(
        tenant_id,
        "SELECT language_primary, ai_disclosure_enabled FROM agents WHERE id = :a",
        a=agent_id,
    )
    assert tuple(restored) == tuple(before)


async def test_agent_edit_refuses_a_live_agent_and_the_live_twin_needs_a_click() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)  # `_make_tenant`'s agent is live
    args = {
        "agent_id": str(agent_id),
        "language_primary": "en-IN",
        "voice_id": None,
        "ai_disclosure_enabled": None,
        "recording_notice_enabled": None,
    }
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_edit", args)
    assert "agent_edit_live" in refused.value.reason
    proposal = await _propose(tenant_id, token, "agent_edit_live", args)
    assert "next call" in proposal.summary
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert (await _one(tenant_id, "SELECT language_primary FROM agents WHERE id = :a", a=agent_id))[
        0
    ] == "en-IN"


async def test_capture_fields_are_replaced_and_undo_restores_the_old_list() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    field = {
        "key": "budget",
        "label": "Budget",
        "type": "text",
        "enum_values": None,
        "reason": "To quote",
        "required": False,
    }
    receipt = await _run(
        tenant_id, token, "agent_capture_fields_set", {"agent_id": str(agent_id), "fields": [field]}
    )
    assert receipt.applied is True
    _status, _tier, prior, result = await _action_row(tenant_id, receipt.action_id)
    assert [f["key"] for f in result["fields"]] == ["budget"]
    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert undone.status_code == 200, undone.text
    fields = (
        await _one(
            tenant_id,
            "SELECT s.fields FROM agents a JOIN extraction_schemas s "
            "ON s.id = a.extraction_schema_id WHERE a.id = :a",
            a=agent_id,
        )
    )[0]
    assert [f["key"] for f in fields] == [f["key"] for f in prior["fields"]]


async def test_agent_changes_apply_is_refused_when_nothing_is_waiting() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id, token, "agent_changes_apply", {"agent_id": str(await _agent_of(tenant_id))}
        )
    assert "nothing to apply" in refused.value.reason


async def test_agent_deactivate_then_delete_through_the_lifecycle() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "agent_delete", {"agent_id": str(agent_id)})
    paused = await _propose(tenant_id, token, "agent_deactivate", {"agent_id": str(agent_id)})
    await _confirm(tenant_id, _user_of(token), paused.token)
    assert (await _one(tenant_id, "SELECT status FROM agents WHERE id = :a", a=agent_id))[
        0
    ] == "paused"
    deleted = await _propose(tenant_id, token, "agent_delete", {"agent_id": str(agent_id)})
    await _confirm(tenant_id, _user_of(token), deleted.token)
    assert (await _one(tenant_id, "SELECT status FROM agents WHERE id = :a", a=agent_id))[
        0
    ] == "archived"
    assert {"agent.deactivated", "agent.archived"} <= {a for a, _o, _i in await _audit(tenant_id)}


async def test_a_neighbours_agent_is_a_404_for_every_agent_action() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _s, _t = await _make_tenant()
    foreign = str(await _agent_of(other_id))
    for name in ("agent_edit_live", "agent_deactivate", "agent_delete", "agent_changes_apply"):
        with pytest.raises(ProblemError) as crossed:
            await _propose(
                tenant_id,
                token,
                name,
                {"agent_id": foreign}
                if name != "agent_edit_live"
                else {
                    "agent_id": foreign,
                    "language_primary": "en-IN",
                    "voice_id": None,
                    "ai_disclosure_enabled": None,
                    "recording_notice_enabled": None,
                },
            )
        assert crossed.value.status == 404, name


# --- business hours, knowledge and numbers -------------------------------------------------


async def test_business_hours_are_proposed_for_the_whole_week_and_saved() -> None:
    tenant_id, _slug, token = await _make_tenant()
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "business_hours_set", {"hours": []})
    hours = [
        {
            "day": d,
            "opens": None if d == "sun" else "09:00",
            "closes": None if d == "sun" else "18:00",
            "closed": d == "sun",
        }
        for d in days
    ]
    proposal = await _propose(tenant_id, token, "business_hours_set", {"hours": hours})
    assert "09:00" in proposal.proposed
    await _confirm(tenant_id, _user_of(token), proposal.token)
    stored = (await _one(tenant_id, "SELECT hours FROM business_profiles"))[0]
    assert stored["sun"] is None and stored["mon"]["opens"] == "09:00"


async def test_knowledge_actions_refuse_what_they_cannot_name() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id, token, "knowledge_link_add", {"name": None, "url": "file:///etc/passwd"}
        )
    with pytest.raises(ProblemError) as missing:
        await _propose(tenant_id, token, "knowledge_remove", {"upload_id": str(uuid.uuid4())})
    assert missing.value.status == 404


async def test_number_actions_are_refused_where_the_platform_has_no_workspaces() -> None:
    from apps.api.tenancy.engine_workspace import engine_has_workspaces

    if engine_has_workspaces():  # pragma: no cover - the test deployment runs the fake engine
        pytest.skip("this deployment buys numbers in the app")
    tenant_id, _slug, token = await _make_tenant()
    for name, args in (
        ("number_buy", {"city": "Hyderabad", "agent_id": None, "direction": "inbound"}),
        ("number_release", {"number_id": str(uuid.uuid4())}),
    ):
        with pytest.raises(write_tools.WriteRefusedError):
            await _propose(tenant_id, token, name, args)


# --- the action log ------------------------------------------------------------------------


async def test_a_confirmed_console_action_is_on_the_activity_log() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    proposal = await _propose(
        tenant_id, token, "lead_rename", {"lead_id": str(lead_id), "name": "Ravi K"}
    )
    await _confirm(tenant_id, _user_of(token), proposal.token)
    async with _client() as http:
        page = await http.get("/v1/copilot/actions", headers=_headers(token, slug))
    rows = page.json()["actions"]
    assert rows[0]["tool"] == "lead_rename" and rows[0]["tier"] == "confirm"
    assert rows[0]["can_undo"] is False


async def test_a_refused_console_action_is_logged_without_arguments() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await action_log.record_refusal(
        realm="client",
        tenant_id=tenant_id,
        actor_id=_user_of(token),
        tool="call_place",
        tier="confirm",
        object_type="lead",
        reason="this person's role may not do what `call_place` proposes",
    )
    row = await _one(
        tenant_id, "SELECT status, args_redacted FROM copilot_actions WHERE tool = 'call_place'"
    )
    assert tuple(row) == ("refused", None)


def test_every_console_action_names_where_its_result_lives() -> None:
    for tool in CONSOLE_ACTIONS:
        assert tool.where and tool.audit_action and tool.permission, tool.name


async def test_a_test_call_is_refused_where_test_calling_is_not_set_up() -> None:
    from apps.api.agents.trial_calls import trial_calling_ready

    if trial_calling_ready():  # pragma: no cover - the test deployment runs the fake engine
        pytest.skip("this deployment places trial calls")
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "agent_test_call",
            {
                "agent_id": str(await _agent_of(tenant_id)),
                "lead_id": str(await _lead_of(tenant_id)),
            },
        )
    assert "no test call was proposed" in refused.value.reason


async def test_business_profile_sections_go_through_the_profile_service() -> None:
    tenant_id, _slug, token = await _make_tenant()
    empty = {
        "branches": None,
        "services": None,
        "faqs": None,
        "staff": None,
        "booking_rules": None,
        "languages": None,
    }
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "business_profile_set", empty)
    with pytest.raises(write_tools.WriteRefusedError) as bad_price:
        await _propose(
            tenant_id,
            token,
            "business_profile_set",
            {**empty, "services": [{"name": "Cleaning", "price_inr": "₹1,500", "notes": None}]},
        )
    assert "services" in bad_price.value.reason
    proposal = await _propose(
        tenant_id,
        token,
        "business_profile_set",
        {
            **empty,
            "services": [{"name": "Cleaning", "price_inr": "1500", "notes": None}],
            "booking_rules": "Bookings a day ahead.",
        },
    )
    assert proposal.proposed == "booking_rules set; services 1 item(s)"
    await _confirm(tenant_id, _user_of(token), proposal.token)
    row = await _one(tenant_id, "SELECT services, booking_rules FROM business_profiles")
    assert row[0][0]["name"] == "Cleaning" and row[1] == "Bookings a day ahead."
    assert ("business_profile.updated", "organization", str(tenant_id)) in await _audit(tenant_id)

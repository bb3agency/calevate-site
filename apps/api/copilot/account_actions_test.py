"""D-893 lane L6: Pip's account actions and reads, each held to `docs/COPILOT-CONTRACT.md` §5.

For every tool: the planner's canonical arguments and refusals; the change through
`run_immediate` or `confirm` with its `audit_log` and `copilot_actions` rows; for an
immediate tool the Undo and its compare-and-swap refusal; the permission refused inside the
tool; the emailed-code tools refused until Pip's confirm can ask for the code; and the
reads that name every id the actions take. Every test mints its own tenant.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.forwarding_fixtures import add_line, give_calevate_number

from apps.api.copilot import account_actions, service, tools, write_tools
from apps.api.copilot.account_actions import (
    ACCOUNT_ACTIONS,
    ACCOUNT_CODE_ACTIONS,
    ACCOUNT_TOOL_AREAS,
)
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ingest import lead_policy
from apps.api.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"account-{uuid.uuid4()}",
        ip=None,
    )


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(_principal(tenant_id, _user_of(token)))
    )


async def _plan(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    """The planner alone, for its canonical arguments (the proposal frame does not carry
    them; the signed token does)."""
    tool = write_tools.tool_named(name)
    assert tool is not None
    actor = write_tools.actor_for(_principal(tenant_id, _user_of(token)))
    assert actor is not None
    async with tenant_session(tenant_id) as session:
        return await tool.plan(session, actor, args)


async def _do(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    proposal = await _propose(tenant_id, token, name, args)
    return await _confirm(tenant_id, _user_of(token), proposal.token)


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _agent_of(tenant_id: UUID) -> UUID:
    return UUID(str((await _one(tenant_id, "SELECT id FROM agents LIMIT 1"))[0]))


async def _read(name: str, tenant_id: UUID, role: str = "owner") -> str:
    return await tools.run_read_tool(
        name,
        "{}",
        context=tools.ToolContext(tenant_id=tenant_id, role=role),
        registry=service._read_tool_registry("client"),
    )


async def _action_summary(tenant_id: UUID, tool: str) -> str:
    row = await _one(
        tenant_id,
        "SELECT summary FROM copilot_actions WHERE tool = :t ORDER BY created_at DESC LIMIT 1",
        t=tool,
    )
    return str(row[0])


async def _undo(token: str, slug: str, action_id: str) -> Any:
    async with _client() as http:
        return await http.post(
            f"/v1/copilot/actions/{action_id}/undo", headers=_headers(token, slug)
        )


async def _add_member(tenant_id: UUID, role: str) -> UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:i, :e, 'Asha', now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, :r, now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id, "r": role},
        )
    return user_id


# --- the registry ----------------------------------------------------------------------------


def test_the_account_actions_are_appended_last_and_each_has_an_area() -> None:
    names = [tool.name for tool in write_tools.WRITE_TOOLS]
    mine = [tool.name for tool in ACCOUNT_ACTIONS]
    assert names[-len(mine) :] == mine
    assert set(ACCOUNT_TOOL_AREAS) == set(mine)
    assert set(ACCOUNT_TOOL_AREAS.values()) <= {
        "numbers",
        "team",
        "settings",
        "integrations",
        "billing",
    }


def test_only_the_reviewed_account_actions_skip_the_click() -> None:
    immediate = {tool.name for tool in ACCOUNT_ACTIONS if tool.tier == "immediate"}
    assert immediate == {
        "forwarding_line_change",
        "lead_source_edit",
        "lead_source_switch",
        "low_balance_alert_set",
    }
    for name in ("ai_allowance_extra", "auto_recharge_set", "held_lead_decide", "team_invite"):
        assert write_tools.tier_of(name) == "confirm", name


def test_nothing_here_pays_tops_up_or_approves_a_payment_method() -> None:
    for tool in ACCOUNT_ACTIONS:
        for word in ("pay", "topup", "top_up", "mandate", "pledge", "kyc", "legal", "delete"):
            assert word not in tool.name, tool.name


def test_each_code_gated_tool_names_the_string_its_button_sends() -> None:
    slug = "acme-clinic"
    assert (
        ACCOUNT_CODE_ACTIONS["forwarding_line_add"]({}, slug) == "add_forwarded_number:acme-clinic"
    )
    assert ACCOUNT_CODE_ACTIONS["forwarding_line_test"]({}, slug) == "forwarding_test:acme-clinic"
    assert ACCOUNT_CODE_ACTIONS["crm_endpoint_create"]({}, slug) == "create_endpoint:acme-clinic"
    owner_invite = {"email": " A@B.in ", "role": "owner"}
    assert ACCOUNT_CODE_ACTIONS["team_invite"](owner_invite, slug) == (
        "invite_owner:acme-clinic:a@b.in"
    )
    assert ACCOUNT_CODE_ACTIONS["team_invite"]({"email": "a@b.in", "role": "staff"}, slug) is None
    user = str(uuid.uuid4())
    assert ACCOUNT_CODE_ACTIONS["team_member_role"]({"user_id": user, "role": "owner"}, slug) == (
        f"promote_owner:acme-clinic:{user}"
    )
    assert (
        ACCOUNT_CODE_ACTIONS["team_member_role"]({"user_id": user, "role": "staff"}, slug) is None
    )


@pytest.mark.parametrize(
    ("name", "args"),
    [
        (
            "forwarding_line_add",
            {
                "number": "9812345670",
                "line_kind": "mobile",
                "carrier": "airtel",
                "mode": "all_calls",
                "ring_seconds": 0,
                "calevate_number_id": None,
            },
        ),
        ("forwarding_line_test", {"line_id": str(uuid.uuid4())}),
        ("team_invite", {"email": "new@example.com", "role": "owner"}),
        (
            "crm_endpoint_create",
            {
                "url": "https://crm.example.com/x",
                "events": ["lead.created"],
                "include_recording_url": False,
                "include_transcript": False,
                "include_raw_transcript": False,
            },
        ),
    ],
)
async def test_a_code_gated_tool_is_refused_until_the_confirm_asks_for_the_code(
    name: str, args: dict[str, Any]
) -> None:
    assert account_actions.CODE_GATE_ON_CONFIRM is False
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, name, args)
    assert "code we email" in refused.value.reason


@pytest.mark.parametrize("tool", ACCOUNT_ACTIONS, ids=lambda tool: tool.name)
async def test_staff_are_refused_inside_every_account_tool(tool: Any) -> None:
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token), role="staff")
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        if tool.tier == "immediate":
            await write_tools.run_immediate(tool.name, "{}", principal=principal, seed="s", ip=None)
        else:
            await write_tools.plan_write(tool.name, "{}", actor=write_tools.actor_for(principal))
    assert "role may not" in refused.value.reason


# --- numbers ----------------------------------------------------------------------------------


async def test_number_assign_takes_a_number_off_its_agent_and_refuses_a_neighbours() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _o, _ot = await _make_tenant()
    number_id, _e164 = await give_calevate_number(tenant_id, await _agent_of(tenant_id))
    foreign, _ = await give_calevate_number(other_id, await _agent_of(other_id))
    args = {"number_id": str(number_id), "agent_id": None, "direction": None}
    proposal = await _propose(tenant_id, token, "number_assign", args)
    assert proposal.current == "Reception"
    assert proposal.proposed == "no agent"
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    row = await _one(tenant_id, "SELECT agent_id FROM phone_numbers WHERE id = :i", i=number_id)
    assert row[0] is None
    assert ("number.assigned", "phone_number", str(number_id)) in await _audit(tenant_id)
    with pytest.raises(ProblemError):
        await _propose(tenant_id, token, "number_assign", {**args, "number_id": str(foreign)})


async def test_a_forwarding_change_runs_at_once_and_undoes_until_changed_again() -> None:
    tenant_id, slug, token = await _make_tenant()
    await give_calevate_number(tenant_id, await _agent_of(tenant_id))
    line = await add_line(tenant_id, ring_seconds=20)
    change = {
        "line_id": str(line.id),
        "line_kind": "mobile",
        "carrier": "jio",
        "mode": "all_calls",
        "ring_seconds": 0,
        "calevate_number_id": None,
    }
    receipt = await _run(tenant_id, token, "forwarding_line_change", change)
    assert receipt.applied is True
    row = await _one(
        tenant_id, "SELECT mode, carrier FROM forwarded_lines WHERE id = :i", i=line.id
    )
    assert tuple(row) == ("all_calls", "jio")
    undone = await _undo(token, slug, receipt.action_id)
    assert undone.status_code == 200, undone.text
    row = await _one(
        tenant_id,
        "SELECT mode, ring_seconds, carrier FROM forwarded_lines WHERE id = :i",
        i=line.id,
    )
    assert tuple(row) == ("conditional", 20, "airtel")

    second = await _run(tenant_id, token, "forwarding_line_change", change)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE forwarded_lines SET ring_seconds = 0, carrier = 'vi' WHERE id = :i"),
            {"i": line.id},
        )
    refused = await _undo(token, slug, second.action_id)
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_action_changed_since")


async def test_a_forwarded_number_is_removed_on_confirm() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await give_calevate_number(tenant_id, await _agent_of(tenant_id))
    line = await add_line(tenant_id)
    await _do(tenant_id, token, "forwarding_line_remove", {"line_id": str(line.id)})
    assert await _one(tenant_id, "SELECT 1 FROM forwarded_lines WHERE id = :i", i=line.id) is None


async def test_numbers_list_names_forwarded_lines_call_lines_and_the_backup_phone() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await give_calevate_number(tenant_id, await _agent_of(tenant_id))
    line = await add_line(tenant_id)
    result = await _read("numbers_list", tenant_id)
    assert f"[line_id {line.id}]" in result
    assert "Calls at once:" in result
    assert "No backup phone is set" in result


# --- team -------------------------------------------------------------------------------------


async def test_a_staff_invitation_is_minted_and_mailed_on_confirm() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(
        tenant_id, token, "team_invite", {"email": " New@Example.com ", "role": "staff"}
    )
    planned = await _plan(
        tenant_id, token, "team_invite", {"email": " New@Example.com ", "role": "staff"}
    )
    assert planned.args == {"email": "new@example.com", "role": "staff"}
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    row = await _one(tenant_id, "SELECT email, role FROM invitations")
    assert tuple(row) == ("new@example.com", "staff")
    async with untenanted_session() as session:
        mailed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = 'deliver_auth_email' "
                    "AND payload->>'to' = :p"
                ),
                {"p": "new@example.com"},
            )
        ).scalar_one()
    assert mailed >= 1
    team = await _read("team_members", tenant_id)
    assert "[invitation_id " in team


async def test_an_invitation_is_cancelled_or_resent() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await _do(tenant_id, token, "team_invite", {"email": "x@example.com", "role": "staff"})
    invitation_id = str((await _one(tenant_id, "SELECT id FROM invitations"))[0])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE invitations SET last_sent_at = now() - interval '1 hour' WHERE id = :i"),
            {"i": invitation_id},
        )
    resent = await _do(
        tenant_id, token, "team_invitation", {"invitation_id": invitation_id, "action": "resend"}
    )
    assert resent.applied is True
    await _do(
        tenant_id, token, "team_invitation", {"invitation_id": invitation_id, "action": "cancel"}
    )
    assert await _one(tenant_id, "SELECT 1 FROM invitations WHERE id = :i", i=invitation_id) is None


async def test_a_member_is_demoted_or_removed_and_self_and_promotion_are_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    colleague = await _add_member(tenant_id, "owner")
    with pytest.raises(write_tools.WriteRefusedError) as self_change:
        await _propose(
            tenant_id, token, "team_member_role", {"user_id": str(_user_of(token)), "role": "staff"}
        )
    assert "own role" in self_change.value.reason
    done = await _do(
        tenant_id, token, "team_member_role", {"user_id": str(colleague), "role": "staff"}
    )
    assert done.applied is True
    role = await _one(tenant_id, "SELECT role FROM memberships WHERE user_id = :u", u=colleague)
    assert role[0] == "staff"
    with pytest.raises(write_tools.WriteRefusedError) as promotion:
        await _propose(
            tenant_id, token, "team_member_role", {"user_id": str(colleague), "role": "owner"}
        )
    assert "code we email" in promotion.value.reason
    await _do(tenant_id, token, "team_member_remove", {"user_id": str(colleague)})
    assert (
        await _one(tenant_id, "SELECT 1 FROM memberships WHERE user_id = :u", u=colleague) is None
    )


# --- settings ---------------------------------------------------------------------------------


async def test_the_backup_phone_is_set_and_removed_and_a_landline_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "line_protection_phone", {"phone": "0401234567"})
    proposal = await _propose(tenant_id, token, "line_protection_phone", {"phone": "98765 43210"})
    planned = await _plan(tenant_id, token, "line_protection_phone", {"phone": "98765 43210"})
    assert planned.args == {"phone": "+919876543210"}
    assert "43210" not in proposal.summary
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert (await _one(tenant_id, "SELECT phone_e164 FROM heal_fallback_phones"))[0] == (
        "+919876543210"
    )
    await _do(tenant_id, token, "line_protection_phone", {"phone": None})
    assert await _one(tenant_id, "SELECT 1 FROM heal_fallback_phones") is None


async def test_a_lead_source_shows_its_secret_once_and_never_logs_it() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    done = await _do(
        tenant_id,
        token,
        "lead_source_create",
        {"source": "website_form", "agent_id": str(agent_id)},
    )
    assert "X-Ingest-Secret" in done.detail or "Copy it now" in done.detail
    assert "secret was shown once" in await _action_summary(tenant_id, "lead_source_create")
    source_id = str((await _one(tenant_id, "SELECT id FROM inbound_webhooks"))[0])
    rotated = await _do(
        tenant_id,
        token,
        "lead_source_rotate",
        {"lead_source_id": source_id, "retire_old_now": True},
    )
    assert "not shown again" in rotated.detail
    assert "shown once" in await _action_summary(tenant_id, "lead_source_rotate")


async def test_a_lead_source_is_paused_repointed_and_both_undo() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _do(tenant_id, token, "lead_source_create", {"source": "custom", "agent_id": None})
    source_id = str((await _one(tenant_id, "SELECT id FROM inbound_webhooks"))[0])

    paused = await _run(
        tenant_id, token, "lead_source_switch", {"lead_source_id": source_id, "on": False}
    )
    assert (await _one(tenant_id, "SELECT active FROM inbound_webhooks"))[0] is False
    assert (await _undo(token, slug, paused.action_id)).status_code == 200
    assert (await _one(tenant_id, "SELECT active FROM inbound_webhooks"))[0] is True
    with pytest.raises(write_tools.WriteRefusedError):
        await _run(
            tenant_id, token, "lead_source_switch", {"lead_source_id": source_id, "on": True}
        )

    pointed = await _run(
        tenant_id,
        token,
        "lead_source_edit",
        {"lead_source_id": source_id, "agent_id": str(agent_id)},
    )
    assert (await _one(tenant_id, "SELECT agent_id FROM inbound_webhooks"))[0] == agent_id
    assert (await _undo(token, slug, pointed.action_id)).status_code == 200
    assert (await _one(tenant_id, "SELECT agent_id FROM inbound_webhooks"))[0] is None


async def test_the_calling_rules_merge_with_the_plan_and_held_leads_are_decided() -> None:
    tenant_id, _slug, token = await _make_tenant()
    rules = {
        "calling_agent_id": None,
        "wait_seconds": 120,
        "hours_start": "10:00",
        "hours_end": None,
        "days": None,
        "after_hours": "hold",
        "retry_attempts": None,
        "retry_interval_minutes": None,
        "detect_machines": None,
    }
    planned = await _plan(tenant_id, token, "lead_calling_rules", rules)
    assert planned.args["wait_seconds"] == 120
    assert planned.args["hours_start"] == "10:00"
    assert planned.args["hours_end"] == "21:00"
    proposal = await _propose(tenant_id, token, "lead_calling_rules", rules)
    await _confirm(tenant_id, _user_of(token), proposal.token)
    async with tenant_session(tenant_id) as session:
        plan = await lead_policy.load_plan(session)
        lead_id = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar_one()
        hold_id = await lead_policy.hold_lead(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            agent_id=await _agent_of(tenant_id),
            source="website_form",
        )
    assert (plan.wait_seconds, plan.after_hours) == (120, "hold")
    status = await _read("integrations_status", tenant_id)
    assert f"[hold_id {hold_id}]" in status
    await _do(tenant_id, token, "held_lead_decide", {"hold_id": str(hold_id), "decision": "drop"})
    held = await _one(tenant_id, "SELECT status FROM lead_call_holds WHERE id = :i", i=hold_id)
    assert held[0] == "dropped"
    with pytest.raises(ProblemError):
        await _propose(
            tenant_id, token, "held_lead_decide", {"hold_id": str(hold_id), "decision": "call"}
        )


# --- integrations -----------------------------------------------------------------------------


async def _endpoint(tenant_id: UUID) -> UUID:
    from apps.api.integrations.service import create_webhook_endpoint

    async with tenant_session(tenant_id) as session:
        created = await create_webhook_endpoint(
            session,
            tenant_id=tenant_id,
            url="https://crm.example.com/hooks/calevate",
            events=["lead.created"],
            include_recording_url=False,
            include_transcript=False,
            include_raw_transcript=False,
            role="owner",
        )
    return created.id


async def test_an_endpoint_is_edited_rekeyed_and_switched_off() -> None:
    tenant_id, _slug, token = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    status = await _read("integrations_status", tenant_id)
    assert f"[endpoint_id {endpoint_id}]" in status
    assert "Google Sheets: not connected" in status
    edit = {
        "endpoint_id": str(endpoint_id),
        "events": ["lead.created", "call.completed"],
        "include_recording_url": False,
        "include_transcript": True,
        "include_raw_transcript": False,
    }
    proposal = await _propose(tenant_id, token, "crm_endpoint_edit", edit)
    assert "the transcript" in proposal.proposed
    await _confirm(tenant_id, _user_of(token), proposal.token)
    row = await _one(
        tenant_id,
        "SELECT events, include_transcript FROM outbound_webhooks WHERE id = :i",
        i=endpoint_id,
    )
    assert sorted(row[0]) == ["call.completed", "lead.created"] and row[1] is True
    rekeyed = await _do(
        tenant_id,
        token,
        "crm_endpoint_act",
        {"endpoint_id": str(endpoint_id), "action": "new_secret"},
    )
    assert "not shown again" in rekeyed.detail
    assert "shown once" in await _action_summary(tenant_id, "crm_endpoint_act")
    await _do(
        tenant_id,
        token,
        "crm_endpoint_act",
        {"endpoint_id": str(endpoint_id), "action": "switch_off"},
    )
    off = await _one(tenant_id, "SELECT active FROM outbound_webhooks WHERE id = :i", i=endpoint_id)
    assert off[0] is False
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "crm_endpoint_act",
            {"endpoint_id": str(endpoint_id), "action": "switch_off"},
        )


async def test_a_delivery_resend_is_scoped_to_the_account_and_needs_a_failure() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(ProblemError):
        await _propose(tenant_id, token, "crm_delivery_resend", {"delivery_id": str(uuid.uuid4())})


# --- billing settings -------------------------------------------------------------------------


async def test_spending_limits_are_set_on_confirm() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id, token, "spend_caps_set", {"cap_spend_inr": "lots", "cap_minutes": None}
        )
    done = await _do(
        tenant_id, token, "spend_caps_set", {"cap_spend_inr": "2500", "cap_minutes": 300}
    )
    assert done.applied is True
    row = await _one(tenant_id, "SELECT client_cap_spend, client_cap_min FROM plans")
    assert (Decimal(str(row[0])), row[1]) == (Decimal("2500"), 300)


async def test_auto_recharge_cannot_be_switched_on_without_an_approved_method() -> None:
    tenant_id, _slug, token = await _make_tenant()
    on = {"enabled": True, "threshold_inr": None, "amount_inr": None, "monthly_cap_inr": None}
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "auto_recharge_set", on)
    assert "never sets up payments" in refused.value.reason


async def test_the_low_credit_line_runs_at_once_and_undoes() -> None:
    tenant_id, slug, token = await _make_tenant()
    receipt = await _run(tenant_id, token, "low_balance_alert_set", {"threshold_inr": "₹750"})
    line = await _one(tenant_id, "SELECT low_balance_alert_inr FROM organizations")
    assert Decimal(str(line[0])) == Decimal("750")
    settings = await _read("billing_settings", tenant_id)
    assert "Low-credit warning below ₹750.00" in settings
    assert (await _undo(token, slug, receipt.action_id)).status_code == 200
    assert (await _one(tenant_id, "SELECT low_balance_alert_inr FROM organizations"))[0] is None
    staff_view = await _read("billing_settings", tenant_id, role="staff")
    assert "permission" in staff_view.lower() or "may not" in staff_view.lower()


async def test_more_ai_help_is_refused_while_the_included_allowance_lasts() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "ai_allowance_extra", {})
    assert "cannot be added" in refused.value.reason

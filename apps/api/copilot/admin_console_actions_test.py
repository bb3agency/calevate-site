"""D-698: the admin assistant's per-client actions and its new reads.

Each per-client action acts on the account whose page is OPEN (`viewing_tenant_id`), in
that account's own session, through the console button's own function, after a click.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.api_security_test import _make_tenant

from apps.api.copilot import admin_actions, admin_tools, service, tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session, untenanted_session


def _admin(token: str, role: str = "superadmin") -> Principal:
    return Principal(
        realm="admin", user_id=UUID(token.rsplit(":", 1)[1]), tenant_id=None, role=role
    )


async def _confirm(token: str, proposal: Any, *, role: str = "superadmin") -> Any:
    async with untenanted_session() as session:
        return await admin_actions.confirm_admin(
            session,
            proposal.token,
            principal=_admin(token, role),
            require_step_up=lambda _action: None,
            ip=None,
        )


async def _submitted_kyc(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kyc_records (id, tenant_id, status, entity_type, "
                "  verification_source, submitted_at, created_at, updated_at) "
                "VALUES (:id, :tid, 'submitted', 'private_limited', 'operator', now(), "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )


def test_the_new_admin_actions_are_appended_and_confirm_only() -> None:
    names = [tool.name for tool in admin_actions.ADMIN_ACTIONS]
    assert names[0] == "platform_halt_outbound"
    assert names[1:] == [
        "admin_kyc_review",
        "admin_workspace_provision",
        "admin_number_release",
        "admin_voice_set",
        "healer_retry",
        "healer_resolve",
        "healer_attest_rate",
        "admin_call_lines_raise",
        "admin_call_lines_decline",
    ]
    for tool in admin_actions.ADMIN_ACTIONS:
        assert tool.tier == "confirm", tool.name
    admin = json.dumps(service.tool_array("admin"))
    client = json.dumps(service.tool_array("client"))
    assert '"admin_kyc_review"' in admin and '"admin_kyc_review"' not in client


def test_a_per_client_action_demands_its_console_routes_confirmation() -> None:
    """The assistant used to propose a client-page action with no confirmation while the
    console button for the same act (provisioning a workspace, releasing a number, deciding
    a KYC review) demanded step-up — so the assistant was a way around the gate."""
    tenant, number = uuid.uuid4(), uuid.uuid4()
    by_name = {tool.name: tool for tool in admin_actions.ADMIN_ACTIONS}
    expected: dict[str, tuple[dict[str, Any], str]] = {
        "admin_kyc_review": ({"decision": "approve"}, f"kyc_review:{tenant}:approve"),
        "admin_workspace_provision": ({}, f"provision_workspace:{tenant}"),
        "admin_number_release": (
            {"number_id": str(number)},
            f"release_number:{tenant}:{number}",
        ),
        "admin_call_lines_raise": ({"call_lines": 4}, f"set_call_lines:{tenant}"),
    }
    for name, (args, confirmation) in expected.items():
        confirm = by_name[name].confirm_action
        assert confirm is not None, name
        assert confirm(args, tenant) == confirmation, name


async def test_confirming_a_kyc_decision_through_the_assistant_takes_the_step_up() -> None:
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    await _submitted_kyc(tenant_id)
    proposal = await admin_actions.plan_admin_action(
        "admin_kyc_review",
        json.dumps(
            {
                "decision": "reject",
                "document_ref": None,
                "reason": "Unreadable.",
                "pan_checked": False,
            }
        ),
        principal=_admin(token, "operator"),
        viewing_tenant_id=tenant_id,
    )
    asked: list[str] = []

    def refuse(action: str) -> None:
        asked.append(action)
        raise WriteRefusedError("stale factor")

    async with untenanted_session() as session:
        with pytest.raises(WriteRefusedError):
            await admin_actions.confirm_admin(
                session,
                proposal.token,
                principal=_admin(token, "operator"),
                require_step_up=refuse,
                ip=None,
            )
    assert asked == [f"kyc_review:{tenant_id}:reject"]
    async with tenant_session(tenant_id) as session:
        status = (await session.execute(text("SELECT status FROM kyc_records"))).scalar()
    assert status == "submitted", "a refused step-up must change nothing"


async def test_a_per_client_action_needs_a_clients_page_open() -> None:
    token = await _make_admin()
    with pytest.raises(WriteRefusedError) as refused:
        await admin_actions.plan_admin_action(
            "admin_kyc_review",
            json.dumps({"decision": "approve", "pan_checked": True}),
            principal=_admin(token),
            viewing_tenant_id=None,
        )
    assert "open that client's page" in refused.value.reason


async def test_a_kyc_rejection_is_proposed_then_recorded_in_the_clients_session() -> None:
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    await _submitted_kyc(tenant_id)
    with pytest.raises(WriteRefusedError):
        await admin_actions.plan_admin_action(
            "admin_kyc_review",
            json.dumps(
                {"decision": "reject", "document_ref": None, "reason": None, "pan_checked": False}
            ),
            principal=_admin(token, "operator"),
            viewing_tenant_id=tenant_id,
        )
    proposal = await admin_actions.plan_admin_action(
        "admin_kyc_review",
        json.dumps(
            {
                "decision": "reject",
                "document_ref": None,
                "reason": "The certificate is unreadable.",
                "pan_checked": False,
            }
        ),
        principal=_admin(token, "operator"),
        viewing_tenant_id=tenant_id,
    )
    # The console's review button demands this exact confirmation, so the assistant does too.
    assert proposal.confirm_action == f"kyc_review:{tenant_id}:reject"
    assert proposal.proposed == "rejected"
    async with tenant_session(tenant_id) as session:
        before = (await session.execute(text("SELECT status FROM kyc_records"))).scalar()
    assert before == "submitted"
    done = await _confirm(token, proposal, role="operator")
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        decided = (
            await session.execute(text("SELECT status, rejection_reason FROM kyc_records"))
        ).first()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'kyc.reviewed'"
                ),
                {"t": str(tenant_id)},
            )
        ).scalar()
    assert decided is not None
    assert tuple(decided) == ("rejected", "The certificate is unreadable.")
    assert audited == 1
    async with untenanted_session() as session:
        logged = (
            await session.execute(
                text(
                    "SELECT status, tier FROM admin_copilot_actions "
                    "WHERE tool = 'admin_kyc_review' AND viewing_tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert logged is not None
    assert tuple(logged) == ("done", "confirm")


async def test_an_operator_cannot_curate_voices_and_an_unknown_voice_is_refused() -> None:
    operator = await _make_admin(role="operator")
    args = json.dumps({"voice_id": "no-such-voice", "state": "disabled"})
    with pytest.raises(WriteRefusedError) as role:
        await admin_actions.plan_admin_action(
            "admin_voice_set", args, principal=_admin(operator, "operator"), viewing_tenant_id=None
        )
    assert "role may not" in role.value.reason
    superadmin = await _make_admin()
    with pytest.raises(WriteRefusedError) as unknown:
        await admin_actions.plan_admin_action(
            "admin_voice_set", args, principal=_admin(superadmin), viewing_tenant_id=None
        )
    assert "no voice" in unknown.value.reason


async def test_workspace_and_number_actions_refuse_where_there_are_no_workspaces() -> None:
    from apps.api.tenancy.engine_workspace import engine_has_workspaces

    if engine_has_workspaces():  # pragma: no cover - the test deployment runs the fake engine
        pytest.skip("this deployment has per-client workspaces")
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    for name, args in (
        ("admin_workspace_provision", {}),
        ("admin_number_release", {"number_id": str(uuid.uuid4())}),
    ):
        with pytest.raises(WriteRefusedError):
            await admin_actions.plan_admin_action(
                name,
                json.dumps(args),
                principal=_admin(token, "operator"),
                viewing_tenant_id=tenant_id,
            )


async def _admin_read(name: str, role: str = "superadmin", **args: Any) -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=None, role=role),
        registry=service._read_tool_registry("admin"),
    )


async def test_the_kyc_queue_lists_a_waiting_client() -> None:
    tenant_id, slug, _client_token = await _make_tenant()
    await _submitted_kyc(tenant_id)
    result = await _admin_read("admin_kyc_queue", limit=200)
    assert slug in result
    assert "open that client's page" in result


async def test_a_clients_kyc_can_be_asked_by_slug_from_any_screen() -> None:
    """FAILS IF "is X verified?" again needs X's page open: the tool resolves the client by
    slug and states the KYC status in words, under that client's own session."""
    from tests.conftest import verify_kyc_and_pledge_for_tests

    tenant_id, slug, _client_token = await _make_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    result = await _admin_read("admin_client_standing", role="operator", client=slug)
    assert f"({slug})" in result
    assert "Business verification (KYC): verified" in result
    assert "No-cold-calls pledge: accepted." in result
    missing = await _admin_read("admin_client_standing", client=f"nobody-{uuid.uuid4().hex}")
    assert missing.startswith("No client")


@pytest.mark.parametrize(
    "name",
    ["admin_held_accounts", "admin_alerts", "admin_voices", "admin_dead_letters"],
)
async def test_each_admin_board_answers_in_a_sentence(name: str) -> None:
    result = await _admin_read(name)
    assert result and "could not be read" not in result, result


async def test_an_operator_cannot_read_the_superadmin_boards() -> None:
    for name in ("admin_alerts", "admin_voices"):
        assert (await _admin_read(name, role="operator")).startswith("Refused"), name


def test_the_admin_reads_are_appended_after_the_first_four() -> None:
    names = [tool.name for tool in admin_tools.ADMIN_READ_TOOLS]
    assert names[:4] == [
        "platform_tenants",
        "platform_health",
        "platform_ops_state",
        "search_runbooks",
    ]
    assert names[4:] == [
        "admin_kyc_queue",
        "admin_held_accounts",
        "admin_alerts",
        "admin_voices",
        "admin_client_standing",
        "healer_incidents",
        "healer_incident",
        "healer_money_review",
        "admin_diagnose",
        "admin_rate_card",
        # D-934 APPENDS.
        "fleet_chart",
        # A7-19 APPENDS.
        "admin_call_line_requests",
        "admin_dead_letters",
    ]


async def _asking_for_lines(tenant_id: UUID) -> UUID:
    """An open request for more calls at once, as the client's own Ask makes it."""
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_line_requests (id, tenant_id, status, lines_at_request, "
                "  wanted_lines, created_at, updated_at) "
                "VALUES (:id, :tid, 'open', 2, 4, now(), now())"
            ),
            {"id": request_id, "tid": tenant_id},
        )
    return request_id


async def test_the_call_line_requests_read_lists_an_asking_client() -> None:
    """A7-19: the bell's list, through the assistant."""
    tenant_id, _slug, _client_token = await _make_tenant()
    await _asking_for_lines(tenant_id)
    result = await _admin_read("admin_call_line_requests")
    assert f"[tenant_id {tenant_id}]" in result
    assert "wants 4" in result
    assert "admin_call_lines_raise" in result


async def test_a_call_line_request_is_declined_through_the_assistant() -> None:
    """A7-19: the Decline button's write, after a click, on the request the card showed."""
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    request_id = await _asking_for_lines(tenant_id)
    with pytest.raises(WriteRefusedError):
        await admin_actions.plan_admin_action(
            "admin_call_lines_decline",
            json.dumps({"reason": "   "}),
            principal=_admin(token, "operator"),
            viewing_tenant_id=tenant_id,
        )
    proposal = await admin_actions.plan_admin_action(
        "admin_call_lines_decline",
        json.dumps({"reason": "Two lines cover your calls for now."}),
        principal=_admin(token, "operator"),
        viewing_tenant_id=tenant_id,
    )
    assert proposal.proposed == "declined"
    done = await _confirm(token, proposal, role="operator")
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, decline_reason FROM call_line_requests WHERE id = :id"),
                {"id": request_id},
            )
        ).first()
    assert row is not None
    assert tuple(row) == ("declined", "Two lines cover your calls for now.")
    with pytest.raises(WriteRefusedError) as again:
        await admin_actions.plan_admin_action(
            "admin_call_lines_decline",
            json.dumps({"reason": "No."}),
            principal=_admin(token, "operator"),
            viewing_tenant_id=tenant_id,
        )
    assert "no open request" in again.value.reason


async def test_raising_call_lines_through_the_assistant_answers_the_request() -> None:
    """A7-19: the raise takes the panel's confirmation and closes the open request."""
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    await _asking_for_lines(tenant_id)
    from apps.api.tenancy.call_lines import read_call_lines

    async with tenant_session(tenant_id) as session:
        before = (await read_call_lines(session, tenant_id=tenant_id)).lines
    with pytest.raises(WriteRefusedError):
        await admin_actions.plan_admin_action(
            "admin_call_lines_raise",
            json.dumps({"call_lines": before}),
            principal=_admin(token, "operator"),
            viewing_tenant_id=tenant_id,
        )
    proposal = await admin_actions.plan_admin_action(
        "admin_call_lines_raise",
        json.dumps({"call_lines": before + 1}),
        principal=_admin(token, "operator"),
        viewing_tenant_id=tenant_id,
    )
    assert proposal.confirm_action == f"set_call_lines:{tenant_id}"
    done = await _confirm(token, proposal, role="operator")
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        after = (await read_call_lines(session, tenant_id=tenant_id)).lines
    assert after == before + 1

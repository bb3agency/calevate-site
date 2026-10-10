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
        "admin_first_campaign_decide",
        "admin_workspace_provision",
        "admin_number_release",
        "admin_voice_set",
    ]
    for tool in admin_actions.ADMIN_ACTIONS:
        assert tool.tier == "confirm", tool.name
    admin = json.dumps(service.tool_array("admin"))
    client = json.dumps(service.tool_array("client"))
    assert '"admin_kyc_review"' in admin and '"admin_kyc_review"' not in client


async def test_a_per_client_action_needs_a_clients_page_open() -> None:
    token = await _make_admin()
    with pytest.raises(WriteRefusedError) as refused:
        await admin_actions.plan_admin_action(
            "admin_first_campaign_decide",
            json.dumps({"decision": "approved", "note": "Checked the list and script"}),
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
    assert proposal.confirm_action is None and proposal.proposed == "rejected"
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


async def test_the_first_campaign_hold_is_released_by_confirm() -> None:
    token = await _make_admin(role="operator")
    tenant_id, _slug, _client_token = await _make_tenant()
    proposal = await admin_actions.plan_admin_action(
        "admin_first_campaign_decide",
        json.dumps({"decision": "approved", "note": "Checked the list and the script"}),
        principal=_admin(token, "operator"),
        viewing_tenant_id=tenant_id,
    )
    await _confirm(token, proposal, role="operator")
    async with tenant_session(tenant_id) as session:
        status = (await session.execute(text("SELECT status FROM first_campaign_reviews"))).scalar()
    assert status == "approved"


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


@pytest.mark.parametrize("name", ["admin_held_accounts", "admin_alerts", "admin_voices"])
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
    ]

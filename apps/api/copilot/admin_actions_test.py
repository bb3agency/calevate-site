"""D-694: the admin assistant can act — through its own confirm door, with the console
button's step-up — and can open admin screens; neither leaks into the client realm."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from tests.admin_security_test import _make_admin

from apps.api.copilot import admin_actions, admin_screens, service
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.navigation import NavigationRefusedError
from apps.api.core.context import Principal
from apps.api.core.loadshed import set_platform_status
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.service import read_halt_state

CONFIRM = "/v1/admin/copilot/confirm"


def _admin(token: str, role: str = "superadmin") -> Principal:
    return Principal(
        realm="admin", user_id=UUID(token.rsplit(":", 1)[1]), tenant_id=None, role=role
    )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def test_each_realm_has_its_own_fixed_tool_array() -> None:
    """Byte-identical within a realm, and the admin actions only in the admin array."""
    client = json.dumps(service.tool_array("client"))
    admin = json.dumps(service.tool_array("admin"))
    assert client == json.dumps(service.tool_array("client"))
    assert admin == json.dumps(service.tool_array("admin"))
    assert "platform_halt_outbound" in admin and "platform_halt_outbound" not in client
    assert service.BACKGROUND_TOOL_NAME in client and service.BACKGROUND_TOOL_NAME not in admin
    assert '"open_screen"' in admin and '"open_screen"' in client


def test_every_admin_action_is_confirm_tier() -> None:
    for tool in admin_actions.ADMIN_ACTIONS:
        assert tool.tier == "confirm", tool.name


async def test_the_halt_is_proposed_not_done() -> None:
    token = await _make_admin()
    await set_platform_status(outbound_halted=False, halt_reason=None, actor_id=None)
    proposal = await admin_actions.plan_admin_action(
        "platform_halt_outbound",
        json.dumps({"reason": "drill"}),
        principal=_admin(token),
        viewing_tenant_id=None,
    )
    assert proposal.confirm_action == "halt_outbound"
    assert proposal.proposed == "Halted"
    async with untenanted_session() as session:
        assert (await read_halt_state(session)).outbound_halted is False


async def test_an_operator_role_without_ops_manage_is_offered_nothing() -> None:
    token = await _make_admin(role="operator")
    with pytest.raises(WriteRefusedError):
        await admin_actions.plan_admin_action(
            "platform_halt_outbound",
            json.dumps({"reason": "drill"}),
            principal=_admin(token, role="operator"),
            viewing_tenant_id=None,
        )


async def test_confirm_needs_the_buttons_step_up_header_and_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.ops import halt

    queued: list[str] = []

    async def _record(job: str, *args: object, **kwargs: object) -> str:
        queued.append(job)
        return "job-id"

    monkeypatch.setattr(halt, "enqueue", _record)
    token = await _make_admin()
    await set_platform_status(outbound_halted=False, halt_reason=None, actor_id=None)
    proposal = await admin_actions.plan_admin_action(
        "platform_halt_outbound",
        json.dumps({"reason": "drill"}),
        principal=_admin(token),
        viewing_tenant_id=None,
    )
    auth = {"Authorization": f"Bearer {token}"}
    try:
        async with _client() as http:
            missing = await http.post(CONFIRM, headers=auth, json={"token": proposal.token})
            assert missing.status_code == 403, missing.text
            assert missing.json()["type"].endswith("/step_up_required")

            done = await http.post(
                CONFIRM,
                headers={**auth, "X-Confirm-Action": "halt_outbound"},
                json={"token": proposal.token},
            )
            assert done.status_code == 200, done.text
            assert done.json()["applied"] is True

            replay = await http.post(
                CONFIRM,
                headers={**auth, "X-Confirm-Action": "halt_outbound"},
                json={"token": proposal.token},
            )
            assert replay.status_code == 403
        async with untenanted_session() as session:
            assert (await read_halt_state(session)).outbound_halted is True

        async with _client() as http:
            listed = await http.get("/v1/admin/copilot/actions", headers=auth)
        assert listed.status_code == 200, listed.text
        rows = listed.json()["actions"]
        assert rows[0]["tool"] == "platform_halt_outbound"
        assert rows[0]["realm"] == "admin"
        assert rows[0]["can_undo"] is False
    finally:
        await set_platform_status(outbound_halted=False, halt_reason=None, actor_id=None)


async def test_a_client_token_is_refused_at_the_admin_door() -> None:
    from tests.api_security_test import _make_tenant

    from apps.api.copilot import write_tools

    tenant_id, _slug, client_token = await _make_tenant()
    admin_token = await _make_admin()
    # A client-realm proposal, signed by the same key under the CLIENT audience.
    from sqlalchemy import text

    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        lead = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar()
    actor = write_tools.actor_for(
        Principal(
            realm="client",
            user_id=UUID(client_token.rsplit(":", 1)[1]),
            tenant_id=tenant_id,
            role="owner",
        )
    )
    proposal = await write_tools.plan_write(
        "dnc_add", json.dumps({"lead_id": str(lead), "reason": "manual"}), actor=actor
    )
    async with _client() as http:
        refused = await http.post(
            CONFIRM,
            headers={"Authorization": f"Bearer {admin_token}", "X-Confirm-Action": "x"},
            json={"token": proposal.token},
        )
    assert refused.status_code == 403
    assert refused.json()["type"].endswith("/copilot_proposal_invalid")


def test_admin_navigation_opens_only_sidebar_screens_the_role_may_open() -> None:
    opened = admin_screens.resolve_admin_destination(
        json.dumps({"screen": "client health"}), role="operator", current_route="/admin"
    )
    assert opened.route == "/admin/health"
    with pytest.raises(NavigationRefusedError):
        admin_screens.resolve_admin_destination(
            json.dumps({"screen": "Operations"}), role="operator", current_route="/admin"
        )
    with pytest.raises(NavigationRefusedError):
        admin_screens.resolve_admin_destination(
            json.dumps({"screen": "/admin/../evil"}), role="superadmin", current_route="/admin"
        )


def test_the_admin_inventory_matches_the_admin_sidebar() -> None:
    """`adminNav.ts` is the source of truth; every href and label it lists is here, in order."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "apps/web/src/app/admin/adminNav.ts").read_text(
        encoding="utf-8"
    )
    hrefs = re.findall(r'href: "([^"]+)"', source)
    labels = re.findall(r'label: "([^"]+)"', source)
    assert [screen.route for screen in admin_screens.ADMIN_SCREENS] == hrefs
    assert [screen.name for screen in admin_screens.ADMIN_SCREENS] == labels

"""D-694: an immediate action is logged with the state it overwrote, and Undo puts it back —
only for the person who asked, only inside the window, and only if nothing changed since.

Every test mints its own tenant; the shared stores are keyed per action or per proposal.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import action_log, write_tools
from apps.api.copilot.actions import ACTION_TIERS, ActionTool, Undo, action_schema
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session
from apps.api.main import app


def _principal(tenant_id: UUID, user_id: UUID, *, role: str = "owner") -> Principal:
    return Principal(realm="client", user_id=user_id, tenant_id=tenant_id, role=role)


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _lead_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _lead_status(tenant_id: UUID, lead_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(text("SELECT status FROM leads WHERE id = :i"), {"i": lead_id})
        ).scalar()
    return str(value)


async def _set_status(tenant_id: UUID, lead_id: UUID, status: str, token: str) -> Any:
    return await write_tools.run_immediate(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": status}),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"undo-test-{uuid.uuid4()}",
        ip=None,
    )


async def _row(tenant_id: UUID, action_id: str) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, tier, prior_state, result_state, args_redacted, "
                    "undoable_until, actor_user_id FROM copilot_actions WHERE id = :i"
                ),
                {"i": UUID(action_id)},
            )
        ).first()


def test_an_immediate_tool_without_an_inverse_cannot_be_registered() -> None:
    """The tier's rule, extended to the Undo: neither field has a default, and the wrong
    pairing fails at construction rather than in production."""

    async def _noop(*_: Any) -> Any:  # pragma: no cover - never called
        return None

    common: dict[str, Any] = {
        "permission": "leads:write",
        "object_type": "lead",
        "audit_action": "x",
        "schema": action_schema("x", "x", {}),
        "plan": _noop,
        "execute": _noop,
        "where": "x",
    }
    with pytest.raises(ValueError, match="inverse"):
        ActionTool(name="x", tier="immediate", undo=None, **common)
    with pytest.raises(ValueError, match="irreversible"):
        ActionTool(name="x", tier="confirm", undo=Undo(capture=_noop, invert=_noop), **common)
    assert set(ACTION_TIERS) == {"immediate", "confirm"}


def test_every_immediate_tool_carries_an_inverse_and_every_confirm_tool_none() -> None:
    """Derived from the registry, so a new tool is covered the day it is registered."""
    for tool in write_tools.WRITE_TOOLS:
        assert (tool.undo is not None) == (tool.tier == "immediate"), tool.name
    assert "lead_set_status" in write_tools.immediate_tool_names()
    assert write_tools.tier_of("dnc_add") == "confirm"


async def test_an_immediate_action_is_logged_with_the_state_it_overwrote() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    before = await _lead_status(tenant_id, lead_id)

    receipt = await _set_status(tenant_id, lead_id, "hot", token)
    assert receipt.applied is True
    assert receipt.action_id is not None
    assert receipt.undoable_until is not None

    row = await _row(tenant_id, receipt.action_id)
    assert row is not None
    status, tier, prior, result, args, until, actor = row
    assert (status, tier) == ("done", "immediate")
    assert prior == {"status": before}
    assert result == {"status": "hot"}
    assert args == {"lead_id": str(lead_id), "status": "hot"}
    assert until is not None
    assert actor == _user_of(token)


async def test_undo_puts_it_back_once_and_the_second_click_is_told_so() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    before = await _lead_status(tenant_id, lead_id)
    receipt = await _set_status(tenant_id, lead_id, "hot", token)

    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["tool"] == "lead_set_status"
        assert await _lead_status(tenant_id, lead_id) == before

        again = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert again.status_code == 409
    assert again.json()["type"].endswith("/copilot_action_already_undone")
    row = await _row(tenant_id, receipt.action_id)
    assert row is not None and row[0] == "undone"


async def test_undo_refuses_when_the_record_changed_since() -> None:
    """The compare half of the CAS: a status somebody moved after the assistant did is
    left alone, and the row stays undoable-in-principle but `done`."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    receipt = await _set_status(tenant_id, lead_id, "hot", token)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE leads SET status = 'won' WHERE id = :i"), {"i": lead_id})

    async with _client() as http:
        refused = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token, slug)
        )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_action_changed_since")
    assert await _lead_status(tenant_id, lead_id) == "won"


async def test_another_tenants_action_is_not_found() -> None:
    """Hard rule 1: tenant B cannot undo, or even see, tenant A's action."""
    tenant_a, _slug_a, token_a = await _make_tenant()
    _tenant_b, slug_b, token_b = await _make_tenant()
    lead_id = await _lead_of(tenant_a)
    receipt = await _set_status(tenant_a, lead_id, "hot", token_a)

    async with _client() as http:
        crossed = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo", headers=_headers(token_b, slug_b)
        )
        listed = await http.get("/v1/copilot/actions", headers=_headers(token_b, slug_b))
    assert crossed.status_code == 404
    assert listed.status_code == 200
    assert listed.json()["actions"] == []
    assert await _lead_status(tenant_a, lead_id) == "hot"


async def test_copilot_actions_rls_returns_zero_rows_across_tenants() -> None:
    """The cross-tenant zero-rows test hard rule 1 asks of every new tenant table."""
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    await _set_status(tenant_a, await _lead_of(tenant_a), "hot", token_a)
    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM copilot_actions"))).scalar()
    assert seen == 0


async def test_the_activity_log_lists_my_actions_with_can_undo() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    receipt = await _set_status(tenant_id, lead_id, "contacted", token)
    async with _client() as http:
        page = await http.get("/v1/copilot/actions", headers=_headers(token, slug))
    assert page.status_code == 200, page.text
    rows = page.json()["actions"]
    assert rows[0]["id"] == receipt.action_id
    assert rows[0]["can_undo"] is True
    assert rows[0]["tier"] == "immediate"


async def test_a_refusal_is_logged_without_its_arguments() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await action_log.record_refusal(
        realm="client",
        tenant_id=tenant_id,
        actor_id=_user_of(token),
        tool="dnc_add",
        tier="confirm",
        object_type="lead",
        reason="this person's role may not do what `dnc_add` proposes",
    )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, args_redacted, refusal_reason FROM copilot_actions")
            )
        ).first()
    assert row is not None
    assert row[0] == "refused"
    assert row[1] is None
    assert "role may not" in str(row[2])


def test_redacted_args_keep_ids_and_drop_phone_numbers() -> None:
    lead = str(uuid.uuid4())
    cleaned = action_log.redact_args({"lead_id": lead, "body": "call me on 9876543210"})
    assert cleaned["lead_id"] == lead
    assert "9876543210" not in cleaned["body"]

"""D-934: pinned dashboard cards — the query is stored, never the figures; the card re-runs
for each viewer; the account's cards are invisible to every other account; Pip's pin and
unpin run at once and Undo exactly."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.analytics_summary_test import _debit
from tests.analytics_test import _agent, _call, _ist, _today_ist
from tests.api_security_test import _make_tenant

from apps.api.copilot import pins, undo, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.write_tools_test import _principal, _user_of
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _staff_on(tenant_id: UUID) -> str:
    """A staff member on an existing account, as a dev bearer token."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'staff', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{user_id}"


async def test_a_pin_stores_the_query_and_each_viewer_sees_their_own_answer() -> None:
    tenant_id, slug, owner = await _make_tenant()
    staff = await _staff_on(tenant_id)
    async with tenant_session(tenant_id) as session:
        await _debit(session, tenant_id, "4.00", _ist(_today_ist(), 10), "96.00")
    async with _client() as http:
        made = await http.post(
            "/v1/copilot/pins",
            json={"chart": "spend_by_day", "args": {"days": 7}, "title": "  Spend  this week "},
            headers=_headers(owner, slug),
        )
        assert made.status_code == 201, made.text
        pin_id = made.json()["id"]
        assert made.json()["title"] == "Spend this week"
        mine = await http.get(f"/v1/copilot/pins/{pin_id}/card", headers=_headers(owner, slug))
        theirs = await http.get(f"/v1/copilot/pins/{pin_id}/card", headers=_headers(staff, slug))
        listed = await http.get("/v1/copilot/pins", headers=_headers(staff, slug))

    assert mine.json()["spec"]["total"] == "4.00" and mine.json()["refused"] is None
    assert theirs.json()["spec"] is None and "billing:read" in theirs.json()["refused"]
    assert [p["id"] for p in listed.json()["pins"]] == [pin_id]
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT args FROM dashboard_pins WHERE id = :id"), {"id": pin_id}
            )
        ).scalar_one()
    assert stored == {"days": 7}


async def test_rename_reorder_remove_and_restore() -> None:
    _tenant, slug, owner = await _make_tenant()
    h = _headers(owner, slug)
    async with _client() as http:
        first = (
            await http.post(
                "/v1/copilot/pins", json={"chart": "calls_by_day", "title": "A"}, headers=h
            )
        ).json()
        second = (
            await http.post(
                "/v1/copilot/pins", json={"chart": "hot_leads", "title": "B"}, headers=h
            )
        ).json()
        renamed = await http.patch(
            f"/v1/copilot/pins/{first['id']}", json={"title": "Calls"}, headers=h
        )
        ordered = await http.put(
            "/v1/copilot/pins/order", json={"ids": [second["id"], first["id"]]}, headers=h
        )
        stale = await http.put("/v1/copilot/pins/order", json={"ids": [first["id"]]}, headers=h)
        removed = await http.delete(f"/v1/copilot/pins/{second['id']}", headers=h)
        after_remove = await http.get("/v1/copilot/pins", headers=h)
        restored = await http.post(f"/v1/copilot/pins/{second['id']}/restore", headers=h)
        after_restore = await http.get("/v1/copilot/pins", headers=h)

    assert renamed.json()["title"] == "Calls"
    assert [p["id"] for p in ordered.json()["pins"]] == [second["id"], first["id"]]
    assert stale.status_code == 409
    assert removed.status_code == 200
    assert [p["id"] for p in after_remove.json()["pins"]] == [first["id"]]
    assert restored.status_code == 200
    assert [p["id"] for p in after_restore.json()["pins"]] == [second["id"], first["id"]]


async def test_a_home_holds_twelve_cards_and_refuses_the_thirteenth() -> None:
    _tenant, slug, owner = await _make_tenant()
    h = _headers(owner, slug)
    async with _client() as http:
        for n in range(pins.MAX_PINS):
            ok = await http.post(
                "/v1/copilot/pins", json={"chart": "calls_by_day", "title": f"C{n}"}, headers=h
            )
            assert ok.status_code == 201
        full = await http.post(
            "/v1/copilot/pins", json={"chart": "calls_by_day", "title": "X"}, headers=h
        )
        unknown = await http.post(
            "/v1/copilot/pins", json={"chart": "fleet_calls", "title": "X"}, headers=h
        )
    assert full.status_code == 409 and "pin_limit" in full.text
    assert unknown.status_code in (404, 409, 422)


async def test_another_accounts_pins_are_zero_rows() -> None:
    mine, slug, owner = await _make_tenant()
    _other, other_slug, other = await _make_tenant()
    async with tenant_session(mine) as session:
        await _call(session, mine, await _agent(session), at=_ist(_today_ist(), 9))
    async with _client() as http:
        made = (
            await http.post(
                "/v1/copilot/pins",
                json={"chart": "calls_by_day", "title": "Mine"},
                headers=_headers(owner, slug),
            )
        ).json()
        listed = await http.get("/v1/copilot/pins", headers=_headers(other, other_slug))
        card = await http.get(
            f"/v1/copilot/pins/{made['id']}/card", headers=_headers(other, other_slug)
        )
        removed = await http.delete(
            f"/v1/copilot/pins/{made['id']}", headers=_headers(other, other_slug)
        )
    assert listed.json()["pins"] == []
    assert card.status_code == 404 and removed.status_code == 404
    async with tenant_session(_other) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM dashboard_pins"))
        ).scalar_one() == 0


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"pins-{uuid.uuid4()}",
        ip=None,
    )


async def _undo(tenant_id: UUID, token: str, action_id: str) -> str:
    async with tenant_session(tenant_id) as session:
        out = await undo.undo_client_action(
            session, UUID(action_id), principal=_principal(tenant_id, _user_of(token)), ip=None
        )
    return out.detail


async def test_pip_pins_and_unpins_at_once_and_undo_is_exact() -> None:
    tenant_id, _slug, owner = await _make_tenant()
    pinned = await _run(
        tenant_id, owner, "chart_pin", {"chart": "leads_by_status", "days": 14, "title": "Leads"}
    )
    assert pinned.applied and pinned.action_id
    async with tenant_session(tenant_id) as session:
        rows = await pins.list_pins(session, "client")
    assert [(r.chart, r.args.days, r.title) for r in rows] == [("leads_by_status", 14, "Leads")]

    assert await _undo(tenant_id, owner, pinned.action_id) == "Taken off the home screen."
    async with tenant_session(tenant_id) as session:
        assert await pins.list_pins(session, "client") == []

    again = await _run(
        tenant_id, owner, "chart_pin", {"chart": "hot_leads", "days": None, "title": "Hot"}
    )
    unpinned = await _run(tenant_id, owner, "chart_unpin", {"title": "hot"})
    assert unpinned.applied and unpinned.object_id == again.object_id
    assert await _undo(tenant_id, owner, unpinned.action_id) == "Back on the home screen."
    async with tenant_session(tenant_id) as session:
        assert [str(r.id) for r in await pins.list_pins(session, "client")] == [again.object_id]


async def test_pip_refuses_a_chart_it_does_not_have_and_a_card_that_is_not_there() -> None:
    tenant_id, _slug, owner = await _make_tenant()
    with pytest.raises(WriteRefusedError, match="not one of report_chart"):
        await _run(tenant_id, owner, "chart_pin", {"chart": "fleet_spend", "days": 7, "title": "X"})
    with pytest.raises(WriteRefusedError, match="no card"):
        await _run(tenant_id, owner, "chart_unpin", {"title": "Nothing"})


async def test_the_admin_home_has_its_own_cards() -> None:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Anand', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    h = {"Authorization": f"Bearer dev:admin:{admin_id}"}
    async with _client() as http:
        made = await http.post(
            "/v1/admin/copilot/pins",
            json={"chart": "fleet_failures", "title": "Problems"},
            headers=h,
        )
        client_chart = await http.post(
            "/v1/admin/copilot/pins", json={"chart": "calls_by_day", "title": "X"}, headers=h
        )
        card = await http.get(f"/v1/admin/copilot/pins/{made.json()['id']}/card", headers=h)
        removed = await http.delete(f"/v1/admin/copilot/pins/{made.json()['id']}", headers=h)
    assert made.status_code == 201, made.text
    assert client_chart.status_code != 201
    assert card.json()["spec"]["chart"] == "fleet_failures"
    assert removed.status_code == 200

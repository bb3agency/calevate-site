"""The client and admin surfaces of the per-client workspace (D-693).

Client (`/v1/numbers/own/*`): where the account stands, its business details, the cities and
numbers it could buy at OUR monthly price, buying and releasing — and no vendor name in any
answer (white-label, D-679). Admin (`/v1/admin/engine-workspaces/*`): the tenant's workspace,
retry, buy/release/forget in the client's name, and the ops summary with the plan headroom.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.engine_number_purchase_test import _attested, _client
from tests.number_provisioning_flow_test import _member
from tests.thinnest_fake_account import FakeAccount
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]

VENDOR_WORDS = ("thinnest", "ThinnestAI", "org_")


async def _client_headers(tenant_id: UUID) -> dict[str, str]:
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    return {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": str(slug)}


async def _admin_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _white_label(body: Any) -> None:
    text_body = json.dumps(body)
    for word in VENDOR_WORDS:
        assert word not in text_body, f"client answer names the platform: {word}"


async def test_a_client_walks_status_search_buy_and_release_without_a_vendor_name(
    account: FakeAccount,
) -> None:
    price = await _attested()
    tenant_id, workspace = await _client(account)
    headers = await _client_headers(tenant_id)
    async with _http() as http:
        status = await http.get("/v1/numbers/own/status", headers=headers)
        assert status.status_code == 200, status.text
        assert (status.json()["step"], status.json()["inr_per_month"]) == ("ready", str(price))
        _white_label(status.json())

        cities = await http.get("/v1/numbers/own/cities", headers=headers)
        assert cities.json() == [{"name": "Bangalore", "available": 25}]
        page = await http.get("/v1/numbers/own/available?city=Bangalore", headers=headers)
        assert page.status_code == 200, page.text
        offered = page.json()
        assert offered["next_cursor"] == "20"
        assert {n["inr_per_month"] for n in offered["numbers"]} == {str(price)}
        # The numbers themselves are random digits, so only the non-number fields are read.
        priced = [
            {k: v for k, v in n.items() if k not in ("number", "e164")} for n in offered["numbers"]
        ]
        assert "349" not in json.dumps(priced), "the vendor's price never reaches a client"
        _white_label(offered)

        key = f"key-{uuid.uuid4().hex}"
        body = {"number": offered["numbers"][0]["number"], "request_key": key}
        bought = await http.post("/v1/numbers/own/purchase", json=body, headers=headers)
        assert bought.status_code == 201, bought.text
        assert bought.json()["first_period"] == "charged"
        _white_label(bought.json())
        again = await http.post("/v1/numbers/own/purchase", json=body, headers=headers)
        assert again.json()["replayed"] is True

        number_id = bought.json()["number_id"]
        refused = await http.post(
            f"/v1/numbers/own/{number_id}/release", json={"confirm": False}, headers=headers
        )
        assert refused.status_code == 422
        released = await http.post(
            f"/v1/numbers/own/{number_id}/release", json={"confirm": True}, headers=headers
        )
        assert released.json() == {"number_id": number_id, "released": True}
    assert not account.ws(workspace).numbers


async def test_the_status_says_set_up_while_the_workspace_is_not_ready(
    account: FakeAccount,
) -> None:
    await _attested()
    tenant_id, _workspace = await _client(account)
    await give_own_workspace(tenant_id, status="plan_limit")
    headers = await _client_headers(tenant_id)
    async with _http() as http:
        status = await http.get("/v1/numbers/own/status", headers=headers)
        assert status.json()["step"] == "workspace"
        _white_label(status.json())
        buy = await http.post(
            "/v1/numbers/own/purchase",
            json={"number": "918012345678", "request_key": f"key-{uuid.uuid4().hex}"},
            headers=headers,
        )
    assert buy.status_code == 422 or buy.status_code == 409, buy.text
    assert "engine_workspace_not_provisioned" in buy.text
    _white_label(buy.json())


async def test_the_number_screens_are_absent_where_clients_have_no_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.engine_workspace_test import _tenant

    tenant_id = await _tenant()
    headers = await _client_headers(tenant_id)
    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    async with _http() as http:
        status = await http.get("/v1/numbers/own/status", headers=headers)
        assert status.json()["available"] is False
        assert (await http.get("/v1/numbers/own/cities", headers=headers)).status_code == 404


async def test_an_admin_sees_the_workspace_buys_releases_and_forgets(
    account: FakeAccount,
) -> None:
    await _attested()
    tenant_id, workspace = await _client(account)
    headers = await _admin_headers()
    base = f"/v1/admin/engine-workspaces/tenants/{tenant_id}"
    async with _http() as http:
        view = await http.get(base, headers=headers)
        assert view.status_code == 200, view.text
        assert (view.json()["status"], view.json()["workspace_id"]) == ("active", workspace)
        assert view.json()["purchase_step"] == "ready"

        page = await http.get(f"{base}/numbers/available", headers=headers)
        first = page.json()["numbers"][0]
        assert first["vendor_inr_per_month"] == "349"
        bought = await http.post(
            f"{base}/numbers/purchase",
            json={"number": first["number"], "request_key": f"key-{uuid.uuid4().hex}"},
            headers=headers,
        )
        assert bought.status_code == 201, bought.text
        number_id = bought.json()["number_id"]

        still = await http.post(
            f"{base}/numbers/{number_id}/forget", json={"confirm": True}, headers=headers
        )
        assert "engine_number_still_held" in still.text
        released = await http.post(
            f"{base}/numbers/{number_id}/release", json={"confirm": True}, headers=headers
        )
        assert released.json()["released"] is True

        again = await http.post(f"{base}/provision", headers=headers)
        assert again.status_code == 200 and again.json()["status"] == "active"


async def test_the_ops_summary_counts_workspaces_against_the_plan(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.engine_workspace_test import _tenant

    waiting = await _tenant()
    await give_own_workspace(waiting, status="plan_limit")
    monkeypatch.setattr(get_settings(), "thinnest_customer_plan", "pro")
    async with _http() as http:
        summary = await http.get(
            "/v1/admin/engine-workspaces/summary", headers=await _admin_headers()
        )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert (body["plan"], body["plan_cap"]) == ("pro", 100)
    assert body["headroom"] == max(100 - body["counted"], 0)
    assert body["by_status"].get("plan_limit", 0) >= 1

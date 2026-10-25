"""The operator's WhatsApp board (D-784) lists clients that HAVE WhatsApp.

Its cap bounds the clients shown, not the directory walked: a cap on the directory hid every
connected client whose name sorted after the first `MAX_CLIENTS` accounts.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.whatsapp import admin_routes
from sqlalchemy import text
from tests.api_security_test import _make_tenant


async def _operator() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def test_a_connected_client_is_listed_wherever_its_name_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two plain accounts that sort first, so a cap of one on the directory would walk only
    # an account with no WhatsApp.
    for _ in range(2):
        plain_id, _slug, _token = await _make_tenant()
        async with tenant_session(plain_id) as session:
            await session.execute(
                text("UPDATE organizations SET name = :n WHERE id = :id"),
                {"n": f"   AAAA {plain_id.hex[:6]}", "id": plain_id},
            )
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET name = :n WHERE id = :id"),
            {"n": f"zzzz WhatsApp {tenant_id.hex[:6]}", "id": tenant_id},
        )
        # Heard from in the future, so it is the newest whatever else this database holds.
        await session.execute(
            text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, waba_id, onboarding, status, "
                "last_event_at) VALUES (:i, :t, '1' || abs(hashtext(CAST(:i AS text)))::text, "
                "'new', 'connected', now() + interval '1 day')"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
    monkeypatch.setattr(admin_routes, "MAX_CLIENTS", 1)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        response = await http.get("/v1/admin/whatsapp", headers=await _operator())

    assert response.status_code == 200, response.text
    listed = [client["tenant_id"] for client in response.json()["clients"]]
    assert listed == [str(tenant_id)]

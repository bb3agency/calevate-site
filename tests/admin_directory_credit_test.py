"""The client directory's credit column: minutes first, rupees second, and only where a
wallet exists.

The redesigned roster (REDESIGN-2, founder decision 10 Oct 2026) shows each client's
credit left beside its name, and the property worth pinning is that the roster quotes the
SAME figures the client's own credits screen quotes — `wallet.tier_minutes` and
`service.get_balance`, read inside the client's own tenant session — rather than a second
derivation that could drift. Three cases:

1. a prepaid account carries its balance and the per-quality minutes its wallet computes;
2. an invoiced (`managed`) account has no wallet, so both fields are null, never zero;
3. the assistant's unpaged roster walk does not pay for the credit reads at all.

CONCURRENCY: every case mints its own tenant and asserts only on that tenant's row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.billing.service import get_balance, record_entry, to_paise
from apps.api.billing.wallet import tier_minutes
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


async def _tenant(plan_tier: str, *, topup: Decimal | None = None) -> UUID:
    created = await admin_service.create_organization(
        name="Directory Credit Traders",
        slug=f"dircredit-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :t"),
            {"tier": plan_tier, "t": tenant_id},
        )
        if topup is not None:
            await record_entry(
                session, tenant_id=tenant_id, delta=topup, reason="topup", ref=f"rzp_{tenant_id}"
            )
    return tenant_id


async def _row(tenant_id: UUID, *, with_credit: bool) -> dict[str, Any]:
    async with admin_session() as session:
        rows = await admin_service.tenant_overview(
            session, tenant_id=tenant_id, with_credit=with_credit
        )
    assert len(rows) == 1
    return rows[0]


async def test_a_prepaid_row_quotes_what_the_credits_screen_quotes() -> None:
    tenant_id = await _tenant("prepaid", topup=Decimal("300.00"))

    row = await _row(tenant_id, with_credit=True)
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        minutes = await tier_minutes(session, tenant_id=tenant_id)

    assert row["credit_inr"] == to_paise(balance.amount_inr) == Decimal("300.00")
    assert row["minutes_left"] == [
        {"voice_tier": tier.voice_tier, "label": tier.label, "minutes": tier.minutes}
        for tier in minutes
    ], "the roster's minutes must be the wallet's own pair, in catalogue order"


async def test_an_invoiced_row_has_no_credit_to_quote() -> None:
    tenant_id = await _tenant("managed")

    row = await _row(tenant_id, with_credit=True)

    assert row["credit_inr"] is None
    assert row["minutes_left"] is None


async def test_the_unpaged_walk_does_not_read_the_wallet() -> None:
    tenant_id = await _tenant("prepaid", topup=Decimal("50.00"))

    row = await _row(tenant_id, with_credit=False)

    assert row["credit_inr"] is None and row["minutes_left"] is None, (
        "the assistant's roster tool walks every client and must not pay for credit reads"
    )


async def test_the_directory_route_carries_the_credit_on_the_wire() -> None:
    tenant_id = await _tenant("prepaid", topup=Decimal("120.50"))
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    headers = {"Authorization": f"Bearer dev:admin:{admin_id}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["credit_inr"]) == Decimal("120.50")
    assert isinstance(body["minutes_left"], list) and body["minutes_left"], (
        "a prepaid client's row names its minutes per voice quality"
    )

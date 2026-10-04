"""The admin margin books the phone rental it already counts as cost (D-665).

`cost_inr` included the `number_rental` usage row — our carrier's price — and revenue had
no line for what the client was charged for the same number, so every renting client's
margin read low by the whole rental price. What is asserted:

1. a prepaid rental debit and an invoiced rental period both reach `revenue_inr`;
2. `rental_revenue_inr` is published beside it and equals the statement's rental lines;
3. the tenant spend page keeps its identity, now with three parts.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing.invoice import build_invoice
from apps.api.billing.number_rental import (
    RENTAL_CHARGE_LABEL,
    charge_number_rental,
    invoice_number_rental,
    rental_revenue_inr,
    today_ist,
)
from apps.api.billing.service import current_billing_month, margin_for_tenant
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.money_walk_test import _tenant
from tests.spend_attribution_test import _client, _make_admin

pytestmark = [pytest.mark.rls]

RENT = Decimal("499.00")


async def _prepaid_rental(tenant_id: uuid.UUID) -> None:
    today = today_ist()
    async with tenant_session(tenant_id) as session:
        await charge_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=uuid.uuid4(),
            anchor=today,
            period_start=today,
            inr_per_month=RENT,
        )


async def test_a_prepaid_rental_is_revenue_on_the_margin() -> None:
    tenant_id, _agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        before = await margin_for_tenant(session, tenant_id=tenant_id)
    await _prepaid_rental(tenant_id)

    async with tenant_session(tenant_id) as session:
        after = await margin_for_tenant(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert after["rental_revenue_inr"] == RENT
    assert after["revenue_inr"] - before["revenue_inr"] == RENT
    billed = sum(
        (i["amount_inr"] for i in invoice["line_items"] if i["description"] == RENTAL_CHARGE_LABEL),
        Decimal("0"),
    )
    assert after["rental_revenue_inr"] == billed, "the margin books what the statement bills"


async def test_an_invoiced_rental_is_revenue_on_the_margin() -> None:
    tenant_id, _agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :t"),
            {"t": tenant_id},
        )
        await invoice_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=uuid.uuid4(),
            period_start=today_ist(),
            inr_per_month=RENT,
        )
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
        rental = await rental_revenue_inr(
            session, tenant_id=tenant_id, month=current_billing_month()
        )

    assert rental == RENT
    assert margin["rental_revenue_inr"] == RENT


async def test_a_month_with_no_rental_books_none() -> None:
    tenant_id, _agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)

    assert margin["rental_revenue_inr"] == Decimal("0.00")


async def test_the_spend_page_revenue_is_its_three_parts() -> None:
    tenant_id, _agent_id = await _tenant()
    await _prepaid_rental(tenant_id)
    token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["rental_revenue_inr"]) == RENT
    retainer = Decimal(body["retainer_inr"] or "0")
    assert retainer + Decimal(body["period_charge_inr"]) + Decimal(
        body["rental_revenue_inr"]
    ) == Decimal(body["revenue_inr"])

    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
    assert Decimal(body["revenue_inr"]) == margin["revenue_inr"], (
        "the spend page and the margin card must book the same revenue"
    )

"""Invoice generation (ROADMAP M2, hard rule 7).

The invoice is a structured statement DERIVED from `usage_summary` — same ledger, same
IST month, same Decimals — so these tests assert the arithmetic a client could check
by hand, the deterministic invoice number, and the paise quantization at the boundary.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing.invoice import build_invoice
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

_TWO_DECIMALS = re.compile(r"\.\d{2}$")


async def _tenant_with_usage(
    *,
    minutes: int = 120,
    unit_cost: str = "0.5000",
    monthly_fee: str | None = "9999.00",
    included_min: int = 100,
    overage_rate: str = "8.0000",
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Invoice Clinic",
        slug=f"inv-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        if monthly_fee is not None:
            await session.execute(
                text(
                    "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                    "concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, :fee, :inc, "
                    ":rate, 10, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "fee": Decimal(monthly_fee),
                    "inc": included_min,
                    "rate": Decimal(overage_rate),
                },
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                ":qty, :cost, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "qty": Decimal(minutes * 60),
                "cost": Decimal(unit_cost),
            },
        )
    return tenant_id, call_id


async def test_the_invoice_adds_up_the_way_a_client_would_check_it() -> None:
    """₹9999 plan + 20 overage min at ₹8 = ₹10159 subtotal; 10159 * 0.18 = ₹1828.62
    exactly (no rounding hides anywhere); total ₹11987.62. Two line items."""
    tenant_id, _ = await _tenant_with_usage(
        minutes=120, monthly_fee="9999.00", included_min=100, overage_rate="8.0000"
    )
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["subtotal_inr"] == Decimal("10159.00")
    assert invoice["gst_rate_pct"] == Decimal("18")
    assert invoice["gst_inr"] == Decimal("1828.62")
    assert invoice["total_inr"] == Decimal("11987.62")

    assert len(invoice["line_items"]) == 2
    plan_line, overage_line = invoice["line_items"]
    assert plan_line["description"] == "Monthly plan fee"
    assert plan_line["qty"] == 1
    assert plan_line["unit_inr"] == Decimal("9999.00")
    assert plan_line["amount_inr"] == Decimal("9999.00")
    assert "20.00 min" in overage_line["description"]
    assert overage_line["amount_inr"] == Decimal("160.00")

    assert invoice["usage"]["minutes_used"] == Decimal("120.00")
    assert invoice["usage"]["calls"] == 1
    assert invoice["usage"]["included_minutes"] == 100


async def test_usage_within_the_included_minutes_produces_no_zero_overage_line() -> None:
    """40 minutes against 100 included → the plan fee is the ONLY line. A ₹0.00
    overage line on an invoice invites a dispute about nothing — the absence of a
    charge is stated by absence, not by a zero."""
    tenant_id, _ = await _tenant_with_usage(minutes=40, included_min=100)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert len(invoice["line_items"]) == 1
    assert invoice["line_items"][0]["description"] == "Monthly plan fee"
    assert invoice["subtotal_inr"] == Decimal("9999.00")


async def test_the_invoice_number_is_deterministic_per_tenant_month() -> None:
    """Rebuilding the same month yields the SAME number — a regenerated invoice can
    never silently duplicate. A different month yields a different number."""
    tenant_id, _ = await _tenant_with_usage(minutes=10)
    async with tenant_session(tenant_id) as session:
        first = await build_invoice(session, tenant_id=tenant_id)
        second = await build_invoice(session, tenant_id=tenant_id)
        other_month = await build_invoice(session, tenant_id=tenant_id, month="2026-01")

    assert first["invoice_number"] == second["invoice_number"]
    assert first["invoice_number"] != other_month["invoice_number"]
    month_part = first["month"].replace("-", "")
    assert first["invoice_number"] == f"CAL-{month_part}-{tenant_id.hex[:8]}"


async def test_every_money_field_is_a_paise_quantized_decimal() -> None:
    """NUMERIC(12,4) is storage precision; two decimals is what a rupee amount means
    to the person reading the invoice (hard rule 7 — and never a float)."""
    tenant_id, _ = await _tenant_with_usage(minutes=120)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    money = [invoice["subtotal_inr"], invoice["gst_inr"], invoice["total_inr"]]
    for item in invoice["line_items"]:
        money.extend([item["unit_inr"], item["amount_inr"]])
    for value in money:
        assert isinstance(value, Decimal), f"money is never a float: {value!r}"
        assert _TWO_DECIMALS.search(str(value)), f"not paise-quantized: {value!r}"


async def test_a_tenant_with_no_plan_still_gets_a_statement() -> None:
    """A client mid-onboarding has usage before a plan row exists. The invoice must
    still build — a usage-only statement with nothing to charge: no line items,
    ₹0.00 subtotal, ₹0.00 GST, ₹0.00 total."""
    tenant_id, _ = await _tenant_with_usage(minutes=30, monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["line_items"] == []
    assert invoice["subtotal_inr"] == Decimal("0.00")
    assert invoice["gst_inr"] == Decimal("0.00")
    assert invoice["total_inr"] == Decimal("0.00")
    assert invoice["usage"]["minutes_used"] == Decimal("30.00")

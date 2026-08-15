"""Invoice generation (ROADMAP M2, hard rule 7).

The invoice is a structured statement DERIVED from `usage_summary` — same ledger, same
IST month, same Decimals — so these tests assert the arithmetic a client could check
by hand, the deterministic invoice number, and the paise quantization at the boundary.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.invoice import _reconcile_overage, build_invoice
from apps.api.core.errors import ProblemError
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


def build_expected_number(tenant_id: Any, month_part: str) -> str:
    """Composed from the SHIPPED suffix function, never from a second copy of its layout.
    A test that re-derives the algorithm agrees with itself and proves nothing."""
    from apps.api.billing.invoice import _tenant_serial_suffix

    return f"CAL-{month_part}-{_tenant_serial_suffix(tenant_id)}"


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
    # The SHAPE, not the algorithm. This asserted `tenant_id.hex[:8]` until D-114, which
    # was not merely coupling the test to an implementation — it was asserting the defect:
    # tenant ids are uuid7, so the first eight hex characters are a millisecond timestamp
    # shifted right by 16, advancing once every 65.5 seconds. Any two clients onboarded in
    # the same minute shared this number, and the test could not see it because it only
    # ever compared against the same expression the code used.
    assert first["invoice_number"].startswith(f"CAL-{month_part}-")
    assert first["invoice_number"] == build_expected_number(tenant_id, month_part)


async def test_two_tenants_created_in_the_same_minute_get_different_invoice_numbers() -> None:
    """The collision D-114 closed, pinned where it can be seen.

    Created back to back on purpose: that is precisely the case the old suffix could not
    distinguish, and it is not a rare one — it is what onboarding two clients in one
    sitting looks like.
    """
    first_tenant, _ = await _tenant_with_usage(minutes=1)
    second_tenant, _ = await _tenant_with_usage(minutes=1)
    async with tenant_session(first_tenant) as session:
        one = await build_invoice(session, tenant_id=first_tenant)
    async with tenant_session(second_tenant) as session:
        two = await build_invoice(session, tenant_id=second_tenant)
    assert one["invoice_number"] != two["invoice_number"], (
        "two clients share an invoice number — the tenant suffix is derived from a "
        "coarse slice of a time-ordered id again"
    )


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


# --- the two-rung overage reconciles to the figure the client was already shown ----


def test_the_rung_lines_sum_to_the_total_the_panel_already_showed() -> None:
    """The panel prices the whole overage in ONE quantization; the invoice shows each
    TTS rung on its own line, which is two. Those disagree by a paisa often enough to
    matter, and the panel's figure is the one the client has already seen and the one
    `margin_for_tenant` is computed from — so the invoice has to move, and the drift has
    to land on the LAST line where a hand-checker expects the remainder.

    An unreconciled invoice is not a rounding curiosity: it is a document whose lines do
    not add up to its own total, which is the first thing an accountant checks and the
    fastest way to lose an argument about a bill that is otherwise correct.
    """
    rungs = [
        {"description": "premium", "amount_inr": Decimal("100.01")},
        {"description": "value", "amount_inr": Decimal("50.01")},
    ]
    _reconcile_overage(rungs, Decimal("150.00"))

    assert sum((r["amount_inr"] for r in rungs), start=Decimal("0")) == Decimal("150.00")
    assert rungs[0]["amount_inr"] == Decimal("100.01"), "the first line is left alone"
    # The remainder lands whole on the last line, quantized to paise and exact —
    # 50.01 - 0.02. Compared as digits, because a float 49.99 is not this number.
    assert str(rungs[1]["amount_inr"]) == "49.99"

    # The other direction: the panel's total ABOVE the sum of the rungs.
    short = [{"amount_inr": Decimal("10.00")}, {"amount_inr": Decimal("5.00")}]
    _reconcile_overage(short, Decimal("15.03"))
    assert str(short[1]["amount_inr"]) == "5.03"

    # And a total the rungs already sum to is left untouched, so the reconciliation
    # cannot invent a difference of its own.
    exact = [{"amount_inr": Decimal("7.50")}, {"amount_inr": Decimal("2.50")}]
    _reconcile_overage(exact, Decimal("10.00"))
    assert [str(r["amount_inr"]) for r in exact] == ["7.50", "2.50"]


def test_an_invoice_with_no_overage_rungs_has_nothing_to_reconcile() -> None:
    """A month entirely inside the included minutes builds NO rung lines, and the
    reconciliation must return without touching anything.

    The failure it guards is an indexing one, not an arithmetic one: `rungs[-1]` on an
    empty list is an `IndexError`, which would turn "this client used less than their
    plan allows" — the most ordinary month there is — into a 500 on the invoice route.
    """
    empty: list[dict[str, Any]] = []
    _reconcile_overage(empty, Decimal("0.00"))
    assert empty == []

    # Not even a non-zero total (which cannot happen while the caller only reconciles a
    # list it built from priced rungs) may make it reach for a line that is not there.
    _reconcile_overage(empty, Decimal("12.34"))
    assert empty == []


async def test_an_invoice_for_a_tenant_that_does_not_exist_is_a_404_not_a_blank_document() -> None:
    """The statement's face — the client's name and billing email — comes from
    `organizations`. With no row there is no supply to invoice and no recipient to
    address it to.

    The answer must be the RFC-9457 404 rather than a document with empty identity
    fields: an invoice is the artefact a client pays against, and one that renders with
    a blank recipient over real usage totals is a document that can be sent by mistake.
    A deleted tenant is exactly when this happens, which is also exactly when nobody is
    watching the batch that generated it.
    """
    missing = uuid.uuid4()
    async with tenant_session(missing) as session:
        with pytest.raises(ProblemError) as refused:
            await build_invoice(session, tenant_id=missing)

    assert refused.value.status == 404
    assert refused.value.code == "not_found"

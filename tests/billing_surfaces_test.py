"""Usage and margin panels (D-12, hard rule 7).

Three properties, and all three are about money being right rather than approximately
right:

- **NUMERIC end to end.** Costs are Decimal from the ledger to the response string; a
  float anywhere in the chain is how ₹0.1 + ₹0.2 becomes a client dispute.
- **Billing months are IST.** A month that rolls at 05:30 IST puts an evening call in
  the wrong month, and the client's invoice then disagrees with their own diary.
- **Our supplier cost never reaches the client panel.** `unit_cost_paid` is what D-12
  put on every usage row so margin is a query — and it is commercially ours.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _tenant_with_usage(
    *,
    minutes: int = 120,
    unit_cost: str = "0.5000",
    monthly_fee: str | None = "9999.00",
    included_min: int = 100,
    overage_rate: str = "8.0000",
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Billing Clinic",
        slug=f"bill-{uuid.uuid4().hex[:8]}",
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


async def test_the_usage_panel_bills_overage_in_exact_rupees() -> None:
    """120 minutes, 100 included, ₹8/min → ₹160.00 exactly, not ₹159.99999."""
    tenant_id, _ = await _tenant_with_usage(minutes=120, included_min=100, overage_rate="8.0000")
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["minutes_used"] == Decimal("120.00")
    assert summary["included_minutes"] == 100
    assert summary["overage_minutes"] == Decimal("20.00")
    assert summary["overage_cost_inr"] == Decimal("160.00")
    assert isinstance(summary["overage_cost_inr"], Decimal), "money is never a float"
    assert summary["calls"] == 1


async def test_usage_under_the_included_minutes_is_not_negative_overage() -> None:
    tenant_id, _ = await _tenant_with_usage(minutes=40, included_min=100)
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
    assert summary["overage_minutes"] == Decimal("0.00")
    assert summary["overage_cost_inr"] == Decimal("0.00"), "unused minutes are not a credit"


async def test_a_tenant_with_no_plan_still_gets_a_panel() -> None:
    """A client mid-onboarding has usage before they have a plan row; the screen must
    render numbers rather than 500."""
    tenant_id, _ = await _tenant_with_usage(minutes=30, monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
    assert summary["minutes_used"] == Decimal("30.00")
    assert summary["monthly_fee_inr"] is None
    assert summary["overage_cost_inr"] == Decimal("0.00")


async def test_margin_is_revenue_minus_what_we_actually_paid() -> None:
    """D-12's whole reason for `unit_cost_paid`: margin per client is a query."""
    # 120 min = 7200 telephony seconds at ₹0.50/unit → ₹3600 cost.
    # Revenue = ₹9999 monthly + 20 overage min at ₹8 = ₹10159.
    tenant_id, _ = await _tenant_with_usage(
        minutes=120, unit_cost="0.5000", monthly_fee="9999.00", included_min=100
    )
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert margin["cost_inr"] == Decimal("3600.00")
    assert margin["revenue_inr"] == Decimal("10159.00")
    assert margin["margin_inr"] == Decimal("6559.00")
    assert margin["margin_pct"] == Decimal("64.6")


async def test_margin_percent_is_none_rather_than_zero_before_anything_is_billed() -> None:
    """'0% margin' and 'nothing billed yet' are different facts, and an operator acts
    differently on each."""
    tenant_id, _ = await _tenant_with_usage(minutes=10, monthly_fee=None, included_min=0)
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
    assert margin["revenue_inr"] == Decimal("0.00")
    assert margin["margin_pct"] is None


async def test_the_billing_month_is_ist_not_utc() -> None:
    """A call at 23:00 IST on the 31st is 17:30 UTC the same day — but one at 00:30 IST
    on the 1st is 19:00 UTC on the 31st, and it belongs to the NEW month. Getting this
    wrong makes an invoice disagree with the client's own diary."""
    tenant_id, call_id = await _tenant_with_usage(minutes=10)
    async with tenant_session(tenant_id) as session:
        # 2026-07-31 19:00 UTC == 2026-08-01 00:30 IST → August.
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                "600, 0.5, TIMESTAMPTZ '2026-07-31 19:00:00+00', now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        july = await billing.usage_summary(session, tenant_id=tenant_id, month="2026-07")
        august = await billing.usage_summary(session, tenant_id=tenant_id, month="2026-08")

    assert july["minutes_used"] == Decimal("0.00"), "19:00 UTC on the 31st is already August IST"
    assert august["minutes_used"] >= Decimal("10.00")


async def test_money_is_reported_in_paise_not_storage_precision() -> None:
    """NUMERIC(12,4) is how it is stored; two decimals is what a rupee amount means to
    the person reading the invoice. ₹9999.0000 on a screen looks like a bug."""
    tenant_id, _ = await _tenant_with_usage(minutes=10, monthly_fee="9999.00")
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
    assert str(summary["monthly_fee_inr"]) == "9999.00"
    assert str(summary["spend_used_inr"]) == "0.00"


async def test_one_tenants_usage_never_appears_in_anothers_panel() -> None:
    a_tenant, _ = await _tenant_with_usage(minutes=120)
    b_tenant, _ = await _tenant_with_usage(minutes=5)
    async with tenant_session(a_tenant) as session:
        a_summary = await billing.usage_summary(session, tenant_id=a_tenant)
    async with tenant_session(b_tenant) as session:
        b_summary = await billing.usage_summary(session, tenant_id=b_tenant)
    assert a_summary["minutes_used"] == Decimal("120.00")
    assert b_summary["minutes_used"] == Decimal("5.00")

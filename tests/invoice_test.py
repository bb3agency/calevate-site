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
from apps.api.billing.invoice import build_invoice
from apps.api.billing.service import overage_rungs, tier_usage, to_paise, usage_summary
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


async def _tenant_with_two_rungs(
    *,
    premium_seconds: str,
    value_seconds: str,
    overage_rate: str,
    overage_rate_value: str,
    included_min: int = 0,
) -> uuid.UUID:
    """A tenant with one premium call and one value call, metered in SECONDS.

    Seconds rather than minutes because the defect this fixture exists for lives in the
    conversion: `telephony_s` is what the pipeline writes and `qty / 60` is where a
    minute count acquires a fraction of a paisa.
    """
    created = await admin_service.create_organization(
        name="Two Rung Clinic",
        slug=f"rung-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, included_min, overage_rate, "
                "overage_rate_value, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, :inc, :rate, :value_rate, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "inc": included_min,
                "rate": Decimal(overage_rate),
                "value_rate": Decimal(overage_rate_value),
            },
        )
        for tier, seconds in (("premium", premium_seconds), ("value", value_seconds)):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500001', 'completed', now(), now())"
                ),
                {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
            )
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    "'telephony_s', :qty, :cost, now(), CAST(:meta AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "qty": Decimal(seconds),
                    "cost": Decimal("0.0133"),
                    "meta": f'{{"tts_tier": "{tier}"}}',
                },
            )
    return tenant_id


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

    # New sixteen-character format (Rule 46(b)): CAL + YYMM + base-36 tenant suffix.
    return f"CAL{month_part[2:4]}{month_part[4:6]}{_tenant_serial_suffix(tenant_id)}"


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
    assert first["invoice_number"].startswith(f"CAL{month_part[2:4]}{month_part[4:6]}")
    assert len(first["invoice_number"]) == 16, "Rule 46(b): at most sixteen characters"
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


# --- the two-rung overage needs no reconciliation, and that is the assertion ------


def test_the_panel_total_is_literally_the_sum_of_the_lines_the_invoice_prints() -> None:
    """`overage_rungs` is called by the panel and by the invoice, so the two cannot
    disagree — the total is the same addition, not a second computation reconciled
    afterwards.

    THIS REPLACES `invoice._reconcile_overage`, which bent the LAST LINE to close a gap
    the panel and the invoice opened between them. The reconciliation worked and was the
    wrong shape: it made the lines add up while leaving one of them not multiplying out,
    which is the arithmetic a client actually checks by hand. Deleting the gap beats
    closing it, and this is the property that says the gap is gone.
    """
    priced = overage_rungs(
        premium_min=Decimal("5.01"),
        value_min=Decimal("4.99"),
        rate=Decimal("7.1250"),
        rate_value=Decimal("3.7500"),
    )
    assert [rung.amount_inr for rung in priced] == [Decimal("35.70"), Decimal("18.71")]
    # Each rung multiplies out at the rate printed beside it, to the paisa.
    for rung in priced:
        assert to_paise(rung.minutes * rung.rate_inr) == rung.amount_inr

    # THE CASE THAT SEPARATES THE TWO IMPLEMENTATIONS. Each rung is priced and rounded
    # ON ITS OWN and the total is their SUM — it is not one quantization of the whole
    # with the second rung derived by subtraction. Half a paisa on each rung is where
    # those two answers part company: 0.01 min at ₹0.50 is ₹0.005 twice, which is ₹0.02
    # as two lines and ₹0.01 as one sum. The per-line answer is the one that survives a
    # client multiplying each line out.
    halves = overage_rungs(
        premium_min=Decimal("0.01"),
        value_min=Decimal("0.01"),
        rate=Decimal("0.5000"),
        rate_value=Decimal("0.5000"),
    )
    assert [rung.amount_inr for rung in halves] == [Decimal("0.01"), Decimal("0.01")]
    assert sum((rung.amount_inr for rung in halves), Decimal("0")) == Decimal("0.02")
    assert to_paise(Decimal("0.01") * Decimal("0.5") * 2) == Decimal("0.01"), (
        "the fixture no longer distinguishes per-rung rounding from one rounding of the "
        "whole, so this assertion has stopped choosing between them"
    )

    # And a plan with no value rate is ONE rung carrying every overage minute, priced at
    # the single rate — the shape every invoice had before `overage_rate_value` existed.
    (single,) = overage_rungs(
        premium_min=Decimal("5.01"),
        value_min=Decimal("4.99"),
        rate=Decimal("7.1250"),
        rate_value=None,
    )
    assert single.minutes == Decimal("10.00")
    assert single.amount_inr == Decimal("71.25")


async def test_a_two_rung_invoice_multiplies_out_line_by_line_on_awkward_minutes() -> None:
    """The end-to-end version, on the seconds that produced the defect.

    300.3s premium + 299.7s value is 5.005 + 4.995 minutes — a total of exactly 10.00 —
    and each rung sits on a half-paisa boundary. Rounding the rungs independently gave
    5.01 + 5.00 = 10.01 against a panel reading 10.00, and the invoice then printed
    "5.00 min at ₹3.75/min ... ₹18.69": six paise adrift of the multiplication a client
    does with a calculator.

    Rates are deliberately not round numbers. A fixture priced at ₹8.00/min cannot
    expose this class of defect at all, which is why the suite had an assertion for
    "every line multiplies out" that passed throughout.
    """
    tenant_id = await _tenant_with_two_rungs(
        premium_seconds="300.3000",
        value_seconds="299.7000",
        overage_rate="7.1250",
        overage_rate_value="3.7500",
    )
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert summary["minutes_used"] == Decimal("10.00")
    assert (
        summary["overage_minutes_premium"] + summary["overage_minutes_value"]
        == summary["overage_minutes"]
        == Decimal("10.00")
    ), "the two published rungs must add to the total the client is charged on"

    overage_lines = [
        item for item in invoice["line_items"] if item["description"].startswith("Extra")
    ]
    assert len(overage_lines) == 2
    for line in overage_lines:
        assert to_paise(line["qty"] * line["unit_inr"]) == line["amount_inr"], (
            f"this line does not multiply out: {line}"
        )
    assert (
        sum((line["amount_inr"] for line in overage_lines), Decimal("0"))
        == (summary["overage_cost_inr"])
    )
    assert invoice["subtotal_inr"] == sum(
        (item["amount_inr"] for item in invoice["line_items"]), Decimal("0")
    )


async def test_the_tier_panel_and_the_usage_panel_agree_about_one_month() -> None:
    """Two surfaces, one ledger, one set of minute figures.

    `tier_usage` reports three buckets and `usage_summary` reports the total. They are
    the same allocated numbers now (`_tier_totals`), so the buckets add to the total
    exactly rather than to a paisa beside it.
    """
    tenant_id = await _tenant_with_two_rungs(
        premium_seconds="300.3000",
        value_seconds="299.7000",
        overage_rate="7.1250",
        overage_rate_value="3.7500",
    )
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        tiers = await tier_usage(session, tenant_id=tenant_id)

    buckets = tiers["minutes_premium"] + tiers["minutes_value"] + tiers["minutes_unattributed"]
    assert buckets == summary["minutes_used"]
    assert (
        tiers["minutes_billable_premium"] + tiers["minutes_billable_value"]
        == summary["minutes_used"]
    )


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


@pytest.fixture(autouse=True)
def _gst_registered_supplier(monkeypatch: pytest.MonkeyPatch):
    """Register a specimen GST supplier for this suite.

    These tests assert the TAX-INVOICE arithmetic (18% GST split into heads), which is only
    lawful once Calevate is GST-registered. An UNregistered supplier now issues a bill of
    supply with no tax (CGST s.32, Rule 49; billing/invoice.py), so without a registered
    supplier ``gst_inr`` would be zero and these arithmetic assertions would test nothing.
    The specimen GSTIN is Telangana (36) so an intra-State supply splits into CGST+SGST.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("GST_SUPPLIER_LEGAL_NAME", "Calevate")
    monkeypatch.setenv("GST_SUPPLIER_ADDRESS", "Plot 42, Madhapur, Hyderabad 500081")
    monkeypatch.setenv("GST_SUPPLIER_GSTIN", "36AABCC1234D1Z5")
    monkeypatch.setenv("GST_SUPPLY_SAC", "998315")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

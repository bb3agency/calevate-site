"""The onboarding setup fee, billed through the invoice (hard rules 1, 4, 7; D-63).

`plans.setup_fee` was a column nothing read. These tests are the argument that it is now
billed EXACTLY ONCE — under regeneration, under a plan change, under two concurrent
generations — and that a plan quoting no fee produces no line at all rather than a ₹0.00
one. The money assertions are the arithmetic a client checks by hand.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing.charges import SETUP_FEE_KIND, SETUP_FEE_REF, one_time_charge_lines
from apps.api.billing.invoice import build_invoice
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.service import current_billing_month
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

SETUP_LINE = "One-time onboarding & setup"


async def _tenant(
    *,
    setup_fee: str | None = "25000.00",
    monthly_fee: str | None = "9999.00",
) -> uuid.UUID:
    """A tenant onboarded NOW (so the current billing month is their onboarding month)
    with one plan row, effective-dated open on both ends like every real one."""
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Setup Fee Clinic",
        slug=f"setup-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, setup_fee, monthly_fee, included_min, "
                "overage_rate, concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, "
                ":setup, :fee, 100, 8.0000, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "setup": Decimal(setup_fee) if setup_fee is not None else None,
                "fee": Decimal(monthly_fee) if monthly_fee is not None else None,
            },
        )
    return tenant_id


async def _charge_rows(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT kind, amount, billing_month FROM one_time_charges "
                    "WHERE tenant_id = :t ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(k), Decimal(str(a)), str(m)) for k, a, m in rows]


def _setup_lines(invoice: dict[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = invoice["line_items"]  # type: ignore[assignment]
    return [item for item in items if item["description"] == SETUP_LINE]


async def test_the_setup_fee_lands_on_the_onboarding_month_invoice() -> None:
    """₹25,000 setup + ₹9,999 plan = ₹34,999 subtotal, GST ₹6,299.82, total ₹41,298.82 —
    and the ledger holds exactly one row, in the tenant's onboarding month."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    (line,) = _setup_lines(invoice)
    assert line["qty"] == Decimal("1")
    assert line["unit_inr"] == Decimal("25000.00")
    # STRING equality, not Decimal: `Decimal("25000.0000") == Decimal("25000.00")` is
    # True, so a line that skipped `to_paise` and printed the storage precision would
    # pass a numeric assertion and reach the client as "₹25000.0000".
    assert str(line["amount_inr"]) == "25000.00"
    assert str(line["unit_inr"]) == "25000.00"
    assert invoice["subtotal_inr"] == Decimal("34999.00")
    assert invoice["gst_inr"] == Decimal("6299.82")
    assert invoice["total_inr"] == Decimal("41298.82")

    assert await _charge_rows(tenant_id) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]


async def test_regenerating_the_invoice_does_not_charge_the_setup_fee_twice() -> None:
    """Invoices are DERIVED — rendering one is not billing again. Three renders across
    three transactions still leave one ledger row and one line."""
    tenant_id = await _tenant()
    totals = []
    for _ in range(3):
        async with tenant_session(tenant_id) as session:
            invoice = await build_invoice(session, tenant_id=tenant_id)
        assert len(_setup_lines(invoice)) == 1
        totals.append(invoice["total_inr"])

    assert totals[0] == totals[1] == totals[2] == Decimal("41298.82")
    assert len(await _charge_rows(tenant_id)) == 1


async def test_two_concurrent_generations_produce_one_setup_charge() -> None:
    """The race is FORCED, not hoped for: B's transaction is opened and driven into the
    write while A's is still uncommitted, which is the only interleaving that tells the
    designs apart.

    `asyncio.gather` of two renders does not: they usually serialize, and a
    read-then-write implementation passes it. Here B is started with A's charge inserted
    and unconflicted-with, so B is inside the window where a `SELECT … WHERE NOT EXISTS`
    reads "not charged yet". With the guard in the WRITE, B's speculative insert waits on
    A's index entry, writes nothing when A commits, and its read-back — a new statement,
    hence a new READ COMMITTED snapshot — returns A's row. One charge, and both
    statements print the line."""
    tenant_id = await _tenant()
    second: dict[str, object] = {}

    async def render_second() -> None:
        async with tenant_session(tenant_id) as session:
            second.update(await build_invoice(session, tenant_id=tenant_id))

    async with tenant_session(tenant_id) as session:
        first = await build_invoice(session, tenant_id=tenant_id)
        task = asyncio.create_task(render_second())
        # Long enough for B to issue its own insert and block on the index entry A holds
        # uncommitted. If it were NOT blocked there, this test would be proving nothing.
        await asyncio.sleep(0.3)
        assert not task.done(), "B finished without ever contending — the race did not happen"
    await asyncio.wait_for(task, timeout=5)

    assert len(_setup_lines(first)) == 1
    assert len(_setup_lines(second)) == 1
    assert first["total_inr"] == second["total_inr"] == Decimal("41298.82")
    assert len(await _charge_rows(tenant_id)) == 1


async def test_a_plan_change_never_creates_a_second_setup_charge() -> None:
    """A new plan row quoting its own (larger) setup fee supersedes the old one for
    pricing, and bills no second onboarding: the ledger key is the TENANT's onboarding,
    not the plan's. The rendered line keeps the amount actually billed."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        before = await build_invoice(session, tenant_id=tenant_id)
    assert len(_setup_lines(before)) == 1

    async with tenant_session(tenant_id) as session:
        # Effective from an hour ago, so it is the row in effect for "now" — the same
        # gesture an operator makes to re-terms a client (billing/plans.py).
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, setup_fee, monthly_fee, included_min, "
                "overage_rate, concurrency_ceiling, effective_from, created_at, updated_at) "
                "VALUES (:i, :t, 99000.0000, 9999.0000, 100, 8.0000, 10, "
                "now() - interval '1 hour', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
        after = await build_invoice(session, tenant_id=tenant_id)

    (line,) = _setup_lines(after)
    # STRING equality, not Decimal: `Decimal("25000.0000") == Decimal("25000.00")` is
    # True, so a line that skipped `to_paise` and printed the storage precision would
    # pass a numeric assertion and reach the client as "₹25000.0000".
    assert str(line["amount_inr"]) == "25000.00"
    assert str(line["unit_inr"]) == "25000.00", "the amount billed is frozen in the ledger"
    assert await _charge_rows(tenant_id) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]


async def test_a_month_that_is_not_the_onboarding_month_carries_no_setup_line() -> None:
    """The fee belongs to the month the client was onboarded in. Rendering an earlier
    month must neither print it nor bill it — otherwise which month it lands on would
    depend on which statement somebody happened to open first."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month="2026-01")

    assert _setup_lines(invoice) == []
    assert await _charge_rows(tenant_id) == []


async def test_a_billed_setup_fee_does_not_follow_the_client_into_later_months() -> None:
    """The charge is stamped with the statement it belongs to, and the invoice reads
    charges FOR THAT MONTH. A tenant already billed the fee must not see it again on
    every subsequent invoice — which is the failure a ledger read without a month filter
    produces, and the one an unbilled tenant's empty ledger would hide."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        onboarding = await build_invoice(session, tenant_id=tenant_id)
    assert len(_setup_lines(onboarding)) == 1

    # A month the tenant was NOT onboarded in, chosen after the fact so the row exists.
    later = "2027-03" if current_billing_month() < "2027-03" else "2029-03"
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=later)

    assert _setup_lines(invoice) == []
    assert len(await _charge_rows(tenant_id)) == 1


@pytest.mark.parametrize("setup_fee", [None, "0.0000", "-500.0000"])
async def test_no_setup_fee_produces_no_line_and_no_ledger_row(setup_fee: str | None) -> None:
    """NULL, zero and negative all mean "there is nothing to charge". A ₹0.00 line on an
    invoice invites a dispute about nothing, and a negative fee is a discount nobody
    designed — neither may reach a client's statement."""
    tenant_id = await _tenant(setup_fee=setup_fee)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert _setup_lines(invoice) == []
    assert invoice["subtotal_inr"] == Decimal("9999.00"), "only the monthly fee"
    assert await _charge_rows(tenant_id) == []


async def test_a_tenant_with_no_plan_at_all_is_never_charged_a_setup_fee() -> None:
    """No plan row means unpriced (billing/plans.py) — including no onboarding fee."""
    tenant_id = await _tenant(setup_fee=None, monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        # Remove the plan row this fixture writes, so the tenant genuinely has none.
        await session.execute(text("DELETE FROM plans WHERE tenant_id = :t"), {"t": tenant_id})
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["line_items"] == []
    assert await _charge_rows(tenant_id) == []


async def test_a_reversal_row_prints_as_a_credit_on_the_same_statement() -> None:
    """Hard rule 4's escape hatch: a setup fee that has to be undone is a NEW row under
    its own `ref`, never an edit. The invoice reads every charge for the month, so the
    correction reaches the client's statement and nets the subtotal back to the plan
    fee."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await build_invoice(session, tenant_id=tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO one_time_charges (id, tenant_id, kind, ref, description, amount, "
                "billing_month, occurred_at, created_at) VALUES (:i, :t, :kind, "
                "'reversal:onboarding', 'Onboarding fee waived', -25000.0000, :m, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "kind": SETUP_FEE_KIND, "m": current_billing_month()},
        )
        invoice = await build_invoice(session, tenant_id=tenant_id)

    descriptions = [item["description"] for item in invoice["line_items"]]
    assert descriptions == ["Monthly plan fee", SETUP_LINE, "Onboarding fee waived"]
    assert invoice["subtotal_inr"] == Decimal("9999.00")


async def test_the_charge_ledger_refuses_updates_and_deletes() -> None:
    """Append-only (hard rule 4), enforced by the trigger and not by convention."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await build_invoice(session, tenant_id=tenant_id)

    for statement in (
        "UPDATE one_time_charges SET amount = 1 WHERE tenant_id = :t",
        "DELETE FROM one_time_charges WHERE tenant_id = :t",
    ):
        with pytest.raises(Exception, match=r"append-only|immutable|forbidden"):
            async with tenant_session(tenant_id) as session:
                await session.execute(text(statement), {"t": tenant_id})


async def test_one_tenants_charges_are_invisible_to_another() -> None:
    """Hard rule 1: RLS, not a WHERE clause. A session scoped to B sees zero rows of A's
    charges even when it names A's id, and cannot write one for A either."""
    a = await _tenant()
    b = await _tenant()
    async with tenant_session(a) as session:
        await build_invoice(session, tenant_id=a)

    async with tenant_session(b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM one_time_charges WHERE tenant_id = :t"), {"t": a}
            )
        ).scalar()
        assert rows == 0
        # And the invoice builder, handed A's id on B's session, bills nothing for A:
        # every read it makes is fenced by the same policy.
        lines = await one_time_charge_lines(
            session,
            tenant_id=a,
            month=current_billing_month(),
            onboarded_at=datetime.now(UTC),
            priced_at=datetime.now(UTC),
        )
        assert lines == []

    # A's own ledger is untouched by B's attempt: still exactly the one charge.
    assert await _charge_rows(a) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]
    assert SETUP_FEE_REF == "onboarding"


def test_a_billing_month_needs_an_aware_instant() -> None:
    """A naive datetime would be read in the process's local timezone, so the same row
    would bill in two different months on a UTC container and an IST laptop."""
    with pytest.raises(ValueError, match="aware instant"):
        ist_billing_month(datetime(2026, 8, 14, 23, 30))

    # 23:30 UTC on 31 July is 05:00 IST on 1 August — the shift is the point.
    assert ist_billing_month(datetime(2026, 7, 31, 23, 30, tzinfo=UTC)) == "2026-08"

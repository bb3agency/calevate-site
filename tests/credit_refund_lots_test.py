"""A refund takes the credit off the LOTS, not only off the balance (D-561).

`credit_refund` appended a compensating `credit_ledger` row and stopped there. The lot the
refunded purchase had opened stood untouched, which made three things false at once and
none of them visible on the wallet screen:

1. **the client's next minute was priced at a purchase they no longer own.**
   `lots.read_open_lots` selects on `closed_at IS NULL` alone and orders by `opened_at`, so
   the phantom lot stayed at the HEAD of the FIFO queue: a later top-up at a dearer pack's
   rates was drawn down at the refunded lot's cheaper one, which is billing at a rate
   nobody agreed to;
2. **the runway quoted minutes nobody paid for.** `wallet.read_runway` sums
   `lots.runway()`, and `workers/wallet_alerts.py` emails that figure;
3. **plan invariant §2.3.1 — the balance IS `SUM(credits_remaining)` — was false** from the
   moment the refund landed, in the direction that says the wallet holds more than it does.

The fix is the door this repository already has: `service.remove_credit_from_lots`, called
under the lock already held and in the transaction of the ledger row, exactly as the
operator adjustment calls it (`credit_routes.py`). Every test below asserts the LEDGER and
the LOTS together, because the two disagreeing is the failure, and either alone looks fine.

Run: uv run pytest -q tests/credit_refund_lots_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.lots import CallDemand, open_lot, read_open_lots, runway
from apps.api.billing.service import LotRates, charge_for_call, get_balance, record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.credit_lots_helpers import lot_rows


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Refund Lots Clinic",
        slug=f"rfl-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    return tenant_id


async def _fund(tenant_id: UUID, *, amount_inr: str, pack_id: str | None = None) -> str:
    """One captured payment through the real writer, so the lot is opened the way
    production opens it — rates and all."""
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount_inr),
                currency="INR",
                pack_id=pack_id,
            ),
        )
    return payment_id


async def _refund(
    tenant_id: UUID, *, payment_id: str, amount_inr: str, refund_id: str | None = None
) -> str:
    refund_id = refund_id or f"rfnd_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await payments.credit_refund(
            session,
            refund=payments.RefundEvent(
                refund_id=refund_id,
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount_inr),
                currency="INR",
            ),
        )
    return refund_id


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def _open_remaining(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        lots = await read_open_lots(session, tenant_id=tenant_id)
    return sum((lot.credits_remaining for lot in lots), Decimal("0"))


async def _refund_meta(tenant_id: UUID, refund_id: str) -> dict:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT meta FROM credit_ledger WHERE tenant_id = :t AND reason = 'refund' "
                    "AND ref = :r"
                ),
                {"t": tenant_id, "r": refund_id},
            )
        ).scalar_one()
    return dict(row)


# ============================================================================
# The whole purchase back
# ============================================================================


async def test_a_full_refund_empties_the_lot_it_reverses() -> None:
    """The plainest shape, and the one that was broken: money back, credit gone.

    A full refund cannot be a restatement — `credits_total > 0` is a CHECK and a lot of
    nothing is not a correction — so the credit is spent off the queue at face value, which
    drains and closes the lot. What matters is the pair: balance ₹0 AND no open lot.
    """
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="2500.00")
    assert await _open_remaining(tenant_id) == Decimal("2500.0000")

    refund_id = await _refund(tenant_id, payment_id=payment_id, amount_inr="2500.00")

    assert await _balance(tenant_id) == Decimal("0.0000")
    assert await _open_remaining(tenant_id) == Decimal("0.0000"), (
        "the refunded purchase must not keep funding minutes"
    )
    rows = await lot_rows(tenant_id)
    assert len(rows) == 1, "the lot is emptied, never deleted — the row is the record"
    assert rows[0]["credits_remaining"] == Decimal("0.0000")
    assert rows[0]["closed_at"] is not None
    # The row says WHERE the credit came from, exactly as an adjustment's does, so an
    # auditor pairing the ledger against the lots needs no third source.
    assert [split["credits"] for split in (await _refund_meta(tenant_id, refund_id))["lots"]] == [
        "2500.0000"
    ]


async def test_the_runway_stops_quoting_minutes_the_client_was_refunded_for() -> None:
    """`wallet.read_runway` sums `lots.runway()` and the low-balance email quotes it, so a
    phantom lot is a promise of talk time made to a client who has their money back."""
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")
    async with tenant_session(tenant_id) as session:
        assert (await runway(session, tenant_id=tenant_id))["sarvam_minutes"] > 0

    await _refund(tenant_id, payment_id=payment_id, amount_inr="5000.00")

    async with tenant_session(tenant_id) as session:
        left = await runway(session, tenant_id=tenant_id)
    assert left["sarvam_minutes"] == left["cartesia_minutes"] == Decimal("0")


async def test_a_refunded_purchase_does_not_price_the_clients_next_top_up() -> None:
    """THE MONEY DEFECT, asserted where it lands: the rate of the next call.

    A ₹50,000 pack buys the cheapest minute on the card (₹4.50). Refunded in full and
    replaced by a ₹2,000 pack (₹5.00), the client's next minute costs ₹5.00 — the pack they
    are actually holding. With the phantom lot left open it costs ₹4.50, because FIFO is
    `opened_at` and the refunded lot is older: a rate nobody agreed to, on credit bought at
    another price.
    """
    tenant_id = await _tenant()
    refunded_payment = await _fund(tenant_id, amount_inr="50000.00", pack_id="max")
    await _refund(tenant_id, payment_id=refunded_payment, amount_inr="50000.00")
    await _fund(tenant_id, amount_inr="2000.00", pack_id="starter")

    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("9.99"), Decimal("9.99")),
            ),
        )
    assert charged == Decimal("50.0000"), "10 minutes of the ₹2,000 pack, at ₹5.00"
    assert await _open_remaining(tenant_id) == await _balance(tenant_id) == Decimal("1950.0000")


# ============================================================================
# Partly back, and the wallet that had already spent it
# ============================================================================


async def test_a_partial_refund_restates_the_lot_and_leaves_its_rates_alone() -> None:
    """Part of the purchase back is a RESTATEMENT of that purchase, at its own frozen
    rates — the client keeps the terms they bought on what they still hold, which is the
    Terms sentence itself. It is not a re-price and it must never become one."""
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")

    await _refund(tenant_id, payment_id=payment_id, amount_inr="2000.00")

    rows = await lot_rows(tenant_id)
    assert len(rows) == 1
    assert rows[0]["credits_total"] == Decimal("3000.0000")
    assert rows[0]["credits_remaining"] == Decimal("3000.0000")
    assert rows[0]["closed_at"] is None
    assert (rows[0]["sarvam_inr_per_min"], rows[0]["cartesia_inr_per_min"]) == (
        Decimal("5.0000"),
        Decimal("7.0000"),
    ), "a refund returns money; it does not re-price what is left"
    assert await _open_remaining(tenant_id) == await _balance(tenant_id) == Decimal("3000.0000")


async def test_two_partial_refunds_land_on_the_same_place_as_one_whole_one() -> None:
    """The sequence, because each refund is its own compensating entry and each restates
    what the previous one left. The second takes the remainder, which no restatement can
    express, so the lot is spent off the queue and closed."""
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")

    await _refund(tenant_id, payment_id=payment_id, amount_inr="2000.00")
    await _refund(tenant_id, payment_id=payment_id, amount_inr="3000.00")

    assert await _balance(tenant_id) == Decimal("0.0000")
    assert await _open_remaining(tenant_id) == Decimal("0.0000")
    assert (await lot_rows(tenant_id))[0]["closed_at"] is not None


async def test_a_refund_of_credit_already_spent_overdraws_rather_than_leaving_a_lot() -> None:
    """The overdrawn wallet needs no path of its own, and this is why.

    The client spent ₹4,000 of a ₹5,000 pack before the refund processed. The lot floors at
    zero, the shortfall finds no other lot, and what reaches no lot becomes the wallet
    overdraft the negative balance already carries (plan §0 Q5) — so invariant §2.3.1's
    negative half holds: every lot at 0 and `overdraft = -balance`.
    """
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")
    async with tenant_session(tenant_id) as session:
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("800"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("5.00")),
            ),
        )
    assert await _balance(tenant_id) == Decimal("1000.0000")

    await _refund(tenant_id, payment_id=payment_id, amount_inr="5000.00")

    assert await _balance(tenant_id) == Decimal("-4000.0000")
    assert await _open_remaining(tenant_id) == Decimal("0.0000")


# ============================================================================
# The edges: no purchase to reverse, and the same refund twice
# ============================================================================


async def test_a_refund_of_an_unrecorded_payment_records_and_moves_no_lot() -> None:
    """There is no top-up row to name, so there is no lot to restate. The refund is still
    recorded — refusing to record a movement that happened at the provider would hide it —
    and the whole of it becomes overdraft, which is the honest answer."""
    tenant_id = await _tenant()

    await _refund(tenant_id, payment_id=f"pay_{uuid.uuid4().hex[:10]}", amount_inr="750.00")

    assert await _balance(tenant_id) == Decimal("-750.0000")
    assert await lot_rows(tenant_id) == []


async def test_the_same_refund_delivered_twice_takes_the_credit_off_the_lots_once() -> None:
    """The replay guard covers the lots as well as the ledger, because it returns BEFORE
    either — a second delivery that moved the lots would drain a purchase the client still
    holds while the balance, correctly, did not move at all."""
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")
    refund_id = f"rfnd_{uuid.uuid4().hex[:12]}"

    await _refund(tenant_id, payment_id=payment_id, amount_inr="2000.00", refund_id=refund_id)
    await _refund(tenant_id, payment_id=payment_id, amount_inr="2000.00", refund_id=refund_id)

    assert await _balance(tenant_id) == Decimal("3000.0000")
    assert await _open_remaining(tenant_id) == Decimal("3000.0000")
    assert (await lot_rows(tenant_id))[0]["credits_total"] == Decimal("3000.0000")


# ============================================================================
# The pack bonus's own lot — the same defect, on a branch no pack can reach today
# ============================================================================


async def test_a_refund_takes_the_pack_bonus_off_its_lot_too() -> None:
    """`_claw_back_pack_bonus` had the identical hole, and it is fixed on the identical
    door.

    IT CANNOT FIRE THROUGH THE CATALOGUE: every pack in `credit_packs.PACK_CATALOGUE`
    carries `bonus_pct = 0` (D-547 delivered the bigger pack as a cheaper minute rather than
    as bonus credits), so `_grant_pack_bonus` writes nothing and the clawback returns early
    on `grant is None`. The grant is therefore built here the way that function builds it —
    a `bonus` row keyed on the payment id, and the `bonus_legacy` lot it opens — because a
    branch that is only unreachable by today's configuration is not a branch that may go
    untested. Half the purchase back takes half the bonus back, off the bonus's OWN lot.
    """
    tenant_id = await _tenant()
    payment_id = await _fund(tenant_id, amount_inr="5000.00", pack_id="growth")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("250.00"),
            reason="bonus",
            ref=payment_id,
            meta={"kind": "pack_bonus", "source": "razorpay"},
        )
        bonus_entry_id = (
            await session.execute(
                text(
                    "SELECT id FROM credit_ledger WHERE tenant_id = :t AND reason = 'bonus' "
                    "AND ref = :r"
                ),
                {"t": tenant_id, "r": payment_id},
            )
        ).scalar_one()
        await open_lot(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("250.00"),
            sarvam_inr_per_min=Decimal("5.00"),
            cartesia_inr_per_min=Decimal("7.00"),
            source="bonus_legacy",
            pack_id="growth",
            ledger_entry_id=UUID(str(bonus_entry_id)),
        )
    assert await _open_remaining(tenant_id) == await _balance(tenant_id) == Decimal("5250.0000")

    await _refund(tenant_id, payment_id=payment_id, amount_inr="2500.00")

    # ₹2,500 of ₹5,000 back takes ₹125 of the ₹250 bonus with it — and both come off lots.
    assert await _balance(tenant_id) == Decimal("2625.0000")
    assert await _open_remaining(tenant_id) == Decimal("2625.0000")
    by_source = {row["source"]: row for row in await lot_rows(tenant_id)}
    assert by_source["topup"]["credits_remaining"] == Decimal("2500.0000")
    assert by_source["bonus_legacy"]["credits_remaining"] == Decimal("125.0000")

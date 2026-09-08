"""An operator correcting a mis-recorded payment, on a lot already spent (ADDENDUM 2 §2.2).

THE BUG THIS FILE EXISTS FOR, stated as a regression test rather than as a paragraph: the
plan's original sentence said a restatement adjusts `credits_total` and `credits_remaining`
"by the same delta". That preserves `credits_remaining <= credits_total` and violates
`credits_remaining >= 0` — a lot of 5,000 with 1,000 left, restated down by 2,000, needs
`credits_remaining = -1,000`, the CHECK refuses the write, and an operator correcting a
bank mismatch is stopped mid-correction. `test_the_naive_restatement_hits_the_check` runs
the naive UPDATE and requires the database to refuse it, so nobody can quietly reintroduce
it; the rest of the file pins the fix.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing import lots
from apps.api.billing.service import LotRates
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.credit_lots_helpers import GROWTH, add_lot, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]


async def _spend(tenant_id, *, minutes: str) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session(tenant_id) as session:
        await lots.consume(
            session,
            tenant_id=tenant_id,
            demand=lots.CallDemand(
                minutes=Decimal(minutes),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("5.00")),
            ),
        )


async def test_a_downward_restatement_floors_at_zero_and_returns_the_shortfall() -> None:
    """The worked example from ADDENDUM 2: recorded ₹10,000, the bank shows ₹8,000, the
    client has already spent ₹9,000. The lot goes to 8,000/0 and closes; ₹1,000 is
    overdraft the CALLER books, not something the lot absorbs."""
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="10000.00", rates=GROWTH)
    await _spend(tenant, minutes="1800")  # ₹9,000 at ₹5.00

    async with tenant_session(tenant) as session:
        result = await lots.adjust_lot_for_restatement(
            session, lot_id=lot_id, delta=Decimal("-2000.00")
        )

    assert result.credits_total == Decimal("8000.0000")
    assert result.credits_remaining == Decimal("0.0000")
    assert result.closed is True
    assert result.shortfall == Decimal("1000.0000")
    row = (await lot_rows(tenant))[0]
    assert (row["credits_total"], row["credits_remaining"]) == (
        Decimal("8000.0000"),
        Decimal("0.0000"),
    )
    assert row["closed_at"] is not None
    # The RATES are untouched in either direction — that is what stays frozen.
    assert row["sarvam_inr_per_min"] == Decimal("5.0000")


async def test_a_downward_restatement_the_lot_can_absorb_leaves_no_shortfall() -> None:
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="10000.00", rates=GROWTH)
    await _spend(tenant, minutes="200")  # ₹1,000

    async with tenant_session(tenant) as session:
        result = await lots.adjust_lot_for_restatement(
            session, lot_id=lot_id, delta=Decimal("-2000.00")
        )

    assert result.credits_total == Decimal("8000.0000")
    assert result.credits_remaining == Decimal("7000.0000")
    assert result.closed is False
    assert result.shortfall == Decimal("0.0000")
    assert (await lot_rows(tenant))[0]["closed_at"] is None


async def test_an_upward_restatement_reopens_a_lot_that_had_closed() -> None:
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="100.00", rates=GROWTH)
    await _spend(tenant, minutes="20")  # empties and closes it

    async with tenant_session(tenant) as session:
        result = await lots.adjust_lot_for_restatement(
            session, lot_id=lot_id, delta=Decimal("50.00")
        )

    assert result.credits_total == Decimal("150.0000")
    assert result.credits_remaining == Decimal("50.0000")
    assert result.closed is False
    row = (await lot_rows(tenant))[0]
    assert row["closed_at"] is None
    # And it is spendable again — a reopened lot rejoins the FIFO queue.
    async with tenant_session(tenant) as session:
        assert await lots.read_open_lots(session, tenant_id=tenant) != []


async def test_the_naive_restatement_hits_the_check_the_fix_exists_for() -> None:
    """FAILS IF: `credits_remaining >= 0` stops being enforced, or somebody "simplifies"
    the fix back to moving both columns by the same delta."""
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="10000.00", rates=GROWTH)
    await _spend(tenant, minutes="1800")

    with pytest.raises(DBAPIError) as raised:
        async with tenant_session(tenant) as session:
            await session.execute(
                text(
                    "UPDATE credit_lots SET credits_total = credits_total - 2000, "
                    "credits_remaining = credits_remaining - 2000 WHERE id = :id"
                ),
                {"id": lot_id},
            )
    assert "ck_credit_lots_remaining_within_total" in str(raised.value)


async def test_a_restatement_that_would_empty_the_purchase_is_refused_with_a_sentence() -> None:
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant) as session:
            await lots.adjust_lot_for_restatement(session, lot_id=lot_id, delta=Decimal("-1000.00"))

    assert raised.value.code == "restatement_empties_lot"
    assert raised.value.remediation


async def test_a_restatement_of_nothing_is_a_defect_not_a_no_op() -> None:
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    with pytest.raises(ValueError, match="changes nothing"):
        async with tenant_session(tenant) as session:
            await lots.adjust_lot_for_restatement(session, lot_id=lot_id, delta=Decimal("0"))


async def test_restating_a_lot_that_is_not_this_tenant_s_is_not_found() -> None:
    """Under RLS "not found" and "belongs to someone else" are the same answer, and the
    correction path must not become the exception that says which."""
    owner = await make_tenant()
    lot_id = await add_lot(owner, credits_inr="1000.00", rates=GROWTH)
    stranger = await make_tenant()

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(stranger) as session:
            await lots.adjust_lot_for_restatement(session, lot_id=lot_id, delta=Decimal("10.00"))

    assert raised.value.code == "not_found"


async def test_a_lot_that_moved_under_the_correction_is_a_conflict_not_a_silent_write() -> None:
    """The CAS on the restatement UPDATE. Forced deterministically by handing the function
    a stale reading of the lot — which is what a concurrent debit produces."""
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)
    async with tenant_session(tenant) as session:
        fresh = await lots.read_open_lots(session, tenant_id=tenant)
    stale = lots.OpenLot(
        lot_id=fresh[0].lot_id,
        tenant_id=fresh[0].tenant_id,
        source=fresh[0].source,
        pack_id=fresh[0].pack_id,
        override_of_pack_id=fresh[0].override_of_pack_id,
        credits_total=fresh[0].credits_total,
        credits_remaining=Decimal("999.0000"),  # someone spent ₹1 between read and write
        sarvam_inr_per_min=fresh[0].sarvam_inr_per_min,
        cartesia_inr_per_min=fresh[0].cartesia_inr_per_min,
        opened_at=fresh[0].opened_at,
        closed_at=fresh[0].closed_at,
    )

    async def _stale_read(session: object, *, lot_id: object) -> lots.OpenLot:
        return stale

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant) as session:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(lots, "read_lot", _stale_read)
                await lots.adjust_lot_for_restatement(
                    session, lot_id=lot_id, delta=Decimal("100.00")
                )

    assert raised.value.code == "credit_lots_contended"
    assert (await lot_rows(tenant))[0]["credits_total"] == Decimal("1000.0000")

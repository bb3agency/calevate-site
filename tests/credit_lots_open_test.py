"""Opening a lot: what it records, and the four ways it refuses (D-547, §3.1).

`open_lot` is the seam every credit-adding writer will call in Phase B2 — a Razorpay
capture, an admin top-up, a grant, a trial credit, an operator's rate override. The rates
are the CALLER'S in every one of those cases (plan §0 Q3/Q4/Q6), so this file pins that the
function stores what it is given and validates only what would produce an unspendable row.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing import lots
from apps.api.db.session import tenant_session
from sqlalchemy.exc import IntegrityError
from tests.credit_lots_helpers import GROWTH, add_lot, credit_entry, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]


async def test_a_lot_records_its_pack_its_source_and_the_pack_its_rates_were_borrowed_from() -> (
    None
):
    """The founding-client promotion (plan §0 Q6) is a rate OVERRIDE: the lot is sold at
    another pack's rates and says so on its own row, because a client asking why their
    minute costs what it costs must be answerable from the lot."""
    tenant = await make_tenant()
    await add_lot(
        tenant,
        credits_inr="2000.00",
        rates=(Decimal("4.60"), Decimal("6.25")),
        source="override",
        pack_id="starter",
        override_of_pack_id="pro",
    )

    row = (await lot_rows(tenant))[0]
    assert row["source"] == "override"
    assert row["pack_id"] == "starter"
    assert row["override_of_pack_id"] == "pro"
    assert (row["sarvam_inr_per_min"], row["cartesia_inr_per_min"]) == (
        Decimal("4.6000"),
        Decimal("6.2500"),
    )
    assert row["credits_total"] == row["credits_remaining"] == Decimal("2000.0000")


async def test_a_grant_carries_no_pack_at_all() -> None:
    """Plan §0 Q4: a gift is spent at the standard price, and `pack_id` stays NULL because
    no pack was bought. The nullable columns have to actually be nullable."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="500.00", source="grant", pack_id=None)

    row = (await lot_rows(tenant))[0]
    assert row["pack_id"] is None
    assert row["override_of_pack_id"] is None
    assert row["source"] == "grant"


async def test_the_same_ledger_entry_cannot_open_two_lots() -> None:
    """The replay guarantee, on this side of the link: money that arrived once buys credit
    once, whatever a retried webhook believes."""
    tenant = await make_tenant()
    entry = await credit_entry(tenant, amount="1000.00")

    async def _open() -> None:
        async with tenant_session(tenant) as session:
            await lots.open_lot(
                session,
                tenant_id=tenant,
                credits_inr=Decimal("1000.00"),
                sarvam_inr_per_min=GROWTH[0],
                cartesia_inr_per_min=GROWTH[1],
                source="topup",
                pack_id="growth",
                ledger_entry_id=entry,
            )

    await _open()
    with pytest.raises(IntegrityError, match="uq_credit_lots_ledger_entry_id"):
        await _open()


@pytest.mark.parametrize(
    ("credits_inr", "sarvam", "cartesia", "message"),
    [
        ("0.00", "5.00", "7.00", "credits > 0"),
        ("-10.00", "5.00", "7.00", "credits > 0"),
        ("100.00", "0.00", "7.00", "Sarvam rate"),
        ("100.00", "5.00", "4.00", "may not be below"),
    ],
)
async def test_terms_that_would_make_an_unspendable_lot_are_refused_by_name(
    credits_inr: str, sarvam: str, cartesia: str, message: str
) -> None:
    """`ValueError` and not a `ProblemError`: every argument comes from our own catalogue
    or console, never from a client's keyboard, so a bad one is a defect to fix rather than
    a sentence to render — and the message says WHICH term was wrong, because the CHECK a
    layer down would only say that a row was refused."""
    tenant = await make_tenant()
    entry = await credit_entry(tenant, amount="100.00")

    with pytest.raises(ValueError, match=message):
        async with tenant_session(tenant) as session:
            await lots.open_lot(
                session,
                tenant_id=tenant,
                credits_inr=Decimal(credits_inr),
                sarvam_inr_per_min=Decimal(sarvam),
                cartesia_inr_per_min=Decimal(cartesia),
                source="topup",
                pack_id="growth",
                ledger_entry_id=entry,
            )

    assert await lot_rows(tenant) == []


async def test_the_open_lots_read_is_the_one_the_wallet_screen_will_use() -> None:
    """`read_open_lots` is what the client's own "3,200 at ₹4.70 / ₹6.50, then 2,000 at
    ₹5.00 / ₹8.00" list is built from (plan §5.F1), and it is the same read the debit walks
    — so the order shown and the order spent cannot disagree."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH, pack_id="growth")
    await add_lot(
        tenant, credits_inr="200.00", rates=(Decimal("4.70"), Decimal("6.50")), pack_id="plus"
    )

    async with tenant_session(tenant) as session:
        open_lots = await lots.read_open_lots(session, tenant_id=tenant)

    assert [lot.pack_id for lot in open_lots] == ["growth", "plus"]
    assert [lot.credits_remaining for lot in open_lots] == [
        Decimal("100.0000"),
        Decimal("200.0000"),
    ]
    assert open_lots[0].rate_for("sarvam") == Decimal("5.0000")
    assert open_lots[1].rate_for("cartesia") == Decimal("6.5000")
    assert all(lot.tenant_id == tenant for lot in open_lots)

"""A dispute release gives a hold's credit back to the lots it was taken from (`144ee20b5`):
the shares no lot can take back, and a release that first repays an overdraft."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import disputes, lots
from apps.api.billing.service import get_balance, record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.money_w3_test import _dispute_event, _lot_of
from tests.razorpay_payments_e2e_test import (  # noqa: F401 (autouse fixture)
    _configured,
    _fund,
    _id,
    _tenant,
)

pytestmark = [pytest.mark.rls]


# --- giving a dispute hold's credit back to its lots -------------------------------------


@pytest.mark.parametrize(
    ("given", "sold"),
    [(Decimal("0"), Decimal("0")), (Decimal("-1"), Decimal("5")), (Decimal("5"), Decimal("-1"))],
    ids=["nothing", "negative-credit", "negative-sold"],
)
async def test_returning_nothing_or_a_negative_figure_to_a_lot_is_refused(
    given: Decimal, sold: Decimal
) -> None:
    with pytest.raises(ValueError, match="nothing to return"):
        await lots.return_credits(
            None,  # type: ignore[arg-type]  # refused before any read
            lot_id=uuid.uuid4(),
            credits_inr=given,
            sold=sold,
        )


async def test_credit_for_a_lot_that_is_gone_is_left_for_the_caller_to_place() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert (
            await lots.return_credits(session, lot_id=uuid.uuid4(), credits_inr=Decimal("10"))
            is False
        )


async def test_shares_no_lot_takes_back_stay_with_the_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lot that can no longer take credit back (lapsed, re-priced), and a split that names
    no lot, give nothing back here: the release opens a lot for that share instead."""
    asked: list[tuple[UUID, Decimal, Decimal]] = []

    async def _cannot(
        _session: Any, *, lot_id: UUID, credits_inr: Decimal, sold: Decimal = Decimal("0")
    ) -> bool:
        asked.append((lot_id, credits_inr, sold))
        return False

    monkeypatch.setattr(disputes, "return_credits", _cannot)
    purchase, later = uuid.uuid4(), uuid.uuid4()
    returned = await disputes._return_to_held_lots(
        None,  # type: ignore[arg-type]  # every lot write is the fake above
        lot=SimpleNamespace(lot_id=purchase),  # type: ignore[arg-type]
        lot_restated=Decimal("400"),
        taken=[
            {"lot_id": None, "credits": "50"},
            {"lot_id": str(later), "credits": "100"},
        ],
        amount=Decimal("500"),
        balance_after=Decimal("500"),
    )

    assert returned == Decimal("0")
    assert asked == [
        (purchase, Decimal("250"), Decimal("400")),
        (later, Decimal("100"), Decimal("0")),
    ]


async def test_a_won_dispute_after_an_overdraft_repays_it_and_reopens_the_rest_at_its_rates() -> (
    None
):
    """Calls made after the hold overdrew the wallet. The release repays that overdraft
    first, so less than the hold goes back to the purchase's lot; the balance, what the
    release could not return, opens its own lot at the disputed purchase's rates."""
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    assert await _dispute_event(tenant_id, payment_id, "open", 100000) == "held"
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-200"),
            reason="usage",
            ref=_id("call"),
            allow_negative=True,
        )

    assert await _dispute_event(tenant_id, payment_id, "won", 100000) == "released"

    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("800")
        open_credit = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(credits_remaining), 0) FROM credit_lots "
                    "WHERE tenant_id = :t AND credits_remaining > 0"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert Decimal(str(open_credit)) == Decimal("800.0000")
    total, _remaining = await _lot_of(tenant_id, payment_id)
    assert total == Decimal("1000.0000"), "the purchase's lot is back at what it was sold as"

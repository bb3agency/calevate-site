"""Two writers on one wallet: the compare-and-swap, and what a lost race costs (D-547).

BACKEND-PATTERNS §5's guard-in-the-write, on the hottest money path in the product. In
production every caller is inside `lock_tenant_credits`, so these interleavings do not
arise — which is exactly why they are driven here by hand: a backstop nothing exercises is
a backstop nobody knows is broken, and `billing/lots.py` deliberately has NO
`SELECT ... FOR UPDATE` in front of the CAS precisely so this arm stays reachable.

The interleaving is deterministic, not timing-based: the reads and the writes are ordered
by the test, so a failure here is a defect and never a slow machine (D-29).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing import lots
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from tests.credit_lots_helpers import GROWTH, add_lot, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]


async def test_a_debit_that_lost_the_race_re_reads_and_takes_what_is_left() -> None:
    """One writer reads a lot, another spends part of it and COMMITS, and the first then
    tries to decrement against the value it saw. The CAS matches no row, the lot is re-read
    and the portion recomputed — one call, correctly priced, no double spend."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    async with tenant_session(tenant) as first:
        stale = await lots.read_open_lots(first, tenant_id=tenant)

        # A second transaction commits between the read above and the write below.
        async with tenant_session(tenant) as second:
            await lots.consume(
                second,
                tenant_id=tenant,
                demand=lots.CallDemand(
                    minutes=Decimal("100"),  # ₹500
                    voice_tier="sarvam",
                    fallback_inr_per_min=Decimal("5.00"),
                ),
            )

        # The first writer's CAS is against `credits_remaining = 1000`, which is gone.
        assert not await lots._take(
            first, lot_id=stale[0].lot_id, seen=stale[0].credits_remaining, take=Decimal("600")
        )
        splits = await lots._consume_call(
            first,
            lots=list(stale),
            demand=lots.CallDemand(
                minutes=Decimal("120"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )

    # ₹500 of lot left: 100 minutes out of it, then 20 minutes of overdraft at its rate.
    assert [split.credits for split in splits] == [Decimal("500.0000"), Decimal("100.0000")]
    assert splits[-1].lot_id is None
    row = (await lot_rows(tenant))[0]
    assert row["credits_remaining"] == Decimal("0.0000")
    assert row["closed_at"] is not None


async def test_a_lot_closed_under_us_is_stepped_past_rather_than_retried() -> None:
    """The other outcome of a lost race: the row is gone from the open set entirely, so
    re-reading it yields nothing and the walk moves to the next lot. Without that arm the
    debit would spin against a lot that can never pay again."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)
    await add_lot(tenant, credits_inr="500.00", rates=GROWTH)

    async with tenant_session(tenant) as first:
        stale = await lots.read_open_lots(first, tenant_id=tenant)
        async with tenant_session(tenant) as second:
            await lots.consume(  # empties and CLOSES the first lot
                second,
                tenant_id=tenant,
                demand=lots.AiAssistDemand(credits=Decimal("100.00")),
            )
        splits = await lots._consume_ai_assist(
            first, lots=list(stale), demand=lots.AiAssistDemand(credits=Decimal("50.00"))
        )

    assert len(splits) == 1
    assert splits[0].lot_id == stale[1].lot_id
    assert [row["credits_remaining"] for row in await lot_rows(tenant)] == [
        Decimal("0.0000"),
        Decimal("450.0000"),
    ]


async def test_a_lot_that_keeps_losing_the_race_stops_instead_of_spinning() -> None:
    """A run of lost races is not contention — under the advisory lock it cannot happen at
    all — so it is a caller in a loop or a defect, and the debit says so rather than
    hanging. The failure is a conflict with a sentence, not a wedged worker."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    async def _never_wins(*_: Any, **__: Any) -> bool:
        return False

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant) as session:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(lots, "_take", _never_wins)
                await lots.consume(
                    session,
                    tenant_id=tenant,
                    demand=lots.AiAssistDemand(credits=Decimal("10.00")),
                )

    assert raised.value.code == "credit_lots_contended"
    assert raised.value.remediation
    assert (await lot_rows(tenant))[0]["credits_remaining"] == Decimal("1000.0000")

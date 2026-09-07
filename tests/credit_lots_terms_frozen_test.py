"""A lot's terms cannot be edited after it is opened (invariant §2.3.3, migration
`c9f3a71e58d2`).

The promise a client is being given is that the rates shown when they bought apply to that
credit until it is spent, whatever the rate card does later (Terms §6.1, Phase F). A
promise enforced only by "no code writes that column" lasts until the first console
feature that does, so it is enforced by the `credit_lots_terms_frozen` trigger and asserted
here — including the direction that matters most for the future: a column NOT in the
mutable allowlist is frozen even though nobody has thought about it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.credit_lots_helpers import GROWTH, add_lot, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]

FROZEN = "a lot's terms are frozen"


async def _update(tenant_id, lot_id, assignment: str) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(f"UPDATE credit_lots SET {assignment} WHERE id = :id"), {"id": lot_id}
        )


@pytest.mark.parametrize(
    "assignment",
    [
        "sarvam_inr_per_min = 1.0000",
        "cartesia_inr_per_min = 99.0000",
        "source = 'grant'",
        "pack_id = 'max'",
        "override_of_pack_id = 'max'",
        "opened_at = now() - interval '10 days'",
    ],
)
async def test_the_terms_of_a_lot_cannot_be_updated(assignment: str) -> None:
    """Each of these would change what a client was sold AFTER they bought it. The two
    rates are the promise itself; `pack_id`, `override_of_pack_id` and `source` are the
    record of why the rates are what they are; `opened_at` is its place in the FIFO queue,
    which decides whose credit is spent first."""
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    with pytest.raises(DBAPIError) as raised:
        await _update(tenant, lot_id, assignment)

    assert FROZEN in str(raised.value)


async def test_the_four_mutable_columns_still_move() -> None:
    """The allowlist, from the other side: spending a lot, closing it, and an operator's
    restatement of how much was sold all have to work."""
    tenant = await make_tenant()
    lot_id = await add_lot(tenant, credits_inr="1000.00", rates=GROWTH)

    await _update(
        tenant,
        lot_id,
        "credits_remaining = 400, credits_total = 900, closed_at = now(), updated_at = now()",
    )

    row = (await lot_rows(tenant))[0]
    assert row["credits_remaining"] == Decimal("400.0000")
    assert row["credits_total"] == Decimal("900.0000")
    assert row["closed_at"] is not None


async def test_the_freeze_is_enumerated_from_the_mutable_side() -> None:
    """FAILS IF: someone rewrites the trigger to list the FROZEN columns instead.

    The distinction is not stylistic. Listing the frozen ones makes every column added
    later mutable by default and silently; listing the mutable ones makes a new column
    frozen until somebody argues it into the allowlist. The trigger body is read from the
    database, so this asserts what is INSTALLED, not what a migration file says.
    """
    async with tenant_session(await make_tenant()) as session:
        body = (
            await session.execute(
                text(
                    "SELECT prosrc FROM pg_proc WHERE proname = 'calevate_credit_lot_terms_frozen'"
                )
            )
        ).scalar_one()

    assert "to_jsonb(NEW)" in body
    for mutable in ("credits_remaining", "credits_total", "closed_at", "updated_at"):
        assert f"'{mutable}'" in body
    assert "sarvam_inr_per_min" not in body

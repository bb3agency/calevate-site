"""`credit_lots` is tenant-isolated in both directions (hard rule 1).

The table holds what one business bought and at what price, so a cross-tenant read is a
commercial leak and a cross-tenant WRITE is worse — it moves another client's credit. The
policy is the STRICT repo-wide form for every verb, with no `OR <guc> IS NULL` arm: that
variant is what `f2b91c47e0a3` had to correct on `kb_uploads`, where it bought a
cross-tenant write that the read half's ops worker never needed. No untenanted worker reads
lots, so there is nothing here to widen for.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.db.registry import APPEND_ONLY_TABLES, TENANT_TABLES
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.credit_lots_helpers import GROWTH, add_lot, make_tenant

pytestmark = [pytest.mark.rls]


async def test_another_tenant_sees_zero_lots() -> None:
    owner = await make_tenant()
    await add_lot(owner, credits_inr="1000.00", rates=GROWTH)
    stranger = await make_tenant()

    async with tenant_session(stranger) as session:
        rows = (await session.execute(text("SELECT id FROM credit_lots"))).all()

    assert rows == []


async def test_an_untenanted_session_sees_zero_lots() -> None:
    """The fail-closed property: no GUC, no rows. A sweep or an ops query that forgets to
    enter a tenant reads nothing rather than reading everyone."""
    owner = await make_tenant()
    await add_lot(owner, credits_inr="1000.00", rates=GROWTH)

    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT id FROM credit_lots"))).all()

    assert rows == []


async def test_another_tenant_cannot_spend_this_tenant_s_lot() -> None:
    """The WITH CHECK half, which is the one the corrected migration was about. An UPDATE
    from the wrong tenant must match zero rows — not raise, not partially apply."""
    owner = await make_tenant()
    await add_lot(owner, credits_inr="1000.00", rates=GROWTH)
    stranger = await make_tenant()

    async with tenant_session(stranger) as session:
        result = await session.execute(text("UPDATE credit_lots SET credits_remaining = 0"))
        assert result.rowcount == 0

    async with tenant_session(owner) as session:
        remaining = (
            await session.execute(text("SELECT credits_remaining FROM credit_lots"))
        ).scalar_one()
    assert remaining == Decimal("1000.0000")


async def test_another_tenant_cannot_open_a_lot_on_this_tenant_s_wallet() -> None:
    """WITH CHECK on INSERT: a row whose `tenant_id` is somebody else's is refused by the
    database, whatever the code that built it believed."""
    owner = await make_tenant()
    stranger = await make_tenant()
    entry = await add_lot(owner, credits_inr="10.00", rates=GROWTH)
    assert entry  # the owner's own lot opened fine

    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(stranger) as session:
            await session.execute(
                text(
                    "INSERT INTO credit_lots (id, tenant_id, source, credits_total, "
                    "credits_remaining, sarvam_inr_per_min, cartesia_inr_per_min, "
                    "ledger_entry_id) SELECT gen_random_uuid(), :owner, 'grant', 10, 10, "
                    "5, 7, gen_random_uuid()"
                ),
                {"owner": owner},
            )


def test_the_table_is_registered_as_tenant_scoped_and_is_not_a_ledger() -> None:
    """`check_rls_coverage` refuses an unregistered tenant table, and `APPEND_ONLY_TABLES`
    is what `check_ledger_immutability` reads. A lot is drawn DOWN, so it belongs in the
    first list and must never reach the second."""
    assert "credit_lots" in TENANT_TABLES
    assert "credit_lots" not in APPEND_ONLY_TABLES

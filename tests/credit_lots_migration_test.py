"""The one-shot migration of live balances into opening lots (§3.4, plan §0 Q2).

It runs its OWN SQL — the two statements imported from revision `c9f3a71e58d2` — against
tenants this test creates, inside each tenant's session. That is deliberate: the assertion
has to be about the statements that will run on production data, not about a Python
re-implementation of them, and a migration that has already been applied cannot be
re-applied to be observed. Scoped by RLS to one tenant at a time, the `DISTINCT ON` sees
exactly that tenant's ledger, which is the same shape the bracketed production run sees
across all of them.

What is pinned: ONE lot per positive balance, at Sarvam ₹5.00 / Cartesia ₹7.00, linked to a
ZERO-DELTA marker entry; NO lot for a zero or negative balance; and no balance moved in
either case.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from apps.api.billing.service import get_balance, record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.credit_lots_helpers import lot_rows, make_tenant

pytestmark = [pytest.mark.rls]

REVISION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "c9f3a71e58d2_credit_lots.py"
)


def _revision() -> ModuleType:
    """The migration module, loaded by PATH rather than imported.

    `alembic/versions` is not a package and its modules are not importable by name; loading
    the file is also the point — the statements asserted here are the ones in the revision
    that ran, so a future edit to either half cannot pass unnoticed.
    """
    spec = importlib.util.spec_from_file_location("credit_lots_revision", REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _ledger(tenant_id: UUID, *, delta: str, reason: str, balance_after: str) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(delta),
            reason=reason,  # type: ignore[arg-type]
            ref=f"seed-{reason}-{balance_after}",
            allow_negative=True,
        )


async def _run_migration_for(tenant_id: UUID) -> None:
    revision = _revision()
    async with tenant_session(tenant_id) as session:
        await session.execute(text(revision._INSERT_MARKERS))
        await session.execute(text(revision._INSERT_LOTS))


async def test_a_positive_balance_opens_exactly_one_lot_at_the_q2_rates() -> None:
    tenant = await make_tenant()
    await _ledger(tenant, delta="2000.00", reason="topup", balance_after="2000")
    await _ledger(tenant, delta="-500.00", reason="usage", balance_after="1500")

    await _run_migration_for(tenant)

    rows = await lot_rows(tenant)
    assert len(rows) == 1
    lot = rows[0]
    assert lot["source"] == "migration"
    assert lot["credits_total"] == lot["credits_remaining"] == Decimal("1500.0000")
    # Q2: the ₹5,000-pack card. Exactly what every existing balance was sold at — a
    # migration that invented a better rate would be a gift and a worse one a breach.
    assert lot["sarvam_inr_per_min"] == Decimal("5.0000")
    assert lot["cartesia_inr_per_min"] == Decimal("7.0000")
    assert lot["pack_id"] is None
    assert lot["closed_at"] is None


async def test_the_marker_entry_records_where_lots_began_and_moves_no_money() -> None:
    tenant = await make_tenant()
    await _ledger(tenant, delta="800.00", reason="topup", balance_after="800")

    await _run_migration_for(tenant)

    async with tenant_session(tenant) as session:
        marker = (
            (
                await session.execute(
                    text(
                        "SELECT id, delta, reason, balance_after, meta FROM credit_ledger "
                        "WHERE ref = 'lot_migration'"
                    )
                )
            )
            .mappings()
            .one()
        )
        balance = (await get_balance(session, tenant_id=tenant)).amount_inr

    assert marker["delta"] == Decimal("0.0000")
    assert marker["reason"] == "adjustment"
    assert marker["meta"] == {"kind": "lot_migration"}
    assert balance == Decimal("800.0000")
    assert (await lot_rows(tenant))[0]["id"] is not None
    # The lot names the marker, so `ledger_entry_id` (UNIQUE) points at a real row.
    async with tenant_session(tenant) as session:
        linked = (
            await session.execute(text("SELECT ledger_entry_id FROM credit_lots"))
        ).scalar_one()
    assert UUID(str(linked)) == UUID(str(marker["id"]))


@pytest.mark.parametrize(
    ("delta", "reason"),
    [("0.00", "topup"), ("-150.00", "usage")],
)
async def test_a_wallet_at_or_below_zero_opens_no_lot(delta: str, reason: str) -> None:
    """A spent or overdrawn wallet has nothing to express as a lot: invariant §2.3.1 says
    every lot is at zero below the line, and opening one for a negative balance would be
    inventing credit."""
    tenant = await make_tenant()
    await _ledger(tenant, delta="100.00", reason="topup", balance_after="100")
    await _ledger(
        tenant, delta=str(Decimal(delta) - Decimal("100.00")), reason=reason, balance_after="0"
    )

    await _run_migration_for(tenant)

    assert await lot_rows(tenant) == []
    async with tenant_session(tenant) as session:
        markers = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE ref = 'lot_migration'")
            )
        ).scalar_one()
    assert markers == 0


async def test_a_wallet_with_no_ledger_at_all_opens_no_lot() -> None:
    tenant = await make_tenant()

    await _run_migration_for(tenant)

    assert await lot_rows(tenant) == []

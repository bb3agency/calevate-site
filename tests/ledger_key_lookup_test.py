"""Lookups by `(tenant_id, reason, ref)` read `ux_credit_ledger_tenant_reason_ref`.

The key is partial on a cutoff (migration f9c2b41a8e57), so a lookup that does not repeat
the bound cannot use it and reads every ledger row the tenant has: one row per charged
call, so it grows with the account, and `read_entry_by_ref` runs under the credit lock on
the charge path. These pin that the bound is the index's own, that a row on either side of
it is still found, and that the plans use the key.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from apps.api.billing.attribution import _WALLET_DEBITS_SQL
from apps.api.billing.models import LEDGER_KEY_SINCE_SQL
from apps.api.billing.service import read_entry_by_ref
from apps.api.db.session import get_engine, tenant_session
from scripts.reconcile_credit_ledger import LEDGER_UNIQUE_INDEX_CUTOFF
from sqlalchemy import event, text
from tests.conftest import create_org_with_receptionist

KEY = "ux_credit_ledger_tenant_reason_ref"


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Ledger Key Traders",
        slug=f"ledger-key-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _debit(tenant_id: uuid.UUID, ref: str, *, before_cutoff: bool) -> uuid.UUID:
    entry_id = uuid.uuid4()
    at = LEDGER_UNIQUE_INDEX_CUTOFF - timedelta(days=3) if before_cutoff else None
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) VALUES (:id, :t, -2.50, 'usage', :ref, 0, "
                "COALESCE(CAST(:at AS timestamptz), now()), now())"
            ),
            {"id": entry_id, "t": tenant_id, "ref": ref, "at": at},
        )
    return entry_id


async def test_the_bound_is_the_keys_own_cutoff() -> None:
    async with tenant_session(uuid.uuid4()) as session:
        predicate = (
            await session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": KEY}
            )
        ).scalar_one()
        bound = (await session.execute(text(f"SELECT {LEDGER_KEY_SINCE_SQL}"))).scalar_one()
    assert bound == LEDGER_UNIQUE_INDEX_CUTOFF
    assert "occurred_at >= '2026-08-11 08:07:00+00'" in predicate, predicate


async def test_an_entry_on_either_side_of_the_cutoff_is_found() -> None:
    tenant_id = await _tenant()
    old_ref, new_ref = str(uuid.uuid4()), str(uuid.uuid4())
    old_id = await _debit(tenant_id, old_ref, before_cutoff=True)
    new_id = await _debit(tenant_id, new_ref, before_cutoff=False)
    async with tenant_session(tenant_id) as session:
        old = await read_entry_by_ref(session, tenant_id=tenant_id, reason="usage", ref=old_ref)
        new = await read_entry_by_ref(session, tenant_id=tenant_id, reason="usage", ref=new_ref)
        none = await read_entry_by_ref(session, tenant_id=tenant_id, reason="topup", ref=new_ref)
        debits = (
            await session.execute(
                text(_WALLET_DEBITS_SQL), {"tid": tenant_id, "refs": [old_ref, new_ref]}
            )
        ).all()
    assert old is not None and old.entry_id == old_id
    assert new is not None and new.entry_id == new_id and new.amount_inr == Decimal("-2.50")
    assert none is None, "the reason is part of the key"
    assert {str(r[0]): r[1] for r in debits} == {old_ref: Decimal("2.50"), new_ref: Decimal("2.50")}


async def test_both_lookups_read_the_key() -> None:
    tenant_id = await _tenant()
    ref = str(uuid.uuid4())
    await _debit(tenant_id, ref, before_cutoff=False)
    captured: list[tuple[str, Any]] = []

    def capture(_c: Any, _cur: Any, statement: str, params: Any, *_rest: Any) -> None:
        if "credit_ledger" in statement and "ref = " in statement:
            captured.append((statement, params))

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        async with tenant_session(tenant_id) as session:
            await read_entry_by_ref(session, tenant_id=tenant_id, reason="usage", ref=ref)
            await session.execute(text(_WALLET_DEBITS_SQL), {"tid": tenant_id, "refs": [ref]})
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    assert len(captured) == 2

    async with tenant_session(tenant_id) as session:
        connection = await session.connection()
        # Priced out so a tiny table does not make a scan the cheaper choice.
        await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        await connection.exec_driver_sql("SET LOCAL enable_bitmapscan = off")
        for statement, params in captured:
            plan = "\n".join(
                str(r[0])
                for r in (await connection.exec_driver_sql("EXPLAIN " + statement, params)).all()
            )
            assert KEY in plan, f"{statement}\n{plan}"

"""Reconciling the double-credits a check-then-write race left on `credit_ledger`.

The bug is fixed (the dedupe SELECT now runs under the advisory lock); the RESIDUE is
not. 21 `(tenant_id, ref)` pairs hold two entries where one payment or one call
happened, so those wallets read high (top-ups) or low (usage). Hard rule 4 forbids the
obvious repair: the rows are evidence, and a ledger you can edit is not one. The repair
is a COMPENSATING ENTRY.

What these tests protect, in the order they matter:

- **Idempotency.** The thing being fixed is a double-write, so a reconciler that can
  double-write is the same bug wearing a fix's clothes. Running it twice — and running
  two of it at the same moment, which is exactly how the originals were created — must
  compensate ONCE.
- **The originals survive byte for byte.** A "reconciliation" that quietly repaired
  history would destroy the only record of what happened.
- **Dry run is the default.** A money-writing script whose default is to write is a
  footgun; `parse_args([])` must not apply.
- **The trigger still refuses an UPDATE.** If a future hand ever "simplifies" the
  compensating INSERT into an edit, this is the test that stops it.

Every tenant here is created by the test and corrected by the test. Nothing runs a
full-database scan: the dev database is shared and has 15k+ organizations in it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import get_balance, record_entry
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from scripts import reconcile_credit_ledger as reconciler
from scripts.reconcile_credit_ledger import (
    COMPENSATION_REASON,
    DUPLICATE_REF_PREFIX,
    parse_args,
    reconcile,
    scan_tenant,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Reconcile Clinic",
        slug=f"rec-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
    return tenant_id


async def _rows(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """The whole wallet, oldest first — the same ordering `_newest_balance` reads by."""
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text(
                    "SELECT id, reason, delta, ref, balance_after, occurred_at, meta "
                    "FROM credit_ledger WHERE tenant_id = :t ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [
        {
            "id": uuid.UUID(str(r[0])),
            "reason": str(r[1]),
            "delta": Decimal(str(r[2])),
            "ref": r[3],
            "balance_after": Decimal(str(r[4])),
            "occurred_at": r[5],
            "meta": r[6],
        }
        for r in found
    ]


async def _balance(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


# The residue this tool repairs is HISTORICAL: it was written before the
# check-then-write race was closed, and the closed race cannot produce it again.
RESIDUE_AGE = timedelta(days=120)


async def _double_credit(tenant_id: uuid.UUID, ref: str = "UTR-DOUBLE-1") -> None:
    """The race's output, seeded as what it actually is — an old pair of rows.

    This used to call `record_entry` twice, on the reasoning that the originals came
    through the ledger's only writer and a hand-rolled INSERT would seed a shape the
    bug never produced. That was right about fidelity and wrong about time:
    `record_entry` stamps `clock_timestamp()`, so every run of this suite manufactured
    a FRESH violating pair — and a unique index that would stop the race recurring
    cannot be added while its own test suite keeps producing violations after any
    cutoff. Measured by the migration that tried: 11 of this module's 13 tests failed
    with such an index present.

    So the rows are inserted directly, backdated. An INSERT is exactly what the
    append-only trigger permits (hard rule 4 forbids UPDATE and DELETE, which is why
    backdating afterwards is impossible and had to move to the write). `balance_after`
    is computed the way `record_entry` computes it, so the shape is still the shape the
    bug produced — including the second row's balance reflecting the phantom credit,
    which is the whole reason the wallet reads richer than it is.
    """
    occurred = datetime.now(UTC) - RESIDUE_AGE
    async with tenant_session(tenant_id) as session:
        opening = (
            await session.execute(
                text(
                    "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
                    "ORDER BY occurred_at DESC, id DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).scalar()
        running = Decimal(opening) if opening is not None else Decimal("0")
        for index in range(2):
            running += Decimal("750")
            await session.execute(
                text(
                    "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, "
                    "balance_after, occurred_at, created_at) VALUES (:id, :tid, :delta, "
                    "'topup', :ref, :balance, :at, :at)"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "delta": Decimal("750"),
                    "ref": ref,
                    "balance": running,
                    # Distinct instants, so `ORDER BY occurred_at, id` is stable and the
                    # reconciler keeps the FIRST row exactly as it would in production.
                    "at": occurred + timedelta(seconds=index),
                },
            )


# --- the detector --------------------------------------------------------------


async def test_the_detector_prices_the_duplication_without_touching_it() -> None:
    tenant_id = await _tenant()
    await _double_credit(tenant_id)
    before = await _rows(tenant_id)

    async with tenant_session(tenant_id) as session:
        groups = await scan_tenant(session, tenant_id)

    assert len(groups) == 1
    group = groups[0]
    assert (group.ref, group.reason) == ("UTR-DOUBLE-1", "topup")
    assert group.entry_ids == (before[0]["id"], before[1]["id"])
    assert group.kept_entry_id == before[0]["id"], "the FIRST entry is the real one"
    assert group.duplicate_entry_ids == (before[1]["id"],)
    # The surplus is what the wallet is overstated by, and it is a Decimal — never a
    # float (hard rule 7).
    assert group.surplus_inr == Decimal("750.0000")
    assert isinstance(group.surplus_inr, Decimal)
    assert await _rows(tenant_id) == before, "a detector writes nothing"


async def test_a_clean_wallet_reports_nothing() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup", ref="UTR-CLEAN-1"
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-30"),
            reason="usage",
            ref=str(uuid.uuid4()),
        )
        groups = await scan_tenant(session, tenant_id)
    assert groups == []

    report = await reconcile(tenant_id=tenant_id, apply=True)
    assert report.groups == 0
    assert report.written == 0
    assert len(await _rows(tenant_id)) == 2


# --- dry run is the default ----------------------------------------------------


def test_the_command_line_defaults_to_a_dry_run() -> None:
    """The property, not the docstring: an operator who types nothing writes nothing."""
    assert parse_args([]).apply is False
    assert parse_args(["--apply"]).apply is True


async def test_the_dry_run_reports_the_correction_it_would_write_and_writes_nothing() -> None:
    tenant_id = await _tenant()
    await _double_credit(tenant_id)
    before = await _rows(tenant_id)

    report = await reconcile(tenant_id=tenant_id)  # no `apply=` — the default

    assert report.applied is False
    assert report.groups == 1
    assert report.written == 0
    assert report.surplus_inr == Decimal("750.0000")
    tenant = report.tenants[0]
    assert tenant.tenant_id == tenant_id
    assert tenant.balance_inr == Decimal("1500.0000"), "what the wallet says today"
    assert tenant.balance_after_inr == Decimal("750.0000"), "what it would say after"
    correction = tenant.corrections[0]
    assert correction.status == "pending"
    assert correction.delta_inr == Decimal("-750.0000")
    assert await _rows(tenant_id) == before, "a dry run is a read"


# --- the compensating entry ----------------------------------------------------


async def test_one_compensating_entry_corrects_the_balance_and_both_originals_survive() -> None:
    tenant_id = await _tenant()
    await _double_credit(tenant_id)
    before = await _rows(tenant_id)

    report = await reconcile(tenant_id=tenant_id, apply=True)

    assert report.applied is True
    assert report.written == 1
    after = await _rows(tenant_id)

    assert len(after) == 3, "two originals plus exactly one correction"
    assert after[:2] == before, "the evidence is untouched — same ids, deltas, balances"
    assert await _balance(tenant_id) == Decimal("750.0000"), "one payment, one credit"

    entry = after[2]
    assert entry["reason"] == COMPENSATION_REASON == "adjustment"
    assert entry["delta"] == Decimal("-750.0000")
    assert entry["balance_after"] == Decimal("750.0000")


async def test_the_correction_names_the_group_it_corrects() -> None:
    """A future reader must be able to walk from the correction back to its cause
    without knowing this script ever existed."""
    tenant_id = await _tenant()
    await _double_credit(tenant_id, ref="UTR-TRACE-9")
    originals = await _rows(tenant_id)
    await reconcile(tenant_id=tenant_id, apply=True)
    entry = (await _rows(tenant_id))[2]

    ref = str(entry["ref"])
    assert ref.startswith(f"{DUPLICATE_REF_PREFIX}:topup:UTR-TRACE-9:")
    assert ref != "UTR-TRACE-9", (
        "the correction cannot reuse the duplicated reference — that would make the "
        "pair a triple and keep the unique index unbuildable"
    )

    meta = entry["meta"]
    assert meta["kind"] == "duplicate_ledger_entry"
    assert meta["dedupe"] == {"ref": "UTR-TRACE-9", "reason": "topup"}
    assert meta["kept_entry_id"] == str(originals[0]["id"])
    assert meta["compensated_entry_ids"] == [str(originals[1]["id"])]
    # Money inside JSON is a STRING. A JSON number here would be a float by the time
    # anyone read it back (hard rule 7).
    assert meta["surplus_inr"] == "750.0000"
    assert isinstance(meta["surplus_inr"], str)


async def test_an_over_charged_call_is_compensated_upward() -> None:
    """The two `usage` groups: the client was debited twice for one call, so the
    correction is a credit. Same machinery, opposite sign."""
    tenant_id = await _tenant()
    call_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("1000"), reason="topup", ref="UTR-USAGE-1"
        )
        for _ in range(2):
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("-30"), reason="usage", ref=call_id
            )

    assert await _balance(tenant_id) == Decimal("940.0000")
    report = await reconcile(tenant_id=tenant_id, apply=True)

    assert report.written == 1
    assert report.surplus_inr == Decimal("-30.0000"), "the wallet reads LOW by ₹30"
    assert await _balance(tenant_id) == Decimal("970.0000")
    entry = (await _rows(tenant_id))[3]
    assert entry["delta"] == Decimal("30.0000")
    assert str(entry["ref"]).startswith(f"{DUPLICATE_REF_PREFIX}:usage:{call_id}:")


# --- idempotency: the property most likely to go wrong -------------------------


async def test_a_second_run_compensates_nothing() -> None:
    tenant_id = await _tenant()
    await _double_credit(tenant_id)

    first = await reconcile(tenant_id=tenant_id, apply=True)
    settled = await _rows(tenant_id)
    second = await reconcile(tenant_id=tenant_id, apply=True)

    assert first.written == 1
    assert second.written == 0, "the surplus was already cancelled once"
    assert second.tenants[0].corrections[0].status == "already_reconciled"
    assert await _rows(tenant_id) == settled, "a re-run is a no-op, row for row"
    assert await _balance(tenant_id) == Decimal("750.0000")


async def test_a_dry_run_after_a_real_run_reports_nothing_left_to_do() -> None:
    tenant_id = await _tenant()
    await _double_credit(tenant_id)
    await reconcile(tenant_id=tenant_id, apply=True)

    report = await reconcile(tenant_id=tenant_id)

    assert report.groups == 1, "the duplicated group is still in the history, as it must be"
    assert report.pending == 0, "but there is nothing left to write"
    assert report.tenants[0].balance_after_inr == report.tenants[0].balance_inr


async def test_two_reconcilers_running_at_once_compensate_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode this whole file exists for.

    Two runs overlapping is not hypothetical — it is precisely how the duplicates being
    fixed were created. If the "has this group been compensated?" lookup ran outside the
    per-tenant advisory lock, both runs would read "not yet" and both would append, and
    the reconciler would have re-committed the bug it was written to repair.

    The overlap is FORCED, for the reason `credit_topup_test.py` documents about its own
    race: a plain `asyncio.gather` of two runs does not reliably interleave — with the
    lock deleted it still reported "one correction" on every attempt, a test that would
    keep passing after the property it names was removed. So the second run is released
    only once the first is inside the critical section, and the MECHANISM is asserted
    next to the outcome: while the first run holds the lock, the second must not be able
    to reach the idempotency lookup at all.
    """
    tenant_id = await _tenant()
    await _double_credit(tenant_id, ref="UTR-RERACE-1")

    first_planned = asyncio.Event()
    second_planned = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_plan = reconciler.plan_correction

    async def traced(session: Any, group: Any) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            planned = await real_plan(session, group)
            first_planned.set()
            # If the lock does its job the second run cannot get here, so this times
            # out — the timeout IS the passing case, and the sample below is taken
            # while the first run still holds its transaction open.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(second_planned.wait(), timeout=1.0)
            seen["second_planned_while_first_open"] = second_planned.is_set()
            return planned
        if task is not holder:
            second_planned.set()
        return await real_plan(session, group)

    monkeypatch.setattr(reconciler, "plan_correction", traced)

    async def run(second: bool) -> Any:
        if second:
            await first_planned.wait()
        return await reconcile(tenant_id=tenant_id, apply=True)

    reports = await asyncio.gather(run(False), run(True))

    assert seen.get("second_planned_while_first_open") is False, (
        "the second run read the group's corrections while the first was still open — "
        "the advisory lock is not covering the check-then-write"
    )
    assert sum(r.written for r in reports) == 1, "one surplus, one correction"
    corrections = [r for r in await _rows(tenant_id) if r["reason"] == COMPENSATION_REASON]
    assert len(corrections) == 1
    assert await _balance(tenant_id) == Decimal("750.0000")


async def test_the_compensating_reference_is_unique_within_the_tenant() -> None:
    """Two duplicated groups on one wallet must not produce one colliding correction —
    otherwise the reconciliation leaves behind exactly the defect it was cleaning up."""
    tenant_id = await _tenant()
    await _double_credit(tenant_id, ref="UTR-TWO-A")
    await _double_credit(tenant_id, ref="UTR-TWO-B")

    report = await reconcile(tenant_id=tenant_id, apply=True)

    assert report.written == 2
    refs = [r["ref"] for r in await _rows(tenant_id) if r["reason"] == COMPENSATION_REASON]
    assert len(refs) == len(set(refs)) == 2
    assert await _balance(tenant_id) == Decimal("1500.0000"), "two real payments of ₹750"


# --- the floor the reconciler stands on ----------------------------------------


async def test_the_ledger_still_refuses_an_update_after_reconciliation() -> None:
    """If this reconciler is ever "improved" into an UPDATE, the database says no —
    and that is the guarantee, not the code review that missed it."""
    tenant_id = await _tenant()
    await _double_credit(tenant_id)
    await reconcile(tenant_id=tenant_id, apply=True)

    with pytest.raises(DBAPIError, match="append-only"):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE credit_ledger SET delta = 0 WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM credit_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
    assert len(await _rows(tenant_id)) == 3, "nothing was removed by the attempts"


async def test_reconciling_one_tenant_leaves_another_alone() -> None:
    mine = await _tenant()
    theirs = await _tenant()
    await _double_credit(mine, ref="UTR-MINE")
    await _double_credit(theirs, ref="UTR-THEIRS")
    untouched = await _rows(theirs)

    report = await reconcile(tenant_id=mine, apply=True)

    assert [t.tenant_id for t in report.tenants] == [mine]
    assert await _rows(theirs) == untouched
    assert await _balance(theirs) == Decimal("1500.0000"), "still overstated, deliberately"

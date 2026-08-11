"""Whether `credit_ledger` can carry a unique index on its reference — settled.

Four attempts added a partial unique index on `(tenant_id, ref)` and four were refused.
The refusals were each correct and each incomplete: they named the history that blocks
the build, then a fixture that kept minting fresh violations, then a second fixture. The
question nobody answered is the one this file answers — *what writes a duplicate, and is
any of it something production is allowed to do?*

Measured, not reasoned about: snapshot the violating groups, run the suite, diff, and
pull the rows. Every violating group on this database traces to one of five writers.

  1. `credit_reconciliation_test._double_credit` / `_double_charge` — residue seeds.
     LEGITIMATE. The script under test repairs duplicates, so its fixtures must create
     duplicates. Backdated by direct INSERT, so they sit behind the cutoff. See
     `test_the_residue_seed_cannot_drift_past_the_cutoff` — they used to be backdated
     RELATIVE to now, which is a time bomb, and that is fixed here.
  2. `schema_hardening_2_test` / `schema_hardening_3_test` tripwires — self-referential.
     They assert the index is ABSENT and mint a pair each run to prove it. Their own
     docstrings say to delete them in the commit that adds the index. They are the only
     writers that put a violation AFTER the cutoff, and they stop existing with it.
  3. `signup_atomicity_test.test_the_lookup_ignores_a_usage_row_carrying_the_same_ref`
     — LEGITIMATE, and the reason the key is not `(tenant_id, ref)`. A call id and a
     payment reference share the `ref` column, and the system is written to tolerate a
     collision rather than prevent it. See `test_a_call_id_and_a_payment_reference_may_
     collide`.
  4. The reconciler's own compensating entries, written twice in a lost race (five
     `adjustment` groups, all 2026-08-11 04:57 to 04:58). FIXED before this session — the
     lock now precedes the scan — and non-recurring. See
     `test_the_reconciler_still_compensates_a_group_only_once`.
  5. The production writers themselves, before commit 636171c/51a52c4 moved the dedupe
     SELECT inside the advisory lock. FIXED. See
     `test_the_production_writers_cannot_mint_a_duplicate_key`.

So: nothing production is allowed to do produces a duplicate `(tenant_id, reason, ref)`,
and the one duplicate it IS allowed to produce — a shared `ref` across two reasons — is
excluded by putting `reason` in the key. The index is landable. Its exact statement and
rationale live in `scripts/reconcile_credit_ledger.py`, which is also where the cutoff
constant lives, so this file and the migration cannot disagree about the date.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import charge_for_call, find_topup, record_entry
from apps.api.db.session import tenant_session
from scripts.reconcile_credit_ledger import (
    COMPENSATION_REASON,
    LEDGER_UNIQUE_INDEX_CUTOFF,
    reconcile,
)
from sqlalchemy import text
from tests import credit_reconciliation_test as residue

# The index this file is about. Written out once so every assertion below is checked
# against the same shape the migration will carry.
INDEX_KEY = ("tenant_id", "reason", "ref")


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Uniqueness Clinic",
        slug=f"uniq-{uuid.uuid4().hex[:8]}",
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


async def _keys(tenant_id: uuid.UUID) -> list[tuple[str, str, datetime]]:
    """Every `(reason, ref, occurred_at)` on one wallet — the index key, materialized."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, ref, occurred_at FROM credit_ledger "
                    "WHERE tenant_id = :t AND ref IS NOT NULL ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), str(r[1]), r[2]) for r in rows]


def _duplicate_keys(keys: list[tuple[str, str, datetime]]) -> list[tuple[str, str]]:
    """What the candidate index would reject: a repeated `(reason, ref)` at or after the
    cutoff. Rows before the cutoff are outside the partial index and cannot collide."""
    seen: set[tuple[str, str]] = set()
    clashes: list[tuple[str, str]] = []
    for reason, ref, occurred_at in keys:
        if occurred_at < LEDGER_UNIQUE_INDEX_CUTOFF:
            continue
        if (reason, ref) in seen:
            clashes.append((reason, ref))
        seen.add((reason, ref))
    return clashes


# --- 1. the residue seed, and the time bomb it used to carry ---------------------


class _Recorded:
    """Stands in for a result row. The seed helpers only ever call `.scalar()` on their
    one read (the opening balance); `None` is the "empty wallet" answer."""

    def scalar(self) -> None:
        return None


class _RecordingSession:
    """Captures the parameters a seed helper would write, and writes nothing.

    This test must not touch `credit_ledger`, and the reason is the whole subject of
    the file. Its FAILING state is a residue seed stamped in the future; if it wrote
    that row, a single red run would leave an undeletable post-cutoff duplicate on the
    database (hard rule 4 — the append-only trigger refuses the cleanup), and the index
    this file exists to unblock would be unbuildable there forever. A test whose red
    state permanently breaks the thing it is testing is not a tripwire, it is a trap.
    So the property is asserted against the parameters, one layer above the INSERT.
    """

    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Recorded:
        if params is not None:
            self.params.append(params)
        return _Recorded()


async def test_the_residue_seed_cannot_drift_past_the_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The minter nobody named, because it only misbehaves in the future.

    `_double_credit` seeds its residue backdated — that much was already fixed, and it
    is what let a cutoff predicate work at all. But it backdated RELATIVE to the wall
    clock (`datetime.now(UTC) - timedelta(days=120)`), and a cutoff is an ABSOLUTE
    literal frozen into a migration. Those two move apart: 120 days after the migration
    lands, `now() - 120 days` is *after* the cutoff, the seed starts landing inside the
    partial index, and `credit_reconciliation_test` begins failing with an IntegrityError
    on a date nobody chose. The suite would have been green for four months first.

    So the property is not "the seed is old", it is "the seed does not move". This winds
    the fixture's clock 16 months forward and requires the rows it would write to still
    fall before the cutoff — which is only true if the seed instant is a constant.
    """

    class _FutureClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime(2027, 12, 25, tzinfo=UTC)

    recorder = _RecordingSession()

    @asynccontextmanager
    async def _fake_session(_tenant_id: uuid.UUID) -> AsyncIterator[_RecordingSession]:
        yield recorder

    monkeypatch.setattr(residue, "datetime", _FutureClock)
    monkeypatch.setattr(residue, "tenant_session", _fake_session)

    await residue._double_credit(uuid.uuid4(), ref="UTR-DRIFT-1")
    await residue._double_charge(uuid.uuid4(), str(uuid.uuid4()), opening=Decimal("1000"))

    stamps = [p["at"] for p in recorder.params if "at" in p]
    assert len(stamps) == 5, "two double-credit rows, one opening top-up, two charges"
    latest = max(stamps)
    assert latest < LEDGER_UNIQUE_INDEX_CUTOFF, (
        f"with the clock at 2027-12-25 the residue seed would land at {latest}, at or "
        f"after the {LEDGER_UNIQUE_INDEX_CUTOFF} cutoff — it is backdated relative to "
        "the wall clock, so it walks forward across the cutoff and takes the unique "
        "index with it"
    )


async def test_the_seeded_residue_is_still_the_shape_the_reconciler_repairs() -> None:
    """Pinning the seed to an absolute instant must not turn it into a different fact.

    The rows still have to be a duplicated group the detector finds and prices, or the
    fix above would have bought the index by deleting the coverage.
    """
    tenant_id = await _tenant()
    await residue._double_credit(tenant_id, ref="UTR-STILL-REAL")

    report = await reconcile(tenant_id=tenant_id, apply=True)

    assert report.groups == 1
    assert report.written == 1
    assert report.surplus_inr == Decimal("750.0000"), "one phantom ₹750 credit, priced"


# --- 2. why `reason` is in the key ----------------------------------------------


async def test_a_call_id_and_a_payment_reference_may_collide() -> None:
    """The finding that rules out `UNIQUE (tenant_id, ref)` — the shape attempted four
    times.

    `credit_ledger.ref` is not one namespace. A `usage` row carries a call id; a `topup`
    row carries whatever the bank printed — `TopUpIn.payment_ref` is a free string of 3
    to 120 characters, so a 36-character UUID is a value an operator can legitimately
    key. The system does not prevent the collision, it TOLERATES it, deliberately and in
    three places: `find_topup` scopes its lookup to `reason = 'topup'`, `charge_for_call`
    scopes its dedupe to `reason = 'usage'`, and the reconciler's own detector groups by
    `(ref, reason)` rather than by `ref`.

    A unique index on `(tenant_id, ref)` would convert that tolerated collision into an
    IntegrityError on a money route — a 500 on the top-up endpoint for a payment that is
    perfectly valid. That is the failure mode worth more than the duplicates the index
    catches, and it is why the key carries `reason`.
    """
    tenant_id = await _tenant()
    shared = str(uuid.uuid4())

    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-10.00"),
            reason="usage",
            ref=shared,
            allow_negative=True,
        )
        assert await find_topup(session, tenant_id=tenant_id, ref=shared) is None, (
            "a usage row must never be readable as a credited payment"
        )
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("300.00"), reason="topup", ref=shared
        )
        found = await find_topup(session, tenant_id=tenant_id, ref=shared)

    assert found is not None and found.amount_inr == Decimal("300.0000")

    keys = await _keys(tenant_id)
    refs = [ref for _, ref, _ in keys]
    assert refs.count(shared) == 2, "one reference, two reasons, both legitimate"
    assert "reason" in INDEX_KEY, "the key must separate them"
    assert _duplicate_keys(keys) == [], (
        "a (tenant_id, reason, ref) index tolerates the collision; a (tenant_id, ref) "
        "one would have rejected a valid payment"
    )


# --- 3. the writers that used to mint, and no longer do -------------------------


async def test_the_production_writers_cannot_mint_a_duplicate_key() -> None:
    """Both real writers, driven concurrently, land one row each.

    This is the property the index would enforce, asserted against the code that is
    supposed to make the index redundant. If either dedupe ever slips back outside
    `lock_tenant_credits`, this fails here rather than as an IntegrityError in
    production.
    """
    tenant_id = await _tenant()
    call_id = uuid.uuid4()
    payment_ref = f"UTR-CONC-{uuid.uuid4().hex[:8]}"

    async def top_up() -> None:
        async with tenant_session(tenant_id) as session:
            if await find_topup(session, tenant_id=tenant_id, ref=payment_ref) is None:
                await record_entry(
                    session,
                    tenant_id=tenant_id,
                    delta=Decimal("500.00"),
                    reason="topup",
                    ref=payment_ref,
                )

    async def charge() -> None:
        async with tenant_session(tenant_id) as session:
            await charge_for_call(
                session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("30.00")
            )

    await asyncio.gather(top_up(), top_up())
    await asyncio.gather(charge(), charge())

    keys = await _keys(tenant_id)
    assert [k for k in keys if k[1] == payment_ref] != [], "the top-up did land"
    assert len([k for k in keys if k[1] == payment_ref]) == 1, "one payment, one credit"
    assert len([k for k in keys if k[1] == str(call_id)]) == 1, "one call, one debit"
    assert _duplicate_keys(keys) == []


async def test_the_reconciler_still_compensates_a_group_only_once() -> None:
    """Writer #4: the reconciler's own `adjustment` entries were double-written once
    (five groups, 2026-08-11 04:57 to 04:58) before its idempotency lookup moved inside the
    lock. Re-running it must not re-mint the very defect it repairs — including into a
    key the index would then reject."""
    tenant_id = await _tenant()
    await residue._double_credit(tenant_id, ref="UTR-ONCE-1")

    first = await reconcile(tenant_id=tenant_id, apply=True)
    second = await reconcile(tenant_id=tenant_id, apply=True)

    assert first.written == 1
    assert second.written == 0, "the second run found its own correction and wrote nothing"

    keys = await _keys(tenant_id)
    compensations = [k for k in keys if k[0] == COMPENSATION_REASON]
    assert len(compensations) == 1
    assert _duplicate_keys(keys) == []


# --- 4. the cutoff itself --------------------------------------------------------


def test_the_cutoff_and_the_residue_cannot_cross() -> None:
    """A cutoff is only a grandfather line if it stops moving, and so is the residue.

    Deliberately NOT asserted here: that the cutoff is "in the past". That is a fact
    about when the test runs, not about the constant, and encoding it would rot in
    exactly the way the relative backdate did — it would fail on this machine today and
    start passing tomorrow. What must hold forever is the ORDER of two fixed instants,
    plus the tzinfo: a naive literal compared against a `timestamptz` column is read in
    the server's zone, which is how a cutoff silently moves by five and a half hours.

    The 30-day gap is headroom. The migration author has to move the cutoff forward to
    their own authoring instant (see `scripts/reconcile_credit_ledger.py`), and they
    should be able to do that without coming back to the residue fixture.
    """
    assert LEDGER_UNIQUE_INDEX_CUTOFF.tzinfo is not None, "a naive cutoff is a moving one"
    assert residue.RESIDUE_AT.tzinfo is not None
    assert LEDGER_UNIQUE_INDEX_CUTOFF - timedelta(days=30) > residue.RESIDUE_AT, (
        "the reconciliation residue must sit well behind the cutoff, with room for the "
        "cutoff to be moved forward when the migration is finally authored"
    )

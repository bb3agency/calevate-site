"""Dropping `ix_credit_ledger_tenant_id`: the column stays indexed, twice becomes once.

Migration `a6f2e84b1d37` created `ix_credit_ledger_tenant_recent`
`(tenant_id, occurred_at DESC, id DESC)` and deliberately kept the older
single-column `ix_credit_ledger_tenant_id` for one release — hard rule 8's two-step
deprecation, "the new index has to be observed carrying production plans before the
old one is removed". Migration `e7c3d10a9f52` is step two. This file is what makes
that removal a claim with evidence rather than a hopeful diff.

Three properties, and the third is the one that matters:

1. **The prefix index is gone**, and gone from the MODEL too. Dropping it in SQL while
   `CreditLedgerEntry.tenant_id` still said `index=True` would have the next
   `alembic revision --autogenerate` recreate it — a deprecation that undoes itself.
2. **`tenant_id` is still indexed**, by an index that LEADS with it. A btree's leading
   column is what makes a prefix index redundant, so the claim "redundant" is exactly
   the claim "some other index starts with this column".
3. **Every query the repo issues against `credit_ledger` still reaches an index**,
   asserted by pricing sequential scans at `disable_cost` and requiring that no Seq
   Scan survives. That is the same stable probe `schema_hardening_test.py` uses for the
   balance read's ordering, and for the same reason: a plain "the plan must not Seq
   Scan" assertion measures the table's STATISTICS — on a near-empty table a sequential
   scan is the correct plan and the test would fail for a schema that is perfectly
   fine. A Seq Scan that survives being priced at disable_cost means no index can serve
   the predicate at all, which is the actual regression the drop could cause, and the
   verdict is the same on an empty table and a million-row one.

Nothing is committed. `credit_ledger` is append-only (hard rule 4) and the
`credit_ledger_append_only` trigger enforces it at the database, so the ledger below is
built inside one transaction and the transaction is ABANDONED. A rollback is not a
deletion — those rows were never facts.

CONCURRENCY: every case mints its own tenant and asserts no global count, so this file
runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import json
from typing import Any

from apps.api.billing.models import CreditLedgerEntry
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DROPPED_INDEX = "ix_credit_ledger_tenant_id"
COMPOSITE_INDEX = "ix_credit_ledger_tenant_recent"

LEDGER_ENTRIES = 2000

# Every statement in the repo that reads `credit_ledger` with a `tenant_id` predicate —
# the set the dropped index could conceivably have been serving. Named by their callers
# so a failure says which surface broke, not which SQL string did.
#
# The last one is the FK enforcement check `organizations ON DELETE RESTRICT` runs when
# an operator deletes a tenant, in the shape Postgres issues it (`SELECT 1 ... FOR KEY
# SHARE`). The real RI query bypasses RLS entirely — the manual is explicit that
# referential integrity checks are not subject to row security — so this is the same
# predicate under a tenant session rather than the literal trigger; the index choice is
# what is being measured and the predicate is identical either way. The plan of the
# genuine RI query, taken with `row_security = off` on an 18k-entry ledger, is recorded
# in migration e7c3d10a9f52.
LEDGER_QUERIES: dict[str, str] = {
    "_newest_balance (billing/service.py)": (
        "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
        "ORDER BY occurred_at DESC, id DESC LIMIT 1"
    ),
    "credits panel (billing/credit_routes.py)": (
        "SELECT id, delta, reason, ref, balance_after, occurred_at FROM credit_ledger "
        "WHERE tenant_id = :tid ORDER BY occurred_at DESC, id DESC LIMIT 50"
    ),
    "_find_topup (billing/service.py)": (
        "SELECT id, delta FROM credit_ledger WHERE tenant_id = :tid AND reason = 'topup' "
        "AND ref = 'no-such-ref' ORDER BY occurred_at DESC, id DESC LIMIT 1"
    ),
    "charge_for_call dedupe (billing/service.py)": (
        "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = 'no-such-ref' "
        "AND reason = 'usage' LIMIT 1"
    ),
    "duplicate groups (scripts/reconcile_credit_ledger.py)": (
        "SELECT ref, reason, array_agg(id ORDER BY occurred_at, id) "
        "FROM credit_ledger WHERE tenant_id = :tid AND ref IS NOT NULL "
        "GROUP BY ref, reason HAVING count(*) > 1"
    ),
    "_ref_exists (scripts/reconcile_credit_ledger.py)": (
        "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = 'no-such-ref' LIMIT 1"
    ),
    "FK enforcement shape (organizations ON DELETE RESTRICT)": (
        "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid FOR KEY SHARE"
    ),
}


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every node in an EXPLAIN (FORMAT JSON) plan tree, flattened."""
    found = [plan]
    for child in plan.get("Plans", []):
        found.extend(_nodes(child))
    return found


async def _forced_plan(session: AsyncSession, sql: str, tenant_id: Any) -> list[dict[str, Any]]:
    """The plan the planner produces when a sequential scan costs `disable_cost`.

    PG16's docs are explicit that `enable_seqscan = off` DISCOURAGES rather than
    forbids, which is what makes it a probe rather than a lie: a Seq Scan still there
    after being priced at 1e10 is a Seq Scan the planner had no alternative to.
    """
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    raw = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), {"tid": tenant_id})).scalar()
    payload = raw if isinstance(raw, list) else json.loads(str(raw))
    return _nodes(payload[0]["Plan"])


async def test_the_prefix_index_is_gone_from_the_database() -> None:
    """Step two of the two-step deprecation, on the live schema.

    Read from `pg_indexes` rather than from the migration file: what matters is the
    database an operator's queries hit, and a migration that was written but never
    applied is exactly the half-wired change this assertion exists to catch.
    """
    async with untenanted_session() as session:
        names = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'credit_ledger'")
                )
            ).all()
        }

    assert DROPPED_INDEX not in names, (
        f"{DROPPED_INDEX} is still on this database. It is a strict prefix of "
        f"{COMPOSITE_INDEX} and serves no query that index does not — on an append-only "
        "ledger that is a write cost paid on every entry, forever, with no read to pay "
        "it back (migration e7c3d10a9f52)."
    )
    assert COMPOSITE_INDEX in names, (
        f"{COMPOSITE_INDEX} is what makes dropping the prefix safe. Without it "
        "`tenant_id` is not indexed at all and every wallet read is a table scan."
    )


async def test_the_composite_still_leads_with_tenant_id() -> None:
    """The whole argument for redundancy in one assertion.

    A btree serves any predicate on a PREFIX of its key list, so "the single-column
    index adds nothing" is true precisely while some other index's FIRST key is
    `tenant_id`. Asserted on the catalog's key order, not on the index's name or its
    definition string, so a future index that carries the property in a different shape
    still passes.
    """
    async with untenanted_session() as session:
        first_keys = (
            await session.execute(
                text(
                    "SELECT i.relname, a.attname FROM pg_index ix "
                    "JOIN pg_class i ON i.oid = ix.indexrelid "
                    "JOIN pg_class c ON c.oid = ix.indrelid "
                    "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ix.indkey[0] "
                    "WHERE c.relname = 'credit_ledger'"
                )
            )
        ).all()

    leading = {name for name, column in first_keys if column == "tenant_id"}
    assert leading, (
        "no index on credit_ledger leads with tenant_id — dropping the single-column "
        "index left the column unindexed, which is a table scan on the pre-dispatch "
        f"balance read and on every FK check. Indexes seen: {first_keys}"
    )


def test_the_model_no_longer_asks_for_the_dropped_index() -> None:
    """The half a SQL-only drop would have missed.

    `index=True` on a `mapped_column` is a standing request: autogenerate compares the
    model to the database and helpfully re-creates whatever the model declares. Leaving
    it there would have the NEXT migration resurrect the index this one removed, which
    is worse than never dropping it — the redundancy would come back silently, in an
    unrelated revision, with no docstring explaining it.
    """
    single_column_tenant_indexes = [
        index.name
        for index in CreditLedgerEntry.__table__.indexes
        if [column.name for column in index.columns] == ["tenant_id"]
        and len(index.expressions) == 1
    ]
    assert not single_column_tenant_indexes, (
        "the ORM still declares a single-column index on credit_ledger.tenant_id "
        f"({single_column_tenant_indexes}): the composite in __table_args__ already "
        "covers the column, and autogenerate will recreate this one at the next revision"
    )


async def test_every_ledger_query_still_reaches_an_index_on_a_long_ledger() -> None:
    """The regression the drop could actually cause, measured on a real ledger.

    Each of the seven statements the repo issues against `credit_ledger` — the wallet
    balance read on the pre-dispatch path, the credits panel, both idempotency dedupes,
    both reconciler lookups, and the shape of the foreign-key enforcement check — is
    planned with sequential scans priced at `disable_cost`. A Seq Scan that survives
    that is a query with no index available to it, which is precisely what removing an
    index can break and is a verdict independent of how many rows this database happens
    to hold.

    The ledger is 2000 entries so the plans are taken against a real ordering rather
    than a single row, and the transaction is abandoned (hard rule 4 — see the module
    docstring).
    """
    tenant_id = uuid7()
    offenders: dict[str, list[str]] = {}

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Index prune clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"idx-prune-{tenant_id.hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) SELECT gen_random_uuid(), :tid, 1.0000, 'topup', "
                "NULL, g, now() - make_interval(secs => g), now() "
                "FROM generate_series(1, :n) g"
            ),
            {"tid": tenant_id, "n": LEDGER_ENTRIES},
        )

        for caller, sql in LEDGER_QUERIES.items():
            nodes = await _forced_plan(session, sql, tenant_id)
            seq_scans = [
                node["Node Type"]
                for node in nodes
                if node.get("Relation Name") == "credit_ledger"
                and "Seq Scan" in str(node.get("Node Type"))
            ]
            if seq_scans:
                offenders[caller] = seq_scans

        await session.rollback()

    assert not offenders, (
        "these credit_ledger queries have no index available to them with sequential "
        f"scans priced at disable_cost: {offenders}. Dropping {DROPPED_INDEX} left a "
        "surface without a plan — restore it (downgrade e7c3d10a9f52) or index the "
        "predicate that lost its index."
    )

"""The five indexes `c9e2a7b41d63` adds, pinned by the plans that bought them (D-205).

Every one of these was chosen from an `EXPLAIN (ANALYZE, BUFFERS)` on a database seeded to
86,013 leads / 72,000 calls / 360,000 usage_events; the numbers are in the migration and in
`docs/evidence/deepdive-dbscale.md`. This file asserts the two properties those numbers
depend on, at a size no fixture has to reach:

  1. the index is ON THIS DATABASE — a migration written and not applied is exactly the
     half-wired change a measurement in a docstring cannot catch; and
  2. the access path exists, probed the way `credit_ledger_index_prune_test.py` probes:
     `enable_seqscan = off` DISCOURAGES a sequential scan rather than forbidding it
     (PG16), so a plan that still names the index is a plan the planner could produce.

FOR THE TWO ORDERED READS the probe also turns `enable_sort` off and asserts NO `Sort`
node survives. That is the assertion that cannot pass by accident: producing
`ORDER BY … LIMIT n` without a sort requires an index whose key order IS that order, so
the test is red the moment the index is dropped, declared with the wrong direction, or
declared without `NULLS LAST` where the query asks for it — which is the specific mistake
`ix_calls_tenant_started` exists to avoid (`DESC` defaults to `NULLS FIRST`).

WHERE A PLAN PROBE WOULD BE THE WRONG TEST, it is not used. Two of the five indexes are
chosen over a competing one on VOLUME — a fixture tenant with a handful of rows makes the
narrower `ix_*_tenant_id` the correct choice, so asserting a plan there would pin the cost
model instead of the schema. Those are asserted on the catalog, through the same
`pg_index.indkey[0]` census that counted the deficit in the first place, and the billing
month is asserted on the PREDICATE's shape plus its boundary behaviour.

CONCURRENCY: every test mints its own organization and asserts nothing about global
counts, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.plans import ist_month_window
from apps.api.billing.service import _IST_MONTH_WINDOW
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: index -> the table it is on. Read from `pg_indexes`, which is the database an
#: operator's queries actually hit.
INDEXES: dict[str, str] = {
    "ix_usage_events_call_id": "usage_events",
    "ix_usage_events_tenant_occurred": "usage_events",
    "ix_leads_tenant_recent": "leads",
    "ix_calls_tenant_started": "calls",
    "ix_campaign_contacts_last_call_id": "campaign_contacts",
}


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    found = [plan]
    for child in plan.get("Plans", []):
        found.extend(_nodes(child))
    return found


async def _plan(
    session: AsyncSession, sql: str, params: dict[str, Any], *, no_sort: bool = False
) -> list[dict[str, Any]]:
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    if no_sort:
        # Same shape of probe: `enable_sort = off` prices a sort at `disable_cost`, so a
        # Sort that survives is one the planner had no index path to avoid.
        await session.execute(text("SET LOCAL enable_sort = off"))
    raw = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), params)).scalar()
    payload = raw if isinstance(raw, list) else json.loads(str(raw))
    return _nodes(payload[0]["Plan"])


def _index_names(nodes: list[dict[str, Any]]) -> set[str]:
    return {str(n["Index Name"]) for n in nodes if "Index Name" in n}


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Index Probe",
        slug=f"idx-probe-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


@pytest.mark.parametrize(("index", "table"), sorted(INDEXES.items()))
async def test_the_index_is_on_this_database(index: str, table: str) -> None:
    async with untenanted_session() as session:
        names = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": table}
                )
            ).all()
        }
    assert index in names, (
        f"{index} is not on this database. Migration c9e2a7b41d63 creates it; a measurement "
        "in a docstring proves nothing about a schema that never got it."
    )


async def test_the_leads_page_orders_without_sorting() -> None:
    """`crm.service.list_leads_page`'s row query, key for key.

    Before `ix_leads_tenant_recent` this was a top-N heapsort of every lead the tenant
    has (28.5 ms / 1,668 buffers at 50,001 rows), and the CSV export's larger LIMIT
    spilled the sort to disk. Neither is visible from the SQL, which is why the ordering
    is asserted against the plan rather than trusted.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        nodes = await _plan(
            session,
            "SELECT l.id FROM leads l WHERE l.deleted_at IS NULL "
            "ORDER BY l.updated_at DESC, l.id DESC LIMIT 50",
            {},
            no_sort=True,
        )
    assert "ix_leads_tenant_recent" in _index_names(nodes)
    assert not [n for n in nodes if n["Node Type"] == "Sort"], (
        "the leads page still sorts: the index is not serving (tenant_id, updated_at DESC, "
        "id DESC), which is the ordering `list_leads_page` and the CSV export both take"
    )


async def test_the_calls_page_orders_without_sorting_including_nulls_last() -> None:
    """`crm.service.list_calls`, whose ordering is `started_at DESC NULLS LAST, id DESC`.

    The NULLS clause is the trap: `DESC` alone means `NULLS FIRST`, so an index declared
    without `NULLS LAST` is a correct index for a different ordering and the sort comes
    back. Red if the index is ever redeclared the obvious way.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        nodes = await _plan(
            session,
            "SELECT c.id FROM calls c ORDER BY c.started_at DESC NULLS LAST, c.id DESC LIMIT 50",
            {},
            no_sort=True,
        )
    assert "ix_calls_tenant_started" in _index_names(nodes)
    assert not [n for n in nodes if n["Node Type"] == "Sort"], (
        "the calls page still sorts — check that ix_calls_tenant_started declares "
        "started_at DESC NULLS LAST and not a bare DESC"
    )


#: The census that produced this pass's finding, expressed as a test: a foreign-key CHILD
#: column with no index LEADING with it. `pg_index.indkey[0]` is the whole discriminator —
#: a btree serves a predicate on a prefix of its key list and on nothing else, so
#: `uq_usage_events_tenant_call_unit (tenant_id, call_id, …)` does not serve
#: `call_id = $1` however much it mentions the column.
_UNINDEXED_FK_CENSUS = """
WITH fk AS (
  SELECT c.conrelid, c.conkey, cl.relname AS child_table
  FROM pg_constraint c
  JOIN pg_class cl ON cl.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = cl.relnamespace
  WHERE c.contype = 'f' AND n.nspname = 'public'
)
SELECT fk.child_table || '.' || (
         SELECT string_agg(a.attname, ',' ORDER BY x.ord)
         FROM unnest(fk.conkey) WITH ORDINALITY AS x(attnum, ord)
         JOIN pg_attribute a ON a.attrelid = fk.conrelid AND a.attnum = x.attnum)
FROM fk
WHERE NOT EXISTS (
  SELECT 1 FROM pg_index i
  WHERE i.indrelid = fk.conrelid AND i.indisvalid
    AND (SELECT array_agg(k ORDER BY o)
           FROM unnest(string_to_array(i.indkey::text, ' ')::smallint[]) WITH ORDINALITY AS t(k, o)
          WHERE o <= array_length(fk.conkey, 1)) = fk.conkey
)
"""

#: The child columns this pass took OUT of that census, and the reason each was worth an
#: index. Everything else it leaves in is argued in `docs/evidence/deepdive-dbscale.md` —
#: this list is deliberately not "all of them".
FK_COLUMNS_NOW_INDEXED: dict[str, str] = {
    "usage_events.call_id": (
        "the post-call metering guard and _pipeline_settled's EXISTS, per completed call "
        "and per poller tick — 25.8 ms / 3,617 buffers against 225,000 rows without it"
    ),
    "campaign_contacts.last_call_id": (
        "campaign_dispatch._settle_contact, whose docstring promises one indexed lookup — "
        "4.7 ms / 650 buffers over 29,520 contacts without it"
    ),
}


@pytest.mark.parametrize("column", sorted(FK_COLUMNS_NOW_INDEXED))
async def test_the_foreign_key_child_column_now_leads_an_index(column: str) -> None:
    """Asserted on the CATALOG rather than on a plan, and that is the stronger statement.

    A plan probe on a fixture-sized table measures the cost model, not the schema: with
    two candidate indexes and no rows, either can win. `indkey[0]` is the property the
    planner's choice depends on and it is true or false regardless of volume — it is also
    the exact query that counted 34 such columns at the previous revision.
    """
    async with untenanted_session() as session:
        remaining = {
            str(row[0]) for row in (await session.execute(text(_UNINDEXED_FK_CENSUS))).all()
        }
    assert column not in remaining, (
        f"{column} has no index leading with it, so {FK_COLUMNS_NOW_INDEXED[column]}. "
        "Migration c9e2a7b41d63."
    )


def test_the_billing_month_predicate_is_a_range_a_btree_can_use() -> None:
    """`billing/service._IST_MONTH_WINDOW` — the rewrite this index exists to serve.

    ASSERTED ON THE PREDICATE, NOT ON A PLAN, and the reason is worth recording because it
    is the limit of plan probes generally. A fixture tenant has a handful of `usage_events`
    rows, so the planner's choice between `ix_usage_events_tenant_id` and
    `ix_usage_events_tenant_occurred` is decided by index SIZE, and the narrower one wins —
    correctly. The measured win (84.0 ms / 3,829 buffers rendered vs 2.2 ms / 76 as a
    range, on a tenant with 225,000 rows) is a fact about volume no fixture reaches, so a
    plan assertion here would pin the cost model rather than the change.

    What IS invariant is the SHAPE: `to_char(occurred_at AT TIME ZONE …, 'YYYY-MM') = :month`
    is STABLE, so PostgreSQL will use it neither as an index condition nor as an index
    EXPRESSION — no index can ever serve it. A half-open comparison against the column can
    be both. Red the moment the predicate goes back to a rendered string.
    """
    assert "to_char" not in _IST_MONTH_WINDOW, (
        "the billing month is a rendered string again: `to_char` is STABLE, so this "
        "predicate cannot be an index condition and cannot be an index expression either — "
        "every money rollup goes back to reading the tenant's whole metering history"
    )
    assert "occurred_at >=" in _IST_MONTH_WINDOW and "occurred_at <" in _IST_MONTH_WINDOW, (
        "the month must be a half-open comparison against the COLUMN for a btree to use it"
    )


async def test_the_month_window_selects_the_same_rows_the_rendered_month_did() -> None:
    """The equivalence the rewrite is only allowed if it keeps (D-186's boundary case).

    A call stamped 23:00 IST on the last day of August is an AUGUST call, and its
    `occurred_at` is 17:30 UTC on the 31st — the instant a UTC-month predicate files in
    August by luck and a `+ interval '5:30'` predicate files in September by bug. Both
    rows below are inserted, and the August window must return exactly the first.
    """
    tenant_id = await _tenant()
    august_evening = "2026-08-31T17:30:00+00:00"  # 23:00 IST, 31 Aug
    september_morning = "2026-08-31T19:00:00+00:00"  # 00:30 IST, 1 Sep
    async with tenant_session(tenant_id) as session:
        for occurred, qty in ((august_evening, 11), (september_morning, 22)):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "occurred_at, created_at) VALUES (:id, :tid, NULL, 'other', :qty, "
                    "CAST(:occurred AS timestamptz), now())"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "qty": qty, "occurred": occurred},
            )
        start, end = ist_month_window("2026-08")
        total = (
            await session.execute(
                text(
                    "SELECT COALESCE(sum(qty), 0) FROM usage_events WHERE tenant_id = :tid "
                    "AND unit_type = 'other' "
                    "AND occurred_at >= :month_from AND occurred_at < :month_to"
                ),
                {"tid": tenant_id, "month_from": start, "month_to": end},
            )
        ).scalar()
    assert int(total or 0) == 11, (
        "the IST month window is not the IST month: 23:00 IST on the 31st belongs to "
        "August and 00:30 IST on the 1st does not"
    )


async def test_the_partial_predicates_are_the_ones_the_queries_carry() -> None:
    """A partial index is only an index for the rows its predicate admits, so the
    predicate is part of the contract and not a size optimisation somebody may relax.

    `ix_leads_tenant_recent` is `WHERE deleted_at IS NULL` because `_lead_scope` opens
    with that clause unconditionally; the two `call_id`/`last_call_id` ones are
    `IS NOT NULL` because every probe binds a real id — and because that is what lets
    them serve the referential-integrity check too (`col = $1` under a strict operator
    proves `col IS NOT NULL`).
    """
    expected = {
        "ix_leads_tenant_recent": "deleted_at IS NULL",
        "ix_usage_events_call_id": "call_id IS NOT NULL",
        "ix_campaign_contacts_last_call_id": "last_call_id IS NOT NULL",
    }
    async with untenanted_session() as session:
        defs = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(:names)"
                    ),
                    {"names": list(expected)},
                )
            ).all()
        }
    for name, predicate in expected.items():
        assert name in defs, f"{name} is missing"
        assert f"WHERE ({predicate})" in defs[name], (
            f"{name} no longer carries `WHERE {predicate}` — it is now an index for a "
            "different set of rows than the queries that were measured against it"
        )

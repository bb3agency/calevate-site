"""The three structural gaps closed by migrations d3b71c9a5e08, a6f2e84b1d37 and
7c04ab5f9e26 — written as the PROPERTIES the schema now guarantees.

Each of these was previously guaranteed by a convention: an ARQ job id keyed on the
call, a per-tenant advisory lock, a row lock held across a dispatcher's whole
transaction. Conventions hold until the next caller forgets one, or until a process is
killed between two statements. What is asserted below is the part a forgetful caller
and a SIGKILL cannot undo.

House rules, inherited from `tests/reliability_audit_test.py` because they are the same
database:

- **Run-unique rows.** Other suites hammer this Postgres and none of these tables are
  truncated between runs. Every row written here carries `RUN`, and every assertion
  counts only rows this module wrote.
- **Backdated outbox rows, retired immediately.** `claim_outbox_batch` is oldest-first
  over the WHOLE table, so a claim test can only be deterministic if its rows are at the
  front of the queue. They are dated far enough back to beat every other suite's, and
  deleted as soon as the test that needs them is done — a leftover backdated row would
  sit at the head of somebody else's dispatcher tick.
- **A killed worker is simulated by abandoning a transaction**, never by calling a
  "fail" helper. The bug was that a rollback erased the evidence of an attempt; a test
  that politely reports failure cannot see it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, NamedTuple

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability import service as rel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

RUN = uuid.uuid4().hex[:12]


def marker(name: str) -> str:
    return f"schema-hardening-{name}-{RUN}"


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> Any:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE payload->>'marker' LIKE :m"),
            {"m": f"%{RUN}"},
        )


# ------------------------------------------------------------------- fixtures


async def _make_org() -> uuid.UUID:
    """Org creation runs under the NEW org's own GUC — FORCE RLS derives WITH CHECK from
    USING, so inserting a tenant root requires app.tenant_id = the new org id."""
    org_id = uuid7()
    async with tenant_session(org_id) as s:
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Hardening', :slug, 'active', now(), now())"
            ),
            {"id": org_id, "slug": f"sh-{org_id.hex[:12]}"},
        )
    return org_id


async def _make_call(tenant_id: uuid.UUID) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as s:
        agent_id = uuid7()
        await s.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "created_at, updated_at) VALUES (:id, :tid, 'a', 'inbound', 'I am an AI', "
                "now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        await s.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ref, 'inbound', 'completed', "
                "now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ref": f"eng-{call_id.hex[:16]}"},
        )
    return call_id


_INSERT_EXTRACTION = (
    "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, valid, "
    "created_at, updated_at) VALUES (:id, :tid, :cid, 1, CAST(:data AS jsonb), true, "
    "now(), now())"
)


async def _seed_outbox(name: str, *, count: int = 1) -> list[uuid.UUID]:
    """Outbox rows dated a year back, so the oldest-first claim reaches OURS and — just
    as important — a small `limit` never reaches anybody else's."""
    ids: list[uuid.UUID] = []
    async with untenanted_session() as session:
        for _ in range(count):
            mid = uuid7()
            ids.append(mid)
            await session.execute(
                text(
                    "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                    "created_at, updated_at) VALUES (:id, 'default', 'notify_hot_lead', "
                    "CAST(:p AS jsonb), 'pending', 0, now() - interval '400 days', now())"
                ),
                {"id": mid, "p": json.dumps({"marker": marker(name)})},
            )
    return ids


async def _outbox_row(message_id: uuid.UUID) -> tuple[str, int, bool]:
    """(status, attempt_count, is_leased_now)."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempt_count, (locked_until IS NOT NULL "
                    "AND locked_until > now()) FROM outbox_messages WHERE id = :id"
                ),
                {"id": message_id},
            )
        ).first()
    assert row is not None, "the row this test seeded has gone missing"
    return str(row[0]), int(row[1]), bool(row[2])


async def _retire(*ids: uuid.UUID) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = ANY(:ids)"), {"ids": list(ids)}
        )


# ===================================================== 1. one call, one extraction


async def test_a_call_cannot_carry_two_extractions() -> None:
    """The invariant every reader already assumes (`ORDER BY created_at DESC LIMIT 1` in
    the CRM detail, "the" extraction in the retention eraser) is now a database fact.

    Pre-migration this test passes trivially in the wrong direction: both inserts
    succeed and the call has two answers.
    """
    tenant_id = await _make_org()
    call_id = await _make_call(tenant_id)
    params = {"tid": tenant_id, "cid": call_id, "data": json.dumps({"budget": 50})}

    async with tenant_session(tenant_id) as s:
        await s.execute(text(_INSERT_EXTRACTION), {**params, "id": uuid7()})

    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as s:
            await s.execute(text(_INSERT_EXTRACTION), {**params, "id": uuid7()})

    async with tenant_session(tenant_id) as s:
        count = (
            await s.execute(
                text("SELECT count(*) FROM call_extractions WHERE call_id = :cid"),
                {"cid": call_id},
            )
        ).scalar()
    assert count == 1, f"one call, one extraction — found {count}"


async def test_two_pipeline_runs_racing_on_one_call_cannot_both_insert() -> None:
    """The case the update-or-insert could not close, and the reason the constraint had
    to exist.

    Both runs read "no row for this call" — genuinely concurrently, with overlapping
    transactions — and both then insert. Without the unique key both commit and the CRM
    has two extractions with no way to say which one it is reading. With it, the second
    blocks on the first's uncommitted key, and on the commit it is refused.
    """
    tenant_id = await _make_org()
    call_id = await _make_call(tenant_id)
    both_looked = asyncio.Event()
    lookups = 0

    async def pipeline_run(first: bool) -> str:
        nonlocal lookups
        async with tenant_session(tenant_id) as s:
            existing = (
                await s.execute(
                    text(
                        "SELECT 1 FROM call_extractions WHERE call_id = :cid AND tenant_id = :tid"
                    ),
                    {"cid": call_id, "tid": tenant_id},
                )
            ).first()
            assert existing is None, "both runs must genuinely see an empty table"
            lookups += 1
            if lookups == 2:
                both_looked.set()
            else:
                await asyncio.wait_for(both_looked.wait(), timeout=5)
            if not first:
                # Let the other run reach its INSERT first, so the loser is the one that
                # waits on the winner's key rather than the other way round.
                await asyncio.sleep(0.1)
            try:
                await s.execute(
                    text(_INSERT_EXTRACTION),
                    {
                        "id": uuid7(),
                        "tid": tenant_id,
                        "cid": call_id,
                        "data": json.dumps({"run": "first" if first else "second"}),
                    },
                )
            except IntegrityError:
                return "refused"
        return "inserted"

    outcomes = await asyncio.gather(pipeline_run(True), pipeline_run(False), return_exceptions=True)
    landed = [o for o in outcomes if o == "inserted"]

    async with tenant_session(tenant_id) as s:
        count = (
            await s.execute(
                text("SELECT count(*) FROM call_extractions WHERE call_id = :cid"),
                {"cid": call_id},
            )
        ).scalar()

    assert count == 1, f"two racing pipeline runs filed {count} extractions for one call"
    assert len(landed) == 1, f"exactly one run may win, outcomes were {outcomes}"


async def test_the_extraction_key_leads_with_the_tenant_so_it_cannot_leak() -> None:
    """A unique violation is one of the few ways a row your RLS policy hides can
    announce that it exists. Leading the key with `tenant_id` means the only conflict
    reachable from a tenant session is with that tenant's own row — and the cross-tenant
    zero-rows guarantee (hard rule 1) still holds over the table the index sits on.
    """
    tenant_a = await _make_org()
    tenant_b = await _make_org()
    call_a = await _make_call(tenant_a)
    call_b = await _make_call(tenant_b)

    for tid, cid in ((tenant_a, call_a), (tenant_b, call_b)):
        async with tenant_session(tid) as s:
            await s.execute(
                text(_INSERT_EXTRACTION),
                {"id": uuid7(), "tid": tid, "cid": cid, "data": json.dumps({})},
            )

    async with tenant_session(tenant_a) as s:
        visible = (
            await s.execute(
                text("SELECT count(*) FROM call_extractions WHERE call_id = :cid"), {"cid": call_b}
            )
        ).scalar()
    assert visible == 0, "tenant A must see zero rows of tenant B's extractions"

    # B's own insert is unaffected by A's row existing: the index is per tenant.
    async with tenant_session(tenant_b) as s:
        own = (
            await s.execute(
                text("SELECT count(*) FROM call_extractions WHERE tenant_id = :tid"),
                {"tid": tenant_b},
            )
        ).scalar()
    assert own == 1

    async with untenanted_session() as s:
        indexed = (
            await s.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_call_extractions_tenant_id_call_id'"
                )
            )
        ).scalar()
    assert indexed is not None, "the constraint must exist"
    assert "(tenant_id, call_id)" in str(indexed), f"tenant_id must LEAD the key, got {indexed!r}"


# =============================================== 2. the credit balance read and its index


# The read this section is about, character for character as `apps/api/billing/
# service.py::_newest_balance` issues it. If that ORDER BY ever changes, this string has
# to change with it — and the test below then measures the NEW read against the index,
# which is the only comparison worth making.
BALANCE_READ = (
    "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
    "ORDER BY occurred_at DESC, id DESC LIMIT 1"
)

# Two ledgers, three orders of magnitude apart: the measurement is the DIFFERENCE between
# them, so `LONG_LEDGER` only has to be big enough that "the plan read the whole ledger"
# and "the plan read one row" can never be mistaken for each other. Nothing here is
# committed (see `_measure_balance_read`), so the size costs a few milliseconds per run
# rather than a permanently fatter shared table.
LONG_LEDGER = 2000
SHORT_LEDGER = 2

# The two entries that share one `occurred_at`. Balances far above any generated row's,
# so the number the read returns names WHICH entry it walked to.
TIE_LOSER = Decimal("90001.0000")
TIE_WINNER = Decimal("90002.0000")


def _plan_nodes(node: dict[str, Any], depth: int = 0) -> list[dict[str, Any]]:
    """Every node of an EXPLAIN (FORMAT JSON) plan tree, parents before children.

    FORMAT JSON rather than the default text because the assertions below are about node
    TYPES and ACTUAL ROW COUNTS, and reading those out of indented prose with `in` is how
    a plan assertion ends up matching the word "Sort" inside `Sort Key:` — or missing an
    `Incremental Sort` because the string it was looking for was an index name.
    """
    nodes = [{**node, "_depth": depth}]
    for child in node.get("Plans", []):
        nodes.extend(_plan_nodes(child, depth + 1))
    return nodes


def _plan_summary(nodes: list[dict[str, Any]]) -> str:
    """The plan as a few readable lines — what ran, and how many rows it touched.

    A failure here is read by a human deciding whether an index regressed, and
    `json.dumps` of an ANALYZE/BUFFERS tree buries that in 200 lines of block counters.
    """
    lines = []
    for n in nodes:
        via = f" using {n['Index Name']}" if n.get("Index Name") else ""
        on = f" on {n['Relation Name']}" if n.get("Relation Name") else ""
        lines.append(
            f"{'  ' * int(n['_depth'])}-> {n['Node Type']}{via}{on} "
            f"(actual rows={n.get('Actual Rows')}, cost={n.get('Total Cost')}, "
            f"buffers={n.get('Shared Hit Blocks', 0) + n.get('Shared Read Blocks', 0)})"
        )
    return "\n".join(lines)


async def _explain_balance_read(
    session: AsyncSession, tenant_id: uuid.UUID, *, forced: bool = False
) -> tuple[list[dict[str, Any]], str]:
    """Run the balance read under EXPLAIN (ANALYZE) and return (plan nodes, plan text).

    `forced=True` first tells the planner that sorting and seq-scanning are unattractive
    (`enable_sort`/`enable_seqscan` are DISCOURAGEMENTS, not prohibitions — PostgreSQL
    "cannot suppress explicit sorts entirely", it only avoids them where another method
    exists, https://www.postgresql.org/docs/16/runtime-config-query.html). That is
    precisely what makes them a usable probe: if a Sort node SURVIVES being made
    astronomically expensive, no index can carry this ordering — which is the regression
    this section exists to catch, and it reads the same on any data volume.

    `jit = off` because PG16 prices a discouraged node at disable_cost = 1e10, and a plan
    costed in the billions trips the JIT thresholds; the failure case would otherwise
    spend seconds compiling the plan it is about to fail on.
    """
    if forced:
        await session.execute(text("SET LOCAL jit = off"))
        await session.execute(text("SET LOCAL enable_sort = off"))
        await session.execute(text("SET LOCAL enable_seqscan = off"))
    root = (
        await session.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {BALANCE_READ}"), {"tid": tenant_id}
        )
    ).scalar()
    assert root, "EXPLAIN returned nothing"
    nodes = _plan_nodes(root[0]["Plan"])
    return nodes, _plan_summary(nodes)


def _rows_examined(nodes: list[dict[str, Any]], plan_text: str) -> int:
    """Rows the plan actually pulled OFF `credit_ledger` — the number the index is
    supposed to hold at 1 no matter how long the ledger is."""
    scans = [n for n in nodes if n.get("Relation Name") == "credit_ledger"]
    assert len(scans) == 1, f"expected exactly one scan of credit_ledger:\n{plan_text}"
    return int(scans[0]["Actual Rows"])


class BalanceRead(NamedTuple):
    """One tenant's balance read, measured rather than described."""

    entries: int
    rows_examined: int
    sort_nodes: list[str]
    answer: Decimal | None
    forced_plan: str
    planners_own_choice: str


async def _measure_balance_read(entries: int) -> BalanceRead:
    """Build a tenant with `entries` ledger rows, read its balance under EXPLAIN, and
    ABANDON the whole thing.

    The ledger is never committed. Hard rule 4 forbids UPDATE and DELETE on
    `credit_ledger` — the `credit_ledger_append_only` trigger enforces it at the database
    — so a test that committed thousands of rows on every run would fatten the shared
    database forever with no way to clean up after itself. A rollback is not a deletion:
    these rows were never facts. Everything the measurement needs (the index, the
    planner, the executor) is fully live inside the transaction that wrote them.
    """
    tenant_id = uuid7()
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Ledger growth', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"sh-grow-{tenant_id.hex[:12]}"},
        )
        await s.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) SELECT gen_random_uuid(), :tid, 1.0000, 'topup', "
                "NULL, g, now() - make_interval(secs => g), now() "
                "FROM generate_series(1, :n) g"
            ),
            {"tid": tenant_id, "n": entries},
        )
        # Two entries sharing one `occurred_at`, newest last: `id DESC` is then the only
        # thing that can say which of them the balance is. uuid7 ids ascend with time, so
        # the second insert is both the later write and the greater key.
        for balance in (TIE_LOSER, TIE_WINNER):
            await s.execute(
                text(
                    "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, "
                    "balance_after, occurred_at, created_at) VALUES (:id, :tid, 1.0000, "
                    "'topup', NULL, :bal, now(), now())"
                ),
                {"id": uuid7(), "tid": tenant_id, "bal": balance},
            )

        # Unforced FIRST: `SET LOCAL` lasts the rest of the transaction, so once the
        # planner has been told sorting is expensive there is no way back to its own
        # opinion within this ledger.
        _, unforced_text = await _explain_balance_read(s, tenant_id)
        forced, forced_text = await _explain_balance_read(s, tenant_id, forced=True)
        answer = (await s.execute(text(BALANCE_READ), {"tid": tenant_id})).scalar()
        await s.rollback()

    return BalanceRead(
        entries=entries + 2,
        rows_examined=_rows_examined(forced, forced_text),
        sort_nodes=[n["Node Type"] for n in forced if "Sort" in str(n["Node Type"])],
        answer=Decimal(answer) if answer is not None else None,
        forced_plan=forced_text,
        planners_own_choice=unforced_text,
    )


async def test_the_balance_read_does_not_get_slower_as_the_ledger_grows() -> None:
    """THE property `ix_credit_ledger_tenant_recent` was added for: reading a wallet
    balance costs the same on a client's first day and on their thousandth.

    `_newest_balance` is on the pre-dispatch path of every top-up and every per-call
    charge. With only `ix_credit_ledger_tenant_id` the plan finds a tenant's rows and
    then sorts ALL of them to answer LIMIT 1 — a full sort of a ledger history to read
    one number. The index whose keys are `(tenant_id, occurred_at DESC, id DESC)` turns
    that into a walk that stops at the first row.

    Measured, not named. The earlier version of this test asserted that the string
    `ix_credit_ledger_tenant_recent` appeared in an `EXPLAIN` of a RANDOM tenant id with
    no rows, and it failed whenever the planner priced the two indexes within a hair of
    each other (8.17 vs 8.18) — which it does exactly when it estimates one row, because
    sorting one row IS free and the choice genuinely does not matter there. A test that
    fails on a plan that is not slow, for a tenant that does not exist, teaches people to
    ignore it. So this asserts what a client would feel:

    - **no Sort node survives** `enable_sort = off` — i.e. an index really does carry
      `occurred_at DESC, id DESC` for a tenant. Node TYPE, not index name: `Incremental
      Sort` (what an index missing the `id DESC` tail produces) counts as a sort, and the
      day this index is replaced by a better one the property is still met.
    - **rows examined stays at 1** on a ledger of 2000 entries, and is the SAME number as
      on a ledger of four. That is "does not get slower as the ledger grows" written as an
      observation rather than a hope, and it is what actually failed in the degenerate
      case: with the index dropped, the same read pulled all 2002 rows to return one.
    - **the newest entry is the one returned**, including when two entries share an
      `occurred_at` — the `id DESC` tail is what makes "newest" a total order, and an
      index that dropped it would still pass a Sort-node check on distinct timestamps.

    The planner's UNforced choice is captured and reported, never asserted: on a table
    whose statistics say one row per tenant (a fresh test database, or any database the
    app role cannot ANALYZE — PG16 restricts that to the owner) preferring a sort is
    correct, and on a ledger with real statistics the same planner picks the index by a
    factor of 120 (4.19 vs 504.51 on an 18k-row ledger, measured). Asserting on it would
    be asserting on the statistics, not on the schema.

    Nothing here is committed. The ledger is built inside one transaction and the
    transaction is ABANDONED — hard rule 4 forbids UPDATE and DELETE on `credit_ledger`
    (the `credit_ledger_append_only` trigger enforces it at the database), so a test that
    inserted 2000 committed rows on every run would grow the shared database forever with
    no way to clean up. A rollback is not a deletion: those rows were never facts.
    """
    grown = await _measure_balance_read(LONG_LEDGER)
    fresh = await _measure_balance_read(SHORT_LEDGER)

    assert not grown.sort_nodes, (
        "no index carries the balance read's ordering: with sorting priced at "
        f"disable_cost the plan STILL sorts ({grown.sort_nodes}) and pulled "
        f"{grown.rows_examined} rows off a {grown.entries}-entry ledger to return one "
        "number. Reading a wallet balance now costs the client's history, and it gets "
        f"worse every month they stay:\n{grown.forced_plan}"
    )
    assert grown.rows_examined == 1, (
        f"the balance read pulled {grown.rows_examined} rows off a {grown.entries}-entry "
        "ledger to return one — the index is not carrying the ordering to its first "
        f"row:\n{grown.forced_plan}"
    )
    assert grown.rows_examined == fresh.rows_examined, (
        f"a {grown.entries}-entry ledger costs {grown.rows_examined} rows and a "
        f"{fresh.entries}-entry one costs {fresh.rows_examined}: the read scales with a "
        f"client's history, which is the whole thing the index is for:\n{grown.forced_plan}"
    )
    assert grown.answer == TIE_WINNER, (
        "`newest` must be a TOTAL order: two entries share one occurred_at and the read "
        f"returned {grown.answer!r} rather than the entry with the greater id — the "
        "`id DESC` tail of the index (and of the ORDER BY) is what settles the tie"
    )
    # Reported, never asserted (see the docstring): the planner's own pick depends on
    # this table's statistics, which no test controls and the app role cannot refresh.
    assert grown.planners_own_choice, "EXPLAIN returned nothing"


async def test_the_credit_ledger_cannot_be_deduplicated_by_deletion() -> None:
    """Why the partial unique index on `(tenant_id, ref)` is NOT in migration
    a6f2e84b1d37 — the reason is this trigger, not an oversight.

    21 (tenant_id, ref) pairs on this database already violate that index. Every other
    table in this file could be cleaned before its constraint went on; `credit_ledger`
    cannot, because it is append-only (hard rule 4) and the database enforces it. The
    correction for a double credit is a compensating entry made by a person reading a
    bank statement, not a DELETE issued by a migration — so the index waits on that
    reconciliation rather than on schema work.
    """
    tenant_id = await _make_org()
    entry_id = uuid7()
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) VALUES (:id, :tid, 100.0000, 'topup', :ref, "
                "100.0000, clock_timestamp(), clock_timestamp())"
            ),
            {"id": entry_id, "tid": tenant_id, "ref": f"UTR-{RUN}"},
        )

    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as s:
            await s.execute(text("DELETE FROM credit_ledger WHERE id = :id"), {"id": entry_id})

    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as s:
            await s.execute(
                text("UPDATE credit_ledger SET delta = 0 WHERE id = :id"), {"id": entry_id}
            )

    async with tenant_session(tenant_id) as s:
        still_there = (
            await s.execute(
                text("SELECT count(*) FROM credit_ledger WHERE id = :id"), {"id": entry_id}
            )
        ).scalar()
    assert still_there == 1, "an append-only ledger keeps its rows, which is the whole point"


# ============================================ 3. an outbox claim survives its dispatcher


async def test_a_killed_dispatcher_does_not_reset_the_attempt_count() -> None:
    """THE property. `claim_outbox_batch`'s docstring promises that a message which
    keeps killing its worker walks to the DLQ instead of looping; before migration
    7c04ab5f9e26 it did the opposite.

    The death is simulated honestly: the claim is taken through the real function, and
    then the dispatcher's transaction is ABANDONED — rolled back with nothing reported,
    which is what a SIGKILL leaves behind. Nothing here calls `mark_outbox_failed`; a
    worker that was killed did not get to report anything, and a test that reports for
    it cannot see the bug.

    Pre-migration this fails on the first assertion: the bump lived in the transaction
    that was just rolled back, so the row is `pending` with `attempt_count = 0` again —
    forever, on every pass.
    """
    (message_id,) = await _seed_outbox("killed")

    async with untenanted_session() as session:
        batch = await rel.claim_outbox_batch(session, limit=1)
        assert [m.id for m in batch] == [message_id], (
            "the backdated row must be the one claimed — another suite has seeded an "
            f"even older row, got {[str(m.id) for m in batch]}"
        )
        assert batch[0].attempt_count == 1, "the claim reports the attempt it just recorded"
        # SIGKILL. The dispatcher never publishes, never reports, never commits.
        await session.rollback()

    status, attempts, leased = await _outbox_row(message_id)
    await _retire(message_id)
    assert attempts == 1, (
        "the attempt a killed dispatcher made must survive it — the row came back with "
        f"attempt_count={attempts}, which is a retry budget that resets forever"
    )
    assert status == "pending", f"an abandoned claim stays claimable, got {status!r}"
    assert leased, "and it stays LEASED until the lease lapses, so nobody else takes it meanwhile"


async def test_a_leased_message_is_not_handed_to_a_second_dispatcher() -> None:
    """The other half of the same change: the commit that makes the bump durable also
    drops the `FOR UPDATE` locks, so exclusivity has to be carried by the row itself.

    A second claim that runs after the first has committed must NOT see the message —
    and must see it again once the lease has lapsed, with the attempt count where the
    dead dispatcher left it.
    """
    (message_id,) = await _seed_outbox("leased")

    async with untenanted_session() as session:
        first = await rel.claim_outbox_batch(session, limit=1)
    assert [m.id for m in first] == [message_id], "sanity: our row is at the front"

    async with untenanted_session() as session:
        second = await rel.claim_outbox_batch(session, limit=1)
    assert message_id not in {m.id for m in second}, (
        "a committed claim must still exclude the next dispatcher — otherwise the "
        "durable bump bought exclusivity's death"
    )

    # Wall-clock, without sleeping for the lease: the holder died two minutes ago.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE outbox_messages SET locked_until = now() - interval '1 second' "
                "WHERE id = :id"
            ),
            {"id": message_id},
        )

    async with untenanted_session() as session:
        third = await rel.claim_outbox_batch(session, limit=1)
    mine = [m for m in third if m.id == message_id]
    status, attempts, _ = await _outbox_row(message_id)
    await _retire(message_id)

    assert mine, "a lapsed lease must return the message to the queue with no reaper involved"
    assert mine[0].attempt_count == 2, (
        f"the re-claim continues the budget rather than restarting it, got {mine[0].attempt_count}"
    )
    assert attempts == 2 and status == "pending"


async def test_a_message_that_keeps_killing_its_worker_reaches_the_dlq() -> None:
    """The end of the walk. `mark_outbox_failed` is the only other route to the DLQ and
    it is a route only a worker that SURVIVED can take, so a durable bump on its own
    would merely make the loop slower and the attempt count larger.

    Every pass here is a real claim followed by an abandoned transaction, and the lease
    is expired between passes exactly as wall-clock would. The budget must end.
    """
    (message_id,) = await _seed_outbox("poison")

    passes = 0
    for _ in range(rel.OUTBOX_MAX_ATTEMPTS * 3):
        async with untenanted_session() as session:
            batch = await rel.claim_outbox_batch(session, limit=1)
            claimed = [m for m in batch if m.id == message_id]
            await session.rollback()  # the worker dies mid-publish, again
        status, _, _ = await _outbox_row(message_id)
        if status != "pending":
            break
        if not claimed:
            # Only reachable if another suite jumped the queue; the lease expiry below
            # would then never apply to our row.
            raise AssertionError("our backdated row was not the one claimed")
        passes += 1
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE outbox_messages SET locked_until = now() - interval '1 second' "
                    "WHERE id = :id"
                ),
                {"id": message_id},
            )

    status, attempts, _ = await _outbox_row(message_id)
    await _retire(message_id)
    assert status == "failed", (
        f"a message that never survives a dispatcher must end in the DLQ, not loop — "
        f"still {status!r} after {passes} claims"
    )
    assert attempts >= rel.OUTBOX_MAX_ATTEMPTS, (
        f"and it must spend its whole budget getting there, spent {attempts}"
    )


async def test_reporting_an_outcome_releases_the_lease_immediately() -> None:
    """A retryable failure must not also cost the message its lease.

    `mark_outbox_failed` below the ceiling returns the row to `pending`; if it left
    `locked_until` in place, the next tick would skip it and every transient failure
    would become a two-minute stall. Same for a publish: a resolved message holding a
    lease would make `locked_until IS NOT NULL` mean nothing.
    """
    retried, published = await _seed_outbox("release", count=2)

    async with untenanted_session() as session:
        batch = await rel.claim_outbox_batch(session, limit=2)
        assert {m.id for m in batch} == {retried, published}, "sanity: both rows are ours"
        await rel.mark_outbox_failed(
            session, message_id=retried, error="the receiver blinked", attempt_count=1
        )
        await rel.mark_outbox_published(session, message_id=published, job_id="job-1")

    status, _, leased = await _outbox_row(retried)
    assert (status, leased) == ("pending", False), (
        f"a retryable failure returns the message to the queue NOW, got {status!r} leased={leased}"
    )
    status, _, leased = await _outbox_row(published)
    assert (status, leased) == ("published", False), (
        f"a published message holds no lease, got {status!r} leased={leased}"
    )

    # And the released one really is claimable again on the very next tick.
    async with untenanted_session() as session:
        again = await rel.claim_outbox_batch(session, limit=1)
    assert [m.id for m in again] == [retried], "released means claimable, not merely unlocked"
    await _retire(retried, published)


async def test_the_lease_is_shorter_than_the_generic_claim_lease() -> None:
    """One number per unit of work, and the outbox's unit is milliseconds long.

    `CLAIM_LEASE` is ten minutes because an idempotency holder can legitimately be an
    ARQ job running for five. An outbox claim hands one job to Redis; ten minutes of
    stall for a crashed dispatcher would be a self-inflicted outbox-lag breach.
    """
    assert rel.OUTBOX_CLAIM_LEASE < rel.CLAIM_LEASE
    assert timedelta(seconds=30) <= rel.OUTBOX_CLAIM_LEASE, (
        "and not so short that a merely slow dispatcher loses a claim it still holds"
    )

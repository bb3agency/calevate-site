"""The two engine route tables: reads are global, writes belong to the row's own tenant.

`engine_agent_routes` and `engine_kb_routes` are the two entries in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` that CARRY a `tenant_id` and are not policied on
it for reads — an engine webhook arrives with only a vendor agent id and no session, and
the KB orphan question ("which objects on this account does no tenant of ours claim") is
unaskable from a tenant session. Both exemptions are arguments about READING.

Until migration `b8e2d47f0c19` the write policy on both was
`tenant_id = <guc> OR <guc> IS NULL`, so a session with NO `app.tenant_id` could INSERT,
UPDATE or DELETE a row naming any tenant at all — measured as `calevate_app`
(NOSUPERUSER NOBYPASSRLS) on a migrated database, 10 Sep 2026: an untenanted
`INSERT INTO engine_agent_routes ... VALUES (<arbitrary tenant>, ...)` returned
`INSERT 0 1`. That is the table that decides WHICH AGENT AN INBOUND NUMBER REACHES, so the
worst of it is not a leak but a redirection: one `UPDATE ... SET tenant_id` sends a
client's inbound calls into another client's agent.

WHAT THIS FILE PINS, and why each half needs its own test:

  * the cross-tenant zero-rows property in the shape it can hold HERE. A SELECT is
    deliberately global (the exemption), so "zero rows" is about the write verbs: tenant
    B's session UPDATEs and DELETEs zero of tenant A's rows, and RE-TENANTING raises
    rather than silently succeeding, because `WITH CHECK` judges the row you are trying to
    leave behind;
  * the same three for an UNTENANTED session, which is the newly closed hole;
  * that the SWEEP STILL WORKS, which is the reason this was not a revert: the drift
    stamp is the one write that legitimately crosses no boundary and is still done from
    the row's own tenant, and its untenanted form now writes nothing;
  * that the READ is still global, because the sweeps' batch read and the inbound webhook
    resolution both depend on it and a narrowing there would look like a security fix
    while breaking every inbound call.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.agents.reconciliation import record_drift
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb.reconciliation import record_kb_drift
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

#: A vendor name no adapter answers to, so nothing else in the suite claims these rows:
#: every sweep, summary and dispatch query in the tree filters on `engine`.
ENGINE = "rls-probe"


class _Routes:
    """One route row per table, owned by `tenant`, addressed by `ref`."""

    def __init__(self, tenant: uuid.UUID, other: uuid.UUID, ref: str) -> None:
        self.tenant = tenant
        self.other = other
        self.ref = ref


@pytest.fixture
async def routes() -> AsyncIterator[_Routes]:
    """Two tenants and one route each table, written by the tenant that owns them.

    Synthetic tenant and agent ids, deliberately: neither table carries a foreign key to
    `organizations` or `agents` (they are the bridge FROM the vendor's namespace, and a
    route can outlive both), so what is under test — the policy — needs no fixture beyond
    a uuid. The rows are removed on the way out because the suite shares one database and
    a stray `active` route is a tenant every cross-tenant sweep would then visit.
    """
    holder = _Routes(uuid.uuid4(), uuid.uuid4(), f"rls-{uuid.uuid4().hex[:10]}")
    async with tenant_session(holder.tenant) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active) VALUES (:e, :r, :t, :a, true)"
            ),
            {"e": ENGINE, "r": holder.ref, "t": holder.tenant, "a": uuid.uuid4()},
        )
        await session.execute(
            text(
                "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, "
                "agent_id, source_id) VALUES (:e, :r, :t, :a, :s)"
            ),
            {
                "e": ENGINE,
                "r": holder.ref,
                "t": holder.tenant,
                "a": uuid.uuid4(),
                "s": uuid.uuid4(),
            },
        )
    yield holder
    async with tenant_session(holder.tenant) as session:
        await session.execute(
            text("DELETE FROM engine_kb_routes WHERE engine = :e AND engine_kb_ref = :r"),
            {"e": ENGINE, "r": holder.ref},
        )
        await session.execute(
            text("DELETE FROM engine_agent_routes WHERE engine = :e AND engine_agent_ref = :r"),
            {"e": ENGINE, "r": holder.ref},
        )


async def _route_row(table: str, key: str, ref: str) -> tuple[uuid.UUID, bool | None]:
    """(tenant_id, active) as an untenanted session sees it — the global read."""
    active = ", active" if table == "engine_agent_routes" else ", NULL"
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(f"SELECT tenant_id{active} FROM {table} WHERE engine = :e AND {key} = :r"),
                {"e": ENGINE, "r": ref},
            )
        ).first()
    assert row is not None, f"the fixture did not write a {table} row"
    return uuid.UUID(str(row[0])), row[1]


# --- 1. another tenant ---------------------------------------------------------


async def test_another_tenants_session_writes_zero_rows_on_either_route_table(
    routes: _Routes,
) -> None:
    """The cross-tenant zero-rows property (hard rule 1) in the only shape these tables
    can hold it: the READ is global by exemption, so the count that must be zero is the
    ROWCOUNT of every write verb. `c4b70e928a1f` closed this half; it is pinned here
    because `b8e2d47f0c19` rewrote the policy it lives in, and a rewrite is exactly when a
    property gets dropped by accident."""
    async with tenant_session(routes.other) as session:
        deactivated = await session.execute(
            text("UPDATE engine_agent_routes SET active = false WHERE engine_agent_ref = :r"),
            {"r": routes.ref},
        )
        deleted = await session.execute(
            text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :r"),
            {"r": routes.ref},
        )
        kb_deleted = await session.execute(
            text("DELETE FROM engine_kb_routes WHERE engine_kb_ref = :r"),
            {"r": routes.ref},
        )
    assert deactivated.rowcount == 0, "another tenant silenced this client's inbound route"
    assert deleted.rowcount == 0, "another tenant deleted this client's inbound route"
    assert kb_deleted.rowcount == 0, "another tenant deleted this client's knowledge claim"
    assert (await _route_row("engine_agent_routes", "engine_agent_ref", routes.ref)) == (
        routes.tenant,
        True,
    )


async def test_a_tenant_cannot_claim_another_tenants_route_by_re_tenanting_it(
    routes: _Routes,
) -> None:
    """`USING` decides which rows you may touch and `WITH CHECK` decides what you may
    leave behind, so a re-tenanting is refused by the second even where the first admits
    the row. Pinned in BOTH directions — a tenant reaching for somebody else's row, and
    the row's OWNER trying to hand it away — because only the second is a WITH CHECK
    failure and the two would otherwise pass on one implementation."""
    async with tenant_session(routes.other) as session:
        stolen = await session.execute(
            text("UPDATE engine_agent_routes SET tenant_id = :me WHERE engine_agent_ref = :r"),
            {"me": routes.other, "r": routes.ref},
        )
        assert stolen.rowcount == 0, "a tenant re-pointed another client's inbound calls"

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with tenant_session(routes.tenant) as session:
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET tenant_id = :them WHERE engine_agent_ref = :r"
                ),
                {"them": routes.other, "r": routes.ref},
            )
    assert (await _route_row("engine_agent_routes", "engine_agent_ref", routes.ref))[
        0
    ] == routes.tenant


# --- 2. no tenant at all — the arm this migration removed ----------------------


async def test_an_untenanted_session_cannot_insert_a_route_for_any_tenant(
    routes: _Routes,
) -> None:
    """The measured hole, stated as the property that closed it. This INSERT returned
    `INSERT 0 1` before `b8e2d47f0c19` — from a session with no `app.tenant_id`, naming a
    tenant of its choosing, on the table that maps an inbound number to an agent."""
    for statement, params in (
        (
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id) "
            "VALUES (:e, :r, :t, :a)",
            {"a": uuid.uuid4()},
        ),
        (
            "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, agent_id, "
            "source_id) VALUES (:e, :r, :t, :a, :s)",
            {"a": uuid.uuid4(), "s": uuid.uuid4()},
        ),
    ):
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with untenanted_session() as session:
                await session.execute(
                    text(statement),
                    {"e": ENGINE, "r": f"{routes.ref}-forged", "t": routes.other, **params},
                )


async def test_an_untenanted_session_cannot_re_tenant_deactivate_or_delete_a_route(
    routes: _Routes,
) -> None:
    """The exposure that made this worth a migration even though nothing reaches it today.

    The next untenanted writer — a new worker, a new sweep, a route handler reaching for
    `untenanted_session` — used to inherit all three of these on a table whose contents
    decide which client answers a phone number. Each is a rowcount of zero now, which is
    the fail-closed answer: nothing raises, nothing is written, and the row is unchanged.
    """
    async with untenanted_session() as session:
        stolen = await session.execute(
            text("UPDATE engine_agent_routes SET tenant_id = :them WHERE engine_agent_ref = :r"),
            {"them": routes.other, "r": routes.ref},
        )
        silenced = await session.execute(
            text("UPDATE engine_agent_routes SET active = false WHERE engine_agent_ref = :r"),
            {"r": routes.ref},
        )
        deleted = await session.execute(
            text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :r"),
            {"r": routes.ref},
        )
        kb_deleted = await session.execute(
            text("DELETE FROM engine_kb_routes WHERE engine_kb_ref = :r"),
            {"r": routes.ref},
        )
    assert stolen.rowcount == 0, "an untenanted session re-pointed a client's inbound calls"
    assert silenced.rowcount == 0, "an untenanted session silenced a client's inbound route"
    assert deleted.rowcount == 0, "an untenanted session deleted a client's inbound route"
    assert kb_deleted.rowcount == 0, "an untenanted session deleted a client's knowledge claim"
    assert (await _route_row("engine_agent_routes", "engine_agent_ref", routes.ref)) == (
        routes.tenant,
        True,
    )
    assert (await _route_row("engine_kb_routes", "engine_kb_ref", routes.ref))[0] == routes.tenant


# --- 3. the sweeps still do their job -----------------------------------------


async def test_the_drift_sweeps_still_record_from_the_routes_own_tenant(
    routes: _Routes,
) -> None:
    """The narrowing was not a revert: both sweeps still stamp their verdict.

    This is the half that makes the hole load-bearing — `record_drift` and
    `record_kb_drift` are the two writers that used the untenanted arm. They now take the
    tenant the batch read already handed them and write under it, which is what
    `dispatch_scan` (`a8d4f21c9b06`) does per tenant rather than reaching for a privileged
    role.
    """
    async with tenant_session(routes.tenant) as session:
        assert await record_drift(
            session, tenant_id=routes.tenant, engine=ENGINE, ref=routes.ref, state="not_applied"
        )
        assert await record_kb_drift(
            session, tenant_id=routes.tenant, engine=ENGINE, ref=routes.ref, state="unaccounted"
        )
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT drift_state, drift_detected_at, kb_drift_state, kb_drift_detected_at "
                    "FROM engine_agent_routes WHERE engine = :e AND engine_agent_ref = :r"
                ),
                {"e": ENGINE, "r": routes.ref},
            )
        ).one()
    assert row[0] == "not_applied" and row[1] is not None
    assert row[2] == "unaccounted" and row[3] is not None


async def test_the_drift_stamp_writes_nothing_from_an_untenanted_session(
    routes: _Routes,
) -> None:
    """And the OLD call shape fails closed rather than silently working.

    `False` is the value both functions already return for "the route vanished under us",
    which the sweeps treat as a skip — so a future author who reaches for
    `untenanted_session()` again gets a tick that records nothing and a `skipped` count
    that says so, never a cross-tenant write.
    """
    async with untenanted_session() as session:
        assert not await record_drift(
            session, tenant_id=routes.tenant, engine=ENGINE, ref=routes.ref, state="applied"
        )
        assert not await record_kb_drift(
            session, tenant_id=routes.tenant, engine=ENGINE, ref=routes.ref, state="in_sync"
        )


# --- 4. the exemption itself is intact ----------------------------------------


async def test_the_read_is_still_global_on_both_tables(routes: _Routes) -> None:
    """The half that must NOT change, and the reason this file exists rather than a
    one-line policy swap: an inbound webhook arrives with a vendor id and no session, the
    drift sweeps claim their batch across the fleet, and the KB orphan sweep asks what no
    tenant claims. All three are untenanted READS, and narrowing them would read like a
    security fix while stopping every inbound call."""
    async with untenanted_session() as session:
        agent_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM engine_agent_routes "
                    "WHERE engine = :e AND engine_agent_ref = :r"
                ),
                {"e": ENGINE, "r": routes.ref},
            )
        ).scalar_one()
        kb_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM engine_kb_routes WHERE engine = :e AND engine_kb_ref = :r"
                ),
                {"e": ENGINE, "r": routes.ref},
            )
        ).scalar_one()
    assert agent_rows == 1, "the untenanted read the inbound webhook depends on is gone"
    assert kb_rows == 1, "the untenanted read the KB orphan sweep depends on is gone"


async def test_neither_write_policy_admits_a_session_with_no_tenant(routes: _Routes) -> None:
    """The catalogue, not the behaviour — read from `pg_policy` so that a future migration
    re-adding the `OR <guc> IS NULL` arm fails HERE, next to the reasoning, and not only
    in `scripts/check_rls_coverage.py`. `USING (true)` on the `*_global_read` policies is
    the exemption and is asserted to still be `FOR SELECT`: the same expression on any
    other command is the whole defect, one verb wider."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.relname, p.polname, p.polcmd, "
                    "pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid) "
                    "FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                    "WHERE c.relname IN ('engine_agent_routes', 'engine_kb_routes')"
                )
            )
        ).all()
    assert len(rows) == 4, "a policy was added or dropped on a route table"
    for table, name, cmd, using, with_check in rows:
        if name == "tenant_isolation":
            for expression in (using, with_check):
                assert expression is not None and "IS NULL" not in expression.upper(), (
                    f"{table}.{name} admits a session with no tenant again: {expression}"
                )
        else:
            assert cmd == "r", f"{table}.{name} is USING (true) on {cmd}, not on SELECT alone"

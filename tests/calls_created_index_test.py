"""The reads that find a tenant's calls by `created_at` are served by an index (D-787).

The attention queue's failed calls (polled by the header bell on every console page) and
the Performance tab's aggregates filter `calls` by `created_at`. Without
`ix_calls_tenant_created` each one scanned every call the tenant ever made. This runs the
real functions, captures the statements they send, and asks the planner how it would run
each with sequential scans priced out — so a dropped index, or a query rewritten into a
shape the index cannot serve, fails here rather than as a slow console.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.core.settings import Settings
from apps.api.crm.attention import failed_calls
from apps.api.crm.performance import performance
from apps.api.db.session import get_engine, tenant_session
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.conftest import create_org_with_receptionist

INDEX = "ix_calls_tenant_created"


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Created At Motors",
        slug=f"created-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _history(tenant_id: uuid.UUID) -> None:
    """Give the tenant a realistic history: months of calls, none inside the read windows.

    With a handful of rows the tenant index and the tenant-and-time index cost the same, so
    the planner's pick among them is arbitrary and varies with what the rest of the suite
    left in `calls` (CI picked `ix_calls_tenant_id`, 19 Oct 2026). Old rows plus fresh
    statistics make the time index the cheaper one, which is the production shape it
    exists for. ANALYZE needs the table owner, hence the owner connection.
    """
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, started_at, updated_at) SELECT gen_random_uuid(), :tid, :aid, "
                "'history-' || :run || '-' || n, 'inbound', 'completed', at, at, now() "
                "FROM generate_series(1, 600) AS n, "
                "LATERAL (SELECT now() - make_interval(days => 30 + n % 330) AS at) AS t"
            ),
            {"tid": tenant_id, "aid": agent_id, "run": uuid.uuid4().hex},
        )
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: ANALYZE needs the table owner"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ANALYZE calls"))
    finally:
        await engine.dispose()


async def test_the_reads_by_creation_time_use_the_index() -> None:
    tenant_id = await _tenant()
    await _history(tenant_id)
    captured: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, statement: str, params: Any, *_rest: Any) -> None:
        if "FROM calls" in statement and "created_at >" in statement:
            captured.append((statement, params))

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        async with tenant_session(tenant_id) as session:
            await failed_calls(session)
            await performance(session, days=7)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)

    # failed calls, plus the Performance funnel, qualified leads, outcomes and busiest hours.
    assert len(captured) == 5
    async with tenant_session(tenant_id) as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        connection = await session.connection()
        for statement, params in captured:
            plan = (await connection.exec_driver_sql("EXPLAIN " + statement, params)).all()
            shown = "\n".join(str(row[0]) for row in plan)
            # The plan is in the message because the full suite leaves other tenants' rows
            # in `calls`, and a plan that differs only there cannot be reproduced alone.
            assert "Seq Scan on calls" not in shown, f"{statement}\n{shown}"
            # The qualified-leads count is driven from `leads`, so the planner may reach the
            # calls through `ix_calls_lead_id` (one lookup per lead) instead of the time index;
            # both are index reads. Every other statement starts from `calls` by time.
            served = (INDEX, "ix_calls_lead_id") if "FROM leads" in statement else (INDEX,)
            assert any(name in shown for name in served), f"{statement}\n{shown}"

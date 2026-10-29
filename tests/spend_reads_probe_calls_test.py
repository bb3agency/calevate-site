"""The month's spend reads find each charged call by primary key.

`GET /v1/billing/spend` (per-call attribution) and `GET /v1/billing/spend/daily` (per-day
and per-agent series) match one month of usage rows or debits to their calls. As plain
joins the planner hashed every call the account ever had to do it (at 60k calls: 15 ms and
11 ms of hashing for ~2.4k rows of the month). A `LATERAL ... LIMIT 1` makes each match a
`pk_calls` probe, so the read grows with the month and not with the account's history.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from apps.api.core.settings import get_settings
from apps.api.db.session import get_engine, tenant_session
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.conftest import create_org_with_receptionist, fund_wallet
from tests.first_run_test import _owner


async def _account() -> uuid.UUID:
    """Months of uncharged history and three calls charged today."""
    created = await create_org_with_receptionist(
        name="Spend Probe Traders",
        slug=f"spend-probe-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await fund_wallet(tenant_id)
    run = uuid.uuid4().hex
    async with tenant_session(tenant_id) as session:
        params = {"t": tenant_id, "a": created["agent_id"], "run": run}
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, started_at, ended_at, duration_s, updated_at) "
                "SELECT gen_random_uuid(), :t, :a, 'hist-' || :run || '-' || n, 'inbound', "
                "'completed', at, at, at, 60, now() FROM generate_series(1, 2000) n, "
                "LATERAL (SELECT now() - make_interval(days => 40 + n % 300) AS at) w"
            ),
            params,
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, started_at, ended_at, duration_s, updated_at) "
                "SELECT gen_random_uuid(), :t, :a, 'today-' || :run || '-' || n, 'inbound', "
                "'completed', now(), now(), now(), 60, now() FROM generate_series(1, 3) n"
            ),
            params,
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) SELECT gen_random_uuid(), :t, c.id, "
                "'platform_min', 1, 0.5, now(), now() FROM calls c "
                "WHERE c.engine_call_id LIKE 'today-' || :run || '-%'"
            ),
            params,
        )
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) SELECT gen_random_uuid(), :t, -4.50, 'usage', "
                "c.id::text, 9000, now(), now() FROM calls c "
                "WHERE c.engine_call_id LIKE 'today-' || :run || '-%'"
            ),
            params,
        )
    owner_url = get_settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: ANALYZE needs the table owner"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ANALYZE calls"))
            await conn.execute(text("ANALYZE usage_events"))
            await conn.execute(text("ANALYZE credit_ledger"))
    finally:
        await engine.dispose()
    return tenant_id


async def test_the_months_rows_meet_their_calls_by_primary_key() -> None:
    tenant_id = await _account()
    headers = await _owner(tenant_id)
    captured: list[tuple[str, Any]] = []

    def capture(_c: Any, _cur: Any, statement: str, params: Any, *_rest: Any) -> None:
        if re.search(r"\bcalls c\b", statement) and (
            "FROM folded f" in statement or "FROM credit_ledger e" in statement
        ):
            captured.append((statement, params))

    from apps.api.main import app
    from httpx import ASGITransport, AsyncClient

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
            spend = await http.get("/v1/billing/spend", headers=headers)
            daily = await http.get("/v1/billing/spend/daily", headers=headers)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    assert spend.status_code == 200, spend.text
    assert daily.status_code == 200, daily.text
    assert len(captured) == 2, [s[:80] for s, _ in captured]

    async with tenant_session(tenant_id) as session:
        connection = await session.connection()
        for statement, params in captured:
            plan = "\n".join(
                str(r[0])
                for r in (
                    await connection.exec_driver_sql(
                        "EXPLAIN (ANALYZE, COSTS OFF) " + statement, params
                    )
                ).all()
            )
            reads = [line for line in plan.splitlines() if " on calls " in line]
            assert reads, plan
            assert all("pk_calls" in line for line in reads), plan

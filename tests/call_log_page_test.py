"""The call log picks its page from `calls` alone, then joins (crm/service.list_calls).

The log orders running calls first (D-886) and then newest first. It used to sort the JOINED
rows, so the per-row work (the call-back LATERAL, the lead's name, the credit used) ran for
every call the account ever had before the LIMIT kept one page. These pin the two halves:
the paging still reads exactly as one ordered list, and the per-row work is page-sized.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import get_engine, tenant_session
from sqlalchemy import event
from tests.call_log_live_rows_test import _ended
from tests.first_run_test import _owner
from tests.test_call_status_test import (
    _call,
    _client,
    _end_inserted_calls,  # noqa: F401  (autouse: ends every live row written here)
)
from tests.trial_test_calls_test import _trial_tenant

pytestmark = [pytest.mark.rls]


async def _log(tenant_id: UUID, agent_id: UUID) -> tuple[list[UUID], list[UUID], UUID]:
    """Two calls being dialled, one queued call that never heard its end, four ended."""
    now = datetime.now(UTC)
    running = [
        await _call(tenant_id, agent_id, status="queued", placed=now - timedelta(minutes=m))
        for m in (1, 2)
    ]
    stale = await _call(tenant_id, agent_id, status="queued", placed=now - timedelta(hours=3))
    ended = [
        await _ended(tenant_id, agent_id, started=now - timedelta(minutes=m))
        for m in (5, 90, 200, 400)
    ]
    return running, ended, stale


async def test_pages_read_as_one_list_with_running_calls_first() -> None:
    tenant_id, agent_id = await _trial_tenant()
    running, ended, stale = await _log(tenant_id, agent_id)
    headers = await _owner(tenant_id)
    async with _client() as http:
        whole = await http.get("/v1/calls?limit=50", headers=headers)
        assert whole.status_code == 200, whole.text
        paged: list[str] = []
        for offset in range(0, 8, 2):
            page = await http.get(f"/v1/calls?limit=2&offset={offset}", headers=headers)
            assert page.status_code == 200, page.text
            paged.extend(row["id"] for row in page.json())
        queued = await http.get("/v1/calls?status=queued", headers=headers)

    order = [row["id"] for row in whole.json()]
    # Ended calls interleave with the stale row by when each happened: 5, 90 min, the stale
    # row at 3 h, then 200 and 400 min.
    expected = [*running, ended[0], ended[1], stale, ended[2], ended[3]]
    assert order == [str(i) for i in expected]
    assert paged == order
    assert [row["live_state"] for row in whole.json()[:3]] == ["live", "live", None]
    # A filter narrows both halves: the running calls still lead, the stale one follows.
    assert [row["id"] for row in queued.json()] == [str(i) for i in (*running, stale)]


async def test_per_row_work_runs_for_one_page_not_the_whole_history() -> None:
    tenant_id, agent_id = await _trial_tenant()
    now = datetime.now(UTC)
    for m in range(30):
        await _ended(tenant_id, agent_id, started=now - timedelta(minutes=10 + m))
    headers = await _owner(tenant_id)
    captured: list[tuple[str, Any]] = []

    def capture(_c: Any, _cur: Any, statement: str, params: Any, *_rest: Any) -> None:
        if "scheduled_callbacks" in statement and "FROM calls c" in statement:
            captured.append((statement, params))

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        async with _client() as http:
            listed = await http.get("/v1/calls?limit=5", headers=headers)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 5
    assert len(captured) == 1, [s for s, _ in captured]

    statement, params = captured[0]
    async with tenant_session(tenant_id) as session:
        connection = await session.connection()
        plan = "\n".join(
            str(row[0])
            for row in (
                await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, COSTS OFF) " + statement, params
                )
            ).all()
        )
    # Every node under the call-back LATERAL runs once per joined row; with the page chosen
    # first that is the page, not the 30 calls (nor the whole table) the account holds.
    loops = [int(n) for n in re.findall(r"loops=(\d+)", plan)]
    assert max(loops) <= 5, plan

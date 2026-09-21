"""The route three alarm remediations told an operator to run.

THE DEFECT THIS PINS. `GET /v1/ops/kb-orphans` was named by
`runbooks/alarm-index.md` in the remediation of `engine_kb_orphans_detected`,
`engine_kb_account_listing_incomplete` and `kb_orphan_sweep_abandoned`, and by
`workers/kb_orphans.py` twice — and no router served it. An operator following any of
those mid-incident reached a 404, and `account_kb_report` sat public with a docstring
saying "the ops route calls it too" about a route that did not exist.

Run: uv run pytest -q tests/ops_kb_orphans_route_test.py
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.main import app
from httpx import ASGITransport, AsyncClient

PATH = "/v1/ops/kb-orphans"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest.mark.asyncio
async def test_the_route_the_runbook_names_is_actually_served() -> None:
    """Served and permissioned — not 404. The 404 is the whole defect."""
    async with _client() as http:
        anonymous = await http.get(PATH)
    assert anonymous.status_code != 404, (
        "the route three alarm remediations send an operator to is unmounted again"
    )
    assert anonymous.status_code in (401, 403), anonymous.text


@pytest.mark.asyncio
async def test_an_engine_with_no_account_store_says_so_rather_than_reporting_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`supported=False` and NOT "0 orphans".

    An engine that keeps no account-level knowledge store has nothing to walk. Reporting
    zero findings would read as "we looked and it is clean", which is the silence the
    sweep exists to break — and on an owned runtime it is the ordinary state.
    """
    from apps.api.ops import routes as ops_routes

    async def _no_store() -> None:
        return None

    monkeypatch.setattr(ops_routes, "account_kb_report", _no_store)
    report = await ops_routes.read_kb_orphans()

    assert report.supported is False
    assert report.findings == 0
    assert report.listing_complete is False, (
        "an engine with nothing to walk has not produced a complete listing, and a caller "
        "must be able to tell that from a clean one"
    )
    assert report.listing_incomplete_reason == "engine_keeps_no_account_knowledge_store"


@pytest.mark.asyncio
async def test_the_counts_and_rows_come_from_the_sweep_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ONE READING, shared with the cron.

    `workers/kb_orphans.account_kb_report` is public precisely so this route and the daily
    sweep cannot come to disagree about what `unclaimed` means. A handler that re-derived
    the answer would be the second reading that docstring refuses.
    """
    from uuid import uuid4

    from apps.api.kb.orphans import KbOrphanReport, KbOrphanRow
    from apps.api.ops import routes as ops_routes

    source_id, tenant_id = uuid4(), uuid4()
    stub = KbOrphanReport(
        accounted=7,
        unrecorded=1,
        unclaimed=2,
        stranded=3,
        rows=[KbOrphanRow(verdict="unclaimed", handle="kb-abc", source_id=None)],
        truncated=True,
        listing_complete=False,
        listing_incomplete_reason="page_cap_reached",
    )

    async def _stubbed() -> Any:
        return stub

    monkeypatch.setattr(ops_routes, "account_kb_report", _stubbed)
    report = await ops_routes.read_kb_orphans()

    assert (report.accounted, report.unrecorded, report.unclaimed, report.stranded) == (
        7,
        1,
        2,
        3,
    )
    assert report.findings == 6, "findings is the sweep's own sum, not a second arithmetic"
    assert report.truncated is True
    assert report.listing_complete is False
    assert report.listing_incomplete_reason == "page_cap_reached"
    assert [row.handle for row in report.rows] == ["kb-abc"]
    assert report.rows[0].verdict == "unclaimed"
    assert report.rows[0].source_id is None
    assert source_id != tenant_id

"""A truncated listing must be LOUD at the poller, not just honest at the adapter.

`ExecutionListing.complete` is worth nothing on its own — a signal nobody reads is not a
signal. `reconcile_executions` is the only caller, so this is where the fact becomes an
alert an operator receives, a metric an SLO rule can watch, and a job result that does
not read as "all quiet".

Deliberately DB-free: the listings here carry no snapshots, so the job never reaches
`_pipeline_settled` — the poller's per-execution probe, which asks whether the artefacts
the pipeline owed this call are actually there, not merely whether a completed call row
exists. What is under test is the branch between "the engine answered" and
"we repaired something", and it must hold even when there is nothing to repair — a
truncated listing with zero repairs is the most dangerous shape there is, because every
other number on the tick says everything is fine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import apps.workers.pipeline as pipeline_module
import pytest
from apps.workers.pipeline import reconcile_executions
from calevate_shared.engine import ExecutionListing


class _StubEngine:
    """Returns one prepared listing. Only `name` and `list_executions` are reached."""

    name = "fake"

    def __init__(self, listing: ExecutionListing) -> None:
        self._listing = listing

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        return self._listing


@pytest.fixture
def poller(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Runs the job against a prepared listing and reports what it emitted."""
    alerts: list[tuple[str, str, str | None]] = []
    metrics: list[str] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        alerts.append((stage, code, detail))

    def _metric(*, reason: str) -> None:
        metrics.append(reason)

    monkeypatch.setattr(pipeline_module, "alert", _alert)
    monkeypatch.setattr(pipeline_module, "record_reconciliation_listing_incomplete", _metric)

    async def run(listing: ExecutionListing) -> dict[str, Any]:
        monkeypatch.setattr(pipeline_module, "get_engine", lambda: _StubEngine(listing))
        result = await reconcile_executions({})
        return {"result": result, "alerts": list(alerts), "metrics": list(metrics)}

    return run


async def test_a_possibly_truncated_listing_alerts_even_when_nothing_was_repaired(
    poller: Any,
) -> None:
    """The whole point. Executions past the page have no webhook (at-most-once, D-31),
    no repair and no error anywhere — this alert is the only trace they leave."""
    emitted = await poller(
        ExecutionListing(
            snapshots=[], complete=False, incomplete_reason="full_page_suspected", pages_fetched=1
        )
    )

    codes = [code for _stage, code, _detail in emitted["alerts"]]
    assert "reconciliation_listing_incomplete" in codes, (
        "the poller read a possibly truncated window and said nothing — the calls in the "
        "gap are unrecoverable and invisible"
    )
    assert emitted["metrics"] == ["full_page_suspected"]
    assert "listing_incomplete=full_page_suspected" in emitted["result"], (
        "the job result must not read as a quiet tick"
    )


async def test_the_alert_carries_counts_and_a_reason_and_no_payload(poller: Any) -> None:
    """Hard rule 6: what an operator gets is ids, counts and OUR words. The reason is
    the adapter's closed enum, so it is also a stable deduplication key (BACKEND-PATTERNS
    §8) rather than a formatted vendor string."""
    emitted = await poller(
        ExecutionListing(
            snapshots=[], complete=False, incomplete_reason="explicit_more", pages_fetched=3
        )
    )

    detail = next(
        d for _s, code, d in emitted["alerts"] if code == "reconciliation_listing_incomplete"
    )
    assert detail is not None
    assert "explicit_more" in detail
    assert "3 page(s)" in detail


async def test_a_complete_listing_is_silent(poller: Any) -> None:
    """The counterweight. An alarm that fires on every healthy tick is an alarm the
    operator stops reading, which costs exactly the calls this one exists to save."""
    emitted = await poller(ExecutionListing(snapshots=[], complete=True))

    assert emitted["alerts"] == []
    assert emitted["metrics"] == []
    assert emitted["result"] == "repaired=0"

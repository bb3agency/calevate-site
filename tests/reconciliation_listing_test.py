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

from datetime import UTC, datetime, timedelta
from typing import Any

import apps.workers.pipeline as pipeline_module
import pytest
from apps.api.engine.fake import FakeEngine
from apps.workers.pipeline import reconcile_executions
from calevate_shared.engine import ExecutionListing
from pydantic import ValidationError


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


# =============================================================================
# The verdict itself: `complete=True` must be a CLAIM, never a leftover
#
# Everything above tests what the poller does with an answer. These test whether the
# answer can be produced by accident — which is the half `ExecutionListing`'s own
# docstring is about ("never the fallback for 'we did not look'") and the half nothing
# enforced: the field carried `= True`, so the shortest construction anyone writes made
# the strongest claim in the type.
# =============================================================================


def test_a_listing_cannot_be_built_without_stating_whether_it_is_complete() -> None:
    """THE DEFAULT WAS THE DEFECT. `ExecutionListing(snapshots=rows)` used to mean
    "I read the whole window", asserted by omission — from an adapter that may have read
    page one of nine, at the one seam where the missing rows are precisely the calls whose
    at-most-once webhook was lost (D-31). `EngineCapabilities` made every field required
    for the same reason and says so in the same words; this is that doctrine applied to
    the other claim an adapter can make without thinking."""
    with pytest.raises(ValidationError) as raised:
        ExecutionListing(snapshots=[])  # type: ignore[call-arg]
    assert "complete" in str(raised.value)


def test_an_incomplete_listing_must_name_a_reason() -> None:
    """`reason` is the alert's deduplication key (BACKEND-PATTERNS §8), and the poller
    falls back to the string `unknown` without one. "Possibly truncated, cause unstated"
    is the single alert an operator cannot act on, so the type refuses to express it."""
    with pytest.raises(ValidationError) as raised:
        ExecutionListing(snapshots=[], complete=False)
    assert "reason" in str(raised.value)


def test_a_complete_listing_may_not_also_carry_a_reason() -> None:
    """The opposite incoherence, and the more dangerous one: the poller branches on
    `complete`, so an adapter that noticed truncation and published the all-clear anyway
    would have its finding read by nobody. That looks like diligence in the code and is
    silence on the wire."""
    with pytest.raises(ValidationError):
        ExecutionListing(snapshots=[], complete=True, incomplete_reason="explicit_more")


async def test_the_fake_engine_reports_both_verdicts_from_real_paging() -> None:
    """The second adapter, DRIVEN rather than described.

    `complete` is only worth something if both answers are reachable from real behaviour:
    an adapter that can only ever say True is indistinguishable from one that never looks.
    So this walks the fake engine across its own page boundary — one call under the size,
    one over — and requires the verdict to flip, with a reason that describes what
    actually happened.

    `page_cap_reached` rather than `full_page_suspected`: this engine enumerated its own
    store, so truncation is KNOWN, not suspected, and the two labels send an operator to
    different places. And `pages_fetched` stays 1 truthfully — there is no continuation to
    follow in memory, and inflating it would fake the one number that says the paging path
    really ran.
    """
    engine = FakeEngine(listing_page_size=3)
    since = datetime.now(UTC) - timedelta(hours=1)
    for index in range(3):
        engine.seed_inbound_call(
            call_id=f"exec_page_{index}",
            agent_ref="fakeagent_paging",
            from_e164="+915000000001",
            to_e164="+911140000000",
        )

    exactly_full = await engine.list_executions(since=since)
    assert len(exactly_full.snapshots) == 3
    assert exactly_full.complete is True, (
        "an engine that enumerated its own store and returned everything it holds has "
        "positive grounds for the claim — reporting a page-sized window as suspect here "
        "would fire the alert on every healthy tick"
    )
    assert exactly_full.incomplete_reason is None

    engine.seed_inbound_call(
        call_id="exec_page_over",
        agent_ref="fakeagent_paging",
        from_e164="+915000000001",
        to_e164="+911140000000",
    )
    truncated = await engine.list_executions(since=since)

    assert len(truncated.snapshots) == 3, "the rows it did get are still returned"
    assert truncated.complete is False, (
        "the fourth call is past the page and the caller was not told — that call has no "
        "webhook, no repair and nothing anywhere that says it existed"
    )
    assert truncated.incomplete_reason == "page_cap_reached"
    assert truncated.pages_fetched == 1

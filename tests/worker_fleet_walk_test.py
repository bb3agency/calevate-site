"""The fleet-wide walks stop themselves, and the one job that had no ladder now has one.

Three defects, one theme: a background job that is killed or finished by something other
than its own code cannot report what it failed to do.

* **The walks.** `qa_sampling.draw_qa_samples` and `kb_aggregation.send_agent_knowledge_
  digests` walk the whole client directory one `tenant_session` at a time, with no bound
  of any kind. `WorkerSettings.job_timeout` is 300 seconds; past it `run_job` cancels the
  task and sees `TimeoutError` (arq 0.28.0, `arq/worker.py:594-634`), which is none of the
  three exceptions `retry_jobs` honours — so the tick is finished on its first attempt, the
  tail of the fleet is never walked, and the log line it leaves is not one
  `ARQ_TERMINAL_MESSAGES` alerts on. The retried case is a DEPLOY (`CancelledError`), and
  there the pass restarts from the top of the same ordering: for the digest sweep, whose
  per-tenant step is an EMAIL, that re-mails everyone already reached.
  `dispatcher.report_overdue_erasures` was bounded for exactly this in D-369;
  `fleet_walk.WalkBudget` is that one mechanism, and these tests drive it on all three.
* **The ladder.** `action_audit.record_action_invocation` raised on failure, and a plain
  raise is terminal under arq 0.28 (`retry_jobs` honours `Retry`, `RetryJob` and
  `CancelledError` and nothing else). One lock timeout and the audit row for a tool the
  caller actually ran was gone, with no alert and no outbox row behind it.

The budgets are monkeypatched to zero rather than the clock being wound: the property
under test is "the walk notices it is out of budget and announces it", not "180 seconds
is enough", which is a fact about a machine rather than about this code.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from apps.workers import action_audit, kb_aggregation, qa_sampling
from apps.workers.fleet_walk import FLEET_WALK_DEADLINE, WalkBudget
from apps.workers.settings import WorkerSettings


class _Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, kind: str, code: str, *, detail: str = "", **kw: Any) -> None:
        self.calls.append((kind, code, detail))


def _spent_budget() -> WalkBudget:
    return WalkBudget(timedelta(seconds=0))


# --- the budget itself --------------------------------------------------------


def test_the_default_budget_leaves_real_headroom_under_arqs_job_timeout() -> None:
    """The whole point of the budget is to finish BEFORE arq cancels the job. The margin
    is checked, not just the ordering: a budget a few seconds under the timeout is racing
    the cancellation it exists to avoid, and the alert, the last tenant session and the
    pool teardown all happen after the walk stops."""
    timeout = timedelta(seconds=WorkerSettings.job_timeout)
    assert timeout > FLEET_WALK_DEADLINE, (
        f"the fleet-walk budget ({FLEET_WALK_DEADLINE}) is not under arq's job_timeout "
        f"({timeout}), so the walk is cancelled instead of stopping itself"
    )
    assert timeout - FLEET_WALK_DEADLINE >= timedelta(seconds=60), (
        "less than a minute of headroom between the budget and the cancellation"
    )


def test_the_budget_latches_so_truncation_is_reported_once() -> None:
    """`exhausted` is read AFTER the loop, when the clock has moved on. A non-latching
    flag would be re-derived from a deadline that is now long past for a walk that
    finished perfectly inside it."""
    fresh = WalkBudget(timedelta(hours=1))
    assert fresh.spent() is False and fresh.exhausted is False
    spent = _spent_budget()
    assert spent.spent() is True
    assert spent.exhausted is True, "the flag must survive the loop it was set in"


# --- the weekly QA draw -------------------------------------------------------


async def test_a_qa_draw_that_runs_out_of_time_stops_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tenants past the budget have NO sample for the week, and `samples_drawn` is
    then a floor rather than the draw. Silence here reads exactly like a quiet week."""
    alerts = _Alerts()
    monkeypatch.setattr(qa_sampling, "alert", alerts)
    monkeypatch.setattr(qa_sampling, "WalkBudget", lambda *a, **k: _spent_budget())

    tenants = [uuid.UUID(int=1), uuid.UUID(int=2)]
    totals = await qa_sampling.draw_for_tenants(tenants, [])

    assert totals["tenants_probed"] == 0, (
        f"a spent budget must stop the walk before the first tenant session: {totals}"
    )
    assert totals["tenants_unreached"] == 2, totals

    async def _directory(*_: Any, **__: Any) -> dict[str, int]:
        return totals

    monkeypatch.setattr(qa_sampling, "draw_for_tenants", _directory)
    monkeypatch.setattr(qa_sampling, "_DIRECTORY", "SELECT id FROM organizations WHERE false")
    await qa_sampling.draw_qa_samples({})

    fired = [call[1] for call in alerts.calls]
    assert "qa_sample_draw_truncated" in fired, (
        f"the draw stopped part-way through the fleet and said nothing: {fired}"
    )
    # NOT the failure alarm: nothing failed, the walk simply never got there, and the two
    # have different answers (retry vs. the fleet has outgrown one tick).
    assert "qa_sample_draw_failed" not in fired, fired
    assert "qa_sample_draw_abandoned" not in fired, fired


async def test_an_unreached_tenant_is_not_read_as_the_whole_draw_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The abandoned-draw arm compares failures against what the pass REACHED. Compared
    against the directory — which is what it did while the walk was unbounded — a
    truncated pass in which every attempted tenant failed slips past it silently."""
    alerts = _Alerts()
    monkeypatch.setattr(qa_sampling, "alert", alerts)

    async def _one_failed_one_unreached(*_: Any, **__: Any) -> dict[str, int]:
        return {
            "tenants": 2,
            "tenants_probed": 1,
            "weeks": 1,
            "calls_in_frame": 0,
            "samples_drawn": 0,
            "tenants_failed": 1,
            "tenants_unreached": 1,
        }

    monkeypatch.setattr(qa_sampling, "draw_for_tenants", _one_failed_one_unreached)
    monkeypatch.setattr(qa_sampling, "_DIRECTORY", "SELECT id FROM organizations WHERE false")

    with pytest.raises(qa_sampling.Retry):
        await qa_sampling.draw_qa_samples({"job_try": 1})

    fired = [call[1] for call in alerts.calls]
    assert "qa_sample_draw_failed" in fired and "qa_sample_draw_truncated" in fired, fired


# --- the weekly knowledge digest ---------------------------------------------


async def test_a_digest_sweep_that_runs_out_of_time_stops_before_it_mails_anyone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep's per-tenant step is an EMAIL, so a pass that is cut short is either a
    fleet silently under-served (the timeout, which arq does not retry) or the same client
    mailed again (a deploy's `CancelledError`, which it does). The budget is what keeps
    either cancellation from happening at all."""
    alerts = _Alerts()
    sent: list[str] = []

    async def _never(*_: Any, **__: Any) -> str:  # pragma: no cover - must not be called
        sent.append("mailed")
        return "sent"

    monkeypatch.setattr(kb_aggregation, "alert", alerts)
    monkeypatch.setattr(kb_aggregation, "_digest_one", _never)
    monkeypatch.setattr(kb_aggregation, "WalkBudget", lambda *a, **k: _spent_budget())

    summary = await kb_aggregation._sweep(kb_aggregation.datetime.now(kb_aggregation.UTC))

    assert sent == [], f"a spent budget must stop the sweep before any send: {summary}"
    assert "reached=0" in summary, summary
    fired = [call[1] for call in alerts.calls]
    assert "kb_digest_undelivered" in fired, (
        f"the sweep reached part of the fleet and said nothing, which reads as a quiet "
        f"week: {fired}"
    )
    detail = next(call[2] for call in alerts.calls if call[1] == "kb_digest_undelivered")
    assert "time budget" in detail, (
        "the detail must separate 'the query did not name every agent' from 'the pass "
        f"ran out of clock' — they have different remedies: {detail}"
    )


# --- the action-audit ladder --------------------------------------------------


def _failing_session(*_: Any, **__: Any) -> Any:
    class _Boom:
        async def __aenter__(self) -> Any:
            raise TimeoutError("lock timeout")

        async def __aexit__(self, *_exc: Any) -> None:  # pragma: no cover - never reached
            return None

    return _Boom()


async def test_an_audit_write_that_fails_asks_for_the_retry_it_used_to_forfeit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain raise is TERMINAL under arq: `WorkerSettings.max_tries` never reaches a
    job that does not ask. Before this ladder, one lock timeout lost the audit row for a
    tool the caller had actually run."""
    monkeypatch.setattr(action_audit, "tenant_session", _failing_session)
    with pytest.raises(action_audit.Retry):
        await action_audit.record_action_invocation(
            {"job_try": 1},
            {"tenant_id": str(uuid.UUID(int=1)), "tool_id": "tool-1"},
        )


async def test_the_last_attempt_alerts_rather_than_failing_in_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq refuses the pickup AFTER the ladder is spent, so the last attempt is the only
    place this job can say the invocation is permanently unlogged."""
    alerts = _Alerts()
    monkeypatch.setattr(action_audit, "alert", alerts)
    monkeypatch.setattr(action_audit, "tenant_session", _failing_session)

    with pytest.raises(TimeoutError):
        await action_audit.record_action_invocation(
            {"job_try": action_audit.WORKER_MAX_TRIES},
            {"tenant_id": str(uuid.UUID(int=1)), "tool_id": "tool-1"},
        )

    fired = [call[1] for call in alerts.calls]
    assert fired == ["action_audit_unrecorded"], fired
    detail = alerts.calls[0][2]
    assert "TimeoutError" in detail and "lock timeout" not in detail, (
        "the exception TYPE locates the failure; its message can quote the row that "
        f"broke it (hard rule 6): {detail}"
    )

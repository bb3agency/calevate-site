"""A7-15: the live-apply line said "about to be updated" with a spinner 22 hours later, naming
a setting key that no longer exists. A run still queued past the time a running worker takes
to pick it up is flagged, and every reason reads as a setting's label."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from apps.api.agents.live_apply import LiveApplyRunView
from apps.api.ops.config_catalog import FIELD_META
from apps.api.ops.live_apply_routes import NOT_STARTED_AFTER, REMOVED_SETTING, _out


def _run(*, status: str, age: timedelta, reasons: list[str]) -> LiveApplyRunView:
    return LiveApplyRunView(
        id=uuid.uuid4(),
        scope="platform",
        tenant_id=None,
        agent_id=None,
        reasons=reasons,
        status=status,
        total=None,
        applied=0,
        failed=0,
        retrying=0,
        failures=[],
        created_at=datetime.now(UTC) - age,
        finished_at=None,
        superseded_by=None,
    )


def test_a_run_queued_past_the_pick_up_time_is_flagged() -> None:
    late = _out(_run(status="pending", age=timedelta(hours=22), reasons=["hot_facts_enabled"]))
    assert late.not_started is True
    fresh = _out(_run(status="pending", age=timedelta(seconds=5), reasons=["hot_facts_enabled"]))
    assert fresh.not_started is False
    running = _out(_run(status="running", age=timedelta(hours=22), reasons=["hot_facts_enabled"]))
    assert running.not_started is False
    assert late.not_started_after_minutes == int(NOT_STARTED_AFTER.total_seconds() // 60)


def test_reasons_read_as_labels_and_a_removed_setting_says_so() -> None:
    run = _out(
        _run(
            status="done",
            age=timedelta(minutes=1),
            reasons=["hot_facts_enabled", "ai_notice_introduces_agent"],
        )
    )
    assert run.reason_labels == [FIELD_META["hot_facts_enabled"].label, REMOVED_SETTING]

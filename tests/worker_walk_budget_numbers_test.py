"""The number-rental meter, the renewal collector and the held-number sweep stop inside
their time budget.

Each walks the whole directory one `tenant_session` at a time. Past `job_timeout` arq
cancels the tick with `TimeoutError` and never retries it (`fleet_walk`'s docstring), so the
newest accounts went unmetered, uncharged for a renewing number, or kept a held number
renewing at our cost. The budgets are monkeypatched to zero, as
`worker_walk_budget_digest_expiry_test` does.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import number_holds, number_rental
from apps.workers.fleet_walk import WalkBudget
from arq import Retry

_TWO_TENANTS = (
    "SELECT CAST('00000000-0000-7000-8000-00000000b001' AS uuid) "
    "UNION ALL SELECT CAST('00000000-0000-7000-8000-00000000b002' AS uuid)"
)


class _Alerts:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def __call__(self, kind: str, code: str, **_: Any) -> None:
        self.codes.append(code)


def _spent() -> WalkBudget:
    return WalkBudget(timedelta(seconds=0))


@pytest.fixture
def spent_rentals(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Both rental crons on a two-account directory with no budget left; returns the
    accounts whose numbers were read."""
    read: list[uuid.UUID] = []

    async def _bought(tenant_id: uuid.UUID) -> list[Any]:
        read.append(tenant_id)
        return []

    monkeypatch.setattr(number_rental, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(number_rental, "_ALL_TENANTS", _TWO_TENANTS)
    monkeypatch.setattr(number_rental, "_tenant_bought", _bought)
    return read


async def test_the_rental_meter_retries_when_the_budget_runs_out(
    spent_rentals: list[uuid.UUID],
) -> None:
    with pytest.raises(Retry):
        await number_rental.meter_number_rentals({"job_try": 1})
    assert spent_rentals == [], "a spent budget must stop the walk before the first tenant"


async def test_the_rental_meter_alarms_when_the_last_try_is_still_cut_short(
    spent_rentals: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts = _Alerts()
    monkeypatch.setattr(number_rental, "alert", alerts)

    result = await number_rental.meter_number_rentals({"job_try": WORKER_MAX_TRIES})

    assert "'unreached': 2" in result, result
    assert "number_rentals_incomplete" in alerts.codes, alerts.codes


async def test_renewals_retry_when_the_budget_runs_out(
    spent_rentals: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _never(*_: Any, **__: Any) -> Any:
        raise AssertionError("a spent budget must not collect anything")

    monkeypatch.setattr(number_rental, "collect_number_rental", _never)

    with pytest.raises(Retry):
        await number_rental.renew_number_rentals({"job_try": 1})


async def test_renewals_alarm_when_the_last_try_is_still_cut_short(
    spent_rentals: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts = _Alerts()
    monkeypatch.setattr(number_rental, "alert", alerts)

    with pytest.raises(RuntimeError, match="2 account"):
        await number_rental.renew_number_rentals({"job_try": WORKER_MAX_TRIES})
    assert "number_rental_renewals_unrecorded" in alerts.codes, alerts.codes


async def test_the_hold_sweep_stops_at_its_budget_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts = _Alerts()
    settled: list[uuid.UUID] = []

    async def _settle(tenant_id: uuid.UUID) -> tuple[Any, int]:
        settled.append(tenant_id)
        return Counter(), 0

    monkeypatch.setattr(number_holds, "alert", alerts)
    monkeypatch.setattr(number_holds, "engine_number_provider", lambda: "plivo")
    monkeypatch.setattr(number_holds, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(number_holds, "_DIRECTORY", _TWO_TENANTS)
    monkeypatch.setattr(number_holds, "settle_tenant", _settle)

    result = await number_holds.sweep_number_holds({"job_try": 1})

    assert settled == [], "a spent budget must stop the walk before the first tenant"
    assert "'unreached': 2" in result, result
    assert "number_holds_truncated" in alerts.codes, alerts.codes


# --- the read-only probes: a tenant past the budget is unreached, and says so ---------------

_TENANT_IDS = [
    uuid.UUID("00000000-0000-7000-8000-00000000b001"),
    uuid.UUID("00000000-0000-7000-8000-00000000b002"),
]


async def _two() -> list[uuid.UUID]:
    return list(_TENANT_IDS)


async def test_the_recording_watch_counts_tenants_past_its_budget_as_unreached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import recording_watch

    alerts = _Alerts()
    monkeypatch.setattr(recording_watch, "alert", alerts)
    monkeypatch.setattr(recording_watch, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(recording_watch, "callable_tenants", _two)

    result = await recording_watch.report_missing_recordings({})

    assert "unreached=2" in result, result
    assert "recording_copy_missing" in alerts.codes, alerts.codes


async def test_the_extraction_reread_sweep_counts_tenants_past_its_budget_as_unreached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import extraction_reread

    alerts = _Alerts()
    monkeypatch.setattr(extraction_reread, "alert", alerts)
    monkeypatch.setattr(extraction_reread, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(extraction_reread, "callable_tenants", _two)

    result = await extraction_reread.sweep_failed_extractions({})

    assert "unreached=2" in result, result
    assert "extraction_reread_exhausted" in alerts.codes, alerts.codes


async def test_the_forwarded_lines_sweep_stops_at_its_budget_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import forwarding

    alerts = _Alerts()

    async def _never(tenant_id: uuid.UUID) -> tuple[bool, int]:
        raise AssertionError("a spent budget must stop the walk before the first tenant")

    monkeypatch.setattr(forwarding, "alert", alerts)
    monkeypatch.setattr(forwarding, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(forwarding, "live_tenants", _two)
    monkeypatch.setattr(forwarding, "_sweep_tenant_lines", _never)

    result = await forwarding.sweep_forwarded_lines({})

    assert result.endswith("unreached:2"), result
    assert "forwarded_lines_sweep_incomplete" in alerts.codes, alerts.codes


class _Directory:
    """`admin_session()` answering the directory read with two tenant ids."""

    async def __aenter__(self) -> _Directory:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def execute(self, *_: Any, **__: Any) -> Any:
        class _Rows:
            def all(self) -> list[tuple[uuid.UUID]]:
                return [(t,) for t in _TENANT_IDS]

        return _Rows()


async def test_a_cut_short_health_pass_skips_the_fleet_wide_judgments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import healer

    alerts = _Alerts()
    outage_fleets: list[Any] = []
    judged: list[Any] = []

    async def _outage(broken: set[uuid.UUID], tally: Any, *, fleet: Any = None) -> None:
        outage_fleets.append(fleet)

    monkeypatch.setattr(healer, "alert", alerts)
    monkeypatch.setattr(healer, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(healer, "admin_session", _Directory)
    monkeypatch.setattr(healer, "_detect_outage", _outage)
    monkeypatch.setattr(healer, "_judge_objective", lambda *a, **k: judged.append(a))

    result = await healer.score_agent_health({})

    assert '"walk_truncated": 1' in result, result
    assert "agent_health_truncated" in alerts.codes, alerts.codes
    assert outage_fleets == [None], "a partial fleet must not judge (or clear) voice domains"
    assert judged == []


async def test_the_gloss_sweep_stops_its_tenant_walk_at_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import kb_gloss

    alerts = _Alerts()

    async def _never(tenant_id: uuid.UUID) -> int:
        raise AssertionError("a spent budget must stop the walk before the first tenant")

    monkeypatch.setattr(kb_gloss, "alert", alerts)
    monkeypatch.setattr(kb_gloss, "background_leg", lambda *a, **k: object())
    monkeypatch.setattr(kb_gloss, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _two)
    monkeypatch.setattr(kb_gloss, "_rekey_one_tenant", _never)

    await kb_gloss.write_knowledge_glosses({})

    assert "kb_gloss_sweep_incomplete" in alerts.codes, alerts.codes


async def test_the_index_sync_stops_at_its_budget_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import kb_index_sync

    alerts = _Alerts()

    async def _never(tenant_id: uuid.UUID) -> None:
        raise AssertionError("a spent budget must stop the walk before the first tenant")

    monkeypatch.setattr(kb_index_sync, "alert", alerts)
    monkeypatch.setattr(kb_index_sync, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(kb_index_sync, "tenants_holding_knowledge", _two)
    monkeypatch.setattr(kb_index_sync, "_sync_one_tenant", _never)

    result = await kb_index_sync.sync_knowledge_index({})

    assert "unreached=2" in result, result
    assert "kb_index_sync_truncated" in alerts.codes, alerts.codes

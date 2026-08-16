"""An erasure that was filed and never executed has to reach a human (P6.5).

**NOTHING WATCHED `deletion_requests`.** Rows sat `completed_at IS NULL` forever with no
cron, no alert and no ops query. `report_stalled_pipeline` had existed for months for
calls — whose worst case is a lead a client did not see — while the one workflow with a
STATUTORY right behind it had no equivalent.

The failure it catches is not slow, it is silent. `execute_deletion_request` is enqueued
ONCE, in the request's own transaction, and unlike the post-call pipeline it has no
`reconcile_executions` behind it. A deploy that cancelled the in-flight job, or a worker
that died with it claimed, leaves the request open permanently; the only signal was a
status page returning `pending` to a data principal nobody was watching.

THE TEST THAT WOULD HAVE CAUGHT THE OBVIOUS WRONG IMPLEMENTATION is
`test_a_tenant_with_no_published_agent_is_still_probed`. The natural move was to reuse
`report_stalled_pipeline`'s tenant list, and that list is
`SELECT DISTINCT tenant_id FROM engine_agent_routes` — tenants with a PUBLISHED AGENT.
Every tenant most likely to be holding a forgotten erasure (never published one; churned,
so `tenant_erasure` tore their routes down) is outside it, so the alarm would have been
blind in precisely the population it exists for and green on every tick.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import request_erasure
from apps.api.db.session import tenant_session
from apps.workers import dispatcher
from apps.workers import settings as worker_settings
from sqlalchemy import text


def _phone() -> str:
    """A fresh subject per test: several suites share this database."""
    return f"+9198761{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Erasure Clinic",
        slug=f"overdue-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"]


async def _open_request(tenant_id: uuid.UUID, *, age: timedelta) -> uuid.UUID:
    """One open erasure request, aged backwards.

    Written through `request_erasure` rather than a hand-built INSERT so the row has the
    shape the product actually produces — `subject_ref`, `scope`, and the outbox row that
    goes with it. Only `requested_at` is then moved, because the alternative is a test
    that sleeps for an hour.
    """
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=_phone())
        await session.execute(
            text("UPDATE deletion_requests SET requested_at = :ts WHERE id = :id"),
            {"ts": datetime.now(UTC) - age, "id": record.id},
        )
    return record.id


async def _complete(tenant_id: uuid.UUID, request_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE deletion_requests SET completed_at = now() WHERE id = :id"),
            {"id": request_id},
        )


class _Alerts:
    """Captures `dispatcher.alert` calls. The alert IS the deliverable here — the return
    string is for the arq job log, and nobody reads a job log at 3am."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, kind: str, code: str, *, detail: str = "", **kw: Any) -> None:
        self.calls.append((kind, code, detail))


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> _Alerts:
    captured = _Alerts()
    monkeypatch.setattr(dispatcher, "alert", captured)
    return captured


@pytest.fixture
def only(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the sweep at ONE tenant.

    The counting tests below assert on exact numbers, and `report_overdue_erasures`
    aggregates over every organization in the database — which several suites share and
    which holds open erasure requests written by others. Left fleet-wide these read
    whatever else happens to be in there, which is a test that passes for reasons it does
    not state and fails for reasons it cannot name.

    The fleet WALK is not skipped by this, it is tested where it belongs:
    `test_a_tenant_with_no_published_agent_is_still_probed` exercises the real directory
    and is the assertion that would catch the wrong tenant source.
    """

    def _pin(tenant_id: uuid.UUID) -> None:
        async def _one() -> list[uuid.UUID]:
            return [tenant_id]

        monkeypatch.setattr(dispatcher, "_all_tenants", _one)

    return _pin


def _overdue(result: str) -> int:
    """Parse by KEY, never by position: the return string carries two numbers and a test
    that splits on the first `=` reads `unreached` as the count the day the order changes.
    """
    return int(dict(part.split("=") for part in result.split())["overdue_erasures"])


def _unreached(result: str) -> int:
    return int(dict(part.split("=") for part in result.split())["unreached"])


# ============================================================================
# What is and is not overdue
# ============================================================================


async def test_an_erasure_open_past_the_bound_is_alerted(alerts: _Alerts, only: Any) -> None:
    tenant_id = await _tenant()
    only(tenant_id)
    await _open_request(tenant_id, age=dispatcher.ERASURE_OVERDUE_AFTER + timedelta(minutes=5))

    result = await dispatcher.report_overdue_erasures({})

    assert _overdue(result) == 1
    assert [c for c in alerts.calls if c[1] == "erasure_requests_overdue"], (
        "the count reached the job's return value and nothing else — an operator only "
        "learns about this through the alert"
    )


async def test_a_request_filed_moments_ago_is_a_queue_not_an_incident(
    alerts: _Alerts, only: Any
) -> None:
    """The healthy path, and the one that decides whether anybody keeps the alarm on.

    A request is written and dispatched within seconds. If the probe counted every open
    row it would fire on every normal erasure, and an alarm that is always on is one
    nobody reads on the night a real one arrives — the same argument
    `_count_stalled` records about silent calls.
    """
    tenant_id = await _tenant()
    only(tenant_id)
    await _open_request(tenant_id, age=timedelta(seconds=3))
    await _open_request(tenant_id, age=timedelta(minutes=2))

    result = await dispatcher.report_overdue_erasures({})

    assert _overdue(result) == 0, "a freshly filed request was counted as overdue"
    assert alerts.calls == [], "and a healthy fleet must page nobody"


async def test_an_executed_erasure_stops_being_counted(only: Any) -> None:
    """`completed_at` is the whole predicate. Without it the alarm would report every
    erasure this product has ever performed, forever, and rise monotonically."""
    tenant_id = await _tenant()
    only(tenant_id)
    request_id = await _open_request(
        tenant_id, age=dispatcher.ERASURE_OVERDUE_AFTER + timedelta(hours=2)
    )
    assert _overdue(await dispatcher.report_overdue_erasures({})) == 1

    await _complete(tenant_id, request_id)

    assert _overdue(await dispatcher.report_overdue_erasures({})) == 0


# ============================================================================
# The tenant source — the finding inside the finding
# ============================================================================


async def test_a_tenant_with_no_published_agent_is_still_probed(alerts: _Alerts) -> None:
    """THE TEST THAT REJECTS THE OBVIOUS IMPLEMENTATION.

    `_callable_tenants()` — what `report_stalled_pipeline` sweeps — is
    `SELECT DISTINCT tenant_id FROM engine_agent_routes`. A tenant with no PUBLISHED agent
    has no row there, and `admin_service.create_organization` does not publish one, so
    this tenant is invisible to that list by construction.

    A client can exercise DPDP §12 against a tenant that never went live, and a churned
    client's routes are deleted by `tenant_erasure` while their subjects' requests stay
    open — so the tenants excluded by that list are the ones most likely to be holding a
    forgotten erasure. Reusing it would have produced an alarm that is green precisely
    where it is needed.
    """
    tenant_id = await _tenant()
    assert tenant_id not in await dispatcher._callable_tenants(), (
        "this tenant has no engine route, which is what makes the assertion below mean "
        "something — if that changes, the test has stopped testing the finding"
    )
    await _open_request(tenant_id, age=dispatcher.ERASURE_OVERDUE_AFTER + timedelta(minutes=30))

    assert tenant_id in await dispatcher._all_tenants()
    assert _overdue(await dispatcher.report_overdue_erasures({})) >= 1
    assert [c for c in alerts.calls if c[1] == "erasure_requests_overdue"]


# ============================================================================
# The sweep's own failure modes
# ============================================================================


async def test_one_tenants_failure_does_not_quieten_the_alarm(
    alerts: _Alerts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same shape as `report_stalled_pipeline`'s isolation test and for the same reason:
    an alarm that fires on a TOTAL fails towards silence when its sweep aborts. A smaller
    number and a healthy fleet are the same reading, so the tick has to survive one
    tenant and say how much of the fleet it actually saw.
    """
    tenant_id = await _tenant()
    await _open_request(tenant_id, age=dispatcher.ERASURE_OVERDUE_AFTER + timedelta(minutes=30))

    real_session = dispatcher.tenant_session
    broken = uuid.UUID(int=0)

    def _session(tid: uuid.UUID) -> Any:
        if tid == broken:
            raise RuntimeError("connection reset")
        return real_session(tid)

    async def _broken_first() -> list[uuid.UUID]:
        # The unreachable tenant IN FRONT of the real one, so this proves the sweep
        # CONTINUES rather than merely that it does not raise.
        return [broken, tenant_id]

    monkeypatch.setattr(dispatcher, "tenant_session", _session)
    monkeypatch.setattr(dispatcher, "_all_tenants", _broken_first)

    result = await dispatcher.report_overdue_erasures({})

    assert _unreached(result) == 1
    assert _overdue(result) == 1, "the tenant after the broken one was still swept"
    body = next(c[2] for c in alerts.calls if c[1] == "erasure_requests_overdue")
    assert "floor" in body, (
        "the alert quotes a number that is short by an unknown amount and must say so"
    )


async def test_a_wholly_failed_sweep_still_alerts(
    alerts: _Alerts, only: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`if total or unreached:` rather than `if total:`. A sweep that reached nobody has a
    total of zero, which is indistinguishable from a clean fleet — and it is the reading
    an operator would take on the one night it is wrong."""
    only(await _tenant())

    def _session(tid: uuid.UUID) -> Any:
        raise RuntimeError("connection reset")

    monkeypatch.setattr(dispatcher, "tenant_session", _session)

    result = await dispatcher.report_overdue_erasures({})

    assert _overdue(result) == 0
    assert _unreached(result) > 0
    assert [c for c in alerts.calls if c[1] == "erasure_requests_overdue"], (
        "a sweep that reached nobody reported zero overdue erasures and said nothing"
    )


async def test_the_alert_body_carries_no_subject(alerts: _Alerts, only: Any) -> None:
    """Hard rule 6, and `subject_ref` counts. It is a hash of the number, which
    `deletion.py` already argues at length is still subject-linkable — the query selects
    `count(*)` and nothing else so that there is no path by which one could reach here.
    """
    tenant_id = await _tenant()
    only(tenant_id)
    await _open_request(tenant_id, age=dispatcher.ERASURE_OVERDUE_AFTER + timedelta(hours=3))

    await dispatcher.report_overdue_erasures({})

    body = next(c[2] for c in alerts.calls if c[1] == "erasure_requests_overdue")
    assert "+91" not in body
    assert "SELECT count(*)" in dispatcher._OVERDUE_ERASURES, (
        "the probe must aggregate in the database — selecting rows would put "
        "`subject_ref` and `phone_e164` one attribute access away from an alert body"
    )


# ============================================================================
# Registration
# ============================================================================


def test_the_probe_is_actually_registered_as_a_cron() -> None:
    """A job nobody scheduled is the defect class CLAUDE.md names outright: it looks like
    progress on a screen and never runs.

    Its `max_tries` is NOT asserted here. `worker_reliability_test` already owns that
    question for every cron that cannot self-heal and this job is named in its list —
    two tests for one property is the second way of doing one thing that CLAUDE.md calls
    a defect even when both pass, and it is the copy that goes stale.
    """
    registered = [
        job
        for job in worker_settings.CRON_JOBS
        if "report_overdue_erasures" in getattr(job.coroutine, "__name__", "")
        or "report_overdue_erasures" in job.coroutine.__qualname__
    ]
    assert registered, "the overdue-erasure probe exists and nothing schedules it"

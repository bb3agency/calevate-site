"""The missing-recording-copy sweep (D-805): `apps/workers/recording_watch.py`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.alarm_severity import severity_of
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.workers import recording_watch
from apps.workers.pipeline import PIPELINE_STALL_AFTER
from apps.workers.settings import WorkerSettings
from apps.workers.storage import NOT_READY_MAX_DEFER_S
from sqlalchemy import text
from tests.conftest import accept_agreements


async def _tenant(prefix: str) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name=f"{prefix.title()} Homes",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(UUID(str(created["id"])))
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    ended_ago: timedelta,
    status: str = "completed",
    engine_call_id: str | None = None,
    extra_sql: str = "",
) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, created_at, updated_at) VALUES (:id, :tid, "
                ":aid, :ecid, 'inbound', :status, :ended - interval '2 minutes', :ended, 120, "
                ":ended - interval '2 minutes', now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": engine_call_id or f"call_{call_id.hex[:16]}",
                "status": status,
                "ended": datetime.now(UTC) - ended_ago,
            },
        )
        if extra_sql:
            await session.execute(
                text(f"UPDATE calls SET {extra_sql} WHERE id = :id"), {"id": call_id}
            )
    return call_id


async def _missing(tenant_id: UUID) -> set[UUID]:
    async with tenant_session(tenant_id) as session:
        found = await recording_watch.missing_copies(session, now=datetime.now(UTC))
    return {copy.call_id for copy in found}


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    fired: list[tuple[str, str, dict[str, Any]]] = []

    def _alert(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs))

    monkeypatch.setattr(recording_watch, "alert", _alert)
    return fired


def _only(*tenants: UUID) -> Any:
    async def _tenants() -> list[UUID]:
        return list(tenants)

    return _tenants


def _parsed(result: str) -> dict[str, int]:
    return {key: int(value) for key, value in (part.split("=") for part in result.split())}


async def test_a_connected_call_with_no_copy_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _tenant("recmiss")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(tenant_id))

    result = await recording_watch.report_missing_recordings({})

    assert _parsed(result) == {"missing": 1, "at_risk": 0, "unreached": 0}
    [(stage, code, kwargs)] = fired
    assert (stage, code) == ("WORKER_DELIVERY", "recording_copy_missing")
    assert kwargs["call_id"] == str(call_id)
    assert kwargs["tenant_id"] == str(tenant_id)
    assert "1 connected call(s) across 1 tenant(s)" in kwargs["detail"]
    # 30-day floor, ended 3 hours ago.
    assert "deletes it in 29.9 day(s)" in kwargs["detail"]


async def test_calls_that_owe_no_copy_are_not_reported() -> None:
    tenant_id, agent_id = await _tenant("recskip")
    owed = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    await _call(
        tenant_id, agent_id, ended_ago=timedelta(hours=3), extra_sql="recording_url = 'k/a.wav'"
    )
    await _call(
        tenant_id,
        agent_id,
        ended_ago=timedelta(hours=3),
        extra_sql="engine_content_deleted_at = now()",
    )
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3), status="no_answer")
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3), status="failed")
    await _call(
        tenant_id,
        agent_id,
        ended_ago=timedelta(hours=3),
        engine_call_id=f"pipecat:{tenant_id}:{uuid.uuid4().hex}",
    )
    await _call(
        tenant_id, agent_id, ended_ago=timedelta(hours=3), extra_sql="erased_subject_ref = 'subj'"
    )
    # Inside the grace: the copy may still be on its way.
    await _call(tenant_id, agent_id, ended_ago=timedelta(minutes=30))
    # Past the platform's deletion by more than the reporting tail: history.
    await _call(tenant_id, agent_id, ended_ago=timedelta(days=40))

    assert await _missing(tenant_id) == {owed}


async def test_a_tenant_whose_engagement_was_erased_is_not_reported() -> None:
    tenant_id, agent_id = await _tenant("recerase")
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id},
        )

    assert await _missing(tenant_id) == set()


async def test_one_tenant_that_cannot_be_checked_is_counted_and_still_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant("recunreach")
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    broken = uuid.UUID(int=0)
    real_session = recording_watch.tenant_session

    def _session(tid: UUID) -> Any:
        if tid == broken:
            raise RuntimeError("connection reset")
        return real_session(tid)

    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "tenant_session", _session)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(broken, tenant_id))

    result = await recording_watch.report_missing_recordings({})

    assert _parsed(result) == {"missing": 1, "at_risk": 0, "unreached": 1}
    detail = next(kw["detail"] for _s, code, kw in fired if code == "recording_copy_missing")
    assert "1 of 2 tenant(s) could not be checked" in detail


async def test_a_sweep_that_reached_nobody_still_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    def _session(tid: UUID) -> Any:
        raise RuntimeError("connection reset")

    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "tenant_session", _session)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(uuid.uuid4()))

    result = await recording_watch.report_missing_recordings({})

    assert _parsed(result) == {"missing": 0, "at_risk": 0, "unreached": 1}
    assert [code for _s, code, _kw in fired] == ["recording_copy_missing"]


async def test_a_copy_days_from_deletion_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _tenant("recrisk")
    await _call(tenant_id, agent_id, ended_ago=timedelta(days=10))
    soonest = await _call(tenant_id, agent_id, ended_ago=timedelta(days=25))
    gone = await _call(tenant_id, agent_id, ended_ago=timedelta(days=31))
    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(tenant_id))

    result = await recording_watch.report_missing_recordings({})

    assert _parsed(result) == {"missing": 3, "at_risk": 2, "unreached": 0}
    risk = next(kw for _s, code, kw in fired if code == "recording_copy_at_risk")
    assert risk["call_id"] == str(gone)
    assert risk["call_ids"] == f"{gone},{soonest}"
    assert "2 call(s) with no recording copy are within 7 days" in risk["detail"]
    assert "1 may already be gone" in risk["detail"]
    assert severity_of("recording_copy_at_risk") == "page"
    assert severity_of("recording_copy_missing") == "attention"


async def test_a_client_workspace_deletes_on_its_confirmed_retention() -> None:
    """A client whose transcript period is a week has the platform delete recordings at a
    week too, so a call in its own workspace is at risk long before the plan's 30 days."""
    tenant_id, agent_id = await _tenant("recwsret")
    workspace = f"org_{uuid.uuid4().hex[:20]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, "
                "workspace_id, status, retention_days, retention_plan_days, created_at, "
                "updated_at) VALUES (:id, :tid, 'thinnest', :ref, :ws, 'active', 7, 30, "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "ref": f"calevate-{tenant_id}", "ws": workspace},
        )
    in_workspace = await _call(
        tenant_id,
        agent_id,
        ended_ago=timedelta(days=3),
        engine_call_id=f"call_{uuid.uuid4().hex[:16]}@{workspace}",
    )
    in_developer = await _call(tenant_id, agent_id, ended_ago=timedelta(days=3))

    async with tenant_session(tenant_id) as session:
        found = await recording_watch.missing_copies(session, now=datetime.now(UTC))
    deletes = {copy.call_id: copy.deletes_at - copy.ended for copy in found}

    assert deletes == {in_workspace: timedelta(days=7), in_developer: timedelta(days=30)}


def test_the_grace_outlasts_the_copy_and_its_re_drive() -> None:
    """Shorter than the copy's own ladder plus the poller's re-drive, and the sweep reports
    calls whose copy is still legitimately in flight."""
    ladder = timedelta(
        seconds=WORKER_MAX_TRIES * WorkerSettings.job_timeout
        + (WORKER_MAX_TRIES - 1) * NOT_READY_MAX_DEFER_S
    )
    listing_window = timedelta(minutes=30)
    assert PIPELINE_STALL_AFTER + listing_window + 2 * ladder <= recording_watch.COPY_GRACE

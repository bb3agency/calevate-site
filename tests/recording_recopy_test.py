"""Re-copying a call's missing recording (D-808): `recording_watch.recopy_call_recording`,
the sweep that queues it and the operator's per-call route."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.queue import get_queue
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import pipeline, recording_watch, storage
from arq.constants import job_key_prefix
from calevate_shared.engine import ExecutionSnapshot
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.recording_watch_test import _call, _capture, _only, _parsed, _tenant

ROUTE = "/v1/ops/tenants/{tenant_id}/calls/{call_id}/recording/recopy"
SOURCE = "https://recordings.example/call.wav"


class _EngineWithoutItsOwnSource:
    """An engine that serves no recording of its own, so the copy uses the snapshot's link."""

    name = "fake"


def _snapshot(execution_id: str) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        recording_url=SOURCE,
    )


def _engine(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], list[str]]:
    """Stage the engine read and the download. Returns (executions read, sources fetched)."""
    read: list[str] = []
    fetched: list[str] = []

    async def _truth(engine: Any, *, execution_id: str, delivery: Any, **_: Any) -> Any:
        assert delivery is None
        read.append(execution_id)
        return _snapshot(execution_id)

    async def _copy(*, source_url: str, tenant_id: UUID, call_id: UUID, leg: str = "call") -> str:
        fetched.append(source_url)
        return storage.recording_key(tenant_id, call_id)

    monkeypatch.setattr(recording_watch, "post_call_truth", _truth)
    monkeypatch.setattr(recording_watch, "get_engine", _EngineWithoutItsOwnSource)
    monkeypatch.setattr(pipeline, "get_engine", _EngineWithoutItsOwnSource)
    monkeypatch.setattr(pipeline, "copy_recording", _copy)
    return read, fetched


async def _row(tenant_id: UUID, call_id: UUID) -> tuple[Any, int]:
    async with tenant_session(tenant_id) as session:
        url = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).scalar()
        usage = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :id"), {"id": call_id}
            )
        ).scalar()
    return url, int(usage or 0)


def _payload(tenant_id: UUID, call_id: UUID) -> dict[str, str]:
    return {"tenant_id": str(tenant_id), "call_id": str(call_id)}


async def test_the_job_copies_a_missing_recording_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant("recopy")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    read, fetched = _engine(monkeypatch)

    outcome = await recording_watch.recopy_call_recording({}, _payload(tenant_id, call_id))

    assert outcome == "call:copied+transfer:none_offered"
    assert read == [f"call_{call_id.hex[:16]}"], "the call's own engine handle is read"
    assert fetched == [SOURCE]
    url, usage = await _row(tenant_id, call_id)
    assert url == storage.recording_key(tenant_id, call_id)
    assert usage == 0, "a re-copy must not meter the call"


async def test_the_job_is_a_no_op_for_a_recording_we_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant("recopyheld")
    call_id = await _call(
        tenant_id, agent_id, ended_ago=timedelta(hours=3), extra_sql="recording_url = 'k/a.wav'"
    )
    read, fetched = _engine(monkeypatch)

    outcome = await recording_watch.recopy_call_recording({}, _payload(tenant_id, call_id))

    assert outcome == "already_copied"
    assert (read, fetched) == ([], [])
    assert (await _row(tenant_id, call_id))[0] == "k/a.wav"


@pytest.mark.parametrize(
    ("extra_sql", "refusal"),
    [
        ("engine_content_deleted_at = now()", "content_deleted"),
        ("erased_subject_ref = 'subj'", "erased"),
    ],
)
async def test_the_job_never_fetches_deleted_or_erased_content(
    monkeypatch: pytest.MonkeyPatch, extra_sql: str, refusal: str
) -> None:
    tenant_id, agent_id = await _tenant("recopygone")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3), extra_sql=extra_sql)
    read, fetched = _engine(monkeypatch)

    outcome = await recording_watch.recopy_call_recording({}, _payload(tenant_id, call_id))

    assert outcome == refusal
    assert (read, fetched) == ([], [])
    assert (await _row(tenant_id, call_id))[0] is None


async def test_the_sweep_queues_each_missing_call_once_and_still_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant("recopysweep")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(tenant_id))

    first = _parsed(await recording_watch.report_missing_recordings({}))
    second = _parsed(await recording_watch.report_missing_recordings({}))

    assert (first["recopies"], first["recopies_pending"]) == (1, 0)
    assert (second["recopies"], second["recopies_pending"]) == (0, 1)
    job_id = recording_watch.recopy_job_id(tenant_id, call_id, source="sweep")
    assert await (await get_queue()).exists(job_key_prefix + job_id) == 1
    missing = [kw["detail"] for _s, code, kw in fired if code == "recording_copy_missing"]
    assert len(missing) == 2, "a queued re-copy is not a copy: both sweeps alarm"
    assert "re-copies requested for 1, already queued for 0" in missing[0]
    assert "re-copies requested for 0, already queued for 1" in missing[1]


async def test_a_sweep_that_cannot_queue_still_alarms_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant("recopyredis")
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    await _call(tenant_id, agent_id, ended_ago=timedelta(hours=4))
    fired = _capture(monkeypatch)
    monkeypatch.setattr(recording_watch, "callable_tenants", _only(tenant_id))
    attempts: list[str] = []

    async def _down(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> None:
        attempts.append(str(job_id))
        raise ConnectionError("redis down")

    monkeypatch.setattr(recording_watch, "enqueue", _down)

    result = _parsed(await recording_watch.report_missing_recordings({}))

    assert result["missing"] == 2
    assert result["recopies"] == 0
    assert len(attempts) == 1, "the second enqueue would only wait out the same timeout"
    [detail] = [kw["detail"] for _s, code, kw in fired if code == "recording_copy_missing"]
    assert "could not be queued for 2" in detail


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin(role: str) -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _press(token: str, tenant_id: UUID, call_id: UUID) -> Any:
    async with _client() as http:
        return await http.post(
            ROUTE.format(tenant_id=tenant_id, call_id=call_id),
            headers={"Authorization": f"Bearer {token}"},
        )


async def _audits(call_id: UUID) -> int:
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'ops.recording_recopy' "
                    "AND object_id = :oid"
                ),
                {"oid": str(call_id)},
            )
        ).scalar()
    return int(count or 0)


async def test_the_operator_route_needs_ops_manage() -> None:
    tenant_id, agent_id = await _tenant("recopyperm")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))

    refused = await _press(await _admin("operator"), tenant_id, call_id)

    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"
    assert await _audits(call_id) == 0
    job_id = recording_watch.recopy_job_id(tenant_id, call_id, source="operator")
    assert await (await get_queue()).exists(job_key_prefix + job_id) == 0


async def test_the_operator_route_queues_once_and_audits_what_it_queued() -> None:
    tenant_id, agent_id = await _tenant("recopyroute")
    call_id = await _call(tenant_id, agent_id, ended_ago=timedelta(hours=3))
    token = await _admin("superadmin")

    first = await _press(token, tenant_id, call_id)
    second = await _press(token, tenant_id, call_id)

    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "queued"
    assert first.json()["queued"] is True
    assert second.json()["outcome"] == "already_queued"
    job_id = recording_watch.recopy_job_id(tenant_id, call_id, source="operator")
    assert await (await get_queue()).exists(job_key_prefix + job_id) == 1
    assert await _audits(call_id) == 1, "only the press that queued a job is audited"


async def test_the_operator_route_refuses_a_call_with_nothing_to_copy() -> None:
    tenant_id, agent_id = await _tenant("recopyrefuse")
    held = await _call(
        tenant_id, agent_id, ended_ago=timedelta(hours=3), extra_sql="recording_url = 'k/a.wav'"
    )
    token = await _admin("superadmin")

    answered = await _press(token, tenant_id, held)
    unknown = await _press(token, tenant_id, uuid.uuid4())

    assert answered.status_code == 200, answered.text
    assert (answered.json()["outcome"], answered.json()["queued"]) == ("already_copied", False)
    assert unknown.status_code == 404, unknown.text
    assert await _audits(held) == 0

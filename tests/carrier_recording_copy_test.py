"""The carrier's recording reaches OUR `recordings/`, once, promptly, or loudly (D-668).

What this file catches:

1. **`RecordStop` through the existing carrier path.** The callback stores only the carrier's
   recording id on the call, moves no status, and queues the copy keyed per call.
2. **The copy is idempotent** — `recording_url` set means ours already — and lands OUR key.
3. **Failure is loud and bounded in minutes.** A storage failure retries on a minutes
   ladder and then alarms; a recording the carrier no longer holds pages; the sweep
   re-queues every uncopied recording and pages one still not ours after six hours,
   because the carrier's retention may be three days (contract §9a).
4. **An erased subject's audio is never re-acquired**, and the carrier's copy is deleted.
5. **An erasure quotes the recording ids on the telephony task and deletes them at the
   carrier** (`processor_erasure`, `root-site/openapi.json:8459-8484`).

Run: uv run python -m pytest -q tests/carrier_recording_copy_test.py
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierCallEvent, CarrierRecordingSource
from apps.api.engine.vobiz import parse_event as vobiz_parse_event
from apps.workers import carrier_events, carrier_recordings, retention
from apps.workers.carrier_events import ingest_carrier_event
from apps.workers.carrier_recordings import (
    COPY_JOB,
    COPY_OVERDUE_AFTER,
    DELETE_JOB,
    copy_carrier_recording,
    delete_carrier_recordings,
    reconcile_carrier_recordings,
)
from apps.workers.storage import StorageUnavailableError
from arq import Retry
from sqlalchemy import text
from tests.carrier_event_job_test import Recorder, install_recorder, make_call, make_tenant

pytestmark = [pytest.mark.rls]

RECORDING_ID = "d7801b2e-e76d-4dd8-be9c-9e015a7267b8"


@dataclass
class _Carrier:
    """Vobiz's own callback parser, with the recording API faked."""

    source: CarrierRecordingSource | None = field(
        default_factory=lambda: CarrierRecordingSource(
            url="https://media.vobiz.ai/r.mp3",
            auth_headers={"X-Auth-ID": "MA_X", "X-Auth-Token": "tok"},
            auth_hosts=frozenset({"vobiz.ai"}),
        )
    )
    found: str | None = None
    asked: list[tuple[str, str]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "vobiz"

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        return vobiz_parse_event(fields)

    async def recording_source(
        self, recording_id: str, *, carrier_call_id: str
    ) -> CarrierRecordingSource | None:
        self.asked.append((recording_id, carrier_call_id))
        return self.source

    async def find_recording(self, carrier_call_id: str) -> str | None:
        return self.found

    async def delete_recording(self, recording_id: str) -> bool:
        self.deleted.append(recording_id)
        return True


@dataclass
class _Copies:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> _Carrier:
    fake = _Carrier()
    monkeypatch.setattr(carrier_events, "get_carrier", lambda name=None: fake)
    monkeypatch.setattr(carrier_recordings, "get_carrier", lambda name=None: fake)
    return fake


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = install_recorder(monkeypatch)

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None, **kw: Any):
        rec.enqueued.append((job, payload, job_id, kw))
        return job_id or job

    monkeypatch.setattr(carrier_recordings, "enqueue", _enqueue)
    monkeypatch.setattr(
        carrier_recordings, "alert", lambda stage, code, **kw: rec.alerts.append((stage, code, kw))
    )
    return rec


@pytest.fixture
def copies(monkeypatch: pytest.MonkeyPatch) -> _Copies:
    state = _Copies()

    async def _copy(**kwargs: Any) -> str:
        state.calls.append(kwargs)
        if state.fail:
            raise StorageUnavailableError("recording upload failed: ClientError")
        return f"recordings/{kwargs['tenant_id']}/{kwargs['call_id']}.wav"

    async def _delete(keys: list[str]) -> int:
        return len(keys)

    monkeypatch.setattr(carrier_recordings.storage, "copy_recording", _copy)
    monkeypatch.setattr(carrier_recordings.storage, "delete_objects", _delete)
    return state


async def _call(*, ended_ago: timedelta = timedelta(0)) -> tuple[uuid.UUID, uuid.UUID, str, str]:
    tenant_id, agent_id, ref = await make_tenant()
    ccid = str(uuid.uuid4())
    call_id = await make_call(
        tenant_id, agent_id, status="completed", direction="inbound", carrier_call_id=ccid
    )
    when = datetime.now(UTC) - ended_ago
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET carrier = 'vobiz', ended_at = :w, created_at = :w WHERE id = :c"
            ),
            {"w": when, "c": call_id},
        )
    return tenant_id, call_id, ref, ccid


async def _row(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[Any, ...]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT carrier_recording_id, recording_url, status FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).first()
    assert row is not None
    return tuple(row)


def _record_stop(ref: str, ccid: str, *, reason: str = "HungUp") -> dict[str, Any]:
    return {
        "carrier": "vobiz",
        "carrier_call_id": ccid,
        "event": "RecordStop",
        "engine_agent_ref": ref,
        "call_id": None,
        "inbox_row_id": None,
        "fields": {
            "CallUUID": ccid,
            "Event": "RecordStop",
            "RecordingID": RECORDING_ID,
            "RecordingDuration": "42",
            "RecordingEndReason": reason,
        },
    }


def _copy_job(tenant_id: uuid.UUID, call_id: uuid.UUID) -> dict[str, str]:
    return {"tenant_id": str(tenant_id), "call_id": str(call_id)}


# --- 1. the callback --------------------------------------------------------------------


async def test_record_stop_stores_the_id_moves_no_status_and_queues_the_copy(
    carrier: _Carrier, seen: Recorder
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    outcome = await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    assert outcome.endswith(":copy_enqueued")
    recording_id, ours, status = await _row(tenant_id, call_id)
    assert recording_id == RECORDING_ID
    assert ours is None, "the callback stores the carrier's id, never a URL"
    assert status == "completed"
    copies = [e for e in seen.enqueued if e[0] == COPY_JOB]
    assert copies == [(COPY_JOB, _copy_job(tenant_id, call_id), f"{COPY_JOB}:{call_id}", {})]
    assert not [a for a in seen.alerts if a[1] == "carrier_recording_ended_early"]


async def test_a_recording_that_stopped_on_a_keypress_is_alarmed(
    carrier: _Carrier, seen: Recorder
) -> None:
    _tenant_id, _call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid, reason="FinishedOnKey"))
    assert [a[1] for a in seen.alerts] == ["carrier_recording_ended_early"]


async def test_a_second_different_id_does_not_replace_the_first(
    carrier: _Carrier, seen: Recorder
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    other = _record_stop(ref, ccid)
    other["fields"]["RecordingID"] = "a1b2c3d4-0000-4000-8000-000000000000"
    outcome = await ingest_carrier_event({"job_try": 1}, other)
    assert not outcome.endswith(":copy_enqueued")
    assert (await _row(tenant_id, call_id))[0] == RECORDING_ID


# --- 2. the copy ------------------------------------------------------------------------


async def test_the_copy_lands_our_key_once(
    carrier: _Carrier, seen: Recorder, copies: _Copies
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    assert await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id)) == "copied"
    assert carrier.asked == [(RECORDING_ID, ccid)], "resolved by id, checked against the call"
    sent = copies.calls[0]
    assert sent["source_url"] == "https://media.vobiz.ai/r.mp3"
    assert sent["auth_hosts"] == frozenset({"vobiz.ai"})
    assert (await _row(tenant_id, call_id))[1] == f"recordings/{tenant_id}/{call_id}.wav"
    again = await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id))
    assert again == "already_copied"
    assert len(copies.calls) == 1


async def test_a_call_with_no_recording_copies_nothing(
    carrier: _Carrier, seen: Recorder, copies: _Copies
) -> None:
    tenant_id, call_id, _ref, _ccid = await _call()
    outcome = await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id))
    assert outcome == "no_recording"
    assert copies.calls == [] and carrier.asked == []


async def test_a_recording_the_carrier_no_longer_holds_pages(
    carrier: _Carrier, seen: Recorder, copies: _Copies
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    carrier.source = None
    assert await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id)) == "lost"
    assert "carrier_recording_lost" in [a[1] for a in seen.alerts]
    assert copies.calls == []


async def test_a_storage_failure_retries_in_minutes_then_alarms(
    carrier: _Carrier, seen: Recorder, copies: _Copies
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    copies.fail = True
    with pytest.raises(Retry) as first:
        await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id))
    assert first.value.defer_score is not None
    assert first.value.defer_score <= 5 * 60 * 1000, "minutes, not hours"
    last = await copy_carrier_recording({"job_try": 3}, _copy_job(tenant_id, call_id))
    assert last == "copy_failed"
    assert "carrier_recording_copy_failed" in [a[1] for a in seen.alerts]
    assert (await _row(tenant_id, call_id))[1] is None


# --- 3. erased before the copy ---------------------------------------------------------


async def test_an_erased_subjects_recording_is_deleted_at_the_carrier_not_copied(
    carrier: _Carrier, seen: Recorder, copies: _Copies
) -> None:
    tenant_id, call_id, ref, ccid = await _call()
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET erased_subject_ref = 'deadbeef' WHERE id = :c"),
            {"c": call_id},
        )
    outcome = await copy_carrier_recording({"job_try": 1}, _copy_job(tenant_id, call_id))
    assert outcome == "erased_not_copied"
    assert copies.calls == []
    deletions = [e for e in seen.enqueued if e[0] == DELETE_JOB]
    assert deletions and deletions[0][1]["recording_ids"] == [RECORDING_ID]


async def test_the_delete_job_deletes_each_recording_at_the_carrier(carrier: _Carrier) -> None:
    outcome = await delete_carrier_recordings(
        {"job_try": 1},
        {"carrier": "vobiz", "recording_ids": [RECORDING_ID], "tenant_id": str(uuid.uuid4())},
    )
    assert outcome == "deleted=1 already_gone=0"
    assert carrier.deleted == [RECORDING_ID]


# --- 4. the sweep -----------------------------------------------------------------------


async def test_the_sweep_requeues_uncopied_and_pages_the_overdue(
    carrier: _Carrier, seen: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, call_id, ref, ccid = await _call(ended_ago=COPY_OVERDUE_AFTER + timedelta(hours=1))
    await ingest_carrier_event({"job_try": 1}, _record_stop(ref, ccid))
    seen.enqueued.clear()

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(carrier_recordings, "callable_tenants", _only_this_tenant)
    result = await reconcile_carrier_recordings({})
    assert "overdue=1" in result
    assert [e[1] for e in seen.enqueued if e[0] == COPY_JOB] == [_copy_job(tenant_id, call_id)]
    overdue = [a for a in seen.alerts if a[1] == "carrier_recording_copy_overdue"]
    assert overdue and overdue[0][0] == "WORKER_STALL"


async def test_the_sweep_finds_a_recording_whose_callback_never_came(
    carrier: _Carrier, seen: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, call_id, _ref, _ccid = await _call(ended_ago=timedelta(minutes=20))
    carrier.found = RECORDING_ID

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(carrier_recordings, "callable_tenants", _only_this_tenant)
    result = await reconcile_carrier_recordings({})
    assert "found=1" in result
    assert (await _row(tenant_id, call_id))[0] == RECORDING_ID
    assert [e[1] for e in seen.enqueued if e[0] == COPY_JOB] == [_copy_job(tenant_id, call_id)]


async def test_with_recording_off_the_sweep_asks_the_carrier_nothing(
    carrier: _Carrier, seen: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings

    tenant_id, call_id, _ref, _ccid = await _call(ended_ago=timedelta(minutes=20))
    carrier.found = RECORDING_ID
    monkeypatch.setenv("CARRIER_RECORDING_ENABLED", "false")
    get_settings.cache_clear()

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(carrier_recordings, "callable_tenants", _only_this_tenant)
    try:
        assert "found=0" in await reconcile_carrier_recordings({})
    finally:
        get_settings.cache_clear()
    assert (await _row(tenant_id, call_id))[0] is None


# --- 5. the erasure -----------------------------------------------------------------------


async def test_an_erasure_quotes_the_recording_and_deletes_it_at_the_carrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[dict[str, Any]] = []

    async def _queue(**kwargs: Any) -> str:
        queued.append(kwargs)
        return "queued"

    monkeypatch.setattr(retention, "enqueue_carrier_deletion", _queue)
    tenant_id, call_id, _ref, ccid = await _call()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET from_e164 = :p, carrier_recording_id = :r WHERE id = :c"),
            {"p": phone, "r": RECORDING_ID, "c": call_id},
        )
        request_id = (
            await session.execute(
                text(
                    "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, "
                    " scope, requested_at, created_at) "
                    "VALUES (gen_random_uuid(), :t, :p, :r, 'all', now(), now()) RETURNING id"
                ),
                {"t": tenant_id, "p": phone, "r": "deadbeef"},
            )
        ).scalar()

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        refs = (
            await session.execute(
                text(
                    "SELECT vendor_refs FROM processor_erasure_tasks "
                    "WHERE request_ref = :r AND processor = 'telephony'"
                ),
                {"r": request_id},
            )
        ).scalar()
    assert sorted(refs) == sorted([ccid, RECORDING_ID])
    assert queued == [{"carrier": "vobiz", "recording_ids": [RECORDING_ID], "tenant_id": tenant_id}]


async def test_the_database_refuses_a_phone_number_as_a_recording_id() -> None:
    from sqlalchemy.exc import IntegrityError

    tenant_id, call_id, _ref, _ccid = await _call()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET carrier_recording_id = '919876500011' WHERE id = :c"),
                {"c": call_id},
            )

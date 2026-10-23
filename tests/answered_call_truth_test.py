"""An answered ThinnestAI call settles from its whole record, never from `call.completed` (D-848).

The production sequence (21 Oct 2026, two outbound test calls): `call.completed` arrived, the
ingest found the call billable and queued the post-call job with that delivery on it, and the
job read the delivery as the call's truth. `call.completed` carries how the call ended and how
long it lasted; the transcript and the recording link come with `call.analysed` 0.8 s later
(snapshots/2026-10-19/pages/api-reference/webhooks/create-webhook.md:281-285). So the call
settled with no turns, no recording, summary `empty` and outcome `missed`, and the
`call.analysed` job, and the reconciliation re-drive after it, were deduped against the
finished run's job id.

The vendor is an `httpx.MockTransport` whose Get Call answers whatever the test sets.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.core.queue import WORKER_MAX_TRIES, get_queue, job_id_for, redis_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.workers import extraction as extraction_module
from apps.workers import pipeline
from apps.workers.settings import WorkerSettings
from arq import Retry
from arq.worker import Function, Worker, func
from sqlalchemy import text
from tests.thinnest_post_call_test import _attest, _thinnest_agent, _usage

ENGINE = "thinnest"
AGO = timedelta(minutes=40)


def _whole(call_id: str, ref: str, *, transcript: bool = True) -> dict[str, Any]:
    """Get Call's object for an answered outbound call (get-call.md shape)."""
    ended = datetime.now(UTC) - AGO
    data: dict[str, Any] = {
        "id": call_id,
        "attempt": 1,
        "status": "completed",
        "direction": "outbound",
        "phone": "919812345678",
        "from": "918045678901",
        "agent": {"id": ref, "name": "Front desk"},
        "startedAt": (ended - timedelta(seconds=66)).isoformat(),
        "answeredAt": (ended - timedelta(seconds=58)).isoformat(),
        "endedAt": ended.isoformat(),
        "seconds": 58,
        "hangup": "answered",
        "summary": "Asked for a demo next week." if transcript else None,
        "recording": {"url": "https://app.thinnest.ai/api/v1/recordings/9f1", "ready": True},
        "analysedAt": (ended + timedelta(seconds=1)).isoformat(),
        "error": None,
    }
    if transcript:
        data["transcript"] = [
            {"speaker": "agent", "text": "Namaskaram!", "at": data["answeredAt"]},
            {"speaker": "customer", "text": "Demo kavali", "at": data["answeredAt"]},
            {"speaker": "agent", "text": "Sure, Tuesday works.", "at": data["answeredAt"]},
        ]
    return data


def _completed_hint(call_id: str, ref: str) -> dict[str, Any]:
    """A `call.completed` body: how the call ended and how long it lasted, as `outcome`, never
    `status`, and no transcript, recording or `analysedAt` (the live openapi.json example and
    ThinnestAI's email of 21 Oct 2026, §23 item 5)."""
    whole = _whole(call_id, ref, transcript=False)
    return {
        "callRef": call_id,
        "conversationId": "conv_1",
        "outcome": "completed",
        "hangup": "answered",
        "seconds": whole["seconds"],
        "direction": "outbound",
        "surface": "phone",
        "phone": whole["phone"],
        "id": call_id,
        "quality": None,
        "endedAt": whole["endedAt"],
    }


def _seal(event: str, call_id: str, data: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"id": f"evt_{uuid.uuid4().hex[:8]}", "event": event, "data": data})
    return seal_delivery(body, engine=ENGINE, execution_id=call_id, event_name=f"{event}:1")


class _Spy:
    model_name = "spy"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def run(self, spec: Any, transcript: str) -> dict[str, Any]:
        self.inputs.append(transcript)
        return {"outcome_tag": "answered"}


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"get_call": None, "gets": 0, "enqueued": [], "alerts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.startswith("/api/v1/calls/"):
            state["gets"] += 1
            if state["get_call"] is None:
                return httpx.Response(404, json={"error": "Not found"})
            return httpx.Response(200, json=state["get_call"])
        return httpx.Response(500)

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://app.thinnest.ai/api/v1"
        ),
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)

    async def _copy(*, tenant_id: UUID, call_id: UUID, leg: str = "call", **_: Any) -> str:
        return f"recordings/{tenant_id}/{call_id}.mp3"

    async def _archive(**kw: Any) -> str:
        return f"engine-payloads/{kw['tenant_id']}/{kw['call_id']}/x.json"

    async def _enqueue(job: str, payload: dict[str, Any], **_: Any) -> str:
        state["enqueued"].append((job, payload))
        return "job"

    real_alert = pipeline.alert

    def _alert(stage: str, code: str, **kw: Any) -> None:
        state["alerts"].append(code)
        real_alert(stage, code, **kw)

    spy = _Spy()
    state["spy"] = spy
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: spy)
    monkeypatch.setattr(pipeline, "copy_recording", _copy)
    monkeypatch.setattr(pipeline, "archive_payload", _archive)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    monkeypatch.setattr(pipeline, "alert", _alert)
    return state


async def _ingest(ref: str, call_id: str, delivery: dict[str, Any] | None) -> str:
    payload: dict[str, Any] = {"engine": ENGINE, "execution_id": call_id, "engine_agent_ref": ref}
    if delivery is not None:
        payload["delivery"] = delivery
    return await pipeline.ingest_engine_event({}, payload)


def _queued(state: dict[str, Any]) -> dict[str, Any]:
    payloads = [p for job, p in state["enqueued"] if job == pipeline.POSTCALL_JOB]
    assert payloads, "the post-call job was never queued"
    return payloads[-1]


async def _call(tenant_id: UUID, call_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.status, c.recording_url, c.summary_state, c.outcome_tag, "
                    "(SELECT count(*) FROM transcript_turns t WHERE t.call_id = c.id) "
                    "FROM calls c WHERE c.id = :c"
                ),
                {"c": call_id},
            )
        ).one()
    return dict(zip(("status", "recording", "summary_state", "outcome", "turns"), row, strict=True))


async def _staged(vendor: dict[str, Any]) -> tuple[UUID, str, str]:
    await _attest("platform", "1.00")
    tenant_id, _agent, ref = await _thinnest_agent(None)
    return tenant_id, ref, f"out_{uuid.uuid4().hex[:12]}"


async def test_a_call_completed_delivery_never_settles_an_answered_calls_content(
    vendor: dict[str, Any],
) -> None:
    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref)
    hint = _seal("call.completed", execution_id, _completed_hint(execution_id, ref))

    assert await _ingest(ref, execution_id, hint) == "pipeline_enqueued"
    payload = _queued(vendor)
    assert await pipeline.run_post_call_pipeline({"job_try": 1}, payload) == "ok"

    call = await _call(tenant_id, UUID(payload["call_id"]))
    assert call["turns"] == 3
    assert call["recording"] is not None
    assert call["summary_state"] == "ready"
    assert call["outcome"] != "missed"


async def test_an_answered_call_without_its_transcript_yet_waits_instead_of_settling(
    vendor: dict[str, Any],
) -> None:
    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    hint = _seal("call.completed", execution_id, _completed_hint(execution_id, ref))
    await _ingest(ref, execution_id, hint)
    payload = _queued(vendor)

    with pytest.raises(Retry):
        await pipeline.run_post_call_pipeline({"job_try": 1}, payload)

    call = await _call(tenant_id, UUID(payload["call_id"]))
    assert call["summary_state"] == "pending", "nothing may read as settled while it waits"
    assert call["turns"] == 0


async def test_the_last_attempt_settles_loudly_and_never_says_nothing_was_said(
    vendor: dict[str, Any],
) -> None:
    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    hint = _seal("call.completed", execution_id, _completed_hint(execution_id, ref))
    await _ingest(ref, execution_id, hint)
    payload = _queued(vendor)

    assert await pipeline.run_post_call_pipeline({"job_try": WORKER_MAX_TRIES}, payload) == "ok"

    call = await _call(tenant_id, UUID(payload["call_id"]))
    assert "engine_call_answered_without_transcript" in vendor["alerts"]
    assert call["summary_state"] == "failed"
    assert call["outcome"] != "missed"


async def test_a_call_completed_hint_records_its_outcome_when_get_call_cannot_answer(
    vendor: dict[str, Any],
) -> None:
    """Get Call 404: the hint stands, its `outcome` read as the status, so the row says the
    call was answered rather than `failed`, and nothing is settled until `call.analysed`."""
    tenant_id, ref, execution_id = await _staged(vendor)
    hint = _seal("call.completed", execution_id, _completed_hint(execution_id, ref))

    assert await _ingest(ref, execution_id, hint) == "awaiting_completion:completed"
    assert vendor["gets"] == 1
    assert not [job for job, _ in vendor["enqueued"] if job == pipeline.POSTCALL_JOB]
    async with tenant_session(tenant_id) as session:
        status, seconds = (
            await session.execute(
                text("SELECT status, duration_s FROM calls WHERE engine_call_id = :e"),
                {"e": execution_id},
            )
        ).one()
    assert (status, seconds) == ("completed", 58)


async def test_the_later_analysed_delivery_rereads_a_call_settled_without_turns_and_bills_once(
    vendor: dict[str, Any],
) -> None:
    tenant_id, ref, execution_id = await _staged(vendor)
    # The engine's own record, read before its analysis held the turns.
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    await _ingest(ref, execution_id, None)
    first = _queued(vendor)
    await pipeline.run_post_call_pipeline({"job_try": WORKER_MAX_TRIES}, first)
    call_id = UUID(first["call_id"])
    billed = await _usage(tenant_id, call_id)
    assert billed, "the answered call's minutes are metered on the first settle"

    analysed = _seal("call.analysed", execution_id, _whole(execution_id, ref))
    assert await _ingest(ref, execution_id, analysed) == "pipeline_enqueued"
    second = _queued(vendor)
    assert second["delivery"] == analysed
    assert await pipeline.run_post_call_pipeline({"job_try": 1}, second) == "ok"

    call = await _call(tenant_id, call_id)
    assert call["turns"] == 3
    assert call["summary_state"] == "ready"
    assert [text_ for text_ in vendor["spy"].inputs if text_.strip()], (
        "the reading of the empty settle was reused for a call that now has words"
    )
    assert await _usage(tenant_id, call_id) == billed, "a re-run must not meter twice"

    reads = len(vendor["spy"].inputs)
    await pipeline.run_post_call_pipeline({"job_try": 1}, second)
    assert len(vendor["spy"].inputs) == reads, "an unchanged transcript reuses its reading"
    assert await _usage(tenant_id, call_id) == billed


async def test_the_poller_re_drives_an_answered_call_that_settled_without_turns(
    vendor: dict[str, Any],
) -> None:
    _tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    await _ingest(ref, execution_id, None)
    await pipeline.run_post_call_pipeline({"job_try": WORKER_MAX_TRIES}, _queued(vendor))

    vendor["get_call"] = _whole(execution_id, ref)
    engine = pipeline.get_engine()
    assert isinstance(engine, ThinnestEngine)
    listed = engine.snapshot_from_delivery({"data": _whole(execution_id, ref, transcript=False)})
    assert await pipeline._pipeline_settled(ENGINE, listed) == "unfinished_pipeline"


async def test_a_deduped_enqueue_is_reported_as_one(
    vendor: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref)

    async def _deduped(job: str, payload: dict[str, Any], **_: Any) -> None:
        return None

    monkeypatch.setattr(pipeline, "enqueue", _deduped)
    assert await _ingest(ref, execution_id, None) == "pipeline_deduped"


async def test_a_completed_row_reads_as_answered_whatever_the_snapshot_states(
    vendor: dict[str, Any],
) -> None:
    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref)
    await _ingest(ref, execution_id, None)
    call_id = UUID(_queued(vendor)["call_id"])
    engine = pipeline.get_engine()
    assert isinstance(engine, ThinnestEngine)
    hint = _completed_hint(execution_id, ref)
    del hint["outcome"]
    unstated = engine.snapshot_from_delivery({"data": hint})
    assert unstated.status != "completed"

    assert await pipeline._record_outcome(tenant_id, call_id, unstated) != "missed"


async def test_a_finished_post_call_job_does_not_hold_its_id_against_a_later_delivery() -> None:
    """The job id dedupes runs that overlap; a run that has finished must not swallow the
    next delivery's (arq refuses an id whose result key is still kept)."""
    registered = next(
        f
        for f in WorkerSettings.functions
        if getattr(f, "name", getattr(f, "__name__", "")) == pipeline.POSTCALL_JOB
    )
    runs = 0

    async def counting(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        nonlocal runs
        runs += 1
        return "ok"

    keep = registered.keep_result_s if isinstance(registered, Function) else None
    queue_name = f"arq:test-postcall-{uuid.uuid4().hex[:8]}"
    worker = Worker(
        functions=[func(counting, name=pipeline.POSTCALL_JOB, keep_result=keep)],
        redis_settings=redis_settings(),
        queue_name=queue_name,
        keep_result=WorkerSettings.keep_result,
        burst=True,
        poll_delay=0.01,
        handle_signals=False,
        ctx={},
    )
    redis = await get_queue()
    job_id = job_id_for(pipeline.POSTCALL_JOB, str(uuid.uuid4()))
    try:
        assert await redis.enqueue_job(
            pipeline.POSTCALL_JOB, {}, _job_id=job_id, _queue_name=queue_name
        )
        await worker.main()
        again = await redis.enqueue_job(
            pipeline.POSTCALL_JOB, {}, _job_id=job_id, _queue_name=queue_name
        )
        assert again is not None, "a finished run's id swallowed the later delivery"
        await worker.main()
    finally:
        await worker.close()
    assert runs == 2


async def test_the_repair_script_lists_then_re_drives_a_call_settled_without_turns(
    vendor: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import redrive_empty_calls

    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    await _ingest(ref, execution_id, None)
    first = _queued(vendor)
    await pipeline.run_post_call_pipeline({"job_try": WORKER_MAX_TRIES}, first)
    call_id = UUID(first["call_id"])
    billed = await _usage(tenant_id, call_id)

    queued: list[tuple[str, dict[str, Any]]] = []

    async def _enqueue(job: str, payload: dict[str, Any], **_: Any) -> str:
        queued.append((job, payload))
        return "job"

    monkeypatch.setattr(redrive_empty_calls, "enqueue", _enqueue)
    monkeypatch.setattr(redrive_empty_calls, "get_engine", pipeline.get_engine)
    window = timedelta(hours=2)
    found = await redrive_empty_calls.candidates(window=window, cap=10, only_tenant=tenant_id)
    assert [c.call_id for c in found] == [call_id]
    assert (
        await redrive_empty_calls.run(window=window, cap=10, apply=False, only_tenant=tenant_id)
        == 1
    )
    assert queued == [], "a read-only run queues nothing"

    assert (
        await redrive_empty_calls.run(window=window, cap=10, apply=True, only_tenant=tenant_id) == 1
    )
    [(job, payload)] = queued
    assert job == pipeline.INGEST_JOB

    vendor["get_call"] = _whole(execution_id, ref)
    assert await pipeline.ingest_engine_event({}, payload) == "pipeline_enqueued"
    await pipeline.run_post_call_pipeline({"job_try": 1}, _queued(vendor))
    call = await _call(tenant_id, call_id)
    assert call["turns"] == 3
    assert call["summary_state"] == "ready"
    assert await _usage(tenant_id, call_id) == billed
    assert await redrive_empty_calls.candidates(window=window, cap=10, only_tenant=tenant_id) == []


async def _settle_with_turns(vendor: dict[str, Any]) -> tuple[UUID, UUID, str, str]:
    tenant_id, ref, execution_id = await _staged(vendor)
    vendor["get_call"] = _whole(execution_id, ref)
    await _ingest(ref, execution_id, None)
    job = _queued(vendor)
    assert await pipeline.run_post_call_pipeline({"job_try": 1}, job) == "ok"
    return tenant_id, UUID(job["call_id"]), ref, execution_id


async def test_a_run_without_the_transcript_reads_the_stored_turns_not_a_silence(
    vendor: dict[str, Any],
) -> None:
    """21 Oct 2026: a run whose reading of the call held no transcript reached extraction
    after another run had stored the turns, took the no-words shortcut and wrote "hung up
    early" on an answered call. The stored turns are the call's words."""
    tenant_id, call_id, ref, execution_id = await _settle_with_turns(vendor)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM call_extractions WHERE call_id = :c"), {"c": call_id}
        )
    reads = len(vendor["spy"].inputs)
    vendor["get_call"] = _whole(execution_id, ref, transcript=False)
    await _ingest(ref, execution_id, None)
    await pipeline.run_post_call_pipeline({"job_try": 1}, _queued(vendor))
    fresh = vendor["spy"].inputs[reads:]
    assert fresh and fresh[-1].strip(), "the extraction read a silence over a stored call"
    assert (await _call(tenant_id, call_id))["outcome"] != "hung_up_early"


async def test_a_stored_no_words_reading_over_a_conversation_is_read_again(
    vendor: dict[str, Any],
) -> None:
    """The no-words row was newer than the turns, so the "turn written after the row"
    guard reused it on every re-drive; a hung_up_early reading over caller speech is not
    reused."""
    tenant_id, call_id, ref, execution_id = await _settle_with_turns(vendor)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE call_extractions SET outcome_hint = 'hung_up_early', "
                "updated_at = now() + interval '1 second' WHERE call_id = :c"
            ),
            {"c": call_id},
        )
    reads = len(vendor["spy"].inputs)
    await _ingest(ref, execution_id, None)
    await pipeline.run_post_call_pipeline({"job_try": 1}, _queued(vendor))
    assert len(vendor["spy"].inputs) > reads, "the no-words reading was reused"


async def test_the_repair_script_re_drives_a_call_whose_reading_never_settled(
    vendor: dict[str, Any],
) -> None:
    """23 Oct 2026: the post-call job was cancelled at its time limit inside the reading, so
    the call kept its turns but its summary stayed `pending` and it was never metered."""
    from scripts import redrive_empty_calls

    tenant_id, call_id, _ref, _execution_id = await _settle_with_turns(vendor)
    window = timedelta(hours=2)
    assert await redrive_empty_calls.candidates(window=window, cap=10, only_tenant=tenant_id) == []
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET summary_state = 'pending' WHERE id = :c"), {"c": call_id}
        )
    found = await redrive_empty_calls.candidates(window=window, cap=10, only_tenant=tenant_id)
    assert [c.call_id for c in found] == [call_id]

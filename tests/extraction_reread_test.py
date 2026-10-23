"""A call whose reading failed at the provider is read again, a few times, within a day (D-841).

The founder's 20 Oct test call read "No outcome" because `extract_call` stored a provider
failure (`errors._model`) as the call's extraction and nothing ever re-drove it: the poller and
the stall alarm both took any `call_extractions` row as done.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.workers import dispatcher, extraction_reread, pipeline
from calevate_shared.extraction import ExtractionOutput
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _outbox_rows, _run_pipeline, _stub_storage
from tests.postcall_crm_events_test import BROWSING, READY, give_agent_outcomes, reads_as, subscribe

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
_stub_storage = _stub_storage


async def _provider_fails(*_args: Any, **_kw: Any) -> ExtractionOutput:
    return ExtractionOutput(valid=False, errors={"_model": "ReadTimeout"})


async def _failed_call(
    label: str, monkeypatch: pytest.MonkeyPatch, *, events: list[str] | None = None
) -> tuple[UUID, UUID]:
    """A completed call whose pipeline ran while the provider was failing, ended 20 min ago."""
    tenant_id, execution_id, call_id = await _completed_call(label)
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    if events:
        await subscribe(tenant_id, events)
    monkeypatch.setattr(pipeline, "extract_call", _provider_fails)
    await _run_pipeline(tenant_id, call_id, execution_id)
    await _age(tenant_id, call_id, minutes=20)
    return tenant_id, call_id


async def _age(tenant_id: UUID, call_id: UUID, *, minutes: int) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET ended_at = now() - make_interval(mins => :m) WHERE id = :c"),
            {"m": minutes, "c": call_id},
        )


async def _row(tenant_id: UUID, call_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ce.errors, ce.reread_attempts, c.outcome_tag, c.business_outcome "
                    "FROM call_extractions ce JOIN calls c ON c.id = ce.call_id "
                    "WHERE ce.call_id = :c"
                ),
                {"c": call_id},
            )
        ).one()
    return {"errors": row[0] or {}, "attempts": row[1], "outcome": row[2], "business": row[3]}


def _payload(tenant_id: UUID, call_id: UUID) -> dict[str, str]:
    return {"tenant_id": str(tenant_id), "call_id": str(call_id)}


async def _stalled(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return await dispatcher._count_stalled(session)


async def test_a_failed_reading_is_read_again_and_the_crm_hears_the_new_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _failed_call(
        "reread", monkeypatch, events=["call.completed", "call.updated"]
    )
    assert await _stalled(tenant_id) == 1, "a provider failure is not an extraction"

    queued: list[tuple[str, dict[str, Any], str | None]] = []

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        queued.append((job, payload, job_id))
        return job_id or job

    monkeypatch.setattr(extraction_reread, "enqueue", _enqueue)
    # Other tests' failed calls share the database; let this sweep reach every one.
    monkeypatch.setattr(extraction_reread, "REREAD_PER_SWEEP", 100_000)
    result = await extraction_reread.sweep_failed_extractions({})
    assert (extraction_reread.REREAD_JOB, _payload(tenant_id, call_id)) in [
        (job, payload) for job, payload, _id in queued
    ], result

    reads_as(monkeypatch, "ready_to_buy")
    assert await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id)) == (
        "reread"
    )

    row = await _row(tenant_id, call_id)
    assert "_model" not in row["errors"]
    assert row["attempts"] == 1
    assert row["business"] == "ready_to_buy"
    assert await _stalled(tenant_id) == 0
    assert len(await _outbox_rows("notify_hot_lead", {"call_id": str(call_id)})) == 1
    updated = await _outbox_rows(
        "deliver_outbound_webhook", {"event": "call.updated", "data": {"call_id": str(call_id)}}
    )
    assert [u["data"]["business_outcome"] for u in updated] == ["ready_to_buy"]
    completed = await _outbox_rows(
        "deliver_outbound_webhook", {"event": "call.completed", "data": {"call_id": str(call_id)}}
    )
    assert len(completed) == 1, "call.completed went out once, before the re-read"

    # Read: nothing left to do, however often it is asked.
    assert await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id)) == (
        "not_due"
    )


async def test_a_reading_that_keeps_failing_stops_at_the_cap_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _failed_call("cap", monkeypatch)
    fired: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        extraction_reread, "alert", lambda stage, code, **kw: fired.append((stage, code, kw))
    )

    for attempt in range(1, extraction_reread.REREAD_MAX_ATTEMPTS + 1):
        outcome = await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))
        assert outcome == "still_failed"
        assert (await _row(tenant_id, call_id))["attempts"] == attempt
        # Too soon for another try...
        assert (
            await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))
            == "not_due"
        )
        # ...until the spacing has passed.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE call_extractions SET reread_at = now() - interval '31 minutes' "
                    "WHERE call_id = :c"
                ),
                {"c": call_id},
            )

    assert (
        await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))
        == "not_due"
    ), "never past the cap"

    # The sweep walks every tenant in the shared database, so what it queues and which call
    # the alarm names are asserted about this tenant's call only.
    queued: list[dict[str, Any]] = []

    async def _enqueue(_job: str, payload: dict[str, Any], **_k: Any) -> str:
        queued.append(payload)
        return "queued"

    monkeypatch.setattr(extraction_reread, "enqueue", _enqueue)
    await extraction_reread.sweep_failed_extractions({})
    assert _payload(tenant_id, call_id) not in queued, "an exhausted call is not queued again"
    assert any(code == "extraction_reread_exhausted" for _s, code, _kw in fired), (
        "a call still unread after every try is an alarm"
    )
    async with tenant_session(tenant_id) as session:
        assert await extraction_reread.exhausted_rereads(session, now=_now()) == [call_id]


async def test_a_call_past_the_day_or_too_young_is_not_read_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _failed_call("window", monkeypatch)

    await _age(tenant_id, call_id, minutes=25 * 60)
    assert (
        await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))
        == "not_due"
    )

    async with tenant_session(tenant_id) as session:
        assert await extraction_reread.due_rereads(session, now=_now()) == []
        await session.execute(
            text("UPDATE calls SET ended_at = now() WHERE id = :c"), {"c": call_id}
        )
        assert await extraction_reread.due_rereads(session, now=_now()) == [], (
            "inside the pipeline's own grace a call may still be mid-retry"
        )


def _now() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=1)


async def test_a_call_the_rereads_gave_up_on_stops_paging_that_leads_are_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """21-22 Oct 2026: `postcall_pipeline_stalled` paged on every tick for 43 hours. A
    provider-failed reading past its last re-read was still "owed" to the stall alarm until
    a day after the call ended, though nothing automatic would ever change it."""
    tenant_id, call_id = await _failed_call("gaveup", monkeypatch)

    async def _this_tenant() -> list[UUID]:
        return [tenant_id]

    fired: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(dispatcher, "callable_tenants", _this_tenant)
    monkeypatch.setattr(dispatcher, "alert", lambda _stage, code, **kw: fired.append((code, kw)))

    assert await dispatcher.report_stalled_pipeline({}) == "stalled=1 unreached=0"
    assert fired[-1][0] == "postcall_pipeline_stalled"
    assert fired[-1][1]["call_id"] == str(call_id), "the page names a call to look up"
    assert fired[-1][1]["tenant_id"] == str(tenant_id)

    async def _set(assignment: str) -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(f"UPDATE call_extractions SET {assignment} WHERE call_id = :c"),
                {"c": call_id},
            )

    await _set(f"reread_attempts = {extraction_reread.REREAD_MAX_ATTEMPTS - 1}")
    assert await _stalled(tenant_id) == 1, "a re-read is still to come"

    await _set(f"reread_attempts = {extraction_reread.REREAD_MAX_ATTEMPTS}")
    assert await _stalled(tenant_id) == 0, "spent tries are extraction_reread_exhausted's"
    fired.clear()
    assert await dispatcher.report_stalled_pipeline({}) == "stalled=0 unreached=0"
    assert fired == []
    async with tenant_session(tenant_id) as session:
        assert await extraction_reread.exhausted_rereads(session, now=_now()) == [call_id]

    # The runbook's repair puts the call back in the re-read's hands, and in this count.
    await _set("reread_attempts = 0")
    assert await _stalled(tenant_id) == 1

    await _set("scrubbed_at = now()")
    assert await _stalled(tenant_id) == 0, "a destroyed reading is never read again"

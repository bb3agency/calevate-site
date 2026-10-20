"""Calls whose reading failed at the provider are read again, a few times, within a day (D-841).

`extract_call` answers a provider failure (a timeout, a 5xx, a reply in a shape we cannot
read) with `errors = {"_model": <type>}` so the call, its lead and its metering still land.
That row counts as the call's extraction, so nothing re-drove it: the call kept "No outcome",
no summary from the model and no business outcome for good (the founder's 20 Oct test call).

This sweep finds those calls and reads each one again through the pipeline's own stages and
no others: the extraction with its key moments, the summary, the outcome, the business
outcome, the lead and its hot alert. No recording copy, no transcript write, no call
metering, no `call.completed`. The model pass is metered under
`ASSIST_FEATURE_CALL_EXTRACTION`, which is ours and never counted against the client's
allowance (`billing.models.ABSORBED_ASSIST_FEATURES`), exactly as the first pass was.

The transcript read again is the one we stored, not a fresh engine read: it is what the
first pass read, and a re-read must not depend on the platform still holding the call.

Each call gets at most `REREAD_MAX_ATTEMPTS`, at least `REREAD_SPACING` apart, until
`REREAD_WINDOW` after it ended. The attempt is claimed by compare-and-swap on
`call_extractions.reread_attempts` before the model is asked, so two runs cannot both spend
one. A re-read that changes the call's outcome sends the client's CRM `call.updated`.

Ids and counts only in logs and alarms (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import CallDirection, CallStatus, Speaker, TranscriptTurn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.optout import detect_opt_out
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.db.session import tenant_session
from apps.api.integrations import service as integrations
from apps.workers.extraction import MODEL_FAILURE, model_answered
from apps.workers.pipeline import (
    PIPELINE_STALL_AFTER,
    _agent_business_outcomes,
    _extract_stage,
    _load_call_context,
    _maybe_notify_hot_lead,
    _record_business_outcome,
    _record_outcome,
    _record_reading,
    _upsert_lead,
    call_event_data,
    callable_tenants,
    extractor_transcript,
)

log = get_logger(__name__)

#: The arq name of one call's re-read.
REREAD_JOB: Final = "reread_call_extraction"

#: Re-reads one call gets. A provider outage of an hour or two is covered by three spaced
#: tries; a call the model fails on three times is a call a person should look at.
REREAD_MAX_ATTEMPTS: Final = 3

#: Time between two re-reads of one call, so three tries span an outage rather than one
#: minute of it.
REREAD_SPACING: Final = timedelta(minutes=30)

#: How long after a call ended it is still re-read (founder, 20 Oct 2026).
REREAD_WINDOW: Final = timedelta(hours=24)

#: Re-reads one sweep queues, oldest call first: each is a paid model round trip, and a
#: provider that has just failed hundreds of calls should not get them all at once.
REREAD_PER_SWEEP: Final = 50

#: Minutes past the hour the sweep runs: every 30 minutes, matching `REREAD_SPACING`, on
#: minutes no other cron uses.
REREAD_SWEEP_MINUTES: Final = frozenset({6, 36})

#: A completed call whose stored extraction is a provider failure. `ce.scrubbed_at` and the
#: erasure columns leave out a call whose data was destroyed: there is nothing to re-read,
#: and reading it again would bring erased words back. Runs in a `tenant_session`.
_FAILED_READ_SQL: Final = (
    "FROM call_extractions ce "
    "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
    "WHERE c.status = 'completed' "
    "  AND (ce.errors ->> :model_failure) IS NOT NULL "
    "  AND ce.scrubbed_at IS NULL "
    "  AND c.erased_subject_ref IS NULL "
    "  AND NOT EXISTS (SELECT 1 FROM tenant_erasure_requests e WHERE e.tenant_id = c.tenant_id) "
    "  AND COALESCE(c.ended_at, c.created_at) < :settled_before "
    "  AND COALESCE(c.ended_at, c.created_at) > :window_start "
)

_DUE_SQL: Final = (
    "SELECT ce.call_id, ce.reread_attempts "
    + _FAILED_READ_SQL
    + "AND ce.reread_attempts < :max_attempts "
    "AND (ce.reread_at IS NULL OR ce.reread_at < :spaced_before) "
    "ORDER BY COALESCE(c.ended_at, c.created_at), ce.call_id"
)

_EXHAUSTED_SQL: Final = (
    "SELECT ce.call_id " + _FAILED_READ_SQL + "AND ce.reread_attempts >= :max_attempts "
    "ORDER BY COALESCE(c.ended_at, c.created_at), ce.call_id"
)

#: The CAS that spends one attempt: only while the row is still a provider failure, under
#: the cap, past the spacing and inside the window.
_CLAIM_SQL: Final = (
    "UPDATE call_extractions ce SET reread_attempts = ce.reread_attempts + 1, "
    "reread_at = now(), updated_at = now() "
    "FROM calls c WHERE c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
    "AND ce.call_id = :cid "
    "AND c.status = 'completed' "
    "AND (ce.errors ->> :model_failure) IS NOT NULL "
    "AND ce.scrubbed_at IS NULL "
    "AND c.erased_subject_ref IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM tenant_erasure_requests e WHERE e.tenant_id = c.tenant_id) "
    "AND COALESCE(c.ended_at, c.created_at) > :window_start "
    "AND ce.reread_attempts < :max_attempts "
    "AND (ce.reread_at IS NULL OR ce.reread_at < :spaced_before) "
    "RETURNING ce.reread_attempts"
)


@dataclass(frozen=True, slots=True)
class FailedRead:
    call_id: UUID
    attempts: int


def _binds(now: datetime) -> dict[str, Any]:
    return {
        "model_failure": MODEL_FAILURE,
        "settled_before": now - PIPELINE_STALL_AFTER,
        "window_start": now - REREAD_WINDOW,
        "spaced_before": now - REREAD_SPACING,
        "max_attempts": REREAD_MAX_ATTEMPTS,
    }


async def due_rereads(session: AsyncSession, *, now: datetime) -> list[FailedRead]:
    """This tenant's failed readings due another try, oldest call first."""
    rows = (await session.execute(text(_DUE_SQL), _binds(now))).all()
    return [FailedRead(call_id=row[0], attempts=int(row[1])) for row in rows]


async def exhausted_rereads(session: AsyncSession, *, now: datetime) -> list[UUID]:
    """This tenant's calls still unread after every try, inside the window."""
    rows = (await session.execute(text(_EXHAUSTED_SQL), _binds(now))).all()
    return [row[0] for row in rows]


def reread_job_id(tenant_id: UUID, call_id: UUID, attempt: int) -> str:
    """One id per (call, attempt), so a queued try is not queued twice and the next one is
    not refused by the last one's kept result."""
    return job_id_for(REREAD_JOB, str(tenant_id), str(call_id), str(attempt))


async def _stored_snapshot(tenant_id: UUID, call_id: UUID) -> ExecutionSnapshot | None:
    """The call as the first pass saw it, rebuilt from what we stored of it."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_call_id, status, direction, duration_s, from_e164, to_e164, "
                    "started_at, ended_at, "
                    "CASE WHEN summary_source = 'engine' THEN summary END "
                    "FROM calls WHERE id = :cid AND tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            return None
        turns = (
            await session.execute(
                text(
                    "SELECT idx, speaker, text, lang, start_ms, end_ms, start_approximate "
                    "FROM transcript_turns WHERE call_id = :cid AND tenant_id = :tid "
                    "ORDER BY idx"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).all()
    status = cast(CallStatus, str(row[1]))
    return ExecutionSnapshot(
        engine_call_id=str(row[0]),
        status=status,
        raw_status=status,
        terminal=True,
        billable_ready=True,
        direction=cast(CallDirection, str(row[2])),
        duration_s=row[3],
        from_e164=row[4],
        to_e164=row[5],
        started_at=row[6],
        ended_at=row[7],
        engine_summary=row[8],
        transcript=[
            TranscriptTurn(
                call_id=str(call_id),
                idx=int(t[0]),
                speaker=cast(Speaker, str(t[1])),
                text=str(t[2] or ""),
                lang=t[3],
                start_ms=t[4],
                end_ms=t[5],
                start_approximate=bool(t[6]),
            )
            for t in turns
        ],
    )


async def _outcomes_now(tenant_id: UUID, call_id: UUID) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT outcome_tag, business_outcome FROM calls "
                    "WHERE id = :cid AND tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
    return (row[0], row[1]) if row is not None else (None, None)


async def reread_extraction(tenant_id: UUID, call_id: UUID) -> str:
    """Read one call again and file what the reading changes. Returns `still_failed`,
    `reread` or `call_not_found`.

    The attempt has already been claimed; this does the reading. Each stage is the
    pipeline's own and is safe to run again: the extraction is one row per call, the lead
    files a call once (`_upsert_lead`), and the hot alert is queued once per lead per call.
    """
    snapshot = await _stored_snapshot(tenant_id, call_id)
    if snapshot is None:
        return "call_not_found"
    spec, schema_version, agent_id, direction, _disclosure, _notice = await _load_call_context(
        tenant_id, call_id
    )
    before = await _outcomes_now(tenant_id, call_id)
    business_outcomes = await _agent_business_outcomes(tenant_id, agent_id)
    extraction = await _extract_stage(
        tenant_id,
        call_id,
        snapshot,
        spec=spec,
        agent_id=agent_id,
        transcript_text=extractor_transcript(snapshot.transcript),
        opt_out_signal=detect_opt_out(snapshot.transcript) if snapshot.transcript else None,
        business_outcomes=business_outcomes,
    )
    if extraction is None or not model_answered(extraction):
        return "still_failed"

    reading = await _record_reading(tenant_id, call_id, snapshot, extraction)
    call_outcome = await _record_outcome(tenant_id, call_id, snapshot)
    business_outcome = await _record_business_outcome(tenant_id, call_id, business_outcomes)
    lead_id = await _upsert_lead(
        tenant_id,
        agent_id,
        call_id,
        snapshot,
        direction=direction,
        data=extraction.data,
        schema_version=schema_version,
        outcome=call_outcome,
        reading=extraction,
        business_move=business_outcome.lead_status if business_outcome else None,
    )
    if lead_id is not None:
        await _maybe_notify_hot_lead(
            tenant_id,
            lead_id,
            call_id,
            business_outcome,
            connected=snapshot.status == "completed",
        )

    after = (call_outcome, business_outcome.key if business_outcome else None)
    if after != before:
        async with tenant_session(tenant_id) as session:
            await integrations.enqueue_event(
                session,
                tenant_id=tenant_id,
                event=integrations.CALL_UPDATED_EVENT,
                data=call_event_data(
                    call_id,
                    lead_id=lead_id,
                    direction=direction,
                    duration_s=snapshot.duration_s,
                    outcome=call_outcome,
                    extraction=extraction,
                    summary=reading.summary,
                    business_outcome=business_outcome,
                ),
            )
    return "reread"


async def reread_call_extraction(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim one attempt for this call, then read it again. `not_due` when the claim finds
    the call already read, at its cap, too soon after the last try or past the window."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(text(_CLAIM_SQL), {"cid": call_id, **_binds(datetime.now(UTC))})
        ).first()
    if claimed is None:
        return "not_due"
    outcome = await reread_extraction(tenant_id, call_id)
    log.info(
        "extraction_reread",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "attempt": int(claimed[0]),
            "outcome": outcome,
        },
    )
    return outcome


async def _queue(found: list[tuple[UUID, FailedRead]]) -> tuple[int, int, int]:
    """Queue the oldest `REREAD_PER_SWEEP`. Returns (queued, already queued, not queued);
    the first enqueue failure stops the loop, as every later one would wait out the same
    Redis timeout."""
    queued = pending = 0
    batch = found[:REREAD_PER_SWEEP]
    for index, (tenant_id, read) in enumerate(batch):
        try:
            job = await enqueue(
                REREAD_JOB,
                {"tenant_id": str(tenant_id), "call_id": str(read.call_id)},
                job_id=reread_job_id(tenant_id, read.call_id, read.attempts + 1),
            )
        except Exception:
            log.exception(
                "extraction_reread_enqueue_failed",
                extra={"tenant_id": str(tenant_id), "call_id": str(read.call_id)},
            )
            return queued, pending, len(batch) - index
        if job is None:
            pending += 1
        else:
            queued += 1
    return queued, pending, 0


async def sweep_failed_extractions(ctx: dict[str, Any]) -> str:
    """Every 30 minutes: queue a re-read for each failed reading that is due one, and alarm
    on the calls still unread after every try.

    Same shape as `recording_watch.report_missing_recordings`: each tenant is asked in its
    own session, one tenant's failure is counted as unreached and the sweep goes on, and an
    unreached tenant alarms, because a sweep that could not look reads exactly like one that
    found nothing.
    """
    del ctx
    now = datetime.now(UTC)
    due: list[tuple[UUID, FailedRead]] = []
    exhausted: list[tuple[UUID, UUID]] = []
    unreached = 0
    tenants = await callable_tenants()
    for tenant_id in tenants:
        try:
            async with tenant_session(tenant_id) as session:
                due.extend((tenant_id, read) for read in await due_rereads(session, now=now))
                exhausted.extend(
                    (tenant_id, call_id) for call_id in await exhausted_rereads(session, now=now)
                )
        except Exception:
            # The id, never the exception's payload: a psycopg error can quote the row.
            log.exception("extraction_reread_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue

    queued, pending, not_queued = await _queue(due)
    if exhausted or unreached or not_queued:
        detail = (
            f"{len(exhausted)} call(s) are still unread after {REREAD_MAX_ATTEMPTS} re-reads "
            f"within {int(REREAD_WINDOW.total_seconds() // 3600)} hours of ending"
        )
        if not_queued:
            detail += f"; {not_queued} re-read(s) due could not be queued"
        if unreached:
            detail += (
                f"; {unreached} of {len(tenants)} tenant(s) could not be checked, so the "
                "count is a floor rather than a total"
            )
        ids = (
            {"tenant_id": str(exhausted[0][0]), "call_id": str(exhausted[0][1])}
            if exhausted
            else {}
        )
        alert("WORKER_STALL", "extraction_reread_exhausted", detail=detail, **ids)
    return (
        f"due={len(due)} queued={queued} already_queued={pending} not_queued={not_queued} "
        f"exhausted={len(exhausted)} unreached={unreached}"
    )


__all__ = [
    "REREAD_JOB",
    "REREAD_MAX_ATTEMPTS",
    "REREAD_PER_SWEEP",
    "REREAD_SPACING",
    "REREAD_SWEEP_MINUTES",
    "REREAD_WINDOW",
    "due_rereads",
    "exhausted_rereads",
    "reread_call_extraction",
    "reread_extraction",
    "reread_job_id",
    "sweep_failed_extractions",
]

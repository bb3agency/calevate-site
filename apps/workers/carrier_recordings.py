"""Carrier-held call recordings, copied into OUR `recordings/` (D-668).

    voice-runtime claims `RecordStop` → ingest_carrier_event → note_recording
      → copy_carrier_recording: resolve by id at the carrier → fetch → our bucket
        → `calls.recording_url` = our key (dashboard playback, exports, CRM link)
        → `call.recording_ready` to the client's opted-in webhooks (D-670)
    reconcile_carrier_recordings (cron): re-enqueue uncopied, find unreported, page overdue;
      queue the expiry of every carrier copy whose twin has been ours for a day
    expire_carrier_recording: HEAD our copy, then delete the carrier's (D-670)
    delete_carrier_recordings: an erasure's deletion of the carrier's copy

WHY THE CARRIER'S COPY GOES AFTER A DAY (founder, 3 Oct 2026). Once ours exists, the
carrier's is a second store of the caller's voice that we neither need nor control. A day is
the margin for finding that our copy is bad (a truncated or unplayable file) while the
carrier's can still be fetched again. The deletion is driven by the 20-minute sweep rather
than by a job deferred 24 hours: a deferred arq job lives only in Redis, so a flush or a lost
volume would forget it silently, while the sweep re-derives the work from `calls` every run.

WHY PROMPTLY, AND WHY THE ALARM IS HOURS AWAY RATHER THAN DAYS. Vobiz's recordings pages
say 30 days (`vobiz-findings/mirror/pages/platform/voice/recordings.md:9,21`), but the same
page's own screenshot shows a "Storage Life" of 3 days (`:18`), and the API says only that
recording URLs "may be temporary" (`recording/recording-object.md:139`). The conflict is
UNRESOLVED (`docs/evidence/vobiz-api-contract.md` §9a), so this module is built to the
shorter reading: the copy runs on the callback, retries over minutes, and
`carrier_recording_copy_overdue` pages at `COPY_OVERDUE_AFTER`, long before three days.

WHY THE API AND NOT THE CALLBACK'S URL. `RecordStop` carries `RecordUrl`/`RecordFile`, but
the vendor tells integrators to download from the `recording_url` the retrieve call returns
(`recording/download-recording.md:43`), and the retrieve call also names the call the
recording belongs to, which is checked before a byte is fetched. voice-runtime does not
even forward the URL (`carrier_events._NEVER_FORWARDED`).

HARD RULE 6. Only the carrier's opaque recording id is stored (`calls.carrier_recording_id`,
CHECK-constrained to an id shape); the download URL lives for one fetch and is never logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierRecording, carrier_of_record, get_carrier
from apps.api.integrations import service as integrations
from apps.workers import storage
from apps.workers.pipeline import _is_transient, callable_tenants

log = get_logger(__name__)

COPY_JOB: Final = "copy_carrier_recording"
DELETE_JOB: Final = "delete_carrier_recordings"
EXPIRE_JOB: Final = "expire_carrier_recording"

#: How long the carrier's copy outlives ours (founder, 3 Oct 2026).
CARRIER_COPY_KEPT_FOR: Final = timedelta(hours=24)

#: A carrier copy still not deleted this long after ours landed pages. A day of sweeps
#: (72 runs, each re-queueing the expiry) past the deadline is not a blip.
CARRIER_DELETE_OVERDUE_AFTER: Final = timedelta(hours=48)

#: Backoff between the copy's own attempts. Minutes, not hours: the carrier's retention is
#: unresolved and may be as short as three days (module docstring).
COPY_RETRY_BACKOFF_S: Final[tuple[float, ...]] = (60.0, 300.0)

#: A recording reported and still not ours after this long pages. Six hours is a working
#: day's worth of retries (the sweep re-queues every 20 minutes and arq keeps a finished
#: job's id for an hour) and leaves the whole of the shorter three-day reading to act in.
COPY_OVERDUE_AFTER: Final = timedelta(hours=6)

#: How far back the sweep still asks the carrier for a recording. The LONGER reading of its
#: retention: past it there is nothing left to fetch whichever reading is right.
CARRIER_RETENTION_HORIZON: Final = timedelta(days=30)

#: The window in which a finished, recorded-eligible call with no `RecordStop` yet is looked
#: up by its call id, so a callback the carrier never delivered still reaches us. It opens
#: after the callback has had time to arrive and is narrow so each call is asked about
#: two or three times, not once per sweep for a month.
UNREPORTED_AFTER: Final = timedelta(minutes=10)
UNREPORTED_BEFORE: Final = timedelta(minutes=70)

RECORDING_SWEEP_MINUTES: Final = frozenset({11, 31, 51})
SWEEP_PER_TENANT: Final = 50
SWEEP_BUDGET: Final = 500


def _ladder(attempt: int) -> float:
    return COPY_RETRY_BACKOFF_S[max(0, min(attempt, len(COPY_RETRY_BACKOFF_S)) - 1)]


# --- the callback ---------------------------------------------------------------------


async def note_recording(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, recording: CarrierRecording
) -> bool:
    """Store the carrier's recording id on the call. True when this call now names it.

    The first id stands, as for every identity column on `calls`; a second, different one
    is logged rather than adopted. An erased call takes none: the subject's audio must not
    be re-acquired, and `copy_carrier_recording` deletes the carrier's copy instead.
    """
    row = (
        await session.execute(
            text(
                "UPDATE calls SET carrier_recording_id = :rid, updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid AND carrier_recording_id IS NULL "
                "RETURNING id"
            ),
            {"rid": recording.recording_id, "cid": call_id, "tid": tenant_id},
        )
    ).first()
    if row is not None:
        return True
    held = (
        await session.execute(
            text("SELECT carrier_recording_id FROM calls WHERE id = :cid AND tenant_id = :tid"),
            {"cid": call_id, "tid": tenant_id},
        )
    ).scalar()
    if held != recording.recording_id:
        log.warning(
            "carrier_recording_id_disagrees",
            extra={"call_id": str(call_id), "recording_id": recording.recording_id},
        )
        return False
    return True


def report_short_recording(*, tenant_id: UUID, call_id: UUID, recording: CarrierRecording) -> None:
    """A recording that stopped before the call did (silence timeout, length cap or a
    keypress, `xml/record.md:57-62`). The audio we keep is then not the whole call."""
    if recording.ended_with_call:
        return
    alert(
        "WORKER_TERMINAL",
        "carrier_recording_ended_early",
        detail=(
            f"the carrier stopped recording with reason {recording.end_reason!r}, so the "
            "stored recording is shorter than the call"
        ),
        tenant_id=str(tenant_id),
        call_id=str(call_id),
    )


async def enqueue_copy(
    *, tenant_id: UUID, call_id: UUID, defer_s: float | None = None
) -> str | None:
    """Queue the copy for one call, keyed per call so the callback and the sweep collapse."""
    return await enqueue(
        COPY_JOB,
        {"tenant_id": str(tenant_id), "call_id": str(call_id)},
        job_id=job_id_for(COPY_JOB, str(call_id)),
        **({"_defer_by": defer_s} if defer_s else {}),
    )


# --- the copy -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CopyTarget:
    tenant_id: UUID
    call_id: UUID


def _copy_target(payload: dict[str, Any]) -> _CopyTarget:
    try:
        return _CopyTarget(
            tenant_id=UUID(str(payload["tenant_id"])), call_id=UUID(str(payload["call_id"]))
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="carrier_recording_payload_invalid",
            title="A recording copy could not be read",
            detail="The recording copy job was enqueued without a usable tenant or call id.",
        ) from exc


async def copy_carrier_recording(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Copy one call's carrier recording into our bucket, at most once.

    Idempotent: `recording_url` set means ours already, and the key is a pure function of
    (tenant, call) (`storage.recording_key`), so two overlapping runs PUT the same bytes to
    the same key. A run that exhausts its tries is alarmed and left to the sweep.
    """
    attempt = int(ctx.get("job_try", 1))
    target = _copy_target(payload)
    try:
        return await _copy(target)
    except storage.StorageUnavailableError as exc:
        # Before `except Retry`: it IS a `Retry` (with its own 30 s defer), and re-raising it
        # as one would let arq finish the last try silently instead of alarming.
        return _retry_or_report(target, exc, attempt, transient=True)
    except Retry:
        raise
    except Exception as exc:
        return _retry_or_report(target, exc, attempt, transient=_is_transient(exc))


def _retry_or_report(target: _CopyTarget, exc: Exception, attempt: int, *, transient: bool) -> str:
    if transient and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_ladder(attempt)) from exc
    alert(
        "WORKER_DELIVERY",
        "carrier_recording_copy_failed",
        detail=(
            f"{type(exc).__name__} after {attempt} attempt(s); the sweep retries it, and "
            "carrier_recording_copy_overdue pages if it is still not ours"
            if transient
            else f"{type(exc).__name__} is permanent, not retried"
        ),
        tenant_id=str(target.tenant_id),
        call_id=str(target.call_id),
    )
    return "copy_failed"


async def _copy(target: _CopyTarget) -> str:
    async with tenant_session(target.tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT carrier, carrier_call_id, carrier_recording_id, recording_url, "
                    "erased_subject_ref FROM calls WHERE id = :cid AND tenant_id = :tid"
                ),
                {"cid": target.call_id, "tid": target.tenant_id},
            )
        ).first()
    if row is None:
        return "no_call"
    carrier_name, carrier_call_id, recording_id, ours, erased = row
    if ours:
        return "already_copied"
    if not recording_id or not carrier_call_id:
        return "no_recording"
    carrier = carrier_of_record(carrier_name)
    if erased is not None:
        # The subject was erased before the copy ran: their voice is not re-acquired, and
        # the carrier's copy goes the way the erasure would have sent it.
        await enqueue_carrier_deletion(
            carrier=carrier, recording_ids=[str(recording_id)], tenant_id=target.tenant_id
        )
        return "erased_not_copied"

    source = await get_carrier(carrier).recording_source(
        str(recording_id), carrier_call_id=str(carrier_call_id)
    )
    if source is None:
        alert(
            "WORKER_TERMINAL",
            "carrier_recording_lost",
            detail=(
                f"carrier={carrier} no longer holds this call's recording and we never "
                "copied it: the audio is gone"
            ),
            tenant_id=str(target.tenant_id),
            call_id=str(target.call_id),
        )
        return "lost"
    key = await storage.copy_recording(
        source_url=source.url,
        tenant_id=target.tenant_id,
        call_id=target.call_id,
        leg="call",
        auth_headers=source.auth_headers,
        auth_hosts=source.auth_hosts,
    )
    async with tenant_session(target.tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "UPDATE calls SET recording_url = :key, recording_copied_at = now(), "
                    "updated_at = now() "
                    "WHERE id = :cid AND tenant_id = :tid AND recording_url IS NULL "
                    "AND erased_subject_ref IS NULL RETURNING id"
                ),
                {"key": key, "cid": target.call_id, "tid": target.tenant_id},
            )
        ).first()
        if stored is not None:
            # Only the run that set the pointer tells the client's CRM, in the same
            # transaction, so the event and the pointer it links to commit together.
            await integrations.enqueue_event(
                session,
                tenant_id=target.tenant_id,
                event=integrations.RECORDING_READY_EVENT,
                data={"call_id": str(target.call_id)},
            )
    if stored is None:
        # Erased while the bytes were in flight. The object would name nobody's pointer,
        # which is the one shape no sweep and no erasure can reach, so it goes now.
        await storage.delete_objects([key])
        return "erased_during_copy"
    log.info("carrier_recording_copied", extra={"call_id": str(target.call_id)})
    return "copied"


# --- the carrier's copy, on erasure ---------------------------------------------------


async def enqueue_carrier_deletion(
    *, carrier: str, recording_ids: list[str], tenant_id: UUID
) -> str | None:
    """Queue the deletion of the carrier's copies. Not keyed: two erasures of overlapping
    calls each delete what they name, and a repeated delete is answered "already gone"."""
    if not recording_ids:
        return None
    return await enqueue(
        DELETE_JOB,
        {"carrier": carrier, "recording_ids": recording_ids, "tenant_id": str(tenant_id)},
    )


async def delete_carrier_recordings(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Delete the carrier's copy of each recording an erasure named.

    The erasure's `telephony` task already quotes these ids, so a failure here is never
    silent: it alarms, and the written request the task tracks covers what was not deleted.
    """
    attempt = int(ctx.get("job_try", 1))
    carrier = carrier_of_record(str(payload.get("carrier") or "") or None)
    ids = [str(i) for i in payload.get("recording_ids") or []]
    deleted = gone = 0
    try:
        client = get_carrier(carrier)
        for recording_id in ids:
            if await client.delete_recording(recording_id):
                deleted += 1
            else:
                gone += 1
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_ladder(attempt)) from exc
        alert(
            "WORKER_DELIVERY",
            "carrier_recording_delete_failed",
            detail=(
                f"carrier={carrier}: {type(exc).__name__} after {attempt} attempt(s) with "
                f"{len(ids) - deleted - gone} of {len(ids)} recording(s) not deleted; the "
                "erasure's telephony task lists their ids for the written request"
            ),
            tenant_id=str(payload.get("tenant_id") or "unknown"),
        )
        return "delete_failed"
    return f"deleted={deleted} already_gone={gone}"


# --- the carrier's copy, one day after ours ---------------------------------------------

_EXPIRY_ROW_SQL: Final = (
    "SELECT carrier, carrier_recording_id, recording_url, carrier_recording_deleted_at, "
    "erased_subject_ref, COALESCE(recording_copied_at, updated_at) <= now() - :kept "
    "FROM calls WHERE id = :cid AND tenant_id = :tid"
)


async def enqueue_expiry(*, tenant_id: UUID, call_id: UUID) -> str | None:
    """Queue the expiry for one call, keyed per call so overlapping sweeps collapse."""
    return await enqueue(
        EXPIRE_JOB,
        {"tenant_id": str(tenant_id), "call_id": str(call_id)},
        job_id=job_id_for(EXPIRE_JOB, str(call_id)),
    )


async def expire_carrier_recording(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Delete the carrier's copy of one call's recording, a day after ours was stored.

    Idempotent: `carrier_recording_deleted_at` set means done, and the carrier answering
    404 is "already gone", stamped the same way. The job re-reads the clock and the call
    itself, so a stale or early enqueue does nothing. A run that exhausts its tries is
    logged and left to the sweep, which re-queues it every 20 minutes and pages through
    `carrier_recording_delete_overdue` at `CARRIER_DELETE_OVERDUE_AFTER`.
    """
    attempt = int(ctx.get("job_try", 1))
    target = _copy_target(payload)
    try:
        return await _expire(target)
    except storage.StorageUnavailableError as exc:
        # Before `except Retry`, for the reason `copy_carrier_recording` gives.
        return _retry_or_log_expiry(target, exc, attempt, transient=True)
    except Retry:
        raise
    except Exception as exc:
        return _retry_or_log_expiry(target, exc, attempt, transient=_is_transient(exc))


def _retry_or_log_expiry(
    target: _CopyTarget, exc: Exception, attempt: int, *, transient: bool
) -> str:
    if transient and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_ladder(attempt)) from exc
    log.warning(
        "carrier_recording_expiry_failed",
        extra={
            "call_id": str(target.call_id),
            "reason": type(exc).__name__,
            "attempts": attempt,
            "permanent": not transient,
        },
    )
    return "expiry_failed"


async def _expire(target: _CopyTarget) -> str:
    async with tenant_session(target.tenant_id) as session:
        row = (
            await session.execute(
                text(_EXPIRY_ROW_SQL),
                {
                    "kept": CARRIER_COPY_KEPT_FOR,
                    "cid": target.call_id,
                    "tid": target.tenant_id,
                },
            )
        ).first()
    if row is None:
        return "no_call"
    carrier_name, recording_id, ours, deleted_at, erased, due = row
    if deleted_at is not None:
        return "already_deleted"
    if erased is not None:
        # The erasure queued its own deletion of this copy (`enqueue_carrier_deletion`).
        return "erased"
    if not recording_id or not ours:
        return "not_copied"
    if not due:
        return "not_due"
    # The carrier's copy is the only other copy, so ours is proved present first. A pointer
    # alone is not proof: the object can be gone while the row still names it.
    if not await storage.object_exists(str(ours)):
        alert(
            "WORKER_TERMINAL",
            "carrier_recording_ours_missing",
            detail=(
                "our stored copy of this call's recording is missing from object storage, "
                "so the carrier's copy was NOT deleted; it is now the only copy"
            ),
            tenant_id=str(target.tenant_id),
            call_id=str(target.call_id),
        )
        return "ours_missing"
    deleted_now = await get_carrier(carrier_of_record(carrier_name)).delete_recording(
        str(recording_id)
    )
    async with tenant_session(target.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET carrier_recording_deleted_at = now(), updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid "
                "AND carrier_recording_deleted_at IS NULL"
            ),
            {"cid": target.call_id, "tid": target.tenant_id},
        )
    log.info(
        "carrier_recording_expired",
        extra={"call_id": str(target.call_id), "already_gone": not deleted_now},
    )
    return "deleted" if deleted_now else "already_gone"


# --- the sweep ------------------------------------------------------------------------

_UNCOPIED_SQL: Final = (
    "SELECT id, COALESCE(ended_at, created_at) < now() - :overdue FROM calls "
    "WHERE carrier_recording_id IS NOT NULL AND recording_url IS NULL "
    "AND erased_subject_ref IS NULL AND created_at > now() - :horizon "
    "ORDER BY created_at LIMIT :cap"
)

#: Finished Vobiz calls the carrier may have recorded and never reported. `status =
#: 'completed'` because only a connected call has a conversation to record.
_UNREPORTED_SQL: Final = (
    "SELECT id, carrier_call_id FROM calls "
    "WHERE carrier = 'vobiz' AND status = 'completed' AND carrier_call_id IS NOT NULL "
    "AND carrier_recording_id IS NULL AND recording_url IS NULL "
    "AND erased_subject_ref IS NULL "
    "AND COALESCE(ended_at, updated_at) < now() - :after "
    "AND COALESCE(ended_at, updated_at) > now() - :before "
    "ORDER BY COALESCE(ended_at, updated_at) LIMIT :cap"
)


#: Copied recordings whose carrier copy is due to go, and whether each is past the alarm.
#: `updated_at` stands in for `recording_copied_at` on rows copied before that column.
#: Erased calls are left to the erasure, which deletes the carrier's copy itself.
_EXPIRY_DUE_SQL: Final = (
    "SELECT id, COALESCE(recording_copied_at, updated_at) < now() - :overdue FROM calls "
    "WHERE carrier_recording_id IS NOT NULL AND recording_url IS NOT NULL "
    "AND carrier_recording_deleted_at IS NULL AND erased_subject_ref IS NULL "
    "AND COALESCE(recording_copied_at, updated_at) < now() - :kept "
    "AND created_at > now() - :horizon "
    "ORDER BY created_at LIMIT :cap"
)


async def reconcile_carrier_recordings(ctx: dict[str, Any]) -> str:
    """Re-queue every uncopied recording, look up unreported ones, page the overdue, and
    queue the expiry of every carrier copy whose twin has been ours for a day.

    The guarantee behind the callback, in the shape `carrier_events.reconcile_carrier_cdrs`
    keeps: one tenant's failure is not the sweep's, and every counter rides the return.
    """
    started = time.monotonic()
    enqueued = found = overdue = unreached = 0
    expiring = delete_overdue = 0
    truncated = False
    lookups = get_settings().carrier_recording_enabled
    for tenant_id in await callable_tenants():
        if enqueued + expiring >= SWEEP_BUDGET:
            truncated = True
            break
        try:
            async with tenant_session(tenant_id) as session:
                rows = (
                    await session.execute(
                        text(_UNCOPIED_SQL),
                        {
                            "overdue": COPY_OVERDUE_AFTER,
                            "horizon": CARRIER_RETENTION_HORIZON,
                            "cap": SWEEP_PER_TENANT,
                        },
                    )
                ).all()
                unreported = (
                    (
                        await session.execute(
                            text(_UNREPORTED_SQL),
                            {
                                "after": UNREPORTED_AFTER,
                                "before": UNREPORTED_BEFORE,
                                "cap": SWEEP_PER_TENANT,
                            },
                        )
                    ).all()
                    if lookups
                    else []
                )
                expiries = (
                    await session.execute(
                        text(_EXPIRY_DUE_SQL),
                        {
                            "kept": CARRIER_COPY_KEPT_FOR,
                            "overdue": CARRIER_DELETE_OVERDUE_AFTER,
                            "horizon": CARRIER_RETENTION_HORIZON,
                            "cap": SWEEP_PER_TENANT,
                        },
                    )
                ).all()
            for call_id, is_overdue in expiries:
                delete_overdue += int(bool(is_overdue))
                await enqueue_expiry(tenant_id=tenant_id, call_id=UUID(str(call_id)))
                expiring += 1
            for call_id, is_overdue in rows:
                overdue += int(bool(is_overdue))
                await enqueue_copy(tenant_id=tenant_id, call_id=UUID(str(call_id)))
                enqueued += 1
            for call_id, carrier_call_id in unreported:
                recording_id = await get_carrier("vobiz").find_recording(str(carrier_call_id))
                if recording_id is None:
                    continue
                async with tenant_session(tenant_id) as session:
                    noted = await note_recording(
                        session,
                        tenant_id=tenant_id,
                        call_id=UUID(str(call_id)),
                        recording=CarrierRecording(recording_id=recording_id),
                    )
                if noted:
                    found += 1
                    await enqueue_copy(tenant_id=tenant_id, call_id=UUID(str(call_id)))
                    enqueued += 1
        except Exception:
            log.exception("carrier_recording_sweep_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1

    if overdue:
        alert(
            "WORKER_STALL",
            "carrier_recording_copy_overdue",
            detail=(
                f"{overdue} call recording(s) reported by the carrier more than "
                f"{int(COPY_OVERDUE_AFTER.total_seconds() // 3600)}h ago are still not in "
                "our storage; the carrier's retention may be as short as 3 days"
            ),
        )
    if delete_overdue:
        alert(
            "WORKER_STALL",
            "carrier_recording_delete_overdue",
            detail=(
                f"{delete_overdue} carrier recording(s) are still not deleted more than "
                f"{int(CARRIER_DELETE_OVERDUE_AFTER.total_seconds() // 3600)}h after our "
                "copy was stored; the carrier still holds the caller's voice"
            ),
        )
    if unreached or truncated:
        alert(
            "WORKER_DELIVERY",
            "carrier_recording_sweep_incomplete",
            detail=(
                f"unreached={unreached} truncated={truncated}: enqueued={enqueued} is a "
                "floor; check the worker log for carrier_recording_sweep_failed"
            ),
        )
    elapsed = time.monotonic() - started
    return (
        f"enqueued={enqueued} found={found} overdue={overdue} unreached={unreached} "
        f"expiring={expiring} delete_overdue={delete_overdue} truncated={truncated} "
        f"took={elapsed:.1f}s"
    )


__all__ = [
    "CARRIER_COPY_KEPT_FOR",
    "CARRIER_DELETE_OVERDUE_AFTER",
    "CARRIER_RETENTION_HORIZON",
    "COPY_JOB",
    "COPY_OVERDUE_AFTER",
    "COPY_RETRY_BACKOFF_S",
    "DELETE_JOB",
    "EXPIRE_JOB",
    "RECORDING_SWEEP_MINUTES",
    "UNREPORTED_AFTER",
    "UNREPORTED_BEFORE",
    "copy_carrier_recording",
    "delete_carrier_recordings",
    "enqueue_carrier_deletion",
    "enqueue_copy",
    "enqueue_expiry",
    "expire_carrier_recording",
    "note_recording",
    "reconcile_carrier_recordings",
    "report_short_recording",
]

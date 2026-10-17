"""Calls whose recording we never copied, reported while the platform still holds it (D-805).

We keep our own copy of every call recording for the TRAI 90-day floor
(docs/SECURITY-COMPLIANCE.md); ThinnestAI deletes its copy on the workspace's
`callRetentionDays`, at most the plan's window — 30 days on pay-as-you-go, 49 Pro, 75 Scale
(VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/
workspace/update-workspace.md:582-598`, `channels/voice.md:819-823`). After that, a copy we
never made cannot be made, and before it the platform's console can still download the audio
(`channels/voice.md:821-822`).

The pipeline alarms on the failures it sees (`recording_copy_failed`, `recording_source_gone`)
and arq's exhausted ladder raises `job_retries_exhausted`, but none of those fires for a call
whose pipeline never ran, nor says how long is left. The recording is also not one of the
artefacts `pipeline._expected_artifacts` re-drives for. This sweep looks at the outcome
instead of the attempts: a connected call with no copy, past the time a copy takes.

Each missing copy it finds is also re-copied (D-808): `recopy_call_recording` reads the call
from the engine again and runs the pipeline's own `_copy_recordings` on it and no other
stage, so metering and extraction are never re-run. The same job backs the operator's
per-call action (`POST /v1/ops/tenants/{tenant_id}/calls/{call_id}/recording/recopy`). A
call whose re-copy keeps failing stays missing, so the sweep keeps alarming on it.

Ids and counts only in logs and alarms (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from arq import Retry
from calevate_shared.engine import PIPECAT_REF_PREFIX
from calevate_shared.engine_scope import SCOPE_SEPARATOR, WORKSPACE_PREFIX
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.engine_delivery import post_call_truth
from apps.workers.pipeline import _copy_recordings, _is_transient, _retry_after, callable_tenants

log = get_logger(__name__)

#: How long after a call ends its copy may still legitimately be on its way. The copy's own
#: ladder is at most three attempts (`core/queue.WORKER_MAX_TRIES`) of up to five minutes
#: each (`WorkerSettings.job_timeout`), at most five minutes apart (`storage.
#: NOT_READY_MAX_DEFER_S`); a call it gave up on is re-driven by the reconciliation poller
#: once `pipeline.PIPELINE_STALL_AFTER` has passed, while the call is still in its 30-minute
#: listing window, behind a second ladder. Two hours clears all of that;
#: `tests/recording_watch_test.py` pins it against those numbers.
COPY_GRACE: Final = timedelta(hours=2)

#: The shortest window any ThinnestAI plan keeps recordings (pay-as-you-go,
#: update-workspace.md:596-597). Used wherever we do not hold the number the platform
#: confirmed: a workspace the hourly retention sweep has not yet read (`workers/
#: engine_retention`; the developer workspace's answer is on `platform_state`, D-809). A
#: longer real window only makes the alarm early, never late.
PLAN_FLOOR_DAYS: Final = 30

#: The sweep's minute past the hour: one no other cron fires on.
RECORDING_WATCH_MINUTE: Final = 51

#: A missing copy this close to the platform's deletion pages instead of waiting for today.
AT_RISK_DAYS: Final = 7

#: Calls the at-risk alarm names, soonest first: each is a call an operator may have to
#: re-copy by hand or, failing that, download, so they need the list; a bound keeps the alert
#: body small.
AT_RISK_IDS_NAMED: Final = 20

#: The at-risk alarm names each call as `call_<n>` = `<tenant_id>:<call_id>`, n from 1,
#: soonest first (D-809). One scalar per call because alert ids are a flat map of strings
#: (`core/alerting.alert`) and each value is cut at `core/logging.MAX_FREE_TEXT` characters
#: when stored, so one joined list would keep five calls of twenty. The tenant travels with
#: each call because the re-copy route is tenant-scoped and the listed calls can span
#: tenants.
AT_RISK_CALL_KEY: Final = "call_"


def at_risk_call_ids(pairs: list[tuple[UUID, UUID]]) -> dict[str, str]:
    """`call_<n>` ids for the first `AT_RISK_IDS_NAMED` (tenant, call) pairs, in order."""
    return {
        f"{AT_RISK_CALL_KEY}{index}": f"{tenant_id}:{call_id}"
        for index, (tenant_id, call_id) in enumerate(pairs[:AT_RISK_IDS_NAMED], start=1)
    }


#: How long past the platform's deletion a missing copy is still reported. The audio is gone
#: by then, but the alarm on its last days should not stop the instant they run out.
PAST_DELETION_DAYS: Final = 3

#: Connected calls of this tenant with no copy of the AI leg's recording, past `COPY_GRACE`
#: and not more than `PAST_DELETION_DAYS` past the platform's deletion. Runs in a
#: `tenant_session`.
#:
#: * `completed` is the only status of ours that means the call connected
#:   (`engine/thinnest._STATUS_MAP`); a missed, failed or cancelled call is never offered a
#:   recording to copy (`ThinnestEngine.recording_source`), so its null pointer is not a gap.
#:   Every agent is published with `recordCalls: true`, so every connected call has one.
#: * A `pipecat:` ref is a call our former runtime ran: no platform holds a copy to fetch.
#: * `engine_content_deleted_at`: the platform has said this call's content is gone.
#: * `erased_subject_ref`, or a whole-engagement erasure on file: the pointer is null because
#:   an erasure cleared it, not because a copy is missing.
#: * The platform's deletion falls the workspace's confirmed `callRetentionDays` after the
#:   call for a call held in the client's own workspace (`<raw>@org_…`), our developer
#:   workspace's confirmed one for any other, and the plan floor where neither has been
#:   read. The clock is `workers/retention._call_clock`'s.
_MISSING_SQL: Final = """
WITH missing AS (
  SELECT c.id,
    COALESCE(c.ended_at, c.created_at + make_interval(secs => COALESCE(c.duration_s, 0)))
      AS ended,
    CASE WHEN strpos(c.engine_call_id, :scope_marker) > 0
      THEN COALESCE((SELECT w.retention_days FROM tenant_engine_workspaces w
                     WHERE w.tenant_id = c.tenant_id), :plan_floor)
      ELSE COALESCE((SELECT s.developer_retention_days FROM platform_state s WHERE s.id = 1),
                    :plan_floor) END AS keep_days
  FROM calls c
  WHERE c.status = 'completed'
    AND c.recording_url IS NULL
    AND c.engine_content_deleted_at IS NULL
    AND c.erased_subject_ref IS NULL
    AND c.engine_call_id NOT LIKE :own_runtime_refs
    AND NOT EXISTS (SELECT 1 FROM tenant_erasure_requests e WHERE e.tenant_id = c.tenant_id)
)
SELECT m.id, m.ended, m.ended + make_interval(days => m.keep_days) AS deletes_at
FROM missing m
WHERE m.ended < :settled_before
  AND m.ended + make_interval(days => m.keep_days + :past_days) > :now
ORDER BY deletes_at, m.id
"""


@dataclass(frozen=True, slots=True)
class MissingCopy:
    call_id: UUID
    ended: datetime
    deletes_at: datetime


async def missing_copies(session: AsyncSession, *, now: datetime) -> list[MissingCopy]:
    """This tenant's missing copies, soonest deletion first."""
    rows = (
        await session.execute(
            text(_MISSING_SQL),
            {
                "scope_marker": f"{SCOPE_SEPARATOR}{WORKSPACE_PREFIX}",
                "plan_floor": PLAN_FLOOR_DAYS,
                "own_runtime_refs": f"{PIPECAT_REF_PREFIX}:%",
                "settled_before": now - COPY_GRACE,
                "past_days": PAST_DELETION_DAYS,
                "now": now,
            },
        )
    ).all()
    return [MissingCopy(call_id=row[0], ended=row[1], deletes_at=row[2]) for row in rows]


def _days(delta: timedelta) -> float:
    return delta.total_seconds() / 86400


#: The arq name of the per-call re-copy. The API's operator action imports it from here.
RECOPY_JOB: Final = "recopy_call_recording"

#: Re-copies one sweep asks for, soonest deletion first. Each is one engine read and one
#: recording download, so an outage that left hundreds of calls uncopied is worked through
#: over a few hours instead of in one burst against the platform that has just been failing.
RECOPY_PER_SWEEP: Final = 50

#: Why a call is not re-copied. The job returns it as its outcome and the operator action
#: answers with it, so both say the same thing about the same call.
RecopyRefusal = Literal[
    "call_not_found", "erased", "content_deleted", "already_copied", "not_connected", "own_runtime"
]

#: Who asked for a re-copy. Part of the job id, so the sweep's hourly request and an
#: operator's press are deduped separately: an operator retrying a call the sweep queued an
#: hour ago is not refused for that hour.
RecopySource = Literal["sweep", "operator"]

#: The same exclusions as `_MISSING_SQL`, read for one call. Erasure is checked first: a
#: call whose caller or whole engagement was erased must not be fetched again, whatever
#: else is true of it.
_RECOPY_TARGET_SQL: Final = """
SELECT c.engine_call_id,
  c.status,
  c.recording_url IS NOT NULL,
  c.engine_content_deleted_at IS NOT NULL,
  c.erased_subject_ref IS NOT NULL
    OR EXISTS (SELECT 1 FROM tenant_erasure_requests e WHERE e.tenant_id = c.tenant_id)
FROM calls c
WHERE c.id = :id
"""


@dataclass(frozen=True, slots=True)
class RecopyTarget:
    """A call's engine handle, or why it is not to be re-copied (then the handle is "")."""

    engine_call_id: str
    refusal: RecopyRefusal | None


async def recopy_target(session: AsyncSession, call_id: UUID) -> RecopyTarget:
    """Whether this call's recording may be re-copied. Runs in the call's `tenant_session`."""
    row = (await session.execute(text(_RECOPY_TARGET_SQL), {"id": call_id})).first()
    if row is None:
        return RecopyTarget("", "call_not_found")
    engine_call_id, status, held, content_deleted, erased = row
    refusal: RecopyRefusal | None = None
    if erased:
        refusal = "erased"
    elif content_deleted:
        refusal = "content_deleted"
    elif held:
        refusal = "already_copied"
    elif status != "completed" or not engine_call_id:
        refusal = "not_connected"
    elif str(engine_call_id).startswith(f"{PIPECAT_REF_PREFIX}:"):
        refusal = "own_runtime"
    return RecopyTarget("" if refusal else str(engine_call_id), refusal)


def recopy_job_id(tenant_id: UUID, call_id: UUID, *, source: RecopySource) -> str:
    return job_id_for(RECOPY_JOB, str(tenant_id), str(call_id), source)


async def enqueue_recopy(tenant_id: UUID, call_id: UUID, *, source: RecopySource) -> bool:
    """Queue one call's re-copy. False when one from the same source is already queued."""
    queued = await enqueue(
        RECOPY_JOB,
        {"tenant_id": str(tenant_id), "call_id": str(call_id)},
        job_id=recopy_job_id(tenant_id, call_id, source=source),
    )
    return queued is not None


async def recopy_call_recording(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Copy one call's recording(s) again, through the pipeline's own copy and nothing else.

    The snapshot is read the way the pipeline reads it (`post_call_truth`, no delivery in
    hand), because ThinnestAI's recording address and fetch rules come from the call's
    current record (`ThinnestEngine.recording_source`). `_copy_recordings` keeps its guard
    per leg and its `recording_copy_failed` / `recording_source_gone` alarms, and a storage
    failure raises its own `arq.Retry`.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    async with tenant_session(tenant_id) as session:
        target = await recopy_target(session, call_id)
    if target.refusal is not None:
        return target.refusal
    attempt = int(ctx.get("job_try", 1))
    try:
        snapshot = await post_call_truth(
            get_engine(),
            tenant_id=tenant_id,
            call_id=call_id,
            execution_id=target.engine_call_id,
            delivery=None,
        )
    except Exception as exc:
        # arq retries only an `arq.Retry`; anything else would end the job on its first try.
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        log.warning(
            "recording_recopy_unreadable",
            extra={
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "error": type(exc).__name__,
            },
        )
        raise
    return await _copy_recordings(tenant_id, call_id, snapshot)


async def _request_recopies(found: list[tuple[UUID, MissingCopy]]) -> tuple[int, int, int]:
    """Queue re-copies for the soonest `RECOPY_PER_SWEEP` missing copies.

    Returns (queued, already queued, not queued). The first enqueue failure stops the loop:
    every later one would wait out the same Redis connect timeout.
    """
    soonest = sorted(found, key=lambda pair: pair[1].deletes_at)[:RECOPY_PER_SWEEP]
    queued = pending = 0
    for index, (tenant_id, copy) in enumerate(soonest):
        try:
            fresh = await enqueue_recopy(tenant_id, copy.call_id, source="sweep")
        except Exception:
            log.exception(
                "recording_recopy_enqueue_failed",
                extra={"tenant_id": str(tenant_id), "call_id": str(copy.call_id)},
            )
            return queued, pending, len(soonest) - index
        if fresh:
            queued += 1
        else:
            pending += 1
    return queued, pending, 0


async def report_missing_recordings(ctx: dict[str, Any]) -> str:
    """Hourly: every tenant asked, in its own session, for connected calls with no copy.

    Same shape as `dispatcher.report_stalled_pipeline`: one tenant's failure is counted as
    unreached and the sweep goes on, and an unreached tenant alarms on its own, because a
    sweep that could not look reads exactly like one that found nothing. Each call found is
    queued for `recopy_call_recording` before the alarms are raised; the alarms still fire,
    because a queued re-copy is not yet a copy.
    """
    del ctx
    now = datetime.now(UTC)
    found: list[tuple[UUID, MissingCopy]] = []
    tenants_affected = 0
    unreached = 0
    tenants = await callable_tenants()
    for tenant_id in tenants:
        try:
            async with tenant_session(tenant_id) as session:
                missing = await missing_copies(session, now=now)
        except Exception:
            # The id, never the exception's payload: a psycopg error can quote the row.
            log.exception("recording_watch_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue
        if missing:
            tenants_affected += 1
            found.extend((tenant_id, copy) for copy in missing)

    at_risk = sorted(
        (
            (tenant_id, copy)
            for tenant_id, copy in found
            if copy.deletes_at <= now + timedelta(days=AT_RISK_DAYS)
        ),
        key=lambda pair: pair[1].deletes_at,
    )
    floor_note = (
        f"; {unreached} of {len(tenants)} tenant(s) could not be checked, so the count is a "
        "floor rather than a total"
        if unreached
        else ""
    )
    # Before the alarms, so what they say about the re-copies is what was done.
    queued, pending, not_queued = await _request_recopies(found)
    recopy_note = ""
    if found:
        recopy_note = (
            f"; re-copies requested for {queued}, already queued for {pending}"
            + (f", could not be queued for {not_queued}" if not_queued else "")
            + (
                f", the rest wait for the next sweep ({RECOPY_PER_SWEEP} per sweep)"
                if len(found) > RECOPY_PER_SWEEP
                else ""
            )
        )
    if found or unreached:
        oldest_tenant, oldest = min(found, key=lambda pair: pair[1].ended, default=(None, None))
        detail = f"{len(found)} connected call(s) across {tenants_affected} tenant(s) have no copy"
        ids: dict[str, str] = {}
        if oldest is not None and oldest_tenant is not None:
            detail += (
                f"; the oldest ended {_days(now - oldest.ended):.1f} day(s) ago and the "
                f"voice platform deletes it in {_days(oldest.deletes_at - now):.1f} day(s)"
            )
            ids = {"tenant_id": str(oldest_tenant), "call_id": str(oldest.call_id)}
        alert(
            "WORKER_DELIVERY",
            "recording_copy_missing",
            detail=detail + recopy_note + floor_note,
            **ids,
        )
    if at_risk:
        soonest_tenant, soonest = at_risk[0]
        past = sum(1 for _tenant, copy in at_risk if copy.deletes_at <= now)
        alert(
            "WORKER_DELIVERY",
            "recording_copy_at_risk",
            detail=(
                f"{len(at_risk)} call(s) with no recording copy are within {AT_RISK_DAYS} days "
                f"of the voice platform deleting theirs; the soonest goes in "
                f"{max(_days(soonest.deletes_at - now), 0.0):.1f} day(s)"
                + (f"; {past} may already be gone" if past else "")
                + recopy_note
                + floor_note
            ),
            tenant_id=str(soonest_tenant),
            call_id=str(soonest.call_id),
            **at_risk_call_ids([(tenant_id, copy.call_id) for tenant_id, copy in at_risk]),
        )
    return (
        f"missing={len(found)} at_risk={len(at_risk)} unreached={unreached} "
        f"recopies={queued} recopies_pending={pending}"
    )


__all__ = [
    "AT_RISK_CALL_KEY",
    "AT_RISK_DAYS",
    "AT_RISK_IDS_NAMED",
    "COPY_GRACE",
    "PAST_DELETION_DAYS",
    "PLAN_FLOOR_DAYS",
    "RECOPY_JOB",
    "RECOPY_PER_SWEEP",
    "RECORDING_WATCH_MINUTE",
    "MissingCopy",
    "RecopyRefusal",
    "RecopySource",
    "RecopyTarget",
    "at_risk_call_ids",
    "enqueue_recopy",
    "missing_copies",
    "recopy_call_recording",
    "recopy_job_id",
    "recopy_target",
    "report_missing_recordings",
]

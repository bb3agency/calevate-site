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

Ids and counts only in logs and alarms (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import PIPECAT_REF_PREFIX
from calevate_shared.engine_scope import SCOPE_SEPARATOR, WORKSPACE_PREFIX
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.workers.pipeline import callable_tenants

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
#: confirmed: our developer workspace (trial calls, calls from before D-693), whose plan we
#: never record, and a client workspace not yet checked. A longer real window only makes the
#: alarm early, never late.
PLAN_FLOOR_DAYS: Final = 30

#: The sweep's minute past the hour: one no other cron fires on.
RECORDING_WATCH_MINUTE: Final = 51

#: A missing copy this close to the platform's deletion pages instead of waiting for today.
AT_RISK_DAYS: Final = 7

#: Call ids the at-risk alarm names, soonest first: each is a download an operator has to
#: make by hand, so they need the list, and a bound keeps the alert body small.
AT_RISK_IDS_NAMED: Final = 20

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
#:   call for a call held in the client's own workspace (`<raw>@org_…`), and the plan floor
#:   otherwise. The clock is `workers/retention._call_clock`'s.
_MISSING_SQL: Final = """
WITH missing AS (
  SELECT c.id,
    COALESCE(c.ended_at, c.created_at + make_interval(secs => COALESCE(c.duration_s, 0)))
      AS ended,
    CASE WHEN strpos(c.engine_call_id, :scope_marker) > 0
      THEN COALESCE((SELECT w.retention_days FROM tenant_engine_workspaces w
                     WHERE w.tenant_id = c.tenant_id), :plan_floor)
      ELSE :plan_floor END AS keep_days
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


async def report_missing_recordings(ctx: dict[str, Any]) -> str:
    """Hourly: every tenant asked, in its own session, for connected calls with no copy.

    Same shape as `dispatcher.report_stalled_pipeline`: one tenant's failure is counted as
    unreached and the sweep goes on, and an unreached tenant alarms on its own, because a
    sweep that could not look reads exactly like one that found nothing.
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
        alert("WORKER_DELIVERY", "recording_copy_missing", detail=detail + floor_note, **ids)
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
                + floor_note
            ),
            tenant_id=str(soonest_tenant),
            call_id=str(soonest.call_id),
            call_ids=",".join(str(copy.call_id) for _tenant, copy in at_risk[:AT_RISK_IDS_NAMED]),
        )
    return f"missing={len(found)} at_risk={len(at_risk)} unreached={unreached}"


__all__ = [
    "AT_RISK_DAYS",
    "AT_RISK_IDS_NAMED",
    "COPY_GRACE",
    "PAST_DELETION_DAYS",
    "PLAN_FLOOR_DAYS",
    "RECORDING_WATCH_MINUTE",
    "MissingCopy",
    "missing_copies",
    "report_missing_recordings",
]

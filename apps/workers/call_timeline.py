"""Fetches a finished call's per-turn timings and keeps them on the call (D-902).

The voice platform writes a call's timeline after the call and does not say when, and it
answers "no timeline" alike for one not written yet, one never recorded for that kind of call
(off the standard voice pipeline) and a call from before 27 Oct 2026. So the post-call pipeline
queues this job a minute after a call with answered turns, and an empty answer is retried on a
ladder rather than stored, until the call's final report has landed (`_report_landed`), after
which an empty answer is final: `calls.engine_timeline` stays NULL until a real one arrives,
and NULL at the end means the platform timed nothing for the call. A separate job rather
than a pipeline stage, so waiting on the timeline never holds back a call's transcript, lead
or minutes.

Idempotent: a call that already holds a timeline is not fetched again, and a re-fetch would
write the same times.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for, job_try
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.engine_outage import engine_unavailable

log = get_logger(__name__)

JOB_NAME: Final = "fetch_call_timeline"

#: The first fetch waits this long after the post-call pipeline queues it.
FIRST_FETCH_AFTER: Final = timedelta(seconds=60)
#: Then these waits between tries, the last try having nothing after it.
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (120.0, 600.0)

#: A fetch the engine did not answer through the whole ladder is queued again this much
#: later, up to `OUTAGE_ROUNDS` times: about six hours of an engine not answering before the
#: timeline is given up. Under a new job id per round, because the spent job's kept result
#: holds its own id for an hour.
OUTAGE_REQUEUE_AFTER: Final = timedelta(minutes=30)
OUTAGE_ROUNDS: Final = 12

_HELD_SQL: Final = "SELECT engine_timeline IS NOT NULL FROM calls WHERE id = :cid"
_STORE_SQL: Final = (
    "UPDATE calls SET engine_timeline = CAST(:timeline AS jsonb), updated_at = now() "
    "WHERE id = :cid AND engine_timeline IS NULL"
)


def timeline_expected(snapshot: ExecutionSnapshot) -> bool:
    """A call worth asking about: it connected, an agent took it (a call forwarded to the
    business's phone has no agent turns), and the engine did not report zero turns."""
    if snapshot.status != "completed" or snapshot.forwarded:
        return False
    return snapshot.quality is None or snapshot.quality.turns != 0


async def request_call_timeline(*, tenant_id: UUID, call_id: UUID, execution_id: str) -> None:
    """Queue the fetch, once per call while one is queued or kept."""
    await enqueue(
        JOB_NAME,
        {"tenant_id": str(tenant_id), "call_id": str(call_id), "execution_id": execution_id},
        job_id=job_id_for(JOB_NAME, str(call_id)),
        _defer_by=FIRST_FETCH_AFTER,
    )


async def _report_landed(execution_id: str) -> bool:
    """Has the call's final report landed? Then a timeline not there now never will be: Get
    Call's `quality.turns` stops being null with the report the timeline is written from
    (ThinnestAI, email of 28 Oct 2026, VENDOR-STATED). A read that fails says not yet."""
    try:
        snapshot = await get_engine().get_execution(execution_id)
    except ProblemError:
        return False
    return snapshot.quality is not None and snapshot.quality.turns is not None


def _retry_or_stop(attempt: int, outcome: str, call_id: UUID) -> str:
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    log.info("call_timeline_not_recorded", extra={"call_id": str(call_id), "outcome": outcome})
    return outcome


async def _after_outage(payload: dict[str, Any], call_id: UUID, outcome: str) -> str:
    """Queue the fetch again for after the outage, or give it up once the rounds are spent."""
    round_ = int(payload.get("outage_round") or 0) + 1
    if round_ > OUTAGE_ROUNDS:
        log.info("call_timeline_not_recorded", extra={"call_id": str(call_id), "outcome": outcome})
        return outcome
    await enqueue(
        JOB_NAME,
        {**payload, "outage_round": round_},
        job_id=job_id_for(JOB_NAME, str(call_id), f"outage-{round_}"),
        _defer_by=OUTAGE_REQUEUE_AFTER,
    )
    log.info("call_timeline_requeued", extra={"call_id": str(call_id), "round": round_})
    return f"requeued:{round_}"


async def fetch_call_timeline(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    attempt = job_try(ctx)
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    execution_id = str(payload["execution_id"])

    async with tenant_session(tenant_id) as session:
        held = (await session.execute(text(_HELD_SQL), {"cid": call_id})).scalar_one_or_none()
    if held is None:
        return "no_call"
    if held:
        return "already_stored"

    try:
        timeline = await get_engine().get_call_timeline(execution_id)
    except ProblemError as exc:
        # A 5xx is the engine failing, not refusing: read here as a verdict, one 502 lost
        # the call's timeline for good.
        if engine_unavailable(exc):
            if attempt < WORKER_MAX_TRIES:
                raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt)) from exc
            return await _after_outage(payload, call_id, f"unreachable:{exc.code}")
        # The engine answered and refused: a verdict on the request, not worth a retry.
        log.warning(
            "call_timeline_refused",
            extra={"call_id": str(call_id), "reason": exc.code, "attempt": attempt},
        )
        return f"refused:{exc.code}"

    if timeline is None or not timeline.turns:
        if await _report_landed(execution_id):
            log.info("call_timeline_not_recorded", extra={"call_id": str(call_id)})
            return "none_recorded"
        return _retry_or_stop(attempt, "none_recorded", call_id)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(_STORE_SQL), {"cid": call_id, "timeline": timeline.model_dump_json()}
        )
    return f"stored:{len(timeline.turns)}"


__all__ = [
    "FIRST_FETCH_AFTER",
    "JOB_NAME",
    "RETRY_BACKOFF_S",
    "fetch_call_timeline",
    "request_call_timeline",
    "timeline_expected",
]

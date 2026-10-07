"""The settlement backstop: an answered call whose worker never settled it is finalised anyway.

    carrier hangup of an answered call → finalise_unsettled_call, deferred
      (`carrier_events.enqueue_finalise`, `FINALISE_GRACE_S` after the hangup)
    finalise_unsettled_call
      the `post-call:{call}` promise exists → nothing (the worker settled)
      no worker ever opened the call → `failed` (never billed), nothing promised
      otherwise → a `worker_settlement_missing` refusal per worker-measured leg,
                  `duration_s` from the carrier's `billsec`, the post-call promise claimed

WHY THIS EXISTS. `worker/service.settle_call` is the only thing that promises a call's
post-call pipeline (extraction, CRM columns, lead, the client's billable minute). A worker
container killed mid-call — a deploy, an OOM, a host lost — never settles, so the call sat
`completed` with no lead, no minute billed and its CDR cost waiting for a meter that would
never run.

WHY THE SETTLEMENT'S OWN KEY. The promise is claimed through `enqueue_outbox_once` under
`post-call:{calls.id}`, the key `settle_call` claims FIRST and reads as "already settled".
So whichever of the two commits first wins and the other is a no-op: a worker settlement
arriving after this job is answered `already_settled`, and the pipeline runs exactly once.
What a late settlement then loses is its measured legs, which is what the refusals here
already record.

WHY NO CLIENT CHARGE IS INVENTED HERE. The minute is billed by the post-call meter off
`calls.duration_s`, as for every call; this job only gives it the carrier's `billsec`,
which is the carrier's own count of the connected time. The speech, language and runtime
legs were never measured and are refused rather than estimated (hard rule 7).

A row still live whose hangup never arrived reaches this job through
`carrier_events.reconcile_carrier_cdrs`, which ends it from the carrier's call record and
queues this backstop the way the hangup would have.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, get_args
from uuid import UUID

from arq import Retry
from calevate_shared.events import TERMINAL_STATUSES
from calevate_shared.worker_api import MeteredLegName, SettlementRefusal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierCdr, carrier_of_record, get_carrier
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.worker.service import ENGINE_NAME, POSTCALL_DEDUPE_PREFIX, _write_refusal
from apps.workers.pipeline import _is_transient, _retry_after

log = get_logger(__name__)

#: `apps/workers/pipeline.POSTCALL_JOB`, restated for `worker/service.POSTCALL_JOB`'s
#: reason: `scripts/check_job_wiring.py` resolves a job name only as a module-level constant
#: in the file that enqueues it. `tests/call_finalise_test.py` pins the three equal.
POSTCALL_JOB: Final = "run_post_call_pipeline"

#: The refusal code, on every leg the worker would have measured.
SETTLEMENT_MISSING_CODE: Final = "worker_settlement_missing"

#: The legs a worker settlement measures. The carrier leg is not among them: its cost is
#: the CDR's (`carrier_events.record_cdr_cost`), with or without a settlement.
UNSETTLED_LEGS: Final[tuple[MeteredLegName, ...]] = tuple(
    sorted(leg for leg in get_args(MeteredLegName) if leg != "carrier")
)

_REFUSAL_DETAIL: Final = (
    "The voice worker never settled this call, so the speech, language and runtime use it "
    "measured was lost with it."
)
_REFUSAL_REMEDIATION: Final = (
    "Read the worker and Pipecat Cloud logs for this call id: a container stopped mid-call "
    "(deploy, out of memory, host lost) settles nothing. This leg cannot be re-metered; "
    "the carrier minute is still priced from the call record."
)


@dataclass(frozen=True, slots=True)
class _Target:
    tenant_id: UUID
    call_id: UUID


@dataclass(frozen=True, slots=True)
class _Call:
    status: str
    carrier: str | None
    carrier_call_id: str | None
    engine_call_id: str
    settled: bool
    #: A voice worker opened this call (`started_at`, which only its opening event writes)
    #: or flushed a turn of it.
    served: bool


def _target(payload: dict[str, Any]) -> _Target:
    try:
        return _Target(
            tenant_id=UUID(str(payload["tenant_id"])), call_id=UUID(str(payload["call_id"]))
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="call_finalise_payload_invalid",
            title="A finished call could not be wrapped up",
            detail="The call-finalise job was enqueued without a usable tenant or call id.",
        ) from exc


async def finalise_unsettled_call(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Finalise one call whose settlement never arrived. Keyed per call by its producer."""
    attempt = int(ctx.get("job_try", 1))
    try:
        return await _finalise(_target(payload), attempt)
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        alert(
            "WORKER_TERMINAL",
            "call_finalise_abandoned",
            detail=(
                f"{type(exc).__name__} after {attempt} attempt(s): this call's post-call "
                "pipeline may never be promised"
                if _is_transient(exc)
                else f"{type(exc).__name__} is permanent, not retried"
            ),
            call_id=str(payload.get("call_id") or "unknown"),
        )
        raise


async def _finalise(target: _Target, attempt: int) -> str:
    call = await _read_call(target)
    if call.settled:
        return "already_settled"
    if call.status not in TERMINAL_STATUSES:
        # The hangup that queued this job moves the row terminal first; a live row here is
        # a status somebody rewrote since, and finalising a live call would bill its minute.
        log.warning(
            "call_finalise_not_terminal",
            extra={"tenant_id": str(target.tenant_id), "call_id": str(target.call_id)},
        )
        return "not_terminal"
    if not call.served:
        return await _record_unserved(target)
    cdr = await _read_cdr(target, call, attempt)
    at = datetime.now(UTC)
    async with tenant_session(target.tenant_id) as session:
        claimed = await enqueue_outbox_once(
            session,
            job=POSTCALL_JOB,
            # `settle_call`'s payload, key for key: the pipeline cannot tell who promised it.
            payload={
                "tenant_id": str(target.tenant_id),
                "call_id": str(target.call_id),
                "engine": ENGINE_NAME,
                "execution_id": call.engine_call_id,
            },
            dedupe_key=f"{POSTCALL_DEDUPE_PREFIX}{target.call_id}",
        )
        if claimed is None:
            # The settlement committed between the read above and this claim.
            return "already_settled"
        for leg in UNSETTLED_LEGS:
            await _write_refusal(
                session,
                target.tenant_id,
                target.call_id,
                SettlementRefusal(
                    leg=leg,
                    code=SETTLEMENT_MISSING_CODE,
                    detail=_REFUSAL_DETAIL,
                    remediation=_REFUSAL_REMEDIATION,
                ),
                at=at,
            )
        if cdr is not None:
            await _record_billsec(session, target, cdr)
    alert(
        "WORKER_TERMINAL",
        "worker_settlement_missing",
        detail=(
            "an answered call was never settled by its voice worker; its post-call pipeline "
            "was promised from the carrier's record "
            f"({'with' if cdr is not None else 'without'} the carrier's connected time)"
        ),
        tenant_id=str(target.tenant_id),
        call_id=str(target.call_id),
    )
    return "finalised:cdr" if cdr is not None else "finalised:no_cdr"


async def _read_call(target: _Target) -> _Call:
    """The row, and whether its post-call promise is already on the books.

    The promise is read here only to spare a settled call (the common case) a carrier
    round trip; the claim in `_finalise` is what decides.
    """
    async with tenant_session(target.tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.status, c.carrier, c.carrier_call_id, c.engine_call_id, "
                    "EXISTS (SELECT 1 FROM outbox_messages o WHERE o.dedupe_key = :key), "
                    "c.started_at IS NOT NULL OR EXISTS "
                    "  (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id) "
                    "FROM calls c WHERE c.id = :cid AND c.tenant_id = :tid"
                ),
                {
                    "key": f"{POSTCALL_DEDUPE_PREFIX}{target.call_id}",
                    "cid": target.call_id,
                    "tid": target.tenant_id,
                },
            )
        ).first()
    if row is None:
        raise ProblemError(
            kind="validation",
            code="call_finalise_call_missing",
            title="No such call",
            detail="The call this finalise job names is not in its tenant.",
        )
    return _Call(
        status=str(row[0]),
        carrier=row[1],
        carrier_call_id=row[2],
        engine_call_id=str(row[3]),
        settled=bool(row[4]),
        served=bool(row[5]),
    )


#: Ends an unserved call as `failed`, unless a worker's settlement or first event landed
#: since the read: the claim and both kinds of evidence are re-asked in the statement.
_UNSERVED_SQL: Final = (
    "UPDATE calls c SET updated_at = now(), "
    "  status = CASE WHEN c.status = 'completed' THEN 'failed' ELSE c.status END "
    "WHERE c.id = :cid AND c.tenant_id = :tid AND c.started_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id) "
    "AND NOT EXISTS (SELECT 1 FROM outbox_messages o WHERE o.dedupe_key = :key) "
    "RETURNING c.id"
)


async def _record_unserved(target: _Target) -> str:
    """A call the carrier connected and no voice worker ever served: `failed`, not billed.

    The rule `carrier_events.orphan_status` already applies to an inbound hangup with no
    row, applied to a row that exists — an outbound dial whose worker never connected, or a
    row a worker's session read refused. `completed` is the one status the post-call meter
    bills, and the carrier's talk time on such a call is somebody hearing nothing. So no
    pipeline is promised: there is no transcript to extract, no worker leg to refuse, and an
    outbox claim would keep a campaign contact out of its retry ladder
    (`campaign_dispatch._UNANSWERED_DIALS_SQL`), which is where a person who heard silence
    belongs. The carrier's own charge still reaches our cost through the CDR read the hangup
    queued.
    """
    async with tenant_session(target.tenant_id) as session:
        ended = (
            await session.execute(
                text(_UNSERVED_SQL),
                {
                    "cid": target.call_id,
                    "tid": target.tenant_id,
                    "key": f"{POSTCALL_DEDUPE_PREFIX}{target.call_id}",
                },
            )
        ).first()
    if ended is None:
        # A worker's settlement or first batch committed after the read.
        return "already_settled"
    alert(
        "WORKER_TERMINAL",
        "answered_call_never_reached_worker",
        detail=(
            "the carrier connected this call but no voice worker ever opened it or recorded a "
            "turn, so it was recorded failed and not billed; no post-call pipeline was promised"
        ),
        tenant_id=str(target.tenant_id),
        call_id=str(target.call_id),
    )
    return "unserved"


async def _read_cdr(target: _Target, call: _Call, attempt: int) -> CarrierCdr | None:
    """The carrier's record of the call, from the carrier recorded on its row.

    Optional: without it the call is still finalised, with `duration_s` left as it is. A
    transient failure is retried while attempts remain, because the record is what gives
    the client's minute its length.
    """
    if call.carrier_call_id is None:
        return None
    try:
        return await get_carrier(carrier_of_record(call.carrier)).fetch_cdr(call.carrier_call_id)
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise
        log.warning(
            "call_finalise_cdr_unread",
            extra={
                "call_id": str(target.call_id),
                "reason": type(exc).__name__,
                "code": exc.code if isinstance(exc, ProblemError) else None,
            },
        )
        return None


async def _record_billsec(session: AsyncSession, target: _Target, cdr: CarrierCdr) -> None:
    """The carrier's connected seconds, where nothing has recorded a duration."""
    await session.execute(
        text(
            "UPDATE calls SET duration_s = :billsec, updated_at = now() "
            "WHERE id = :cid AND tenant_id = :tid AND duration_s IS NULL"
        ),
        {"billsec": cdr.billed_seconds, "cid": target.call_id, "tid": target.tenant_id},
    )


__all__ = [
    "POSTCALL_JOB",
    "SETTLEMENT_MISSING_CODE",
    "UNSETTLED_LEGS",
    "finalise_unsettled_call",
]

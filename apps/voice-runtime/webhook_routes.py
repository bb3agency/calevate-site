"""Engine webhook receiver. LATENCY-CRITICAL (hard rule 3).

The contract this file must satisfy, in order:

1. **Verify authenticity per engine.** For Bolna that is a source-IP allowlist —
   there is no signature to check (D-31) — plus execution-id dedupe.
2. **Ack in under 500ms.** Measured on every request (`record_webhook_ack_ms`) so a
   regression shows up as a metric, not as a mystery.
3. **Defer all real work to ARQ.** Nothing here fetches, parses costs, or writes a
   domain row.
4. **No DB writes beyond the minimal event row** — the inbox claim (dedupe) and the
   forensic delivery row. Both are infra tables, neither is tenant-scoped, and the
   tenant is not even resolved here.

The deeper reason it is this thin: Bolna's delivery is at-most-once with no retries,
so a slow or failing receiver silently LOSES calls. Being fast is a correctness
property here, not a performance nicety. The 10-minute reconciliation poller is what
makes a loss recoverable (D-31), and it is the poller — not this endpoint — that is
the guarantee of record.
"""

from __future__ import annotations

import json
import time

from apps.api.core.alerting import alert, record_webhook_ack_ms
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_enqueued
from engine_intake import client_ip, extract, verify_source
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1", tags=["engine-webhooks"])

# Redis fast-path dedupe. The inbox row is the durable truth; this just keeps a burst
# of duplicates from touching Postgres at all.
_DEDUPE_TTL_S = 3600
INGEST_JOB = "ingest_engine_event"


@router.post(
    "/engine/{engine}",
    status_code=202,
    summary="Engine status webhook (unsigned for Bolna — hint only, poller is truth)",
)
async def engine_webhook(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()

    # Bootstrap step 6: the RAW bytes are read first and never re-parsed downstream.
    # Bolna signs nothing today, but an engine that does will need the exact bytes,
    # and retro-fitting raw-body preservation into a live receiver is miserable.
    raw = await request.body()
    source_ip = client_ip(
        request.client.host if request.client else None,
        {k.lower(): v for k, v in request.headers.items()},
    )

    verdict = verify_source(engine, source_ip)
    if not verdict.ok:
        # Alert, do not process. An unverified event at an unsigned endpoint is either
        # a misconfigured edge or someone probing us; both are worth waking up for.
        alert("ROUTE_HANDLER", "webhook_source_rejected", detail=verdict.reason, engine=engine)
        raise ProblemError.unauthorized("This caller is not permitted to post events.")

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event = extract(payload)
    if event is None:
        # Ack anyway: an event we cannot key is one we can never dedupe, and Bolna
        # would not resend it regardless. The poller will pick the call up.
        alert("ROUTE_HANDLER", "webhook_unkeyable", engine=engine)
        record_webhook_ack_ms((time.perf_counter() - started) * 1000, provider=engine)
        return {"status": "ignored", "reason": "no execution id"}

    payload_digest = body_hash(payload)
    redis_key = f"calevate:wh:{engine}:{event.execution_id}:{payload_digest[:16]}"
    try:
        if not await get_redis().set(redis_key, "1", nx=True, ex=_DEDUPE_TTL_S):
            record_webhook_ack_ms((time.perf_counter() - started) * 1000, provider=engine)
            return {"status": "duplicate", "execution_id": event.execution_id}
    except Exception:  # Redis down: fall through to the durable claim, never 500
        log.warning("webhook_fastpath_unavailable", extra={"engine": engine})

    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session,
            provider=engine,
            event_key=event.execution_id,
            payload_hash=payload_digest,
            event_name=event.raw_status,
        )
        if claim.state == "duplicate":
            record_webhook_ack_ms((time.perf_counter() - started) * 1000, provider=engine)
            return {"status": "duplicate", "execution_id": event.execution_id}

        # The minimal event row: forensic trail only (SEC-COMP §4). `signature_valid`
        # records what evidence we actually had, so a later investigation can tell an
        # IP-allowlisted event from a signed one.
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, direction, source, event_type, status, "
                "attempts, signature_valid, first_at, last_at, created_at) VALUES "
                "(:id, 'in', :source, :event_type, 'received', 1, :sig, now(), now(), now())"
            ),
            {
                "id": uuid7(),
                "source": engine,
                "event_type": event.raw_status,
                "sig": verdict.method == "hmac",
            },
        )

        # Keyed by the natural key, so a duplicate webhook and a poller rediscovery
        # collapse into one job before any worker runs.
        job_id = await enqueue(
            INGEST_JOB,
            {
                "engine": engine,
                "execution_id": event.execution_id,
                "raw_status": event.raw_status,
                "engine_agent_ref": event.engine_agent_ref,
                "inbox_row_id": str(claim.row_id),
            },
            job_id=job_id_for(INGEST_JOB, engine, event.execution_id, event.raw_status),
        )
        await mark_inbox_enqueued(session, row_id=claim.row_id)

    elapsed_ms = (time.perf_counter() - started) * 1000
    record_webhook_ack_ms(elapsed_ms, provider=engine)
    if elapsed_ms > 500:
        # Hard rule 3 has a number in it; treat breaching it as an incident signal.
        alert("ROUTE_HANDLER", "webhook_ack_slow", detail=f"{elapsed_ms:.0f}ms", engine=engine)
    response.headers["X-Ack-Ms"] = f"{elapsed_ms:.1f}"
    return {
        "status": "accepted",
        "execution_id": event.execution_id,
        "job_id": job_id or "deduped",
    }


__all__ = ["INGEST_JOB", "router"]

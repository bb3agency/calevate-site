"""Engine webhook receiver. LATENCY-CRITICAL (hard rule 3).

The contract this file must satisfy, in order:

1. **Verify authenticity per engine, before reading a byte of body.** For Bolna that
   is a source-IP allowlist — there is no signature to check (D-31) — plus
   execution-id dedupe. Everything after this step is work done for a caller we have
   already decided to trust, which is why the order matters.
2. **Ack in under 500ms.** Measured AND reported on every response path
   (`X-Ack-Ms` + `record_webhook_ack_ms`), so a regression shows up as a number
   rather than as a mystery — including on the paths a flood would take.
3. **Defer all real work to ARQ.** Nothing here fetches, parses costs, or writes a
   domain row.
4. **No DB writes beyond the minimal event row** — the inbox claim (dedupe) and the
   forensic delivery row. Both are infra tables, neither is tenant-scoped, and the
   tenant is not even resolved here.
5. **Answer every request deliberately.** Unsigned means anyone who learns the URL can
   POST: malformed JSON, 200MB of it, ten thousand nested arrays, an engine name we
   never deployed. Each of those has a chosen answer here; none of them is a 500.

The deeper reason it is this thin: Bolna's delivery is at-most-once with no retries,
so a slow or failing receiver silently LOSES calls. Being fast is a correctness
property here, not a performance nicety. The 10-minute reconciliation poller is what
makes a loss recoverable (D-31), and it is the poller — not this endpoint — that is
the guarantee of record.
"""

from __future__ import annotations

import json
import time
from typing import Any

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
#
# **THE KEY IS WRITTEN AFTER THE TRANSACTION COMMITS, NEVER BEFORE IT.** It used to be a
# SETNX taken up front, which made the fast path MORE durable than the fact it stands
# for: if the durable claim or the enqueue then failed, the transaction rolled back and
# the key survived for its full hour — so every retry of that event was answered
# `duplicate` with no inbox row and no job behind it. At an at-most-once endpoint that is
# an event we told the vendor we accepted and then dropped, recoverable only by the
# 10-minute poller.
#
# Deleting the key on the failure path was the other candidate and is weaker: a
# compensating action shares a fate with the thing it compensates for, and the failures
# worth defending against here — a killed process, a severed Redis connection — are
# exactly the ones that would eat the delete too. Writing the key only once the row and
# the job exist needs nothing to go right afterwards.
#
# What the split costs: a read on the way in and a write on the way out instead of one
# SETNX, and deliveries that arrive WHILE the first one's transaction is still open now
# reach the durable claim instead of being absorbed here. That claim is where they
# belong — it is the layer that actually decides — and every delivery after the first
# commit (which is the entire real duplicate population, since Bolna does not retry and
# duplicates come from replays and poller rediscoveries later in time) is still absorbed
# without touching Postgres.
_DEDUPE_TTL_S = 3600
INGEST_JOB = "ingest_engine_event"

# Hard rule 3's number, in one place so the metric, the alert and the docs agree.
_ACK_BUDGET_MS = 500.0

# The largest body we will hold in memory for an UNAUTHENTICATED caller. An execution
# payload is a status line plus a transcript; a megabyte is already an implausibly long
# call. Refusing above it is safe precisely because the payload is only a hint (D-31) —
# the poller still picks the execution up — whereas buffering whatever a stranger sends
# is an unbounded allocation on the one service that must not stall.
_MAX_BODY_BYTES = 1_048_576


def _ack_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _ack(response: Response, started: float, engine: str, body: dict[str, str]) -> dict[str, str]:
    """Every acked path leaves through here, so the budget is measured, alerted and
    REPORTED identically on all of them.

    The early returns are exactly the paths a flood takes — a duplicate storm, a stream
    of unkeyable payloads. Instrumenting only the happy path measures the endpoint at
    its least stressed, which is the opposite of useful.
    """
    elapsed = _ack_ms(started)
    record_webhook_ack_ms(elapsed, provider=engine)
    if elapsed > _ACK_BUDGET_MS:
        # Hard rule 3 has a number in it; treat breaching it as an incident signal.
        alert("ROUTE_HANDLER", "webhook_ack_slow", detail=f"{elapsed:.0f}ms", engine=engine)
    response.headers["X-Ack-Ms"] = f"{elapsed:.1f}"
    return body


async def _fast_path_seen(redis_key: str, *, engine: str) -> bool:
    """Has this exact delivery already been handled to completion? A READ, never a write.

    Redis being unavailable degrades correctly and deliberately: we answer "not seen" and
    fall through to the durable claim, which is the dedupe that carries the guarantee.
    """
    try:
        return await get_redis().get(redis_key) is not None
    except Exception:  # Redis down: fall through to the durable claim, never 500
        log.warning("webhook_fastpath_unavailable", extra={"engine": engine})
        return False


async def _remember_fast_path(redis_key: str, *, engine: str) -> None:
    """Record that this delivery is settled — called only after the claim has COMMITTED.

    Best effort by design: a key we failed to write costs one extra Postgres round trip
    on the next copy of this delivery, which is the cheap direction to be wrong in. The
    expensive direction — a key we wrote for work that never landed — is what the
    post-commit placement removes.
    """
    try:
        await get_redis().set(redis_key, "1", ex=_DEDUPE_TTL_S)
    except Exception:
        log.warning("webhook_fastpath_unavailable", extra={"engine": engine})


async def _read_bounded(request: Request) -> bytes | None:
    """The raw body, or None if the caller exceeded the cap.

    Streamed rather than `await request.body()` so an oversized POST is abandoned after
    a megabyte instead of after all of it. The declared length is checked first, which
    turns the common case into a rejection that reads nothing at all.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/engine/{engine}",
    status_code=202,
    summary="Engine status webhook (unsigned for Bolna — hint only, poller is truth)",
)
async def engine_webhook(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()

    # Step 1 — WHO is calling, decided from the socket and the edge headers alone.
    # It reads no body, so a caller we are going to refuse never gets us to allocate
    # for them: on a public, unsigned endpoint that ordering is the difference between
    # a rejection and a memory-exhaustion primitive.
    source_ip = client_ip(
        request.client.host if request.client else None,
        {k.lower(): v for k, v in request.headers.items()},
    )
    verdict = verify_source(engine, source_ip)
    if not verdict.ok:
        # Alert, do not process. An unverified event at an unsigned endpoint is either
        # a misconfigured edge or someone probing us; both are worth waking up for.
        # `source_ip` is in the alert because of the incident it is FOR: the vendor
        # renumbers, every webhook starts 401ing, every call falls back to the poller.
        # An alert that says only "not allowlisted" leaves the operator running tcpdump
        # to learn the one value they need to fix it. Not PII under hard rule 6 — it is
        # a machine caller's address — and it never appears in the response body.
        alert(
            "ROUTE_HANDLER",
            "webhook_source_rejected",
            detail=verdict.reason,
            engine=engine,
            source_ip=source_ip or "unknown",
        )
        refused = ProblemError.unauthorized("This caller is not permitted to post events.")
        refused.headers["X-Ack-Ms"] = f"{_ack_ms(started):.1f}"
        raise refused

    # Step 2 — the RAW bytes, bounded, read once and never re-parsed downstream. Bolna
    # signs nothing today, but an engine that does will need the exact bytes (its
    # signature check belongs right here, as a SECOND gate after the source check), and
    # retro-fitting raw-body preservation into a live receiver is miserable.
    raw = await _read_bounded(request)
    if raw is None:
        alert("ROUTE_HANDLER", "webhook_payload_too_large", engine=engine)
        oversized = ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Payload too large",
            detail="The event body exceeds the accepted size.",
            status=413,
            headers={"X-Ack-Ms": f"{_ack_ms(started):.1f}"},
        )
        raise oversized

    # Step 3 — parse defensively. Anyone who reaches this line has cleared the source
    # check, but "the engine's IP sent it" is not "the engine sent well-formed JSON",
    # and `json.loads` raises RecursionError — NOT JSONDecodeError — on a deeply nested
    # document. A 500 here is not cosmetic: Bolna delivers at most once and swallows
    # errors, so a receiver that crashes on one hostile POST is indistinguishable from
    # one that crashes on the real call arriving in the same second.
    payload: dict[str, Any] = {}
    readable = True
    try:
        decoded = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        readable = False
    else:
        if isinstance(decoded, dict):
            payload = decoded
        else:
            readable = False

    event = extract(payload)
    if event is None:
        # Ack anyway: an event we cannot key is one we can never dedupe, and Bolna
        # would not resend it regardless. The poller will pick the call up.
        alert("ROUTE_HANDLER", "webhook_unkeyable", engine=engine)
        return _ack(
            response,
            started,
            engine,
            {
                "status": "ignored",
                "reason": "no execution id" if readable else "unreadable payload",
            },
        )

    payload_digest = body_hash(payload)
    redis_key = f"calevate:wh:{engine}:{event.execution_id}:{payload_digest[:16]}"
    if await _fast_path_seen(redis_key, engine=engine):
        return _ack(
            response,
            started,
            engine,
            {"status": "duplicate", "execution_id": event.execution_id},
        )

    job_id: str | None = None
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session,
            provider=engine,
            # THE UNIT OF WORK IS THE TRANSITION, NOT THE EXECUTION. Bolna fires one
            # webhook per status change (queued → in-progress → completed, TRD §5) with
            # the same execution id each time, and `job_id_for` below already keys the
            # job on (execution, status). Keying the inbox on the execution alone made
            # the two disagree: the FIRST transition claimed the row and enqueued, and
            # every later one — including `completed`, the only transition where cost,
            # recording and transcript exist — came back `duplicate` and enqueued
            # nothing. The post-call pipeline then never ran from a webhook at all;
            # every call waited for the 10-minute reconciliation poller, which makes
            # FLOWS §3.6 ("lead + summary visible < 2 min after hangup") unmeetable and
            # quietly turns D-31's "poller = guarantee of record, webhook = low-latency
            # hint" into "the poller does everything". `pipeline.py` returning
            # `awaiting_completion:{raw_status}` is the other half of the evidence: it
            # expects to be called once per transition.
            event_key=f"{event.execution_id}:{event.raw_status}",
            # The hash of that unit of work, not of this delivery. The inbox reads a
            # changed hash under an existing key as a doctored replay and answers 409 +
            # `webhook_payload_mismatch` — and two deliveries of the SAME transition can
            # still differ in body (a retry with a fuller payload), so hashing the
            # delivery raised a spoofing alarm on healthy traffic. An alarm that always
            # fires is an alarm nobody reads when a real one arrives.
            #
            # Nothing is lost by narrowing it: at an unsigned endpoint the caller
            # controls the entire payload, so a body hash was never evidence of
            # authenticity — the source-IP check is, and the poller is the truth.
            payload_hash=body_hash(
                {
                    "engine": engine,
                    "execution_id": event.execution_id,
                    "raw_status": event.raw_status,
                }
            ),
            event_name=event.raw_status,
        )
        claimed = claim.state != "duplicate"

        if claimed:
            # The minimal event row: forensic trail only (SEC-COMP §4). `signature_valid`
            # records what evidence we actually had, so a later investigation can tell an
            # IP-allowlisted event from a signed one.
            await session.execute(
                text(
                    "INSERT INTO webhook_deliveries (id, direction, source, event_type, "
                    "status, attempts, signature_valid, first_at, last_at, created_at) VALUES "
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

    # PAST THE COMMIT. Everything the key stands for is now durable — the inbox row, the
    # forensic row, the job — so the key cannot outlive a transaction that failed: an
    # exception above propagates and never reaches this line. Reached on the duplicate
    # branch too, because a delivery the inbox has already settled is exactly the thing
    # the next copy should be spared a Postgres round trip for.
    await _remember_fast_path(redis_key, engine=engine)

    if not claimed:
        return _ack(
            response,
            started,
            engine,
            {"status": "duplicate", "execution_id": event.execution_id},
        )

    return _ack(
        response,
        started,
        engine,
        {
            "status": "accepted",
            "execution_id": event.execution_id,
            "job_id": job_id or "deduped",
        },
    )


__all__ = ["INGEST_JOB", "router"]

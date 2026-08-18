"""In-call tool endpoints. LATENCY-CRITICAL (hard rule 3), and today there is exactly one.

`POST /tools/v1/{engine}/opt-out` is the engine-side custom function an agent invokes the
moment a caller says "don't call me again". SEC-COMP §2.3 asks for precisely this ("⇒ tool
adds to tenant `dnc_list` within the call"), and `apps/api/compliance/optout.py` argues at
length why it is built ALONGSIDE the post-call transcript pass rather than instead of it.

The same five obligations the webhook receiver carries, for the same reasons, and the
helpers are IMPORTED from it rather than re-implemented — a second ack-measuring,
body-bounding, source-verifying implementation in the same tiny service is the "two ways
of doing one thing" CLAUDE.md calls a defect even when both work:

1. verify the source before reading a byte of body;
2. ack under 500ms, measured and reported on every path including the refusals — into
   `tool_ack_ms`, this endpoint's OWN series, because the budget that actually governs it
   is TRD §6.2's 100ms and a percentile pooled with the post-call receiver's could never
   show it (D-109 measured the server half at p95 1.4ms single-flight and ~143ms at 250
   concurrent, so the number this series carries is one somebody has to be able to read);
3. defer the real work to ARQ — the tenant, the number and the call are resolved in
   `apps/workers/optout.py` from an authenticated Get Execution (D-31: the payload is a
   hint, the fetch is the truth);
4. no DB writes at all here — this endpoint does not even claim an inbox row, because
   there is no at-most-once event to dedupe: a repeated tool call collapses on the ARQ
   job id, and duplicate suppression of the same number is a no-op by construction;
5. answer every request deliberately — an unsigned endpoint gets malformed bodies,
   enormous bodies and payloads with no execution id, and none of them may be a 500.

WHAT IS ASSUMED AND WHAT IS VERIFIED (D-31/D-32 — an unverified vendor behaviour is a
gate or a marked assumption, never a silent premise):

* VERIFIED: nothing about Bolna's custom-function mechanism. It is OPERATIONS §2 gate 8
  ("test a custom function to our endpoint and record the tool-call p95 — **no timeout is
  documented**").
* ASSUMED, and the assumption is confined to this file: that the engine can be configured
  to POST a JSON body carrying the execution id of the call in progress, and that it
  tolerates a small JSON object in reply. Nothing downstream depends on the SHAPE of that
  body beyond one string, and the endpoint accepts the three spellings an engine plausibly
  uses (`execution_id`, `id`, `call_id`) rather than betting on one.
* CONSEQUENCE, stated plainly rather than hidden: until gate 8 is run and the engine is
  configured with this function, this route is reachable and correct but **nothing calls
  it**, and the post-call transcript pass is what actually closes the compliance hole. The
  route is not half-wired — it is mounted, registered, tested and its job is registered —
  but it is not yet EXERCISED by the vendor, and no reader should mistake one for the
  other.

The reply is `{"status": "accepted"}` and never "done": the write happens in a worker a
few hundred milliseconds later. What the agent may safely tell the caller is that the
request is registered — which is true the moment the job is queued, because the queue is
durable and the post-call pass is behind it.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.settings import get_settings
from calevate_shared.client_address import client_ip
from engine_intake import execution_key, verify_source
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

# The ack accounting, the bounded read and the deadlines, from the receiver that already
# owns them. Private by convention, not by intent — see the module docstring. `TOOL_ACK`
# is what tells the two endpoints apart inside those shared helpers: this one's acks land
# in `tool_ack_ms` and its breaches are named `tool_*`, so the in-call budget (TRD §6.2,
# 100ms) can be read off a series of its own instead of being averaged into the post-call
# receiver's `webhook_ack_ms`.
from webhook_routes import _DURABLE_DEADLINE_S, TOOL_ACK, _ack, _read_bounded, measured

log = get_logger(__name__)

router = APIRouter(prefix="/tools/v1", tags=["in-call-tools"])

# Must equal `apps.workers.optout.OPTOUT_JOB`. Spelled as a literal rather than imported,
# because `apps.workers` is FORBIDDEN in this process (hard rule 3, and
# `tests/voice_runtime_import_surface_test.py` enforces it) — the receiver spells
# `ingest_engine_event` the same way for the same reason. The two are asserted equal in
# `tests/call_optout_test.py`, so the duplication cannot drift.
OPTOUT_JOB = "record_in_call_optout"

# A tool call is an execution id, a language tag and a sentence of reason. A kilobyte is
# already generous; the receiver's megabyte is sized for a transcript-bearing webhook and
# would be an absurd allocation to accept from a stranger here.
_MAX_TOOL_BODY = 4096


class ToolAckOut(BaseModel):
    """The in-call tool's ack, declared for the reason `WebhookAckOut` is (D-303).

    "Accepted" is the only thing this route can truthfully say — the suppression is
    written by a worker a few hundred milliseconds later — so the status is a one-value
    `Literal` rather than a free string, and the model refuses anything else.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]
    execution_id: str
    job_id: str


@router.post(
    "/{engine}/opt-out",
    status_code=202,
    response_model=ToolAckOut,
    summary="In-call opt-out (engine custom function) — queues the suppression",
)
async def in_call_opt_out(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(
        started, engine, _opt_out(engine, request, response, started), meter=TOOL_ACK
    )


async def _opt_out(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """The tool call proper. Split from the route only so `measured` can wrap every exit."""
    source_ip = client_ip(
        request.client.host if request.client else None,
        request.headers,
        app_env=get_settings().app_env,
    )
    verdict = verify_source(engine, source_ip)
    if not verdict.ok:
        alert(
            "ROUTE_HANDLER",
            "tool_source_rejected",
            detail=verdict.reason,
            engine=engine,
            source_ip=source_ip or "unknown",
        )
        raise ProblemError.unauthorized("This caller is not permitted to call this tool.")

    raw = await _read_bounded(request, engine=engine, limit=_MAX_TOOL_BODY, meter=TOOL_ACK)
    if raw is None:
        alert("ROUTE_HANDLER", "tool_payload_too_large", engine=engine)
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Payload too large",
            detail="The tool call body exceeds the accepted size.",
            status=413,
        )

    payload: dict[str, Any] = {}
    try:
        decoded = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        decoded = None
    if isinstance(decoded, dict):
        payload = decoded

    execution_id = execution_key(payload)
    if execution_id is None:
        # A 422, not an ack. This is the one place this service DIFFERS from the webhook
        # receiver, and deliberately: an unkeyable status webhook is still recovered by
        # the 10-minute poller, so acking it costs nothing — an unkeyable TOOL call has
        # no poller behind it, and answering 202 would tell the agent the caller's
        # request was registered when nothing was. The agent must hear a failure so it
        # can fall back to promising a callback, and the post-call pass still catches
        # the words in the transcript.
        alert("ROUTE_HANDLER", "tool_call_unkeyable", engine=engine)
        raise ProblemError(
            kind="validation",
            code="tool_call_unkeyable",
            title="Missing execution id",
            detail="The tool call did not name the execution it belongs to.",
            status=422,
        )

    try:
        async with asyncio.timeout(_DURABLE_DEADLINE_S):
            job_id = await enqueue(
                OPTOUT_JOB,
                {
                    "engine": engine,
                    "execution_id": execution_id,
                    # HINTS ONLY, both bounded and both re-derived downstream where it
                    # matters: the worker reads the number, the direction and the tenant
                    # from the authenticated fetch. These two only become evidence text.
                    "reason": str(payload.get("reason") or "")[:200],
                    "language": str(payload.get("language") or "")[:8],
                },
                # One suppression per execution: the model invoking the function twice,
                # or the engine retrying it, must not queue two jobs. Not a correctness
                # requirement — `record_call_optout` is idempotent — but a queue that
                # collapses the duplicate is cheaper than a database that does.
                job_id=job_id_for(OPTOUT_JOB, engine, execution_id),
            )
    except TimeoutError:
        elapsed = (time.perf_counter() - started) * 1000
        alert("ROUTE_HANDLER", "tool_enqueue_timeout", detail=f"{elapsed:.0f}ms", engine=engine)
        raise ProblemError(
            kind="transient",
            code="tool_queue_unavailable",
            title="Opt-out could not be queued",
            detail="The request was not registered; please tell the caller it will be handled.",
        ) from None

    # Ids only (hard rule 6): no number is in this payload and none is in this line.
    log.info("in_call_optout_queued", extra={"engine": engine, "job_id": job_id or "deduped"})
    return _ack(
        response,
        started,
        engine,
        {"status": "accepted", "execution_id": execution_id, "job_id": job_id or "deduped"},
        meter=TOOL_ACK,
    )


__all__ = ["OPTOUT_JOB", "router"]

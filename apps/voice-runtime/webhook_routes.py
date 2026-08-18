"""Engine webhook receiver. LATENCY-CRITICAL (hard rule 3).

The contract this file must satisfy, in order:

1. **Verify authenticity per engine, before reading a byte of body.** For Bolna that
   is a source-IP allowlist — there is no signature to check (D-31) — plus
   execution-id dedupe. Everything after this step is work done for a caller we have
   already decided to trust, which is why the order matters.
2. **Ack in under 500ms.** Measured AND reported on every response path
   (`X-Ack-Ms` + `record_webhook_ack_ms`), so a regression shows up as a number
   rather than as a mystery — including on the paths a flood would take, which are
   the refusals, the 409 from the inbox and the 500 from a sick driver. That is what
   `measured()` is for; before it, those last two shipped with no header and no sample.
   And BOUNDED, not merely measured, because measuring a nine-second ack does not
   shorten it: the durable section runs under `_DURABLE_DEADLINE_S` and the body read
   under `_BODY_DEADLINE_S`. Those two are the only waits on this path that can outlive
   the caller's patience, and each has a designed answer on breach.
3. **Defer all real work to ARQ.** Nothing here fetches, parses costs, or writes a
   domain row.
4. **No DB writes beyond the minimal event row** — the inbox claim (dedupe) and the
   forensic delivery row. Both are infra tables, neither is tenant-scoped, and the
   tenant is not even resolved here.
5. **Answer every request deliberately.** Unsigned means anyone who learns the URL can
   POST: malformed JSON, 200MB of it, ten thousand nested arrays, an engine name we
   never deployed, a body that dribbles, a connection that hangs up half way. Each of
   those has a chosen answer here; none of them is a 500. The last two were the ones
   this list claimed and did not have.

The deeper reason it is this thin: Bolna's delivery is at-most-once with no retries,
so a slow or failing receiver silently LOSES calls. Being fast is a correctness
property here, not a performance nicety. The 10-minute reconciliation poller is what
makes a loss recoverable (D-31), and it is the poller — not this endpoint — that is
the guarantee of record.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from apps.api.core.alerting import (
    alert,
    record_tool_ack_ms,
    record_webhook_ack_ms,
    record_webhook_replay_divergence,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.observability import set_span_attributes, span, tracing_enabled
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_enqueued
from calevate_shared.client_address import client_ip
from engine_intake import IntakeEvent, engine_label, extract, verify_source
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from starlette.requests import ClientDisconnect

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
#
# **THE KEY IS THE UNIT OF WORK; THE BODY DIGEST IS ITS VALUE.** The key is the same
# `{execution_id}:{raw_status}` transition the inbox claims and `job_id_for` keys the job
# on. It used to carry `body_hash(payload)[:16]` in the KEY, and that one field made the
# two layers disagree about what a duplicate IS. `_claim_and_enqueue` already argues the
# case for the DURABLE hash — "two deliveries of the SAME transition can still differ in
# body (a retry with a fuller payload)" — and the fast path was left keyed on the delivery,
# so:
#
#   * every re-delivery whose body moved by one byte MISSED the cache and opened a
#     transaction. Measured: five replays of one settled transition, each carrying a
#     different integer in an ignored field, cost 15 Postgres statements where the cache
#     is meant to cost zero. At an unsigned endpoint the caller controls the whole body,
#     so that is a Postgres-round-trip amplifier anyone past the source check can pull.
#   * it re-serialised and hashed the WHOLE payload inside the ack. `body_hash` json-dumps
#     with sorted keys before SHA-256, so a body at the megabyte cap cost ~6.4ms of CPU
#     (measured on this box: 3.2ms at 0.5 MiB) on the single event loop that owes every
#     other in-flight delivery a sub-500ms ack — more than the entire rest of the handler,
#     and D-55 puts this process's ceiling at ~250 acks/s of exactly that CPU.
#   * AND IT DETECTED NOTHING. It is tempting to read the old key as a control on an
#     unsigned engine — same execution, same status, different body is what a doctored
#     replay looks like. It was not one. All it did was route that delivery to Postgres,
#     where the inbox compared a `payload_hash` computed from `{engine, execution_id,
#     raw_status}` against itself and, necessarily, matched. Driven against the pristine
#     receiver to be sure: 202 `duplicate`, ZERO alerts, `payload_hash` unchanged, three
#     Postgres statements, and the doctored `agent_id` discarded without reaching a job.
#
# So the divergence is now MEASURED instead of merely being expensive: the key's value is
# `_body_digest(raw)`, and a cache hit whose bytes differ increments
# `webhook_replay_divergence` (`_fast_path_seen`). The answer to the caller is unchanged
# (`duplicate`) and Postgres is still untouched — falling through on a mismatch would just
# restore the amplifier — but an operator can now see that somebody is replaying our
# deliveries with rewritten content, which nothing in this system could see before.
_DEDUPE_TTL_S = 3600
INGEST_JOB = "ingest_engine_event"

# Hard rule 3's number, in one place so the metric, the alert and the docs agree.
_ACK_BUDGET_MS = 500.0

# How long the durable section may take before we stop waiting for it.
#
# THE BUDGET ABOVE IS AN ALERT, NOT A BOUND. Measuring an ack that took nine seconds does
# not stop it taking nine seconds, and the only unbounded wait on this path was Postgres:
# psycopg sets no statement timeout, the engine sets no connect timeout, and
# `pool_pre_ping`'s `SELECT 1` hangs on exactly the same socket as the query it is
# checking. So an unresponsive database did not degrade this service, it froze it — every
# in-flight webhook holding a request, a pooled connection and a worker slot, on the one
# deployable whose entire premise is that it never stalls.
#
# The other two waits were already bounded and are left alone: the fast-path Redis client
# carries `socket_connect_timeout/socket_timeout = 2` (core/redis.py) and the ARQ pool
# `conn_retries=1, conn_timeout=2` (core/queue.py, which argues this exact case — "ten
# times the budget spent learning something the first refused connection already said").
# This is the same doctrine and the same number, applied to the one place that lacked it.
#
# WHY NOT 500ms. The alert and the abandon are different jobs. A deadline at the ack
# budget would give up on a database that is merely slow, and every event it gave up on
# would wait for the 10-minute reconciliation poller — a latency blip promoted to a
# pipeline outage. 500ms says "something is wrong, look at it"; two seconds says "nothing
# is coming, stop holding the request". The gap between them is deliberate.
#
# Breaching it is an ERROR, never an ack: the transaction rolls back, the fast-path key is
# never written (it is only written past the commit), the key stays claimable, and the
# poller — the guarantee of record (D-31) — still recovers the execution.
_DURABLE_DEADLINE_S = 2.0

# The largest body we will hold in memory for an UNAUTHENTICATED caller. An execution
# payload is a status line plus a transcript; a megabyte is already an implausibly long
# call. Refusing above it is safe precisely because the payload is only a hint (D-31) —
# the poller still picks the execution up — whereas buffering whatever a stranger sends
# is an unbounded allocation on the one service that must not stall.
_MAX_BODY_BYTES = 1_048_576

# How long the caller has to finish sending that body.
#
# THE SECOND UNBOUNDED WAIT, and the comment above `_DURABLE_DEADLINE_S` used to say
# Postgres was the only one. It was not: `_read_bounded` iterates `request.stream()` with
# no bound in TIME, only in BYTES, so a caller that dribbles the body holds this handler
# for as long as it likes. Measured before the fix: a body delivered in seven chunks
# 250ms apart was answered **202 with `X-Ack-Ms: 1506.1`** — the budget breached
# threefold, correctly measured, correctly alerted, and not bounded by anything.
#
# THE EDGE DOES NOT COVER THIS ONE, which is why it matters here rather than in nginx.
# `hooks.` is the one vhost that sets `proxy_request_buffering off`
# (`infra/nginx/calevate.conf.template`) — deliberately, so the ack clock starts at the
# first byte the app sees — so the app is exposed to the client's own upload pacing, and
# nginx's `client_body_timeout` bounds the gap BETWEEN reads (60s by default), not the
# total. A sender emitting one byte a minute is inside every timeout in the chain and
# holds a request, a task and up to a megabyte of buffer per connection, indefinitely.
#
# The number is the same doctrine as the durable deadline and deliberately the same size:
# 500ms is the ALERT, this is the ABANDON. A real delivery is a status line plus a
# transcript arriving over the container bridge from a proxy that has already received it
# — sub-millisecond — so two seconds is three orders of magnitude of headroom, and the
# cost of being wrong is one poller cycle (D-31), not a lost call. Worst case a single
# request now holds for this plus `_DURABLE_DEADLINE_S`; both halves are bounded, alerted
# and non-acks, which is the property that was missing.
_BODY_DEADLINE_S = 2.0


class AckRecorder(Protocol):
    """A named metric recorder from `apps.api.core.alerting` (§8: named recorders only)."""

    def __call__(self, ms: float, *, provider: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AckMeter:
    """Which endpoint a request belongs to, for everything on this path that must say so.

    ONE DESCRIPTOR RATHER THAN THREE PARAMETERS, because the three facts have to move
    together: an ack recorded into the receiver's series and a breach alerted under the
    receiver's code are the same mistake twice, and threading them separately is how the
    second one gets forgotten. `tool_routes` imports the helpers here rather than growing
    a second ack-measuring, body-bounding implementation (its own docstring rejects that),
    so this is what tells them apart.

    THE CODES ARE LITERALS, not `f"{surface}_ack_slow"`. `alerting.py` argues the point
    from PagerDuty's caller-supplied `dedup_key`: "every alert here carries a stable code
    rather than a formatted string" — and `runbooks/deploy-failed.md` greps for
    `webhook_ack_slow` by name.
    """

    record: AckRecorder
    slow_code: str
    body_timeout_code: str


#: The post-call receiver: hard rule 3's 500ms, `webhook_ack_ms`.
WEBHOOK_ACK = AckMeter(
    record=record_webhook_ack_ms,
    slow_code="webhook_ack_slow",
    body_timeout_code="webhook_body_timeout",
)
#: The in-call tool endpoints: TRD §6.2's 100ms, `tool_ack_ms`. Same 500ms breach alert —
#: hard rule 3 binds every handler in this service — but its OWN series, so the tighter
#: budget can be read off a percentile instead of being averaged into the receiver's.
TOOL_ACK = AckMeter(
    record=record_tool_ack_ms,
    slow_code="tool_ack_slow",
    body_timeout_code="tool_body_timeout",
)


def _ack_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


async def measured(
    started: float,
    engine: str,
    work: Coroutine[Any, Any, dict[str, str]],
    *,
    meter: AckMeter = WEBHOOK_ACK,
) -> dict[str, str]:
    """Run a handler so that EVERY exit is measured and reported, not just the acks.

    The claim in this module's docstring — "measured AND reported on every response path"
    — was true of the acks and of the refusals the handler raises by hand, and false of
    the two it does not: `ProblemError.conflict` from the inbox (`webhook_payload_mismatch`,
    a 409 raised three frames down) and any unhandled exception (a 500). Both shipped with
    no `X-Ack-Ms` and no `webhook_ack_ms` sample at all — verified by driving them: the
    409 and the 500 came back with the header absent.

    That is the same hole `_refuse` was written to close one layer up, in the same shape:
    a storm of conflicts or of driver errors makes the series go SILENT rather than spike,
    and on a graph silence is indistinguishable from a quiet night. It is also the shape a
    flood takes — those two are what a doctored-replay run and a sick database produce.

    Wrapping rather than decorating keeps mypy able to see the return type, and keeps the
    accounting in ONE place for both handlers in this service.
    """
    try:
        return await work
    except ProblemError as refusal:
        # `setdefault`: a raise site that already stamped a number it measured itself
        # keeps it. Nothing does today — this is the only stamper — but a future one
        # should not be silently overwritten with a later reading.
        refusal.headers.setdefault("X-Ack-Ms", _refuse(started, engine, meter=meter))
        raise
    except Exception:
        # No response object to stamp: the problem+json for a 500 is assembled by
        # `install_error_handlers`, outside this frame. The METRIC is the half that can
        # still be recorded, and it is the half a dashboard reads.
        _refuse(started, engine, meter=meter)
        raise


def _refuse(started: float, engine: str, *, meter: AckMeter = WEBHOOK_ACK) -> str:
    """Measure a response we are about to refuse, and hand back its `X-Ack-Ms` value.

    Refusals used to set the header and record nothing. The header is for whoever is
    holding a curl; the METRIC is what a dashboard and an SLO rule read, and this file
    already argues the case in `_ack`: "instrumenting only the happy path measures the
    endpoint at its least stressed, which is the opposite of useful". A refusal storm is
    the most stressed this endpoint ever is, and it was the one shape missing.

    It also matters for the specific incident the rejection alert is written for — the
    vendor renumbers and every webhook 401s. With refusals unmeasured, `webhook_ack_ms`
    for provider=bolna does not spike, it goes SILENT, which on a graph is indistinguish-
    able from a quiet night.

    `engine` is bounded to the engines we actually run before it becomes a label
    (`engine_intake.engine_label`, which carries the argument and is now the ONE place
    that bounds it — this function used to do it inline while the `alert()` on the
    refusal path passed the raw value through).
    """
    elapsed = _ack_ms(started)
    meter.record(elapsed, provider=engine_label(engine))
    return f"{elapsed:.1f}"


def _server_span() -> Any:
    """The `TracingMiddleware` span for this request, or None when tracing is off.

    THE BUDGET (hard rule 3). With no collector configured `tracing_enabled()` is one
    module-global read and this returns immediately — the opentelemetry import below is
    never reached, so a deploy without a collector runs the receiver it runs today. The
    measured cost of the whole instrumentation on this path is in the report and in
    `tests/tracing_stages_test.py`; it was measured rather than assumed, because "a
    context manager is basically free" is how a 500ms budget gets spent.
    """
    if not tracing_enabled():
        return None
    from opentelemetry.trace import get_current_span

    active = get_current_span()
    return active if active.get_span_context().is_valid else None


def _ack(
    response: Response,
    started: float,
    engine: str,
    body: dict[str, str],
    *,
    meter: AckMeter = WEBHOOK_ACK,
) -> dict[str, str]:
    """Every acked path leaves through here, so the budget is measured, alerted and
    REPORTED identically on all of them.

    The early returns are exactly the paths a flood takes — a duplicate storm, a stream
    of unkeyable payloads. Instrumenting only the happy path measures the endpoint at
    its least stressed, which is the opposite of useful.
    """
    elapsed = _ack_ms(started)
    meter.record(elapsed, provider=engine)
    # The same number the metric and the `X-Ack-Ms` header carry, on the span. "The ack
    # was slow" is a metric; "the ack was slow AND its inbox-claim child took 480ms of
    # it" is the thing an operator can act on, and it needs both halves on one trace.
    set_span_attributes(_server_span(), ack_ms=round(elapsed, 1), engine=engine)
    if elapsed > _ACK_BUDGET_MS:
        # Hard rule 3 has a number in it; treat breaching it as an incident signal.
        alert("ROUTE_HANDLER", meter.slow_code, detail=f"{elapsed:.0f}ms", engine=engine)
    response.headers["X-Ack-Ms"] = f"{elapsed:.1f}"
    return body


def _body_digest(raw: bytes) -> str:
    """A fingerprint of the bytes we were sent — the VALUE the fast-path key carries.

    OVER THE RAW BYTES, not over the parsed payload. `reliability.body_hash` json-dumps
    with sorted keys before hashing, which is the right answer for a body that must
    survive re-serialisation and the wrong one here: we already hold the bytes, we are
    inside a 500ms ack, and canonicalising a megabyte costs ~6.4ms of CPU against ~0.64ms
    for hashing it (measured on this box at 0.5 MiB: 3.2ms against 0.32ms). Ten times
    cheaper, and STRICTER — a replay that reorders keys is still a replay with different
    bytes, which is exactly the thing being counted.

    Truncated to 128 bits: this is a divergence signal, not a signature.
    """
    return hashlib.sha256(raw).hexdigest()[:32]


async def _fast_path_seen(redis_key: str, digest: str, *, engine: str) -> bool:
    """Has this TRANSITION already been settled? A READ, never a write.

    Redis being unavailable degrades correctly and deliberately: we answer "not seen" and
    fall through to the durable claim, which is the dedupe that carries the guarantee.

    WHAT THE STORED VALUE IS FOR — and this is the half that answers "what detects an
    altered body at an unsigned endpoint". The answer used to be NOTHING, before and after
    the key stopped carrying the body: the `payload_hash` the inbox is given is
    `body_hash({engine, execution_id, raw_status})`, a pure function of the key, so its
    "same key, different hash ⇒ doctored replay" branch is a tautology at this endpoint and
    cannot fire on a body change. That is deliberate (`_claim_and_enqueue` argues it) and it
    was verified rather than assumed: a doctored re-delivery driven against the pristine
    receiver produced 202 `duplicate`, ZERO alerts, an unchanged `payload_hash` and three
    Postgres statements. It reached the database and the database had nothing to say.
    Only `duplicate_count` moved, and that counter cannot tell a byte-identical replay from
    a rewritten one — it counts both, and the cache already hid the identical ones.

    So the key now carries the digest of the delivery that settled it, and a hit whose
    bytes differ is COUNTED (`record_webhook_replay_divergence`) instead of vanishing. That
    is strictly more than either previous state, at a tenth of the CPU the old body-keyed
    version spent, and without the Postgres round trip it spent it on.
    """
    with span("webhook.fastpath", engine=engine) as stage:
        try:
            settled = await get_redis().get(redis_key)
        except Exception:  # Redis down: fall through to the durable claim, never 500
            log.warning("webhook_fastpath_unavailable", extra={"engine": engine})
            # `outcome`, not an exception on the span: Redis being down here is a
            # DESIGNED degradation, and a span marked ERROR for a path that behaved
            # correctly is how a trace backend teaches people to ignore it.
            set_span_attributes(stage, outcome="unavailable")
            return False
        set_span_attributes(stage, deduped=settled is not None)
        if settled is not None and settled != digest:
            # Recorded, never acted on: the answer is still `duplicate`, because the
            # payload is a hint and the authenticated Get Execution is the truth (D-31).
            # Falling through to Postgres on a mismatch would hand any caller past the
            # source check a transaction per request, which is the amplifier this key
            # shape exists to remove. Ids and labels only (hard rule 6) — the diverging
            # bytes are never logged.
            record_webhook_replay_divergence(provider=engine)
            log.warning("webhook_replay_body_diverged", extra={"engine": engine})
            set_span_attributes(stage, body_diverged=True)
        return settled is not None


async def _remember_fast_path(redis_key: str, digest: str, *, engine: str) -> None:
    """Record that this transition is settled, and by which bytes — called only after the
    claim has COMMITTED.

    Best effort by design: a key we failed to write costs one extra Postgres round trip
    on the next copy of this delivery, which is the cheap direction to be wrong in. The
    expensive direction — a key we wrote for work that never landed — is what the
    post-commit placement removes.
    """
    try:
        await get_redis().set(redis_key, digest, ex=_DEDUPE_TTL_S)
    except Exception:
        log.warning("webhook_fastpath_unavailable", extra={"engine": engine})


async def _read_bounded(
    request: Request,
    *,
    engine: str,
    limit: int = _MAX_BODY_BYTES,
    meter: AckMeter = WEBHOOK_ACK,
) -> bytes | None:
    """The raw body, or None if the caller exceeded the cap.

    Streamed rather than `await request.body()` so an oversized POST is abandoned after
    a megabyte instead of after all of it. The declared length is checked first, which
    turns the common case into a rejection that reads nothing at all.

    `limit` defaults to this endpoint's megabyte and is overridden by the in-call tool
    route (`tool_routes.py`), whose bodies are three fields: the megabyte is sized for a
    transcript-bearing webhook, and every endpoint should refuse at ITS own plausible
    size rather than at the largest one in the service.

    BOUNDED IN TIME AS WELL AS IN BYTES (`_BODY_DEADLINE_S`), and RAISES rather than
    returning for the two ways a body fails to arrive at all. Both are deliberate answers
    where there used to be no answer:

    * **the caller dribbles** — measured at 1506ms of ack before this bound existed, and
      unbounded in principle. 408, alerted, non-ack: the poller is the guarantee of
      record (D-31), so refusing costs one cycle and holding costs the service.
    * **the caller hangs up mid-body** — Starlette raises `ClientDisconnect` out of
      `request.stream()`, which nothing caught, so a truncated POST became an
      `unhandled_exception`: an ERROR traceback, a 500, and an `alert()` under the
      ROUTE_HANDLER:unhandled_exception fingerprint. That last one is the part that
      matters. `alerting._admit` suppresses repeats of a fingerprint for 15 minutes, so
      one half-open POST every quarter hour — free, from anywhere the source check lets
      through, and indistinguishable from a flaky mobile network — kept the receiver's
      REAL crash alarm permanently suppressed. A hang-up is not our failure: it is logged
      at WARNING with ids only and answered 400, and the catch-all alarm stays for
      crashes.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(_BODY_DEADLINE_S):
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return None
                chunks.append(chunk)
    except TimeoutError:
        # Byte counts, never bytes: hard rule 6, and the count is the fact an operator
        # needs to tell a stalled sender from one that never started.
        alert(
            "ROUTE_HANDLER",
            meter.body_timeout_code,
            detail=f"{size}B in {_BODY_DEADLINE_S:.0f}s",
            engine=engine,
        )
        raise ProblemError(
            kind="transient",
            code="body_read_timeout",
            title="Request body did not arrive",
            detail="The body was not delivered in time; this request was not accepted.",
            status=408,
        ) from None
    except ClientDisconnect:
        log.warning("intake_body_disconnected", extra={"engine": engine, "bytes": size})
        raise ProblemError(
            kind="validation",
            code="body_incomplete",
            title="Request body incomplete",
            detail="The connection closed before the body was delivered.",
            status=400,
        ) from None
    return b"".join(chunks)


class WebhookAckOut(BaseModel):
    """What the engine is told, as a DECLARED shape rather than a `dict[str, str]` (D-303).

    Four acks leave this receiver — `accepted`, `duplicate` (twice) and `ignored` — and
    until this model they left as bare mappings assembled at four `return` sites. Nothing
    leaked: every value here is ours (a status word, an execution id, an ARQ job id, one
    of two fixed reason strings). But this endpoint's INPUT is a vendor payload that can
    carry a caller's phone number, `apps/api`'s redaction guardrail does not walk this
    service's schema at all, and the distance between "an ack" and "an ack that echoes
    the field we could not key on" is one debugging session.

    `extra="forbid"` makes the model the output whitelist BACKEND-PATTERNS §1 asks for,
    and `response_model_exclude_none=True` on the route keeps the wire bytes exactly what
    they were — an ack with three null keys in it would be a new shape shipped to a
    vendor for a schema's benefit.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "duplicate", "ignored"]
    execution_id: str | None = None
    job_id: str | None = None
    #: Why an event was ignored, in OUR words — never the payload's. The two values are
    #: written at the one `ignored` site below.
    reason: str | None = None


@router.post(
    "/engine/{engine}",
    status_code=202,
    response_model=WebhookAckOut,
    # The bytes on the wire are unchanged: `duplicate` still carries an execution id and
    # nothing else, `ignored` still carries a reason and nothing else.
    response_model_exclude_none=True,
    summary="Engine status webhook (unsigned for Bolna — hint only, poller is truth)",
)
async def engine_webhook(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(started, engine, _receive(engine, request, response, started))


async def _receive(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """The receiver proper. Split from the route only so `measured` can wrap every exit."""
    # Step 1 — WHO is calling, decided from the socket and the edge headers alone.
    # It reads no body, so a caller we are going to refuse never gets us to allocate
    # for them: on a public, unsigned endpoint that ordering is the difference between
    # a rejection and a memory-exhaustion primitive.
    source_ip = client_ip(
        request.client.host if request.client else None,
        request.headers,
        app_env=get_settings().app_env,
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
            # BOUNDED, like the metric label (`_refuse`). This is the one alert whose
            # `engine` is a stranger's string rather than one of ours, and it reached a
            # structured log field on every request and the alert body every 15 minutes.
            engine=engine_label(engine),
            source_ip=source_ip or "unknown",
        )
        raise ProblemError.unauthorized("This caller is not permitted to post events.")

    # Step 2 — the RAW bytes, bounded, read once and never re-parsed downstream. Bolna
    # signs nothing today, but an engine that does will need the exact bytes (its
    # signature check belongs right here, as a SECOND gate after the source check), and
    # retro-fitting raw-body preservation into a live receiver is miserable.
    raw = await _read_bounded(request, engine=engine)
    if raw is None:
        alert("ROUTE_HANDLER", "webhook_payload_too_large", engine=engine)
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Payload too large",
            detail="The event body exceeds the accepted size.",
            status=413,
        )

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
        #
        # "Cannot key" covers both a payload with no execution id and one whose id or
        # status we refuse to store (over-long or control characters — `engine_intake.
        # _keyable`). The reason string does not distinguish them on purpose: it is read
        # by the vendor's logs, and the distinction is ours to keep in the alert.
        alert("ROUTE_HANDLER", "webhook_unkeyable", engine=engine)
        return _ack(
            response,
            started,
            engine,
            {
                "status": "ignored",
                "reason": "unusable execution key" if readable else "unreadable payload",
            },
        )

    redis_key = f"calevate:wh:{engine}:{event.execution_id}:{event.raw_status}"
    digest = _body_digest(raw)
    if await _fast_path_seen(redis_key, digest, engine=engine):
        return _ack(
            response,
            started,
            engine,
            {"status": "duplicate", "execution_id": event.execution_id},
        )

    # The durable half of the dedupe, under the one deadline on this path. Everything
    # that can wait on a socket for an unbounded time is inside it: the three Postgres
    # statements and the enqueue.
    try:
        async with asyncio.timeout(_DURABLE_DEADLINE_S):
            claimed, job_id = await _claim_and_enqueue(
                engine, event, signed=verdict.method == "hmac"
            )
    except TimeoutError:
        # NOT an ack. The transaction rolled back with the cancellation, so the inbox key
        # is still free and the reconciliation poller can still do this work; saying 202
        # here would be a call we told the vendor we had taken and then dropped.
        #
        # Alerted here as well as by the 5xx path in `install_error_handlers`, because
        # only this line knows which engine and how long — the two facts an operator
        # needs to tell "Postgres is gone" from "one engine's traffic is pathological".
        # The header and the metric are `measured`'s job, here as on every other exit.
        alert(
            "ROUTE_HANDLER",
            "webhook_claim_timeout",
            detail=f"{_ack_ms(started):.0f}ms",
            engine=engine,
        )
        raise ProblemError(
            kind="transient",
            code="webhook_claim_unavailable",
            title="Event could not be recorded",
            detail="The event store did not respond in time; this event was not accepted.",
        ) from None

    # PAST THE COMMIT. Everything the key stands for is now durable — the inbox row, the
    # forensic row, the job — so the key cannot outlive a transaction that failed: an
    # exception above propagates and never reaches this line. Reached on the duplicate
    # branch too, because a delivery the inbox has already settled is exactly the thing
    # the next copy should be spared a Postgres round trip for.
    await _remember_fast_path(redis_key, digest, engine=engine)

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


async def _claim_and_enqueue(
    engine: str, event: IntakeEvent, *, signed: bool
) -> tuple[bool, str | None]:
    """Claim the transition, write the forensic row, queue the work. One transaction.

    Returns (claimed, job_id) — `claimed` False means the inbox had already settled this
    transition. Lives in its own function so the whole unit can be given a deadline
    without the caller having to reason about which half of an interleaved block was
    reached; everything here either commits together or rolls back together.
    """
    job_id: str | None = None
    # The durable half of the dedupe, and the only Postgres round trip on the ack path —
    # so when the budget is blown this span is the first place to look. It wraps the
    # whole transaction (claim + forensic row + enqueue + mark), because that is the
    # unit that has to commit, and a claim span that ended before the commit would
    # attribute a slow flush to nothing at all.
    with span("webhook.inbox_claim", kind="client", engine=engine) as claim_stage:
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
                        "status, attempts, signature_valid, first_at, last_at, created_at) "
                        "VALUES (:id, 'in', :source, :event_type, 'received', 1, :sig, "
                        "now(), now(), now())"
                    ),
                    {
                        "id": uuid7(),
                        "source": engine,
                        "event_type": event.raw_status,
                        "sig": signed,
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
        # Outside the session, inside the span: set after the `async with` so the value
        # describes a transaction that actually committed.
        set_span_attributes(claim_stage, claim_status=claim.state, deduped=not claimed)
    return claimed, job_id


__all__ = ["INGEST_JOB", "TOOL_ACK", "WEBHOOK_ACK", "AckMeter", "measured", "router"]

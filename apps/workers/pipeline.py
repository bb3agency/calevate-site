"""Post-call pipeline (TRD §8, FLOWS §6). Idempotent, keyed by call.

    ingest_engine_event → (authenticated fetch is the TRUTH)
      persist call → recording copy → transcript + redaction → extraction →
      lead upsert → metering → hot-lead notification

Three properties this file exists to guarantee:

1. **The webhook is a hint, the fetch is the truth** (D-31). Every job re-reads the
   execution from the engine rather than trusting the payload that woke it. That is
   what makes a duplicate webhook, a poller rediscovery and a manual replay all
   converge on the same result.
2. **`completed` is the trigger, not `disconnected`.** Cost, recording and transcript
   are null until then (TRD §5), so a pipeline that fired on disconnect would meter
   zeros and store an empty transcript. `snapshot.billable_ready` is that gate.
3. **Every step is re-runnable.** Upserts, not inserts; CAS on status transitions;
   `usage_events` written once per (call, unit) because the ledger is append-only and
   a double-run would double-bill (hard rule 4 + 7). Both jobs lean on this: neither
   would be allowed a retry ladder without it.

Both jobs also share ONE failure policy — `_is_transient` decides, `_abandon_ingest` and
`_abandon_post_call` act on it — because arq 0.28 retries a job only for `arq.Retry`,
and a job that signals "try again" by re-raising is a job with `max_tries` in name only.

SLO: lead visible in the client dashboard under 2 minutes after hangup — measured with
`record_pipeline_lag`, not assumed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NoReturn
from uuid import UUID

from arq import Retry
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.extraction import ExtractionOutput, ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment
from apps.api.billing.caps import CAPS_CTE, lock_tenant_spend_state, over_cap_sql
from apps.api.billing.rates import MONEY_Q, ROUNDING, billable_tier
from apps.api.billing.service import charge_for_call, plan_tier_of
from apps.api.compliance.optout import (
    DETECTED_POST_CALL,
    OptOutSignal,
    detect_opt_out,
    record_call_optout,
)
from apps.api.core.alerting import (
    alert,
    record_pipeline_lag,
    record_reconciliation_listing_incomplete,
    record_reconciliation_repair,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.observability import set_span_attributes, span, tracing_enabled
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.integrations import service as integrations
from apps.api.reliability.service import enqueue_outbox, mark_inbox_failed, mark_inbox_processed
from apps.workers.extraction import extract_call
from apps.workers.moments import derive_moments, merge_moments
from apps.workers.redaction import redact
from apps.workers.storage import (
    StorageUnavailableError,
    archive_payload,
    copy_recording,
    payload_key,
)

log = get_logger(__name__)

POSTCALL_JOB = "run_post_call_pipeline"
INGEST_JOB = "ingest_engine_event"

# Hot-lead rule (FLOWS §6): these reach the owner within 2 minutes.
HOT_LEAD_STATUSES = frozenset({"hot"})
HOT_LEAD_FIELD_TRIGGERS: dict[str, frozenset[str]] = {
    "urgency": frozenset({"emergency", "urgent"}),
    "intent": frozenset({"buy", "book"}),
}

# --- stage spans --------------------------------------------------------------
#
# `traced_job` gives this file ONE span per job, which answers "the lead took four
# minutes" with "yes it did". The stages below are what turn that into an answer: each
# `span("pipeline.…")` is a child of the job span, so the trace reads as a flame graph
# of the things this pipeline actually does and the model round trip inside
# `extract_call` — the usual culprit — is a bar you can see rather than a bar you infer.
# The recording copy has one too, and it is not decoration: it is the only stage that
# waits on a THIRD PARTY's network, so "the lead took four minutes" is answered by it
# more often than by anything else, and its `outcome` says whether it fetched at all.
#
# Attributes are ids, counts and durations, nothing else (hard rule 6). Note what is
# NOT written: no field names, no summary, no transcript length in characters keyed as
# `transcript_*` — `transcript`, `text`, `extraction` and `payload` are all REDACT_KEYS
# substrings, so a key containing them is refused by `sanitize_attributes` before its
# value is even looked at. The names here are chosen to pass that filter honestly, not
# to slip past it.


def _job_span() -> Any:
    """The enclosing `traced_job` span, or None when tracing is off.

    Used to stamp the pipeline's own SLO number onto the trace. The opentelemetry
    import is local and guarded: workers are not the latency path, but this module is
    imported by `apps/workers/settings.py` at boot and the SDK must stay unimported
    when no collector is configured (the subprocess assertion in tracing_test.py).
    """
    if not tracing_enabled():
        return None
    from opentelemetry.trace import get_current_span

    active = get_current_span()
    return active if active.get_span_context().is_valid else None


# --- tenant resolution --------------------------------------------------------


async def _resolve_agent(
    session: AsyncSession, engine: str, engine_agent_ref: str | None
) -> tuple[UUID, UUID] | None:
    """engine_agent_ref → (tenant_id, agent_id). The ONLY bridge from their id space to
    ours; an adapter must never guess a tenant (hard rule 1).

    Reads `engine_agent_routes`, not `agents`: at this point there is no session and no
    tenant, so the lookup is inherently cross-tenant — and `agents` is FORCE-RLS'd and
    stays that way. The routing table exists precisely so this resolution never needs
    an RLS exemption.
    """
    if not engine_agent_ref:
        return None
    row = (
        await session.execute(
            text(
                "SELECT tenant_id, agent_id FROM engine_agent_routes "
                "WHERE engine_agent_ref = :ref AND engine = :engine AND active"
            ),
            {"ref": engine_agent_ref, "engine": engine},
        )
    ).first()
    return (row[0], row[1]) if row else None


# --- job 1: ingest ------------------------------------------------------------

# The same ladder, and the same reasoning, as `outbound_webhooks.RETRY_BACKOFF_S`: one
# entry shorter than the budget because the last attempt has nothing after it, and real
# backoff rather than a flat re-poll — an engine that is restarting wants half a minute,
# and an engine that is genuinely down should not be re-hit every few seconds.
RETRY_BACKOFF_S: tuple[float, ...] = (30.0, 120.0)

# Engine failures where an IDENTICAL retry can still succeed, which is the only kind
# worth a rung on the ladder. `engine_unreachable` is the transport never completing
# (DNS, refused, timeout, TLS) — the adapter's own equivalent of "no status at all" —
# and `engine_rate_limited` is `kind="transient"`, which the error ladder defines as
# "identical retry can work".
#
# Deliberately NOT here: `engine_rejected`. That is the engine answering, and its answer
# is a verdict on the request — most often a 404 for an execution it has never heard of
# (a replayed webhook, a hand-typed id, an execution on another account). Re-fetching it
# fails identically three times, thirty seconds and two minutes apart, and the only thing
# the ladder buys is a later terminal alert. The adapter collapses 4xx and 5xx into that
# one code, so a genuine engine-side 500 is not retried here either; the reconciliation
# poller (D-31) is what re-drives it, and it is the guarantee of record regardless.
TRANSIENT_ENGINE_CODES = frozenset({"engine_unreachable", "engine_rate_limited"})


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _is_transient(exc: BaseException) -> bool:
    """Is another attempt capable of a different outcome?

    A `ProblemError` is the engine layer's considered verdict, so it is read as one. Any
    OTHER exception is our own infrastructure failing mid-job — a database blip, a Redis
    hiccup — and those are blips by nature; a genuine bug retries three times and stops,
    which is a cheap price for not dropping an at-most-once call on a transient fault.
    """
    if isinstance(exc, ProblemError):
        return exc.kind == "transient" or exc.code in TRANSIENT_ENGINE_CODES
    return True


async def _abandon_ingest(
    *, inbox_row_id: Any, exc: Exception, attempt: int, execution_id: str
) -> NoReturn:
    """Record the failure on the inbox row, then either ask for a retry or stop loudly.

    **`arq.Retry`, not a bare `raise`.** arq 0.28 retries a job only for `Retry`,
    `RetryJob` or `CancelledError`; every other exception sets `finish=True` and the job
    leaves the queue after ONE attempt (`arq/worker.py`, the `else` branch in `run_job`'s
    handler). This function used to signal "try again later" by re-raising whatever it
    caught, so `WorkerSettings.max_tries = 3` was decorative here and a fetch that failed
    on a network blip was a call that only the 10-minute poller could recover.

    The inbox row is marked FAILED either way, which is what makes the key re-claimable:
    `claim_inbox_event` re-claims a `failed` row by CAS, so neither a blip nor a terminal
    rejection may permanently poison an at-most-once event key.
    """
    if inbox_row_id:
        async with untenanted_session() as session:
            await mark_inbox_failed(
                session, row_id=UUID(str(inbox_row_id)), error=type(exc).__name__
            )
    if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_retry_after(attempt)) from exc
    # Give up loudly, whether the budget ran out or the engine rejected the read
    # outright. A silent stop is indistinguishable from "no events happened", and this
    # one costs a call: the poller only re-drives executions the engine will still list.
    alert(
        "WORKER_TERMINAL",
        "engine_ingest_abandoned",
        detail=(
            f"{type(exc).__name__} after {attempt} attempt(s)"
            if _is_transient(exc)
            else f"{type(exc).__name__} is permanent, not retried"
        ),
        execution_id=execution_id,
    )
    raise exc


def _ingest_target(payload: dict[str, Any]) -> tuple[str, str, Any]:
    """The engine, the execution and the inbox row this job runs on — or a PERMANENT
    failure, exactly as `_post_call_target` reports one for the other job.

    A job payload with no usable `execution_id` cannot be fixed by waiting: the same dict
    is parsed three identical times. Reported as a `validation` ProblemError so the ONE
    transient/permanent split (`_is_transient`) classifies it, rather than a bare KeyError
    escaping the failure policy — which is what it used to do, and arq finishes a job on
    the first attempt for anything that is not `arq.Retry`.

    Ids only in the message, never the payload (hard rule 6).
    """
    try:
        return (
            str(payload.get("engine") or "fake"),
            str(payload["execution_id"]),
            payload.get("inbox_row_id"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="ingest_payload_invalid",
            title="Unusable engine-event job payload",
            detail="The ingest job was enqueued without a usable execution id.",
        ) from exc


async def ingest_engine_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Enqueued by the voice-runtime receiver and by the reconciliation poller.

    Does the minimum that must happen synchronously with the event: fetch the truth,
    resolve the tenant, upsert the call row so the dashboard's live tile is right, and
    hand off to the heavy pipeline only once the engine says the call is complete.

    **THE FAILURE POLICY WRAPS THE WHOLE JOB, and it did not use to (D-148).** Two of this job's
    five steps were inside a `try` — the engine fetch and the enqueue — and the three
    between them were not: `_resolve_agent`, `_upsert_call` (which is where the call row
    and the A/B arm attribution are written) and `mark_inbox_processed`. A database blip
    in any of those raised bare, so arq 0.28 finished the job after ONE attempt
    (`arq/worker.py::run_job` retries only for `Retry`/`RetryJob`/`CancelledError`), NO
    alert fired, and the inbox row was left in `processing` — which `claim_inbox_event`
    answers `duplicate` for the whole `CLAIM_LEASE`, so a vendor retry inside those ten
    minutes was dropped too. Measured on a real worker before the fix: 1 attempt, 0
    alerts, row still `processing`. The 10-minute poller bounded the damage, which is
    exactly the inversion `_abandon_ingest` exists to prevent — the ladder is the fast
    recovery and the poller is the guarantee, not the other way round.

    So the stages live in `_ingest_stages` and this wrapper owns the policy, the same
    shape `run_post_call_pipeline` already used. No stage has to remember one, and none
    of them can quietly opt out.

    **The inbox row is closed LAST.** `processed` is what makes the webhook permanently
    deduped, so it may only be written once every side effect this job owes has actually
    been queued. Marking it before the enqueue meant a crash in between left the event
    deduped forever and the pipeline never queued — bounded by the poller, but backwards.
    """
    # arq's number, never ours: a `job_try` we injected could only confirm that an `if`
    # compares two integers correctly, not that the ladder above it exists.
    attempt = int(ctx.get("job_try", 1))
    # For the alert only, and only when the payload was too broken to parse. Ids.
    execution_hint = str(payload.get("execution_id") or "unknown")
    try:
        engine_name, execution_id, inbox_row_id = _ingest_target(payload)
        return await _ingest_stages(engine_name, execution_id, inbox_row_id, payload)
    except Retry:
        # A stage that already chose its own ladder. Re-deciding it here would overwrite
        # the delay it picked and hide which stage asked.
        raise
    except Exception as exc:
        await _abandon_ingest(
            inbox_row_id=payload.get("inbox_row_id"),
            exc=exc,
            attempt=attempt,
            execution_id=execution_hint,
        )


async def _ingest_stages(
    engine_name: str, execution_id: str, inbox_row_id: Any, payload: dict[str, Any]
) -> str:
    """Fetch the truth, resolve the tenant, upsert the call, hand off. No failure policy
    of its own — see `ingest_engine_event`, which owns the one both jobs share.

    `payload` is still passed whole for the ONE thing the snapshot cannot supply: the
    webhook's `engine_agent_ref`, which is the fallback when the engine's own record
    omits it.
    """
    snapshot = await get_engine().get_execution(execution_id)

    # The snapshot's ref wins over the webhook's: the fetch is the truth (D-31), and
    # the poller path has no webhook payload at all.
    agent_ref = snapshot.engine_agent_ref or payload.get("engine_agent_ref")
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, agent_ref)
    if resolved is None:
        # An event for an agent we do not know: never invent a tenant, never drop it
        # silently. This is how a mis-provisioned agent gets noticed on day one.
        alert(
            "WORKER_TERMINAL",
            "engine_agent_unmapped",
            detail=f"engine={engine_name}",
            execution_id=execution_id,
        )
        if inbox_row_id:
            async with untenanted_session() as session:
                await mark_inbox_failed(
                    session, row_id=UUID(str(inbox_row_id)), error="agent ref not mapped"
                )
        return "unmapped"

    tenant_id, agent_id = resolved
    call_id = await _upsert_call(tenant_id, agent_id, snapshot, agent_ref)

    if snapshot.billable_ready:
        # A failure here reaches `_abandon_ingest` through the caller, which marks the
        # row failed while it is still `enqueued` rather than `processed` — so the key
        # goes back to `claim_inbox_event`'s CAS and the retry re-drives the whole job.
        # The reverse order — closing the row first — turned this same failure into a
        # permanently deduped webhook with no pipeline behind it.
        await enqueue(
            POSTCALL_JOB,
            {
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "engine": engine_name,
                "execution_id": execution_id,
            },
            job_id=job_id_for(POSTCALL_JOB, str(call_id)),
        )
        outcome = "pipeline_enqueued"
    else:
        outcome = f"awaiting_completion:{snapshot.raw_status}"

    # LAST: everything this job owed is queued, so the event may now be closed.
    if inbox_row_id:
        async with untenanted_session() as session:
            await mark_inbox_processed(session, row_id=UUID(str(inbox_row_id)))
    return outcome


async def _upsert_call(
    tenant_id: UUID, agent_id: UUID, snapshot: ExecutionSnapshot, engine_agent_ref: str | None
) -> UUID:
    """Idempotent by `engine_call_id`. Status only ever moves forward: a late `ringing`
    webhook arriving after `completed` must not un-complete a finished call."""
    with span("pipeline.call_upsert", tenant_id=str(tenant_id), agent_id=str(agent_id)) as stage:
        resolved = await _upsert_call_row(tenant_id, agent_id, snapshot, engine_agent_ref)
        set_span_attributes(stage, call_id=str(resolved))
    return resolved


async def _upsert_call_row(
    tenant_id: UUID, agent_id: UUID, snapshot: ExecutionSnapshot, engine_agent_ref: str | None
) -> UUID:
    direction = snapshot.direction
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "from_e164, to_e164, status, started_at, ended_at, duration_s, "
                    "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, :dir, :from_e, "
                    ":to_e, :status, :started, :ended, :dur, now(), now()) "
                    "ON CONFLICT (engine_call_id) DO UPDATE SET "
                    "  status = EXCLUDED.status, "
                    "  started_at = COALESCE(calls.started_at, EXCLUDED.started_at), "
                    "  ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at), "
                    "  duration_s = COALESCE(EXCLUDED.duration_s, calls.duration_s), "
                    "  updated_at = now() "
                    "WHERE calls.status NOT IN ('completed', 'failed', 'no_answer', 'busy', "
                    "'voicemail') OR EXCLUDED.status = 'completed' "
                    "RETURNING id"
                ),
                {
                    "id": call_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ecid": snapshot.engine_call_id,
                    "dir": direction,
                    "from_e": snapshot.from_e164,
                    "to_e": snapshot.to_e164,
                    "status": snapshot.status,
                    "started": snapshot.started_at,
                    "ended": snapshot.ended_at,
                    "dur": snapshot.duration_s,
                },
            )
        ).first()
        if row is None:
            # The conflict's WHERE clause refused the update (terminal row already
            # there): read the existing id rather than treating it as an error.
            row = (
                await session.execute(
                    text("SELECT id FROM calls WHERE engine_call_id = :ecid"),
                    {"ecid": snapshot.engine_call_id},
                )
            ).first()
            if row is None:  # pragma: no cover — only reachable on a concurrent delete
                raise RuntimeError("call row vanished during upsert")
        resolved_id = UUID(str(row[0]))
        await _record_arm_the_engine_ran(
            session, tenant_id=tenant_id, call_id=resolved_id, engine_agent_ref=engine_agent_ref
        )
    return resolved_id


async def _record_arm_the_engine_ran(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    engine_agent_ref: str | None,
) -> None:
    """Attribute this call to a script arm IF the engine says an arm's agent ran it.

    A/B ATTRIBUTION FOR CALLS WE DID NOT PLACE (ROADMAP M3)
    --------------------------------------------------------
    `agents/service.py::dispatch_call` attributes an OUTBOUND call by drawing a bucket
    before it dials. Nothing draws anything here, and nothing may: by the time this row
    exists the call is over, the caller has already heard a script, and picking an arm
    now would name one they never heard. That is not attribution, it is fabrication, and
    it would be invisible in the data — which is why the rule below is a rule about
    FACTS and not about buckets.

    The fact available is the one the engine reports: `ExecutionSnapshot.
    engine_agent_ref` names the agent object that ran the call, and `publish_variant`
    gives every arm its own engine agent with its own ref. So:

    * ref names an ARM  → that call ran that arm, provably. Record it.
    * ref names the AGENT → the call ran the agent's live script, which is neither arm.
      Record nothing. For an inbound call to the client's DID this is the ordinary case
      (FLOWS §3: the number answers with the agent), and it is why an inbound-only
      experiment is still refused in `agents/experiments.py` — see its docstring.

    It runs for both directions on purpose. On outbound it repairs a real gap rather
    than duplicating `dispatch_call`: that function records only when its own INSERT
    wins, so an engine webhook that beat our commit and created the `calls` row first
    left an arm-dialled call carrying no arm at all. Both writers go through
    `assignment.record`, whose `ON CONFLICT (call_id) DO NOTHING` means the first fact
    written stands and no call can ever change arms.

    Same transaction as the `calls` row by construction — the caller's session.
    """
    if not engine_agent_ref:
        return
    arm = await assignment.arm_of_engine_ref(session, engine_agent_ref=engine_agent_ref)
    if arm is None:
        return
    await assignment.record(session, tenant_id=tenant_id, call_id=call_id, assignment=arm)


# --- job 2: the pipeline ------------------------------------------------------


def _post_call_target(payload: dict[str, Any]) -> tuple[UUID, UUID, str]:
    """The three ids this job runs on, or a PERMANENT failure.

    A malformed job payload is fixed for the life of the job: three parses of the same
    dict fail three identical times, thirty seconds and two minutes apart. Raising it as
    a `validation` ProblemError is how it says so — `_is_transient` reads the kind, so
    this needs no second retry policy of its own (the ingest job's split is the whole
    policy for both jobs).

    Ids only in the message, never the payload (hard rule 6): the job payload is ours,
    but "log the thing that broke" is exactly how a transcript ends up in a log line the
    day someone adds a field to it.
    """
    try:
        return (
            UUID(str(payload["tenant_id"])),
            UUID(str(payload["call_id"])),
            str(payload["execution_id"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="post_call_payload_invalid",
            title="Unusable post-call job payload",
            detail="The post-call job was enqueued without a usable tenant, call or execution id.",
        ) from exc


async def _abandon_post_call(
    *, exc: Exception, attempt: int, call_id: str, execution_id: str
) -> NoReturn:
    """Ask for a retry, or stop loudly. The pipeline's half of `_abandon_ingest`.

    **`arq.Retry`, not a bare `raise`** — arq 0.28 retries a job only for `Retry`,
    `RetryJob` or `CancelledError`; every other exception sets `finish=True` and the job
    leaves the queue after ONE attempt (`arq/worker.py::run_job`, the `else` branch at
    the end of its handler — read at 0.28.0, and `WorkerSettings.max_tries` says the same
    thing). Everything outside the recording copy raised plainly here, so `max_tries = 3`
    was decorative for this job: one database blip mid-pipeline dropped extraction, the
    lead upsert, metering and the hot-lead alert to manual replay, and the reconciliation
    poller could not pick it up either, because its probe asked only whether the call row
    was `completed`. `_pipeline_settled` now asks whether the ARTEFACTS are there, so a
    call this ladder gives up on is one the poller re-drives — the ladder is the fast
    recovery and the poller is the guarantee, rather than the ladder being the only one.

    The retry is safe to take because every stage is re-runnable and, specifically,
    because the two irreversible ones refuse a second write: `_meter` returns early when
    `usage_events` already holds a row for the call — under `lock_call_writes`, so that
    check is a claim rather than a hope — and `charge_for_call` dedupes on `ref = call_id`
    under the per-tenant credit lock. `pipeline_audit_test` proves that against a failure
    injected AFTER metering rather than asserting it.

    Terminal is LOUD. A permanent failure here is a call whose lead never arrives, and
    the 2-minute SLO means nobody is coming to look unless something says so.
    """
    if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_retry_after(attempt)) from exc
    alert(
        "WORKER_TERMINAL",
        "post_call_abandoned",
        detail=(
            f"{type(exc).__name__} after {attempt} attempt(s)"
            if _is_transient(exc)
            else f"{type(exc).__name__} is permanent, not retried"
        ),
        call_id=call_id,
        execution_id=execution_id,
    )
    raise exc


async def run_post_call_pipeline(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """The heavy half, behind the retry ladder `WorkerSettings.max_tries` promises.

    The stages live in `_post_call_stages`; this wrapper exists only to own the failure
    policy, so no stage has to remember one and none of them can quietly opt out.
    """
    # arq's number, never ours — the same reason `ingest_engine_event` reads it here.
    attempt = int(ctx.get("job_try", 1))
    # For the alert only, and only when the payload was too broken to parse. Ids.
    call_hint = str(payload.get("call_id") or "unknown")
    execution_hint = str(payload.get("execution_id") or "unknown")
    try:
        tenant_id, call_id, execution_id = _post_call_target(payload)
        return await _post_call_stages(tenant_id, call_id, execution_id)
    except Retry:
        # A stage that already chose its own ladder — `StorageUnavailableError` is an
        # `arq.Retry` subclass with its own defer. Re-deciding it here would overwrite
        # the delay it picked and hide which stage asked.
        raise
    except Exception as exc:
        await _abandon_post_call(
            exc=exc, attempt=attempt, call_id=call_hint, execution_id=execution_hint
        )


async def _copy_recording_once(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> str:
    """Pull the engine's audio into our bucket, ONCE per call however many times the
    pipeline runs. Returns what happened, for the stage span.

    **THE GUARD IS THE POINT, AND IT IS ABOUT RE-DRIVES, NOT ABOUT SAVING BANDWIDTH
    (D-148).**
    Every other stage is re-runnable by rewriting a row; this one is re-runnable by
    re-fetching several megabytes from a THIRD PARTY over the network, and a third party
    is the one participant that can refuse. `_pipeline_settled` re-drives a call whose
    EXTRACTION or USAGE is missing — the recording is not even in `_expected_artifacts`
    — and the re-drive starts here, at step 1, because the recording comes first. So a
    vendor link that has since expired (Bolna's are direct S3 links with no documented
    expiry, TRD §5) turned a repair for a missing lead into a `StorageUnavailableError`
    that failed the whole job, three times, every hour, forever: the artefact the poller
    came to repair was never reached, and the guarantee of record silently stopped
    guaranteeing that call. Skipping the copy we already hold is what unblocks it.

    `calls.recording_url` holds OUR object key and nothing else — this stage is its only
    writer and the retention sweep is its only clearer — so a non-null value is proof the
    bytes are ours already. A null after the retention sweep means the audio was
    deliberately destroyed; the poller's 30-minute listing window cannot reach a call that
    old, so this cannot resurrect one that a sweep took. That was equally true before,
    and remains the reason the guard is "have we copied it" rather than "does the engine
    still offer one".

    NO `lock_call_writes` HERE, and the omission is deliberate rather than forgotten.
    This is a check-then-write, which is the shape that lock exists for — but the damage
    that lock prevents is a SECOND, DIFFERENT side effect (a second append-only usage row,
    a second CRM delivery under a fresh id). Two overlapping runs that both miss the guard
    here PUT the same bytes to the same key and write the same value to the same column,
    because `storage.recording_key` is a pure function of (tenant, call) — the cost is one
    wasted fetch, not a duplicate artefact. Taking a per-call lock across a 120-second
    vendor download would be the more expensive mistake: it would serialize the pipeline
    behind the one stage a third party controls.

    Storage failures still raise, and must: a lost recording is unrecoverable and TRAI's
    90-day floor is our obligation, not the vendor's.
    """
    if not snapshot.recording_url:
        return "none_offered"
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :id AND tenant_id = :tid"),
                {"id": call_id, "tid": tenant_id},
            )
        ).scalar()
    if held:
        return "already_copied"
    try:
        key = await copy_recording(
            source_url=snapshot.recording_url, tenant_id=tenant_id, call_id=call_id
        )
    except StorageUnavailableError as exc:
        # Re-raise so ARQ retries (it is an `arq.Retry` subclass carrying its own defer).
        alert("WORKER_DELIVERY", "recording_copy_failed", detail=str(exc), call_id=str(call_id))
        raise
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET recording_url = :key, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"key": key, "id": call_id, "tid": tenant_id},
        )
    return "copied"


async def _archive_engine_document(
    tenant_id: UUID, call_id: UUID, execution_id: str, snapshot: ExecutionSnapshot
) -> str:
    """Keep the engine's OWN answer for this call. Returns what happened, for the span.

    **THE PRODUCER D-126 BUILT THE ERASURE ARM FOR.** `storage.archive_payload`,
    `calls.engine_payload_ref` and `retention._erase_engine_payloads` all shipped with
    nothing writing an object between them, so the erasure guarded a store that could not
    exist and TRD §5's "raw vendor payloads go to object storage refs, never into typed
    columns" described a bucket that was always empty. This is the write that makes the
    other three true.

    **WHAT CROSSES THE BOUNDARY IS BYTES** (hard rule 2). `snapshot.raw_document` is the
    vendor's document sealed by the adapter; this function stores it and cannot read a
    field out of it, which is the whole point of the type. The only vendor-derived thing
    named here is `snapshot.engine`, which is OUR name for the adapter.

    **THE WRITE ORDER IS `archive_payload`'s CONTRACT, not a preference.** The reference is
    committed FIRST and the object PUT second, because `_erase_engine_payloads` gates its
    prefix listing on a call carrying a reference: a reference with no object costs one
    wasted listing, while an object no reference names is a caller's number and transcript
    that no DPDP erasure has any reason to look for. The two transactions below are in that
    order for that reason, and swapping them re-opens D-126 one crash at a time.

    **RE-WRITTEN ON EVERY RE-DRIVE, deliberately, and this is where it differs from
    `_copy_recording_once`.** That stage guards because re-running it costs a multi-megabyte
    fetch from a third party who can refuse; this one costs a local PUT of bytes already in
    hand, and `payload_key` is a pure function of (tenant, call, engine, execution) so the
    re-write lands on the same key rather than accumulating objects. A "have we already
    archived it?" guard would buy that PUT back and cost something worth more: an archive
    lost to one storage blip would be recorded as done forever, since the reference is
    committed before the PUT that failed.

    Never raises. The archive is a debug artifact (`archive_payload` is best-effort by
    design), and failing a client's lead to save one would be the tail wagging the dog. A
    refused PUT is visible in the store's own warning and in this stage's `outcome`.
    """
    if snapshot.raw_document is None:
        # An adapter that carried no document. Conformant only for a listing row, so on
        # this path it is worth an outcome an operator can see rather than a silent skip.
        return "none_offered"
    key = payload_key(
        tenant_id=tenant_id, call_id=call_id, engine=snapshot.engine, execution_id=execution_id
    )
    async with tenant_session(tenant_id) as session:
        recorded = rowcount_of(
            await session.execute(
                text(
                    "UPDATE calls SET engine_payload_ref = :key, updated_at = now() "
                    "WHERE id = :id AND tenant_id = :tid"
                ),
                {"key": key, "id": call_id, "tid": tenant_id},
            )
        )
    if not recorded:
        # NO ROW TOOK THE REFERENCE — the call is gone, or RLS put it out of this tenant's
        # reach. Either way the index the erasure walks by does not exist, so PUTting now
        # would create precisely the object D-126 exists to make impossible: a caller's
        # number and transcript under a prefix no `calls` row will ever point at. The
        # ordering contract is only a contract if the second half is CONDITIONAL on the
        # first half having landed.
        log.warning(
            "engine_document_archive_unreferenced",
            extra={"call_id": str(call_id), "engine": snapshot.engine},
        )
        return "call_row_absent"
    stored = await archive_payload(
        tenant_id=tenant_id,
        call_id=call_id,
        engine=snapshot.engine,
        execution_id=execution_id,
        document=snapshot.raw_document,
    )
    return "archived" if stored is not None else "put_refused"


async def _post_call_stages(tenant_id: UUID, call_id: UUID, execution_id: str) -> str:
    started = time.perf_counter()

    snapshot = await get_engine().get_execution(execution_id)

    # STEP 1 — recording first, always. Everything else can be recomputed.
    with span("pipeline.recording_copy", call_id=str(call_id)) as stage:
        set_span_attributes(stage, outcome=await _copy_recording_once(tenant_id, call_id, snapshot))

    # STEP 1b — the vendor's own document, archived under this call's prefix (D-126).
    # After the recording because the recording is the artefact a third party can take
    # away from us; this one is bytes we already hold.
    with span("pipeline.engine_document_archive", call_id=str(call_id)) as stage:
        set_span_attributes(
            stage,
            outcome=await _archive_engine_document(tenant_id, call_id, execution_id, snapshot),
        )

    # STEP 2 — transcript + redaction. `text_redacted` is the default view (hard rule 5).
    with span("pipeline.transcript_persist", call_id=str(call_id)) as stage:
        transcript_text = await _persist_transcript(tenant_id, call_id, snapshot)
        set_span_attributes(stage, turn_count=len(snapshot.transcript or []))

    # STEP 2b — an opt-out the caller spoke becomes a suppression, BEFORE extraction.
    #
    # Order is the point: extraction is a model round trip with a 30-second timeout and
    # an ARQ retry behind it, and hard rule 5's deadline ("before the next dispatch
    # tick") is 30 seconds. Suppressing after the slowest stage in the pipeline would
    # spend the entire budget on a step this one does not need.
    #
    # This is the BRACES. The belt is the in-call tool (voice-runtime `/tools/v1/opt-out`
    # → `workers.optout.record_in_call_optout`), which fires while the caller is still on
    # the line; this pass runs on every completed call whether or not the model invoked
    # it. `compliance/optout.py` argues why both exist and what each one misses.
    opt_out_signal = detect_opt_out(snapshot.transcript) if snapshot.transcript else None
    with span("pipeline.opt_out", call_id=str(call_id)) as stage:
        outcome = await _maybe_record_opt_out(tenant_id, call_id, snapshot, opt_out_signal)
        set_span_attributes(stage, outcome=outcome)

    # STEP 3 — extraction against the agent's schema.
    spec, schema_version, agent_id, direction = await _load_call_context(tenant_id, call_id)
    needs_extraction = bool(spec.fields or transcript_text)
    # THE SPAN THIS WHOLE EXERCISE IS FOR. A model round trip lives in here, and it is
    # the stage most likely to own the missing minutes — a 30s extraction timeout
    # (EXTRACTION_TIMEOUT_S) plus an ARQ retry is a lead that arrives late with nothing
    # in the logs to say why. `input_bytes` is the transcript's SIZE, never its text.
    with span(
        "pipeline.extract",
        call_id=str(call_id),
        field_count=len(spec.fields),
        input_bytes=len(transcript_text.encode("utf-8", "replace")),
    ) as stage:
        extraction = await extract_call(spec, transcript_text) if needs_extraction else None
        set_span_attributes(
            stage,
            extract_status=(
                "skipped" if extraction is None else ("valid" if extraction.valid else "invalid")
            ),
        )

    if extraction is not None:
        # STEP 3b — the key moments a client jumps to instead of replaying the call
        # (D-156). No model call and no round trip: every input is already in hand here,
        # so this is a string match over turns we have just persisted. It runs INSIDE the
        # persist span rather than its own because it is arithmetic — a span per
        # microsecond of Python is noise in a trace whose point is finding the missing
        # minutes.
        #
        # The model half (`merge_moments`'s second argument) is empty until the extractor
        # returns highlights; the merge is called anyway so the write path is the same one
        # that will carry them, rather than a branch nobody has run.
        moments = merge_moments(
            derive_moments(
                turns=snapshot.transcript,
                extraction=extraction.data,
                field_labels={field.key: field.label for field in spec.fields},
                opt_out_turn_idx=opt_out_signal.turn_idx if opt_out_signal else None,
            ),
            [],
        )
        with span(
            "pipeline.extraction_persist",
            call_id=str(call_id),
            field_count=len(extraction.data),
            moment_count=len(moments),
        ):
            await _persist_extraction(
                tenant_id,
                call_id,
                extraction,
                schema_version=schema_version,
                moments=moments,
            )

    # STEP 4 — lead upsert (+ repeat-caller flag on phone match).
    with span("pipeline.lead_upsert", call_id=str(call_id), agent_id=str(agent_id)) as stage:
        lead_id = await _upsert_lead(
            tenant_id,
            agent_id,
            call_id,
            snapshot,
            direction=direction,
            data=extraction.data if extraction else {},
            schema_version=schema_version,
        )
        set_span_attributes(stage, lead_id=str(lead_id) if lead_id else "none")

    # STEP 5 — metering. Append-only, written once per (call, unit).
    if snapshot.cost is not None:
        with span("pipeline.meter", call_id=str(call_id)) as stage:
            set_span_attributes(stage, usage_row_count=await _meter(tenant_id, call_id, snapshot))

    # STEP 6 — notifications, through the OUTBOX so a crash cannot lose them.
    if lead_id is not None and extraction is not None:
        with span("pipeline.notify_hot_lead", call_id=str(call_id), lead_id=str(lead_id)) as stage:
            outcome = await _maybe_notify_hot_lead(tenant_id, lead_id, call_id, extraction.data)
            set_span_attributes(stage, outcome=outcome)

    # STEP 7 — if this call was a campaign dial, the outcome closes the contact or puts
    # it back on the retry ladder (FLOWS §5). Local import: the dispatcher is a worker
    # peer, and a module-level import would drag it into every pipeline run.
    from apps.workers.campaign_dispatch import resolve_campaign_contact

    async with tenant_session(tenant_id) as session:
        # Step 8's `_already_enqueued` is a check-then-write and the delivery id it would
        # duplicate is minted FRESH per fan-out — so two overlapping runs do not send the
        # client a retry they can deduplicate, they send them the same lead twice under
        # two different ids. Taken before the campaign resolution so the whole
        # transaction is one serialized unit rather than two.
        await lock_call_writes(session, call_id)
        await resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=call_id, call_status=snapshot.status
        )

        # STEP 8 — outbound CRM sync (D-23). Last, and only for a call that actually
        # completed: an outcome the client's CRM can act on is one where the summary and
        # extraction above already exist. Enqueued in this transaction, delivered by the
        # outbox — the same guarantee the notification in step 6 gets.
        #
        # Once per call, not once per pipeline run: the delivery id is minted fresh on
        # each fan-out, so a receiver deduplicating on it cannot collapse two runs of
        # the same call — the client would simply be told twice.
        if snapshot.status == "completed" and not await _already_enqueued(
            session,
            job="deliver_outbound_webhook",
            matcher={"event": "call.completed", "data": {"call_id": str(call_id)}},
        ):
            await integrations.enqueue_event(
                session,
                tenant_id=tenant_id,
                event="call.completed",
                data={
                    "call_id": str(call_id),
                    "lead_id": str(lead_id) if lead_id else None,
                    "direction": direction,
                    "duration_s": snapshot.duration_s,
                    "outcome": extraction.outcome_tag if extraction else None,
                    "sentiment": extraction.sentiment if extraction else None,
                    # The SUMMARY, never the transcript: a transcript is the most
                    # sensitive artefact we hold, and it does not leave on a webhook.
                    # Redacted on the way out, because the summary is DERIVED from the
                    # transcript and the offline extractor's is a transcript line
                    # verbatim — SEC-COMP §4 puts redaction before anything leaves, and
                    # the notification path already does this (`notifications._compose`).
                    "summary": redact(extraction.summary).text if extraction else None,
                },
            )

    lag = time.perf_counter() - started
    record_pipeline_lag(lag, stage="post_call")
    # The SAME number, on the trace. `record_pipeline_lag` is the SLO metric — it fires
    # on 100% of calls and it is what says the 2-minute budget was missed; the trace is
    # sampled at 10% and it is what says where the time went. Without this attribute
    # they are two systems with no join: an operator holding a breached metric has no
    # way to ask the trace backend for the traces belonging to breaches. Written on the
    # `traced_job` span rather than a child, because it measures the whole job.
    set_span_attributes(_job_span(), pipeline_lag_ms=round(lag * 1000, 1), call_id=str(call_id))
    log.info("pipeline_complete", extra={"call_id": str(call_id), "duration_s": round(lag, 2)})
    return "ok"


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def lock_call_writes(session: AsyncSession, call_id: UUID) -> None:
    """Serialize this CALL's non-idempotent post-call writes for the rest of the
    transaction. Take it BEFORE the read that decides whether to write.

    THE SHAPE IT GUARDS. Three places in this pipeline decide "have we already done this
    for this call?" and then act on the answer — `_meter` (the append-only usage ledger),
    `_maybe_notify_hot_lead` and step 8's CRM fan-out (both through `_already_enqueued`).
    Every one of them is a read-then-write, which under two overlapping runs of the same
    call means both read "not yet" and both write. The damage is not symmetric with the
    idempotent stages around them: `usage_events` carries an append-only trigger, so a
    double meter is a double charge that only a hand-written compensating entry can
    answer, and a second outbox row is a second CRM delivery with a FRESH delivery id —
    which is the one thing the client's own receiver cannot deduplicate.

    Measured rather than assumed: two concurrent `_meter` calls for one call wrote ten
    usage rows for a five-row call and counted its minutes into `spend_state` twice
    (`tests/postcall_concurrency_test.py`, which removes this lock to show the test can
    still see it).

    ONE KEY FOR THE CALL, not one per stage. Two runs of one call must serialize as a
    unit — separate keys would let run A finish metering and run B start notifying while
    A is still deciding — and one key also means there is no ordering to get wrong
    between them. `charge_for_call`'s `credit:{tenant_id}` is always taken AFTER this
    one and by nothing that holds it first, so there is no cycle.

    `pg_advisory_xact_lock` is the house primitive for a read-then-write
    (`billing.lock_tenant_credits`, `compliance.audit`, `ops.secret_service`,
    `ops.config_service`), released by COMMIT or ROLLBACK, with no lease to tune
    (postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS).
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"call:{call_id}"},
    )


async def _already_enqueued(session: AsyncSession, *, job: str, matcher: dict[str, Any]) -> bool:
    """Has this exact side effect already been promised for this call?

    The outbox is the durable record of what we said we would send, and rows are never
    deleted — status only moves (`mark_outbox_published`). So it is also the right place
    to ask "did a previous run of this pipeline already queue this?", which is what
    keeps a replay from telling a client twice.

    MUST be asked under `lock_call_writes` — see there. It is a check-then-write, and
    the ARQ job id that used to be its only defence is a Redis convention with a finite
    window rather than a database fact.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM outbox_messages WHERE job = :job "
                "AND payload @> CAST(:matcher AS jsonb) LIMIT 1"
            ),
            {"job": job, "matcher": _json(matcher)},
        )
    ).first()
    return row is not None


async def _persist_transcript(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> str:
    """Store raw + redacted turns. Idempotent on (call_id, idx) so a re-run rewrites
    rather than duplicates."""
    if not snapshot.transcript:
        return ""
    lines: list[str] = []
    async with tenant_session(tenant_id) as session:
        for turn in snapshot.transcript:
            redacted = redact(turn.text)
            lines.append(f"{turn.speaker}: {turn.text}")
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, lang, start_ms, end_ms, created_at, updated_at) VALUES "
                    "(:id, :tid, :cid, :idx, :speaker, :text, :redacted, :lang, :start, :end, "
                    "now(), now()) ON CONFLICT (call_id, idx) DO UPDATE SET "
                    "text = EXCLUDED.text, text_redacted = EXCLUDED.text_redacted, "
                    "updated_at = now()"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": turn.idx,
                    "speaker": turn.speaker,
                    "text": turn.text,
                    "redacted": redacted.text,
                    "lang": turn.lang,
                    "start": turn.start_ms,
                    "end": turn.end_ms,
                },
            )
    return "\n".join(lines)


async def _maybe_record_opt_out(
    tenant_id: UUID,
    call_id: UUID,
    snapshot: ExecutionSnapshot,
    signal: OptOutSignal | None,
) -> str:
    """ "Don't call me again", said on this call, becomes a `dnc_list` row.

    Returns what happened, for the stage span: `none` (nobody asked), `recorded`, or
    `already` (a previous run of this pipeline, or the in-call tool, got there first) —
    the three answers an operator asking "why was this number not suppressed" needs to
    tell apart, and they are indistinguishable from the outside.

    THE PHONE IS THE OTHER PARTY, on the same rule `_upsert_lead` uses: the caller on
    inbound, the recipient on outbound. Suppressing the wrong end would put OUR OWN
    number on a tenant's do-not-call list and stop every outbound call they place.

    `signal` is DETECTED BY THE CALLER, not here, because the same detection answers a
    second question — which turn to put a "caller asked not to be called again" marker on
    (D-156). Two `detect_opt_out` calls over one transcript could not disagree today, but
    the suppression and the marker would then be free to drift apart on the day the
    detector grows a parameter, and a marker pointing at a turn no suppression was made
    for is worse than no marker.
    """
    if signal is None:
        return "none"
    subject = snapshot.from_e164 if snapshot.direction == "inbound" else snapshot.to_e164
    if not subject:
        # A completed call whose other end we cannot key. Loud, because the caller DID
        # ask and this is the one failure on this path that leaves them dialable.
        alert(
            "WORKER_TERMINAL",
            "opt_out_unattributable",
            detail=f"direction={snapshot.direction}",
            call_id=str(call_id),
        )
        return "unattributable"
    async with tenant_session(tenant_id) as session:
        record = await record_call_optout(
            session,
            tenant_id=tenant_id,
            raw_phone=subject,
            call_id=call_id,
            detected_by=DETECTED_POST_CALL,
            signal=signal,
        )
    return "recorded" if record.evidence_written else "already"


async def _persist_extraction(
    tenant_id: UUID,
    call_id: UUID,
    extraction: ExtractionOutput,
    *,
    schema_version: int,
    moments: list[dict[str, Any]] | None = None,
) -> None:
    """One call has ONE extraction, however many times the pipeline runs.

    A re-run is normal here — a webhook that arrives after the poller already resolved
    the call re-enters the pipeline (D-31) — so this is an upsert rather than the plain
    INSERT it used to be, which filed a second extraction per replay and left the CRM
    with two answers and no way to say which one it read.

    It is a single `ON CONFLICT (tenant_id, call_id) DO UPDATE`, which closes the RACE
    as well as the replay: migration `d3b71c9a5e08` made that pair unique, so two
    pipeline runs on one call — an ARQ retry overlapping the reconciliation poller — can
    no longer both read "no row" and both insert. The read-modify-write this replaces
    depended on the ARQ job id (keyed on the call) to serialize them, which is a Redis
    convention rather than a database fact.

    `moments` rides the same row and the same upsert (D-156). It is DERIVED from this
    extraction and the transcript, so a re-run recomputes it and the upsert replaces it —
    exactly the behaviour `data` needs, for the same reason. Passing None writes NULL,
    which is "nobody has looked at this call" and is distinct from `[]`, "we looked and it
    had none": every row written before the column existed is the former, and a caller
    that cannot compute markers must not claim it found none.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "model, valid, errors, moments, created_at, updated_at) VALUES "
                "(:id, :tid, :cid, :ver, CAST(:data AS jsonb), :model, :valid, "
                "CAST(:errors AS jsonb), CAST(:moments AS jsonb), now(), now()) "
                "ON CONFLICT (tenant_id, call_id) DO UPDATE SET "
                "  schema_version = EXCLUDED.schema_version, "
                "  data = EXCLUDED.data, "
                "  valid = EXCLUDED.valid, "
                "  errors = EXCLUDED.errors, "
                "  moments = EXCLUDED.moments, "
                "  updated_at = now()"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": call_id,
                "ver": schema_version,
                "data": _json(extraction.data),
                "model": None,
                "valid": extraction.valid,
                "errors": _json(extraction.errors) if extraction.errors else None,
                "moments": _json(moments) if moments is not None else None,
            },
        )
        await session.execute(
            text(
                "UPDATE calls SET summary = :summary, sentiment = :sentiment, "
                "outcome_tag = :outcome, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {
                "summary": extraction.summary or None,
                "sentiment": extraction.sentiment,
                "outcome": extraction.outcome_tag,
                "id": call_id,
                "tid": tenant_id,
            },
        )


async def _load_call_context(
    tenant_id: UUID, call_id: UUID
) -> tuple[ExtractionSchemaSpec, int, UUID, str]:
    """The call's agent, its direction, and the schema ACTIVE AT EXTRACTION TIME.

    Direction comes from the stored call row rather than being re-derived: it decides
    which number belongs to the lead, and getting it wrong would file an outbound call
    under our own caller id.

    Leads render by the schema version stored on the row, so a later schema edit never
    rewrites an old lead (TRD §7).
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.agent_id, c.direction, es.version, es.fields FROM calls c "
                    "JOIN agents a ON a.id = c.agent_id "
                    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE c.id = :cid AND c.tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
    if row is None:
        raise RuntimeError(f"call {call_id} not found for schema load")
    agent_id, direction, version, fields = row[0], str(row[1]), row[2], row[3]
    if not fields:
        empty = ExtractionSchemaSpec(version=version or 1, fields=[])
        return empty, version or 1, agent_id, direction
    spec = ExtractionSchemaSpec.model_validate({"version": version or 1, "fields": fields})
    return spec, spec.version, agent_id, direction


async def _upsert_lead(
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    snapshot: ExecutionSnapshot,
    *,
    direction: str,
    data: dict[str, Any],
    schema_version: int,
) -> UUID | None:
    """One lead per (tenant, phone, agent). A second call from the same number updates
    the lead and flips `is_repeat_caller` — that flag is what makes the repeat-caller
    context injection (FLOWS §3) possible later.

    THE LEAD'S PHONE IS THE OTHER PARTY: the caller on inbound, the recipient on
    outbound. Keying on the wrong end would file every outbound call under our own
    number and collapse a tenant's whole CRM into one lead.

    A RE-RUN IS NOT A SECOND CALL. `call_count` and `is_repeat_caller` move only when
    the call id on the row actually changes, and the timeline event is written once per
    call: the pipeline is re-runnable by design (TRD §8), and a replay that invented a
    returning customer would put the repeat-caller context injection (FLOWS §3) in front
    of a first-time caller.
    """
    caller = snapshot.from_e164 if direction == "inbound" else snapshot.to_e164
    if not caller:
        return None
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, schema_version, first_call_id, last_call_id, call_count, "
                    "is_repeat_caller, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                    ":name, :source, 'new', CAST(:data AS jsonb), :ver, :cid, :cid, 1, false, "
                    "now(), now()) "
                    "ON CONFLICT (tenant_id, phone_e164, agent_id) DO UPDATE SET "
                    "  data = leads.data || EXCLUDED.data, "
                    "  schema_version = EXCLUDED.schema_version, "
                    "  name = COALESCE(EXCLUDED.name, leads.name), "
                    "  last_call_id = EXCLUDED.last_call_id, "
                    "  call_count = leads.call_count + "
                    "    (leads.last_call_id IS DISTINCT FROM EXCLUDED.last_call_id)::int, "
                    "  is_repeat_caller = leads.is_repeat_caller OR (leads.call_count > 0 "
                    "    AND leads.last_call_id IS DISTINCT FROM EXCLUDED.last_call_id), "
                    "  updated_at = now() "
                    "RETURNING id"
                ),
                {
                    "id": lead_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "phone": caller,
                    "name": data.get("name") or data.get("caller_name"),
                    "source": "inbound_call" if direction == "inbound" else "campaign",
                    "data": _json(data),
                    "ver": schema_version,
                    "cid": call_id,
                },
            )
        ).first()
        resolved_id = UUID(str(row[0])) if row else None
        if resolved_id is not None:
            await session.execute(
                text(
                    "UPDATE calls SET lead_id = :lid, updated_at = now() "
                    "WHERE id = :cid AND tenant_id = :tid"
                ),
                {"lid": resolved_id, "cid": call_id, "tid": tenant_id},
            )
            await session.execute(
                text(
                    "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                    "created_at, updated_at) SELECT :id, :tid, :lid, 'call', "
                    "CAST(:payload AS jsonb), 'system', now(), now() "
                    "WHERE NOT EXISTS (SELECT 1 FROM lead_events WHERE lead_id = :lid "
                    "AND type = 'call' AND payload->>'call_id' = :cid)"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "lid": resolved_id,
                    "cid": str(call_id),
                    "payload": _json({"call_id": str(call_id), "status": snapshot.status}),
                },
            )
    return resolved_id


def _unit_price(leg_inr: Decimal | None, qty: Decimal) -> Decimal | None:
    """A leg's cost expressed per unit of `qty` — NUMERIC throughout (hard rule 7).

    `qty == 0` (a completed call the engine reports as zero-length) would make the
    division undefined, so the leg cost is kept whole on the row.

    **WHAT THAT DOES AND DOES NOT BUY, because this line used to claim more than it
    delivers.** It said "the money never silently disappears from the ledger", and the
    value is indeed on the row — but every READER of this column multiplies it by `qty`
    (`billing.margin_for_tenant`, `_tier_totals`, the invoice lines), so at `qty == 0` the
    leg contributes nothing to any of them. Measured on a zero-duration call charged
    ₹1.0000: the three duration-priced legs vanish and `SUM(qty * unit_cost_paid)`
    reconstructs ₹0.20, while `spend_state.spend_used` — which takes `cost.total_inr`
    directly, not the rows — records the full ₹1.0000. `billing.service._spend_used` has
    always described this correctly ("a zero-duration call reads a few paise lighter");
    this docstring contradicted it, which is the one thing two accounts of the same money
    must never do. `pipeline_partial_failure_test` now pins the arithmetic so the gap is a
    measured, cited number rather than either claim.

    It is not closable from the WRITE side: the ledger's shape is `qty * unit`, and a
    zero-length call has a real leg cost and genuinely zero seconds. Writing `qty = 1`
    would bill the client a second that never happened — `usage_summary` reads minutes off
    `telephony_s.qty` — which is the worse of the two errors. The closable half is a
    reader that treats a zero-qty row as a whole-leg row, and that lives in
    `apps/api/billing`.

    THE QUANTUM AND THE MODE ARE IMPORTED, not spelled here, and that is the fix rather
    than the tidying it looks like. This line was `quantize(Decimal("0.0001"))` with no
    mode, so it took the ambient `decimal` context — ROUND_HALF_EVEN by default, and
    mutable process-wide by any library in the image. It is the WRITE path for
    `unit_cost_paid`, so it was the one money rounding in the tree that did not follow the
    doctrine `billing.service.to_paise` states in full ("passed EXPLICITLY, never
    inherited"). Reachable, not theoretical: a ₹0.0180 telephony leg over a 360-second
    call is exactly ₹0.00005/second, which half-even stored as ₹0.0000 — the whole leg
    rounded out of the margin panel and out of a closed month's `spend_used`.
    """
    if leg_inr is None:
        return None
    if qty <= 0:
        return leg_inr
    return (leg_inr / qty).quantize(MONEY_Q, rounding=ROUNDING)


def _ist_month(moment: datetime) -> str:
    """The IST billing month a UTC instant belongs to (billing `_IST_MONTH`)."""
    return (moment + timedelta(hours=5, minutes=30)).strftime("%Y-%m")


# --- the spend cap ------------------------------------------------------------
#
# `spend_state.capped` is the ONLY cap anything enforces: `compliance.check_dispatch`
# reads that boolean and refuses every outbound call while it is true. Until this
# statement set it, `plans.hard_cap_min` and `plans.hard_cap_spend` were reported by the
# usage panel and the admin console and enforced by NOTHING — a runaway campaign would
# have burned straight through both ceilings.
#
# The flag is computed in the SAME statement that accumulates the counters, from the
# totals that statement is storing. A separate read-then-write would let two calls
# finishing at once each see a pre-cap total and neither arm the cap.
#
# KNOWN RESIDUAL, and it is not fixable from here: this statement moves the flag only
# when a call is METERED. A tenant whose traffic is entirely outbound is capped in July,
# refused every dial in August, meters nothing, and therefore never rolls over — the
# rollover below only fires if some call completes. Inbound saves most tenants (the gate
# is outbound-only, so inbound still meters), but a campaign-only client would be stuck.
# The durable fix is a month-aware READ in `compliance.spend_capped` — `capped AND
# month = billing.current_billing_month()` — so a stale month stops being a cap on its
# own; that read exists.
#
# THIS IS NO LONGER THE ONLY WRITER. `billing/caps.py::apply_client_caps` also writes
# the flag, because a client lowering their own cap has to stop the next dial rather
# than the dial after the next call happens to meter. It writes ONLY the flag, only for
# the current billing month, and from the counters this statement maintains — and both
# read one shared definition of "over cap" (`billing.caps.over_cap_sql`) rather than
# each carrying a copy, which is what stops the two from ever disagreeing.
#
# WHOSE CEILING. `caps` now resolves the EFFECTIVE cap — `LEAST(hard_cap_*,
# client_cap_*)` — so the ceiling the admin agreed and the one the client set for
# themselves both bind, and the stricter wins. The CTE body is imported, not restated,
# for the same reason.

# The accumulated totals — reset on a new IST billing month, added to within one.
_ACC_MINUTES = (
    "CASE WHEN spend_state.month = EXCLUDED.month "
    "THEN spend_state.minutes_used + EXCLUDED.minutes_used "
    "ELSE EXCLUDED.minutes_used END"
)
_ACC_SPEND = (
    "CASE WHEN spend_state.month = EXCLUDED.month "
    "THEN spend_state.spend_used + EXCLUDED.spend_used "
    "ELSE EXCLUDED.spend_used END"
)


_SPEND_STATE_UPSERT = f"""
WITH caps AS ({CAPS_CTE})
INSERT INTO spend_state (
    tenant_id, month, minutes_used, spend_used, capped, created_at, updated_at
)
SELECT
    CAST(:tid AS uuid), CAST(:month AS text),
    CAST(:minutes AS numeric), CAST(:spend AS numeric),
    {over_cap_sql("CAST(:minutes AS numeric)", "CAST(:spend AS numeric)")},
    now(), now()
ON CONFLICT (tenant_id) DO UPDATE SET
    minutes_used = {_ACC_MINUTES},
    spend_used = {_ACC_SPEND},
    -- Recomputed, never carried: on a month rollover the counters above reset, and a
    -- flag left at its old value is a tenant capped in July who can never dial in
    -- August — the counters would read one minute used and the gate would still refuse.
    capped = {over_cap_sql(_ACC_MINUTES, _ACC_SPEND)},
    month = EXCLUDED.month,
    updated_at = now()
"""


async def _meter(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> int:
    """Write the cost ledger. Append-only (hard rule 4), so the guard against a
    double-run is a pre-check, not an upsert: a compensating entry is the only fix
    after the fact.

    Returns how many `usage_events` rows it wrote — 0 on the re-run path. That number
    is the trace's evidence that a replay metered nothing, which is the property hard
    rule 4 exists to protect and the one a double-bill would violate silently.

    **THE PRE-CHECK IS UNDER `lock_call_writes`, AND IT HAS TO BE.** A read-then-write
    over money is the exact shape CLAUDE.md's concurrency rule names, and this one was
    unguarded: two overlapping runs of the post-call pipeline for one call both read "not
    metered yet" and both append. Measured, not argued — ten usage rows for a five-row
    call, and its minutes counted into `spend_state` twice, so the client is billed twice
    AND their spend cap is armed at half the real usage. `usage_events` carries an
    append-only trigger, so neither is fixable by an UPDATE.

    WHY IT WAS THOUGHT SAFE, and why that was not enough: the ARQ job id is keyed on the
    call, so two post-call jobs collapse into one while arq holds the dedupe. That is a
    real defence and it is the FIRST one, not the last — its window is `keep_result`
    (3600s), a cancelled `job_timeout = 300` job can still have a transaction in flight
    when its retry starts, and an operator replay or a lost Redis takes the dedupe away
    entirely. A Redis convention must not be the only thing standing between an
    append-only ledger and a double charge.

    AND THERE IS NOW A UNIQUE INDEX BEHIND THE LOCK. This docstring used to end "the
    index remains the better end state and is named in the report"; migration
    `b8d3f47c2a19` built it — `ux_usage_events_tenant_call_unit` on `(tenant_id, call_id,
    unit_type)`, partial on the five unit types written below. The lock is still the
    mechanism and the index is the backstop, and the division of labour is exact: under
    the lock the second run reads the first run's rows and returns 0 before inserting
    anything, so the index is never reached; with the lock forgotten the second inserter
    is REFUSED rather than allowed to double-charge, and because everything here shares
    one transaction the abort takes the whole second metering with it. That is why no
    `ON CONFLICT` appears at the insert site — `DO UPDATE` would fire the append-only
    trigger and `DO NOTHING` would convert the conflict into silence, which on this table
    is worse than an abort. The migration argues both at length.
    """
    cost = snapshot.cost
    if cost is None:
        return 0
    async with tenant_session(tenant_id) as session:
        await lock_call_writes(session, call_id)
        tier = await plan_tier_of(session, tenant_id)
        voice_id = (
            await session.execute(
                # LEFT JOIN: a call whose agent row was since removed still has to
                # meter — and it meters as UNPROVEN, which bills at the value rate.
                text(
                    "SELECT a.tts_voice FROM calls c "
                    "LEFT JOIN agents a ON a.id = c.agent_id AND a.tenant_id = c.tenant_id "
                    "WHERE c.id = :cid AND c.tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).scalar()
        # WHICH VOICE ACTUALLY RAN IS NOT SOMETHING WE MEASURE. The engine reports a
        # synthesizer leg cost and no model name (billing/rates.py explains the vendor
        # question), so this is the voice the agent was CONFIGURED with at metering
        # time — an assumption, stamped with its provenance so no later reader can
        # mistake it for a measurement. An unrecognised or absent voice resolves to the
        # VALUE tier: SURFACES §2b's rule is that an unproven call is never billed at
        # the premium rate.
        tts_tier, tts_tier_source = billable_tier(voice_id if isinstance(voice_id, str) else None)
        already = (
            await session.execute(
                text(
                    "SELECT 1 FROM usage_events WHERE call_id = :cid AND tenant_id = :tid LIMIT 1"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
        if already:
            return 0

        duration_s = Decimal(snapshot.duration_s or 0)
        meta = _json(
            {
                "engine": snapshot.engine,
                "engine_call_id": snapshot.engine_call_id,
                "source_currency": cost.source_currency,
                "source_amount": str(cost.source_amount) if cost.source_amount else None,
                # The fx rate used AT CAPTURE — without it the row cannot be re-derived.
                "fx_rate": str(cost.fx_rate) if cost.fx_rate else None,
                # D-36's TTS ladder, recorded per row so metering can be audited by
                # rung and a mis-tiered call can be compensated (never edited — hard
                # rule 4). `tts_tier_source` is the honesty: `agent_config` means we
                # read the agent's configured voice, NOT that the engine told us.
                "tts_tier": tts_tier,
                "tts_tier_source": tts_tier_source,
                "tts_voice": voice_id if isinstance(voice_id, str) else None,
            }
        )
        # `unit_cost_paid` is a PRICE PER UNIT OF `qty`, because that is what every
        # reader does with it: `margin_for_tenant` sums `qty * unit_cost_paid`, and
        # `usage_summary` bills minutes off `telephony_s.qty`. Writing the leg TOTAL in
        # that column reported ~50x our real cost for a 95-second call and — with the
        # tts/llm rows carrying qty 0 — dropped those legs from the cost side entirely.
        minutes = duration_s / Decimal(60)
        rows: list[tuple[str, Decimal, Decimal | None]] = [
            ("telephony_s", duration_s, _unit_price(cost.network_inr, duration_s)),
            ("platform_min", minutes, _unit_price(cost.platform_inr, minutes)),
            ("stt_s", duration_s, _unit_price(cost.stt_inr, duration_s)),
        ]
        # The engine bills TTS and LLM as leg costs with no character or token count
        # (TRD §5), so there is no quantity to price against. One unit priced at what
        # the leg actually cost keeps the money in the ledger; when the engine exposes
        # counts, qty becomes the count and the price divides by it like the rows above.
        if cost.tts_inr is not None:
            rows.append(("tts_chars", Decimal(1), cost.tts_inr))
        if cost.llm_inr is not None:
            rows.append(("llm_tok_out", Decimal(1), cost.llm_inr))

        for unit_type, qty, unit_cost in rows:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:id, :tid, :cid, "
                    ":unit, :qty, :cost, :at, CAST(:meta AS jsonb), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "unit": unit_type,
                    "qty": qty,
                    "cost": unit_cost,
                    "at": snapshot.ended_at or datetime.now(UTC),
                    "meta": meta,
                },
            )

        # Prepaid credits move with the metering, keyed by call_id so a pipeline
        # re-run cannot double-charge (D-39). Managed tenants are invoiced against a
        # retainer instead, which `charge_for_call` reads from plan_tier.
        if tier in ("self_serve", "trial"):
            await charge_for_call(
                session, tenant_id=tenant_id, call_id=call_id, amount_inr=cost.total_inr
            )

        # spend_state is the pre-dispatch gate (TRD §9): caps are enforced BEFORE a
        # call is placed, so this counter has to move with the ledger.
        #
        # The month is the IST billing month, the same one the invoice and the usage
        # panel use (billing `_IST_MONTH`). A UTC month boundary rolls over at 05:30
        # IST, so every call between midnight and 05:30 on the 1st would be counted
        # against the closed month — the counter and the invoice would disagree, and a
        # tenant capped in the old month would stay capped into the new one.
        #
        # THE LOCK IS NOT OPTIONAL AND THE ROW LOCK IS NOT A SUBSTITUTE. This statement
        # reads the tenant's ceiling out of `plans` (through `caps.CAPS_CTE`) and writes
        # `spend_state`. Under READ COMMITTED an updating command sees concurrent effects
        # on the rows it is UPDATING but not on other rows, so without this it blocks on
        # the `spend_state` row, unblocks with the new counters and the OLD ceiling, and
        # overwrites the `capped` a client's own stop button had just armed — their
        # outbound calling resumes mid-runaway-campaign. `billing/caps.py::
        # lock_tenant_spend_state` carries the full argument and the reproduction lives
        # in `tests/money_walk_test.py`. Taken AFTER `charge_for_call`'s `credit:` lock,
        # which is the only order anything takes the two in.
        await lock_tenant_spend_state(session, tenant_id)
        month = _ist_month(snapshot.ended_at or datetime.now(UTC))
        await session.execute(
            text(_SPEND_STATE_UPSERT),
            {
                "tid": tenant_id,
                "month": month,
                "minutes": duration_s / Decimal(60),
                "spend": cost.total_inr,
            },
        )
    return len(rows)


async def _maybe_notify_hot_lead(
    tenant_id: UUID, lead_id: UUID, call_id: UUID, data: dict[str, Any]
) -> str:
    """Hot-lead rules key off the FIXED status enum and the schema's own fields (D-21).
    The notification goes through the outbox so a worker crash cannot lose it — and is
    queued once per call, so a pipeline replay does not promise a second alert for an
    alert that was already sent.

    Returns which of the three things happened, for the stage span's `outcome`: an
    owner asking "why did I not get the alert" is asking to tell `not_hot` apart from
    `already_queued`, and those are indistinguishable from the outside.
    """
    triggered = [
        key
        for key, values in HOT_LEAD_FIELD_TRIGGERS.items()
        if str(data.get(key, "")).lower() in values
    ]
    if not triggered:
        return "not_hot"
    async with tenant_session(tenant_id) as session:
        # Before the `_already_enqueued` read below, not after it: two overlapping runs
        # of one call would otherwise both see no promise and both queue the alert, and
        # the owner is woken twice for one lead.
        await lock_call_writes(session, call_id)
        await session.execute(
            text(
                "UPDATE leads SET status = 'hot', updated_at = now() "
                "WHERE id = :lid AND tenant_id = :tid AND status = 'new'"
            ),
            {"lid": lead_id, "tid": tenant_id},
        )
        if await _already_enqueued(
            session,
            job="notify_hot_lead",
            matcher={"lead_id": str(lead_id), "call_id": str(call_id)},
        ):
            return "already_queued"
        await enqueue_outbox(
            session,
            queue="notifications",
            job="notify_hot_lead",
            payload={
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "call_id": str(call_id),
                "triggers": triggered,
            },
        )
    return "queued"


# --- job 3: reconciliation ----------------------------------------------------

# How long after hangup the post-call pipeline is DEFINITELY late rather than merely
# in flight. Two readers, one number, on purpose:
#
# - `_pipeline_settled` will not re-drive a call younger than this, so the poller never
#   races a pipeline that is still working;
# - `dispatcher.report_stalled_pipeline` alerts past it.
#
# So "the alarm says this call was dropped" and "the poller will try to repair it" are
# the same instant by construction rather than two numbers that agree today. The value
# has to clear the pipeline's whole retry ladder (`RETRY_BACKOFF_S` = 30s + 120s, plus
# three job runs) with room to spare; ten minutes is roughly four times it, and is well
# inside the poller's own 30-minute listing window so a stalled call still gets ticks.
PIPELINE_STALL_AFTER = timedelta(minutes=10)


# THE ONE RULE for "this call was owed an extraction", as SQL, because two readers need
# it and neither can see the other's inputs.
#
# `_post_call_stages` decides in Python — `needs_extraction = bool(spec.fields or
# transcript_text)` — and both of its inputs are durable afterwards: the turns are rows
# and the schema is a row. So the same question is answerable from the database alone,
# which is what `dispatcher.report_stalled_pipeline` (no snapshot, no engine) and
# `_pipeline_settled` (a snapshot, but the schema is still only in the database) both
# need. Written once here rather than twice in two SQL strings, in the same style as
# `billing.caps.over_cap_sql`: the caller supplies the joins, this supplies the rule.
#
# CONTRACT: the caller must alias `calls` as `c` and LEFT JOIN `extraction_schemas` as
# `es` through the agent. LEFT, not inner — a call whose agent row was since removed
# still had a transcript and is still owed an extraction, and an inner join would drop
# it silently.
#
# WHY IT MATTERS THAT IT IS THE SAME RULE: without it the stall alarm counted every
# completed call with no `call_extractions` row, and a silent call on an agent with no
# schema fields legitimately has none — `needs_extraction` is false for it and the
# pipeline writes nothing. Those calls are permanently inside the 24-hour window, so the
# alarm fired on healthy traffic twice an hour forever, which is how an alarm stops
# being read before the first real stall arrives.
EXTRACTION_OWED_SQL = (
    "(EXISTS (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id) "
    "OR COALESCE(jsonb_array_length(es.fields), 0) > 0)"
)


def _expected_artifacts(snapshot: ExecutionSnapshot, *, extraction_owed: bool) -> tuple[str, ...]:
    """What a FINISHED pipeline must have left behind for THIS execution.

    The whole trick of the probe below, and the reason it needs no schema column. Asked
    without the snapshot, "is there a usage row" is unanswerable — a cost-less call, a
    silent call and a call with no number to key a lead on are all legitimately bare, so
    every absence reads as a stall and every healthy call is re-driven forever. Asked
    WITH the snapshot in hand, the ambiguity is gone: the engine's own record says
    whether this execution had a cost and whether it had a transcript, and an artefact
    the engine's data implies is one the pipeline owed.

    Three artefacts, each gated on the condition the pipeline itself gates on:

    - `transcript_turns` — `_persist_transcript` upserts one row per turn and returns
      early only on an empty transcript.
    - `usage` — `_meter` writes rows for every call whose snapshot carries a cost, and
      returns early only when rows already exist. Cost present with no usage row is a
      pipeline that did not reach step 5.
    - `extraction` — owed exactly when `needs_extraction` would be true, which the
      caller resolves with `EXTRACTION_OWED_SQL` because half of it lives in the
      database rather than in the snapshot.

    NOT a lead: `_upsert_lead` returns None when the other party has no number, and that
    is invisible from here without re-deriving the direction rule. Its absence is
    covered transitively — a pipeline that reached metering reached the lead upsert.
    """
    expected: list[str] = []
    if snapshot.transcript:
        expected.append("transcript")
    if snapshot.cost is not None:
        expected.append("usage")
    if extraction_owed:
        expected.append("extraction")
    return tuple(expected)


#: What the poller decided about one execution. `settled` is the only answer that means
#: "do nothing"; the other two are repair kinds, and they are separate because they are
#: different incidents — `missing_call` is a webhook we never received (the engine's
#: delivery is at most once, D-31) and `unfinished_pipeline` is a webhook we DID receive
#: and then dropped on our own side. One counter for both would have made the second
#: invisible for as long as the first kept happening.
ReconcileVerdict = Literal["settled", "missing_call", "unfinished_pipeline"]


async def _pipeline_settled(engine_name: str, snapshot: ExecutionSnapshot) -> ReconcileVerdict:
    """Is there nothing left for the post-call pipeline to do for this execution?

    THE QUESTION CAN ONLY BE ASKED INSIDE THE OWNING TENANT'S SESSION. `calls` is
    FORCE-RLS'd, so the untenanted probe this replaced returned zero rows for every
    execution ever placed — the poller therefore re-drove its entire 30-minute window on
    every tick and counted every healthy call as a repair, which both hides the real
    repairs the metric exists to surface and re-runs the pipeline for calls that were
    never broken.

    The route table is the same bridge `ingest_engine_event` uses, and it is deliberately
    not tenant-scoped precisely so this resolution needs no RLS exemption (hard rule 1).
    An execution we cannot map is handed to ingest anyway: it alerts on the unmapped
    agent, which is the outcome we want for a mis-provisioned agent.

    **IT USED TO ASK "IS THE CALL ROW WRITTEN", WHICH IS A DIFFERENT QUESTION, AND THE
    DIFFERENCE WAS A CALL LOST FOREVER.** `ingest_engine_event` writes `status =
    'completed'` and only THEN enqueues the pipeline, so a pipeline that never ran —
    Redis refused the enqueue, the worker was killed mid-job, the retry ladder ran out —
    left a completed call row with no transcript, no extraction, no lead and no usage
    event, and the probe skipped it on every subsequent tick. D-31 calls the poller the
    guarantee of record; for that shape it guaranteed only the status line. Measured
    rather than argued: ten consecutive ticks repaired nothing and the artefacts stayed
    at zero (`tests/poller_guarantee_test.py` is that experiment, kept).

    Widening it was previously rejected on the grounds that there is no honest marker,
    and that rejection was right about the marker and wrong about the question: see
    `_expected_artifacts`, which reads the ambiguity out by asking what THIS snapshot
    implies instead of what calls in general have. The alternative — a
    `calls.pipeline_completed_at` column set in the last stage's transaction — would
    answer "did the pipeline run", which is strictly weaker than "did the pipeline leave
    what it owed": a run that completed while silently producing nothing is exactly the
    shape a stage marker reports as healthy.

    THE GRACE IS PART OF THE PROBE, not a caller's concern. Inside
    `PIPELINE_STALL_AFTER` a bare completed call is overwhelmingly a pipeline that is
    queued or walking its retry ladder, and re-driving it would put a second extraction
    (a model round trip, billed) alongside one that is about to finish. Past it, the
    pipeline is late by the SLO's own definition and the poller is what repairs it.

    Costs one extra statement per completed execution and no extra round trip: both
    EXISTS probes ride the same SELECT as the call row.
    """
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, snapshot.engine_agent_ref)
    if resolved is None:
        return "missing_call"
    tenant_id, _agent_id = resolved
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.ended_at, "
                    "  EXISTS (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id) "
                    "    AS has_transcript, "
                    "  EXISTS (SELECT 1 FROM usage_events u WHERE u.call_id = c.id) AS has_usage, "
                    "  EXISTS (SELECT 1 FROM call_extractions e WHERE e.call_id = c.id) "
                    "    AS has_extraction, "
                    f"  {EXTRACTION_OWED_SQL} AS extraction_owed "
                    "FROM calls c "
                    "LEFT JOIN agents a ON a.id = c.agent_id AND a.tenant_id = c.tenant_id "
                    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE c.engine_call_id = :ecid AND c.tenant_id = :tid "
                    "AND c.status = 'completed' LIMIT 1"
                ),
                {"ecid": snapshot.engine_call_id, "tid": tenant_id},
            )
        ).first()
    if row is None:
        # No completed call row at all: the original question, and still the common case
        # — a webhook that never arrived.
        return "missing_call"
    ended_at, has_transcript, has_usage, has_extraction, extraction_owed = row
    present = {
        "transcript": bool(has_transcript),
        "usage": bool(has_usage),
        "extraction": bool(has_extraction),
    }
    missing = [
        name
        for name in _expected_artifacts(snapshot, extraction_owed=bool(extraction_owed))
        if not present[name]
    ]
    if not missing:
        return "settled"
    # `ended_at` is the engine's instant, not ours, and it can be absent on a call the
    # engine completed without one. Fall back to the snapshot's own value and, failing
    # that, treat the call as too young to judge: guessing "late" from a missing
    # timestamp would re-drive on every tick, which is the loop this probe exists to
    # avoid.
    finished_at = ended_at or snapshot.ended_at
    if finished_at is None or datetime.now(UTC) - finished_at < PIPELINE_STALL_AFTER:
        return "settled"
    log.warning(
        # Ids and artefact NAMES only (hard rule 6) — `missing` is a fixed vocabulary
        # from `_expected_artifacts`, never anything read out of a payload.
        "reconciliation_pipeline_unfinished",
        extra={"execution_id": snapshot.engine_call_id, "missing": ",".join(missing)},
    )
    return "unfinished_pipeline"


async def reconcile_executions(ctx: dict[str, Any]) -> str:
    """The guarantee of record (D-31), not a safety net.

    Bolna delivers webhooks at most once with no retries, so an event lost to a deploy,
    a network blip or a 500 is lost forever at the webhook layer. This runs every 10
    minutes, lists executions since the last window, and re-drives anything the post-call
    pipeline has not actually finished (`_pipeline_settled`). Every repair it makes is a
    call something dropped — which is why it emits a metric rather than passing quietly,
    and why the metric names WHICH of the two drops it was.

    And it reports what it could NOT see. The listing is the only window onto lost calls,
    so an adapter that cannot vouch for having read all of it (`ExecutionListing.complete`)
    turns this tick into an incident: see the alert below.

    ONE REPAIR ATTEMPT PER EXECUTION PER HOUR, and it is worth naming because it bounds
    the guarantee: the ARQ job id below is fixed per execution and `WorkerSettings.
    keep_result` is 3600s, so a re-drive that itself fails is not re-attempted until the
    dedupe window closes — by which time the 30-minute listing window has moved past the
    execution. A repair that fails is therefore the terminal alert's problem, not this
    job's, and `_abandon_ingest`/`_abandon_post_call` are what make that alert exist.
    """
    engine = get_engine()
    since = datetime.now(UTC) - timedelta(minutes=30)
    try:
        listing = await engine.list_executions(since=since)
    except Exception as exc:  # engine down: the next tick retries
        alert("WORKER_DELIVERY", "reconciliation_fetch_failed", detail=type(exc).__name__)
        return "engine_unavailable"

    # A LISTING THAT MIGHT HAVE BEEN CUT SHORT IS AN INCIDENT, NOT A DETAIL. Everything
    # this job repairs is a call whose webhook was lost, so an execution missing from the
    # listing is a call that no other mechanism will ever mention: no lead, no usage
    # event, no recording, and no error anywhere. The adapter cannot always know whether
    # the vendor truncated (Bolna publishes no pagination contract), so it says
    # `complete=False` with a reason and the decision to be loud is taken HERE — this is
    # the only caller, and a signal nobody reads is not a signal. It does NOT abort the
    # tick: the executions we DID get are still worth repairing.
    if not listing.complete:
        reason = listing.incomplete_reason or "unknown"
        alert(
            "WORKER_DELIVERY",
            "reconciliation_listing_incomplete",
            detail=(
                f"the engine listing may be truncated ({reason}): "
                f"{len(listing.snapshots)} executions over {listing.pages_fetched} page(s). "
                "Executions beyond it are unrecoverable — widen the window or confirm "
                "the engine's pagination (OPERATIONS §2 gate 6)."
            ),
            engine=engine.name,
        )
        record_reconciliation_listing_incomplete(reason=reason)

    snapshots = listing.snapshots
    repaired = 0
    for snapshot in snapshots:
        if not snapshot.billable_ready:
            continue
        verdict = await _pipeline_settled(engine.name, snapshot)
        if verdict == "settled":
            continue
        await enqueue(
            INGEST_JOB,
            {
                "engine": engine.name,
                "execution_id": snapshot.engine_call_id,
                "raw_status": snapshot.raw_status,
                "engine_agent_ref": snapshot.engine_agent_ref,
                "source": "reconciliation",
            },
            job_id=job_id_for(INGEST_JOB, engine.name, snapshot.engine_call_id, "reconcile"),
        )
        record_reconciliation_repair(kind=verdict)
        repaired += 1

    if repaired:
        log.warning("reconciliation_repaired", extra={"count": repaired})
    if not listing.complete:
        # The return value is what an operator reads in the job log; a bare
        # "repaired=0" on a truncated listing reads as "all quiet", which is the exact
        # misreading this slice exists to remove.
        return f"repaired={repaired} listing_incomplete={listing.incomplete_reason or 'unknown'}"
    return f"repaired={repaired}"


__all__ = [
    "EXTRACTION_OWED_SQL",
    "INGEST_JOB",
    "PIPELINE_STALL_AFTER",
    "POSTCALL_JOB",
    "ReconcileVerdict",
    "ingest_engine_event",
    "reconcile_executions",
    "run_post_call_pipeline",
]

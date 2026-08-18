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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NoReturn
from uuid import UUID

from arq import Retry
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TERMINAL_STATUSES
from calevate_shared.extraction import ExtractionOutput, ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment
from apps.api.billing.caps import (
    CAPS_CTE,
    announce_cap_headroom,
    cap_fullness,
    lock_tenant_spend_state,
    over_cap_sql,
)
from apps.api.billing.plans import ist_billing_month, month_pricing_instant, plan_in_effect_sql
from apps.api.billing.rates import (
    MONEY_Q,
    PREPAID_TIERS,
    ROUNDING,
    billable_tier,
    prepaid_billed_inr,
)
from apps.api.billing.service import charge_for_call, month_increment, plan_tier_of
from apps.api.compliance.deletion import refile_erasure_for_late_records
from apps.api.compliance.disclosure import disclosure_spoken
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
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.integrations import service as integrations
from apps.api.integrations.service import subscribed_endpoint_sql
from apps.api.reliability.service import (
    enqueue_outbox_once,
    mark_inbox_failed,
    mark_inbox_processed,
)
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
# The two names this module ENQUEUES rather than defines, promoted from literals (P6.9).
# They lived as bare strings at four call sites, which made them invisible to
# `tests/job_registration_test.py` — the guard whose entire job is noticing a job name no
# worker answers to. That guard could not see them because it inspected `node.args[0]` for
# every enqueuer, and `enqueue_outbox`'s first positional is the SESSION.
#
# Declared HERE rather than beside their functions for `compliance/deletion.DELETION_JOB`'s
# reason: the constant sits with the enqueuer, so `apps/api` never has to import
# `apps/workers` to name a job. `notify_hot_lead` lives in `workers/notifications.py` and
# `deliver_outbound_webhook` in `workers/outbound_webhooks.py`; both are registered in
# `settings.FUNCTIONS`, which is now what the guard actually checks these against.
HOT_LEAD_JOB = "notify_hot_lead"
OUTBOUND_WEBHOOK_JOB = "deliver_outbound_webhook"

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


async def _withdrawn_route_tenant(
    session: AsyncSession, engine: str, engine_agent_ref: str | None
) -> UUID | None:
    """The tenant a ref USED to belong to, when `_resolve_agent` found nothing.

    Only ever called on the miss path, and only to make the alarm actionable. "We have
    never heard of this agent" and "this agent's account was erased and its number is
    still pointed at the voice platform" are the same silence to `_resolve_agent` and
    completely different jobs for whoever is paged: the first is a mis-provisioned agent
    (`engine_agent_unmapped` has always meant that), the second is a telephony number
    somebody has to go and release, and it can only be discovered by a stranger ringing
    it (D-189, `workers/retention._WITHDRAW_ROUTES_SQL`).

    A tenant id is an id, so hard rule 6 permits it in the alert; the number that is
    still routed is not ours to log.
    """
    if not engine_agent_ref:
        return None
    row = (
        await session.execute(
            text(
                "SELECT tenant_id FROM engine_agent_routes "
                "WHERE engine_agent_ref = :ref AND engine = :engine AND NOT active"
            ),
            {"ref": engine_agent_ref, "engine": engine},
        )
    ).first()
    return UUID(str(row[0])) if row else None


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
        #
        # TWO SILENCES, TWO JOBS (D-189). A ref that was never mapped is a
        # mis-provisioned agent. A ref whose routing was WITHDRAWN is an offboarded
        # client whose number is still pointed at the voice platform, and somebody has
        # to release it with the telephony provider — a fact nothing else in the system
        # can discover, because the only symptom is a stranger ringing the old number.
        # Both stop the ingest; only one of them is fixed by looking at a publish.
        async with untenanted_session() as session:
            withdrawn_for = await _withdrawn_route_tenant(session, engine_name, agent_ref)
        if withdrawn_for is not None:
            alert(
                "WORKER_TERMINAL",
                "engine_agent_route_withdrawn",
                detail=(
                    f"engine={engine_name}; this account's routing was withdrawn "
                    "(offboarding/erasure) and its number is still live — release it "
                    "with the telephony provider and remove the agent at the engine"
                ),
                tenant_id=str(withdrawn_for),
                execution_id=execution_id,
            )
        else:
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
    spec, schema_version, agent_id, direction, disclosure_line = await _load_call_context(
        tenant_id, call_id
    )

    # STEP 2c — the evidence that the disclosure was spoken (P3.3). Numbered out of order
    # because that is where it belongs and where it now runs: it is transcript work, it
    # needs the agent row, and `_load_call_context` is the statement that fetches one. A
    # second query before STEP 2b purely to keep the numbers tidy would put a per-call
    # round trip on the critical path for cosmetics.
    #
    # BEFORE extraction rather than after, for `pipeline.opt_out`'s reason: extraction is
    # a model round trip with a 30-second timeout and a retry ladder behind it, and this
    # is a string match. A compliance record that is only written when the LLM answers is
    # a compliance record missing on exactly the calls somebody will ask about.
    with span("pipeline.disclosure", call_id=str(call_id)) as stage:
        played = disclosure_spoken(snapshot.transcript or [], disclosure_line=disclosure_line)
        await _record_disclosure(tenant_id, call_id, played)
        # The VERDICT, never the line and never a turn (hard rule 6).
        set_span_attributes(stage, disclosure_played=("unknown" if played is None else played))

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
        #
        # "Have we already?" is answered by the CALL ROW, not by scanning the outbox
        # (P6.7). The probe this replaced was `job = :job AND payload @> :matcher` against
        # a table with no index on either and nothing that prunes it — a sequential scan
        # per completed call, taken while holding the lock above, on the 2-minute SLO
        # path. `crm_notified_at` is the same fact on a row this transaction already has,
        # and it is stamped in this transaction so the flag and the outbox rows share one
        # fate. Not `enqueue_outbox_once`: the fan-out writes one row PER SUBSCRIBED
        # ENDPOINT and those are not duplicates of each other.
        if snapshot.status == "completed" and not await _crm_already_notified(session, call_id):
            written = await integrations.enqueue_event(
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
            # Only when a row was actually written. A tenant with no subscribed endpoint
            # gets zero rows from a perfectly healthy pipeline, and stamping anyway would
            # record "we told the client" about a client we told nothing — the flag would
            # then be a worse answer than the outbox scan it replaced. Left NULL, the next
            # run re-asks, which is now a column read on a row already in hand; and
            # `_expected_artifacts` is what stops the poller re-driving a call that was
            # never owed a fan-out.
            if written:
                await _mark_crm_notified(session, call_id)

        # STEP 9 — the DPDP obligation this run may have just broken (D-310).
        #
        # Everything above wrote personal data for this call. If a data principal's
        # erasure COMPLETED while this call was already under way, the certificate their
        # client handed on is now false: the transcript, the extraction, the summary, the
        # recording, the archived vendor document and the `leads` row are all back. The
        # erasure could not have reached forward, and nothing else in this pipeline knows
        # the request exists — so the check belongs here, after the last write rather
        # than before the first, because only a run that is finished can say what it left
        # behind.
        #
        # It re-FILES rather than erasing inline: `compliance/deletion.py` argues why (one
        # erase mechanism, and a second certificate is what the person is owed). In this
        # transaction so the row and its outbox job commit with the pipeline's own work.
        await refile_erasure_for_late_records(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            phones=(snapshot.from_e164, snapshot.to_e164),
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


async def _crm_already_notified(session: AsyncSession, call_id: UUID) -> bool:
    """Has the outbound CRM fan-out already been promised for this call?

    One indexed row read on the primary key, inside the tenant's session, where the
    containment scan of the whole outbox used to be (P6.7). Deliberately a fresh SELECT
    rather than a value threaded down from `_load_call_context`: it is read AFTER
    `lock_call_writes` in the same transaction, which is what makes it the current answer
    rather than one from before a concurrent run committed.
    """
    row = (
        await session.execute(
            text("SELECT crm_notified_at FROM calls WHERE id = :cid"), {"cid": call_id}
        )
    ).first()
    return row is not None and row[0] is not None


async def _mark_crm_notified(session: AsyncSession, call_id: UUID) -> None:
    """Stamp the fan-out, in the transaction that enqueued it.

    `WHERE crm_notified_at IS NULL` so a re-run cannot move the timestamp forward: this
    column answers "when did the client first hear about this call", and a value that
    drifts on every replay is not that.
    """
    await session.execute(
        text(
            "UPDATE calls SET crm_notified_at = now(), updated_at = now() "
            "WHERE id = :cid AND crm_notified_at IS NULL"
        ),
        {"cid": call_id},
    )


def hot_lead_dedupe_key(*, lead_id: UUID, call_id: UUID) -> str:
    """The key that makes the hot-lead alert happen once per (lead, call).

    A function rather than an f-string at the call site because `whatsapp.py` derives its
    own key from the same pair, and two spellings of one keyspace is how the email leg and
    the WhatsApp leg stop agreeing about whether a lead was already alerted on.
    """
    return f"hot-lead:{lead_id}:{call_id}"


async def _persist_transcript(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> str:
    """Store raw + redacted turns. Idempotent on (call_id, idx) so a re-run rewrites
    rather than duplicates.

    **A RE-RUN REPLACES THE TRANSCRIPT; IT DOES NOT MERGE TWO READINGS OF IT** (D-187).
    The upsert used to refresh `text` and `text_redacted` and leave `speaker`, `lang`,
    `start_ms` and `end_ms` at whatever the FIRST run wrote, and to leave any turn past
    the end of the new transcript in place. Both halves produce a row nobody spoke: the
    second run's words under the first run's speaker, and a tail belonging to a reading
    that has been superseded.

    It is reachable through our own parser rather than only through a fickle vendor.
    Bolna sends one prefix-tagged blob and `bolna.parse_transcript` indexes turns by
    POSITION, dropping a leading line it cannot attribute — so two fetches that disagree
    about the opening line are off by one for the whole call, and every turn inherits the
    other reading's speaker. `speaker` is not cosmetic: the extractor is speaker-aware
    (that is why `SAMPLE_TURNS` has the CALLER ask to book), and a mis-attributed turn is
    how a call becomes a hot lead nobody asked for.

    The delete is bounded to THIS call's tail and runs in the same transaction as the
    upserts, so a re-drive that is interrupted cannot leave the transcript shorter than
    either reading. An EMPTY new transcript still returns early and deletes nothing: one
    read coming back with no turns is not evidence that the turns we hold are wrong, and
    `_expected_artifacts` already treats an absent transcript as "nothing implied".
    """
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
                    "speaker = EXCLUDED.speaker, text = EXCLUDED.text, "
                    "text_redacted = EXCLUDED.text_redacted, lang = EXCLUDED.lang, "
                    "start_ms = EXCLUDED.start_ms, end_ms = EXCLUDED.end_ms, "
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
        # Whatever an EARLIER reading left that this one does not claim. `transcript_turns`
        # is tenant-scoped and is not an append-only ledger
        # (`db.registry.APPEND_ONLY_TABLES`), so this is a correction rather than a
        # rewrite of evidence — and the alternative is a call whose last turns come from a
        # transcript we no longer believe.
        #
        # Matched against the indices actually written rather than `idx >= len(turns)`:
        # contiguity is a property of today's parsers, not of `TranscriptTurn` (`idx` is
        # only constrained `ge=0`), and a length comparison would silently delete real
        # turns from the first adapter that numbers them any other way.
        await session.execute(
            text(
                "DELETE FROM transcript_turns WHERE tenant_id = :tid AND call_id = :cid "
                "AND NOT (idx = ANY(:kept))"
            ),
            {
                "tid": tenant_id,
                "cid": call_id,
                "kept": [turn.idx for turn in snapshot.transcript],
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
) -> tuple[ExtractionSchemaSpec, int, UUID, str, str]:
    """The call's agent, its direction, its disclosure line, and the schema ACTIVE AT
    EXTRACTION TIME.

    Direction comes from the stored call row rather than being re-derived: it decides
    which number belongs to the lead, and getting it wrong would file an outbound call
    under our own caller id.

    Leads render by the schema version stored on the row, so a later schema edit never
    rewrites an old lead (TRD §7).

    THE DISCLOSURE LINE RIDES ON THIS QUERY rather than getting its own. It comes from
    the same `agents` row this already joins, one column further along, and a second
    round trip for one string would put a per-call query on the pipeline's critical path
    to answer a question this statement was already standing next to. It is the agent's
    CURRENT line, not a snapshot of the one live when the call ran — the same
    approximation `_upsert_lead` accepts about the agent — and a tenant editing it
    mid-month can therefore make an old call read as undisclosed. That is visible and
    conservative (it can only turn True into False); the alternative is a
    `calls.disclosure_line_at_call` column, which is a real answer and a migration this
    finding does not call for. **D-163 widens that approximation by exactly one case**:
    a tenant who switches `ai_disclosure_enabled` off turns the verdict on their older
    calls from True to `None` (unknown), never to False — still the conservative
    direction, and the same column would fix both.
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    # THE AI SENTENCE, AND ONLY WHEN THE AGENT WAS ASKED TO VOLUNTEER IT
                    # (D-163). `disclosure_played` answers "did the agent say the AI
                    # disclosure", so the needle is the AI half rather than the legacy
                    # bundle — an agent whose owner has switched the RECORDING notice off
                    # would otherwise be scored against a sentence it was never asked to
                    # say and report a breach on every call. When the AI toggle itself is
                    # off the needle is the empty string, which `disclosure_spoken` turns
                    # into `None`: nothing was required, so nothing is certified.
                    "SELECT c.agent_id, c.direction, es.version, es.fields, "
                    "  CASE WHEN a.ai_disclosure_enabled THEN a.ai_disclosure_line ELSE '' END "
                    "FROM calls c "
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
    disclosure_line = str(row[4] or "")
    if not fields:
        empty = ExtractionSchemaSpec(version=version or 1, fields=[])
        return empty, version or 1, agent_id, direction, disclosure_line
    spec = ExtractionSchemaSpec.model_validate({"version": version or 1, "fields": fields})
    return spec, spec.version, agent_id, direction, disclosure_line


async def _record_disclosure(tenant_id: UUID, call_id: UUID, spoken: bool | None) -> None:
    """Write `calls.disclosure_played` — the column three surfaces render and nothing
    wrote (P3.3).

    A NULL VERDICT IS STILL WRITTEN, and writing `None` over a previous `True` is the
    behaviour we want on a re-run: the pipeline is re-runnable by design (TRD §8), and if
    a second pass sees no transcript then the evidence for the first pass's answer is
    gone too. A verdict that could only ever move towards `True` would be a compliance
    field that ratchets, which is the shape of a field that stops meaning anything.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET disclosure_played = :played, updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid"
            ),
            {"played": spoken, "cid": call_id, "tid": tenant_id},
        )


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


def _billable_seconds(snapshot: ExecutionSnapshot, *, tenant_id: UUID, call_id: UUID) -> Decimal:
    """This call's duration as a quantity we are willing to put on a ledger.

    **A NEGATIVE DURATION IS NOT A DURATION, AND IT USED TO REACH THE MONEY PATH.**
    `ExecutionSnapshot.duration_s` is `int | None` with no floor, and both adapters
    build it as `int(duration) if isinstance(duration, int | float) else None`
    (`engine/bolna.py`, `engine/cartesia.py`) — so a vendor's `-1` "unknown" sentinel,
    or a duration derived from two clocks that disagree, arrives here as a real number
    and is multiplied through everything.

    Measured on this tree before the guard existed, on a tenant with ₹120.96 already
    accrued for the month (`tests/negative_duration_test.py` is the reproduction):

        _meter(..., duration_s=-1)
          -> psycopg.errors.CheckViolation: new row for relation "spend_state"
             violates check constraint "ck_spend_state_billed_inr_nonnegative"

    Two things in that are worth stating because neither is obvious.

    * **The increment really is negative.** `month_increment` prices the month
      with the call and without it; taking seconds AWAY makes `after < before`, so the
      call's contribution is below zero and the month's counter is asked to go
      backwards. Every other path into that function is monotone — adding minutes can
      only raise a month's overage, whichever rung they land on — so the constraint
      had never been reachable and the abort had never been seen.
    * **The accumulated total staying positive does NOT save it.** PostgreSQL evaluates
      a CHECK against the row an `INSERT ... ON CONFLICT DO UPDATE` PROPOSES, before the
      conflict is arbitrated, so `billed_inr = -0.16` fails even though the update it
      would have become is `120.96 - 0.16`. Measured against this pg16 rather than
      recalled:

          INSERT INTO t VALUES (1, -5) ON CONFLICT (k) DO UPDATE SET v = t.v + EXCLUDED.v;
          ERROR:  new row for relation "t" violates check constraint "t_v_check"
          DETAIL:  Failing row contains (1, -5).

    The abort takes the WHOLE metering transaction with it, so the call ends up with no
    usage rows, no wallet debit and no counters — and every ARQ retry hits the same
    constraint, so it never recovers on its own. A vendor field we do not control must
    not be able to do that.

    **It is clamped to zero rather than refused, and the call still meters.** Zero is
    the already-designed answer for "this call has a real leg cost and no countable
    seconds" — `_unit_price` keeps the leg whole at `qty <= 0` and the client is billed
    for no minutes, which is the client-favourable direction and the same one
    `billable_tier` takes for an unprovable rung. Refusing to meter at all was the
    alternative and it is worse in exactly the way P1.2 describes: a completed call with
    no usage artefact is one the reconciliation poller calls `settled` and never
    revisits.

    The `alert()` is what stops that being silent. A negative duration is the adapter
    and the vendor disagreeing about a payload — the same class as
    `call_billable_without_cost` above, so it is announced the same way, with ids only
    (hard rule 6).
    """
    seconds = Decimal(snapshot.duration_s or 0)
    if seconds >= 0:
        return seconds
    alert(
        "WORKER_TERMINAL",
        "call_duration_negative",
        detail=(
            "the engine reported a negative call duration: metered the call at zero "
            "seconds so its leg costs still land, billed the client for no minutes, and "
            "left the month's counters alone. Check the adapter's duration key against a "
            "live payload (pilot gate 7)."
        ),
        call_id=str(call_id),
        tenant_id=str(tenant_id),
        # The value itself, because it is the one fact an operator needs to tell a
        # sentinel (`-1`) apart from a clock-skew subtraction, and it is not PII.
        duration_s=str(snapshot.duration_s),
    )
    return Decimal(0)


# THERE IS NO `_ist_month` HERE ANY MORE, and its removal is a money fix rather than a
# tidy-up. It read `(moment + timedelta(hours=5, minutes=30)).strftime("%Y-%m")`, which
# is the right arithmetic ONLY for a moment expressed in UTC — `strftime` renders the
# instant's own naive fields, so a value already carrying +05:30 got shifted a second
# time. Nothing guarantees UTC: both adapters parse `ended_at` with
# `datetime.fromisoformat` and PRESERVE whatever offset the vendor sent (`engine/bolna.py
# ::_parse_dt` — its `replace(tzinfo=UTC)` covers NAIVE values only), and the vendor here
# is an Indian voice platform. A call at 23:00 IST on the last of the month was therefore
# counted into the NEXT month's `spend_state` while its own `usage_events` row — read back
# through `billing.service._IST_MONTH`, which goes via `timestamptz` and is correct — sat
# in the right one. `billing.plans.ist_billing_month` is the one spelling, converts
# properly for any aware instant, and refuses a naive one instead of billing a month it
# guessed. (`tests/billing_month_ordering_test.py` and `tests/one_billing_month_spelling_
# test.py` are the two halves that keep it that way.)


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


# HOW ONE CALL MOVES ONE COUNTER, in the only three directions a call's month can sit
# relative to the month the row is already counting. Written ONCE and applied to each
# column, where it used to be three near-identical string literals differing only in a
# column name — the shape a fourth column silently gets wrong.
#
# **THE `ELSE` BRANCH IS THE FIX.** It used to be `EXCLUDED.<column>`, i.e. "any month
# that is not this one REPLACES the totals", which is right when the new month is LATER
# and destructive when it is EARLIER. A call that settles late — the reconciliation
# poller's 30-minute window straddling midnight IST on the 1st, an ARQ retry ladder
# crossing it, a vendor that takes minutes to price a call (`engine.py`) — arrives
# carrying LAST month's stamp, and the old rule handed it the whole row: this month's
# minutes, this month's supplier spend, this month's billed rupees and the `capped` flag
# were all replaced by that one call's, and `month` went backwards with them. A tenant one
# call short of their ceiling got a fresh month's headroom out of a call they had already
# made, and `compliance.spend_capped` then read the rolled-back month as no cap at all.
#
# So a closed month's call leaves the counters alone. Its money is NOT lost — `usage_events`
# is the ledger and it has the row (that is what every invoice and every panel reads);
# what it may not do is move a ceiling for a month it does not belong to. `spend_state`
# holds ONE month by construction (PK `tenant_id`, no history), so there is no other
# honest answer available to it.
#
# The comparison is a plain text one because `YYYY-MM` sorts chronologically as a string:
# both operands are the same fixed shape, so the ordering reduces to a digit comparison
# and no collation reorders digits. It is the same assumption `caps.read_spend_counters`
# already makes when it compares the stamp for equality.
def _accumulate(column: str) -> str:
    return (
        f"CASE WHEN spend_state.month = EXCLUDED.month "
        f"THEN spend_state.{column} + EXCLUDED.{column} "
        f"WHEN spend_state.month < EXCLUDED.month THEN EXCLUDED.{column} "
        f"ELSE spend_state.{column} END"
    )


_ACC_MINUTES = _accumulate("minutes_used")
# OUR supplier cost, which stays the margin panel's.
_ACC_SPEND = _accumulate("spend_used")
# The CLIENT's currency, accumulated beside ours (P1.3). `spend_used` is what the engine
# charged us; this is what the client owes and is what the cap below is compared against.
# A client's allowance does not carry into the next month any more than their minutes do.
_ACC_BILLED = _accumulate("billed_inr")


_SPEND_STATE_UPSERT = f"""
WITH caps AS ({CAPS_CTE})
INSERT INTO spend_state (
    tenant_id, month, minutes_used, spend_used, billed_inr, capped, created_at, updated_at
)
SELECT
    CAST(:tid AS uuid), CAST(:month AS text),
    CAST(:minutes AS numeric), CAST(:spend AS numeric), CAST(:billed AS numeric),
    -- THE CAP IS COMPARED AGAINST THE CLIENT'S NUMBER, not ours. It used to read
    -- `:spend`, so a client who capped themselves at ₹5,000 was stopped at ₹5,000 of
    -- CALEVATE's supplier cost — roughly ₹20,000 of their own bill.
    {over_cap_sql("CAST(:minutes AS numeric)", "CAST(:billed AS numeric)")},
    now(), now()
ON CONFLICT (tenant_id) DO UPDATE SET
    minutes_used = {_ACC_MINUTES},
    spend_used = {_ACC_SPEND},
    billed_inr = {_ACC_BILLED},
    -- Recomputed, never carried: on a month rollover the counters above reset, and a
    -- flag left at its old value is a tenant capped in July who can never dial in
    -- August — the counters would read one minute used and the gate would still refuse.
    capped = {over_cap_sql(_ACC_MINUTES, _ACC_BILLED)},
    -- Never backwards: `GREATEST` is the month half of the same rule `_accumulate`
    -- applies to the totals, so a late call from a closed month cannot re-stamp the row
    -- with a month that has already ended. It is also what makes the RETURNING below a
    -- usable answer to "did this call count".
    month = GREATEST(spend_state.month, EXCLUDED.month),
    updated_at = now()
RETURNING minutes_used, billed_inr, (SELECT cap_min FROM caps), (SELECT cap_spend FROM caps),
          month
"""
# RETURNING carries the alarm (see `announce_cap_headroom`), and it carries the totals
# AFTER this call rather than the crossing itself because the crossing needs both sides:
# the totals BEFORE are `returned - this call's delta`, which holds on all four paths —
# the insert (before = 0), the accumulate (before = the running total), the month
# rollover, where `_ACC_*` returns the EXCLUDED value and the subtraction gives 0 (exactly
# right for a month that just started), and the closed-month call, where the delta the
# caller subtracts is ZERO because nothing was applied.
#
# **`month` IS ON THE RETURNING FOR THAT LAST PATH, and it is the ONLY honest way to ask.**
# `EXCLUDED` is not referencable from a RETURNING clause — Postgres 16 answers "invalid
# reference to FROM-clause entry for table \"excluded\"", measured against this database
# rather than recalled — so the statement cannot hand back the branch it took directly.
# What it CAN hand back is the row's month afterwards, and because `GREATEST` never moves
# it backwards, `returned_month == :month` is precisely "this call's month is the one
# being counted, so its totals went in". Re-deriving that in Python from a second read of
# `spend_state` would be a second copy of the rule, which is how the caller and the
# statement start to disagree about one write.
#
# Postgres returns the NEW row from an `ON CONFLICT DO UPDATE`, and a CTE is visible in
# `RETURNING`, so the ceilings come back from the same `caps` the flag was computed
# against — reading `plans` a second time could land on a different row and announce
# against a ceiling the flag was not judged by.
# (postgresql.org/docs/16/sql-insert.html — "the ... RETURNING ... row values are those of
# the inserted or updated row".)


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
        # A CALL THAT COMPLETED AND CANNOT BE PRICED IS NOT A NON-EVENT (P1.2).
        #
        # `return 0` on its own wrote no usage row, took no credit, moved no
        # `spend_state` — and `_pipeline_settled` only expects a usage artefact when
        # `snapshot.cost is not None`, so the reconciliation poller, which is D-31's
        # GUARANTEE OF RECORD, classified the call `settled` and never came back for it.
        # Every client-facing money figure derives from `usage_events` rather than from
        # `calls`, so the blast radius of the vendor spelling `total_cost` differently on
        # the live account is: every usage panel reads 0 calls / ₹0.00, every invoice
        # renders empty, no cap ever arms, no wallet is ever debited — and nothing
        # anywhere goes red. That last clause is the defect; refusing to invent a price
        # is correct and stays.
        #
        # `billable_ready` is the discriminator, and it is what makes this an alert
        # rather than noise. A snapshot that is not yet billable has no cost because the
        # engine has not finished settling it (`engine.py`: the vendor may take minutes
        # after disconnect), and the poller WILL come back for that one. A snapshot the
        # adapter has declared billable and cannot price is the adapter and the vendor
        # disagreeing about the payload, which no amount of waiting fixes.
        if snapshot.billable_ready:
            alert(
                "WORKER_TERMINAL",
                "call_billable_without_cost",
                detail=(
                    "engine reported the execution as billable and the adapter could not "
                    "read a cost from it: metered nothing, charged nothing, and the "
                    "reconciliation poller will call this call settled. Check the "
                    "adapter's cost keys against a live payload (pilot gate 7)."
                ),
                call_id=str(call_id),
                tenant_id=str(tenant_id),
            )
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

        duration_s = _billable_seconds(snapshot, tenant_id=tenant_id, call_id=call_id)
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

        # WHAT THE CLIENT OWES FOR THIS CALL, which is not what it cost us (P1.1/P1.3).
        #
        # `cost.total_inr` is the ENGINE's charge to US. It used to be the amount debited
        # from the prepaid wallet as well, so the balance drained at roughly ₹2/min while
        # the runway framing on the client's own screen priced the same minute at
        # `self_serve_inr_per_min` (₹6.00) — the platform booking zero gross margin on the
        # entire self-serve motion, from one variable doing two jobs.
        #
        # WHICH IST BILLING MONTH THIS CALL BELONGS TO. Resolved here rather than beside
        # the counter write, because the RATES below are a fact about this month and not
        # about today (see the next paragraph). One spelling, `billing.plans
        # .ist_billing_month`, on the instant the ledger rows are stamped with.
        month = ist_billing_month(snapshot.ended_at or datetime.now(UTC))
        # THE PLAN ROW IS READ ONCE HERE and used for both halves below, rather than
        # re-read under the lock: a second reading could land on a different row if an
        # operator changed the plan between the two statements — the wallet debit and the
        # counter would then disagree about the price of one call.
        #
        # **AT THE MONTH'S OWN PRICING INSTANT, NOT AT `now()`, AND THAT IS A MONEY FIX.**
        # `month_pricing_instant` is what `usage_summary` and `billing/charges.py` already
        # resolve a month's terms at — now while the month is open, the month's LAST
        # instant once it is closed — so a statement re-rendered after a price change
        # still quotes the terms that were in force (`billing/plans.py` is the whole
        # argument). This read said `NOW_SQL`, so a call that SETTLES LATE was priced by
        # today's plan while its own month's panel and invoice priced it by that month's:
        # the reconciliation poller's window straddling midnight IST on the 1st, an ARQ
        # retry ladder crossing it, or a vendor that takes minutes to price a call
        # (`engine.py` says so in as many words) all land there. Measured on this tree,
        # one ten-minute call ending on the last day of a month whose ₹2/min terms were
        # superseded by ₹20/min on the 1st (`tests/late_call_prices_at_its_own_month_
        # test.py` is the reproduction):
        #
        #     spend_state.billed_inr   ₹200.00   <- the counter, at today's rate
        #     usage_summary / invoice   ₹20.00   <- that month's own rate
        #
        # The CEILING is deliberately still resolved at `now()` inside the upsert's
        # `caps` CTE (`billing/caps.CAPS_CTE`), and the split is not an inconsistency: a
        # RATE is a term of the month being priced, and a CAP is a question about whether
        # this tenant may dial right now.
        plan_rates = (
            await session.execute(
                text(
                    plan_in_effect_sql(
                        "COALESCE(included_min, 0) AS included_min, "
                        "overage_rate, overage_rate_value"
                    )
                ),
                {"tid": tenant_id, "at": month_pricing_instant(month)},
            )
        ).first()
        # THE PLAN'S TERMS AS THIS CALL SEES THEM. Both rungs, not one: this counter no
        # longer picks a marginal rate per call. It used to — the call's own `tts_tier`
        # chose between `overage_rate` and `overage_rate_value` and the allowance was
        # spent in ARRIVAL order — which is a SECOND way of pricing a month beside the one
        # the invoice uses, and the two diverge as soon as a plan quotes both rates.
        # `billing.service.priced_overage` is now the only rule and
        # `_billed_for_this_call` charges the difference this call makes to it.
        included_min = Decimal(str(plan_rates[0])) if plan_rates is not None else Decimal("0")
        overage_rate = (
            Decimal(str(plan_rates[1]))
            if plan_rates is not None and plan_rates[1] is not None
            # A plan that quotes no overage rate accrues nothing, and a list price is
            # deliberately NOT substituted for one (`priced_overage`): the same rate has
            # to price the panel, the cap AND the invoice.
            else Decimal("0")
        )
        # NULL is not zero: "this plan quotes no separate value rate" (bill every overage
        # minute at `overage_rate`) and "the value rung is free" are different plans.
        overage_rate_value = (
            Decimal(str(plan_rates[2]))
            if plan_rates is not None and plan_rates[2] is not None
            else None
        )

        # Prepaid credits move with the metering, keyed by call_id so a pipeline
        # re-run cannot double-charge (D-39). Managed tenants are invoiced against a
        # retainer instead, which `charge_for_call` reads from plan_tier.
        #
        # PREPAID HAS NO ALLOWANCE, so the debit needs no month arithmetic and can be
        # taken before the `spend_state` lock: every minute is charged at the list price.
        if tier in PREPAID_TIERS:
            await charge_for_call(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                amount_inr=prepaid_billed_inr(
                    minutes=minutes,
                    self_serve_rate=get_settings().self_serve_inr_per_min,
                ),
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
        increment = await _counter_increment(
            session,
            tenant_id=tenant_id,
            plan_tier=tier,
            month=month,
            minutes=minutes,
            seconds=duration_s,
            tts_tier=tts_tier,
            included_min=included_min,
            rate=overage_rate,
            rate_value=overage_rate_value,
        )
        billed = increment.billed_inr
        counters = (
            await session.execute(
                text(_SPEND_STATE_UPSERT),
                {
                    "tid": tenant_id,
                    "month": month,
                    "minutes": increment.minutes,
                    "spend": cost.total_inr,
                    "billed": billed,
                },
            )
        ).first()
        if counters is not None:
            # The alarm OPERATIONS §4 promised and nothing implemented (R-2): a capped
            # tenant's campaign stops dialling while the console still says "running",
            # and the only trace was a `compliance_blocks` log line. Announced from the
            # write that crosses the line, D-140's shape exactly.
            #
            # Fired INSIDE this transaction, like `ai_quota._announce_platform_headroom`
            # and for the same reason: the alternative is threading a "say this after you
            # commit" through every caller. The cost is bounded and stated — a rollback
            # after this point means one alert about a call that did not meter, which is
            # an operator reading a spend cap that is one call further away than it said.
            minutes_after = Decimal(str(counters[0]))
            billed_after = Decimal(str(counters[1]))
            cap_min = Decimal(str(counters[2])) if counters[2] is not None else None
            cap_spend = Decimal(str(counters[3])) if counters[3] is not None else None
            # DID THIS CALL COUNT? The row's month after the write answers it (see the
            # RETURNING note): anything other than this call's month means the counter is
            # already on a LATER month and `_accumulate` left it alone, so the delta the
            # crossing arithmetic subtracts is zero and no alarm can fire about a call
            # that moved nothing.
            counted = str(counters[4]) == month
            applied_minutes = increment.minutes if counted else Decimal("0")
            applied_billed = billed if counted else Decimal("0")
            if not counted:
                # An operator reading a cap that did not move needs to know a call was
                # deliberately not counted into it. Ids and months only — no rupees, no
                # phone, no lead (hard rules 6 and the log discipline `warn_no_plan_in_
                # effect` states). Not an `alert()`: around a month boundary this is the
                # expected outcome, and an alarm that fires every rollover is a muted one.
                log.info(
                    "spend_counter_skipped_closed_month",
                    extra={
                        "tenant_id": str(tenant_id),
                        "call_id": str(call_id),
                        "call_month": month,
                        "counter_month": str(counters[4]),
                    },
                )
            announce_cap_headroom(
                tenant_id=tenant_id,
                month=month,
                before=cap_fullness(
                    minutes_used=minutes_after - applied_minutes,
                    billed_inr=billed_after - applied_billed,
                    cap_min=cap_min,
                    cap_spend=cap_spend,
                ),
                after=cap_fullness(
                    minutes_used=minutes_after,
                    billed_inr=billed_after,
                    cap_min=cap_min,
                    cap_spend=cap_spend,
                ),
            )
    return len(rows)


@dataclass(frozen=True, slots=True)
class _CounterIncrement:
    """What one call moves each `spend_state` counter by. Both come from ONE read.

    `spend_used` is deliberately not here: it is `cost.total_inr`, the engine's charge
    to US, and it needs no month arithmetic at all.
    """

    #: What this call adds to `spend_state.minutes_used`. THE LEDGER'S OWN INCREMENT for
    #: every tier, not the call's `duration_s / 60` — see `month_increment` for the
    #: measurement, and note that this is what makes the counter the ceiling is judged
    #: against exactly equal to the "minutes used" the client is shown.
    minutes: Decimal
    #: What this call adds to `spend_state.billed_inr` — the CLIENT's currency.
    billed_inr: Decimal


async def _counter_increment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    plan_tier: str | None,
    month: str,
    minutes: Decimal,
    seconds: Decimal,
    tts_tier: str,
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> _CounterIncrement:
    """This call's contribution to the two `spend_state` counters the cap is judged on.

    **MUST be called with `lock_tenant_spend_state` held**, and AFTER this call's
    `usage_events` rows are written in the same transaction. It reads the month's ledger
    and the caller then writes a figure derived from it, which is the read-then-write
    over money CLAUDE.md's concurrency rule names; the lock is already taken by the only
    caller for the upsert's own sake, so this costs nothing and adds no second lock to
    reason about.

    **THE MINUTE FIGURE IS THE LEDGER'S, ON EVERY TIER**, which is why `month_increment`
    is now called for a prepaid tenant too — the rupee half of its answer is unused
    there, and the read it comes from is the one the minute half needs. What that buys
    is stated in full on `month_increment`: the counter `over_cap_sql` compares against
    stops being a per-call quotient rounded at the column's scale and becomes exactly the
    figure `usage_summary` publishes. The cost is one grouped aggregate over the month's
    `usage_events` on the prepaid path that was not there before, under a lock this
    caller already holds.

    PREPAID (`self_serve`, `trial`) RUPEES: every minute is charged with no allowance in
    front of it, so the accrual is the same figure `charge_for_call` was just given, from
    the same function. Deliberately computed twice rather than threaded through as a
    variable — the two are the same NUMBER but not the same FACT, and a future tier with
    a wallet discount would want the debit and the accrual to diverge without either
    quietly following the other. It is emphatically NOT the ledger's increment: a call is
    charged for its own length, and pricing it off the month's running remainder would
    charge two identical calls differently on a statement a client reads per entry.

    MANAGED RUPEES: the difference this call makes to the MONTH's overage bill, priced by
    `billing.service.priced_overage` — the same function that prices the client's panel
    and prints the invoice's lines.

    **THIS BRANCH USED TO CARRY ITS OWN PRICING RULE and that was the defect.** It read
    the month's running minutes off `spend_state` and charged
    `over(before + m) - over(before)` at a rate chosen from THIS call's rung, i.e. it
    spent the included allowance in arrival order — where the invoice spends it on the
    DEARER rung first. The two agree for a plan quoting one rate (so they agreed for
    every plan in the database, `plans.overage_rate_value` being an open founder
    decision) and diverge as soon as a second is quoted: measured at ₹880.00 against
    ₹520.00 on a two-rung month whose cheap minutes arrived first, which is a client
    reading two totals for one month on one screen and a spend cap biting against the
    larger. `tests/two_rung_counter_agrees_test.py` is that reproduction.

    Reading the LEDGER rather than the counter also removes the closed-month caveat this
    docstring used to carry: `month_increment` scopes its read to `month`, so a
    call belonging to a closed month prices against that month's own rows rather than
    against whatever the single `spend_state` row happens to be stamped with.
    """
    increment = await month_increment(
        session,
        tenant_id=tenant_id,
        month=month,
        tier=tts_tier,
        seconds=seconds,
        included_min=included_min,
        rate=rate,
        rate_value=rate_value,
    )
    if plan_tier in PREPAID_TIERS:
        return _CounterIncrement(
            minutes=increment.minutes,
            # THIS CALL'S OWN MINUTES, not the ledger's increment, and the difference is
            # deliberate: `spend_state.billed_inr` for a prepaid tenant must equal the
            # sum of the `usage` debits actually taken off their wallet, because the
            # wallet IS their bill (D-39). `charge_for_call` was handed exactly this
            # figure a few lines above, from this same function, so the counter and the
            # ledger of record cannot drift by a paisa.
            billed_inr=prepaid_billed_inr(
                minutes=minutes,
                self_serve_rate=get_settings().self_serve_inr_per_min,
            ),
        )
    return _CounterIncrement(minutes=increment.minutes, billed_inr=increment.overage_inr)


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
        # ONE STATEMENT, and once-only is the database's decision rather than ours
        # (P6.7). This used to be a containment scan of the whole outbox followed by an
        # insert — unindexable, and correct only because the lock above was taken first.
        # `enqueue_outbox_once` returns None when the promise was already on the books.
        queued = await enqueue_outbox_once(
            session,
            job=HOT_LEAD_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "call_id": str(call_id),
                "triggers": triggered,
            },
            dedupe_key=hot_lead_dedupe_key(lead_id=lead_id, call_id=call_id),
        )
        if queued is None:
            return "already_queued"
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


def _expected_artifacts(
    snapshot: ExecutionSnapshot, *, extraction_owed: bool, crm_fanout_owed: bool
) -> tuple[str, ...]:
    """What a FINISHED pipeline must have left behind for THIS execution.

    The whole trick of the probe below, and the reason it needs no schema column. Asked
    without the snapshot, "is there a usage row" is unanswerable — a cost-less call, a
    silent call and a call with no number to key a lead on are all legitimately bare, so
    every absence reads as a stall and every healthy call is re-driven forever. Asked
    WITH the snapshot in hand, the ambiguity is gone: the engine's own record says
    whether this execution had a cost and whether it had a transcript, and an artefact
    the engine's data implies is one the pipeline owed.

    Four artefacts, each gated on the condition the pipeline itself gates on:

    - `transcript_turns` — `_persist_transcript` upserts one row per turn and returns
      early only on an empty transcript.
    - `usage` — `_meter` writes rows for every call whose snapshot carries a cost, and
      returns early only when rows already exist. Cost present with no usage row is a
      pipeline that did not reach step 5.
    - `extraction` — owed exactly when `needs_extraction` would be true, which the
      caller resolves with `EXTRACTION_OWED_SQL` because half of it lives in the
      database rather than in the snapshot.
    - `crm_fanout` — the D-23 outbound sync, step 8 and therefore LAST. See below.

    **THE FOURTH ONE CLOSES THE HOLE THAT MADE THIS LIST A GUARANTEE OF THE FIRST FIVE
    STEPS RATHER THAN OF THE PIPELINE** (P6.4). `_post_call_stages` has eight steps and
    this list covered three, all of them at or before step 5. Steps 6, 7 and 8 — the
    hot-lead notification, the campaign-contact resolution and the CRM fan-out — run
    AFTER metering, each in its own transaction. So a pipeline that died between step 5's
    commit and step 8 left `usage_events` written, this probe answered `settled`, and the
    poller never came back: **the client's CRM was never told about that call, and nothing
    anywhere recorded that it was not told.** `report_stalled_pipeline` could not see it
    either — `EXTRACTION_OWED_SQL` asks only about extraction.

    The justification this docstring used to carry ("a pipeline that reached metering
    reached the lead upsert") is true, and true of step 4, which PRECEDES metering. It
    proves nothing about 6-8, and the two sentences had been read as one.

    **WHY THE CRM FAN-OUT AND NOT ALL THREE.** It is the last step, so its presence
    implies 6 and 7 ran; and it is the only one of the three with a durable artefact that
    is not conditional on something this function cannot see. Step 6's notification is
    skipped for a lead that is not hot, and step 7's is a no-op for a call that was not a
    campaign dial — both legitimately leave nothing, which is exactly the ambiguity that
    makes an artefact useless as a probe.

    **AND WHY IT NEEDS `has_crm_endpoint`.** `integrations.enqueue_events` writes one
    outbox row per SUBSCRIBED ACTIVE ENDPOINT and returns 0 when there are none — which
    is most tenants, most of the time. Expecting the artefact unconditionally would make
    every call on every tenant without a CRM integration read as `unfinished_pipeline`
    forever, re-driving a whole pipeline (including a billed extraction) on every tick.
    That is precisely the failure this function's first paragraph exists to prevent, one
    artefact later.

    NOT a lead: `_upsert_lead` returns None when the other party has no number, and that
    is invisible from here without re-deriving the direction rule. Its absence is
    covered transitively — a pipeline that reached metering reached the lead upsert.

    **THE SNAPSHOT MUST BE A COMPLETE ONE, AND THIS FUNCTION CANNOT CHECK THAT** (D-187).
    Everything above turns an ABSENCE in the engine's record into "nothing was owed",
    which is sound for `get_execution` and unproven for a `list_executions` row — the
    contract calls those summaries. `_pipeline_settled` is where that gap is closed: it
    confirms an empty expectation set against the authenticated read before believing it.
    """
    expected: list[str] = []
    if snapshot.transcript:
        expected.append("transcript")
    if snapshot.cost is not None:
        expected.append("usage")
    if extraction_owed:
        expected.append("extraction")
    # Step 8 gates on exactly this status, so this list does too — a call that did not
    # complete was never owed a fan-out.
    if snapshot.status == "completed" and crm_fanout_owed:
        expected.append("crm_fanout")
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

    Costs one extra statement per completed execution and no extra round trip: every
    EXISTS probe rides the same SELECT as the call row.
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
                    # STEP 8's artefact (P6.4), read off the call row the query already
                    # has. It used to be a correlated EXISTS containment-scanning the
                    # whole outbox — per completed execution, per tick, over a table with
                    # no index on `job` and nothing that prunes it (P6.7). One writer
                    # (`_mark_crm_notified`, in the same transaction as the fan-out) and
                    # one reader, so the probe and the writer cannot spell the question
                    # two ways, which was the earlier concern and is now structural
                    # rather than a matched pair of literals.
                    #
                    # It also stops depending on the outbox being immortal — which the
                    # prune sweep this release adds would have quietly broken, turning
                    # every call older than the floor into a permanent "unfinished
                    # pipeline" the poller re-drove forever.
                    "  (c.crm_notified_at IS NOT NULL) AS has_crm_fanout, "
                    # And whether one was OWED at all, because a tenant with no
                    # subscribed active endpoint gets zero outbox rows from a perfectly
                    # healthy pipeline — and expecting the artefact anyway would re-drive
                    # every call on every tick forever.
                    #
                    # IMPORTED, NOT MIRRORED. This used to restate the predicate and the
                    # restatement dropped the `kind = ANY(...)` half, so a third endpoint
                    # kind landing in the CHECK constraint ahead of its worker would have
                    # turned every completed call for that tenant into a permanent
                    # `unfinished_pipeline` — re-driven hourly, with a billed extraction
                    # each time. `subscribed_endpoint_sql` carries the argument.
                    #
                    # BARE NAME, not `integrations.subscribed_endpoint_sql`, and that is a
                    # requirement rather than a style: `scripts/check_raw_sql.py` resolves
                    # a helper's return value only through a plain-name call, because
                    # `module.helper(...)` and `obj.helper(...)` are indistinguishable in
                    # the AST — resolving attribute calls would let any object with a
                    # same-named method inherit this function's safety verdict. Written
                    # the other way, this line fails the injection guard.
                    "  EXISTS (SELECT 1 FROM outbound_webhooks w WHERE "
                    f"    {subscribed_endpoint_sql('w')}) AS crm_fanout_owed, "
                    f"  {EXTRACTION_OWED_SQL} AS extraction_owed "
                    "FROM calls c "
                    "LEFT JOIN agents a ON a.id = c.agent_id AND a.tenant_id = c.tenant_id "
                    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE c.engine_call_id = :ecid AND c.tenant_id = :tid "
                    "AND c.status = 'completed' LIMIT 1"
                ),
                {
                    "ecid": snapshot.engine_call_id,
                    "tid": tenant_id,
                    # The predicate's own binds, so the probe and `enqueue_event` cannot
                    # even be given different kinds.
                    "event": "call.completed",
                    "kinds": list(integrations.DELIVERABLE_KINDS),
                },
            )
        ).first()
    if row is None:
        # No completed call row at all: the original question, and still the common case
        # — a webhook that never arrived.
        return "missing_call"
    (
        ended_at,
        has_transcript,
        has_usage,
        has_extraction,
        has_crm_fanout,
        crm_fanout_owed,
        extraction_owed,
    ) = row
    present = {
        "transcript": bool(has_transcript),
        "usage": bool(has_usage),
        "extraction": bool(has_extraction),
        "crm_fanout": bool(has_crm_fanout),
    }
    # `ended_at` is the engine's instant, not ours, and it can be absent on a call the
    # engine completed without one. Fall back to the snapshot's own value and, failing
    # that, treat the call as too young to judge: guessing "late" from a missing
    # timestamp would re-drive on every tick, which is the loop this probe exists to
    # avoid.
    finished_at = ended_at or snapshot.ended_at
    late = finished_at is not None and datetime.now(UTC) - finished_at >= PIPELINE_STALL_AFTER

    expected = _expected_artifacts(
        snapshot, extraction_owed=bool(extraction_owed), crm_fanout_owed=bool(crm_fanout_owed)
    )
    if not expected and late and not any(present.values()):
        # THE SNAPSHOT THE POLLER HOLDS IS A LISTING ROW, AND A LISTING ROW IS A SUMMARY
        # (D-187). `_expected_artifacts` reads what a call was owed off the engine's own
        # record, which is only sound while that record is COMPLETE.
        # `reconcile_executions` — this function's one production caller — passes rows
        # from `list_executions`, and nothing promises those carry the cost and the
        # transcript `get_execution` does: the contract calls them summaries
        # (`VoiceEngine.get_execution`), Bolna publishes no OpenAPI spec, and whether
        # their `GET /executions` rows are as rich as `GET /executions/{id}` is a vendor
        # behaviour NOBODY HAS VERIFIED (D-31/D-32, OPERATIONS §2 gate 6). Both adapters
        # happen to build listing rows with the same code as fetches, and the Bolna stub
        # returns whole execution documents, so the conformance suite cannot fail on the
        # assumption either — which is exactly why it survived as a silent premise.
        #
        # If it is wrong the failure is silent and total for one population: a completed
        # call whose pipeline died, on an agent with no extraction schema and a tenant
        # with no CRM endpoint, implies NOTHING from a summary row — `settled`, forever,
        # never transcribed, never metered, never invoiced, and no alert anywhere. That
        # is the shape D-31 appoints this poller to recover.
        #
        # So an EMPTY expectation set is confirmed against the authenticated read before
        # it is believed, and only there — the three conditions bound the cost tightly.
        # `not expected`: the row carried neither cost nor transcript, so a healthy call
        # under a rich listing never reaches this line. `not any(present.values())`: the
        # database holds nothing either, so a call whose pipeline ran is answered from
        # its own artefacts with no vendor request at all. `late`: the 10-minute grace
        # has elapsed, and the 30-minute listing window then admits the execution about
        # three more times, so a genuinely silent call costs a handful of reads in its
        # whole life rather than one per tick.
        #
        # A failing read PROPAGATES: `reconcile_executions` counts it as `unreached` and
        # says so in `reconciliation_probe_incomplete`, which already reports repairs as
        # a floor. Swallowing it would answer `settled` on no evidence, which is the
        # defect this block exists to remove.
        snapshot = await get_engine().get_execution(snapshot.engine_call_id)
        expected = _expected_artifacts(
            snapshot, extraction_owed=bool(extraction_owed), crm_fanout_owed=bool(crm_fanout_owed)
        )

    missing = [name for name in expected if not present[name]]
    if not missing or not late:
        return "settled"
    log.warning(
        # Ids and artefact NAMES only (hard rule 6) — `missing` is a fixed vocabulary
        # from `_expected_artifacts`, never anything read out of a payload.
        "reconciliation_pipeline_unfinished",
        extra={"execution_id": snapshot.engine_call_id, "missing": ",".join(missing)},
    )
    return "unfinished_pipeline"


async def callable_tenants() -> list[UUID]:
    """Every tenant that can have call rows at all.

    `engine_agent_routes` is the SAME non-tenant-scoped bridge `ingest_engine_event`
    uses, and it exists precisely so a cross-tenant resolution needs no RLS exemption
    (hard rule 1, `db/registry.py`). A call row is only ever created for an agent the
    engine knows, the publish path upserts the route in the transaction that mints the
    ref, and routes are deactivated rather than deleted — so this set covers every
    tenant a stalled call can belong to, without walking organizations that have never
    taken one.

    Deliberately unfiltered on `active`: an agent unpublished after a call still leaves
    that call's extraction owed.

    IT LIVES HERE RATHER THAN IN `dispatcher.py`, WHERE IT WAS WRITTEN. Two sweeps now
    need it — `report_stalled_pipeline` and this module's `_reconcile_outstanding_calls`
    (D-242) — and `dispatcher` already imports `pipeline`, so a second copy was the only
    other way and would have been a second answer to "which tenants can hold a call".
    """
    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    # ORDER BY for `retention._due_tenants`' reason: without it the order
                    # is planner-dependent, so which tenants a partially failing sweep
                    # reached changed from tick to tick.
                    text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id")
                )
            )
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


# --- the half of the guarantee the LISTING cannot cover (D-242) ---------------
#
# `list_executions` asks the vendor for `created_after=<now - 30 minutes>` — a filter on
# when the execution was CREATED. The poller's promise is about when a call FINISHED, and
# those are the same instant only for calls shorter than the window. For a call that ran
# 40 minutes, `completed` lands ~43 minutes after creation and every listing from then on
# excludes it: the execution falls out of the window before its terminal transition ever
# happens. Bolna's webhook is at-most-once with errors swallowed (D-31, verified in their
# OSS delivery code), so ONE lost delivery on a long call left it never transcribed, never
# metered, never invoiced — and invisible to everything else: `report_stalled_pipeline`
# asks `EXTRACTION_OWED_SQL`, which only sees calls already recorded `completed`, and the
# row a lost terminal webhook leaves behind is stuck at `in_progress`.
#
# Nothing in this tree ever said the poller's coverage was bounded by call DURATION. That
# is the silent premise D-31/D-32 exist to forbid, sitting under the one mechanism
# appointed the guarantee of record.
#
# WHY NOT JUST WIDEN THE LISTING WINDOW. A `created_after` of 25 hours would cover the
# tail, and it would also re-list a whole day of executions on every sweep — past
# `_LISTING_MAX_PAGES` for any real fleet, so the poller would report
# `reconciliation_listing_incomplete` on every healthy tick and train the operator to
# ignore the one alarm that says calls are unrecoverable. It also does nothing at all for
# a call that never completes.
#
# WHY NOT AN `updated_after` FILTER. Because it would be a GUESS. `_next_link` refuses to
# invent a pagination parameter for exactly this reason — "a `?page=` the vendor ignores
# returns page one forever, which is a silent truncation wearing the costume of a fix" —
# and inventing a freshness parameter has the identical failure mode. Bolna publishes no
# OpenAPI spec; whether `GET /executions` accepts any such filter is OPERATIONS §2 gate 6,
# and if it turns out to, this job gets cheaper rather than unnecessary.
#
# WHAT THIS DOES INSTEAD is ask the engine about the executions WE ALREADY KNOW ARE
# OUTSTANDING. A call row exists from its first transition (`_ingest_stages` upserts on
# every one), so our own `calls` table already names every call whose ending we never
# heard about — see `_OUTSTANDING_CALLS_SQL` for the two shapes that takes. Each candidate
# gets one authenticated `get_execution` — the read D-187 made `_pipeline_settled` trust —
# and anything the pipeline still owes is re-driven through the same `INGEST_JOB` under the
# same fixed job id, so this job and the listing sweep cannot queue one call's repair
# twice.
#
# ITS OWN CRON RATHER THAN A SECOND PHASE OF `reconcile_executions`, and the reason is
# cost shape. This sweep is O(tenants) — `calls` is FORCE-RLS'd, so "which tenants hold an
# unfinished call" can only be asked one tenant session at a time, exactly as
# `report_stalled_pipeline` asks its question. Bolting that onto the 10-minute guarantee
# tick would triple the fleet-wide fan-out to buy a recovery latency nobody needs: the
# COMMON path (a short call whose webhook was lost) is already covered by the listing
# within ten minutes, and the population this job exists for is calls that have already
# been unfinished for longer than the stall window. Half-hourly, offset from both
# neighbours so the three fan-outs do not collide.

#: How long a non-terminal call row is left alone before the engine is asked about it
#: directly. The same number `_pipeline_settled` waits before believing a call is late:
#: inside it, a call is overwhelmingly still ringing or still talking.
OUTSTANDING_PROBE_AFTER = PIPELINE_STALL_AFTER

#: And how far back it keeps asking. A row still non-terminal a day later is not something
#: another `get_execution` will fix — the vendor has forgotten the call, or the id we hold
#: never named one — so probing it forever would spend a vendor request per sweep per
#: broken row for the life of the deployment. It is REPORTED instead
#: (`calls_never_finished`), which is the outcome a human can act on.
OUTSTANDING_PROBE_HORIZON = timedelta(hours=24)

#: Rows read per tenant per sweep. Oldest first, so a tenant over the cap makes progress
#: from the end closest to falling past the horizon rather than churning the newest rows.
OUTSTANDING_PROBE_PER_TENANT = 50

#: Vendor requests this sweep will make in total, across every tenant. The per-tenant cap
#: bounds one tenant; this bounds the SWEEP, which is what keeps a fleet-wide incident from
#: turning one cron tick into thousands of requests against the engine we are already
#: failing to hear from.
#:
#: WHAT IT COSTS, said plainly: `callable_tenants()` is ordered by tenant id, so a sweep
#: that exhausts the budget starves the SAME tail of the fleet every time until the
#: incident clears or those calls fall past the horizon. That is why hitting it is
#: ALERTED rather than merely bounded — a truncated sweep that passed quietly would be the
#: same defect as a truncated listing reporting `complete=True`. A rotating start offset
#: was the alternative and was rejected: it needs durable state to be fair and makes the
#: sweep non-deterministic to reason about, in exchange for spreading an incident the
#: alert already says to go and fix.
OUTSTANDING_PROBE_BUDGET = 200

#: A call the ENGINE still calls non-terminal this long after it started. Not a repair —
#: there is nothing to re-drive — but it is the shape of a call burning platform minutes
#: with nobody watching, or of an `engine_call_id` that no longer names anything. Two hours
#: is far past any plausible SMB call.
CALL_ABANDONED_AFTER = timedelta(hours=2)

# TWO SHAPES OF UNFINISHED CALL, and both of them are invisible once the execution has
# aged out of the listing window:
#
#   * a row that never reached a terminal status — the terminal webhook was lost, so the
#     call is stuck at `queued`/`ringing`/`in_progress` and NOTHING watches it:
#     `EXTRACTION_OWED_SQL` only asks about calls already recorded `completed`;
#   * a row recorded `completed` that carries neither a usage event nor a transcript turn
#     — the status webhook landed and the pipeline behind it did not. Inside the listing
#     window `_pipeline_settled` catches this (D-187); outside it, on an agent with no
#     extraction schema and a tenant with no CRM endpoint, `report_stalled_pipeline` is
#     silent too, because nothing was owed an extraction.
#
# `status = 'completed'` bounds the second clause rather than `status = ANY(terminal)`, and
# that is the whole reason it is affordable: a `no_answer`, `busy` or `failed` call
# legitimately has no cost and no transcript FOREVER, so the wider predicate would make
# every failed dial in the last 24 hours a candidate on every sweep. Only `completed`
# promises artefacts (TRD §5: cost, recording and transcript populate at `completed`), so
# only `completed` can be missing them.
_OUTSTANDING_CALLS_SQL = (
    "SELECT c.engine_call_id, COALESCE(c.started_at, c.created_at) AS began, c.status "
    "FROM calls c "
    "WHERE COALESCE(c.started_at, c.created_at) < now() - :after "
    "AND COALESCE(c.started_at, c.created_at) > now() - :horizon "
    "AND (c.status <> ALL(:terminal) OR (c.status = 'completed' "
    "  AND NOT EXISTS (SELECT 1 FROM usage_events u WHERE u.call_id = c.id) "
    "  AND NOT EXISTS (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id))) "
    "ORDER BY began LIMIT :cap"
)


async def reconcile_outstanding_calls(ctx: dict[str, Any]) -> str:
    """Ask the engine about every call whose ending we never heard about.

    The second half of D-31's guarantee of record — see the block comment above for why
    the listing sweep cannot cover it and why this is not a wider window.

    ONE TENANT'S FAILURE IS NOT THE SWEEP'S, and one CALL's is not its tenant's: the same
    shape `reconcile_executions`, `report_stalled_pipeline`, `retention.sweep_tenants` and
    `qa_sampling.draw_for_tenants` all take (R-4). Every counter rides the return string
    and the alert, so a repair count reads as a FLOOR rather than a total.
    """
    engine = get_engine()
    repaired = 0
    unreached = 0
    abandoned = 0
    probes = 0
    truncated = False
    for tenant_id in await callable_tenants():
        if probes >= OUTSTANDING_PROBE_BUDGET:
            truncated = True
            break
        try:
            async with tenant_session(tenant_id) as session:
                rows = (
                    await session.execute(
                        text(_OUTSTANDING_CALLS_SQL),
                        {
                            "terminal": sorted(TERMINAL_STATUSES),
                            "after": OUTSTANDING_PROBE_AFTER,
                            "horizon": OUTSTANDING_PROBE_HORIZON,
                            "cap": OUTSTANDING_PROBE_PER_TENANT,
                        },
                    )
                ).all()
        except Exception:
            # The tenant id, never the exception's payload: a psycopg error string can
            # quote the row that broke it, and these rows are calls (hard rule 6).
            log.exception("outstanding_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue
        for engine_call_id, began, status in rows:
            if probes >= OUTSTANDING_PROBE_BUDGET:
                truncated = True
                break
            execution_id = str(engine_call_id)
            probes += 1
            try:
                snapshot = await engine.get_execution(execution_id)
            except Exception:
                # Includes the honest refusal an adapter raises for an execution the
                # vendor does not hold — a real answer about a real problem, but not one
                # a re-drive fixes, so it is counted rather than acted on.
                log.warning(
                    "outstanding_probe_unreadable",
                    extra={"execution_id": execution_id, "engine": engine.name},
                )
                unreached += 1
                continue
            if not snapshot.terminal:
                if datetime.now(UTC) - began >= CALL_ABANDONED_AFTER:
                    abandoned += 1
                continue
            if str(status) in TERMINAL_STATUSES and (
                await _pipeline_settled(engine.name, snapshot) == "settled"
            ):
                # THE VERDICT IS NOT RE-DERIVED HERE. A completed call with no cost and no
                # transcript is not necessarily a dropped pipeline — the engine may simply
                # have nothing to give for it — and `_pipeline_settled` is where that
                # question is already answered from the snapshot rather than from what
                # calls in general look like (D-187). Asking it a second way here is how
                # the poller would start re-driving healthy calls, which is the defect its
                # whole history is made of.
                continue
            await enqueue(
                INGEST_JOB,
                {
                    "engine": engine.name,
                    "execution_id": execution_id,
                    "raw_status": snapshot.raw_status,
                    "engine_agent_ref": snapshot.engine_agent_ref,
                    "source": "reconciliation",
                },
                # The SAME key the listing sweep uses, so a call that both mechanisms
                # reach cannot be driven twice.
                job_id=job_id_for(INGEST_JOB, engine.name, execution_id, "reconcile"),
            )
            record_reconciliation_repair(kind="outside_listing_window")
            repaired += 1

    if abandoned:
        # NOT a repair: there is nothing to re-drive, because the engine says the call has
        # not ended. Either it is genuinely still up hours later — platform minutes burning
        # with nobody watching — or the row's `engine_call_id` no longer names anything the
        # vendor holds. Both need a human; neither is fixed by another sweep.
        alert(
            "WORKER_STALL",
            "calls_never_finished",
            detail=(
                f"{abandoned} call(s) have been non-terminal for over "
                f"{CALL_ABANDONED_AFTER.total_seconds() / 3600:.0f}h and the engine still "
                "reports them unfinished — check the engine console for live calls and the "
                "worker log for outstanding_probe_unreadable"
            ),
            engine=engine.name,
        )
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "outstanding_probe_incomplete",
            detail=(
                f"{unreached} tenant(s) or call(s) could not be probed, so repaired="
                f"{repaired} is a floor rather than a total — check the worker log for "
                "outstanding_probe_failed and outstanding_probe_unreadable"
            ),
            engine=engine.name,
        )
    if truncated:
        # A sweep that stopped early and said nothing would be the listing's
        # `complete=True` defect in a second place: the calls past the cut have no other
        # mechanism behind them until they fall past the horizon.
        alert(
            "WORKER_DELIVERY",
            "outstanding_probe_budget_exhausted",
            detail=(
                f"more than {OUTSTANDING_PROBE_BUDGET} unfinished calls are outstanding; "
                "this sweep stopped there and the rest were not probed. That many at once "
                "is an engine or ingest incident, not a backlog to wait out"
            ),
            engine=engine.name,
        )
    return f"repaired={repaired} probed={probes} unreached={unreached} abandoned={abandoned}"


async def reconcile_executions(ctx: dict[str, Any]) -> str:
    """The guarantee of record (D-31), not a safety net.

    Bolna delivers webhooks at most once with no retries, so an event lost to a deploy,
    a network blip or a 500 is lost forever at the webhook layer. This runs every 10
    minutes, lists executions since the last window, and re-drives anything the post-call
    pipeline has not actually finished (`_pipeline_settled`). Every repair it makes is a
    call something dropped — which is why it emits a metric rather than passing quietly,
    and why the metric names WHICH of the two drops it was.

    And it reports what it could NOT see. The listing is one window onto lost calls, so an
    adapter that cannot vouch for having read all of it (`ExecutionListing.complete`)
    turns this tick into an incident: see the alert below.

    IT IS NOT THE ONLY WINDOW, and saying it was is what let D-242 through. The listing is
    filtered on when an execution was CREATED, so a call that runs longer than the window
    has fallen out of it before it ever ends. `reconcile_outstanding_calls` is the second
    half: it asks the engine directly about every call row we hold that has not reached a
    terminal status, which needs no vendor filter and covers a call of any length.

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
    unreached = 0
    examined = 0
    for snapshot in snapshots:
        if not snapshot.billable_ready:
            continue
        examined += 1
        # ONE EXECUTION'S FAILURE IS NOT THE SWEEP'S (R-4). This loop had no `try`, so a
        # single tenant's probe error — a connection reset, a pool timeout, an RLS/GUC
        # problem — ended the sweep for every execution BEHIND it in the listing and took
        # the job down with it. The listing is D-31's guarantee of record, the only
        # mechanism that recovers a webhook Bolna never delivered, and the failure was
        # silent: the two `alert()` calls above cover the listing FETCH and listing
        # INCOMPLETENESS, neither of which is an exception in here. A transient fault
        # self-heals on the next tick's overlapping window; a persistent one on a tenant
        # sitting early in the vendor's ordering means the guarantee quietly stops
        # guaranteeing with the console green.
        #
        # Same shape as `dispatcher.report_stalled_pipeline`, `retention.sweep_tenants`
        # and `qa_sampling.draw_for_tenants`: per-item `try`, an `unreached` counter, and
        # the counter on both the return string and the alert body so the repair count
        # reads as a FLOOR rather than a total.
        try:
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
        except Exception:
            # The execution id, never the exception's payload: a psycopg error string can
            # quote the row that broke it, and these rows are calls (hard rule 6). The id
            # is the engine's own opaque handle and is what a poller re-run needs.
            log.exception(
                "reconciliation_probe_failed",
                extra={"execution_id": snapshot.engine_call_id, "engine": engine.name},
            )
            unreached += 1
            continue
        record_reconciliation_repair(kind=verdict)
        repaired += 1

    if repaired:
        log.warning("reconciliation_repaired", extra={"count": repaired})
    if unreached:
        # LOUD, because the alternative is the failure mode this whole block exists to
        # remove. A sweep that skipped executions reports a SMALLER repair count, which
        # reads exactly like a healthy fleet — an alarm that fails towards silence is
        # worse than no alarm.
        alert(
            "WORKER_DELIVERY",
            "reconciliation_probe_incomplete",
            detail=(
                f"{unreached} of {examined} execution(s) could not be probed or "
                f"re-driven, so repaired={repaired} is a floor rather than a total. "
                "Their calls are recoverable only while they stay inside the 30-minute "
                "listing window — check the worker log for reconciliation_probe_failed."
            ),
            engine=engine.name,
        )
    tail = f" unreached={unreached}" if unreached else ""
    if not listing.complete:
        # The return value is what an operator reads in the job log; a bare
        # "repaired=0" on a truncated listing reads as "all quiet", which is the exact
        # misreading this slice exists to remove.
        return (
            f"repaired={repaired}{tail} listing_incomplete={listing.incomplete_reason or 'unknown'}"
        )
    return f"repaired={repaired}{tail}"


__all__ = [
    "EXTRACTION_OWED_SQL",
    "INGEST_JOB",
    "PIPELINE_STALL_AFTER",
    "POSTCALL_JOB",
    "ReconcileVerdict",
    "callable_tenants",
    "ingest_engine_event",
    "reconcile_executions",
    "reconcile_outstanding_calls",
    "run_post_call_pipeline",
]

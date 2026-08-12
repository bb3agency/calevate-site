"""ARQ worker settings.

Run: uv run arq apps.workers.settings.WorkerSettings

Every job is idempotent and keyed (post-call work is keyed by call_id), retries 3
times with exponential backoff, and lands in a DLQ with an alert on exhaustion
(TRD §8).

**Tolerant boot** (BACKEND-PATTERNS §2): workers hard-require only DB + Redis. A
missing provider key must NOT crash-loop every queue — the extractor falls back to the
offline implementation and completeness is reported at `/healthz/ready` instead. A
worker that refuses to start because Sarvam is unconfigured takes down recording
copies and metering too, which is a far worse failure than degraded extraction.
"""

from typing import Any

from arq import cron

from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.observability import (
    init_observability,
    shutdown_tracing,
    traced_job,
    tracing_enabled,
)
from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
from apps.api.core.settings import runtime_config_missing_keys, validate_bootstrap_env
from apps.workers.campaign_dispatch import dispatch_campaign_tick
from apps.workers.dispatcher import dispatch_outbox, report_stalled_pipeline, sweep_expired
from apps.workers.notifications import notify_hot_lead
from apps.workers.optout import record_in_call_optout
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.pipeline import ingest_engine_event, reconcile_executions, run_post_call_pipeline
from apps.workers.retention import apply_retention, execute_deletion_request
from apps.workers.whatsapp import escalate_campaign_contact, notify_hot_lead_whatsapp

log = get_logger(__name__)

# `traced_job` is what makes the trace survive Redis: it pops the W3C traceparent the
# enqueue side put in the job payload and opens the worker's span as a CHILD of the
# request that queued the work. Without it a post-call trace would start at the worker
# and the queue wait — usually the largest slice of the "lead visible in 2 minutes"
# budget — would be invisible.
#
# It wraps at IMPORT time and costs nothing when tracing is off (one global read), so
# there is no configuration under which the two lists disagree about which jobs exist.
# `functools.wraps` inside it preserves `__qualname__`, which is the name arq registers
# and the name every producer enqueues by — a mismatch here would DLQ every job.
FUNCTIONS: list[Any] = [
    traced_job(fn)
    for fn in (
        ingest_engine_event,
        run_post_call_pipeline,
        notify_hot_lead,
        # D-23: the client's CRM hears about leads and calls through the same outbox as
        # every other side effect, so a delivery cannot outlive a rolled-back write.
        deliver_outbound_webhook,
        # A DPDP erasure is queued rather than run inline: it touches many rows and must
        # survive a request timing out halfway through.
        execute_deletion_request,
        # Both WhatsApp jobs. An unregistered job is not a dormant feature — the outbox
        # publishes it, arq does not recognise the name, and the row walks its retry
        # ladder into the DLQ while every screen reports the message was queued.
        # `tests/job_registration_test.py` is the guard; this pair is why it exists.
        notify_hot_lead_whatsapp,
        escalate_campaign_contact,
        # Hard rule 5's fast half: voice-runtime acks the engine's opt-out tool call and
        # queues this. Unregistered, the caller's request would be acked to the vendor,
        # dropped by arq, and only recovered by the post-call transcript pass minutes
        # later — the exact silent-degradation shape `job_registration_test.py` guards.
        record_in_call_optout,
    )
]

# Crons are traced too. They have no enqueuing parent, so each tick is its own ROOT
# trace — which is the point for `dispatch_outbox`: outbox lag is a stage of the same
# 2-minute SLO, and it is invisible from the call's own trace.
CRON_JOBS = [
    # The outbox dispatcher is the heartbeat of every reliable side effect.
    cron(traced_job(dispatch_outbox), second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
    # D-31: the guarantee of record, not a safety net. 10 minutes matches the window
    # in which a Bolna execution reaches `completed` plus margin.
    cron(traced_job(reconcile_executions), minute={0, 10, 20, 30, 40, 50}, run_at_startup=True),
    cron(traced_job(report_stalled_pipeline), minute={5, 35}),
    # The dispatch tick (FLOWS §5). Hard rule 5's DNC propagation deadline is
    # 'before the next dispatch tick' — this cron IS that tick.
    cron(traced_job(dispatch_campaign_tick), second={0, 30}),
    cron(traced_job(sweep_expired), hour={3}, minute={17}),
    # Retention is a legal obligation, not a cleanup task: without this the
    # policies we promise in the DPA are only a table (SEC-COMP §4).
    cron(traced_job(apply_retention), hour={3}, minute={40}),
]


async def startup(ctx: dict[str, Any]) -> None:
    validate_bootstrap_env()
    configure_logging()
    # The worker has no `create_app`, so bootstrap step 3 happens here instead — and it
    # must, because the worker is the CONSUMER side of the trace. If only the API
    # initialised tracing, every enqueued traceparent would arrive at a process with no
    # provider and the call's trace would end at Redis.
    observability = init_observability("workers")
    missing = runtime_config_missing_keys()
    if missing:
        # Log, do not die. `/healthz/ready` is the go-live gate.
        log.warning("worker_started_degraded", extra={"missing_config": missing})
    log.info(
        "worker_start",
        extra={
            "jobs": len(FUNCTIONS),
            "crons": len(CRON_JOBS),
            "observability": observability,
            "tracing": tracing_enabled(),
        },
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_stop")
    # Drain the batch processor: a worker stopping mid-pipeline is exactly the trace
    # someone will go looking for.
    shutdown_tracing()


class WorkerSettings:
    functions = FUNCTIONS
    cron_jobs = CRON_JOBS
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_tries = WORKER_MAX_TRIES
    # `max_tries` only counts attempts for jobs that ask to be retried. arq 0.28 retries
    # a job for `arq.Retry`, `RetryJob` or `CancelledError` and for NOTHING else — a job
    # that fails by raising anything else is finished on its first attempt, whatever this
    # number says. Every worker that wants the ladder must `raise Retry(defer=...)`; see
    # `apps/workers/outbound_webhooks.py` and `StorageUnavailableError`. Set explicitly
    # rather than left to the default, because the default is what makes the ladder work
    # at all.
    retry_jobs = True
    job_timeout = 300
    # Keep results long enough for the ARQ-level job-id dedupe window to be useful
    # against duplicate webhooks (BACKEND-PATTERNS §4's cheapest layer).
    keep_result = 3600

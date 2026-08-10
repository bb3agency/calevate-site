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
from apps.api.core.queue import redis_settings
from apps.api.core.settings import runtime_config_missing_keys, validate_bootstrap_env
from apps.workers.dispatcher import dispatch_outbox, report_stalled_pipeline, sweep_expired
from apps.workers.notifications import notify_hot_lead
from apps.workers.pipeline import ingest_engine_event, reconcile_executions, run_post_call_pipeline

log = get_logger(__name__)

FUNCTIONS: list[Any] = [
    ingest_engine_event,
    run_post_call_pipeline,
    notify_hot_lead,
]

CRON_JOBS = [
    # The outbox dispatcher is the heartbeat of every reliable side effect.
    cron(dispatch_outbox, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
    # D-31: the guarantee of record, not a safety net. 10 minutes matches the window
    # in which a Bolna execution reaches `completed` plus margin.
    cron(reconcile_executions, minute={0, 10, 20, 30, 40, 50}, run_at_startup=True),
    cron(report_stalled_pipeline, minute={5, 35}),
    cron(sweep_expired, hour={3}, minute={17}),
]


async def startup(ctx: dict[str, Any]) -> None:
    validate_bootstrap_env()
    configure_logging()
    missing = runtime_config_missing_keys()
    if missing:
        # Log, do not die. `/healthz/ready` is the go-live gate.
        log.warning("worker_started_degraded", extra={"missing_config": missing})
    log.info("worker_start", extra={"jobs": len(FUNCTIONS), "crons": len(CRON_JOBS)})


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_stop")


class WorkerSettings:
    functions = FUNCTIONS
    cron_jobs = CRON_JOBS
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 300
    # Keep results long enough for the ARQ-level job-id dedupe window to be useful
    # against duplicate webhooks (BACKEND-PATTERNS §4's cheapest layer).
    keep_result = 3600

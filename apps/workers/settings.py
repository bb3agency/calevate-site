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
from apps.api.core.settings import (
    runtime_config_missing_keys,
    settings_scope,
    validate_bootstrap_env,
)
from apps.workers.billing import issue_one_time_charges
from apps.workers.campaign_dispatch import TICK_SECONDS, dispatch_campaign_tick
from apps.workers.dispatcher import dispatch_outbox, report_stalled_pipeline, sweep_expired
from apps.workers.engine_reconciliation import SWEEP_MINUTES, sweep_engine_drift
from apps.workers.notifications import notify_hot_lead
from apps.workers.optout import record_in_call_optout
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.pipeline import ingest_engine_event, reconcile_executions, run_post_call_pipeline
from apps.workers.qa_sampling import draw_qa_samples
from apps.workers.retention import (
    apply_retention,
    execute_deletion_request,
    execute_tenant_erasure,
)
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
        # The other erasure: the end of an engagement rather than one data principal's
        # §12 request. Queued for the same reason and registered here for the reason the
        # WhatsApp pair below is — an unregistered job is not a dormant feature, it is a
        # row walking its retry ladder into the DLQ while the console reports the
        # offboarding as under way.
        execute_tenant_erasure,
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
    #
    # `second` comes FROM the dispatcher rather than being written here, because the
    # dispatcher now reasons about its own interval: it alerts when a tick overruns it
    # and it holds a lease sized against it. Two places writing "30" is how those stop
    # being true.
    #
    # **This schedule does NOT serialise the tick, and arq offers no setting that does.**
    # A cron job's arq id embeds its intended execution time (`arq/worker.py::run_cron`),
    # so the :30 tick and the :00 tick are different jobs with different in-progress keys
    # and will happily run at once; the documented alternative, a fixed
    # `cron(job_id=...)`, holds its in-progress key for 60s after the job ENDS
    # (`keep_cronjob_progress`) and would turn a 30-second tick into a 60-second one.
    # `campaign_dispatch._tick_lease` is where single-flight actually comes from.
    cron(traced_job(dispatch_campaign_tick), second=set(TICK_SECONDS)),
    cron(traced_job(sweep_expired), hour={3}, minute={17}),
    # THE WEEKLY QA SPOT-CHECK (SURFACES §1): 5% of every client's calls, drawn so the
    # draw can be re-run and checked (`apps/api/quality/sampling.py`). Monday, early.
    #
    # **The schedule does not decide which week is sampled** — `qa_sampling.closed_weeks`
    # does, from the firing instant converted to IST, and it only ever asks for weeks
    # that have CLOSED. That matters because arq evaluates cron fields in the WORKER
    # HOST's timezone (`Worker.timezone` defaults to the system zone), which this repo
    # pins nowhere; a schedule whose correctness depended on the host clock would sample
    # a partial week the day somebody deployed to a differently-configured box. Monday
    # 02:20 is after the IST week boundary on both a UTC host (07:50 IST) and an IST one,
    # so the tick is early either way and the draw is right regardless.
    #
    # `max_tries` EXPLICIT for the reason `issue_one_time_charges` states below:
    # `cron()` defaults it to 1 and `WorkerSettings.max_tries` does not reach a function
    # carrying its own. A sampling tick that gave up on its first failure would leave a
    # week undrawn with every screen still green. Verified against a real
    # `arq.worker.Worker` in `tests/qa_sampling_test.py`, not asserted by this comment.
    cron(
        traced_job(draw_qa_samples),
        weekday={0},
        hour={2},
        minute={20},
        max_tries=WORKER_MAX_TRIES,
    ),
    # Retention is a legal obligation, not a cleanup task: without this the
    # policies we promise in the DPA are only a table (SEC-COMP §4).
    cron(traced_job(apply_retention), hour={3}, minute={40}),
    # THE DRIFT SWEEP (D-123). `engine_drift_for` was on-demand only, so the two
    # divergences a publish-time read-back structurally cannot see — an agent edited in
    # the VENDOR'S dashboard, and a publish that failed on our side after the vendor
    # committed — stayed wrong until somebody opened that one agent's screen.
    #
    # `minute` comes FROM the module rather than being written here, for the reason
    # `dispatch_campaign_tick`'s `second` does: `engine_reconciliation` reasons about its
    # own interval — it asserts at import that a tick's worst case fits inside it, which
    # is what lets it skip the Redis lease the campaign tick needs — and two places
    # writing "30 minutes" is how that assertion stops being true.
    #
    # `max_tries` EXPLICIT, the reason `issue_one_time_charges` states below: `cron()`
    # defaults it to 1, so a sweep that gave up on its first failure would leave every
    # client's live agent unwatched with the console still green.
    cron(
        traced_job(sweep_engine_drift),
        minute=set(SWEEP_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE SETUP FEE STOPS WAITING FOR A HUMAN. Before this cron the onboarding charge
    # was written by whoever rendered the tenant's invoice, so a client nobody looked
    # at was never billed (`apps/workers/billing.py` and `billing/charges.py` carry the
    # argument, including why daily and not monthly, and why the schedule cannot decide
    # which month the fee lands on).
    #
    # `max_tries` is passed EXPLICITLY because `cron()` defaults it to 1 — the
    # `WorkerSettings.max_tries` below is only a default for functions that do not set
    # their own, and a billing job that quietly gave up its first time out would be the
    # kind of half-wired feature that still looks green. It costs nothing when the tick
    # succeeds: the job only asks for a retry when a tenant actually failed.
    #
    # 02:05 local, ahead of the 03:xx retention/sweep block so a slow sweep cannot
    # delay billing behind it. Which tenant-month a charge belongs to does not depend on
    # this hour, which is what lets it be chosen for scheduling reasons alone.
    cron(
        traced_job(issue_one_time_charges),
        hour={2},
        minute={5},
        max_tries=WORKER_MAX_TRIES,
    ),
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


#: Where a job's settings pin lives between the two hooks below. Keyed with a leading
#: underscore so it cannot collide with anything a job puts in `ctx`.
_SCOPE_KEY = "_settings_pin"


async def on_job_start(ctx: dict[str, Any]) -> None:
    """Pin `Settings` for the life of THIS job (D-101 completes here).

    Requests got this in `create_app`'s middleware; jobs were the half left open, and
    they are the half that runs longest. A post-call pipeline reading `usd_inr_rate`
    when it prices a call and again when it writes the usage row could read a different
    rate each time if a console change landed in between — one call billed at two rates,
    which is a WRONG number in an append-only ledger, not a stale one.

    Entered here rather than wrapped around each job function because arq calls this
    inside the same task that then awaits the function, so the ContextVar set here is
    visible to it — and because a wrapper is a thing 20 job functions have to remember.
    Tasks copy the context at creation, so two jobs running concurrently in one worker
    each get their own pin rather than sharing one.

    The big red switch is deliberately NOT covered by this, and must not be: it is
    `platform_state` read through `core/loadshed`, not a `Settings` field, precisely so
    a halt reaches a dispatch tick already in progress.
    """
    scope = settings_scope()
    scope.__enter__()
    ctx[_SCOPE_KEY] = scope


async def on_job_end(ctx: dict[str, Any]) -> None:
    """Release the pin. Runs even when the job raised — arq calls this either way, which
    is what stops a failed job leaking its pin into whatever the worker runs next."""
    scope = ctx.pop(_SCOPE_KEY, None)
    if scope is not None:
        scope.__exit__(None, None, None)


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
    # One resolution per job, released even on failure. See `on_job_start`.
    on_job_start = on_job_start
    on_job_end = on_job_end
    max_tries = WORKER_MAX_TRIES
    # `max_tries` only counts attempts for jobs that ask to be retried. arq 0.28 retries
    # a job for `arq.Retry`, `RetryJob` or `CancelledError` and for NOTHING else — a job
    # that fails by raising anything else is finished on its first attempt, whatever this
    # number says. Every worker that wants the ladder must `raise Retry(defer=...)`; see
    # `apps/workers/outbound_webhooks.py` and `StorageUnavailableError`. Set explicitly
    # rather than left to the default, because the default is what makes the ladder work
    # at all.
    retry_jobs = True
    # Also the ceiling on how long ONE dispatch tick can run: arq cancels at it, and
    # `campaign_dispatch.TICK_LEASE_TTL_S` is sized to outlive this number so a lease
    # cannot expire under a tick that is still dialling. `tests/dispatch_tick_lease_test`
    # pins the relationship — a comment cannot fail a build.
    job_timeout = 300
    # Keep results long enough for the ARQ-level job-id dedupe window to be useful
    # against duplicate webhooks (BACKEND-PATTERNS §4's cheapest layer).
    keep_result = 3600

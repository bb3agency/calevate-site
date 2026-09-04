"""ARQ worker settings.

Run: uv run arq apps.workers.settings.WorkerSettings

Every job is idempotent and keyed (post-call work is keyed by call_id) and retries 3 times
with exponential backoff.

Windows: set the selector loop policy at import time. psycopg's async driver cannot run
on the default ProactorEventLoop (`tests/conftest.py`, `scripts/seed_dev.py`); without
this, every cron that opens Postgres fails and outbox mail — including the admin OTP —
never leaves `pending`.

**THERE IS NO ARQ DEAD-LETTER QUEUE, and this docstring used to say there was** (P6.5).
The sentence promised "lands in a DLQ with an alert on exhaustion", and two more modules
repeated it. What actually exists is the OUTBOX's `status='failed'`, which is fully wired
— an ops replay action, a depth metric, an audit note — but that covers the ENQUEUE leg.
On the EXECUTION leg, an arq job that exhausts its ladder is `zrem`'d off the queue,
written to a result key for `keep_result` seconds, and gone: nothing in `apps/` or
`scripts/` reads an arq result key, a job status or a failed-job set.

**So the alert is not a property of the queue; it is a property of each job**, and the
shape every job that matters uses is the one `billing.issue_one_time_charges` spells out —
`if attempt < WORKER_MAX_TRIES: raise Retry(...)`, else `alert(...)` and then RAISE, because
returning would file the tick as a success with a number in it that nobody reads. A job
that does not make that pair of gestures fails in silence, whatever this file says.

**AND THAT SENTENCE HAD TWO HOLES IN IT, because it assumed the job's code runs.** Read
off the installed `arq.worker.Worker.run_job`, there are two terminal states where it does
not, and on both of them a per-job `alert()` is structurally unreachable:

* an enqueue for a name no worker registers — `logger.warning('job %s, function %r not
  found')` and `job_failed(...)`, before the function is ever looked up successfully;
* `job_try > max_tries` — `logger.warning('%6.2fs ! %s max retries %d exceeded')` and
  `finish_failed_job(...)`, checked BEFORE `on_job_start`, so the ladder's last rung is a
  pickup the job never sees. Every job that raises `Retry` up to its budget ends here, and
  so does any cron cancelled at `job_timeout` three times running — which is
  `apply_retention` gone until tomorrow with nothing but a log line.

`ARQ_TERMINAL_MESSAGES` and `install_arq_terminal_alerter` below close both by routing
arq's own two warnings into the one `alert()`. That is a call site, not a mechanism: it
stores nothing and touches neither Postgres nor Redis, which is what keeps it working on
the night the thing it is reporting is the queue.

Building a real DLQ was weighed and is not what P6.5 asked for: it would mean a second
durable store for failures beside the outbox we already have, and "one way per problem"
says the answer is to make the nine jobs alert rather than to add a tenth mechanism. The
one thing a DLQ would have bought that per-job alerting does not is REPLAY, and the jobs
here are crons — the next tick is the replay.

**Tolerant boot** (BACKEND-PATTERNS §2): workers hard-require only DB + Redis. A
missing provider key must NOT crash-loop every queue — the extractor falls back to the
offline implementation and completeness is reported at `/healthz/ready` instead. A
worker that refuses to start because Sarvam is unconfigured takes down recording
copies and metering too, which is a far worse failure than degraded extraction.
"""

import asyncio
import logging
import sys
from contextlib import suppress
from typing import Any

# Must run before arq creates its loop. Same policy as tests/conftest.py.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from arq import cron

from apps.api.core.alert_admission import close_admission
from apps.api.core.alerting import alert
from apps.api.core.fx import fx_scope
from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.observability import (
    init_observability,
    shutdown_tracing,
    traced_job,
    tracing_enabled,
)
from apps.api.core.queue import WORKER_MAX_TRIES, close_queue, redis_settings
from apps.api.core.redis import close_redis
from apps.api.core.settings import (
    runtime_config_missing_keys,
    settings_scope,
    validate_bootstrap_env,
)
from apps.api.ops.fx_rates import start_fx_refresher, stop_fx_refresher
from apps.workers.account_closure import notify_account_closed, sweep_due_erasures
from apps.workers.action_audit import record_action_invocation
from apps.workers.auth_email import deliver_auth_email
from apps.workers.billing import issue_one_time_charges
from apps.workers.callbacks import book_requested_callback, cancel_requested_callback
from apps.workers.caller_embeddings import CALLER_EMBED_MINUTES, embed_caller_chunks
from apps.workers.caller_memory_distil import (
    DISTIL_MINUTE as CALLER_MEMORY_DISTIL_MINUTE,
)
from apps.workers.caller_memory_distil import (
    distil_caller_memories,
)
from apps.workers.campaign_dispatch import TICK_SECONDS, dispatch_campaign_tick
from apps.workers.copilot_memory import DISTILL_MINUTE, distil_copilot_memories
from apps.workers.dial_recall import recall_queued_dials
from apps.workers.dispatcher import (
    ERASURE_PROBE_MINUTE,
    dispatch_outbox,
    report_overdue_erasures,
    report_stalled_pipeline,
    sweep_expired,
)
from apps.workers.dnc_recall import recall_dials_for_dnc
from apps.workers.engine_reconciliation import SWEEP_MINUTES, sweep_engine_drift
from apps.workers.engine_violations import SWEEP_MINUTE, sweep_engine_violations
from apps.workers.fx_pull import PULL_MINUTES, pull_fx_rate
from apps.workers.handoff import record_handoff_started
from apps.workers.kb_aggregation import (
    DIGEST_HOUR,
    DIGEST_MINUTE,
    DIGEST_WEEKDAY,
    send_agent_knowledge_digests,
)
from apps.workers.kb_embeddings import EMBED_MINUTES, embed_knowledge_chunks
from apps.workers.kb_gloss import GLOSS_MINUTES, write_knowledge_glosses
from apps.workers.kb_ingest import SWEEP_MINUTES as KB_UPLOAD_SWEEP_MINUTES
from apps.workers.kb_ingest import ingest_kb_source, sweep_kb_uploads
from apps.workers.kb_orphans import ORPHAN_SWEEP_HOUR, ORPHAN_SWEEP_MINUTE, sweep_kb_orphans
from apps.workers.kb_reconciliation import KB_SWEEP_MINUTES, sweep_kb_drift
from apps.workers.notifications import notify_hot_lead
from apps.workers.optout import record_in_call_optout
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.pipeline import (
    ingest_engine_event,
    reconcile_executions,
    reconcile_outstanding_calls,
    run_post_call_pipeline,
)
from apps.workers.qa_sampling import draw_qa_samples
from apps.workers.retention import (
    apply_retention,
    execute_deletion_request,
    execute_tenant_erasure,
    prune_reliability_tables,
)
from apps.workers.tls_expiry import check_tls_expiry
from apps.workers.topup_settlement import SETTLEMENT_MINUTES, sweep_topup_settlement
from apps.workers.wallet_alerts import notify_low_balance
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
        # `scripts/check_job_wiring.py` is the gate now (D-199) and it derives the
        # three-way agreement rather than reading a list; this pair is why it exists.
        notify_hot_lead_whatsapp,
        escalate_campaign_contact,
        # Hard rule 5's fast half: voice-runtime acks the engine's opt-out tool call and
        # queues this. Unregistered, the caller's request would be acked to the vendor,
        # dropped by arq, and only recovered by the post-call transcript pass minutes
        # later — the exact silent-degradation shape `check_job_wiring` guards.
        record_in_call_optout,
        # ACTIONS feature. The in-call/after-call action executor acks the caller fast and
        # queues the audit row here (hard rule 3 — no DB write on the tool path). An
        # unregistered name would DLQ every action's audit while the tool itself succeeded,
        # leaving invocations unlogged — the `check_job_wiring` shape.
        record_action_invocation,
        # D-170. Every one-time secret `apps/api/authn` mints is delivered by this job, so
        # an unregistered one means a reset link that is promised, queued, DLQ'd and never
        # sent — while the sign-in screen truthfully reports that an email was on its way.
        deliver_auth_email,
        # D-432. The big red switch's recall arm. Fired on the halt EDGE by
        # `ops/routes.set_platform`, not cronned — an unregistered one means the switch
        # reports outbound stopped while every dial the vendor already accepted rings on,
        # which is the `check_job_wiring` shape 3 failure on the one control an operator
        # throws when something is going wrong.
        recall_queued_dials,
        # D-428(b), the recall's other arm and the one with a regulator behind it.
        # Published by the outbox in the same transaction as a `dnc_list` insert, so an
        # unregistered name here does not read as a dormant feature: arq accepts the
        # enqueue, the outbox row says `published`, `Worker.run_job` drops it with a
        # warning nothing reads — and the suppression is honoured for the next dispatch
        # tick while the dials already queued at the vendor ring anyway, with every screen
        # reporting the number suppressed.
        recall_dials_for_dnc,
        # D-514. The in-call call-back pair. voice-runtime acks the caller in
        # milliseconds and queues one of these; unregistered, the agent has told somebody
        # on the phone "I have booked that for Tuesday at four", arq drops the name, the
        # row walks into the DLQ and NOTHING ELSE recovers it — there is no post-call pass
        # behind a call-back the way there is behind an opt-out. That is the sharpest
        # version of the `check_job_wiring` shape in this list: a promise made to a person.
        book_requested_callback,
        cancel_requested_callback,
        # D-533. The mid-call notice that a caller is being handed to a person. Same shape
        # as the pair above and with one difference that makes it worse, not better: the
        # engine has ALREADY started placing the leg by the time this fires — the webhook
        # is fire-and-forget and nothing we do can stop it — so an unregistered name here
        # does not merely lose a promise, it loses the only record that a client's caller
        # was put through to a member of their staff at all. The `handoff_attempts` row,
        # the brief and the call-back for a handover nobody answered all hang off it.
        record_handoff_started,
        # THE EMPTY-WALLET WARNING (2 Sep 2026). Published by `billing.service.record_entry`
        # in the same transaction as the ledger entry that crossed the line, so an
        # unregistered name here is not a dormant feature: the outbox marks the row
        # `published`, arq drops the job with a warning nothing reads, and a client's
        # outgoing calls stop with no notice at all — which is precisely the founder's
        # stated failure ("a client whose phone stops being answered because a top-up
        # lapsed is a client who leaves"). `check_job_wiring` shape 3.
        notify_low_balance,
        # D-534. The upload lane's one job: read a client's document into text, approve it
        # if its submitter could, and publish it to the voice platform. Enqueued through
        # the OUTBOX in the same transaction as the `kb_uploads` row, so an unregistered
        # name here is the `check_job_wiring` shape 3 failure with a screen behind it — the
        # outbox marks the row published, arq drops the job with a warning nothing reads,
        # and the client watches an upload sit at "received" for ever while every one of
        # our screens reports it as queued.
        ingest_kb_source,
        # D-536. Queued in the SAME transaction as the closure it announces, so a client
        # is never told about a closure that rolled back and a closure never commits with
        # nobody told. Registered here because an unregistered job name is a DLQ
        # generator — `tests/job_registration_test.py` is what makes that a failing test
        # rather than a silent one.
        notify_account_closed,
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
    #
    # `max_tries` EXPLICIT, for its neighbours' reason and with the sharpest version of
    # it (R-4): `cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does not
    # reach a function carrying its own, so this job — the ONLY mechanism that recovers a
    # webhook Bolna never delivered — was finished on its first attempt by any error the
    # tick met, including a container swap cancelling it mid-sweep. The sweep itself now
    # isolates per execution, so what reaches this ladder is the tick-wide failure (the
    # engine listing, Redis, the pool) rather than one tenant's, and re-running it is free:
    # every re-drive is enqueued under a fixed `job_id_for(..., "reconcile")`, so a retried
    # tick cannot double-drive an execution the previous attempt already queued.
    cron(
        traced_job(reconcile_executions),
        minute={0, 10, 20, 30, 40, 50},
        run_at_startup=True,
        max_tries=WORKER_MAX_TRIES,
    ),
    # `max_tries` here too, though this one DOES self-heal on its next tick 30 minutes
    # later: the alarm's whole job is to notice that the pipeline is late, and an alarm
    # that gives up on its first transient database error is silent for exactly as long
    # as the incident it exists to report. Half an hour of that is not free.
    cron(traced_job(report_stalled_pipeline), minute={5, 35}, max_tries=WORKER_MAX_TRIES),
    # THE COPILOT'S SEMANTIC DISTILLATION (migration d4a9c17e6b02). Hourly at :25, which is
    # clear of the poller (:00/:10/...), `report_stalled_pipeline` (:05/:35) and
    # `reconcile_outstanding_calls` (:15/:45), so no two O(tenants) fan-outs share a minute.
    #
    # A CRON AND NOT AN ENQUEUE, deliberately: an enqueue per copilot turn would be a paid
    # model call per turn, which is the cost this whole job exists to keep OFF the live
    # path. `copilot_memory.MAX_GROUPS_PER_TICK` times 24 is therefore the most calls this
    # feature can make in a day, and the cadence IS the spend rate.
    #
    # `max_tries` EXPLICIT for its neighbours' reason — `cron()` defaults it to 1 and
    # `WorkerSettings.max_tries` does not reach a function carrying its own. Retrying is
    # safe: the job is idempotent on `copilot_memories.distilled_at`, stamped in the same
    # transaction as the rows it produced, so a re-run finds nothing rather than paying
    # twice for the same conversation.
    cron(
        traced_job(distil_copilot_memories),
        minute={DISTILL_MINUTE},
        max_tries=WORKER_MAX_TRIES,
    ),
    # CROSS-CALL MEMORY: what a finished call taught us about the PERSON who rang (D-513).
    # Hourly at :50, clear of every other O(tenants) fan-out in this list, and the ceiling
    # (`caller_memory_distil.MAX_CALLS_PER_TICK`) is per tick — so the cadence IS the spend
    # rate, exactly as for its sibling above.
    #
    # IT COSTS NOTHING ON A DEPLOYMENT WHERE NOBODY HAS SWITCHED THE FEATURE ON, which is
    # every deployment by default: discovery starts from `agents.caller_memory_enabled`, so
    # a fleet with the switch everywhere off makes zero model calls and the tick is one
    # indexed read per tenant.
    #
    # `max_tries` EXPLICIT for its neighbours' reason. Retrying is safe: the job is
    # idempotent on `calls.caller_memory_state`, stamped in the same transaction as the
    # memory rows it produced, so a re-run finds nothing rather than paying twice for the
    # same conversation — and the state carries the "read it, owed nothing" answer that a
    # `source_call_id` alone could not express.
    cron(
        traced_job(distil_caller_memories),
        minute={CALLER_MEMORY_DISTIL_MINUTE},
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE OTHER HALF OF THE GUARANTEE (D-242). `reconcile_executions` above can only see
    # what `list_executions` returns, and that listing is filtered on when an execution
    # was CREATED — so a call that runs longer than the 30-minute window has fallen out of
    # it before its terminal transition ever happens, and one webhook lost past whatever
    # unbounded retry the vendor makes of it (`api-reference/limits.md:61`) left it
    # unrecoverable. This asks the engine directly about every call row still
    # non-terminal past the stall window.
    #
    # HALF-HOURLY, AND OFFSET. It is O(tenants) — `calls` is FORCE-RLS'd, so the question
    # can only be asked one tenant session at a time — which is why it is not a second
    # phase of the 10-minute tick: the common case (a short call whose webhook was lost)
    # is already covered there within ten minutes, and this population has been unfinished
    # for longer than the stall window by definition. :15/:45 keeps it clear of the poller
    # (:00/:10/...) and of `report_stalled_pipeline` (:05/:35), so the three fleet-wide
    # fan-outs never run in the same minute.
    #
    # `max_tries` EXPLICIT for its neighbours' reason: `cron()` defaults it to 1 and
    # `WorkerSettings.max_tries` does not reach a function carrying its own, so a sweep
    # that met one transient database error would be finished for the half hour.
    cron(
        traced_job(reconcile_outstanding_calls),
        minute={15, 45},
        max_tries=WORKER_MAX_TRIES,
    ),
    # The DPDP §12 equivalent of the line above, and the reason it exists is that there
    # WAS no equivalent: an erasure request whose job was lost to a deploy sat open
    # forever with nothing watching (P6.5). Hourly rather than half-hourly because
    # `ERASURE_OVERDUE_AFTER` is an hour — a tighter cadence would re-report the same
    # request without shortening the time to notice it.
    #
    # `max_tries` for its neighbour's reason, and more sharply: unlike the pipeline
    # stall, this condition CANNOT self-heal between ticks. `execute_deletion_request`
    # is enqueued once, in the request's own transaction, with no poller behind it — so
    # the alarm going quiet on a transient database error is the whole failure, not a
    # delay in reporting it.
    #
    # THE MINUTE COMES FROM THE MODULE (`ERASURE_PROBE_MINUTE`) and is no longer :25,
    # which is `DISTILL_MINUTE`: the two heaviest hourly fan-outs were starting together
    # every hour, and this one has a wall-clock budget that a neighbour competing for the
    # pool spends on waiting. `dispatcher.ERASURE_PROBE_MINUTE` carries the argument and
    # `tests/job_registration_test.py` is the guard that keeps it true.
    cron(
        traced_job(report_overdue_erasures),
        minute={ERASURE_PROBE_MINUTE},
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE FIVE-MINUTE FX PULL. The rate every dollar of vendor cost is converted at, kept
    # current without a restart (`apps/workers/fx_pull.py` argues the source, the cadence
    # and the failure ladder). Registered from the job's own `PULL_MINUTES` so the schedule
    # and its argument cannot drift.
    #
    # `run_at_startup` is deliberately NOT set. The rate is not needed to boot — a process
    # with no published rate converts at the configured fallback, which is what it did
    # before this job existed — and a deploy of N workers would otherwise fire N
    # simultaneous requests at a third party for one number none of them urgently needs.
    #
    # `max_tries` EXPLICIT for the reason its neighbours give: `cron()` defaults it to 1
    # and `WorkerSettings.max_tries` does not reach a function carrying its own. A pull
    # that gave up on its first transient failure would be silent for five minutes, which
    # is survivable — but the ladder is also what makes the LAST attempt's `alert()`
    # reachable, and that alert is the only dead-letter this queue has.
    cron(traced_job(pull_fx_rate), minute=set(PULL_MINUTES), max_tries=WORKER_MAX_TRIES),
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
    # `max_tries` for `apply_retention`'s reason, and it is the same class of job: the
    # other half of the retention obligation, on the same nightly cadence, with the same
    # "gone until tomorrow" failure mode and no next tick to self-heal on.
    cron(traced_job(sweep_expired), hour={3}, minute={17}, max_tries=WORKER_MAX_TRIES),
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
    # THE WEEKLY KNOWLEDGE DIGEST. What callers asked, as counts drawn from our own closed
    # enums and the client's own extraction schema — never from a transcript
    # (`apps/api/kb/patterns.py` is the guard and carries the argument).
    #
    # Monday morning, and the schedule does NOT decide which week is summarised: arq
    # evaluates cron fields in the WORKER's timezone, so `kb_aggregation.closed_week`
    # converts the firing instant to IST and only ever asks for the seven days that have
    # already closed. The same separation `draw_qa_samples` above makes, for the same
    # reason.
    #
    # `max_tries` EXPLICIT for its neighbours' reason: `cron()` defaults it to 1 and
    # `WorkerSettings.max_tries` does not reach a function carrying its own. This one is
    # weekly, so a tick finished by its first transient error is not a job that self-heals
    # in half an hour — it is a week in which no client heard anything.
    cron(
        traced_job(send_agent_knowledge_digests),
        weekday={DIGEST_WEEKDAY},
        hour={DIGEST_HOUR},
        minute={DIGEST_MINUTE},
        max_tries=WORKER_MAX_TRIES,
    ),
    # OPERATIONS §4's cert-expiry alarm. DAILY and not hourly: the quantity it measures
    # moves once a day, and certbot's own renewal timer runs twice a day — a check that
    # ran more often would only re-discover the same number and spend the alert path's
    # dedupe window on it. 04:05, after the nightly retention jobs have finished with the
    # database and well before anybody would act on the result.
    #
    # `max_tries` EXPLICIT for the reason its neighbours give: `cron()` defaults it to 1.
    # This job is idempotent to the point of being read-only — one TLS handshake — so a
    # retried attempt costs nothing and a lost one costs a day of not knowing.
    cron(traced_job(check_tls_expiry), hour={4}, minute={5}, max_tries=WORKER_MAX_TRIES),
    # Retention is a legal obligation, not a cleanup task: without this the
    # policies we promise in the DPA are only a table (SEC-COMP §4).
    #
    # `max_tries` EXPLICIT, and the omission this corrects (P6.2) mattered more here than
    # on any of its neighbours — `cron()` defaults it to 1, `WorkerSettings.max_tries`
    # does not reach a function carrying its own, and the neighbours above and below make
    # this exact argument four times while the one job that is a LEGAL obligation went
    # without. Two ways it bit: a container swap cancels the in-flight job, which requeues
    # and then fails its pickup with `job_try=2 > 1`; and any error inside the sweep
    # finished the job on its first attempt. The other four crons that failed this way
    # self-heal on their next tick. This one and `sweep_expired` are gone until tomorrow,
    # which is a night's expired recordings, transcripts and leads still held — so
    # `apply_retention` also alerts on a non-zero failure count now, because a retry
    # ladder that runs out still has to tell somebody.
    cron(traced_job(apply_retention), hour={3}, minute={40}, max_tries=WORKER_MAX_TRIES),
    # D-536. HOURLY, at :25 so it does not land on the same minute as the fleet's other
    # sweeps. The grace window is a PROMISE WITH A DATE ON IT and it has to hold in both
    # directions: an account must not be erased before the date the client was given, and
    # a client who asked us to erase now (`bring_erasure_forward`) must not wait until
    # 03:40 for a deadline they set for this afternoon. An hour is the coarsest tick that
    # keeps "erased on the date we told you" true either way.
    #
    # `max_tries` EXPLICIT for its neighbours' reason: `cron()` defaults it to 1 and
    # `WorkerSettings.max_tries` does not reach a function carrying its own. The next tick
    # IS a sufficient retry here — the sweep is a re-readable query over a durable column
    # and `request_tenant_erasure` dedupes on the open request — but an hour of an
    # overdue erasure is an hour past a date we published to a client, so the ladder runs
    # first and the tick is the backstop rather than the only recovery.
    cron(
        traced_job(sweep_due_erasures),
        minute={25},
        max_tries=WORKER_MAX_TRIES,
    ),
    # The two infra tables `apply_retention` structurally cannot reach, because neither
    # has a `tenant_id` to sweep inside (P6.7). Until this existed nothing anywhere
    # deleted a row from `outbox_messages` or `webhook_inbox_events` — an unbounded copy
    # of lead names, numbers and call summaries sitting outside every retention policy a
    # tenant can set. AFTER `apply_retention` and not before: an outbox row is the
    # promise of a side effect, and pruning promises before the sweep that may still be
    # making them is an ordering nobody would be able to reason about at 03:00.
    # `max_tries` EXPLICIT for the reason its neighbour above spells out at length.
    cron(
        traced_job(prune_reliability_tables),
        hour={4},
        minute={10},
        max_tries=WORKER_MAX_TRIES,
    ),
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
    # THE KNOWLEDGE DRIFT SWEEP (D-158). The same gap on the other object: our only read of
    # what the engine is HOLDING (`kb/service._reconcile_engine_state`) runs at publish
    # time, and a knowledge base is the thing in this system with the longest gap between
    # publishes — so a source edited in the vendor's dashboard, or a publish that committed
    # there and rolled back here, stayed invisible for months rather than minutes.
    #
    # HOURLY rather than the agent sweep's half-hourly, and 15 agents rather than 25,
    # sized against the dearest round trip the PORT allows — an engine whose `list_kb`
    # pulls the whole account's knowledge list and filters it on our side. That is no
    # longer what the primary adapter does (D-488: it reads the agent's own `vector_ids`,
    # one GET, the same price as the agent sweep's), and the bound is deliberately NOT
    # loosened for it: the next adapter may be the dear kind, and a limit relaxed to fit
    # today's cheapest engine is a limit discovered in production by tomorrow's.
    # `apps/workers/kb_reconciliation.py`
    # carries the arithmetic and asserts at import that a tick's worst case fits inside the
    # interval, which is what lets it skip the Redis lease the campaign tick needs —
    # `minute` therefore comes FROM the module, because two places writing "hourly" is how
    # that assertion stops being true.
    #
    # `max_tries` EXPLICIT, the reason `issue_one_time_charges` states below: `cron()`
    # defaults it to 1, so a sweep that gave up on its first failure would leave every
    # client's published knowledge unwatched with the console still green.
    cron(
        traced_job(sweep_kb_drift),
        minute=set(KB_SWEEP_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE ACCOUNT-LEVEL KNOWLEDGE SWEEP (D-519), and it is the sweep above's blind spot
    # rather than a duplicate of it. That one reads what an AGENT references and therefore
    # cannot see an object no agent references — which is what every failure in this
    # feature leaves behind, on an account shared by every tenant, holding a client's
    # uploaded document with nothing at the vendor saying whose it is.
    #
    # DAILY rather than hourly, and one vendor call per tick. `list_account_kb` walks an
    # account-wide listing that grows with every source every client has ever published —
    # the dearest read in the adapter, and the one the drift sweep's batch size exists to
    # avoid making per agent. The residue it finds is made by crashes and by hand; none of
    # its verdicts becomes more actionable for being eight hours fresher.
    #
    # 04:40 because the hours around it are taken (03:17 expiry, 03:40 retention, 04:05
    # the TLS probe, :23 of every hour the KB drift sweep), and `hour`/`minute` come FROM
    # the module for its neighbours' reason.
    #
    # `max_tries` EXPLICIT: `cron()` defaults it to 1, and the failure this job is most
    # likely to suffer is a slow vendor listing — precisely the one that must not be
    # allowed to mean "nothing to report until tomorrow".
    cron(
        traced_job(sweep_kb_orphans),
        hour=set(ORPHAN_SWEEP_HOUR),
        minute=set(ORPHAN_SWEEP_MINUTE),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE ENGLISH GLOSS SWEEP. Not a drift sweep — it is INGESTION, finishing a chunk that
    # arrived without the one derived field retrieval needs. `apps/workers/kb_gloss.py`
    # carries the measurement: a Tenglish question (the form Saaras returns, so the form
    # production actually produces) retrieves a Telugu-script chunk at recall@1 0.250
    # unaided and 0.750 with the gloss, and on this repo's token-overlap ranker it retrieves
    # nothing at all. An unregistered cron here is not a dormant feature: every chunk stays
    # `pending` forever, `search_knowledge` silently keeps answering nothing to half its
    # questions, and the column reads as shipped in every review.
    #
    # `minute` comes FROM the module for its neighbours' reason — two places writing "twice
    # hourly" is how the module's own clearance argument stops being true. `max_tries`
    # EXPLICIT because `cron()` defaults it to 1 and `WorkerSettings.max_tries` does not
    # reach a function registered here; the tick's own failure is a worklist read, which is
    # exactly the kind a retry fixes.
    cron(
        traced_job(write_knowledge_glosses),
        minute=set(GLOSS_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE UPLOAD SWEEP (D-534), and it is two jobs that are one job seen twice: re-drive an
    # ingestion that stalled, and re-read a client's LINK to see whether the page still
    # says what they approved. Both walk `kb_uploads` asking "does this row still reflect
    # reality", which is why they share a tick rather than a second registration.
    #
    # It is the self-healing half of the feature, and the states it exists for are ordinary
    # rather than exotic: an upload that landed before the client had published their agent
    # (nowhere to put the knowledge yet), a worker restarted mid-publish, and a menu page
    # the client's web designer edited without telling anybody. Without it each of those is
    # a row that sits at `received` for ever with a screen saying "processing".
    #
    # `minute` comes FROM the module for its neighbours' reason, and `max_tries` is
    # EXPLICIT because `cron()` defaults it to 1 — a sweep that gave up on its first
    # failure would leave every stalled upload unattended until somebody noticed.
    cron(
        traced_job(sweep_kb_uploads),
        minute=set(KB_UPLOAD_SWEEP_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE EMBEDDING SWEEP (D-502). The gloss sweep's sibling on the same table and the
    # second half of ingestion: the publish transaction writes `kb_chunks.tsv`, this buys
    # the vector beside it. An unregistered cron here is not a dormant feature — every
    # published chunk stays `pending` for ever, the dashboard's knowledge search answers
    # from its keyword arm alone while every screen reports a hybrid store, and the column
    # reads as shipped in review. It runs AFTER the gloss in the same half-hour (:08 against
    # :12) and skips chunks whose gloss is still pending, so a Telugu chunk is embedded with
    # its English retrieval key rather than without it.
    #
    # `minute` comes FROM the module for its neighbours' reason — two places writing "twice
    # hourly" is how the module's own clearance argument stops being true. `max_tries`
    # EXPLICIT because `cron()` defaults it to 1 and `WorkerSettings.max_tries` does not
    # reach a function registered here; the tick's own failure is a worklist read, which is
    # exactly the kind a retry fixes.
    cron(
        traced_job(embed_knowledge_chunks),
        minute=set(EMBED_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE CALLER-DATA INGESTION SWEEP (D-503) — the same job one corpus over: it projects
    # what a client's CALLERS said into `caller_chunks` and buys the vector beside it. An
    # unregistered cron here is not a dormant feature but a broken one that reads as shipped:
    # every projection stays `pending` for ever, the CRM and transcript search screens answer
    # from their keyword arm alone while every surface reports a hybrid store, and nothing
    # anywhere says so.
    #
    # `minute` comes FROM the module for its neighbours' reason — two places writing "twice
    # hourly" is how the module's own clearance argument (:13 and :43 are the last minutes no
    # other O(tenants) fan-out uses) stops being true. `max_tries` EXPLICIT because `cron()`
    # defaults it to 1 and `WorkerSettings.max_tries` does not reach a function registered
    # here; the tick's own failure is a worklist read, which is exactly the kind a retry fixes.
    cron(
        traced_job(embed_caller_chunks),
        minute=set(CALLER_EMBED_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
    # THE COMPLIANCE-FLAG SWEEP. The third drift-shaped gap and the one with a regulator
    # behind it: Bolna raises VIOLATIONS against the account we place every regulated
    # Indian call through, publishes them on a list endpoint, and pushes nothing — so
    # until this cron existed the channel was silent and the first notice would have been
    # enforcement (`docs/evidence/bolna-compliance-residency.md` §1).
    #
    # `minute` comes FROM the module for its neighbours' reason. HOURLY at :50: no
    # deadline is documented on any vendor page, so there is no interval to derive — an
    # hour keeps time-to-notice short on an obligation whose remedy is a human action
    # anyway, and :50 is the one slot the other fleet-wide fan-outs leave free.
    #
    # `max_tries` EXPLICIT, the reason its neighbours give: `cron()` defaults it to 1, and
    # a sweep that gave up on its first vendor blip would leave a compliance obligation
    # unwatched for the hour with every screen green.
    cron(
        traced_job(sweep_engine_violations),
        minute={SWEEP_MINUTE},
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
    # THE PAYMENT WEBHOOK THAT NEVER ARRIVES. Every other alarm on the top-up path fires
    # from inside the webhook handler and therefore needs the delivery to reach us first;
    # a webhook registered against the wrong hostname trips none of them, and the first
    # notice was the client saying they had paid. This sweep is the only reader of
    # `topup_attempts` that pages anybody (`apps/workers/topup_settlement.py` carries the
    # whole argument, including why it cannot reconcile against the provider).
    #
    # `max_tries` EXPLICIT for its neighbours' reason: `cron()` defaults it to 1, and a
    # money watch that gave up on its first database blip would leave every payment
    # unwatched for the half-hour with every screen green.
    cron(
        traced_job(sweep_topup_settlement),
        minute=set(SETTLEMENT_MINUTES),
        max_tries=WORKER_MAX_TRIES,
    ),
]


#: The two ways arq itself ends a job WITHOUT the job's own code running, mapped to the
#: alert code an operator would search for. Keyed by the LOGGING FORMAT STRING rather than
#: by the rendered message, because the format string is a literal in arq's source: it
#: cannot be spoofed by a job id and it does not shift when the arguments do.
#:
#: WHY THIS EXISTS AT ALL. The docstring at the top of this file establishes that the
#: alert on exhaustion is a property of each JOB, not of the queue — and that is right for
#: every path where the job's code is running. These two are the paths where it is NOT:
#:
#:   * `function ... not found` — an enqueue for a name no worker registers. arq accepts
#:     the enqueue, then drops the job with a warning. The job's own code never executes,
#:     so no per-job `alert()` can possibly fire. `scripts/check_job_wiring.py` is the
#:     static gate that stops this shipping; this is the runtime backstop for the case it
#:     structurally cannot see — a producer deployed against a worker that has not been
#:     restarted yet.
#:   * `max N retries exceeded` — the ladder ran out, and arq refuses the pickup BEFORE
#:     calling the function (`Worker.run_job` checks `job_try > max_tries` first, and does
#:     not run `on_job_start`/`on_job_end` on that path). Every job that raises `Retry`
#:     until its last attempt therefore has a terminal state its own code cannot alert
#:     from, and a cron cancelled at `job_timeout` — which arq requeues as a retry — walks
#:     straight into it. That is `apply_retention` gone until tomorrow in silence, which
#:     is the exact failure P6.2 fixed from the other direction.
#:
#: NOT a second DLQ, and not a second alert path: it is one more CALL SITE of the one
#: `alert()` (BACKEND-PATTERNS §8). It stores nothing, reads nothing and touches neither
#: Postgres nor Redis, which is the property that keeps it working on the night the thing
#: it is reporting is the queue.
ARQ_TERMINAL_MESSAGES: dict[str, str] = {
    "job %s, function %r not found": "job_function_not_registered",
    "%6.2fs ! %s max retries %d exceeded": "job_retries_exhausted",
}

#: How much of arq's rendered message rides the alert. Bounded because the message
#: interpolates a job id, and a job id is `"<job>:<natural key>"` — ids only by
#: construction (`core/queue.job_id_for`), but an alert body is forwarded further than a
#: log line is and a bound costs nothing (hard rule 6).
_ARQ_DETAIL_CHARS = 200


class _ArqTerminalFailureAlerter(logging.Handler):
    """Turn arq's own terminal-failure warnings into alerts.

    A `logging.Handler` rather than a fork of arq or a poll of Redis job keys, because
    arq offers no hook on either path and the warning is the only signal it emits. The
    handler matches on `record.msg` — the unformatted template — so it reads arq's
    intent rather than grepping a rendered string; `tests/worker_terminal_alert_test.py`
    pins both templates against the installed `arq.worker` source, so an upgrade that
    rewords them fails the build instead of silently unhooking this.
    """

    def emit(self, record: logging.LogRecord) -> None:
        code = ARQ_TERMINAL_MESSAGES.get(str(record.msg))
        if code is None:
            return
        # `alert()` never raises (its own contract), so nothing here can turn a logging
        # call inside arq's exception handling into a second failure.
        alert("WORKER_TERMINAL", code, detail=record.getMessage()[:_ARQ_DETAIL_CHARS])


def install_arq_terminal_alerter(logger_name: str = "arq.worker") -> bool:
    """Attach the handler once. Returns whether it was newly attached.

    Idempotent because `startup` runs per worker process and a test may call it too; two
    handlers would double every alert, which is how a real signal starts getting muted by
    the operator it is for.
    """
    target = logging.getLogger(logger_name)
    if any(isinstance(handler, _ArqTerminalFailureAlerter) for handler in target.handlers):
        return False
    target.addHandler(_ArqTerminalFailureAlerter(level=logging.WARNING))
    return True


async def startup(ctx: dict[str, Any]) -> None:
    validate_bootstrap_env()
    configure_logging()
    # AFTER `configure_logging`, so the handler is added to the logger tree that is
    # actually in use rather than to one a later reconfiguration replaces.
    install_arq_terminal_alerter()
    # The worker has no `create_app`, so bootstrap step 3 happens here instead — and it
    # must, because the worker is the CONSUMER side of the trace. If only the API
    # initialised tracing, every enqueued traceparent would arrive at a process with no
    # provider and the call's trace would end at Redis.
    observability = init_observability("workers")
    # THE WORKER IS WHERE A CALL'S COST IS CONVERTED (`pipeline._meter`), so it is the
    # process that most needs the published rate — an API that never meters a call would
    # be the wrong one to give it to. One line, idempotent, and a worker that did not call
    # it converts at the configured `usd_inr_rate` exactly as it did before this feature
    # existed: `start_config_refresher`'s adoption contract, applied to the FX store.
    start_fx_refresher()
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
#: The same, for the published FX rate. A SECOND pin rather than a field of the first,
#: because the two values come from different stores and refresh on different clocks —
#: `Settings` from `platform_settings` on the config sentinel, the rate from
#: `fx_rate_observations` on its own poll — and folding one into the other would mean a
#: config change silently re-resolving the rate, or the reverse.
_FX_SCOPE_KEY = "_fx_pin"


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
    # THE RATE IS PINNED THE SAME WAY AND FOR A SHARPER VERSION OF THE SAME REASON. The
    # post-call pipeline fetches an execution (converting its cost) and then writes the
    # usage rows; the FX poll refreshes every 60 seconds underneath. Unpinned, a job that
    # straddled a refresh could convert a call's legs at one rate and re-read another for
    # anything computed later — a call billed at two rates, in an append-only ledger, off
    # by a few paise nobody would ever chase. `fx_scope()` resolves once, INCLUDING the
    # staleness decision, so a job that opened on a fresh rate finishes on it.
    fx = fx_scope()
    fx.__enter__()
    ctx[_FX_SCOPE_KEY] = fx


async def on_job_end(ctx: dict[str, Any]) -> None:
    """Release the pin. Runs even when the job raised — arq calls this either way, which
    is what stops a failed job leaking its pin into whatever the worker runs next."""
    # Innermost first, and each independently: a raising `__exit__` on one must not leak
    # the other into whatever this worker runs next.
    fx = ctx.pop(_FX_SCOPE_KEY, None)
    if fx is not None:
        fx.__exit__(None, None, None)
    scope = ctx.pop(_SCOPE_KEY, None)
    if scope is not None:
        scope.__exit__(None, None, None)


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_stop")
    # THE POOL TEARDOWN THE `job_completion_wait` COMMENT BELOW ALREADY BUDGETS FOR.
    # It said fifteen seconds of headroom "covers the `on_shutdown` hook, the tracing
    # flush and the pool teardown that all run AFTER the drain" while this hook tore
    # down nothing: arq closes its OWN worker pool, but the three clients a JOB opens
    # are ours — `core/queue._pool` (a job enqueueing another job), `core/redis._client`
    # (load-shed, dedupe, rate limits) and `core/alert_admission._client` (the shared
    # suppression window). All three outlived every drain.
    #
    # Independently and best-effort, in the API's order, for the API's reason: a socket
    # that is already gone is the commonest way each is reached, and none of them may
    # cost the tracing flush that follows.
    # The FX poll first: it is the only one of these that holds a database session, and a
    # poll still running while the pool it borrows from is torn down logs a failure that
    # reads like a real one.
    with suppress(Exception):
        await stop_fx_refresher()
    with suppress(Exception):
        await close_redis()
    with suppress(Exception):
        await close_queue()
    with suppress(Exception):
        close_admission()
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
    # DRAIN ON SIGTERM RATHER THAN HARD-CANCEL, and until this line existed three
    # documents said we did while the code did the opposite (P6.1).
    #
    # arq selects its signal handler on the TRUTHINESS of this value: `0` — the default,
    # and what this class carried — installs `handle_sig`, which cancels every in-flight
    # job task in the first millisecond of SIGTERM. Any non-zero value installs
    # `handle_sig_wait_for_completion`, which awaits the running tasks and cancels only
    # what is still going at the deadline. So `compose.prod.yml`'s 60-second
    # `stop_grace_period`, `docs/DEPLOYMENT.md` §4b's "in-flight work finishes instead of
    # being killed" and BACKEND-PATTERNS §10's "drain-then-quit shutdown" were all
    # describing a process that had already thrown its work away.
    #
    # WHY 45 AND NOT 60. It has to be strictly UNDER the compose grace, because that
    # grace ends in SIGKILL: a drain window equal to it would be racing the kill and a
    # drain window longer than it would be cancelled by one. Fifteen seconds of headroom
    # covers the `on_shutdown` hook, the tracing flush and the pool teardown that all run
    # AFTER the drain. `tests/worker_reliability_test.py::
    # test_the_drain_window_fits_inside_the_grace_docker_gives_it` pins the relationship
    # by PARSING the compose file rather than trusting this paragraph — the same shape
    # `dispatch_tick_lease_test` uses for `job_timeout < TICK_LEASE_TTL_S`. (This named
    # `tests/worker_drain_test.py`, which does not exist and never did: the check was
    # written into the reliability suite when D-182 widened it from `workers` alone to
    # all three long-lived services, and the reference was left behind. A comment
    # pointing at an absent guard reads exactly like the guard that was promised and
    # never written next door in `auth_email.py` — which is why the file and the test
    # are both named here, so a grep either lands or fails loudly.)
    #
    # WHY NOT `job_timeout` (300). A job that has run for five minutes is not going to
    # finish in the grace window either, and sizing the drain to the slowest possible job
    # would mean every deploy waits for SIGKILL. The `FUNCTIONS` jobs are idempotent and
    # re-queue; what this window is actually FOR is the crons, which do not — a cancelled
    # `apply_retention` requeues, fails its pickup with `job_try > max_tries`, and is gone
    # until tomorrow, which is a legal obligation skipped in silence because a deploy
    # happened at 03:40 UTC.
    #
    # NO COUNT HERE, DELIBERATELY. This said "the nine `FUNCTIONS` jobs" and "the six
    # `max_tries=1` crons"; there are ten of the first and two of the second, and
    # `apply_retention` — the example the sentence was BUILT on — has carried a ladder
    # since P6.2. A count in prose is the defect class hard rule 4 names, and the two
    # populations are enumerated where they are declared. Which crons legitimately run
    # with one attempt, and why the next tick is a sufficient retry for each, is asserted
    # rather than counted: `tests/job_registration_test.NO_LADDER_NEEDED` (D-366).
    job_completion_wait = 45

"""Four ways the worker fleet failed quietly, and the properties that stop each one.

Every finding here shares a shape: the failure produced LESS output rather than a red
job, so a healthy fleet and a broken one looked identical from outside.

* **P6.1 — the drain.** `WorkerSettings` set no `job_completion_wait`, and arq picks its
  signal handler on that value's TRUTHINESS: `0` installs `handle_sig`, which cancels
  every in-flight task in the first millisecond of SIGTERM. Three documents said the
  opposite, and `compose.prod.yml`'s 60-second grace was being handed to a process that
  had already thrown its work away.
* **P6.2 — the sweeps.** `apply_retention` had `max_tries` at `cron()`'s default of 1, no
  per-tenant isolation, and no alert. `report_stalled_pipeline` had the same unisolated
  loop, where an aborted sweep produces a SMALLER total and therefore a quieter alarm.
* **P6.3 — the blocking send.** A synchronous `smtplib` call behind an `async def`, so
  the call site read as deferred while parking the whole worker.
* **P6.4 — the poller's blind spot.** `_expected_artifacts` covered three artefacts for
  an eight-step pipeline, all of them at or before step 5.

WHY CONFIGURATION IS ASSERTED HERE RATHER THAN BEHAVIOUR, for the two that are settings:
reproducing a SIGTERM drain or a cron retry means running a real arq worker against a
real signal, and what actually decides both is one keyword each. `tests/qa_sampling_test`
already establishes the pattern of driving a real `arq.worker.Worker` for the cron half,
and `dispatch_tick_lease_test` the pattern of pinning one number against another it must
stay under. Both are followed rather than re-invented.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from apps.workers import notifications
from apps.workers import settings as worker_settings
from apps.workers.pipeline import _expected_artifacts
from calevate_shared.engine import ExecutionSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PROD = REPO_ROOT / "compose.prod.yml"


# ============================================================================
# P6.1 — the worker drains on SIGTERM
# ============================================================================


def _compose_grace_seconds(service: str) -> int:
    """`stop_grace_period` for one compose service, in seconds.

    Parsed rather than imported: the compose file is the contract with Docker and there
    is no Python object to read it off. Anchored on the service name so the workers'
    grace cannot be confused with redis's, which is a different number.
    """
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    block = text.split(f"\n  {service}:", 1)
    assert len(block) == 2, f"compose.prod.yml has no `{service}` service"
    match = re.search(r"stop_grace_period:\s*(\d+)s", block[1])
    assert match is not None, f"`{service}` declares no stop_grace_period"
    return int(match.group(1))


def test_the_worker_waits_for_its_jobs_before_it_cancels_them() -> None:
    """THE DEFECT, as the one fact that decides it.

    arq: `if self._job_completion_wait: handle_sig_wait_for_completion else: handle_sig`.
    Zero is falsy, so the default is the hard cancel — which is why this asserts a
    positive number rather than merely that the attribute exists.
    """
    wait = getattr(worker_settings.WorkerSettings, "job_completion_wait", 0)
    assert wait > 0, (
        "WorkerSettings.job_completion_wait is 0 or absent, so arq installs `handle_sig` "
        "and cancels every in-flight job in the first millisecond of SIGTERM — while "
        "compose.prod.yml, DEPLOYMENT §4b and BACKEND-PATTERNS §10 all say in-flight work "
        "is allowed to finish"
    )


def test_the_drain_window_fits_inside_the_grace_docker_gives_it() -> None:
    """The relationship, not the number — the same shape `dispatch_tick_lease_test` pins
    for `job_timeout < TICK_LEASE_TTL_S`.

    STRICTLY under, because the grace ends in SIGKILL: a drain equal to it is racing the
    kill, and a drain longer than it is cancelled by one. The headroom also has to cover
    `on_shutdown`, the tracing flush and the pool teardown, all of which run AFTER the
    drain returns.
    """
    wait = worker_settings.WorkerSettings.job_completion_wait
    grace = _compose_grace_seconds("workers")
    assert wait < grace, (
        f"the drain window ({wait}s) is not under the container's stop_grace_period "
        f"({grace}s) — SIGKILL would arrive mid-drain and the shutdown hooks would never "
        "run"
    )


# ============================================================================
# P6.2 — the nightly obligations survive one bad tenant, and say when they did not
# ============================================================================


#: Crons whose failure is not self-healing on a short tick, so a `max_tries` of 1 means
#: "gone until tomorrow". `apply_retention` and `sweep_expired` are the legal obligation;
#: `report_stalled_pipeline` self-heals in 30 minutes but is the ALARM, and an alarm that
#: gives up on its first transient error is silent for exactly as long as the incident.
#: `report_overdue_erasures` (P6.5) is the sharpest of the four: the condition it watches
#: CANNOT self-heal at all — `execute_deletion_request` is enqueued once, in the request's
#: own transaction, with no poller behind it — so a tick lost to a transient database
#: error is a DPDP §12 request that stays invisible until the next hour, or forever if
#: every tick loses the same way.
_CRONS_NEEDING_A_LADDER = (
    "apply_retention",
    "sweep_expired",
    "report_stalled_pipeline",
    "report_overdue_erasures",
)


def test_every_cron_that_cannot_self_heal_carries_its_own_retry_ladder() -> None:
    """`cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does NOT reach a
    cron — arq reads the per-job value. Three neighbours in the same list already say so
    in a comment each; these three did not have the argument applied to them."""
    by_name = {job.coroutine.__qualname__.split(".")[0]: job for job in worker_settings.CRON_JOBS}
    for name in _CRONS_NEEDING_A_LADDER:
        matches = [job for key, job in by_name.items() if name in key]
        # `traced_job` wraps each coroutine, so match on the registered name instead.
        if not matches:
            matches = [
                job
                for job in worker_settings.CRON_JOBS
                if name in getattr(job.coroutine, "__name__", "")
                or name in str(getattr(job.coroutine, "__wrapped__", ""))
            ]
        assert matches, f"{name} is not registered as a cron at all"
        for job in matches:
            assert job.max_tries == worker_settings.WORKER_MAX_TRIES, (
                f"{name} runs with max_tries={job.max_tries}. A container swap cancels the "
                "in-flight job, which requeues and then fails its pickup with "
                "`job_try=2 > 1` — and this one has no next tick to self-heal on"
            )


def test_the_retention_sweep_isolates_one_tenants_failure() -> None:
    """The loop had no `try`, so one tenant's error ended the sweep for every tenant
    after it — and with no `ORDER BY` on the tenant list, which ones those were changed
    from night to night.

    Asserted on the SOURCE because the behaviour needs a tenant that fails on demand
    inside a real session, and what actually decides it is that the call is inside a
    handler at all. The counter is asserted with it: an isolated loop that does not COUNT
    its failures is a sweep that skipped tenants and reported success.
    """
    from apps.workers import retention

    source = inspect.getsource(retention.sweep_tenants)
    tree = ast.parse(source.lstrip())
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
    assert handlers, (
        "sweep_tenants calls sweep_tenant with no try/except, so one tenant's database "
        "error aborts the nightly retention obligation for every tenant after it"
    )
    assert "tenants_failed" in source, "an isolated sweep that counts nothing reports success"


def test_the_retention_sweep_alerts_when_it_could_not_finish() -> None:
    """A retry ladder that runs out still has to tell somebody. The alert is on the
    COUNT, after the sweep, so the tick does what it can for everyone else first."""
    from apps.workers import retention

    source = inspect.getsource(retention.apply_retention)
    assert "alert(" in source and "retention_sweep_incomplete" in source, (
        "apply_retention finishes silently when tenants failed — the only trace of a "
        "night's undischarged obligation would be a stack trace in a log stream"
    )


def test_the_tenant_lists_are_ordered() -> None:
    """Both nightly sweeps resolve their tenants from the same bridge table. Without an
    `ORDER BY` the order is planner-dependent, which makes "tenant X was not swept" a
    question with no answer."""
    from apps.workers import dispatcher, retention

    for module, name in ((retention, "_due_tenants"), (dispatcher, "_callable_tenants")):
        source = inspect.getsource(getattr(module, name))
        assert "ORDER BY tenant_id" in source, f"{name} enumerates tenants in planner order"


def test_the_stall_alarm_reports_the_tenants_it_could_not_probe() -> None:
    """The quietest failure of the four. The alert fires on the total, so an aborted
    sweep produces a smaller number — or none — and reads exactly like a healthy fleet.
    An alarm that fails towards silence is worse than no alarm."""
    from apps.workers import dispatcher

    source = inspect.getsource(dispatcher.report_stalled_pipeline)
    assert "unreached" in source, "the stall alarm cannot say how much of the fleet it saw"
    assert "if total or unreached:" in source, (
        "the alarm only fires on a non-zero total, so a sweep that failed everywhere is "
        "indistinguishable from a fleet with nothing wrong"
    )


# ============================================================================
# P6.3 — the SMTP send is off the event loop
# ============================================================================


def test_the_email_send_does_not_park_the_worker() -> None:
    """`smtplib.SMTP` with `starttls()` and `login()` is synchronous socket I/O, and
    `_send_email` used to `return` it directly out of an `async def` — so the call site
    read as deferred while stopping all ten concurrent jobs, including `dispatch_outbox`
    on its 10-second schedule and the campaign tick that hard rule 5's DNC deadline is
    defined against.

    The AST is the subject rather than the behaviour: what makes this correct is that the
    blocking call is inside `asyncio.to_thread`, and a timing test would pass on the dev
    transport, which does no I/O at all.
    """
    tree = ast.parse(inspect.getsource(notifications._send_email).lstrip())
    threaded = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_thread"
    ]
    assert threaded, (
        "_send_email calls the transport on the event loop. `storage.py` fixed this exact "
        "class in D-159, `transport.py` states the rule and `whatsapp.py` states it again "
        "about the twin of this call on the same lead in the same transaction"
    )


# ============================================================================
# P6.4 — the poller's guarantee reaches the last step, not the fifth
# ============================================================================


def _snapshot(*, status: str = "completed", cost: object = None) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id="exec_probe",
        direction="outbound",
        status=status,  # type: ignore[arg-type]
        raw_status=status,
        terminal=True,
        billable_ready=True,
        cost=cost,  # type: ignore[arg-type]
        transcript=[],
    )


def test_a_completed_call_owes_the_crm_fanout() -> None:
    """The artefact that was missing. Steps 6-8 all run AFTER metering, each in its own
    transaction, so a pipeline that died between step 5's commit and step 8 left
    `usage_events` written — and the probe called that `settled` forever."""
    expected = _expected_artifacts(_snapshot(), extraction_owed=False, crm_fanout_owed=True)
    assert "crm_fanout" in expected


def test_a_tenant_with_no_subscribed_endpoint_owes_nothing() -> None:
    """The half that keeps the artefact honest, and the reason it needs a second column.

    `integrations.enqueue_events` writes one outbox row per SUBSCRIBED ACTIVE endpoint and
    returns 0 when there are none — which is most tenants. Expecting it unconditionally
    would re-drive every call on every tick forever, including a billed extraction, which
    is exactly the trap `_expected_artifacts` was written to avoid one artefact earlier.
    """
    expected = _expected_artifacts(_snapshot(), extraction_owed=False, crm_fanout_owed=False)
    assert "crm_fanout" not in expected


def test_a_call_that_did_not_complete_owes_nothing() -> None:
    """Step 8 gates on `status == "completed"`, so this list gates on it too — a failed
    or abandoned call was never owed a fan-out and must not be re-driven for one."""
    expected = _expected_artifacts(
        _snapshot(status="failed"), extraction_owed=False, crm_fanout_owed=True
    )
    assert "crm_fanout" not in expected


def test_the_probe_and_the_writer_read_one_column_not_two_spellings_of_a_scan() -> None:
    """Two spellings of "has this call been fanned out" is how a probe and a writer stop
    agreeing — and this pin has now survived the question being asked a third way.

    FIRST it compared two SQL literals, which proved they were equal on the day it ran.
    THEN it required both to name `OUTBOUND_WEBHOOK_JOB`, which made them agree by
    construction while both still containment-scanned the outbox. NEITHER is what the
    code does now: P6.7 replaced both scans with `calls.crm_notified_at`, one column
    written by `_mark_crm_notified` in the fan-out's own transaction and read by the
    poller off a row it already holds.

    So the invariant this file has always been protecting is unchanged and its evidence
    moves with the code: there is ONE fact, and neither side reconstructs it. What would
    now be a regression is either side going back to matching on the outbox payload —
    which is also the shape the nightly prune (`retention.prune_reliability_tables`)
    would silently break, by turning every call older than the floor into a permanent
    "unfinished pipeline".
    """
    from apps.workers import pipeline

    probe = inspect.getsource(pipeline._pipeline_settled)
    writer = inspect.getsource(pipeline._post_call_stages)
    assert "crm_notified_at" in probe, "the poller must read the column, not rebuild it"
    assert "_mark_crm_notified" in writer, "the fan-out must stamp the column it is read by"
    for source, where in ((probe, "the poller probe"), (writer, "the fan-out writer")):
        assert "outbox_messages" not in source, (
            f"{where} went back to scanning the outbox — unindexable, and wrong the "
            "moment the nightly prune removes a published row (P6.7)"
        )

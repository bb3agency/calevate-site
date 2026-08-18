"""The two terminal failures a JOB cannot alert about, and the backstop that does.

`WorkerSettings`' docstring is emphatic that there is no arq dead-letter queue and that
the alert on exhaustion is therefore a property of each job. That is right wherever the
job's own code runs — and `arq.worker.Worker.run_job` has two terminal paths where it
does not:

* `function ... not found` — an enqueue for a name no worker registers. The lookup fails
  before anything of ours executes, so there is no `except` for a job to have written.
  Silent: `logger.warning` and a failed-result key nothing in this repo reads.
* `max N retries exceeded` — checked BEFORE `on_job_start`, so the pickup that ENDS a
  retry ladder never enters the function. Every job that raises `Retry` up to its budget
  ends here, and so does any cron cancelled three times at `job_timeout`, which is
  `apply_retention` gone until tomorrow with nothing but a log line.

Two kinds of test, the shape `tests/guardrail_audit_test.py` uses:

* **wiring** — the two format strings are read out of the INSTALLED arq source, so an
  upgrade that rewords them fails here rather than silently unhooking the alerter. This
  is the whole reason the handler matches `record.msg` and not a rendered string.
* **detection** — drive a real `logging.LogRecord` through the real handler and assert an
  alert comes out, then assert an unrelated arq warning does NOT.
"""

from __future__ import annotations

import inspect
import logging

import arq.worker
import pytest
from apps.workers import settings as worker_settings


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    fired: list[tuple[str, str, str | None]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, detail))

    monkeypatch.setattr(worker_settings, "alert", _capture)
    return fired


@pytest.fixture
def attached() -> logging.Logger:
    """The handler on a private logger, removed afterwards.

    Never `arq.worker` itself: this process shares a logger tree with every other test,
    and a handler left behind would fire on the next file's fixtures.
    """
    logger = logging.getLogger("test.arq.worker.terminal")
    logger.propagate = False
    assert worker_settings.install_arq_terminal_alerter(logger.name) is True
    try:
        yield logger
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


# --- wiring: the templates are arq's, not ours --------------------------------


def test_both_templates_still_appear_in_the_installed_arq_source() -> None:
    """THE LOAD-BEARING ASSERTION. The handler recognises arq's terminal failures by their
    logging FORMAT STRING. If arq rewords either one, the handler goes quiet and every
    other test in this file still passes — a backstop that has silently stopped backing
    anything reads exactly like a healthy one."""
    source = inspect.getsource(arq.worker.Worker.run_job)
    for template in worker_settings.ARQ_TERMINAL_MESSAGES:
        assert template in source, (
            f"arq {arq.VERSION} no longer logs {template!r} in Worker.run_job — the "
            "terminal-failure alerter is unhooked. Re-read run_job and update "
            "`ARQ_TERMINAL_MESSAGES`."
        )


def test_arq_still_ends_these_two_paths_without_running_the_job() -> None:
    """WHY the backstop exists rather than a per-job `except`. Both terminal paths return
    from `run_job` before `on_job_start` is awaited, so nothing of ours can observe them
    from inside a job."""
    source = inspect.getsource(arq.worker.Worker.run_job)
    not_found = source.index("function %r not found")
    exhausted = source.index("max retries %d exceeded")
    on_job_start = source.index("if self.on_job_start:")
    assert not_found < on_job_start and exhausted < on_job_start, (
        "arq now reaches `on_job_start` on a terminal path — a per-job alert may be "
        "possible after all, and this backstop should be reconsidered rather than kept "
        "alongside one"
    )


def test_the_alerter_is_installed_at_worker_startup() -> None:
    """A handler nothing attaches is the half-wired feature CLAUDE.md names. Read off the
    function's source rather than by booting a worker, which needs Redis."""
    assert "install_arq_terminal_alerter()" in inspect.getsource(worker_settings.startup)


def test_installing_twice_does_not_double_the_alert() -> None:
    logger = logging.getLogger("test.arq.worker.idempotent")
    try:
        assert worker_settings.install_arq_terminal_alerter(logger.name) is True
        assert worker_settings.install_arq_terminal_alerter(logger.name) is False
        assert len(logger.handlers) == 1
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


# --- detection: a real record through the real handler ------------------------


def test_an_unregistered_job_name_reaches_an_operator(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    """The worst of the three wiring failures at runtime: the enqueue succeeded, the
    outbox row says published, and arq dropped the job."""
    attached.warning("job %s, function %r not found", "some_job:abc123", "some_job")
    assert len(alerts) == 1, alerts
    stage, code, detail = alerts[0]
    assert (stage, code) == ("WORKER_TERMINAL", "job_function_not_registered")
    assert detail is not None and "some_job" in detail


def test_an_exhausted_retry_ladder_reaches_an_operator(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    attached.warning("%6.2fs ! %s max retries %d exceeded", 1.5, "apply_retention", 3)
    assert len(alerts) == 1, alerts
    stage, code, detail = alerts[0]
    assert (stage, code) == ("WORKER_TERMINAL", "job_retries_exhausted")
    assert detail is not None and "apply_retention" in detail


def test_ordinary_arq_chatter_does_not_alert(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    """An alerter that fired on every warning would be muted by its own operator inside a
    week. `run_job` logs a retry and a cancellation on the NORMAL path — neither is a
    terminal state and neither may page anybody."""
    attached.info("%6.2fs ↻ %s retrying job in %0.2fs", 0.2, "notify_hot_lead", 15.0)
    attached.warning("%6.2fs ↻ %s cancelled, will be run again", 0.2, "apply_retention")
    attached.warning("job %s expired", "some_job:abc123")
    assert alerts == []


def test_the_alert_detail_is_bounded(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    """The message interpolates a job id, which is `"<job>:<natural key>"`. Ids only by
    construction, but an alert body travels further than a log line does."""
    attached.warning("job %s, function %r not found", "j:" + "x" * 5_000, "some_job")
    detail = alerts[0][2] or ""
    assert len(detail) <= worker_settings._ARQ_DETAIL_CHARS


# --- end to end: a real arq Worker on real Redis -------------------------------


@pytest.mark.asyncio
async def test_a_real_worker_drops_an_unregistered_job_and_the_alerter_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole failure, executed rather than reasoned about.

    Everything above drives a `LogRecord` we constructed. This drives a real
    `arq.worker.Worker` against real Redis: enqueue a name nothing registers alongside one
    that is registered, run one burst, and watch arq accept both, complete one and DROP
    the other — which is exactly what a producer deployed ahead of its worker does to a
    client's hot-lead alert or a data principal's erasure.

    Its OWN queue name, never the default: this Redis is shared, and a test that ran the
    fleet's queue would consume another process's work. The queue key and the burst
    worker's result keys are removed at the end for the same reason.
    """
    import secrets

    from apps.api.core.settings import get_settings
    from arq import create_pool
    from arq.connections import RedisSettings
    from arq.worker import Worker, func

    fired: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(
        worker_settings,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code, kw.get("detail"))),
    )

    async def registered(ctx: dict[str, object], payload: dict[str, object]) -> str:
        return "ok"

    queue = f"calevate:test:terminal-alert:{secrets.token_hex(4)}"
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    try:
        pool = await create_pool(redis_settings, default_queue_name=queue)
    except Exception as exc:  # pragma: no cover - machines without the compose stack
        pytest.skip(f"no redis: {type(exc).__name__}: {exc}")

    logging.getLogger("arq.worker").setLevel(logging.WARNING)
    installed = worker_settings.install_arq_terminal_alerter()
    worker = Worker(
        # `func(..., name=...)` because arq names a job by `__qualname__`, and a
        # coroutine defined inside a test is `test_...<locals>.registered` — the
        # control would otherwise fail for the very reason under test, which would
        # make this assertion prove nothing.
        functions=[func(registered, name="registered")],
        redis_settings=redis_settings,
        queue_name=queue,
        burst=True,
        poll_delay=0.05,
    )
    try:
        # arq accepts BOTH enqueues. That is the point: nothing at the call site can tell
        # the difference, which is why the static gate exists and why this backstop does.
        dropped = await pool.enqueue_job("no_such_job", {})
        ran = await pool.enqueue_job("registered", {})
        assert dropped is not None and ran is not None
        job_ids = [dropped.job_id, ran.job_id]
        await worker.main()
        assert worker.jobs_complete == 1, "the registered job did not run"
        assert worker.jobs_failed == 1, "arq did not drop the unregistered job"
        assert [(stage, code) for stage, code, _ in fired] == [
            ("WORKER_TERMINAL", "job_function_not_registered")
        ], fired
        assert "no_such_job" in (fired[0][2] or "")
    finally:
        await worker.close()
        # BY ID, never `keys("arq:result:*")`: this Redis is shared with sibling
        # workers and a wildcard delete would erase their results mid-run.
        for job_id in job_ids:
            await pool.delete(
                f"arq:result:{job_id}",
                f"arq:job:{job_id}",
                f"arq:retry:{job_id}",
                f"arq:in-progress:{job_id}",
            )
        await pool.delete(queue)
        await pool.aclose()
        if installed:
            arq_logger = logging.getLogger("arq.worker")
            for handler in list(arq_logger.handlers):
                if isinstance(handler, worker_settings._ArqTerminalFailureAlerter):
                    arq_logger.removeHandler(handler)

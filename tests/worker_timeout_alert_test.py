"""A job arq KILLS at `job_timeout` reaches an operator.

`tests/worker_terminal_alert_test.py` covers the two paths where arq ends a job WITHOUT
running it. This is the third, and it is the one that made `apply_retention` silent: the
job's code DOES run, overruns `WorkerSettings.job_timeout`, and is cancelled by
`asyncio.wait_for` inside `Worker.run_job`. The exception the worker sees is
`TimeoutError` — none of `Retry`, `RetryJob` or `CancelledError`, the three `retry_jobs`
honours — so the job is finished on its FIRST attempt whatever `max_tries` says, and the
coroutine that would have alerted is the one that was just cancelled. Nothing anywhere
was red.

The template is pinned against the INSTALLED arq source rather than quoted from memory
(hard rule 11): an upgrade that rewords it must fail the build instead of silently
unhooking the alert.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from apps.workers import settings as worker_settings
from tests.worker_terminal_alert_test import _installed_run_job_source


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    fired: list[tuple[str, str, str | None]] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **kw: Any) -> None:
        fired.append((stage, code, detail))

    monkeypatch.setattr(worker_settings, "alert", _alert)
    return fired


@pytest.fixture
def attached() -> Any:
    logger = logging.getLogger("tests.arq.timeout")
    logger.handlers = []
    logger.propagate = False
    worker_settings.install_arq_terminal_alerter(logger.name)
    yield logger
    logger.handlers = []


# `_installed_run_job_source` (imported above) is ONE READER OF arq's SOURCE, shared
# with `worker_terminal_alert_test`, and NOT
# `inspect.getsource(arq_worker.Worker.run_job)` — which is what this file used until it
# failed in the full suite and passed standalone. Sentry's arq integration MONKEYPATCHES
# that attribute with its own `_sentry_run_job` wrapper, so once anything in the process
# has initialised Sentry (the full run does; a single-file run does not) `getsource` hands
# back Sentry's function, in which arq's log templates do not appear. The sibling helper
# reads the installed module's FILE, which no patching of the attribute can reach and
# which is what the question is actually about: what the installed arq logs. The inverse
# is the danger worth naming — had the wrapper happened to contain those strings, the
# assertion would have PASSED while inspecting the wrong function.


def test_the_timeout_template_is_the_one_the_installed_arq_logs() -> None:
    source = _installed_run_job_source()
    assert worker_settings.ARQ_JOB_FAILED_TEMPLATE in source, (
        "arq no longer logs this template for a job that ended by raising, so the "
        "job-timeout alert is unhooked. Re-read `arq/worker.py::run_job` and update "
        "`ARQ_JOB_FAILED_TEMPLATE`."
    )


def test_the_cancellation_is_a_timeout_and_not_a_retryable_exception() -> None:
    """WHY this needs an alert at all: read off the installed source rather than
    remembered. `run_job` awaits the job under `asyncio.wait_for`, and the retry arms
    above the failure branch name three exception types — `TimeoutError` is not one."""
    source = _installed_run_job_source()
    assert "asyncio.wait_for(task, timeout_s)" in source
    failed = source.index(worker_settings.ARQ_JOB_FAILED_TEMPLATE)
    retry_arms = source[:failed]
    assert "isinstance(e, Retry)" in retry_arms
    assert "asyncio.CancelledError, RetryJob" in retry_arms
    assert "TimeoutError" not in retry_arms, (
        "arq now treats a job-timeout cancellation as retryable, which changes what this "
        "alert means — re-read `run_job` before keeping it"
    )


def test_a_job_killed_at_its_timeout_reaches_an_operator(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    attached.warning(
        worker_settings.ARQ_JOB_FAILED_TEMPLATE, 300.01, "apply_retention", "TimeoutError", ""
    )
    assert len(alerts) == 1, alerts
    stage, code, detail = alerts[0]
    assert (stage, code) == ("WORKER_TERMINAL", "job_killed_at_timeout")
    assert detail is not None and "apply_retention" in detail


def test_an_ordinary_job_exception_does_not_alert_on_this_path(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    """Every other exception rides the SAME template, and each of those jobs has its own
    retry ladder, its own last-attempt `alert()` and `job_retries_exhausted` behind it.
    Alerting here as well would page twice for every transient failure — which is how a
    handler gets muted, and then the timeout it exists for goes unread too."""
    attached.warning(
        worker_settings.ARQ_JOB_FAILED_TEMPLATE,
        0.4,
        "sweep_kb_uploads",
        "OperationalError",
        "deadlock detected",
    )
    assert alerts == []


def test_a_malformed_record_on_that_template_is_ignored_rather_than_raising(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    """The handler runs inside arq's own exception handling. A record shaped unlike the
    one arq emits must not turn one failure into two."""
    attached.warning(worker_settings.ARQ_JOB_FAILED_TEMPLATE)
    assert alerts == []


def test_the_detail_is_bounded_like_its_neighbours(
    attached: logging.Logger, alerts: list[tuple[str, str, str | None]]
) -> None:
    attached.warning(
        worker_settings.ARQ_JOB_FAILED_TEMPLATE, 300.0, "j:" + "x" * 5_000, "TimeoutError", ""
    )
    detail = alerts[0][2] or ""
    assert len(detail) <= worker_settings._ARQ_DETAIL_CHARS

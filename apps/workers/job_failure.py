"""Alarm on a job that ends by raising without having reported anything.

arq 0.28 retries a job only for `Retry`, `RetryJob` or `CancelledError`; any other
exception sets `finish=True` and the job leaves the queue after that one attempt
(`arq/worker.py`, `run_job`). Its only trace was arq's own "job failed" warning, which
`settings._ArqTerminalFailureAlerter` turns into an alarm for `TimeoutError` alone,
because most jobs that fail on purpose call `alert()` first and a second alarm from the
handler would page twice for one failure.

That left the jobs that raise WITHOUT alerting — a database error mid-run, a refusal
type nobody wrapped (`kb_read.RedeliveryIncompleteError`) — finished, unreported and
indistinguishable from success on every screen. This wrapper closes it from the job
side, where the difference is knowable: it runs the job inside `alerting.alert_scope`
and, when the job raises anything arq will not retry and no `alert()` fired inside it,
raises one `job_failed_unreported` naming the job and the exception class. It re-raises,
so arq's own bookkeeping is unchanged.

`TimeoutError` is left to the log handler (`job_killed_at_timeout`), which sees the
cancellation this wrapper cannot outlive.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, Final, cast

from arq import Retry
from arq.worker import RetryJob

from apps.api.core.alerting import alert, alert_scope

#: Exceptions arq retries, or that another path already reports.
_NOT_TERMINAL_HERE: Final = (Retry, RetryJob, TimeoutError)

ALARM_CODE: Final = "job_failed_unreported"
#: Attribute set on a wrapped job, so registration can be checked from outside.
MARK: Final = "alerts_unreported_failure"


def alert_unreported_failure[Job: Callable[..., Awaitable[Any]]](job: Job) -> Job:
    """Wrap an arq job so a terminal exception with no `alert()` behind it alarms once."""
    name = getattr(job, "__name__", "job")

    @functools.wraps(job)
    async def run(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        with alert_scope() as raised:
            try:
                return await job(ctx, *args, **kwargs)
            except _NOT_TERMINAL_HERE:
                raise
            except Exception as exc:
                if not raised:
                    alert(
                        "WORKER_TERMINAL",
                        ALARM_CODE,
                        detail=(
                            f"{name} raised {type(exc).__name__} and arq does not retry it; "
                            "the job is finished without having reported why"
                        ),
                        # One episode per job: two different jobs failing are two
                        # conditions, and the registered job names are a closed set.
                        episode=name,
                    )
                raise

    # Carried up through `traced_job`'s `functools.wraps` (it copies `__dict__`), so the
    # registration test can read it off the outermost callable arq holds.
    setattr(run, MARK, True)
    return cast(Job, run)


__all__ = ["ALARM_CODE", "MARK", "alert_unreported_failure"]

"""One wall-clock budget for the fleet-wide walks, so none of them is killed mid-pass.

WHY A BUDGET AT ALL (D-369, generalised). Several crons walk the whole client directory
one `tenant_session` at a time, because the tables they ask about are FORCE-RLS'd and a
cross-tenant probe would need an exemption. That cost grows with the client list rather
than with the data: `retention._due_tenants` records the measurement for exactly this
shape on the development database — ~16k organizations, ~3 minutes of round-trips.

`WorkerSettings.job_timeout` is 300 seconds, and what happens past it is the part that
matters. READ OFF THE INSTALLED SOURCE (arq 0.28.0, `arq/worker.py:594-634`), because the
obvious guess is wrong in the direction that matters: `run_job` awaits the job as
`asyncio.wait_for(task, timeout_s)`, so a job that overruns is cancelled and the WORKER
sees `TimeoutError` — which is none of `Retry`, `RetryJob` or `CancelledError`, the three
`retry_jobs` honours. The job is therefore FINISHED ON ITS FIRST ATTEMPT, whatever
`max_tries` says, and the only trace is `logger.exception('%6.2fs ! %s failed, ...')` —
a template `settings.ARQ_TERMINAL_MESSAGES` does not carry, so no alert fires either.

Three consequences, and the third is the one that made this a shared instrument rather
than one job's constant:

* the tail of the walk is never reached, and grows worse as the fleet grows — the failure
  repairs in the wrong direction;
* nothing says so. A weekly job whose pass is cut in half looks exactly like a quiet week,
  and the ladder its `cron()` registration carries is not even walked;
* a walk with a SIDE EFFECT per tenant re-does the side effect whenever the tick IS
  retried, which is the other half of the same story: a worker cancelled by a deploy past
  `job_completion_wait` raises `CancelledError`, which arq DOES retry, and the pass then
  restarts from the top of the same ordering. `kb_aggregation` is that case — the head of
  the ordering is re-mailed while the tail has still never been reached.

So a walk stops itself, deliberately and while it can still say so, rather than being
stopped by arq. A truncated pass ALERTS — silence would read exactly like a healthy fleet
— and the walk's directory is ordered, so the starved tail is stable and the same tenants
are skipped every tick until somebody acts on it, instead of a different random slice
each time.

A TIME budget, not a tenant COUNT, for the reason `dispatcher.ERASURE_PROBE_DEADLINE`
already gives: the per-item cost is a database session under whatever load the box is
carrying, and the thing that must not happen is arq killing the job, which is a
wall-clock condition. A count tuned for a healthy night is the wrong count on a slow one,
which is when this matters most.

`time.monotonic` and not `datetime.now`: this measures an ELAPSED interval, and a clock
that stepped backwards under NTP would extend the budget past the job timeout it exists
to stay under — the one outcome a deadline may not have.
"""

from __future__ import annotations

import time
from datetime import timedelta

#: The default budget for one fleet-wide walk.
#:
#: 180s leaves two full minutes under `WorkerSettings.job_timeout` (300s) for the alert,
#: the last tenant session to close and the pool to settle — the same "strictly under,
#: with headroom" reasoning `job_completion_wait` uses against the compose grace.
#: `tests/worker_fleet_walk_test.py` pins the relationship by reading `WorkerSettings`
#: rather than trusting this comment.
FLEET_WALK_DEADLINE = timedelta(seconds=180)


class WalkBudget:
    """A monotonic deadline for one pass over the fleet.

    Usage is deliberately two lines at the call site — construct before the loop, ask
    `spent()` at the top of each iteration — because the alternative shapes both hide
    the thing that has to stay visible. A decorator cannot report how MUCH of the fleet
    was reached, and an `asyncio.timeout` cancels mid-tenant, which is the arq behaviour
    this exists to replace rather than relocate.

    `exhausted` latches, so the caller reports truncation once after the loop rather than
    re-reading a clock that has moved on.
    """

    __slots__ = ("_deadline", "budget", "exhausted")

    def __init__(self, budget: timedelta = FLEET_WALK_DEADLINE) -> None:
        self.budget = budget
        self.exhausted = False
        self._deadline = time.monotonic() + budget.total_seconds()

    def spent(self) -> bool:
        """True once the budget is gone. Latches — see the class docstring."""
        if not self.exhausted and time.monotonic() >= self._deadline:
            self.exhausted = True
        return self.exhausted


__all__ = ["FLEET_WALK_DEADLINE", "WalkBudget"]

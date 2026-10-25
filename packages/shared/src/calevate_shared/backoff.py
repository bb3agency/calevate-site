"""The wait an arq job asks for when it raises `Retry(defer=...)`: every worker's one rule.

A ladder of fixed waits makes every job that failed together retry together, so a vendor
or database that dropped a batch of jobs is hit by the whole batch again at the same second
(Marc Brooker, "Exponential Backoff And Jitter", AWS Architecture Blog, 4 Mar 2015,
https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/). Each ladder
keeps its own base steps and attempt count; this module only spreads each step.

`apps/api/engine/vendor_http.throttle_delay_s` is the other backoff in the tree and stays
full jitter: it is an in-request sleep with no attempt budget to burn, the article's case.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence

Rand = Callable[[], float]


def jittered_delay_s(
    base_s: float, *, floor_s: float | None = None, rand: Rand | None = None
) -> float:
    """`base_s` spread by equal jitter: uniform in [base/2, base).

    With `floor_s`, the wait is uniform in [floor, floor + base/2) instead: for a wait whose
    minimum is load-bearing (a lease, a live call, a maintenance window), jitter goes on top.
    """
    # Equal, not full, jitter: with WORKER_MAX_TRIES attempts a full-jitter draw near zero
    # retries into the same outage and burns an attempt; equal jitter keeps half each step.
    spread = base_s / 2
    fixed = spread if floor_s is None else floor_s
    return fixed + spread * (rand or random.random)()


def ladder_delay_s(ladder: Sequence[float], attempt: int, *, rand: Rand | None = None) -> float:
    """The jittered wait after arq's 1-based `attempt`: its step, or the last one past the end."""
    step = ladder[max(min(attempt, len(ladder)) - 1, 0)]
    return jittered_delay_s(step, rand=rand)

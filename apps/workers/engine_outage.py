"""How a worker tells "the voice platform is not answering" from every other failure.

There is no second engine to fail over to, so an outage is waited out: work that needs the
engine is retried later, and nothing is marked failed, abandoned or lost because the engine
could not be asked. Two things follow, and this module holds both so every sweep and job
reads one rule rather than its own copy:

* `engine_unavailable` is the one predicate. A transport failure (`engine_unreachable`: a
  timeout, a refused connection, DNS, TLS), a throttle the adapter's own ladder could not
  clear, and a 5xx are the platform failing; a 4xx is its verdict on our request and is
  never read as an outage.
* `OutageStreak` stops a sweep that has reached a platform which is not answering. Every
  request costs up to `vendor_http.REQUEST_TIMEOUT_S`, and the sweeps that walk calls,
  workspaces or webhook endpoints make one request per item, serially: two hundred items
  at ten seconds each is past `WorkerSettings.job_timeout`, where arq kills the tick with
  whatever it had not yet written (set-asides, cursors, the alarm). Stopping after a few
  failures in a row keeps the tick inside its budget and leaves the rest for the next tick,
  which asks again.

Why consecutive and not a total: one call the engine cannot serve (a 5xx on one id) should
not stop a sweep whose other items are answering, and an answer of any kind in between
resets the count.
"""

from __future__ import annotations

from typing import Final

from apps.api.core.errors import ProblemError
from apps.api.engine.vendor_http import EngineRejectedError

#: Engine failures where an identical retry can still succeed. `engine_unreachable` is the
#: transport never completing; `engine_rate_limited` is `kind="transient"`, which the error
#: ladder defines as "identical retry can work". `engine_rejected` is deliberately absent:
#: a 4xx is a verdict (most often a 404 for an id the engine never issued) and re-asking
#: fails identically. A 5xx under that code is read off `vendor_status` instead.
TRANSIENT_ENGINE_CODES: Final = frozenset({"engine_unreachable", "engine_rate_limited"})

#: Engine-unavailable failures in a row after which a sweep stops asking this tick. Three
#: is past one slow request and one dropped connection, and at ten seconds each it costs a
#: tick thirty seconds rather than its whole `job_timeout`.
OUTAGE_STOP_AFTER: Final = 3


def engine_unavailable(exc: BaseException) -> bool:
    """True when `exc` says the platform did not answer, not that it refused."""
    if isinstance(exc, EngineRejectedError):
        return exc.vendor_status >= 500
    if isinstance(exc, ProblemError):
        return exc.kind == "transient" or exc.code in TRANSIENT_ENGINE_CODES
    return False


class OutageStreak:
    """Engine-unavailable failures in a row within one tick of a sweep."""

    __slots__ = ("_in_a_row", "_stop_after")

    def __init__(self, stop_after: int | None = None) -> None:
        self._in_a_row = 0
        self._stop_after = OUTAGE_STOP_AFTER if stop_after is None else stop_after

    def answered(self) -> None:
        """The engine answered (with anything, a refusal included)."""
        self._in_a_row = 0

    def failed(self, exc: BaseException) -> bool:
        """Record one failure; True when it was the platform not answering. A failure that
        is not an outage counts as an answer."""
        if not engine_unavailable(exc):
            self._in_a_row = 0
            return False
        self._in_a_row += 1
        return True

    @property
    def stopped(self) -> bool:
        """Has the sweep reached a platform that is not answering?"""
        return self._in_a_row >= self._stop_after


__all__ = [
    "OUTAGE_STOP_AFTER",
    "TRANSIENT_ENGINE_CODES",
    "OutageStreak",
    "engine_unavailable",
]

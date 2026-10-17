"""Items a capped, oldest-first sweep visited and could not move, kept out of its next reads.

A sweep that reads `ORDER BY <age> LIMIT n` and leaves a row exactly as it found it — a
provider that refuses that one input, a call the engine still calls live, an account not
finished yet — reads the same row at the head of the next tick. Once `n` such rows exist,
nothing behind them is ever reached. Where the queue is ordered by a column the sweep may
write (a visit stamp such as `webhook_checked_at`), stamping it is the fix and this module is
not used. This is for queues with no such column, where writing one would record something
untrue ("checked") or needs a migration for a hint.

An item is set aside for a while, not for ever: it is asked again after `for_`, so a
refusal that was transient after all, or a call that has since ended, is still reached.
Redis holds a hint, never a record: if it cannot answer, the sweep reads as it did before
this existed (nothing set aside), which is slower but skips nothing.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import timedelta
from typing import Final

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

log = get_logger(__name__)

_KEY: Final = "calevate:set-aside:{sweep}"

#: How long a provider's refusal of one input keeps that input out of a sweep. Long enough
#: that a poison item costs a few refused requests a day, short enough that an item refused
#: by a fault since fixed on our side comes back the same day.
REFUSED_INPUT_SET_ASIDE: Final = timedelta(hours=6)

#: Refusals in a row after which a sweep stops asking for this tenant this tick. Two
#: distinct inputs refused back to back is more likely a request the provider refuses
#: whatever it carries (a configuration fault) than two bad inputs, and asking on through
#: the whole tenant would multiply refused requests by the claim size. The two are still
#: set aside, so the next tick starts behind them either way.
REFUSALS_IN_A_ROW_STOP: Final = 2


async def set_aside(sweep: str, item_ids: Iterable[str], *, for_: timedelta) -> None:
    """Keep `item_ids` out of `sweep`'s reads until `for_` from now."""
    until = time.time() + for_.total_seconds()
    members = {str(item): until for item in item_ids}
    if not members:
        return
    key = _KEY.format(sweep=sweep)
    seconds = int(for_.total_seconds()) + 60
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.zadd(key, members)
            # NX then GT: a key with no expiry yet gets one, and a longer hold extends it.
            # `GT` alone never applies to a key without an expiry.
            pipe.expire(key, seconds, nx=True)
            pipe.expire(key, seconds, gt=True)
            await pipe.execute()
    except Exception as exc:
        log.warning("set_aside_unwritable", extra={"sweep": sweep, "reason": type(exc).__name__})


async def set_aside_ids(sweep: str) -> list[str]:
    """What `sweep` should not read this tick. Empty when Redis cannot say."""
    key = _KEY.format(sweep=sweep)
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, "-inf", time.time())
            pipe.zrange(key, 0, -1)
            _removed, members = await pipe.execute()
    except Exception as exc:
        log.warning("set_aside_unreadable", extra={"sweep": sweep, "reason": type(exc).__name__})
        return []
    return [str(member) for member in members]


class RefusalStreak:
    """Counts a tenant's provider refusals in a row within one tick (`REFUSALS_IN_A_ROW_STOP`)."""

    __slots__ = ("_in_a_row",)

    def __init__(self) -> None:
        self._in_a_row = 0

    def answered(self) -> None:
        self._in_a_row = 0

    def refused(self) -> bool:
        """Record one refusal. True when the sweep should stop asking for this tenant."""
        self._in_a_row += 1
        return self._in_a_row >= REFUSALS_IN_A_ROW_STOP


__all__ = [
    "REFUSALS_IN_A_ROW_STOP",
    "REFUSED_INPUT_SET_ASIDE",
    "RefusalStreak",
    "set_aside",
    "set_aside_ids",
]

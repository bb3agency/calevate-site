"""Outbound dial pacing: at most `Settings.carrier_cps` call starts per second, platform-wide.

The carrier counts calls STARTED per second against the account, not per tenant, and
refuses the excess with a 429 (`vobiz-findings/mirror/pages/faq/cps.md:13-16`). Both
outbound dial loops in this deployable (`campaign_dispatch` and `callbacks`) take a slot
here immediately before `agents.service.dispatch_call`, so a tick that clears ten contacts
spaces their dials instead of sending ten in the same second and losing nine to the carrier.

WHY A SPACING LEASE AND NOT `core.ratelimit.consume`. That counter is a fixed window, which
admits up to twice the rate across a window boundary: at 1 CPS it lets a dial at :00.99 and
another at :01.01, and the carrier counts both inside one second. A `SET NX PX` key whose
TTL is the minimum gap between two dials (`1000 / cps` ms) is a hard spacing guarantee with
the same primitive `campaign_dispatch._tick_lease` already uses, and it needs no release:
the key expiring IS the next slot opening.

ONLY ON THE ENGINE THAT DIALS THROUGH OUR CARRIER. An `owned_runtime` engine places the call
on the carrier account this limit belongs to; any other engine either dials nothing (the
fake) or dials on an account whose limit is not ours to pace.

FAILS OPEN on a Redis error, for `_tick_lease`'s reason: arq delivered this tick through the
same Redis, a dial loop that stops because Redis hiccuped is a campaign that stops, and the
carrier's own 429 is a definite refusal the dial path already treats as retryable.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Final

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine

log = get_logger(__name__)

#: One key per carrier account. Two carriers are two accounts with two limits.
PACING_KEY_PREFIX: Final = "calevate:carrier:dial_slot"

#: The longest one dial waits for its slot before the loop gives the contact back. The tick
#: is single-flight and dials at most the outbound pool plus the call-backs, so at 1 CPS a
#: dial waits about a second; ten seconds means something other than this tick is holding
#: the account's slots, and the contact is better re-queued than the tick stalled.
MAX_PACING_WAIT_S: Final = 10.0

#: The rule name a paced-out dial is refused under. Not a person-level refusal, so the
#: contact or call-back goes back on its ladder with the attempt refunded.
PACING_RULE: Final = "carrier_pacing"


class DialPacingTimeoutError(Exception):
    """No dial slot opened within `MAX_PACING_WAIT_S`. Nothing was dialled."""


def pacing_applies() -> bool:
    """Whether the configured engine starts calls on the carrier account being paced."""
    return get_engine().capabilities.agent_hosting == "owned_runtime"


def slot_interval_ms(cps: int) -> int:
    """The minimum gap between two dial starts, rounded UP so the rate is never exceeded."""
    return max(1, math.ceil(1000 / max(1, cps)))


async def await_dial_slot(
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> float:
    """Wait until this process may start one dial. Returns the seconds spent asleep for a
    slot, which is 0.0 whenever the first ask got one or pacing failed open.

    Read per call, not cached: `carrier_cps` and `carrier` are live settings, so an operator
    raising the account's CPS takes effect on the next dial.

    Raises `DialPacingTimeoutError` when no slot opens in `MAX_PACING_WAIT_S`.
    """
    if not pacing_applies():
        return 0.0
    settings = get_settings()
    interval_ms = slot_interval_ms(settings.carrier_cps)
    key = f"{PACING_KEY_PREFIX}:{settings.carrier}"
    deadline = clock() + MAX_PACING_WAIT_S
    waited = 0.0
    while True:
        try:
            redis = get_redis()
            if await redis.set(key, "1", nx=True, px=interval_ms):
                return waited
            remaining_ms = int(await redis.pttl(key))
            if remaining_ms == -1:
                # A key with no TTL would hold the slot for ever; give it the interval.
                await redis.pexpire(key, interval_ms)
                remaining_ms = interval_ms
        except Exception:
            log.warning("carrier_pacing_unavailable", extra={"carrier": settings.carrier})
            return waited
        # -2: the key expired between SET and PTTL, so the slot is open now.
        wait_s = max(0, remaining_ms) / 1000
        if clock() + wait_s > deadline:
            raise DialPacingTimeoutError
        await sleep(wait_s)
        waited += wait_s


__all__ = [
    "MAX_PACING_WAIT_S",
    "PACING_KEY_PREFIX",
    "PACING_RULE",
    "DialPacingTimeoutError",
    "await_dial_slot",
    "pacing_applies",
    "slot_interval_ms",
]

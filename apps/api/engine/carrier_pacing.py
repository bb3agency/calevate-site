"""What the carrier account admits: call starts per second, and simultaneous lines.

Both limits belong to the carrier ACCOUNT, not to a tenant, and Vobiz refuses the excess of
either with `429 Too Many Requests` (`vobiz-findings/mirror/pages/call/make-call.md:134`,
`faq/cps.md:13-16`). `agents.service.dispatch_call` is the platform's one outbound entry
point, so it is where both are enforced, once per dial, for every caller: the campaign tick,
the call-back pass, the "call this lead" and "call back" buttons and lead ingest.

PACING (`await_dial_slot`). At most `Settings.carrier_cps` dial starts per second. A
`SET NX PX` key whose TTL is the minimum gap between two dials (`slot_interval_ms`) is a hard
spacing guarantee and needs no release: the key expiring is the next slot opening. A
fixed-window counter (`core.ratelimit.consume`) was rejected because it admits up to twice
the rate across a window boundary. Pacing FAILS OPEN on a Redis error: the carrier's own 429
is a refusal the dial path already treats as not placed, and a dial path that stops because
Redis hiccuped is an outage of its own.

LINES (`outbound_line_pool`). `Settings.carrier_concurrency` simultaneous calls, inbound and
outbound together, of which `inbound_line_reserve` are kept for callers: outbound may use the
rest. The count itself is a database question (`carrier_lines_in_use()`, migration
a6d3b9f52e18) answered inside the dial's intent transaction; this module holds the
arithmetic and the horizons so the dispatch tick's budget and the dial gate agree.

BOTH APPLY ONLY TO THE ENGINE THAT DIALS THROUGH OUR CARRIER (`dials_through_our_carrier`).
An `owned_runtime` engine places the call on the carrier account these limits belong to; any
other engine either dials nothing (the fake) or dials on an account whose limits are not
ours.

AN ENGINE WITH ITS OWN CALL CEILING (`engine_concurrency_cap`, ThinnestAI today) gets the
same two answers on its own account: the line pool is its ceiling minus the inbound reserve,
counted from our outbound rows (its inbound calls are invisible to us until they end), and a
`429` holds every dial off for the vendor's `Retry-After` (`start_dial_backoff`) instead of
being re-asked once per claimed contact.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Final

from calevate_shared.config import Settings

from apps.api.agents.models import CALL_CAP_MAX_S
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine
from apps.api.engine.carrier import CARRIER_DEFAULT_RING_TIMEOUT_S, RING_TIMEOUT_S
from apps.api.engine.vendor_http import (
    LINES_BUSY_CODE,
    lines_busy_error,
)

log = get_logger(__name__)

#: One key per carrier account. Two carriers are two accounts with two limits.
PACING_KEY_PREFIX: Final = "calevate:carrier:dial_slot"

#: The longest one dial waits for its slot before it is refused. A dial waits about a second
#: at 1 CPS; ten seconds means something else is holding the account's slots, and the dial
#: is better refused (and the contact, call-back or lead re-queued) than the caller stalled.
MAX_PACING_WAIT_S: Final = 10.0

#: The code a paced-out dial is refused under. Not a person-level refusal, so a contact or
#: call-back goes back on its ladder with the attempt refunded.
PACING_RULE: Final = "carrier_pacing"

#: The code a dial is refused under when the account's outbound lines are all in use.
LINES_BUSY_RULE: Final = LINES_BUSY_CODE

#: Headroom on the gap. The slot is taken in Redis, but the request reaches the carrier after
#: the work between the gate and the HTTP call, whose duration varies per dial; without a
#: margin two dials can arrive closer than `1000 / cps` ms and the carrier counts both in one
#: second.
SPACING_MARGIN_PERCENT: Final = 110

#: How long a `ringing` or `in_progress` row counts as a line in use: the longest call an
#: agent may run plus a margin for the lag between hang-up and the row going terminal. Past
#: it, a row whose end was never reported stops holding a line.
LIVE_LINE_HORIZON: Final = timedelta(seconds=CALL_CAP_MAX_S) + timedelta(minutes=10)

#: How long a `queued` row counts as a line in use: the longest an unanswered dial rings
#: (the timeout we ask for, or the carrier's default if it is not honoured), plus a margin
#: for the time between our intent row and the carrier starting to ring.
RING_LINE_HORIZON: Final = timedelta(
    seconds=max(RING_TIMEOUT_S, CARRIER_DEFAULT_RING_TIMEOUT_S)
) + timedelta(minutes=2)

#: The transaction-scoped advisory lock every dial's line check takes, so two dials cannot
#: both count `pool - 1` lines and both go out. Any constant works as long as nothing else in
#: the schema uses it; this one spells "carrier lines" in ASCII.
CARRIER_LINES_LOCK_KEY: Final = 0x4341_524C_494E_4553


class DialPacingTimeoutError(Exception):
    """No dial slot opened within `MAX_PACING_WAIT_S`. Nothing was dialled."""


def dials_through_our_carrier() -> bool:
    """Whether the configured engine starts calls on the carrier account being limited."""
    return get_engine().capabilities.agent_hosting == "owned_runtime"


def slot_interval_ms(cps: int) -> int:
    """The minimum gap between two dial starts, with headroom, rounded UP."""
    # Integer ceiling: a float margin turns 1100 ms into 1101.
    return max(1, -(-10 * SPACING_MARGIN_PERCENT // max(1, cps)))


def inbound_line_reserve(concurrency: int, reserved_lines: int | None, ratio: float) -> int:
    """Lines kept free for inbound callers: the operator's count, or else `ratio` of them.

    Never zero: the receptionist is the product a client is paying for every minute of the
    day, and a campaign that takes the last line turns a caller away with a carrier error.
    Never more than the account has, so a count typed above the line limit reserves every
    line rather than a negative pool. The share is taken in `Decimal` from the ratio's
    decimal string, because `10 * 0.3` is `3.0000000000000004` in binary floating point and
    its ceiling would reserve four lines.
    """
    if reserved_lines is None:
        return max(1, math.ceil(Decimal(concurrency) * Decimal(str(ratio))))
    return max(1, min(reserved_lines, concurrency))


def engine_concurrency_cap(settings: Settings | None = None) -> int | None:
    """The simultaneous-call ceiling of an engine that runs calls on ITS OWN account, or
    None when the engine has none we hold (the carrier's lines apply, or nothing does).

    ThinnestAI places and answers calls on its own numbers, so `carrier_concurrency` says
    nothing about it; its workspace has its own ceiling, inbound and outbound together
    (`thinnest-findings/mirror/pages/api-reference/place-call.md:333-336`).
    """
    if get_engine().name != "thinnest":
        return None
    return (settings or get_settings()).thinnest_max_concurrent_calls


def outbound_line_pool(settings: Settings | None = None) -> int:
    """Lines outbound dials may hold at once: the account's lines minus the inbound reserve.

    At the default three lines and the automatic reserve that is two outbound lines and one
    kept for callers. Zero when the account is too small to spare one, which the dispatch
    tick reports as `outbound_pool_empty`. On an engine with its own ceiling
    (`engine_concurrency_cap`) that ceiling is the account's lines: at ThinnestAI's 5 that
    is three outbound and two kept for callers, who share the same ceiling and whom we
    cannot see while they talk.
    """
    cfg = settings or get_settings()
    cap = engine_concurrency_cap(cfg)
    lines = cfg.carrier_concurrency if cap is None else cap
    reserve = inbound_line_reserve(lines, cfg.inbound_reserved_lines, cfg.inbound_reserve_ratio)
    return max(0, lines - reserve)


#: How long an outbound row on an engine-capped account counts as holding a line. Such an
#: engine reports nothing while a call rings or talks — ThinnestAI sends `call.completed`
#: when it ends and nothing before (`api-reference/webhooks.md:73-74`) — so the row stays
#: `queued` for the whole call, and the live horizon applies to it rather than the ring one.
ENGINE_LINE_HORIZON: Final = LIVE_LINE_HORIZON

#: One key per engine. A refusal for the workspace's ceiling is the ACCOUNT's, so every
#: dialling process honours it, not only the one that was refused.
ENGINE_BACKOFF_KEY_PREFIX: Final = "calevate:engine:dial_backoff"

#: The hold-off after a throttled dial that named no `Retry-After`: the vendor's own example
#: value (`api-reference/authentication.md:59-66`). A floor as well, because a call ceiling
#: frees only when a call ends and a shorter wait would just collect another 429.
ENGINE_BACKOFF_DEFAULT_S: Final = 60.0

#: The longest hold-off taken from a vendor header, so a malformed one cannot stop dialling
#: for a day. The `from` number's daily cap (`place-call.md:187-189`) is the case that
#: reaches it; dials then retry at this interval, each refunded, until the day turns.
ENGINE_BACKOFF_MAX_S: Final = 900.0


def _backoff_key() -> str:
    return f"{ENGINE_BACKOFF_KEY_PREFIX}:{get_engine().name}"


async def dial_backoff_remaining_s() -> float:
    """Seconds left on this engine's dial hold-off; 0.0 when none, or when the engine has no
    ceiling of its own. Fails OPEN on a Redis error, for `await_dial_slot`'s reason: the
    vendor's own 429 still refuses the dial, and nothing is placed."""
    if engine_concurrency_cap() is None:
        return 0.0
    try:
        remaining_ms = int(await get_redis().pttl(_backoff_key()))
    except Exception:
        log.warning("engine_dial_backoff_unavailable", extra={"engine": get_engine().name})
        return 0.0
    return max(0, remaining_ms) / 1000


async def start_dial_backoff(retry_after_s: float | None) -> float:
    """Hold this engine's dials off after the vendor refused one for its rate or ceiling.
    Returns the hold-off taken. A longer one already running is never shortened."""
    seconds = min(max(retry_after_s or 0.0, ENGINE_BACKOFF_DEFAULT_S), ENGINE_BACKOFF_MAX_S)
    try:
        redis = get_redis()
        key = _backoff_key()
        if await dial_backoff_remaining_s() < seconds:
            await redis.set(key, "1", px=int(seconds * 1000))
    except Exception:
        log.warning("engine_dial_backoff_unavailable", extra={"engine": get_engine().name})
        return 0.0
    log.warning("engine_dial_backoff", extra={"engine": get_engine().name, "seconds": seconds})
    return seconds


def engine_backoff_refusal() -> ProblemError:
    """The refusal for a dial inside the hold-off. Nothing was dialled, and the code is the
    one `DIAL_NOT_PLACED_CODES` already reads as a throttle, so no attempt is spent; the
    wording is `vendor_http.EngineRateLimitedError`'s, because it is the same refusal."""
    return ProblemError(
        kind="transient",
        code="engine_rate_limited",
        title="Voice engine is rate limiting us",
        detail="The voice platform is temporarily refusing new requests.",
        remediation="The lines are busy. Try again in a minute.",
        failure_stage="CORE_LOGIC",
    )


def pacing_timed_out() -> ProblemError:
    """The refusal for a dial whose pacing slot did not open in time. Nothing was dialled."""
    return ProblemError(
        kind="transient",
        code=PACING_RULE,
        title="Calls are being started as fast as the line allows",
        detail="The calling account starts a limited number of calls each second, and this "
        "call could not be started in time, so it was not placed.",
        remediation="Try again in a minute.",
    )


def lines_busy() -> ProblemError:
    """The refusal for a dial while every outbound line is in use. Nothing was dialled."""
    return lines_busy_error()


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
    if not dials_through_our_carrier():
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
    "CARRIER_LINES_LOCK_KEY",
    "ENGINE_BACKOFF_DEFAULT_S",
    "ENGINE_BACKOFF_KEY_PREFIX",
    "ENGINE_BACKOFF_MAX_S",
    "ENGINE_LINE_HORIZON",
    "LINES_BUSY_RULE",
    "LIVE_LINE_HORIZON",
    "MAX_PACING_WAIT_S",
    "PACING_KEY_PREFIX",
    "PACING_RULE",
    "RING_LINE_HORIZON",
    "SPACING_MARGIN_PERCENT",
    "DialPacingTimeoutError",
    "await_dial_slot",
    "dial_backoff_remaining_s",
    "dials_through_our_carrier",
    "engine_backoff_refusal",
    "engine_concurrency_cap",
    "inbound_line_reserve",
    "lines_busy",
    "outbound_line_pool",
    "pacing_timed_out",
    "slot_interval_ms",
    "start_dial_backoff",
]

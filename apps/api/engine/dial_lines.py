"""How many outbound dials the engine's account admits at once, and the hold-off after a refusal.

`agents.service.dispatch_call` is the platform's one outbound entry point, so it is where
the line limit is enforced, once per dial, for every caller: the campaign tick, the
call-back pass, the "call this lead" and "call back" buttons and lead ingest.

LINES (`outbound_line_pool`). The account's simultaneous calls, inbound and outbound
together, of which `inbound_line_reserve` are kept for callers: outbound may use the rest.
The count itself is a database question answered inside the dial's intent transaction;
this module holds the arithmetic and the horizon so the dispatch tick's budget and the dial
gate agree.

AN ENGINE WITH ITS OWN CALL CEILING (`engine_concurrency_cap`, ThinnestAI) uses that
ceiling as the account's lines. Its inbound calls are invisible to us until they end, so
the pool is counted from our outbound rows, and a `429` holds the dials its limit covers
(the account's, one workspace's or one number's) off for the vendor's `Retry-After`
(`start_dial_backoff`) instead of being re-asked once per claimed contact. An engine with
no ceiling of its own (the fake) uses `Settings.carrier_concurrency`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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
from apps.api.engine.vendor_http import (
    LINES_BUSY_CODE,
    ThrottleScope,
    lines_busy_error,
    number_daily_limit_error,
)

log = get_logger(__name__)

#: The code a dial is refused under when the account's outbound lines are all in use.
LINES_BUSY_RULE: Final = LINES_BUSY_CODE

#: How long a live outbound row counts as a line in use: the longest call an agent may run
#: plus a margin for the lag between hang-up and the row going terminal. Past it, a row
#: whose end was never reported stops holding a line.
LIVE_LINE_HORIZON: Final = timedelta(seconds=CALL_CAP_MAX_S) + timedelta(minutes=10)

#: How long an outbound row on an engine-capped account counts as holding a line. Such an
#: engine reports nothing while a call rings or talks — ThinnestAI sends `call.completed`
#: when it ends and nothing before (`api-reference/webhooks.md:73-74`) — so the row stays
#: `queued` for the whole call, and the live horizon applies to it.
ENGINE_LINE_HORIZON: Final = LIVE_LINE_HORIZON

#: The transaction-scoped advisory lock every dial's line check takes, so two dials cannot
#: both count `pool - 1` lines and both go out. Any constant works as long as nothing else in
#: the schema uses it; this one spells "carrier lines" in ASCII.
CARRIER_LINES_LOCK_KEY: Final = 0x4341_524C_494E_4553


def inbound_line_reserve(concurrency: int, reserved_lines: int | None, ratio: float) -> int:
    """Lines kept free for inbound callers: the operator's count, or else `ratio` of them.

    Never zero: the receptionist is the product a client is paying for every minute of the
    day, and a campaign that takes the last line turns a caller away. Never more than the
    account has, so a count typed above the line limit reserves every line rather than a
    negative pool. The share is taken in `Decimal` from the ratio's decimal string, because
    `10 * 0.3` is `3.0000000000000004` in binary floating point and its ceiling would
    reserve four lines.
    """
    if reserved_lines is None:
        return max(1, math.ceil(Decimal(concurrency) * Decimal(str(ratio))))
    return max(1, min(reserved_lines, concurrency))


def engine_concurrency_cap(settings: Settings | None = None) -> int | None:
    """The simultaneous-call ceiling of an engine that runs calls on ITS OWN account, or
    None when the engine has none we hold.

    ThinnestAI places and answers calls on its own numbers; its workspace has its own
    ceiling, inbound and outbound together
    (`thinnest-findings/mirror/pages/api-reference/place-call.md:333-336`).
    """
    if get_engine().name != "thinnest":
        return None
    return (settings or get_settings()).thinnest_max_concurrent_calls


def outbound_line_pool(settings: Settings | None = None) -> int:
    """Lines outbound dials may hold at once: the account's lines minus the inbound reserve.

    At ThinnestAI's 5 that is three outbound and two kept for callers, who share the same
    ceiling and whom we cannot see while they talk. Zero when the account is too small to
    spare one, which the dispatch tick reports as `outbound_pool_empty`.
    """
    cfg = settings or get_settings()
    cap = engine_concurrency_cap(cfg)
    lines = cfg.carrier_concurrency if cap is None else cap
    reserve = inbound_line_reserve(lines, cfg.inbound_reserved_lines, cfg.inbound_reserve_ratio)
    return max(0, lines - reserve)


#: The hold-off keys, one per engine and scope (`ThrottleScope`), shared by every dialling
#: process so a refusal is honoured by all of them, not only the one that was refused. An
#: account-wide limit holds every dial; a workspace's limit only dials placed in that
#: client's workspace; one `from` number's daily cap only dials from that number. Keyed
#: by our own ids, never by a phone number (hard rule 6).
ENGINE_BACKOFF_KEY_PREFIX: Final = "calevate:engine:dial_backoff"

#: The hold-off after a throttled dial that named no `Retry-After`: the vendor's own example
#: value (`api-reference/authentication.md:59-66`). A floor as well, because a call ceiling
#: frees only when a call ends and a shorter wait would just collect another 429.
ENGINE_BACKOFF_DEFAULT_S: Final = 60.0

#: The longest hold-off taken from a vendor header, so a malformed one cannot stop dialling
#: for a day. It is also the hold-off for a number's daily cap (snapshots/2026-10-29/pages/
#: api-reference/calls/place-call.md:674-679), which frees only when the vendor's day turns,
#: a boundary it does not document: dials from that number retry at this interval, each
#: refunded, until it does.
ENGINE_BACKOFF_MAX_S: Final = 900.0

#: The number key of the shared free-trial line (`Settings.trial_caller_number`), which has
#: no `phone_numbers` row of ours.
TRIAL_LINE_KEY: Final = "trial-line"

#: The developer workspace's name in a workspace key; customer workspaces are `org_…`.
_DEVELOPER_WORKSPACE: Final = "developer"


@dataclass(frozen=True, slots=True)
class DialOrigin:
    """Where a dial is placed, as far as a hold-off can be scoped to it."""

    #: The engine workspace the dial is sent to (`scope_of(dial_ref)`); None is ours.
    workspace: str | None
    #: Our `phone_numbers` id of the `from` number, `TRIAL_LINE_KEY`, or None when the dial
    #: names no `from` and the vendor chooses.
    number_key: str | None


def _backoff_key(
    scope: ThrottleScope = ThrottleScope.ACCOUNT, origin: DialOrigin | None = None
) -> str | None:
    base = f"{ENGINE_BACKOFF_KEY_PREFIX}:{get_engine().name}"
    if scope is ThrottleScope.ACCOUNT:
        return base
    if origin is None:
        return None
    if scope is ThrottleScope.WORKSPACE:
        return f"{base}:workspace:{origin.workspace or _DEVELOPER_WORKSPACE}"
    return None if origin.number_key is None else f"{base}:number:{origin.number_key}"


async def _remaining_s(key: str) -> float:
    return max(0, int(await get_redis().pttl(key))) / 1000


async def _held_scope(origin: DialOrigin | None) -> tuple[ThrottleScope, float] | None:
    """The scope holding a dial from `origin` and its seconds left, the number's first; None
    when nothing holds it or the engine has no ceiling of its own. Fails OPEN on a Redis
    error: the vendor's own 429 still refuses the dial, and a dial path that stops because
    Redis hiccuped is an outage of its own."""
    if engine_concurrency_cap() is None:
        return None
    try:
        for scope in (ThrottleScope.NUMBER, ThrottleScope.WORKSPACE, ThrottleScope.ACCOUNT):
            key = _backoff_key(scope, origin)
            if key is not None and (remaining := await _remaining_s(key)) > 0:
                return scope, remaining
    except Exception:
        log.warning("engine_dial_backoff_unavailable", extra={"engine": get_engine().name})
    return None


async def dial_backoff_remaining_s(origin: DialOrigin | None = None) -> float:
    """Seconds left on the hold-off covering a dial from `origin`; without one, the
    account-wide hold-off alone (the campaign tick's budget). 0.0 when none."""
    held = await _held_scope(origin)
    return 0.0 if held is None else held[1]


async def dial_backoff_refusal(origin: DialOrigin) -> ProblemError | None:
    """The refusal for a dial from `origin` inside a hold-off, or None when none holds it.
    A number's daily cap is refused as that, so the client is told another number works."""
    held = await _held_scope(origin)
    if held is None:
        return None
    return (
        number_daily_limit_error() if held[0] is ThrottleScope.NUMBER else engine_backoff_refusal()
    )


async def start_dial_backoff(
    retry_after_s: float | None,
    *,
    scope: ThrottleScope = ThrottleScope.ACCOUNT,
    origin: DialOrigin | None = None,
) -> float:
    """Hold dials off after the vendor refused one for a limit of `scope`, for dials from
    `origin`. Returns the hold-off taken; 0.0 when the refusal names nothing to scope it to
    (a number's cap on a dial that named no number). A longer one already running is never
    shortened."""
    key = _backoff_key(scope, origin)
    engine = get_engine().name
    if key is None:
        log.warning("engine_dial_backoff_unscoped", extra={"engine": engine, "scope": scope})
        return 0.0
    floor = ENGINE_BACKOFF_MAX_S if scope is ThrottleScope.NUMBER else ENGINE_BACKOFF_DEFAULT_S
    seconds = min(max(retry_after_s or 0.0, floor), ENGINE_BACKOFF_MAX_S)
    try:
        if await _remaining_s(key) < seconds:
            await get_redis().set(key, "1", px=int(seconds * 1000))
    except Exception:
        log.warning("engine_dial_backoff_unavailable", extra={"engine": engine})
        return 0.0
    # The scope and, for a workspace, its `org_…` id: ours, not personal data.
    log.warning(
        "engine_dial_backoff",
        extra={
            "engine": engine,
            "seconds": seconds,
            "scope": scope,
            "workspace": origin.workspace if origin is not None else None,
        },
    )
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


def lines_busy() -> ProblemError:
    """The refusal for a dial while every outbound line is in use. Nothing was dialled."""
    return lines_busy_error()


__all__ = [
    "CARRIER_LINES_LOCK_KEY",
    "ENGINE_BACKOFF_DEFAULT_S",
    "ENGINE_BACKOFF_KEY_PREFIX",
    "ENGINE_BACKOFF_MAX_S",
    "ENGINE_LINE_HORIZON",
    "LINES_BUSY_RULE",
    "LIVE_LINE_HORIZON",
    "TRIAL_LINE_KEY",
    "DialOrigin",
    "dial_backoff_refusal",
    "dial_backoff_remaining_s",
    "engine_backoff_refusal",
    "engine_concurrency_cap",
    "inbound_line_reserve",
    "lines_busy",
    "outbound_line_pool",
    "start_dial_backoff",
]

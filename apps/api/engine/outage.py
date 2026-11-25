"""The outbound dial hold while the voice engine is not answering.

`agents.service.dispatch_call` is the platform's one outbound entry point, so this is
asked there, once per dial, for every caller: the campaign tick, the call-back pass, lead
ingest and the "call this lead" button. The dispatch tick also asks it once before it
claims anybody, so a held tick claims no contact, fires no schedule and spends no line.

WHY A HOLD AT ALL. There is no second engine to fail over to, and a dial into an engine
that is not answering costs the full `vendor_http.REQUEST_TIMEOUT_S` (10 s) and, on a read
timeout, leaves a dial whose outcome is unknown (`agents.service.DialUnconfirmedError`).
Without a hold a tick spends its whole `job_timeout` (300 s) timing out one contact after
another, and every one of them becomes a call that must be reconciled before its person
can be tried again.

TRIP: `TRIP_AFTER_FAILURES` consecutive dials that failed for the engine's reason (no
answer, or a 5xx), shared across processes in Redis, inside `FAILURE_WINDOW_S`. Two, not
one, because a single timeout is the ordinary blip of any HTTP dependency and holding the
whole platform for it would cost every client a probe interval; two in a row with no
success between them is the shape of the 26 Nov 2026 incident (two `POST /calls` read
timeouts a minute apart) and already 20 s of a tick. Any dial that succeeds resets the run.
A refusal the vendor ANSWERED (a 4xx, a 429) is the engine working and never counts.

PROBE: a READ, never a dial. `POST /calls` is the endpoint whose failure we care about, and
"place one call to see if it is back" is a phone ringing on a timer rather than through the
compliance gate. The probe is `find_placed_call` on a reference no call carries
(`GET /calls?reference=`, snapshots/2026-10-29/pages/api-reference/calls/list-calls.md:
484-493): the same host, key and resource as the dial, and an empty answer is healthy. At
most one probe per `PROBE_INTERVAL_S` platform-wide, so a held platform asks the vendor
twice a minute however many dials are refused.

RESUME: a probe that answers lifts the hold, and for `RESUME_RAMP_S` afterwards the tick
spends half its budget, so a backlog of held contacts is spread over several ticks instead
of arriving at the vendor in one burst. Nothing else is special on resume: every held
contact goes back through the ordinary claim, which re-reads calling hours, DNC, the
compliance gate and the big red switch at the moment it dials.

FAILS OPEN on a Redis error: the dial then meets the vendor's own answer, and a dial path
that stops because Redis hiccuped is an outage of its own (`dial_lines._held_scope` takes
the same stance).
"""

from __future__ import annotations

import math
import time
from typing import Final, Protocol, runtime_checkable

from apps.api.core.alerting import alert, resolve_alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.engine import get_engine
from apps.api.engine.health import SPIKE_WINDOW_MINUTES
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.engine.vendor_http import (
    ENGINE_UNREACHABLE_CODE,
    EngineRejectedError,
    EngineUnreachableError,
)

log = get_logger(__name__)

#: The code a dial is refused under while the hold is on. Nothing was dialled.
OUTAGE_HOLD_CODE: Final = "engine_outage_hold"

#: The engine failures that count toward the hold and that leave a contact waiting rather
#: than spending its attempt.
ENGINE_DOWN_CODES: Final = frozenset({ENGINE_UNREACHABLE_CODE, OUTAGE_HOLD_CODE})

TRIP_AFTER_FAILURES: Final = 2
#: The run of failures must fall inside the engine-spike alarm's window, so two timeouts an
#: hour apart are two blips, not an outage.
FAILURE_WINDOW_S: Final = SPIKE_WINDOW_MINUTES * 60
#: One campaign dispatch tick (`campaign_dispatch.TICK_INTERVAL_S`).
PROBE_INTERVAL_S: Final = 30.0
#: A hold nobody probes still ends: past this the next dial meets the vendor itself, and two
#: more failures put the hold back. Long enough that no real outage is cut short by it.
HOLD_MAX_S: Final = 3600.0
RESUME_RAMP_S: Final = 120.0

#: The reference the probe asks about. No dial carries it: ours are `calls.id` uuids.
PROBE_REFERENCE: Final = "calevate-dial-hold-probe"

#: One set of keys for the platform: a deployment runs one engine (`ENGINE`).
_PREFIX: Final = "calevate:engine:outage"
_PARTS: Final = ("failures", "hold", "probe", "resumed")


def _key(part: str) -> str:
    return f"{_PREFIX}:{part}"


def state_keys() -> tuple[str, ...]:
    """Every Redis key the hold keeps."""
    return tuple(_key(part) for part in _PARTS)


@runtime_checkable
class _ReadsPlacedCalls(Protocol):
    async def find_placed_call(self, reference: str) -> str | None: ...


def counts_as_engine_down(exc: BaseException) -> bool:
    """Is this dial failure the ENGINE's — no answer at all, or a 5xx it did not document
    as a refusal — rather than an answer about the request?"""
    if isinstance(exc, EngineUnreachableError):
        return True
    return (
        isinstance(exc, EngineRejectedError)
        and exc.vendor_status is not None
        and exc.vendor_status >= 500
        and not exc.request_refused
    )


def outage_hold_error() -> ProblemError:
    """The refusal for a dial while the hold is on. No provider is named (D-679)."""
    return ProblemError(
        kind="transient",
        code=OUTAGE_HOLD_CODE,
        title="Calls are paused for a moment",
        detail="The phone system is not answering right now, so this call was not placed.",
        remediation="It will be tried again automatically once the phone system answers.",
        failure_stage="CORE_LOGIC",
    )


async def note_dial_failure() -> None:
    """Count one dial the engine failed; trip the hold on the `TRIP_AFTER_FAILURES`th."""
    try:
        redis = get_redis()
        key = _key("failures")
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(key, int(FAILURE_WINDOW_S))
        if count < TRIP_AFTER_FAILURES:
            return
        tripped = await redis.set(
            _key("hold"), str(int(time.time())), nx=True, px=int(HOLD_MAX_S * 1000)
        )
    except Exception as exc:
        log.warning("engine_dial_hold_unavailable", extra={"error": type(exc).__name__})
        return
    if tripped:
        log.warning("engine_dial_hold_started", extra={"engine": get_engine().name})
        alert(
            "CORE_LOGIC",
            "engine_dial_hold",
            detail=(
                f"{TRIP_AFTER_FAILURES} dials in a row got no answer (or a 5xx) from the voice "
                "platform, so every outbound dial is held. Contacts wait with their attempts "
                f"refunded; a read probe every {int(PROBE_INTERVAL_S)}s lifts the hold"
            ),
            engine=get_engine().name,
        )


async def note_dial_success() -> None:
    """A dial the engine accepted ends the run of failures."""
    try:
        await get_redis().delete(_key("failures"))
    except Exception as exc:
        log.warning("engine_dial_hold_unavailable", extra={"error": type(exc).__name__})


async def hold_is_on() -> bool:
    """Whether dials are held, read without probing. False when Redis cannot say."""
    try:
        return bool(await get_redis().exists(_key("hold")))
    except Exception as exc:
        log.warning("engine_dial_hold_unavailable", extra={"error": type(exc).__name__})
        return False


async def _engine_answers() -> bool:
    engine = get_engine()
    if not isinstance(engine, _ReadsPlacedCalls):
        # Nothing to ask: an engine we cannot probe is not held on our guess.
        return True
    try:
        with in_workspace(None):
            await engine.find_placed_call(PROBE_REFERENCE)
    except Exception as exc:
        log.info("engine_dial_hold_probe_failed", extra={"error": type(exc).__name__})
        return False
    return True


async def _lift() -> None:
    redis = get_redis()
    await redis.delete(_key("hold"), _key("failures"))
    await redis.set(_key("resumed"), "1", px=int(RESUME_RAMP_S * 1000))
    log.warning("engine_dial_hold_lifted", extra={"engine": get_engine().name})
    resolve_alert("CORE_LOGIC", "engine_dial_hold")


async def dial_hold_refusal() -> ProblemError | None:
    """The refusal for a dial while the engine is held, or None when it may dial.

    Probes when the hold is on and no process has probed in the last `PROBE_INTERVAL_S`;
    a probe that answers lifts the hold for this dial and every one after it."""
    try:
        redis = get_redis()
        if not await redis.exists(_key("hold")):
            return None
        if not await redis.set(_key("probe"), "1", nx=True, px=int(PROBE_INTERVAL_S * 1000)):
            return outage_hold_error()
    except Exception as exc:
        log.warning("engine_dial_hold_unavailable", extra={"error": type(exc).__name__})
        return None
    if not await _engine_answers():
        return outage_hold_error()
    try:
        await _lift()
    except Exception as exc:
        log.warning("engine_dial_hold_unavailable", extra={"error": type(exc).__name__})
    return None


async def resume_budget(budget: int) -> int:
    """The share of `budget` a tick may spend just after the hold lifted: half, at least
    one line, for `RESUME_RAMP_S`; all of it otherwise."""
    if budget <= 1:
        return budget
    try:
        ramping = bool(await get_redis().exists(_key("resumed")))
    except Exception:
        return budget
    return math.ceil(budget / 2) if ramping else budget


__all__ = [
    "ENGINE_DOWN_CODES",
    "FAILURE_WINDOW_S",
    "HOLD_MAX_S",
    "OUTAGE_HOLD_CODE",
    "PROBE_INTERVAL_S",
    "PROBE_REFERENCE",
    "RESUME_RAMP_S",
    "TRIP_AFTER_FAILURES",
    "counts_as_engine_down",
    "dial_hold_refusal",
    "hold_is_on",
    "note_dial_failure",
    "note_dial_success",
    "outage_hold_error",
    "resume_budget",
    "state_keys",
]

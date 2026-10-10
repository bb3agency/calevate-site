"""Is a platform AI provider's MAIN leg failing? Tell the admin, and keep telling them.

WHY THIS EXISTS. The dashboard assistant's main model failed in production and the Sarvam
standby answered; the only trace was a WARNING line nobody reads. Every leg here already
degrades gracefully — the copilot falls back, extraction files `_model`, embeddings leave
chunks `pending` — which is exactly why an outage on one of them is silent. The founder's
decision (10 Oct 2026): when a main leg is failing, the admin is mailed, reminded hourly
until it works, and told once when it does.

THE CONDITION is per `(leg, provider)` — `copilot/google` and `embeddings/azure` are two
outages — and it opens when EITHER

* `FAILURE_THRESHOLD` failures land inside `FAILURE_WINDOW_S` (a fixed window that starts
  at the first failure; the busy-leg case), OR
* `FAILURE_THRESHOLD` failures in a row with no success between them, however far apart
  (`STREAK_TTL_S` bounds "however far"; the quiet-leg case, where three failures may take
  an hour to happen and are still three out of three).

One failure is a blip and alerts nobody. A success ends the streak and, if the condition
was open, closes the episode through `alerting.resolve_alert`, which sends the one
"cleared" line. While open, every failure re-fires `alert()`; `alerting`'s own admission
collapses those to one notice per fifteen minutes, and `REPEAT_WHILE_OPEN_S` turns that
into one reminder email an hour.

COUNTED IN REDIS, because the legs run in `api` (copilot) and in `workers` (extraction,
embeddings), each with several processes, and a per-process count would need three
failures in ONE process. One Lua script per event keeps count-and-decide atomic, the
shape `core/alert_admission.py` uses for the same reason.

IT NEVER BREAKS THE REQUEST PATH AND IT FAILS OPEN FOR LOGGING. Every hook is awaited on a
hot path (a streaming answer, a post-call job), so the Redis round trip is bounded by
`REDIS_BUDGET_S` and any failure — unreachable, slow, a script error — is one WARNING and
a return. What is lost when Redis is down is the alert, never the request; the provider
failure itself is still logged at the call site with its status and type.

HARD RULE 6. What travels is our leg name, our provider name, an HTTP status and an
exception CLASS name. Never a response body: a provider's error body quotes the request,
and the request is a transcript or a person's question.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, Final, Literal, cast

import httpx

from apps.api.core.alerting import alert, resolve_alert
from apps.api.core.logging import get_logger

log = get_logger("calevate.provider_health")

#: The platform AI legs whose MAIN provider failing degrades the product. A closed set of
#: our own words, because it becomes part of an alert fingerprint.
AiLeg = Literal[
    "copilot",
    "standby",
    "extraction",
    "embeddings",
    "memory",
    "kb_gloss",
    "ocr",
    "script",
    "lead_fields",
    "teach",
]

ALARM_CODE: Final = "ai_provider_degraded"
FAILURE_THRESHOLD: Final = 3
FAILURE_WINDOW_S: Final = 600
#: How long a streak survives with no new failure. Long enough to span a quiet leg's gaps,
#: short enough that last night's two failures do not join this morning's one.
STREAK_TTL_S: Final = 6 * 3600
#: The "open" marker's lifetime, refreshed by every failure. A marker that outlives all
#: traffic is harmless: the sweep closes the episode after an hour of quiet anyway.
OPEN_TTL_S: Final = 6 * 3600
#: The hot path's bound on one Redis round trip.
REDIS_BUDGET_S: Final = 0.25
KEY_PREFIX: Final = "provider_health"

_FAILURE_LUA: Final = """
local window = redis.call('INCR', KEYS[1])
if window == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
local streak = redis.call('INCR', KEYS[2])
redis.call('PEXPIRE', KEYS[2], ARGV[2])
local threshold = tonumber(ARGV[3])
if window >= threshold or streak >= threshold then
  redis.call('SET', KEYS[3], '1', 'PX', ARGV[4])
  return {1, window, streak}
end
return {0, window, streak}
"""

#: A success ends the streak; if the condition was open it also empties the window, so a
#: relapse has to earn its alert again rather than inheriting the old episode's count.
_SUCCESS_LUA: Final = """
redis.call('DEL', KEYS[2])
local was_open = redis.call('DEL', KEYS[3])
if was_open == 1 then redis.call('DEL', KEYS[1]) end
return was_open
"""


def _keys(leg: str, provider: str) -> list[str]:
    base = f"{KEY_PREFIX}:{leg}:{provider}"
    return [f"{base}:window", f"{base}:streak", f"{base}:open"]


def failure_fields(exc: BaseException) -> dict[str, Any]:
    """`{"error": <class>, "status": <HTTP status or None>}` — what a failure log carries.

    The status is the difference between "we are rate-limited" (429) and "they are down"
    (503), and it is all of the response this reads: never the body (hard rule 6).
    """
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    return {"error": type(exc).__name__, "status": status}


async def _eval(script: str, keys: list[str], args: list[Any]) -> Any:
    from apps.api.core.redis import get_redis

    redis = get_redis()
    return await asyncio.wait_for(
        cast("Awaitable[Any]", redis.eval(script, len(keys), *keys, *args)),
        timeout=REDIS_BUDGET_S,
    )


async def note_failure(leg: AiLeg, provider: str, exc: BaseException) -> None:
    """Count one main-leg failure; alert when the condition is (or stays) open. Never raises."""
    fields = failure_fields(exc)
    try:
        reply = await _eval(
            _FAILURE_LUA,
            _keys(leg, provider),
            [FAILURE_WINDOW_S * 1000, STREAK_TTL_S * 1000, FAILURE_THRESHOLD, OPEN_TTL_S * 1000],
        )
        degraded = bool(int(reply[0]))
    except Exception as failure:
        log.warning(
            "provider_health_unavailable",
            extra={"leg": leg, "provider": provider, "reason": type(failure).__name__},
        )
        return
    if not degraded:
        return
    status = fields["status"]
    alert(
        "CORE_LOGIC",
        "ai_provider_degraded",
        detail=(
            f"The {leg} leg's main provider ({provider}) is failing: {fields['error']}"
            + (f", HTTP {status}" if status is not None else "")
            + f". Threshold: {FAILURE_THRESHOLD} failures in {FAILURE_WINDOW_S // 60} minutes"
            " or in a row."
        ),
        episode=f"{leg}:{provider}",
        leg=leg,
        provider=provider,
        error=str(fields["error"]),
        status=str(status) if status is not None else "none",
    )


async def note_success(leg: AiLeg, provider: str) -> None:
    """End the streak; if the condition was open, close it and send the one clear line."""
    try:
        was_open = int(await _eval(_SUCCESS_LUA, _keys(leg, provider), []))
    except Exception as failure:
        log.warning(
            "provider_health_unavailable",
            extra={"leg": leg, "provider": provider, "reason": type(failure).__name__},
        )
        return
    if was_open:
        log.info("ai_provider_recovered", extra={"leg": leg, "provider": provider})
        resolve_alert("CORE_LOGIC", ALARM_CODE, episode=f"{leg}:{provider}")


@asynccontextmanager
async def watch(leg: AiLeg, provider: str) -> AsyncIterator[None]:
    """Wrap ONE main-leg provider call: an `httpx.HTTPError` or `TimeoutError` out of the
    block is a failure (re-raised untouched), a clean exit is a success.

    Anything else — a JSON parse, a truncation — is neither: the provider answered, and
    whether the answer was usable is the caller's business, not an outage.
    """
    try:
        yield
    except (httpx.HTTPError, TimeoutError) as exc:
        await note_failure(leg, provider, exc)
        raise
    await note_success(leg, provider)


__all__ = [
    "ALARM_CODE",
    "FAILURE_THRESHOLD",
    "FAILURE_WINDOW_S",
    "AiLeg",
    "failure_fields",
    "note_failure",
    "note_success",
    "watch",
]

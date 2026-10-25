"""Run an in-call action at most once per call, per action, per meaningful arguments.

ThinnestAI never retries an action, but when the primary model fails mid-turn the turn runs
again on a backup model, which can call the same action a second time (ThinnestAI's email of
11 Oct 2026, VENDOR-STATED; the live docs describe the backup only as `rescues` in a call's
quality figures, docs.thinnest.ai api-reference/webhooks "Call quality", read 11 Oct 2026).
A booking, a message or a payment link made twice is not undone, so the second call answers
with the first one's answer.

HOW. `SET key "pending" NX EX` claims the run; the winner runs it and stores its answer under
the same key; a repeat reads the stored answer. A repeat that arrives while the first is
still running waits for it inside `WAIT_S`, then answers that it is already in hand rather
than running it again. An answer meaning nothing was done (`NOT_DONE`) is not kept, so a
later honest retry can still run.

Redis and not a table: the guard lives for one call, and the answer it stores is the small
`{status, say, …}` body the agent already heard. If Redis cannot be read the action runs
unguarded: the two actions whose repeat costs money or reaches the caller (WhatsApp and
payment links) keep their own per-call cap, which refuses when Redis is down
(`actions/in_call.PER_CALL_LIMITS`).

HARD RULE 6: the key is a hash, so no argument value is stored in a key name; the stored
answer is what the agent was told, which never carries the caller's number.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

log = get_logger(__name__)

#: Longer than the longest call (20 minutes on this engine) with room for a late re-run.
TTL_S: Final = 3 * 3600
#: How long a repeat waits for the first run's answer: inside the platform's ten seconds.
WAIT_S: Final = 6.0
_POLL_S: Final = 0.2
_PENDING: Final = "pending"

#: Answers that mean nothing happened, which a repeat runs again.
NOT_DONE: Final = frozenset({"unavailable", "caller_not_matched", "no_call"})

IN_HAND_SAY: Final = (
    "This is already being done from a moment ago. Do NOT do it again. Tell the caller it is "
    "in hand."
)


def _canonical(value: Any) -> str:
    """Case, spacing and Unicode form do not make two arguments different: a backup model
    re-running the turn may write the same value differently."""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(text.split())


def once_key(call_ref: str, action: str, args: Mapping[str, Any]) -> str:
    material = json.dumps(
        [call_ref, action, sorted((k, _canonical(v)) for k, v in args.items())],
        ensure_ascii=False,
    )
    return f"incall:once:{hashlib.sha256(material.encode()).hexdigest()}"


async def once_per_call(
    *,
    call_ref: str,
    action: str,
    args: Mapping[str, Any],
    run: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """`run()`'s answer, run once for this call, action and arguments."""
    key = once_key(call_ref, action, args)
    try:
        redis = get_redis()
        claimed = await redis.set(key, _PENDING, nx=True, ex=TTL_S)
    except Exception as exc:
        log.warning(
            "in_call_once_unreadable", extra={"action": action, "error": type(exc).__name__}
        )
        return await run()
    if not claimed:
        return await _answer_of_first(key, action, run)
    return await _run_claimed(key, action, run)


async def _run_claimed(
    key: str, action: str, run: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    """Run as the holder of the claim, then keep or release the answer."""
    try:
        answer = await run()
    except BaseException:
        await _forget(key)
        raise
    if answer.get("status") in NOT_DONE:
        await _forget(key)
    else:
        try:
            await get_redis().set(key, json.dumps(answer), ex=TTL_S)
        except Exception as exc:
            log.warning(
                "in_call_once_unsaved", extra={"action": action, "error": type(exc).__name__}
            )
    return answer


async def _answer_of_first(
    key: str, action: str, run: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_S
    while True:
        reclaimed = False
        try:
            held = await get_redis().get(key)
            # The first run did nothing (its answer was not kept) or Redis lost the key.
            # CLAIM it again rather than run outright: several repeats can be waiting, and
            # each running on seeing the key gone is the double booking this module exists
            # to prevent. Only the one that wins the claim runs.
            if held is None:
                reclaimed = bool(await get_redis().set(key, _PENDING, nx=True, ex=TTL_S))
        except Exception:
            # A read error mid-wait is not "absent": the first run claimed the key and may
            # still be acting, so keep waiting and answer "in hand" at the deadline.
            held = _PENDING
        if reclaimed:
            return await _run_claimed(key, action, run)
        if held is not None and held != _PENDING:
            try:
                answer = json.loads(held)
            except ValueError:
                answer = None
            if isinstance(answer, dict):
                log.info("in_call_action_repeat_answered", extra={"action": action})
                return answer
        if loop.time() >= deadline:
            log.info("in_call_action_repeat_in_hand", extra={"action": action})
            return {"status": "in_hand", "say": IN_HAND_SAY}
        await asyncio.sleep(_POLL_S)


async def _forget(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception as exc:
        log.warning("in_call_once_unforgotten", extra={"error": type(exc).__name__})


__all__ = ["IN_HAND_SAY", "NOT_DONE", "TTL_S", "WAIT_S", "once_key", "once_per_call"]

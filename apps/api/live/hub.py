"""One Redis subscription per API process, fanned out to its open streams (D-774).

A pub/sub connection per browser tab would scale Redis connections with people looking at
screens; one pattern subscription per process scales them with processes, and the fan-out
to that process's streams is a dict lookup. Each stream gets a bounded queue: a stream
whose browser cannot keep up is told to resync instead of being allowed to grow memory.

The subscription uses its own client (`socket_timeout=None`) rather than
`core.redis.get_redis()`, whose two-second socket timeout is right for a command and
wrong for a connection that waits for messages, and because a subscribed connection cannot
run other commands (BACKEND-PATTERNS §10: dedicated pub/sub connections).
"""

from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final

from pydantic import ValidationError
from redis.asyncio import Redis

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.live.schemas import LiveChange
from apps.api.live.topics import CHANNEL_PREFIX

log = get_logger(__name__)

#: Notes a stream may hold unread before it is told to resync instead.
QUEUE_MAX: Final = 64
#: How long `get_message` blocks before the loop checks whether anyone still listens.
_POLL_S: Final = 5.0
_BACKOFF_MAX_S: Final = 30.0


@dataclass(eq=False)
class Subscription:
    channel: str
    queue: asyncio.Queue[LiveChange] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAX)
    )
    #: Set when a note was dropped (queue full) or the hub lost Redis: the stream must
    #: send `resync` before anything else.
    resync: str | None = None
    #: Set when the process is stopping: the stream says so and ends, so uvicorn's drain
    #: is not held open by a response that would otherwise run for half an hour.
    closing: bool = False
    wake: asyncio.Event = field(default_factory=asyncio.Event)


class LiveHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[Subscription]] = {}
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()

    @property
    def listeners(self) -> int:
        return sum(len(subs) for subs in self._subs.values())

    def subscribe(self, channel: str) -> Subscription:
        sub = Subscription(channel=channel)
        self._subs.setdefault(channel, set()).add(sub)
        if self._task is None or self._task.done():
            self._connected.clear()
            self._task = asyncio.get_running_loop().create_task(self._run())
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.channel)
        if subs is None:
            return
        subs.discard(sub)
        if not subs:
            del self._subs[sub.channel]

    async def wait_connected(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout_s)
        except TimeoutError:
            return False
        return True

    def deliver(self, channel: str, data: str) -> None:
        """Hand one published note to every stream on `channel`."""
        subs = self._subs.get(channel)
        if not subs:
            return
        try:
            note = LiveChange.model_validate_json(data)
        except ValidationError:
            # Only this application publishes under the prefix; anything else is a bug or
            # a stranger with Redis access, and either way it is not forwarded.
            log.warning("live_note_malformed", extra={"channel_prefix": CHANNEL_PREFIX})
            return
        for sub in subs:
            try:
                sub.queue.put_nowait(note)
            except asyncio.QueueFull:
                sub.resync = "fell_behind"
            sub.wake.set()

    def begin_shutdown(self) -> None:
        """Tell every open stream on this process to end now."""
        for subs in self._subs.values():
            for sub in subs:
                sub.closing = True
                sub.wake.set()

    def _resync_all(self) -> None:
        for subs in self._subs.values():
            for sub in subs:
                sub.resync = "subscription_restored"
                sub.wake.set()

    async def _run(self) -> None:
        backoff = 1.0
        lost = False
        while self._subs:
            client = Redis.from_url(
                get_settings().redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=None,
                health_check_interval=30,
            )
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                self._connected.set()
                if lost:
                    self._resync_all()
                    log.info("live_subscription_restored")
                lost = False
                backoff = 1.0
                while self._subs:
                    message = await pubsub.get_message(timeout=_POLL_S)
                    if message is not None and message.get("type") == "pmessage":
                        self.deliver(str(message["channel"]), str(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected.clear()
                lost = True
                log.warning("live_subscription_lost", extra={"error": type(exc).__name__})
            finally:
                # Closing a broken connection can fail too; there is nothing left to save.
                with suppress(Exception):
                    await pubsub.aclose()
                with suppress(Exception):
                    await client.aclose()
            if self._subs and lost:
                await asyncio.sleep(random.uniform(0, backoff))
                backoff = min(backoff * 2, _BACKOFF_MAX_S)
        self._connected.clear()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._connected.clear()


_hub: LiveHub | None = None


def get_hub() -> LiveHub:
    global _hub
    if _hub is None:
        _hub = LiveHub()
    return _hub


def end_live_streams() -> None:
    """Every open stream on this process ends at its next wake-up. Called on SIGTERM."""
    if _hub is not None:
        _hub.begin_shutdown()


async def stop_hub() -> None:
    global _hub
    if _hub is not None:
        await _hub.stop()
        _hub = None


__all__ = ["QUEUE_MAX", "LiveHub", "Subscription", "end_live_streams", "get_hub", "stop_hub"]

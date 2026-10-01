"""Who is speaking on a live call: the ephemeral store and the browser's stream (D-656).

The voice worker posts a speaking state (`calevate_shared.worker_api.SpeakingStateIn`) to
`POST /v1/worker/calls/{ref}/speaking`; the client console reads it through
`GET /v1/calls/{call_id}/speaking`, a `text/event-stream` under the client session.

**REDIS WITH A SHORT TTL, NOT A TABLE.** The state is worth something for about a second and
nothing after the call: no reader needs history, nothing reconciles against it, and a row
per change would put a write on the database for every breath a caller takes. A key per
call — `calevate:live:speaking:<tenant>:<engine call ref>` — expires on its own, so a
container that dies mid-sentence leaves an "agent is speaking" behind for at most
`SPEAKING_TTL_S`. The worker re-sends a non-silent state every `worker`-side heartbeat to
keep a long sentence alive (`voice_worker/speaking.HEARTBEAT_S`, deliberately a third of
the TTL so one lost heartbeat does not blank the indicator).

**THE TENANT IS IN THE KEY, AND BOTH SIDES DERIVE IT FROM SOMETHING THEY CANNOT FORGE.** The
writer parses it out of the ref the worker presents (`tenant_of_pipecat_ref`, the same parse
every `/v1/worker` route does); the reader takes it from the principal and finds the ref by
reading `calls` under that tenant's RLS. A browser therefore cannot name another tenant's
key: a call it cannot see is a 404 before any key is built.

**THE BROWSER GETS A STREAM, NOT A POLL, AND THE EVIDENCE IS THE EDGE.** The UI needs the
indicator within about a second. Polling at 1 Hz is 60 requests a minute per open call
screen against nginx's `client_api` zone of 120 r/m per address
(`infra/nginx/rate-zones.conf.template:46`) — two tabs behind one office NAT exhaust it and
every other screen of the console 429s. One SSE request per call screen costs that zone
one request per `MAX_STREAM_S`. Nothing at the edge needs to change for it:
`fastapi.sse.EventSourceResponse` sends `X-Accel-Buffering: no` and `Cache-Control:
no-cache` and a `: ping` comment every 15 s (`fastapi/routing.py:631-634`,
`fastapi/sse.py:231-235`), inside the api vhost's `proxy_read_timeout 60s`
(`infra/nginx/calevate.conf.template:568`), and no nginx block gzips. That is the same path
`POST /v1/copilot/ask` already streams over, and `lib/copilot/sse.ts` is the browser's
parser for both.

**WHY THE PAYLOAD IS THE STATE AND NOT AN INVALIDATION HINT (D-24 said hints).** D-24's
hint-then-refetch shape exists so a stream never carries data a refetch would have to
re-authorise. Here the refetch would be this same tenant-checked read, so a hint would
double the requests and add a round trip to a one-second budget, and the frame carries
nothing beyond a side and a timestamp.

**THE SERVER READS REDIS ON A SHORT TICK RATHER THAN SUBSCRIBING.** A pub/sub subscription
is a dedicated Redis connection per open stream (BACKEND-PATTERNS §10: "dedicated pub/sub
connections") and a second delivery path to keep consistent with the key; a `GET` every
`POLL_S` on the shared pool is one cheap round trip to a local Redis and the key stays the
only truth. Call status is re-read from Postgres every `STATUS_RECHECK_S` on a fresh,
short `tenant_session`, never on a connection held for the stream.

HARD RULE 6: nothing here logs a ref, a number or any content — ids and counts only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from calevate_shared.events import TERMINAL_STATUSES
from calevate_shared.worker_api import SpeakingSide, SpeakingStateIn
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: The key namespace. Ephemeral and expiring, like every other key in Redis here.
KEY_PREFIX: Final = "calevate:live:speaking"

#: How long a state outlives its last write. Three worker heartbeats.
SPEAKING_TTL_S: Final = 30

#: How often an open stream looks at the key. 250 ms leaves three quarters of the
#: one-second budget for the worker's debounce and the two network legs.
POLL_S: Final = 0.25

#: How often an open stream re-reads the call's status, to end when the call does.
STATUS_RECHECK_S: Final = 2.0

#: The longest one stream stays open. The hook reconnects while the call is still live, so
#: this bounds how long a forgotten tab holds a worker coroutine, not how long a call can be
#: watched.
MAX_STREAM_S: Final = 600.0

#: Keep the newer state: write only when no state is held or the held `seq` is lower.
#: `cjson` is part of Redis's Lua runtime. Returns 1 when written, 0 when refused.
_CAS_LUA: Final = """
local held = redis.call('GET', KEYS[1])
if held then
  local ok, decoded = pcall(cjson.decode, held)
  if ok and type(decoded) == 'table' and tonumber(decoded['seq']) ~= nil
     and tonumber(decoded['seq']) >= tonumber(ARGV[2]) then
    return 0
  end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[3]))
return 1
"""


def speaking_key(tenant_id: UUID, engine_call_id: str) -> str:
    return f"{KEY_PREFIX}:{tenant_id}:{engine_call_id}"


def _store_unavailable() -> ProblemError:
    return ProblemError(
        kind="transient",
        code="live_state_unavailable",
        title="Live call state is unavailable",
        detail="The live call state could not be recorded right now.",
        remediation="Nothing to do: the next state the call sends replaces this one.",
    )


async def record_speaking(tenant_id: UUID, engine_call_id: str, state: SpeakingStateIn) -> bool:
    """Store `state` for the call unless a newer one is already held. True when stored."""
    value = json.dumps(
        {"speaker": state.speaker, "seq": state.seq, "at": state.at.isoformat()},
        separators=(",", ":"),
    )
    try:
        written = await get_redis().eval(  # type: ignore[misc]
            _CAS_LUA,
            1,
            speaking_key(tenant_id, engine_call_id),
            value,
            str(state.seq),
            str(SPEAKING_TTL_S),
        )
    except RedisError as failure:
        log.warning("live_speaking_store_failed", extra={"reason": type(failure).__name__})
        raise _store_unavailable() from failure
    return bool(written)


# --- the browser's read -------------------------------------------------------------


class CallSpeakingOut(BaseModel):
    """One frame of `GET /v1/calls/{call_id}/speaking`.

    `speaker` is who is audible now, `None` for silence or for a state nobody has reported.
    `live` is False on the last frame of a stream that ended because the call did; a stream
    that ends with `live` still True ended for another reason and may be reopened.
    `since` is when the current state began on the worker's clock, `None` when unknown.
    """

    speaker: Literal["caller", "agent"] | None
    live: bool
    since: datetime | None


@dataclass(frozen=True, slots=True)
class LiveCall:
    """A call of the principal's tenant, resolved under RLS before the stream opens."""

    tenant_id: UUID
    call_id: UUID
    engine_call_id: str | None
    status: str


_CALL_SQL: Final = "SELECT engine_call_id, status FROM calls WHERE id = :id"


async def resolve_live_call(tenant_id: UUID, call_id: UUID) -> LiveCall:
    """The call, or 404 — under RLS, so another tenant's call is the same 404."""
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_CALL_SQL), {"id": call_id})).first()
    if row is None:
        raise ProblemError.not_found("Call")
    return LiveCall(tenant_id=tenant_id, call_id=call_id, engine_call_id=row[0], status=str(row[1]))


async def read_speaking(
    tenant_id: UUID, engine_call_id: str
) -> tuple[SpeakingSide | None, datetime | None]:
    """The held state, or `(None, None)` when there is none or it cannot be read.

    A read failure is silence rather than an error frame: the indicator is decoration on a
    call screen, and the next tick tries again.
    """
    try:
        raw = await get_redis().get(speaking_key(tenant_id, engine_call_id))
    except RedisError as failure:
        log.warning("live_speaking_read_failed", extra={"reason": type(failure).__name__})
        return None, None
    if raw is None:
        return None, None
    try:
        held = json.loads(raw)
        speaker = held["speaker"]
        since = datetime.fromisoformat(held["at"])
    except (ValueError, KeyError, TypeError):
        return None, None
    if speaker not in ("caller", "agent"):
        return None, since
    return speaker, since


async def _call_status(tenant_id: UUID, call_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT status FROM calls WHERE id = :id"), {"id": call_id})
        ).first()
    return None if row is None else str(row[0])


#: Seams for the tests: the clock the stream ends by, and how it waits between ticks.
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


async def speaking_frames(
    call: LiveCall,
    *,
    clock: Clock | None = None,
    sleep: Sleep = asyncio.sleep,
) -> AsyncIterator[CallSpeakingOut]:
    """Frames for one open stream: the current state, then each change, then the end.

    The first frame is sent at once so the browser knows the stream is up. A change is a
    different `speaker`; a state re-sent by a heartbeat is not a change and is not sent.
    """
    now = clock or asyncio.get_running_loop().time
    if call.status in TERMINAL_STATUSES or call.engine_call_id is None:
        # A call with no engine ref has never been reached by a worker and never will be.
        yield CallSpeakingOut(speaker=None, live=call.status not in TERMINAL_STATUSES, since=None)
        return
    opened = now()
    next_status_check = opened + STATUS_RECHECK_S
    sent: tuple[SpeakingSide | None, datetime | None] | None = None
    while True:
        speaker, since = await read_speaking(call.tenant_id, call.engine_call_id)
        if sent is None or sent[0] != speaker:
            sent = (speaker, since)
            yield CallSpeakingOut(speaker=speaker, live=True, since=since)
        at = now()
        if at >= next_status_check:
            next_status_check = at + STATUS_RECHECK_S
            status = await _call_status(call.tenant_id, call.call_id)
            if status is None or status in TERMINAL_STATUSES:
                yield CallSpeakingOut(speaker=None, live=False, since=None)
                return
        if at - opened >= MAX_STREAM_S:
            return
        await sleep(POLL_S)


__all__ = [
    "KEY_PREFIX",
    "MAX_STREAM_S",
    "POLL_S",
    "SPEAKING_TTL_S",
    "STATUS_RECHECK_S",
    "CallSpeakingOut",
    "LiveCall",
    "read_speaking",
    "record_speaking",
    "resolve_live_call",
    "speaking_frames",
    "speaking_key",
]

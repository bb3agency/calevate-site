"""Cross-process alert admission: one suppression window and one budget for a SERVICE,
not one per worker process.

WHY THIS EXISTS. `alerting.py` holds its suppression window (`_last_sent`), its
suppression counts (`_suppressed`) and its token bucket (`_tokens`) in module globals.
That was correct while every service ran one process, and it stopped being correct
without anybody noticing: `compose.prod.yml` runs voice-runtime with
`--workers=${VOICE_RUNTIME_WORKERS:-4}` (D-55's measured answer to the 500ms ack budget).
Four uvicorn workers are four PROCESSES, so today production has

* four independent 15-minute windows — one bad deploy pages the operator up to four
  times for the identical fingerprint, which is the "4,000 copies of one bad deploy"
  failure the window was added to prevent, just with a smaller number; and
* four independent token buckets — `ALERT_BUDGET_PER_HOUR` is 20/hour BY DESIGN and is
  silently 80/hour in production. The bucket exists to make a storm legible on a phone,
  and a bound that scales with worker count is not a bound.

The second is the one that would have been hardest to diagnose from the inbox, because
the symptom is "the rate limit does not seem to work" rather than an error.

--------------------------------------------------------------------------------
FAIL OPEN, ABSOLUTELY, AND THAT IS WHAT KEEPS `alerting.py`'s PROMISE
--------------------------------------------------------------------------------

`alerting.py`'s docstring made a load-bearing claim: the alert path "touches no database
and no Redis, so it survives the failures it reports" — because the alarms that matter
most are the ones that fire when infrastructure is broken, and an alert routed through a
broken component is an alert nobody gets.

This module puts Redis on that path, so it has to answer the claim rather than quietly
invalidate it. It answers it by only ever being able to SUPPRESS:

* the ERROR log line is still written first and unconditionally by `alert()`, before
  anything here runs, and it remains the durable record;
* every failure here — unreachable, timeout, script error, garbage reply — returns
  `ADMIT_ON_FAILURE`, which sends;
* so a Redis outage degrades deduplication, never delivery. You get the pre-existing
  per-process behaviour back: up to N copies, which is exactly today's shipped state and
  strictly better than silence.

The risk is therefore inverted in the safe direction: Redis down means MORE alerts, and
never fewer. A design that could drop an alert because a cache was unavailable would be
unacceptable here no matter how much duplication it saved.

--------------------------------------------------------------------------------
ONE SCRIPT, ONE ROUND TRIP, ONE CLOCK
--------------------------------------------------------------------------------

The decision is dedupe AND budget together, and they cannot be two commands: between an
`EXISTS` and a bucket read, another worker admits the same fingerprint and both send.
`EVALSHA` of one Lua script is Redis's own answer to that and is the established shape
for distributed rate limiting, so the whole admission is atomic by construction rather
than by a lock somebody has to remember to take.

The clock is WALL CLOCK, supplied by the caller, and both halves of that are decisions.

*Wall clock, not monotonic.* `alerting._now` is `time.monotonic()`, which is correct for
a single process and meaningless across several: its epoch is arbitrary and different in
every process, so two workers comparing monotonic stamps through Redis would be comparing
unrelated numbers. `time.time()` is the same instant everywhere.

*The caller's clock, not `redis.call('TIME')`.* TIME is the textbook answer when
participants may be on different machines with skewed clocks, and it was the first thing
written here. It is the wrong tool for THIS deployment: every process that shares this
bucket is a `--workers=N` sibling on one host (D-25/D-26 put the whole stack on a single
VPS), so they already share one system clock and TIME buys nothing real. What it costs is
concrete — a clock no test can hold still. `alerting`'s own tests advance a fake clock
past the 15-minute window to prove the alarm re-notifies, and against Redis TIME that
assertion cannot be written at all without sleeping for fifteen minutes. A window whose
expiry is untestable is a window nobody will ever verify again.

So `_now_ms` below is an indirection for exactly the reason `alerting._now` is one. If
the stack ever spans hosts, this is the line to revisit, and the docstring on `_now_ms`
says so.

--------------------------------------------------------------------------------
WHY A SECOND, SYNCHRONOUS CLIENT
--------------------------------------------------------------------------------

`core/redis.py` hands out `redis.asyncio.Redis`, and this code runs on `alerting.py`'s
delivery thread — a plain `threading.Thread` with no event loop, which cannot await. The
alternatives were worse: spinning an event loop per delivery (`asyncio.run` per alert,
on the thread that exists to be cheap), or moving admission back onto the caller's
thread, which is forbidden — `alert()` is reached from a SIGTERM handler and from
voice-runtime's 500ms ack path, and neither may make a network call.

A blocking client on a dedicated daemon thread is the ordinary answer, and it costs
nothing anywhere else: the socket timeouts below bound it, and nothing waits on this
thread except `flush_alerts`, which already has its own deadline.

This adds no dependency — `redis>=5.3` is already declared by `apps/api`, and the sync
client is the same package as the async one. The import is deliberately LAZY (inside the
function) so `apps/voice-runtime`, which imports `alerting` as a library, does not pay
for it at module load (hard rule 3: no heavy imports on the ack path).
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from apps.api.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from redis import Redis

log = get_logger("calevate.alert")

#: Namespace for every key this module owns. Distinct from `ratelimit.KEY_PREFIX` so an
#: operator reading `SCAN` output can tell the two buckets apart at a glance.
KEY_PREFIX: Final = "alerts"

#: Bounded tightly ON PURPOSE. This runs between an alert being dequeued and being sent,
#: so it sits directly in front of the operator learning something is wrong. A Redis that
#: cannot answer in half a second is a Redis we stop waiting for and send without —
#: dedupe is a nicety, delivery is not. `core/redis.py` uses 2s for request paths, which
#: is the right number there and the wrong one here.
SOCKET_TIMEOUT_S: Final = 0.5

#: How long a suppression COUNTER outlives its window. The counter rides the next
#: delivery ("199 further occurrences"), so it must survive slightly longer than the
#: window that fills it or a count is lost to a race with its own expiry. Two windows is
#: generous and costs one small integer per fingerprint.
_COUNTER_TTL_MULTIPLIER: Final = 2


@dataclass(frozen=True, slots=True)
class Admission:
    """What the shared gate decided, and what the delivery should say about it.

    `suppressed` and `rate_limited` are CROSS-PROCESS totals collected since the last
    successful delivery of this fingerprint. `alerting.py` adds them to the counts its
    own in-process pre-filter gathered, so the message reports the true total rather than
    whichever half this worker happened to see.
    """

    admitted: bool
    suppressed: int = 0
    rate_limited: int = 0
    #: True when the verdict is a fallback rather than a decision — Redis could not be
    #: reached or answered nonsense. Kept separate from `admitted` so a caller can log
    #: "we sent because we could not ask" differently from "we sent because we may".
    degraded: bool = False


#: The answer to every failure. Sending a duplicate is a nuisance; withholding an alarm
#: because a cache is down is the failure mode this whole module must not introduce.
ADMIT_ON_FAILURE: Final = Admission(admitted=True, degraded=True)


def _now_ms() -> float:
    """Wall clock in milliseconds, and a FUNCTION so tests can hold it still.

    The same seam as `alerting._now`, for the same reason and with one difference that
    matters: this one is `time.time()` rather than `time.monotonic()`, because the value
    is compared across processes and a monotonic epoch is per-process. See the module
    docstring for why the caller's clock beats `redis.call('TIME')` here — the short
    version is that every sharer of this bucket is a sibling worker on one host, so there
    is only one clock anyway. Revisit this line if the stack ever spans machines.
    """
    return time.time() * 1000.0


# KEYS: 1 dedupe marker · 2 per-fingerprint suppressed counter · 3 bucket hash
#       4 service-wide rate-limited counter
# ARGV: 1 now_ms · 2 window_ms · 3 burst · 4 refill_tokens_per_ms · 5 counter_ttl_ms
#
# Returns {admitted, suppressed, rate_limited}. Written to be read top-to-bottom in the
# order the decision is actually made, because a rate limiter nobody can follow is a
# rate limiter nobody can fix at 3am.
_ADMIT_LUA: Final = """
local now_ms      = tonumber(ARGV[1])
local window_ms   = tonumber(ARGV[2])
local burst       = tonumber(ARGV[3])
local refill_rate = tonumber(ARGV[4])
local counter_ttl = tonumber(ARGV[5])

-- 1. REPEAT SUPPRESSION. The marker HOLDS THE INSTANT it was written and the window is
--    decided by comparing it, not by whether the key still exists. Those are different
--    rules: a TTL expires on Redis's own clock, so with `EXISTS` the window would be
--    governed by two clocks at once and the supplied one would be ignored — which is
--    both untestable and, if the stack ever did span hosts, wrong in a way nobody could
--    reproduce. The TTL below is garbage collection only, and is deliberately longer
--    than the window so it can never expire a decision that is still live.
local sent_at = tonumber(redis.call('GET', KEYS[1]))
if sent_at ~= nil and (now_ms - sent_at) < window_ms then
  redis.call('INCR', KEYS[2])
  redis.call('PEXPIRE', KEYS[2], counter_ttl)
  return {0, 0, 0}
end

-- 2. THE BUCKET, shared by every process of this service. Stored as two fields so the
--    refill is computed from when it was last touched rather than from a tick.
local bucket = redis.call('HMGET', KEYS[3], 'tokens', 'at')
local tokens = tonumber(bucket[1])
local last   = tonumber(bucket[2])
if tokens == nil or last == nil then
  tokens = burst
  last = now_ms
end
tokens = math.min(burst, tokens + ((now_ms - last) * refill_rate))

if tokens < 1 then
  -- Persist the refill even on refusal: otherwise `at` never advances while the bucket
  -- is empty and the next caller recomputes the same starved value forever.
  redis.call('HSET', KEYS[3], 'tokens', tokens, 'at', now_ms)
  redis.call('PEXPIRE', KEYS[3], counter_ttl)
  redis.call('INCR', KEYS[4])
  redis.call('PEXPIRE', KEYS[4], counter_ttl)
  return {0, 0, 0}
end

-- 3. ADMITTED. Spend the token, open the window, and hand back everything that was
--    withheld since the last delivery so the message can report the toll.
tokens = tokens - 1
redis.call('HSET', KEYS[3], 'tokens', tokens, 'at', now_ms)
redis.call('PEXPIRE', KEYS[3], counter_ttl)
redis.call('SET', KEYS[1], now_ms, 'PX', counter_ttl)

local suppressed = tonumber(redis.call('GET', KEYS[2]) or '0')
local limited    = tonumber(redis.call('GET', KEYS[4]) or '0')
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[4])
return {1, suppressed, limited}
"""

_client: Redis | None = None
_script: Any = None
_lock = threading.Lock()


def _connect() -> tuple[Redis, Any]:
    """The blocking client and the registered script, built once per process.

    Lazy for two reasons that agree: importing `redis`'s sync client at module scope
    would put it on voice-runtime's ack-path import graph, and a process that never
    alerts should never open a second Redis connection.
    """
    global _client, _script
    if _client is not None and _script is not None:
        return _client, _script
    with _lock:
        if _client is None or _script is None:
            from redis import Redis as SyncRedis

            from apps.api.core.settings import get_settings

            _client = SyncRedis.from_url(
                get_settings().redis_url,
                decode_responses=True,
                socket_connect_timeout=SOCKET_TIMEOUT_S,
                socket_timeout=SOCKET_TIMEOUT_S,
            )
            _script = _client.register_script(_ADMIT_LUA)
        return _client, _script


def admit(
    *,
    service: str,
    fingerprint: str,
    window_s: float,
    burst: int,
    budget_per_hour: float,
) -> Admission:
    """May THIS process send this alert, given what every other process has sent?

    Never raises. Every path out of here is either a decision or `ADMIT_ON_FAILURE`.

    SCOPED BY SERVICE, not globally, and that is a semantic choice rather than a
    namespacing habit. `api`, `voice-runtime` and `workers` are different programs that
    happen to share a code, and `_subject()` already puts the service in the subject
    line — so a `queue_enqueue_failed` in the workers must not silence the same code in
    voice-runtime, where it means something else and is somebody else's morning. Within
    ONE service, every worker process shares one window and one bucket, which is exactly
    the bound the constants were written to express.
    """
    try:
        client, script = _connect()
        keys = [
            f"{KEY_PREFIX}:sent:{service}:{fingerprint}",
            f"{KEY_PREFIX}:suppressed:{service}:{fingerprint}",
            f"{KEY_PREFIX}:bucket:{service}",
            f"{KEY_PREFIX}:limited:{service}",
        ]
        window_ms = window_s * 1000.0
        reply = script(
            keys=keys,
            args=[
                _now_ms(),
                window_ms,
                burst,
                # Tokens per MILLISECOND, because the script's clock is in milliseconds.
                budget_per_hour / 3_600_000.0,
                window_ms * _COUNTER_TTL_MULTIPLIER,
            ],
            client=client,
        )
    except Exception as exc:
        # Deliberately broad and deliberately not re-raised. The caller is a daemon
        # thread whose job is to get an alarm to a human; there is no failure here worth
        # converting into a lost alert. WARNING rather than ERROR because `alert()`
        # already logged the real problem at ERROR — this line is about the gate, not
        # about the thing being alerted.
        log.warning("alert_admission_unavailable", extra={"reason": type(exc).__name__})
        return ADMIT_ON_FAILURE

    if not isinstance(reply, list) or len(reply) != 3:
        # A reply we cannot read is a reply we do not act on. Same direction as every
        # other failure: send.
        log.warning("alert_admission_unreadable", extra={"reason": type(reply).__name__})
        return ADMIT_ON_FAILURE

    admitted, suppressed, rate_limited = (int(value) for value in reply)
    return Admission(
        admitted=bool(admitted),
        suppressed=suppressed,
        rate_limited=rate_limited,
    )


def forget(*, service: str, fingerprint: str) -> None:
    """Reopen the shared window after a delivery that reached nobody.

    THE SHARED TWIN OF `alerting._forget`, and without it this module would have made
    that function a lie. The window means "a human has been told"; a transport that
    returned False told nobody. Locally that was one `dict.pop` — but the marker is now
    in Redis with a 15-minute TTL, so a single SMTP blip would silence the alarm for the
    whole service until it expired, and every OTHER worker would see the marker and stay
    quiet too. The failure got strictly worse with the fix, which is why this exists.

    The suppression counter is deliberately LEFT ALONE. Occurrences withheld while the
    window was open really did happen, and the next successful delivery should still
    report them; clearing it here would lose the count that makes "still broken, 199
    times" readable.

    Best-effort and silent on failure, like everything else here: the delivery already
    failed and logged, and a second error line about the gate helps nobody.
    """
    try:
        client, _ = _connect()
        client.delete(f"{KEY_PREFIX}:sent:{service}:{fingerprint}")
    except Exception as exc:
        log.warning("alert_admission_forget_failed", extra={"reason": type(exc).__name__})


def reset_admission(*, service: str) -> None:
    """Test seam: forget this service's window, counters and bucket.

    Scoped to one service's four key shapes rather than a `FLUSHDB`, so a test that
    resets alerting cannot silently delete the rate-limiter buckets, the load-shed cache
    or an ARQ queue that another test in the same session is relying on. Best-effort:
    a Redis that is not there has no state to clear.
    """
    try:
        client, _ = _connect()
        # `sent:` and `suppressed:` are per-fingerprint, so they need a scan; the other
        # two are single keys. SCAN rather than KEYS: this runs in tests against a shared
        # developer Redis, and KEYS blocks the server for everyone on it.
        doomed = [f"{KEY_PREFIX}:bucket:{service}", f"{KEY_PREFIX}:limited:{service}"]
        for pattern in (f"{KEY_PREFIX}:sent:{service}:*", f"{KEY_PREFIX}:suppressed:{service}:*"):
            doomed.extend(client.scan_iter(match=pattern, count=100))
        if doomed:
            client.delete(*doomed)
    except Exception as exc:  # pragma: no cover - a test seam must never fail a test
        log.warning("alert_admission_reset_failed", extra={"reason": type(exc).__name__})


def close_admission() -> None:
    """Drop the connection, beside `close_redis` and `close_queue`.

    That sentence was here before anything called it: the API lifespan closed Redis
    alone and the worker's `on_shutdown` flushed spans alone, so this client outlived
    every drain in both processes. `tests/service_teardown_test.py` asserts the calls
    rather than the imports, because a teardown that imports a closer and never reaches
    it reads exactly like one that does.
    """
    global _client, _script
    with _lock:
        if _client is not None:
            # Shutdown is not a place to raise, and a socket that is already gone is the
            # commonest way this is reached.
            with contextlib.suppress(Exception):
                _client.close()
        _client = None
        _script = None


__all__ = [
    "ADMIT_ON_FAILURE",
    "KEY_PREFIX",
    "Admission",
    "admit",
    "close_admission",
    "forget",
    "reset_admission",
]

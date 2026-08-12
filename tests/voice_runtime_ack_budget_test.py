"""Hard rule 3's number, asserted rather than hoped for.

`ack < 500ms` at an engine that delivers at-most-once and never retries (D-31) is a
CORRECTNESS property: a receiver that is slow does not get a second delivery, it loses
the call. The service already MEASURES the budget on every response (`X-Ack-Ms`,
`record_webhook_ack_ms`, an alert past 500ms). Measurement is not enforcement, and
`tests/voice_runtime_security_test.py` says out loud why it declines to assert a
millisecond bound: a CI box under load makes that flaky, and flaky latency assertions
get deleted. That is right, and it leaves three questions it does not answer.

**1. What does the handler actually DO per request?** A wall-clock number is noise on
shared hardware; a ROUND-TRIP COUNT is exact, reproducible and is what the wall clock is
made of. Three DB statements and two Redis ops is a 500ms budget with three orders of
magnitude of headroom. A tenant lookup added "just to log the org" is a fourth statement,
costs a network round trip on every live call, and would sail past an assertion that only
checks `calls == 0`. So this file pins the counts.

**2. What bounds the wait when a dependency stops answering?** Nothing measures its way
out of a hung socket. `apps/api/core/queue.py` already argues this case for Redis and
acts on it (`conn_retries=1, conn_timeout=2` — "ten times the budget spent learning
something the first refused connection already said"), and `core/redis.py` gives the
client `socket_timeout=2`. Postgres had no such bound: a claim against an unresponsive
database waited forever, holding the request, its connection and its worker slot, on the
one service whose whole design premise is that it never stalls.

**3. What does the handler cost the process it SHARES with every other delivery?** The
per-request ledger above is per request; the budget is spent by all of them at once on
one event loop. §1b pins the part of that which is a code property — a warm receiver
opens no new database connections — and leaves the part that is a deployment decision
(how many processes carry 250 concurrent deliveries) to DEPLOYMENT §2a, where an
operator can act on it. D-55 has the measurements behind both.

The rule the first two halves serve: **a failure to do the work must not produce an ack.** An
error tells the vendor nothing useful (it does not retry) but it tells US the truth, and
the 10-minute reconciliation poller — the guarantee of record — recovers the event. An
ack over lost work is unrecoverable by anything except that same poller, and it is
invisible while it happens.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import engine_intake
import pytest
import webhook_routes
from apps.api.core.redis import get_redis
from apps.api.db import session as db_session
from apps.api.db.session import get_engine, untenanted_session
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import AsyncAdaptedQueuePool, QueuePool

ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}


@pytest.fixture(autouse=True)
def _allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_intake, "BOLNA_SOURCE_IPS", frozenset({ENGINE_EGRESS_IP}))


def _client(peer_ip: str = EDGE_PROXY_IP, *, tolerate_crash: bool = False) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(
            app=voice_app, client=(peer_ip, 44444), raise_app_exceptions=not tolerate_crash
        ),
        base_url="http://runtime",
    )


def _event() -> tuple[str, str, dict[str, Any]]:
    token = uuid.uuid4().hex[:12]
    return f"exec_{token}", f"completed-{token}", {}


def _body(execution_id: str, status: str) -> dict[str, Any]:
    return {"execution_id": execution_id, "status": status}


# --- instruments -------------------------------------------------------------


class _Trips:
    """Everything the handler sends over a socket, counted."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.redis_ops: list[str] = []
        self.enqueues: list[str] = []


@pytest.fixture
def trips(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Trips]:
    """Counts DB statements, Redis commands and ARQ enqueues for the code under test.

    The DB side listens on the ENGINE, not on a wrapper, so it counts what psycopg
    actually executes — including anything a future dependency slips in that no test
    would think to stub.
    """
    counted = _Trips()
    engine = get_engine().sync_engine

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        counted.statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _on_execute)

    real_redis = get_redis()
    real_enqueue = webhook_routes.enqueue

    class _CountingRedis:
        async def get(self, key: str) -> Any:
            counted.redis_ops.append("get")
            return await real_redis.get(key)

        async def set(self, key: str, value: str, **kwargs: Any) -> Any:
            counted.redis_ops.append("set")
            return await real_redis.set(key, value, **kwargs)

        async def delete(self, *keys: str) -> Any:
            counted.redis_ops.append("delete")
            return await real_redis.delete(*keys)

    async def _spy_enqueue(job: str, *args: Any, **kwargs: Any) -> str | None:
        counted.enqueues.append(job)
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "get_redis", lambda: _CountingRedis())
    monkeypatch.setattr(webhook_routes, "enqueue", _spy_enqueue)
    try:
        yield counted
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


# --- 1. what the handler costs, exactly --------------------------------------


async def test_the_accepted_path_spends_three_db_round_trips_and_two_redis_ops(
    trips: _Trips,
) -> None:
    """The ledger of a live call's webhook, and the assertion that fails the moment
    somebody adds to it.

    Three statements, each of which hard rule 3 names:
      1. the inbox claim — the durable dedupe, without which an at-most-once event can
         be processed twice and `usage_events` (append-only, hard rule 4) double-charges;
      2. the forensic `webhook_deliveries` row — "no DB writes beyond the minimal event
         row" (SEC-COMP §4 wants the trail);
      3. marking the claim enqueued, so a crash between claim and queue is visible as
         `processing` rather than as a silent duplicate.

    Two Redis ops: the fast-path read on the way in, the fast-path write past the commit.

    What this catches that `calls == 0` does not: a SELECT to resolve the tenant, a
    settings row read, an agent lookup "just for the log line", a second session opened
    because the first was already closed. Every one of them is a network round trip on a
    live call, and none of them creates a `calls` row.
    """
    execution_id, status, _ = _event()

    async with _client() as http:
        response = await http.post(HOOK, json=_body(execution_id, status), headers=HEADERS)

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    assert len(trips.statements) == 3, "the ack path grew a database round trip:\n" + "\n".join(
        f"  {i + 1}. {s[:160]}" for i, s in enumerate(trips.statements)
    )
    kinds = [s.split(" ", 1)[0].upper() for s in trips.statements]
    assert kinds == ["INSERT", "INSERT", "UPDATE"], kinds
    assert trips.redis_ops == ["get", "set"], trips.redis_ops
    assert trips.enqueues == [webhook_routes.INGEST_JOB]

    # And the receiver never enters a tenant's RLS context, because it never resolves a
    # tenant at all (hard rule 3's "no DB writes beyond the minimal event row" has a
    # reads half that is just as load-bearing: a tenant lookup is a round trip AND a
    # coupling to the tenancy module).
    joined = " ".join(trips.statements).lower()
    assert "set_config" not in joined, "the receiver must not set a tenant GUC"
    assert "select" not in joined, "the receiver must not read anything on the ack path"
    for tenant_table in ("calls", "leads", "agents", "organizations", "engine_agent_routes"):
        assert f" {tenant_table} " not in joined, f"the ack path touched {tenant_table}"


async def test_a_duplicate_costs_one_redis_read_and_nothing_else(trips: _Trips) -> None:
    """The point of the fast path: a replay storm must not reach Postgres.

    Bolna does not retry, so real duplicates arrive from replays and from poller
    rediscoveries later in time — i.e. after the first delivery's transaction has long
    committed, which is exactly the population this key absorbs.
    """
    execution_id, status, _ = _event()
    body = _body(execution_id, status)

    async with _client() as http:
        await http.post(HOOK, json=body, headers=HEADERS)
        trips.statements.clear()
        trips.redis_ops.clear()
        trips.enqueues.clear()
        duplicate = await http.post(HOOK, json=body, headers=HEADERS)

    assert duplicate.json()["status"] == "duplicate"
    assert trips.statements == [], "a duplicate must not touch Postgres at all"
    assert trips.redis_ops == ["get"], trips.redis_ops
    assert trips.enqueues == []
    assert "X-Ack-Ms" in duplicate.headers, "the flood path is measured too, or it is not measured"


async def test_a_refused_caller_costs_nothing_at_all(trips: _Trips) -> None:
    """A scanner hammering the URL from off the allowlist must be answerable from the
    socket and the headers alone. If a rejection cost a database round trip, the
    unauthenticated endpoint would be a free amplification vector into our connection
    pool — and the pool is shared with the path that carries live calls.
    """
    execution_id, status, _ = _event()

    async with _client(ATTACKER_IP) as http:
        refused = await http.post(HOOK, json=_body(execution_id, status))

    assert refused.status_code == 401
    assert trips.statements == []
    assert trips.redis_ops == []
    assert trips.enqueues == []
    assert "X-Ack-Ms" in refused.headers, "a rejection is a response; time it like one"


async def test_an_unkeyable_payload_costs_nothing_but_is_still_timed(trips: _Trips) -> None:
    """An event with no usable execution id is acked and dropped (D-31, poller is truth).
    It must not reach the claim, and — since a stream of them is one of the shapes a
    flood takes — it must still be measured."""
    async with _client() as http:
        ignored = await http.post(HOOK, json={"status": "completed"}, headers=HEADERS)

    assert ignored.json()["status"] == "ignored"
    assert trips.statements == []
    assert trips.redis_ops == []
    assert "X-Ack-Ms" in ignored.headers


# --- 1b. what the handler must NOT pay for, at width -------------------------
#
# `tests/webhook_storm_test.py` measured the ack under concurrency and found a convoy:
# server-measured `X-Ack-Ms` p50 110ms at 1 in flight, 669ms at 96, 1389ms at 384, flat
# distribution. The diagnosis (D-55) is that the receiver is CPU-bound on ONE event loop
# at ~250 acks/s per process, so `latency ≈ in-flight / 250` — Little's Law, not a lock
# and not pool exhaustion. Most of that is a sizing rule (DEPLOYMENT §2a), and a sizing
# rule cannot be asserted here.
#
# ONE PIECE OF IT WAS A DEFECT, AND IT IS THE PIECE THESE TESTS PIN. The pool ran on
# SQLAlchemy's defaults (`pool_size=5, max_overflow=10`), and overflow connections are
# SINGLE USE — the pool closes them on return. Measured at 100 concurrent deliveries
# against a real uvicorn: **186 fresh Postgres backends for 1448 requests, 34 new
# connections per second**, each costing ~6ms of this process's CPU to re-authenticate
# (scram-sha-256 = PBKDF2). ~20% of the one core the process has, spent on nothing.
#
# WHY THESE ASSERTIONS AND NOT A MILLISECOND BOUND. A wall-clock assertion under
# concurrency measures the CI runner; `voice_runtime_security_test.py` and the storm file
# both refuse to write one, and they are right. A COUNT OF CONNECTIONS OPENED is exact on
# any machine at any speed, it is the mechanism the latency was made of, and it goes red
# the moment somebody restores an overflow or swaps the engine construction.


async def test_a_warm_receiver_opens_no_new_database_connections_under_load() -> None:
    """The ack path must never pay connection setup. Not "rarely" — never, once warm.

    A fresh backend costs a TCP connect, a SCRAM handshake (PBKDF2 at both ends) and the
    driver's startup exchange: ~6ms of CPU on the single event loop that also has to ack
    every other webhook in flight. On an at-most-once endpoint that CPU is latency, and
    latency is lost calls.

    THE POOL IS DELIBERATELY TINY HERE, built through the real `get_engine`. The property
    only exists at widths that EXCEED the pool, and reaching past a 16-connection pool
    would need a storm of a couple of hundred deliveries — minutes of CI for a fact a
    two-connection pool demonstrates in a second. The pool size is the variable; the
    engine construction under test is the shipped one, which is the half that matters.

    With `max_overflow=0` a caller past the ceiling waits on the pool's `asyncio.Queue`
    — it yields the loop and reuses a connection a moment later — instead of opening one
    it will immediately throw away. "Waited" and "churned" look identical in a latency
    graph and are opposite in cost, which is exactly why this is asserted as a count.
    """
    opened: list[int] = []

    def _on_connect(_dbapi: Any, _record: Any) -> None:
        opened.append(1)

    async with _engine_with_pool_size(2) as engine:
        event.listen(engine.sync_engine, "connect", _on_connect)
        try:
            # Warm: fill the pool to its ceiling, so what follows measures steady state
            # rather than the first requests of a cold process.
            await _concurrent_deliveries(6)
            opened.clear()
            await _concurrent_deliveries(12)
        finally:
            event.remove(engine.sync_engine, "connect", _on_connect)

    assert opened == [], (
        f"a warm receiver opened {len(opened)} new Postgres connection(s) while serving "
        "12 deliveries through a 2-connection pool — it should have QUEUED on the pool "
        "instead. Each of those costs a SCRAM handshake on the event loop that owes "
        "every other delivery a sub-500ms ack: check max_overflow is still 0 (D-55)"
    )


async def test_the_pool_is_sized_with_no_single_use_overflow_and_a_bounded_wait() -> None:
    """The configuration the test above depends on, asserted directly.

    Without this, the churn test could be satisfied by making the pool enormous, which
    trades one failure (CPU burnt on handshakes) for a worse one (a connection budget
    that overruns Postgres `max_connections` and takes down every deployable at once).
    Three properties, each load-bearing:

    - `max_overflow == 0` — no single-use connections, the finding above;
    - the pool is SIZED from config, so an operator can re-size it per deployable
      (DEPLOYMENT §2a) without deploying the latency-critical service;
    - `pool_timeout` is bounded — SQLAlchemy's default is thirty seconds, which is a
      request the vendor gave up on long ago and only the connection is still waiting
      for — and it sits ABOVE the receiver's durable deadline ON PURPOSE. Whichever
      bound fires first decides the answer, and the deadline has a designed one: 503,
      `webhook_claim_timeout`, roll back, leave the key claimable for the poller. A
      `QueuePool limit reached` escaping first would be the same outage wearing a 500.
    """
    pool = get_engine().sync_engine.pool
    assert isinstance(pool, QueuePool | AsyncAdaptedQueuePool), type(pool)
    assert pool._max_overflow == 0, (
        "overflow connections are single-use: the pool closes them on return, so under "
        "sustained load this is a re-authentication treadmill, not a burst valve "
        "(sqlalchemy/sqlalchemy#11707)"
    )
    assert pool.size() == Settings().db_pool_size, (
        "the pool must take its ceiling from DB_POOL_SIZE — re-sizing per deployable is "
        "an environment change, not a deploy of voice-runtime"
    )
    assert webhook_routes._DURABLE_DEADLINE_S < pool.timeout() <= 10, (
        f"pool_timeout={pool.timeout()}s must be bounded (SQLAlchemy defaults to 30s) and "
        f"must sit above the {webhook_routes._DURABLE_DEADLINE_S}s durable deadline, so the "
        "deadline — which has a designed answer — is what a saturated pool meets first"
    )


async def test_the_connection_is_returned_before_the_last_redis_write() -> None:
    """The pool is held for the CLAIM, not for the handler.

    After the transaction commits the handler still does one Redis round trip
    (`_remember_fast_path`). Holding a Postgres connection across it would extend every
    delivery's occupancy by a whole network round trip for work the database is not part
    of — at 250 acks/s that is pool occupancy bought for nothing, and it is the kind of
    thing that gets added by accident when someone moves a line inside the `async with`.

    Asserted as an ORDER of events, which is exact, rather than as a duration.
    """
    engine = get_engine().sync_engine
    order: list[str] = []

    def _on_checkin(_dbapi: Any, _record: Any) -> None:
        order.append("db_checkin")

    real_remember = webhook_routes._remember_fast_path

    async def _spy_remember(*args: Any, **kwargs: Any) -> None:
        order.append("fastpath_write")
        await real_remember(*args, **kwargs)

    event.listen(engine, "checkin", _on_checkin)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(webhook_routes, "_remember_fast_path", _spy_remember)
            execution_id, status, _ = _event()
            async with _client() as http:
                response = await http.post(HOOK, json=_body(execution_id, status), headers=HEADERS)
    finally:
        event.remove(engine, "checkin", _on_checkin)

    assert response.json()["status"] == "accepted"
    assert order == ["db_checkin", "fastpath_write"], (
        f"the connection must be back in the pool before the post-commit Redis write, saw {order}"
    )


@asynccontextmanager
async def _engine_with_pool_size(size: int) -> AsyncIterator[AsyncEngine]:
    """Rebuild the PROCESS engine through `get_engine` with a different pool ceiling.

    Through `get_engine`, not `create_async_engine`, so what is exercised is the shipped
    construction — a test that built its own engine would keep passing after somebody
    changed the real one, which is the only failure this file is here to catch.

    The engine is a process-wide singleton shared by the whole session, so the previous
    one is disposed on the way in and rebuilt on the way out; nothing else in this suite
    holds a session across a test boundary.
    """
    module_settings = Settings()
    previous = db_session._engine
    if previous is not None:
        await previous.dispose()
    db_session._engine = None
    db_session._sessionmaker = None
    try:
        yield get_engine(Settings(**{**module_settings.model_dump(), "db_pool_size": size}))
    finally:
        rebuilt = db_session._engine
        if rebuilt is not None:
            await rebuilt.dispose()
        db_session._engine = None
        db_session._sessionmaker = None
        get_engine()


async def _concurrent_deliveries(width: int) -> None:
    """`width` distinct deliveries released at one event-loop tick.

    `asyncio.Barrier` rather than plain task creation for the reason
    `tests/webhook_storm_test.py` documents: without it each task reaches its first
    await before the next begins, so nothing ever contends for a connection and the
    thing under test never happens.
    """
    token = uuid.uuid4().hex[:10]
    gate = asyncio.Barrier(width)

    async def _one(index: int) -> None:
        async with _client() as http:
            await gate.wait()
            await http.post(
                HOOK,
                json=_body(f"exec_pool_{token}_{index:03d}", f"completed-pool-{token}"),
                headers=HEADERS,
            )

    async with asyncio.TaskGroup() as group:
        for index in range(width):
            group.create_task(_one(index))


# --- 2. a dependency that stops answering ------------------------------------


async def test_a_stalled_database_is_abandoned_at_the_deadline_not_waited_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE test in this file. It runs against real Postgres — `pg_sleep` inside the
    claim's own transaction — because the property under test is that we can actually
    ABANDON a query in flight, not that an `asyncio.sleep` can be cancelled.

    Without a deadline the handler waits as long as the database takes: psycopg sets no
    statement timeout, SQLAlchemy sets no connect timeout, and `pool_pre_ping` issues a
    `SELECT 1` that hangs on precisely the same socket. One unresponsive database and
    every webhook in flight stops being a 500 and starts being a held connection — the
    failure mode that takes the receiver down instead of degrading it.

    The answer on breach must be an ERROR, never a 202. The vendor will not retry either
    way; the difference is whether WE know. A 503 is honest, alerts, and hands the event
    to the poller. A 202 over a rolled-back transaction is a call that quietly vanishes.
    """
    monkeypatch.setattr(webhook_routes, "_DURABLE_DEADLINE_S", 0.35)
    execution_id, status, _ = _event()

    real_claim = webhook_routes.claim_inbox_event

    async def _slow_claim(session: Any, **kwargs: Any) -> Any:
        await session.execute(text("SELECT pg_sleep(5)"))
        return await real_claim(session, **kwargs)

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _slow_claim)

    started = time.perf_counter()
    async with _client(tolerate_crash=True) as http:
        response = await http.post(HOOK, json=_body(execution_id, status), headers=HEADERS)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"the handler waited {elapsed:.1f}s on a stalled database"
    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["kind"] == "transient"
    assert problem["retryable"] is True
    assert "X-Ack-Ms" in response.headers, "a breach is the response most worth timing"

    # Nothing durable, nothing remembered — so the poller's rediscovery of this
    # execution can still claim the key and run the pipeline.
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM webhook_inbox_events WHERE event_key = :k"),
                {"k": f"{execution_id}:{status}"},
            )
        ).scalar()
    assert rows == 0, "an abandoned claim must roll back"

    keys = [k async for k in get_redis().scan_iter(f"calevate:wh:bolna:{execution_id}:*")]
    assert keys == [], "a fast-path key over work that never landed is a permanently lost event"


async def test_the_deadline_is_generous_enough_not_to_fire_on_a_healthy_claim() -> None:
    """The other half, and the reason the number is not 500ms. A deadline set at the ack
    budget would abandon a database that is merely slow — and every event it abandoned
    would wait for the 10-minute poller, turning a latency blip into a pipeline outage.

    So the two numbers do different jobs: 500ms is the ALERT (something is wrong, look at
    it), the deadline is the ABANDON (nothing is coming, stop holding the request). The
    gap between them is deliberate, and this test is what stops someone from closing it.
    """
    assert webhook_routes._DURABLE_DEADLINE_S >= 4 * (webhook_routes._ACK_BUDGET_MS / 1000)


async def test_a_queue_that_refuses_the_job_produces_an_error_never_an_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Defer all real work to ARQ" has a failure mode, and it is the worst one available
    here: enqueue fails, we ack anyway, the vendor never redelivers, and the call is
    processed by nobody. That is not a slow pipeline — it is a call that never happened,
    with a 202 in the access log saying it did.

    So the enqueue sits INSIDE the claim's transaction. If it throws, the claim rolls
    back with it, the fast-path key is never written (it is written past the commit, on
    purpose), and the key stays available for the poller's rediscovery. This test proves
    all four, and then proves the last one by REPLAYING the same delivery against a
    healthy queue.
    """
    execution_id, status, _ = _event()
    body = _body(execution_id, status)

    real_enqueue = webhook_routes.enqueue

    async def _refuse(*_args: Any, **_kwargs: Any) -> str | None:
        raise ConnectionError("redis is not answering")

    monkeypatch.setattr(webhook_routes, "enqueue", _refuse)
    async with _client(tolerate_crash=True) as http:
        failed = await http.post(HOOK, json=body, headers=HEADERS)

    assert failed.status_code >= 500, (
        f"a lost job must be told to somebody, not acked: {failed.status_code} {failed.text[:200]}"
    )

    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text("SELECT count(*) FROM webhook_inbox_events WHERE event_key = :k"),
                {"k": f"{execution_id}:{status}"},
            )
        ).scalar()
        deliveries = (
            await session.execute(
                text("SELECT count(*) FROM webhook_deliveries WHERE event_type = :e"),
                {"e": status},
            )
        ).scalar()
    assert (inbox, deliveries) == (0, 0), "the claim and the forensic row roll back with the job"

    keys = [k async for k in get_redis().scan_iter(f"calevate:wh:bolna:{execution_id}:*")]
    assert keys == [], (
        "the fast-path key must not outlive a transaction that failed — a key with no job "
        "behind it answers every future copy of this delivery 'duplicate'"
    )

    # The event is not poisoned: the same delivery, once the queue is back, is claimable.
    monkeypatch.setattr(webhook_routes, "enqueue", real_enqueue)
    async with _client() as http:
        recovered = await http.post(HOOK, json=body, headers=HEADERS)
    assert recovered.json()["status"] == "accepted", (
        "a failed enqueue must leave the key claimable for the next delivery or the poller"
    )


async def test_a_redis_outage_degrades_to_postgres_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mirror of the test above, and the reason the two are not symmetrical.

    The fast path is a cache, so losing it must cost a Postgres round trip and nothing
    else — `_fast_path_seen` answers "not seen" and the durable claim, which is the layer
    that actually carries the dedupe guarantee, decides. Losing the QUEUE is different in
    kind: there is no second layer behind it, so that one has to fail loudly.
    """

    class _DeadRedis:
        async def get(self, *_a: Any, **_kw: Any) -> Any:
            raise ConnectionError("redis is not answering")

        async def set(self, *_a: Any, **_kw: Any) -> Any:
            raise ConnectionError("redis is not answering")

    monkeypatch.setattr(webhook_routes, "get_redis", lambda: _DeadRedis())
    execution_id, status, _ = _event()
    body = _body(execution_id, status)

    async with _client() as http:
        first = await http.post(HOOK, json=body, headers=HEADERS)
        second = await http.post(HOOK, json=body, headers=HEADERS)

    assert first.json()["status"] == "accepted", "a dead cache must not fail an ack"
    assert second.json()["status"] == "duplicate", "the durable claim still dedupes without Redis"


async def test_the_deadline_does_not_swallow_a_handled_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deadline wrapped around a block is a trap for exceptions that were doing their
    job. `ProblemError.conflict` from the inbox (`webhook_payload_mismatch`) is raised
    inside the guarded region, and it must still leave as a 409 rather than being
    reshaped into a timeout or a 500."""

    async def _mismatch(*_args: Any, **_kwargs: Any) -> Any:
        raise webhook_routes.ProblemError.conflict("webhook_payload_mismatch", "different content")

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _mismatch)

    execution_id, status, _ = _event()
    async with _client(tolerate_crash=True) as http:
        response = await http.post(HOOK, json=_body(execution_id, status), headers=HEADERS)

    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/webhook_payload_mismatch")

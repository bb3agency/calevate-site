"""D-29's `stress:webhook-storm`: the receiver's guarantees under concurrency.

Every property this endpoint stands on is asserted elsewhere ONE REQUEST AT A TIME —
`voice_runtime_security_test.py` (who may call), `voice_runtime_ack_budget_test.py`
(what one call costs, and what happens when a dependency stalls). A storm is where
those properties actually break, because every one of them is really a statement about
what happens when two deliveries meet: an `ON CONFLICT DO NOTHING` that is right
sequentially can double-claim when two transactions overlap, a pool that is ample for
one request queues for twenty, and an ack that is honest when idle can start lying when
the thing behind it is saturated.

The stakes are D-31's: Bolna delivers AT MOST ONCE and never retries. So the two ways
this endpoint can be wrong are not symmetrical —

- **acking work that did not land** loses a call permanently (until the 10-minute
  reconciliation poller, the guarantee of record, rediscovers it), and it is invisible
  while it happens: a 202 in the access log says the opposite of the truth;
- **double-claiming** runs the post-call pipeline twice, and `usage_events` is
  append-only (hard rule 4), so the second run is a second charge on a client's invoice.

D-40 is why this file distrusts the durable claim in particular: the inbox was keyed on
the wrong unit of work, every check was green, and the pipeline silently never ran from
a webhook at all.

WHAT IS ASSERTED, AND WHY IT IS NOT A LATENCY NUMBER
----------------------------------------------------
This runs in CI on a shared runner, and a flaky stress test is worse than none — the
second time it flaps somebody adds `-k "not storm"` and the guarantee goes with it. So
the assertions here are INVARIANTS, which hold on any machine at any speed:

    exactly one inbox row · exactly one forensic row · exactly one accepted response ·
    exactly one job actually created · zero acks over rolled-back work ·
    zero connections left checked out

plus one machine-independent proxy for latency: the **round-trip count**. Wall clock on
a loaded runner measures the runner; `3 x N` database statements for `N` deliveries is
exact, reproducible, and is what the wall clock is made of. A tenant lookup added "just
to log the org" doubles the endpoint's cost under load and would sail past any
millisecond bound generous enough to be stable.

The one timing-shaped assertion is deliberately not a millisecond bound either: it is
"no delivery was abandoned at `_DURABLE_DEADLINE_S`" (2 seconds). The whole storm's
durable work is ~3 statements plus one Redis round trip per delivery against a local
Postgres — a runner would have to be more than an order of magnitude slower than the
slowest box this repo has run on for ONE delivery to spend two seconds inside the claim.
And the failure it guards is real: if the pool, the unique index or Redis serialised the
storm badly enough to blow that deadline, the endpoint is refusing live calls.

WHAT THE STORM MEASURED (this box, local Postgres + Redis, one event loop — the shape
generalises, the numbers do not; re-measure on the target host before quoting them)

    concurrent in flight     1     16     24     48     96    192    384
    ack p50, distinct     ~110    129    173    228    669    939   1389 ms
    ack p50, one herd        6     90    133    245    433    840   1401 ms

Two things to read off it. **The ack budget is a function of concurrency, not of the
handler**: the per-request cost is pinned at 3 statements + 2 Redis ops and did not move,
so what grows is queueing — one event loop and a 15-connection pool serving everyone.
**And the distribution is FLAT** (p50 ≈ max at every width): that is the signature of a
convoy, where every delivery waits for every other, rather than of a tail. Hard rule 3's
500ms is therefore breached somewhere around **~100 concurrent in-flight deliveries per
process** — which is not a hypothetical width, since D-32 records Bolna at 100 concurrent
on Pilots and 250+ in production, i.e. one campaign's calls hanging up together.

That is a CAPACITY finding, not a defect, and the difference matters: correctness was
re-verified out to 768 concurrent (768 accepted → 768 inbox rows → 768 forensic rows; a
768-copy herd → exactly 1 of each; 0 connections left checked out), and the 500ms alert
firing is the system doing its job. Nothing drops until the 2s deadline, and past it the
answer is a 503 and the poller, never a false ack. The scaling lever if it ever bites is
processes and pool size, which is why this file asserts the round-trip count — the thing
a code change can regress — and not a millisecond.

FOLLOW-UP (D-55): the finding above was diagnosed rather than left standing, and the
guessed lever was half right. The process is CPU-saturated on ONE core at ~250 acks/s,
so `ack ≈ in-flight ÷ 250` — Little's Law, which is precisely why the distribution is
flat. Pool EXHAUSTION was not it (instrumented checkout wait: p50 0.1ms at 192
concurrent; pools of 8, 16 and 32 measured identically). The pool did hold one real
defect: connections above `pool_size` are single-use, so the receiver was opening ~34
fresh Postgres backends per second and paying a SCRAM handshake for each — fixed in
`apps/api/db/session.py` (`max_overflow=0`, +20% throughput). The remainder is a
process-count rule, now written where an operator will find it (DEPLOYMENT §2a), and
its deterministic half is asserted in `tests/voice_runtime_ack_budget_test.py` §1b.
Nothing in this file changed: the numbers above are the pre-D-55 measurements and are
left as recorded.

RESEARCH (checked Aug 2026, because "concurrent test" is easy to write and easy to get
wrong):

- `asyncio.TaskGroup` over `asyncio.gather` for structured concurrency — every task is
  awaited before the block exits, so a task that raises cannot be silently orphaned mid
  storm and leave the assertions reading a half-finished database. `gather` is for
  independent fire-and-forget work; these tasks share one logical job.
  (https://blog.rajpoot.dev/posts/python/asyncio-patterns-taskgroup-anyio-2026/,
  https://tildalice.io/asyncio-gather-as-completed-taskgroup-patterns/)
- **A `TaskGroup` alone does not make a race.** Creating N tasks staggers them by
  however long each takes to reach its first await, which on a fast handler is enough
  for delivery 1 to have committed before delivery 2 starts — the test then passes
  because nothing overlapped. `asyncio.Barrier` releases all N at the same tick, which
  is what turns "N requests" into a thundering herd.
- `httpx.ASGITransport` calls the app directly, so this measures OUR handler rather than
  a socket layer or uvicorn's accept loop (https://www.python-httpx.org/async/). That is
  the right instrument here: the contended resources under test — the connection pool,
  the unique index, the Redis round trip — are all inside the handler.
- Postgres `INSERT ... ON CONFLICT DO NOTHING` returns nothing on conflict, so the claim
  falls through to a SELECT; the well-known hazard of that pattern is that a plain
  SELECT takes no lock, so a check-then-insert built on it double-claims under
  concurrency (https://devandchill.com/posts/2020/02/postgres-building-concurrently-safe-upsert-queries/,
  https://www.cybertec-postgresql.com/en/insert-on-conflict-do-select-a-new-feature-in-postgresql-v19/).
  `claim_inbox_event` is NOT that pattern — the INSERT is the claim and the unique index
  is the arbiter — and `test_the_harness_catches_a_claim_that_is_only_right_sequentially`
  below installs the wrong version to prove this file would notice if it became one.

Hard rule 6: the only per-call values here are synthetic execution ids and status
strings. No phone number, no transcript text, in a payload or in an assertion message.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import webhook_routes
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import get_engine, untenanted_session
from apps.api.reliability.service import InboxClaim
from httpx import ASGITransport, AsyncClient, Response
from main import app as voice_app
from sqlalchemy import event, text

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

# Storm widths. Chosen against the pool, not against a wish for a big number: the async
# engine's default pool is 5 + 10 overflow = 15 connections, so 24 concurrent deliveries
# guarantees that some of them WAIT for a connection — the queueing behaviour is the
# point, and a width below 15 would never exercise it. 16 for the same-key herd is
# likewise past the pool, so the herd contends for connections AND for one index tuple.
STORM_WIDTH = 24
HERD_WIDTH = 16

# Statements one delivery may issue. Both branches cost three, which is why the totals
# below are exact rather than ranged:
#   accepted  — INSERT claim, INSERT forensic row, UPDATE claim to 'enqueued'
#   duplicate — INSERT claim (0 rows), SELECT existing, UPDATE duplicate_count
# (a duplicate that arrives after the first has COMMITTED is absorbed by the Redis fast
# path and costs zero; that is a different test, in the ack-budget file.)
STATEMENTS_PER_DELIVERY = 3

# The infra tables the receiver is allowed to touch (hard rule 3: "no DB writes beyond
# the minimal event row"). Anything else appearing under load is the regression this
# file exists to catch.
ALLOWED_TABLES = ("webhook_inbox_events", "webhook_deliveries")


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client() -> AsyncClient:
    """One client per storm task, tolerating app exceptions so a 5xx is a RESPONSE.

    A storm that raises out of the transport tells us nothing about the other 23
    deliveries; a storm that returns 24 status codes tells us exactly which of them the
    receiver refused, which is the distinction the whole file turns on.
    """
    return AsyncClient(
        transport=ASGITransport(
            app=voice_app, client=(EDGE_PROXY_IP, 44444), raise_app_exceptions=False
        ),
        base_url="http://runtime",
    )


# --- instruments -------------------------------------------------------------


@dataclass
class _Trips:
    """Every statement the storm sent, and every enqueue that actually created a job."""

    statements: list[str] = field(default_factory=list)
    created_job_ids: list[str] = field(default_factory=list)
    enqueue_calls: int = 0
    _frozen: list[str] | None = None

    def freeze(self) -> None:
        """Stop counting: the storm is over and everything after this is the TEST's own
        queries.

        Learned the hard way — the first version of this file asserted the round-trip
        budget after reading the inbox back, so the verification `SELECT`s landed in the
        ledger and the total was 3N or 3N+2 depending on assertion order. A count that
        depends on what the test does afterwards is not a measurement of the handler.
        """
        self._frozen = self.counted

    @property
    def counted(self) -> list[str]:
        """Statements the receiver issued, minus the pool's own liveness pings.

        `pool_pre_ping` emits `SELECT 1` on checkout, and a storm wide enough to grow
        the pool is exactly when those appear — counting them would make the totals a
        function of how warm the pool happened to be.
        """
        if self._frozen is not None:
            return self._frozen
        return [s for s in self.statements if s.strip().upper() != "SELECT 1"]


@pytest.fixture
def trips(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Trips]:
    counted = _Trips()
    sync_engine = get_engine().sync_engine

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        counted.statements.append(" ".join(statement.split()))

    event.listen(sync_engine, "before_cursor_execute", _on_execute)

    real_enqueue = webhook_routes.enqueue

    async def _spy_enqueue(job: str, *args: Any, **kwargs: Any) -> str | None:
        counted.enqueue_calls += 1
        job_id = await real_enqueue(job, *args, **kwargs)
        # None means ARQ refused it against an already-queued id. Only a non-None return
        # is a job that now exists — the number that has to be 1.
        if job_id is not None:
            counted.created_job_ids.append(job_id)
        return job_id

    monkeypatch.setattr(webhook_routes, "enqueue", _spy_enqueue)
    try:
        yield counted
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)


@dataclass(frozen=True)
class Delivery:
    execution_id: str
    raw_status: str

    @property
    def event_key(self) -> str:
        return f"{self.execution_id}:{self.raw_status}"

    @property
    def body(self) -> dict[str, str]:
        return {"execution_id": self.execution_id, "status": self.raw_status}


def _deliveries(count: int, *, same_transition: bool) -> list[Delivery]:
    """`count` deliveries, either all of ONE transition (the herd) or all distinct.

    Tokens are per-call random so a storm never collides with another suite's rows on
    this shared database, and so every count below can be scoped to this test alone.
    """
    token = uuid.uuid4().hex[:12]
    if same_transition:
        one = Delivery(f"exec_storm_{token}", f"completed-storm-{token}")
        return [one] * count
    return [
        Delivery(f"exec_storm_{token}_{i:03d}", f"completed-storm-{token}") for i in range(count)
    ]


async def _storm(deliveries: list[Delivery], trips: _Trips | None = None) -> list[Response]:
    """Fire every delivery at the same event-loop tick and return all responses.

    `asyncio.Barrier` is the load-bearing line, not `TaskGroup`: without it the tasks
    start in creation order and each one gets as far as its first await before the next
    begins, which on this handler is far enough for delivery 1 to have committed. The
    barrier makes them contend. `TaskGroup` is how we guarantee no task is still running
    when the assertions read the database.
    """
    gate = asyncio.Barrier(len(deliveries))
    responses: list[Response | None] = [None] * len(deliveries)

    async def _one(index: int, delivery: Delivery) -> None:
        async with _client() as http:
            await gate.wait()
            responses[index] = await http.post(HOOK, json=delivery.body, headers=HEADERS)

    async with asyncio.TaskGroup() as group:
        for index, delivery in enumerate(deliveries):
            group.create_task(_one(index, delivery))

    if trips is not None:
        trips.freeze()
    assert all(r is not None for r in responses)
    return [r for r in responses if r is not None]


def _outcomes(responses: list[Response]) -> dict[str, int]:
    """Response bodies bucketed by what the receiver said it did."""
    tally: dict[str, int] = {}
    for response in responses:
        if response.status_code == 202:
            key = str(response.json().get("status", "?"))
        else:
            key = f"http_{response.status_code}"
        tally[key] = tally.get(key, 0) + 1
    return tally


async def _durable_counts(delivery: Delivery) -> tuple[int, int, int]:
    """(inbox rows, duplicate_count on them, forensic rows) for one transition."""
    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text(
                    "SELECT count(*), COALESCE(sum(duplicate_count), 0) "
                    "FROM webhook_inbox_events WHERE provider = 'bolna' AND event_key = :k"
                ),
                {"k": delivery.event_key},
            )
        ).one()
        forensic = (
            await session.execute(
                text("SELECT count(*) FROM webhook_deliveries WHERE event_type = :e"),
                {"e": delivery.raw_status},
            )
        ).scalar_one()
    return int(inbox[0]), int(inbox[1]), int(forensic)


async def _queued_jobs(delivery: Delivery) -> list[str]:
    """ARQ job keys that exist for this transition, read from the real queue."""
    pattern = f"arq:job:{webhook_routes.INGEST_JOB}:bolna:{delivery.execution_id}:*"
    return [key async for key in get_redis().scan_iter(pattern)]


async def _fast_path_keys(delivery: Delivery) -> list[str]:
    return [
        key async for key in get_redis().scan_iter(f"calevate:wh:bolna:{delivery.execution_id}:*")
    ]


def _assert_no_abandonment(responses: list[Response], *, width: int) -> None:
    """Nobody was abandoned at the durable deadline, and everybody was timed.

    Not a millisecond bound — see the module docstring. `_DURABLE_DEADLINE_S` is two
    seconds against roughly three local statements of work per delivery; a runner slow
    enough to breach that on this width is a runner on which the receiver is dropping
    live calls, which is a result worth failing for rather than a flake.
    """
    acks = [r.headers.get("X-Ack-Ms") for r in responses]
    assert all(a is not None for a in acks), "a storm response left without being measured"
    abandoned = [r for r in responses if r.status_code == 503]
    assert not abandoned, (
        f"{len(abandoned)}/{width} deliveries hit the {webhook_routes._DURABLE_DEADLINE_S}s "
        f"durable deadline — the storm serialised somewhere. Acks (ms): "
        f"{sorted(float(a) for a in acks if a)[-5:]}"
    )


def _assert_round_trip_budget(trips: _Trips, *, deliveries: int) -> None:
    """Concurrency must not buy the handler extra round trips.

    Exact, not ranged: both the accepted and the duplicate branch cost three statements,
    so a storm of N deliveries costs 3N or the handler grew something — a retry loop, a
    pre-ping counted as work, a tenant lookup. Each of those is a network round trip on
    every live call and none of them shows up in a wall-clock assertion loose enough to
    be stable on a shared runner.
    """
    counted = trips.counted
    assert len(counted) == STATEMENTS_PER_DELIVERY * deliveries, (
        f"expected {STATEMENTS_PER_DELIVERY * deliveries} statements for {deliveries} "
        f"deliveries, saw {len(counted)}:\n"
        + "\n".join(f"  {s[:120]}" for s in counted[: 3 * deliveries + 6])
    )
    for statement in counted:
        assert any(table in statement for table in ALLOWED_TABLES), (
            f"the ack path touched something outside the minimal event row: {statement[:160]}"
        )


async def assert_exactly_once(
    responses: list[Response], delivery: Delivery, trips: _Trips, *, width: int
) -> None:
    """The herd's whole contract, in one place — so the negative control at the foot of
    this file can run THIS function against a broken receiver and prove it goes red.

    An invariant checker that the failing test re-implements is not a checker, it is two
    opinions; when one drifts the storm silently stops testing what it says it tests.
    """
    assert _outcomes(responses) == {"accepted": 1, "duplicate": width - 1}, (
        f"a herd of one transition was accepted more than once: {_outcomes(responses)}"
    )

    rows, duplicates, forensic = await _durable_counts(delivery)
    assert rows == 1, f"{rows} inbox rows for one transition — the durable dedupe did not hold"
    assert duplicates == width - 1, (
        f"duplicate_count={duplicates}, expected {width - 1} — a delivery went unaccounted for "
        "(this counter is what a client's activity view shows as 'deduplicated')"
    )
    assert forensic == 1, (
        f"{forensic} forensic rows for one transition — a double claim runs the post-call "
        "pipeline twice, and usage_events is append-only (hard rule 4), so the second run "
        "is a second charge"
    )
    assert len(trips.created_job_ids) == 1, (
        f"{len(trips.created_job_ids)} jobs created from one transition"
    )
    assert len(await _queued_jobs(delivery)) == 1


async def _assert_pool_drained() -> None:
    """No connection is still checked out once the storm has been fully awaited.

    A leak here is the failure that does not announce itself: the receiver keeps working
    at the width that leaked and dies at the next one, on the one deployable whose whole
    premise is that it never stalls. Waited on as a CONDITION rather than a sleep — the
    return to the pool happens in a task's teardown, not at a wall-clock offset.
    """
    pool = get_engine().sync_engine.pool
    for _ in range(200):
        if pool.checkedout() == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{pool.checkedout()} connection(s) never returned to the pool")


# --- 1. the thundering herd: one transition, delivered many times at once -----


async def test_a_thundering_herd_of_one_transition_claims_exactly_once(trips: _Trips) -> None:
    """THE test in this file. `HERD_WIDTH` copies of the SAME (execution, status) arriving
    in the same tick must produce one inbox row, one forensic row, one job, one 202.

    This is the shape the Redis fast path cannot help with: nothing has committed yet, so
    every copy's `GET` misses and every copy reaches the durable claim. Whether the answer
    is "one" is decided entirely by `claim_inbox_event`'s `INSERT ... ON CONFLICT DO
    NOTHING` against the `(provider, event_key)` unique index — the losers block on the
    winner's uncommitted index tuple, and only once it commits do they fall through to the
    SELECT that tells them they lost.

    `duplicate_count` is asserted exactly, not merely as "> 0": it is the number a client's
    activity view shows as "deduplicated", and a herd that increments it 14 times for 15
    duplicates means one delivery went somewhere unaccounted for.
    """
    herd = _deliveries(HERD_WIDTH, same_transition=True)
    one = herd[0]

    responses = await _storm(herd, trips)

    await assert_exactly_once(responses, one, trips, width=HERD_WIDTH)
    _assert_no_abandonment(responses, width=HERD_WIDTH)
    # Every copy reached the DURABLE claim: the fast path is a read, and nothing has
    # committed while the herd is in flight, so all `HERD_WIDTH` misses it. That is the
    # point of the herd — 0 statements here would mean Redis absorbed them and the
    # unique index was never tested at all.
    _assert_round_trip_budget(trips, deliveries=HERD_WIDTH)
    assert len(await _fast_path_keys(one)) == 1
    await _assert_pool_drained()


# --- 2. a wide storm of distinct transitions ---------------------------------


async def test_a_storm_of_distinct_transitions_loses_nothing(trips: _Trips) -> None:
    """`STORM_WIDTH` different calls hanging up at once — past the connection pool, so
    some deliveries queue for a connection.

    The invariant is the at-most-once one: **every 202 has durable work behind it.** Not
    "most did", not "eventually" — an acked delivery with no inbox row is a call we told
    the vendor we took and then dropped, and nothing downstream will ever notice, because
    Bolna does not redeliver and the access log says 202.
    """
    storm = _deliveries(STORM_WIDTH, same_transition=False)

    responses = await _storm(storm, trips)

    assert _outcomes(responses) == {"accepted": STORM_WIDTH}, _outcomes(responses)
    _assert_no_abandonment(responses, width=STORM_WIDTH)
    _assert_round_trip_budget(trips, deliveries=STORM_WIDTH)

    async with untenanted_session() as session:
        claimed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events WHERE provider = 'bolna' "
                    "AND event_key = ANY(:keys) AND status = 'enqueued'"
                ),
                {"keys": [d.event_key for d in storm]},
            )
        ).scalar_one()
    assert claimed == STORM_WIDTH, (
        f"{STORM_WIDTH} deliveries were acked but only {claimed} left an enqueued inbox row"
    )
    assert len(trips.created_job_ids) == STORM_WIDTH, (
        f"{len(trips.created_job_ids)} jobs for {STORM_WIDTH} distinct calls — a lost job at an "
        "at-most-once endpoint is a call that never happened"
    )
    await _assert_pool_drained()


# --- 3. the queue as the bottleneck ------------------------------------------


async def test_a_dead_queue_under_load_refuses_every_delivery_rather_than_acking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`voice_runtime_ack_budget_test.py` proves a refused enqueue produces an error and
    not an ack for ONE request. The failure mode worth this file's time is the same thing
    under load, where a handler with any per-request state or any partially-applied
    transaction would start acking some of them.

    So: nothing acked, nothing durable, nothing remembered in Redis — the whole storm
    stays claimable, which is what makes the 10-minute poller (D-31) able to recover it.
    A fast-path key surviving here would be worse than the outage: it answers every
    future copy of that delivery "duplicate" with no job behind it.
    """

    async def _refuse(*_args: Any, **_kwargs: Any) -> str | None:
        raise ConnectionError("redis is not answering")

    monkeypatch.setattr(webhook_routes, "enqueue", _refuse)
    storm = _deliveries(HERD_WIDTH, same_transition=False)

    responses = await _storm(storm)

    assert not [r for r in responses if r.status_code < 500], (
        f"a queue outage produced acks: {_outcomes(responses)}"
    )

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM webhook_inbox_events WHERE event_key = ANY(:keys)"),
                {"keys": [d.event_key for d in storm]},
            )
        ).scalar_one()
    assert rows == 0, f"{rows} claims survived a transaction whose enqueue failed"
    for delivery in storm:
        assert await _fast_path_keys(delivery) == [], (
            "a fast-path key over work that never landed permanently loses this delivery"
        )
    await _assert_pool_drained()


async def test_a_slow_queue_under_a_herd_still_yields_exactly_one_job(
    monkeypatch: pytest.MonkeyPatch, trips: _Trips
) -> None:
    """The queue is not down, it is SLOW — the case that widens the race rather than
    closing it. The enqueue sits inside the claim's transaction, so a slow queue holds
    the winner's index tuple, its connection and the whole herd behind it for that much
    longer. If anything in the claim were racy, this is the timing that exposes it; and
    if the wait were unbounded, the deadline is what stops it holding the request.

    100ms is two orders of magnitude above a local enqueue and comfortably inside the 2s
    deadline, so the delay changes the interleaving without changing the expected answer.
    """
    real_enqueue = webhook_routes.enqueue

    async def _slow(job: str, *args: Any, **kwargs: Any) -> str | None:
        await asyncio.sleep(0.1)
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _slow)
    herd = _deliveries(HERD_WIDTH, same_transition=True)

    responses = await _storm(herd, trips)

    await assert_exactly_once(responses, herd[0], trips, width=HERD_WIDTH)
    _assert_no_abandonment(responses, width=HERD_WIDTH)
    await _assert_pool_drained()


# --- 4. degradation, and whether it is safe ----------------------------------


async def test_a_storm_that_all_times_out_leaks_no_connection_and_loses_no_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every delivery in the storm stalls in the database and is abandoned at the
    deadline, simultaneously. The question is not whether it gets slower — it is whether
    it degrades SAFELY.

    Two ways it could not. **A leaked connection**: `asyncio.timeout` cancels the task
    mid-query, and a cancellation that lands between "the pool handed out a connection"
    and "the session context manager took ownership of it" would retire a connection per
    stalled webhook — a receiver that survives one incident and dies in the next, with a
    pool of 15 to spend. **A silent loss**: an abandoned claim that left a fast-path key
    or a half-committed row behind would answer the poller's rediscovery "duplicate", and
    the call would be gone for good.

    `pg_sleep` inside the claim's own transaction, because the property is that a query
    IN FLIGHT can be abandoned — not that an `asyncio.sleep` can be cancelled.
    """
    monkeypatch.setattr(webhook_routes, "_DURABLE_DEADLINE_S", 0.35)
    real_claim = webhook_routes.claim_inbox_event

    async def _stalled(session: Any, **kwargs: Any) -> Any:
        await session.execute(text("SELECT pg_sleep(5)"))
        return await real_claim(session, **kwargs)

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _stalled)
    storm = _deliveries(HERD_WIDTH, same_transition=False)

    responses = await _storm(storm)

    assert {r.status_code for r in responses} == {503}, _outcomes(responses)
    assert all("X-Ack-Ms" in r.headers for r in responses), (
        "the breach is the response most worth timing"
    )

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM webhook_inbox_events WHERE event_key = ANY(:keys)"),
                {"keys": [d.event_key for d in storm]},
            )
        ).scalar_one()
    assert rows == 0, "an abandoned claim must roll back; the poller has to be able to re-claim it"
    for delivery in storm:
        assert await _fast_path_keys(delivery) == []
    await _assert_pool_drained()


async def test_a_storm_the_receiver_refused_costs_the_database_nothing(trips: _Trips) -> None:
    """The flood shape that needs no vendor at all: the URL is public and unsigned, so a
    scanner can send this whenever it likes. Refusals must stay answerable from the socket
    and the headers, at width — otherwise the endpoint is a free amplifier into the
    connection pool that carries live calls.
    """
    storm = _deliveries(STORM_WIDTH, same_transition=False)
    attacker = ASGITransport(
        app=voice_app, client=("203.0.113.9", 44444), raise_app_exceptions=False
    )
    gate = asyncio.Barrier(STORM_WIDTH)

    async def _one(delivery: Delivery) -> Response:
        async with AsyncClient(transport=attacker, base_url="http://runtime") as http:
            await gate.wait()
            return await http.post(HOOK, json=delivery.body)

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(_one(d)) for d in storm]

    assert {t.result().status_code for t in tasks} == {401}
    assert trips.counted == [], "a refusal storm reached Postgres"
    assert trips.enqueue_calls == 0
    assert all("X-Ack-Ms" in t.result().headers for t in tasks)


# --- 5. the negative control: this test has been seen to fail ----------------


async def test_the_harness_catches_a_claim_that_is_only_right_sequentially(
    monkeypatch: pytest.MonkeyPatch, trips: _Trips
) -> None:
    """A stress test that has never gone red proves nothing. This one goes red on demand.

    The break installed here is the specific mistake the module docstring cites as the
    classic hazard of `ON CONFLICT DO NOTHING`: **check, then insert.** It reads the inbox
    for an existing row, and if it finds none it claims. That is correct every time you
    run it by hand and correct in every sequential test in this repo — a plain SELECT
    takes no lock, so under a herd all `HERD_WIDTH` copies read "absent" before any of
    them writes, and all of them claim.

    What that would do in production: `HERD_WIDTH` forensic rows, `HERD_WIDTH` 202s, and
    the post-call pipeline run once per copy — a duplicate charge in `usage_events` per
    duplicate delivery (hard rule 4: no compensating UPDATE, only a compensating entry).

    NOTE WHICH ASSERTION SAVES US, because it is not the obvious one. The JOB count stays
    1: every copy enqueues the same `job_id_for(...)` natural key and ARQ refuses the
    duplicates. That is a real defence, but it is the LAST one and its dedupe window is
    finite — a redelivery after the window closes gets a second job. So a file that
    checked only "one job" would be green on a receiver whose durable dedupe had rotted.
    The invariants that actually catch it are the ones on OUR rows: one accepted response,
    one inbox row, one forensic row.

    The check run here is `assert_exactly_once` ITSELF, not a restatement of it, so this
    control cannot drift away from the thing it certifies.
    """
    real_claim = webhook_routes.claim_inbox_event

    async def _check_then_insert(session: Any, **kwargs: Any) -> Any:
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM webhook_inbox_events WHERE provider = :provider "
                    "AND event_key = :key"
                ),
                {"provider": kwargs["provider"], "key": kwargs["event_key"]},
            )
        ).first()
        if existing is not None:
            return await real_claim(session, **kwargs)
        # The bug: "my SELECT saw nothing" treated as "I hold the claim".
        return InboxClaim(state="claimed", row_id=uuid7())

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _check_then_insert)
    # The real claim is what writes the inbox row, so with it bypassed `mark_inbox_enqueued`
    # has nothing to update — the broken receiver still answers, which is precisely how
    # this class of bug survives review.
    herd = _deliveries(HERD_WIDTH, same_transition=True)

    responses = await _storm(herd, trips)

    with pytest.raises(AssertionError, match="accepted more than once"):
        await assert_exactly_once(responses, herd[0], trips, width=HERD_WIDTH)

    # And now the shape of the damage, so a future edit that makes the break stop
    # breaking anything fails here rather than quietly leaving a control that certifies
    # nothing.
    assert _outcomes(responses) == {"accepted": HERD_WIDTH}, _outcomes(responses)
    _, _, forensic = await _durable_counts(herd[0])
    assert forensic == HERD_WIDTH, f"one forensic row per copy expected, saw {forensic}"
    # The finding that makes the invariant choice above non-obvious: ARQ still collapsed
    # the jobs, so the QUEUE looks perfectly healthy while the durable dedupe is gone.
    assert len(trips.created_job_ids) == 1, (
        "ARQ's job-id dedupe is the last line of defence, not the first — its window is "
        "finite, so 'one job' cannot be the only assertion in this file"
    )
    await _assert_pool_drained()

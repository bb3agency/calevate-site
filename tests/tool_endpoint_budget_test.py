"""The in-call tool endpoint against the 100ms budget CLAUDE.md names and nobody measured.

    "Do NOT call model providers directly from request handlers (workers or engine
     only), except the in-call RAG tool endpoint which has a 100ms budget — measure it."

════ WHAT WAS LOOKED FOR FIRST, AND WHY NONE OF IT IS THIS MEASUREMENT ════════════════

Three things in this repo are near enough to be mistaken for it. None of them measures
our server time against 100ms, and saying so is the first job of this file:

* `scripts/pilot/knowledge.py::probe_tool_call_budget` scores `tool_call_latencies_ms`
  against exactly this 100ms number — but those samples are the ENGINE→endpoint→ENGINE
  round trip, typed into `docs/evidence/gate8-inputs.json` by an operator watching a live
  call (`OPERATOR_SOURCED_FINDING`). There is no such file, so the row is NOT RUN and has
  always been. It is also a different quantity: it contains a WAN hop we do not own.
* `tests/voice_runtime_ack_budget_test.py` pins what a request costs — but the WEBHOOK
  receiver's, against hard rule 3's 500ms, and the tool endpoint is not in it.
* `tests/call_optout_test.py` asserts `X-Ack-Ms < 500.0` on one accepted tool call. One
  sample is not a distribution, and 500 is not 100.

**AND THE ENDPOINT THE BUDGET NAMES DOES NOT EXIST.** There is no in-call RAG tool
endpoint: D-33/TRD §6.2 keep T3 cold lookup inside the engine's own knowledge base, and
`tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side` fails
the day one appears in `apps/voice-runtime`. So the budget is a rule about an endpoint
that is deliberately unbuilt, and measuring "it" literally is impossible.

What IS on the caller's audio path today is `POST /tools/v1/{engine}/opt-out` — an engine
custom function invoked mid-call, the same class of request, sharing every layer a RAG
endpoint would need before it retrieved anything: source verification, the bounded read,
the JSON parse, the ack accounting, the ARQ hand-off. Measuring it answers the question
that actually decides TRD §6.2's fallback: **is the server half of a 100ms budget even
affordable, before a single millisecond of network?** That is what is measured below.

════ THE MEASUREMENT (this box, 2026-08-15; re-run with `-s` to reproduce) ═════════════

Real handler, real `main.app`, real `verify_source`, real `_read_bounded`, real ARQ
enqueue against real Redis. Nothing on the path is stubbed or faked. `X-Ack-Ms` is the
handler's own clock (`time.perf_counter()` at entry → `_ack`); the client column is the
same request measured from outside through `httpx.ASGITransport`.

    ONE CALL IN FLIGHT — the single-call case, n=500 warm samples

        server X-Ack-Ms     min 0.8   p50 1.0   p95 1.4   p99 1.6   max 3.8  ms
        client via ASGI     min 1.4   p50 1.6   p95 2.0   p99 2.2   max 4.4  ms
        cold first request  server 3.0 ms · client 8.7 ms
        per request         0 database statements · 1 enqueue · 3 Redis round trips

    CONCURRENT, server-measured ack, released at one event-loop tick

        in flight        1      8     24     96    250
        p50 ms         0.9    6.3   15.1   48.5  143.0
        p95 ms         0.9    6.8   17.1   51.1  187.7
        max ms         0.9    6.8   17.3   52.3  189.1

**THE VERDICT, in the two halves it has.** At one call in flight the budget is not
blown and is not close: p95 1.4ms is 1.4% of 100ms, and the endpoint reaches Postgres
zero times. At production concurrency it IS blown, by our own server time alone: the
distribution is FLAT at every width (p50 ≈ max), which is D-55's convoy signature — one
event loop, `latency ≈ in-flight ÷ throughput`, here ≈ 1,750 acks/s. Solving for 100ms
gives **~175 concurrent in-flight tool calls per process**, and D-32 records Bolna at 100
concurrent on Pilots and 250+ in production. At 250 the server-measured p50 is 143ms
before the network is considered at all.

**WHAT IS EXCLUDED, stated plainly — a measurement that quietly drops the slow part is
worse than none:**

1. **The network is not in these numbers and cannot be.** Engine→us→engine is the
   dominant term and TRD §6.2 already estimates it at +150-400ms for the two-hop external
   route — which is precisely why D-33 keeps retrieval in the engine. Every vendor host is
   egress-blocked from this environment; that half is pilot gate 8 and belongs to an
   operator on a live call, not to this file.
2. **The edge is not in them either.** DEPLOYMENT §1 puts Cloudflare and nginx in front
   of this container. Neither is exercised here.
3. **uvicorn's socket and HTTP layer is not in them.** `ASGITransport` calls the app
   directly, which is deliberate and is this repo's chosen instrument for this question
   (`tests/webhook_storm_test.py`: "this measures OUR handler rather than a socket layer
   or uvicorn's accept loop").
4. **Nothing is stubbed to make the number look good.** Redis is real, local, and takes
   three round trips per enqueue (arq's `enqueue_job` with `_job_id` does WATCH, EXISTS,
   then MULTI/PSETEX/ZADD/EXEC). Postgres is untouched because the handler never reaches
   it — that is a property of the code, asserted below, not an omission from the harness.
   `Settings()` is constructed before the cold sample by the `source_ip_allowlist`
   fixture, so the cold number is a cold ARQ POOL, not a cold process.
5. **One box, one process, one event loop.** The numbers do not generalise to the target
   host. The SHAPE does: a flat distribution stays flat wherever the loop is.

════ WHY THE NUMBERS ARE NOT ASSERTED, AND WHAT IS ═══════════════════════════════════

No test here fails on a millisecond. `tests/voice_runtime_security_test.py` declines a
millisecond bound and `tests/webhook_storm_test.py` argues the case at length — a latency
assertion on a shared CI runner measures the runner, flaps, and gets deleted along with
the guarantee it was carrying. That reasoning applies here with more force, not less: the
margin at width 1 is a factor of seventy, so a bound loose enough to be stable would pass
against a handler an order of magnitude slower than this one.

What IS asserted is the MECHANISM the wall clock is made of, which is exact on any
machine at any speed: **zero database round trips, exactly one enqueue, and no read of
anything.** Three DB statements would not fail a 100ms bound on this box and would be
~40% of the budget on a host with a 10ms database. The count catches that; the clock
does not.

The distribution's home is this docstring plus `docs/TRD.md` §6.2, where the 100ms
number is stated and where the architecture decision it feeds gets made. It is not in
`scripts/pilot/knowledge.py`: gate 8's `custom_function_tool_call_budget` is the
END-TO-END quantity, and folding a server-side number into that row would be exactly the
mistake `scripts/pilot/latency.py` refuses when it keeps vendor-reported components apart
from stopwatch samples — "a different quantity wearing the same name".

Hard rule 6: the only per-request values here are synthetic execution ids and a fixed
reason string. No phone number, no transcript, in a payload or an assertion message.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import tool_routes
from apps.api.db.session import get_engine
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from sqlalchemy import event

ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"
TOOL = "/tools/v1/bolna/opt-out"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

#: TRD §6.2's in-call retrieval budget, restated rather than imported. There is nothing to
#: import — the budget lives in prose in CLAUDE.md and TRD §6.2, which is half of why it
#: was never measured. Stated here so the docstring's arithmetic has a named constant
#: behind it.
IN_CALL_BUDGET_MS = 100.0


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def _body() -> dict[str, str]:
    """A plausible tool call: an execution id, a reason, a language tag."""
    return {
        "execution_id": f"exec_{uuid.uuid4().hex[:16]}",
        "reason": "caller asked to be removed from the list",
        "language": "te",
    }


# --- the ledger instrument ----------------------------------------------------


class _Trips:
    """Everything the handler sends over a socket, counted."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.enqueues: list[str] = []


@pytest.fixture
def trips(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Trips]:
    """Counts DB statements and ARQ enqueues for the code under test.

    The DB side listens on the ENGINE rather than on a wrapper, so it counts what psycopg
    actually executes — including a statement some future dependency slips onto the path
    that no test would think to stub. Same instrument, same reason, as
    `voice_runtime_ack_budget_test.trips`; the Redis half is absent here because this
    endpoint has no fast-path cache to count, and the enqueue's own round trips are arq's
    business rather than a property of our handler.
    """
    counted = _Trips()
    engine = get_engine().sync_engine

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        counted.statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _on_execute)

    real_enqueue = tool_routes.enqueue

    async def _spy_enqueue(job: str, *args: Any, **kwargs: Any) -> str | None:
        counted.enqueues.append(job)
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(tool_routes, "enqueue", _spy_enqueue)
    try:
        yield counted
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


# --- 1. what the handler costs, exactly ---------------------------------------


async def test_the_accepted_tool_call_reaches_postgres_zero_times(trips: _Trips) -> None:
    """The claim `tool_routes`'s docstring makes — "no DB writes at all here" — asserted.

    It was prose. The receiver's equivalent ledger has been pinned since D-55; this
    endpoint had nothing, so a tenant lookup "just to log the org", a settings row read or
    an agent lookup could be added to the one handler on the caller's audio path and every
    test in the repo would stay green.

    ZERO is the right number and it is stronger than the receiver's three. The receiver
    claims an inbox row because an at-most-once delivery must be deduped durably; a tool
    call has no such row to claim — a repeated invocation collapses on the ARQ job id, and
    the worker resolves the tenant, the number and the direction from an authenticated Get
    Execution (D-31). So there is nothing here for a database to do, and a statement
    appearing is not a slower endpoint, it is a design that changed without saying so.
    """
    async with _client() as http:
        response = await http.post(TOOL, json=_body(), headers=HEADERS)

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert trips.statements == [], (
        "the in-call tool endpoint reached Postgres:\n"
        + "\n".join(f"  {i + 1}. {s[:160]}" for i, s in enumerate(trips.statements))
        + "\nEvery statement here is a network round trip inside the caller's audio gap"
    )
    assert trips.enqueues == [tool_routes.OPTOUT_JOB], trips.enqueues
    assert "X-Ack-Ms" in response.headers, "an acked path is a measured path"


async def test_a_refused_tool_call_costs_nothing_at_all(trips: _Trips) -> None:
    """A stranger who found the URL must be answerable from the socket and the headers.

    The receiver asserts this for its own path and the reason is identical: an
    unauthenticated endpoint whose REJECTION costs a database round trip is a free
    amplification vector into a pool shared with the path that carries live calls.
    """
    async with _client(ATTACKER_IP) as http:
        refused = await http.post(TOOL, json=_body())

    assert refused.status_code == 401
    assert trips.statements == []
    assert trips.enqueues == []
    assert "X-Ack-Ms" in refused.headers, "a rejection is a response; time it like one"


async def test_an_unkeyable_tool_call_costs_nothing_and_is_still_measured(
    trips: _Trips,
) -> None:
    """The 422 path — a mis-configured custom function is a stream of these, and a stream
    is the shape a flood takes. It must reach neither Postgres nor the queue, and it must
    still be timed: an endpoint instrumented only on its happy path is measured at its
    least stressed.
    """
    async with _client() as http:
        refused = await http.post(TOOL, json={"reason": "remove me"}, headers=HEADERS)

    assert refused.status_code == 422
    assert trips.statements == []
    assert trips.enqueues == []
    assert "X-Ack-Ms" in refused.headers


# --- 2. the measurement -------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank: the reported percentile IS one of the observed samples.

    Imported spelling and rationale from `scripts.pilot.knowledge.percentile` — an
    interpolated percentile invents a value between two measurements, which is the one
    thing a recorded measurement must not do.
    """
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def distribution(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "min": round(min(samples), 2),
        "p50": round(percentile(samples, 0.50), 2),
        "p95": round(percentile(samples, 0.95), 2),
        "p99": round(percentile(samples, 0.99), 2),
        "max": round(max(samples), 2),
    }


async def measure_sequential(n: int) -> tuple[dict[str, float], dict[str, float]]:
    """`n` warm tool calls, one in flight. Returns (server clock, client clock).

    Warm-up requests are discarded rather than folded in: the first call builds the ARQ
    pool, and a cold sample inside a warm distribution moves the max by an amount nobody
    can later separate out — the same reason `scripts/pilot/latency.py` keeps greeting
    delay out of its turn ledger.
    """
    server_ms: list[float] = []
    client_ms: list[float] = []
    async with _client() as http:
        for _ in range(5):
            await http.post(TOOL, json=_body(), headers=HEADERS)
        for _ in range(n):
            started = time.perf_counter()
            response = await http.post(TOOL, json=_body(), headers=HEADERS)
            client_ms.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 202, response.text
            server_ms.append(float(response.headers["X-Ack-Ms"]))
    return distribution(server_ms), distribution(client_ms)


async def measure_concurrent(width: int) -> dict[str, float]:
    """Server-measured ack for `width` tool calls released at ONE event-loop tick.

    `asyncio.Barrier`, for the reason `webhook_storm_test.py` records: creating N tasks
    staggers them by however long each takes to reach its first await, so without the
    barrier nothing ever overlaps and the measurement is N sequential requests wearing a
    concurrency label.
    """
    async with _client() as http:
        for _ in range(5):
            await http.post(TOOL, json=_body(), headers=HEADERS)

    gate = asyncio.Barrier(width)
    server_ms: list[float] = []

    async def _one() -> None:
        async with _client() as http:
            await gate.wait()
            response = await http.post(TOOL, json=_body(), headers=HEADERS)
            assert response.status_code == 202, response.text
            server_ms.append(float(response.headers["X-Ack-Ms"]))

    async with asyncio.TaskGroup() as group:
        for _ in range(width):
            group.create_task(_one())
    return distribution(server_ms)


async def test_the_measurement_runs_and_reports_a_distribution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The harness that produced the docstring's table, exercised in the ordinary suite.

    NO MILLISECOND IS ASSERTED — see the docstring's argument. What is asserted is that
    the instrument still works: that every sample is a real positive measurement, that the
    percentiles are ordered, and that a distribution came back at all. A harness nobody
    runs is a harness that has quietly stopped measuring, and this is the shape of that
    failure the repo has already met (`scripts/pilot/knowledge.py`: "a probe that has
    never run is exactly as unverified as the vendor it is aimed at").

    `n` is small so the suite stays fast; re-run with a larger `n` and `-s` to reproduce
    the recorded table. The widths are omitted here for the same reason — 250 concurrent
    requests is seconds of CI for a number nobody is allowed to assert on.
    """
    server, client = await measure_sequential(40)
    concurrent = await measure_concurrent(8)

    for label, dist in (("server", server), ("client", client), ("concurrent-8", concurrent)):
        assert dist["n"] > 0, label
        assert dist["min"] > 0, f"{label}: a zero sample means the clock was never read"
        assert dist["min"] <= dist["p50"] <= dist["p95"] <= dist["p99"] <= dist["max"], (
            f"{label}: percentiles out of order — the estimator is broken, not the endpoint"
        )
    # The one relationship that is a property rather than a measurement: the request as
    # seen from outside contains the handler's own clock, so it cannot be shorter.
    assert client["p50"] >= server["p50"], (server, client)

    with capsys.disabled():
        print(f"\n  in-call tool endpoint, budget {IN_CALL_BUDGET_MS:.0f}ms (server side only)")
        print(f"  sequential server X-Ack-Ms : {server}")
        print(f"  sequential client via ASGI : {client}")
        print(f"  concurrent width=8, server : {concurrent}")


# --- 3. what this slice could not fix -----------------------------------------

#: Metric names the in-call tool endpoint's ack path records TODAY.
#:
#: This is the defect, not the design. `tool_routes` leaves through `webhook_routes._ack`,
#: which calls `record_webhook_ack_ms(elapsed, provider=engine)` — so an in-call tool call
#: and a post-call webhook delivery land in ONE series, `webhook_ack_ms{provider="bolna"}`,
#: distinguishable by nothing. They are different endpoints with different budgets and
#: wildly different costs (0 database statements against 3), so the pooled p95 is a
#: blend of two populations: a burst of cheap tool calls DILUTES the receiver's p95 and
#: can hide a regression in it, and the tool endpoint's own budget can never be read off
#: the series at all.
#:
#: NOT FIXED HERE, and the reason is ownership rather than difficulty. The fix is a second
#: recorder in `apps/api/core/alerting.py` ("adding a recorder is how a new SLO gets a
#: vocabulary; ad-hoc counters are not accepted") plus a parameter on
#: `webhook_routes._ack` — and `apps/voice-runtime/webhook_routes.py` belongs to another
#: slice this wave. Re-implementing the ack accounting inside `tool_routes` instead is the
#: "two ways of doing one thing" its own module docstring already rejects.
#:
#: An equality assertion, not an exemption: the day the tool endpoint records its own
#: metric this test goes red and the entry must be deleted with the defect.
KNOWN_OPEN_ACK_METRICS: dict[str, str] = {
    "webhook_ack_ms": (
        "the in-call tool endpoint's ack is pooled into the WEBHOOK receiver's series "
        "because it leaves through `webhook_routes._ack`. Closes when the tool path gets "
        "its own recorder in `apps/api/core/alerting.py` and `_ack` is told which to use."
    ),
}


async def test_the_tool_endpoints_ack_lands_in_the_receivers_metric_and_still_should_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The recorded gap, asserted behaviourally rather than by reading the source.

    A text scan of `tool_routes.py` would pass the day somebody moved the call one level
    down; what matters is which SERIES the number actually lands in, so the metric log is
    the instrument. `calevate.metric` is where every `_record` goes.
    """
    with caplog.at_level(logging.INFO, logger="calevate.metric"):
        async with _client() as http:
            response = await http.post(TOOL, json=_body(), headers=HEADERS)
    assert response.status_code == 202

    recorded = {
        str(record.metric)
        for record in caplog.records
        if record.name == "calevate.metric" and hasattr(record, "metric")
    }
    assert recorded == set(KNOWN_OPEN_ACK_METRICS), (
        f"the in-call tool endpoint now records {sorted(recorded)}. If it has its own "
        "series at last, delete the matching KNOWN_OPEN_ACK_METRICS entry — a recorded "
        "defect that outlives the defect is a hole with a comment on it."
    )

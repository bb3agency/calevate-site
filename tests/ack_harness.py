"""THE ack-timing instrument, for both of voice-runtime's latency-critical surfaces.

There are two budgets in this service and they are different numbers over the same
handler shape: hard rule 3's **500ms** for the post-call webhook receiver, and TRD §6.2's
**100ms** for an in-call tool call. D-109 built a measurement harness for the second one
inside `tests/tool_endpoint_budget_test.py` — percentiles, a warm sequential run, a
barrier-released concurrent run — and the FIRST one, the budget CLAUDE.md actually names
as a hard rule, had none: `tests/voice_runtime_ack_budget_test.py` pinned round-trip
COUNTS and deadlines and never produced a distribution at all.

So the instrument moved here rather than being written a second time (D-241): one
percentile estimator, one warm-up discipline, one barrier. Each budget file keeps only
what is genuinely its own — its URL, its body, and the argument about what its number
means. A second copy of `percentile` is how two measurements of the same service stop
being comparable.

**NO TEST HERE ASSERTS A MILLISECOND, AND NEITHER MAY ITS CALLERS.** The argument is
`tool_endpoint_budget_test`'s and `webhook_storm_test`'s and is unchanged: a latency bound
on a shared runner measures the runner, flaps, and is eventually deleted along with the
guarantee it was carrying (D-29's notes). What the callers assert is the MECHANISM the
clock is made of — round trips, enqueues, connections — which is exact at any speed.

Hard rule 6: this module handles response headers and floats. Nothing it touches is a
payload.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable

from httpx import Response

#: One request, already aimed at its endpoint by the caller. Returns the response so the
#: harness can read `X-Ack-Ms` — the handler's OWN clock, started at the route's first
#: line and stopped in `_ack`, which is the only number that excludes the test client.
AckRequest = Callable[[], Awaitable[Response]]


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank: the reported percentile IS one of the observed samples.

    Spelling and rationale from `scripts.pilot.knowledge.percentile` — an interpolated
    percentile invents a value between two measurements, which is the one thing a
    recorded measurement must not do.
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


def assert_well_formed(label: str, dist: dict[str, float]) -> None:
    """The instrument still works — which is the only thing a distribution may assert.

    A harness nobody checks is a harness that has quietly stopped measuring, and the repo
    has met that failure before (`scripts/pilot/knowledge.py`: "a probe that has never run
    is exactly as unverified as the vendor it is aimed at").
    """
    assert dist["n"] > 0, label
    assert dist["min"] > 0, f"{label}: a zero sample means the clock was never read"
    assert dist["min"] <= dist["p50"] <= dist["p95"] <= dist["p99"] <= dist["max"], (
        f"{label}: percentiles out of order — the estimator is broken, not the endpoint"
    )


async def measure_sequential(
    request: AckRequest, n: int, *, warmup: int = 5, expect_status: int = 202
) -> tuple[dict[str, float], dict[str, float]]:
    """`n` warm requests, ONE in flight. Returns (server clock, client clock).

    Warm-up requests are discarded rather than folded in: the first request builds the ARQ
    pool and the connection pool, and a cold sample inside a warm distribution moves the
    max by an amount nobody can later separate out — the same reason
    `scripts/pilot/latency.py` keeps greeting delay out of its turn ledger.
    """
    server_ms: list[float] = []
    client_ms: list[float] = []
    for _ in range(warmup):
        await request()
    for _ in range(n):
        started = time.perf_counter()
        response = await request()
        client_ms.append((time.perf_counter() - started) * 1000)
        assert response.status_code == expect_status, response.text
        server_ms.append(float(response.headers["X-Ack-Ms"]))
    return distribution(server_ms), distribution(client_ms)


async def measure_concurrent(
    request: AckRequest, width: int, *, warmup: int = 5, expect_status: int = 202
) -> dict[str, float]:
    """Server-measured ack for `width` requests released at ONE event-loop tick.

    `asyncio.Barrier`, for the reason `webhook_storm_test.py` records: creating N tasks
    staggers them by however long each takes to reach its first await, so without the
    barrier nothing ever overlaps and the measurement is N sequential requests wearing a
    concurrency label.
    """
    for _ in range(warmup):
        await request()

    gate = asyncio.Barrier(width)
    server_ms: list[float] = []

    async def _one() -> None:
        await gate.wait()
        response = await request()
        assert response.status_code == expect_status, response.text
        server_ms.append(float(response.headers["X-Ack-Ms"]))

    async with asyncio.TaskGroup() as group:
        for _ in range(width):
            group.create_task(_one())
    return distribution(server_ms)


__all__ = [
    "AckRequest",
    "assert_well_formed",
    "distribution",
    "measure_concurrent",
    "measure_sequential",
    "percentile",
]

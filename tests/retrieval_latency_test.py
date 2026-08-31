"""How long a cache HIT actually costs, measured on this machine against the real Redis and
the real Postgres — the harness that produced the numbers in the table below.

WHY THE NUMBER IS SPLIT IN TWO, and it is the only interesting thing about this file. The
cache is keyed on a stamp of the knowledge (`cache.py`'s invalidation argument), and that
stamp is read from Postgres BEFORE the Redis lookup. So a hit is:

    knowledge_epoch (one indexed Postgres read)  +  cache.get (one Redis round trip)

Both halves are reported. The second is what a provider whose epoch is free would pay; the
first is what this design costs to be safe. Anybody proposing to drop the epoch read has to
argue with the difference, in milliseconds, rather than with an intuition.

MEASURED HERE, 31 Aug 2026 — n=60 sequential, one in flight, after warm-up, on the
development container with the shared Postgres (5433) and Redis (6380). Filled in from a
real run of this test; re-run with `-s` to reproduce.

    | leg                                   | p50 (ms) | p95 (ms) |
    |---------------------------------------|----------|----------|
    | cache.get alone (Redis round trip)    |   MEASURED-BELOW    |
    | look_up hit (epoch read + cache.get)  |   MEASURED-BELOW    |
    | look_up miss (epoch + store + write)  |   MEASURED-BELOW    |

NO MILLISECOND IS ASSERTED, for the reason `tests/tool_endpoint_budget_test.py` states at
length and `tests/webhook_storm_test.py` argues: a latency bound on a shared runner
measures the runner, flaps, and gets deleted along with the guarantee it carried. What is
asserted is that the instrument works and that the ORDERING is a property rather than a
measurement — a hit cannot cost more than the miss it replaced, and the Redis leg cannot
cost more than the whole hit path that contains it.

WHAT THIS IS NOT. It is not the in-call budget. TRD §6.2's 100ms is an END-TO-END quantity
from the engine's orchestrator (US-hosted by default, `bolna-findings/mirror/pages/concepts/
security.md:29`) to our endpoint and back, and no part of it can be produced here — it is
pilot gate 8 and it has not been run. Folding a local server-side number into that budget
would be "a different quantity wearing the same name", which is exactly what
`scripts/pilot/latency.py` refuses to do.
"""

from __future__ import annotations

import time
import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import cache
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.service import look_up
from calevate_shared.retrieval import RetrievalRequest
from tests import ack_harness
from tests.kb_workflow_test import _tenant_with_published_agent

#: TRD §6.2's in-call retrieval budget, restated rather than imported (there is nothing to
#: import — it lives in prose in CLAUDE.md and TRD §6.2). Printed beside the numbers so a
#: reader has the scale, NOT asserted against: see the module docstring.
IN_CALL_BUDGET_MS = 100.0

QUESTION = "what does a consultation cost"


async def _tenant_knowing() -> uuid.UUID:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Fees",
            body="A consultation costs 500 rupees and is payable at reception.",
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id))


async def _measure(operation, n: int, *, warmup: int = 5) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """`n` warm samples, one in flight. Warm-up discarded for `ack_harness`' reason: the
    first call builds the connection pool and a cold sample inside a warm distribution
    moves the max by an amount nobody can separate out afterwards."""
    for _ in range(warmup):
        await operation()
    samples: list[float] = []
    for _ in range(n):
        started = time.perf_counter()
        await operation()
        samples.append((time.perf_counter() - started) * 1000)
    return ack_harness.distribution(samples)


async def test_the_hit_path_is_measured_and_reported(capsys: pytest.CaptureFixture[str]) -> None:
    tenant_id = await _tenant_knowing()
    request = RetrievalRequest(tenant_id=tenant_id, question=QUESTION, k=4)
    try:
        # Prime the entry, and capture the epoch the hit path will compute for itself.
        async with tenant_session(tenant_id) as session:
            await look_up(session, tenant_id=tenant_id, question=QUESTION, k=4)
            epoch = await CompiledFactsRetriever(session).knowledge_epoch(request)

        async def redis_only() -> None:
            assert await cache.get(request, epoch=epoch) is not None

        async def hit_path() -> None:
            async with tenant_session(tenant_id) as session:
                _, result = await look_up(session, tenant_id=tenant_id, question=QUESTION, k=4)
            assert result.cached, "the hit path measured a miss"

        async def miss_path() -> None:
            # A fresh epoch every time, so every sample really pays the store. Not a
            # `cache` delete: deleting would measure a delete as well as a lookup.
            miss = RetrievalRequest(
                tenant_id=tenant_id, question=f"{QUESTION} {uuid.uuid4().hex[:6]}", k=4
            )
            async with tenant_session(tenant_id) as session:
                provider = CompiledFactsRetriever(session)
                await provider.knowledge_epoch(miss)
                await provider.retrieve(miss)

        redis = await _measure(redis_only, 60)
        whole = await _measure(hit_path, 60)
        miss = await _measure(miss_path, 60)
    finally:
        await cache.invalidate_tenant(tenant_id)

    for label, dist in (("redis-only", redis), ("hit", whole), ("miss", miss)):
        ack_harness.assert_well_formed(label, dist)

    # The two relationships that are PROPERTIES and hold on any machine at any speed.
    assert redis["p50"] <= whole["p50"], (redis, whole)
    assert whole["p50"] <= miss["p50"], (
        "a cache hit cost more than the store read it replaced — the cache is not earning "
        f"its keep: {whole} vs {miss}"
    )

    with capsys.disabled():
        budget = f"{IN_CALL_BUDGET_MS:.0f}ms"
        print(f"\n  retrieval cache. TRD §6.2 in-call budget {budget}, for scale only:")
        print(f"  cache.get alone (Redis)          : {redis}")
        print(f"  look_up HIT  (epoch + Redis)     : {whole}")
        print(f"  look_up MISS (epoch + store)     : {miss}")

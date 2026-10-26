"""Knowledge-gap service: idempotency, the aggregate roll-up, and the client mutations.

Every test builds a real tenant (org + its default agent) and real `calls` rows, because
the aggregate joins occurrences to `calls` for its first/last-seen instants and the whole
point of `record_call_gaps` is what it writes to the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import create_org_with_receptionist

from apps.api.core.context import Principal
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.insights import detection, service
from apps.api.insights.detection import RedactedTurn


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Gaps Clinic",
        slug=f"gaps-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, started_at: datetime) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :ecid, 'inbound', "
                "'completed', :at, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "ecid": f"gap-{uuid.uuid4().hex}",
                "at": started_at,
            },
        )
    return call_id


def _pricing_turns() -> list[RedactedTurn]:
    return [
        RedactedTurn(speaker="caller", text="How much is the consultation fee?"),
        RedactedTurn(speaker="agent", text="I don't know the price, I'll WhatsApp you."),
    ]


def _client_principal(tenant_id: uuid.UUID) -> Principal:
    # user_id=None: `knowledge_gaps.resolved_by` and `kb_sources.submitted_by` are both
    # nullable, so a test principal needs no real users row for the mutation FKs.
    return Principal(realm="client", user_id=None, tenant_id=tenant_id, role="owner")


async def test_one_call_with_a_gap_creates_one_aggregate() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    count = await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    assert count == 1
    async with tenant_session(tenant_id) as session:
        result = await service.list_gaps(session)
    assert result.open_count == 1
    assert result.total == 1
    gap = result.items[0]
    assert gap.topic_key == "pricing"
    assert gap.occurrence_count == 1
    assert gap.call_count == 1
    assert gap.signal == "dont_know"
    assert "WhatsApp" in gap.example_answer


async def test_reprocessing_the_same_call_does_not_double_count() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    for _ in range(3):
        await service.record_call_gaps(
            tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
        )
    async with tenant_session(tenant_id) as session:
        result = await service.list_gaps(session)
        occ = (
            await session.execute(
                text("SELECT count(*) FROM knowledge_gap_occurrences WHERE call_id = :c"),
                {"c": call_id},
            )
        ).scalar()
    assert occ == 1  # exactly-once: three runs, one occurrence row
    assert result.items[0].occurrence_count == 1
    assert result.items[0].call_count == 1


async def test_the_same_topic_on_two_calls_is_two_on_two_calls() -> None:
    tenant_id, agent_id = await _tenant()
    now = datetime.now(UTC)
    call_a = await _call(tenant_id, agent_id, now - timedelta(hours=1))
    call_b = await _call(tenant_id, agent_id, now)
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_a, turns=_pricing_turns()
    )
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_b, turns=_pricing_turns()
    )
    async with tenant_session(tenant_id) as session:
        result = await service.list_gaps(session)
    assert result.total == 1
    gap = result.items[0]
    assert gap.occurrence_count == 2
    assert gap.call_count == 2


async def test_a_reprocess_that_drops_a_topic_shrinks_the_aggregate() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    # Re-run with a clean transcript: the pricing gap this call contributed is gone, and it
    # was the only call, so the aggregate is removed rather than left orphaned at open.
    await service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        turns=[RedactedTurn(speaker="agent", text="It is 500 rupees.")],
    )
    async with tenant_session(tenant_id) as session:
        result = await service.list_gaps(session, status=None)
    assert result.total == 0


async def test_urgency_ordering_open_first_then_most_frequent() -> None:
    tenant_id, agent_id = await _tenant()
    now = datetime.now(UTC)
    # A pricing gap on two calls (frequent), a timings gap on one (less frequent).
    for i in range(2):
        call_id = await _call(tenant_id, agent_id, now - timedelta(minutes=i))
        await service.record_call_gaps(
            tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
        )
    timings_call = await _call(tenant_id, agent_id, now)
    await service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=timings_call,
        turns=[
            RedactedTurn(speaker="caller", text="What are your Sunday hours?"),
            RedactedTurn(speaker="agent", text="I don't know the hours."),
        ],
    )
    async with tenant_session(tenant_id) as session:
        result = await service.list_gaps(session, status="open")
    assert [g.topic_key for g in result.items] == ["pricing", "timings"]
    assert result.open_count == 2


async def test_list_gaps_filtered_by_one_agent_excludes_the_others() -> None:
    """The `agent_id` filter on both the page query and the count query — a tenant with
    two agents asking for one agent's gaps must see only that agent's, and the badge
    counts must be scoped the same way."""
    tenant_id, agent_a = await _tenant()
    # A second agent under the same tenant, gap-bearing so an unfiltered list would mix.
    async with tenant_session(tenant_id) as session:
        agent_b = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
                "created_at, updated_at) VALUES (:id, :t, 'Second Agent', 'inbound', 'This is "
                "an AI.', 'This is an AI.', 'This call is recorded.', 'I keep a short note of "
                "what you ask about.', now(), now())"
            ),
            {"id": agent_b, "t": tenant_id},
        )
    call_a = await _call(tenant_id, agent_a, datetime.now(UTC))
    call_b = await _call(tenant_id, agent_b, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_a, call_id=call_a, turns=_pricing_turns()
    )
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_b, call_id=call_b, turns=_pricing_turns()
    )
    async with tenant_session(tenant_id) as session:
        only_a = await service.list_gaps(session, agent_id=agent_a)
    assert only_a.total == 1
    assert only_a.open_count == 1
    assert all(g.agent_id == agent_a for g in only_a.items)


#: Enough topics that a hash order is almost never sorted by chance, plus phrase-derived
#: keys (`detection._topic`) whose `_` and Telugu letters are where a locale collation and
#: codepoint order disagree.
_MANY_TOPICS = (
    "parking",
    "hours",
    "insurance",
    "pricing",
    "q_a_b",
    "q_aa",
    "q_\u0c05\u0c21",
    "refunds",
)


def _gaps_for(keys: tuple[str, ...]) -> list[detection.DetectedGap]:
    return [
        detection.DetectedGap(
            topic_key=key,
            topic_label=key.title(),
            question_redacted=f"What about {key}?",
            answer_redacted="I don't know.",
            signal="dont_know",
        )
        for key in keys
    ]


async def _aggregate_lock_order(
    monkeypatch: pytest.MonkeyPatch, run: Callable[[], Awaitable[object]]
) -> list[str]:
    """The topic order in which `run` takes the aggregate row locks."""
    order: list[str] = []
    real = service._recompute_aggregate

    async def spy(session: AsyncSession, **kwargs: Any) -> None:
        order.append(kwargs["topic_key"])
        await real(session, **kwargs)

    monkeypatch.setattr(service, "_recompute_aggregate", spy)
    await run()
    monkeypatch.setattr(service, "_recompute_aggregate", real)
    return order


async def test_two_calls_take_the_aggregate_locks_in_one_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every writer locks `knowledge_gaps` rows in topic order, or two pipelines deadlock.

    Each recompute locks its aggregate row (STEP 1's upsert) and holds it until commit, and
    one call's topics are recomputed in one transaction. Iterating a Python `set` made the
    order a function of string hashing, which is randomised PER PROCESS — so two workers
    finishing calls that share two topics could each hold one row and wait on the other,
    and Postgres aborts one pipeline run mid-way (its lead upsert and metering with it)
    until the retry.
    """
    tenant_id, agent_id = await _tenant()
    monkeypatch.setattr(detection, "detect_gaps", lambda _turns: _gaps_for(_MANY_TOPICS))
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))

    recorded = await _aggregate_lock_order(
        monkeypatch,
        lambda: service.record_call_gaps(
            tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
        ),
    )
    assert recorded == sorted(_MANY_TOPICS), recorded

    async def scrub() -> int:
        async with tenant_session(tenant_id) as session:
            # A HashAggregate DISTINCT, so the rows arrive in hash order: a sort-based plan
            # under this database's C collation would hand them over sorted by accident,
            # and a production database's locale collation would not.
            await session.execute(text("SET LOCAL enable_sort = off"))
            return await service.scrub_quotes_for_calls(
                session, call_ids=[call_id], mark="[erased]"
            )

    scrubbed = await _aggregate_lock_order(monkeypatch, scrub)
    assert scrubbed == sorted(_MANY_TOPICS), (
        "the erasure path recomputes the same rows and must take them in the same order"
    )

"""Knowledge-gap service: idempotency, the aggregate roll-up, and the client mutations.

Every test builds a real tenant (org + its default agent) and real `calls` rows, because
the aggregate joins occurrences to `calls` for its first/last-seen instants and the whole
point of `record_call_gaps` is what it writes to the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from apps.api.admin import service as admin_service
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.insights import service
from apps.api.insights.detection import RedactedTurn
from apps.api.insights.schemas import GapTeachIn


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
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


async def test_dismiss_moves_a_gap_off_the_open_list() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    principal = _client_principal(tenant_id)
    async with tenant_session(tenant_id) as session:
        gap = (await service.list_gaps(session)).items[0]
        dismissed = await service.dismiss_gap(
            session, gap.id, principal=principal, reason="Not something we sell"
        )
        assert dismissed.status == "dismissed"
        assert (await service.list_gaps(session, status="open")).open_count == 0
        # Still visible in the full history, occurrences intact.
        assert (await service.list_gaps(session, status=None)).total == 1


async def test_teach_records_the_answer_and_seeds_a_kb_draft() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    principal = _client_principal(tenant_id)
    async with tenant_session(tenant_id) as session:
        gap = (await service.list_gaps(session)).items[0]
        taught = await service.teach_gap(
            session,
            gap.id,
            principal=principal,
            payload=GapTeachIn(answer="Consultation is 500 rupees.", create_kb_draft=True),
        )
        assert taught.status == "taught"
        assert taught.resolution == "Consultation is 500 rupees."
        # A pending_approval KB draft was seeded for this agent.
        drafts = (
            await session.execute(
                text(
                    "SELECT status, name FROM kb_sources WHERE agent_id = :a "
                    "AND status = 'pending_approval'"
                ),
                {"a": agent_id},
            )
        ).all()
        assert any("Pricing" in row.name for row in drafts)
        assert (await service.list_gaps(session, status="open")).open_count == 0


async def test_teach_without_a_draft_still_records_the_answer() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    principal = _client_principal(tenant_id)
    async with tenant_session(tenant_id) as session:
        gap = (await service.list_gaps(session)).items[0]
        taught = await service.teach_gap(
            session,
            gap.id,
            principal=principal,
            payload=GapTeachIn(answer="500 rupees.", create_kb_draft=False),
        )
        assert taught.status == "taught"
        drafts = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert drafts == 0


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


async def test_dismissing_a_gap_that_names_nothing_is_a_404() -> None:
    """`_load_gap`'s not-found arm: a gap id that is no tenant's (or another tenant's,
    which RLS makes indistinguishable) 404s before any write happens."""
    tenant_id, _agent_id = await _tenant()
    principal = _client_principal(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await service.dismiss_gap(session, uuid7(), principal=principal, reason=None)
    assert caught.value.status == 404
    assert caught.value.code == "not_found"

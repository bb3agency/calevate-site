"""The caller-data embedding sweep settles, and meters, one batch at a time.

`embed_caller_chunks` buys vectors from the provider in batches and records each purchase
on the platform ledger (`platform_ai_usage`, the only ceiling this job has). A purchase
that has been paid for must reach that ledger whatever happens to the NEXT one.

The scope is a stub `CallerProjection`: what is under test is the sweep's transaction
shape, not what a lead or a transcript projects into, and the real scopes' discovery is
exercised by their own suites.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.retrieval.caller_projections import CallerProjection, ChunkKey, ProjectedChunk
from apps.api.retrieval.embedding import EMBEDDING_DIMS, EMBEDDING_MODEL
from apps.workers import caller_embeddings, chat
from apps.workers.chat import ChatLeg, EmbeddingOutcome, TokenUsage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.kb_workflow_test import _tenant_with_published_agent

_LEG = ChatLeg(
    url="https://example.invalid/embeddings", api_key="k", wire_model="d", dialect="openai"
)


@pytest.fixture
def priced() -> Any:
    install_llm_price_attestations(
        lambda: {
            EMBEDDING_MODEL: LlmPriceAttestation(
                model=EMBEDDING_MODEL,
                input_usd_per_mtok=Decimal("0.02"),
                output_usd_per_mtok=Decimal("0.02"),
                read_on=date(2026, 9, 1),
                attested_by="test",
                source="fixture",
            )
        }
    )
    yield
    install_llm_price_attestations(None)


def _stub_scope(agent_id: uuid.UUID) -> tuple[CallerProjection, list[uuid.UUID]]:
    """A `lead`-kind scope with two subjects, each one chunk."""
    subjects = [uuid.uuid4(), uuid.uuid4()]
    bodies = {(sid, 0): f"Wants a site visit on Saturday ({n})." for n, sid in enumerate(subjects)}

    async def discover(_session: AsyncSession, _limit: int) -> Sequence[ProjectedChunk]:
        return [
            ProjectedChunk(
                subject_id=sid,
                idx=0,
                text=bodies[(sid, 0)],
                agent_id=agent_id,
                phone_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
                occurred_at=datetime.now(UTC),
            )
            for sid in subjects
        ]

    async def content_for(
        _session: AsyncSession, keys: Sequence[ChunkKey]
    ) -> Mapping[ChunkKey, str]:
        return {key: bodies[key] for key in keys if key in bodies}

    return CallerProjection(subject_kind="lead", discover=discover, content_for=content_for), (
        subjects
    )


async def _platform_rows() -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM platform_ai_usage "
                        "WHERE meta->>'feature' = 'caller_embed'"
                    )
                )
            ).scalar_one()
        )


async def test_a_later_batch_failing_does_not_unrecord_a_batch_already_paid_for(
    monkeypatch: pytest.MonkeyPatch, priced: Any
) -> None:
    """A tenant's batches used to share one transaction, so a transport failure on the
    second request rolled back the first batch's vectors, states AND its platform-ledger
    rows after it had been paid for — spend the platform brake never saw, bought again on
    the next tick."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id = uuid.UUID(str(tenant_id))
    scope, subjects = _stub_scope(uuid.UUID(str(agent_id)))

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(caller_embeddings, "registered_projections", lambda: (scope,))
    monkeypatch.setattr(caller_embeddings, "tenants_with_caller_data", _only_this_tenant)
    monkeypatch.setattr(caller_embeddings, "embedding_leg", lambda: _LEG)
    monkeypatch.setattr(caller_embeddings, "EMBED_BATCH", 1)
    calls: list[int] = []

    async def _second_fails(leg: ChatLeg, inputs: Sequence[str], **_: Any) -> EmbeddingOutcome:
        if calls:
            raise httpx.ConnectError("provider unavailable")
        calls.append(len(inputs))
        return EmbeddingOutcome(
            vectors=tuple(tuple(0.0 for _ in range(EMBEDDING_DIMS)) for _ in inputs),
            usage=TokenUsage(11 * len(inputs), 0),
        )

    monkeypatch.setattr(chat, "embed", _second_fails)
    before = await _platform_rows()

    await caller_embeddings.embed_caller_chunks({})

    async with tenant_session(tenant_id) as session:
        states = sorted(
            (str(row[0]), bool(row[1]))
            for row in (
                await session.execute(
                    text(
                        "SELECT embed_state, embedding IS NOT NULL FROM caller_chunks "
                        "WHERE subject_id = ANY(:ids)"
                    ),
                    {"ids": subjects},
                )
            ).all()
        )
    assert states == [("pending", False), ("ready", True)], (
        "the paid batch is stored; the failed one is left for the next tick"
    )
    assert await _platform_rows() > before, "the batch that was paid for is on the ledger"

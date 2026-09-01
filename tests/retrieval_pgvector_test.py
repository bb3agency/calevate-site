"""The T3 store end to end: the dense arm, the fusion, the money, and the OFF switch.

`tests/kb_chunks_rls_test.py` owns the tenancy half. This file owns everything that is not
tenancy, and it drives the REAL statement against the REAL table — a mocked SQL layer would
prove nothing about a query whose whole subject is what Postgres does with two indexes.

The provider is faked at ONE seam: `apps/workers/chat.embed`, the wire call. Everything
below it — the price gate, the metering, the vector's trip into `vector(1536)` and back out
through `<=>` — runs for real, because those are the parts that break.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.models import EMBED_READY
from apps.api.retrieval import pgvector as pgvector_module
from apps.api.retrieval import service as retrieval_service
from apps.api.retrieval.embedding import EMBEDDING_DIMS, EMBEDDING_MODEL
from apps.api.retrieval.pgvector import PgVectorRetriever
from apps.api.retrieval.tiered import KnowledgeRetriever
from apps.workers import chat
from apps.workers.chat import ChatLeg, EmbeddingOutcome, TokenUsage
from calevate_shared.retrieval import RetrievalRequest
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

_LEG = ChatLeg(
    url="https://example.invalid/embeddings", api_key="k", wire_model="d", dialect="openai"
)


def _unit_vector(seed: int) -> tuple[float, ...]:
    """A vector that is 1.0 in exactly one coordinate.

    ORTHOGONAL BY CONSTRUCTION, which is what makes the assertions below deterministic: two
    different seeds are at cosine distance 1 and a seed matches itself at 0, so "the dense
    arm ranked the right chunk first" is a fact about the query rather than a coin flip on
    random floats. The bake-off's own harness used random vectors precisely because it was
    measuring LATENCY and explicitly reported no recall figure; this file is measuring
    behaviour, so it needs vectors whose answer is known.
    """
    return tuple(1.0 if i == seed % EMBEDDING_DIMS else 0.0 for i in range(EMBEDDING_DIMS))


@pytest.fixture
def attested_embedding_price() -> Any:
    """An operator attestation for the embedding model, installed and then removed.

    This is the ONLY thing that makes an embedding billable today: no vendor page publishing
    an embedding price has been read from this container, so `LLM_MODELS` carries no
    catalogue figure for one and `llm_inr_per_ktok` would refuse. The fixture is therefore
    also the documentation of what an operator has to do before the sweep spends anything.
    """
    attestation = LlmPriceAttestation(
        model=EMBEDDING_MODEL,
        input_usd_per_mtok=Decimal("0.02"),
        # EQUAL TO THE INPUT, and it never multiplies anything: an embedding response has no
        # output tokens at all, so every `ai_assist_ktok_out` row this path writes is qty 0.
        output_usd_per_mtok=Decimal("0.02"),
        read_on=date(2026, 9, 1),
        attested_by="test",
        source="fixture",
    )
    install_llm_price_attestations(lambda: {EMBEDDING_MODEL: attestation})
    yield attestation
    install_llm_price_attestations(None)


async def _published(tenant_id: Any, agent_id: Any, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(submitted["id"]))


async def _corpus() -> tuple[uuid.UUID, uuid.UUID]:
    """Two published sources, each embedded at its own orthogonal coordinate."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _published(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _published(tenant_id, agent_id, "Parking", "Valet parking is free for patients.")
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.id, d.content FROM kb_chunks c JOIN kb_documents d "
                    "ON d.id = c.document_id ORDER BY d.content"
                )
            )
        ).all()
        for seed, row in enumerate(rows):
            await session.execute(
                text(
                    "UPDATE kb_chunks SET embedding = CAST(:v AS vector), embed_state = :s, "
                    "embed_model = :m, embed_dim = :d WHERE id = :i"
                ),
                {
                    "i": row[0],
                    "v": "[" + ",".join(map(repr, _unit_vector(seed))) + "]",
                    "s": EMBED_READY,
                    "m": EMBEDDING_MODEL,
                    "d": EMBEDDING_DIMS,
                },
            )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


#: The usage block every fake response carries. A module-level singleton rather than a
#: default argument, which ruff refuses (B008) and which would share one object anyway.
_USAGE = TokenUsage(7, 0)


def _fake_embed(vector: Sequence[float], *, usage: TokenUsage | None = _USAGE) -> Any:
    async def _embed(leg: ChatLeg, inputs: Sequence[str], **kwargs: Any) -> EmbeddingOutcome:
        return EmbeddingOutcome(vectors=tuple(tuple(vector) for _ in inputs), usage=usage)

    return _embed


async def test_the_dense_arm_ranks_the_chunk_its_vector_points_at(
    monkeypatch: pytest.MonkeyPatch, attested_embedding_price: Any
) -> None:
    """The whole round trip: a question is embedded, the vector reaches `<=>`, and the chunk
    at that coordinate wins — even though the question shares NO WORDS with it.

    The question is deliberately word-disjoint from the answer ("where do I leave the car"
    against "Valet parking is free for patients"), so the sparse arm cannot produce this
    result. If the dense arm were silently dropped, this test would return the other chunk
    or nothing at all — which is exactly how a broken vector cast would present.
    """
    tenant_id, _ = await _corpus()
    # Seed 1 is the SECOND row by content order — "Valet parking…" sorts after "A
    # consultation…", so this is the parking chunk's own coordinate.
    monkeypatch.setattr(chat, "embed", _fake_embed(_unit_vector(1)))
    monkeypatch.setattr(pgvector_module, "embedding_leg", lambda: _LEG)

    async with tenant_session(tenant_id) as session:
        result = await PgVectorRetriever(session).retrieve(
            RetrievalRequest(tenant_id=tenant_id, question="where do I leave the car", tier="t3")
        )
    assert result.served_tier == "t3"
    assert result.provider == "pgvector"
    assert "parking" in result.passages[0].text.lower()
    # The provenance is the SOURCE's own name, which is what makes a citation checkable by
    # the client who typed it.
    assert result.passages[0].provenance.label == "Parking"
    assert result.passages[0].provenance.source_id is not None


async def test_the_question_embedding_is_metered_against_the_tenant(
    monkeypatch: pytest.MonkeyPatch, attested_embedding_price: Any
) -> None:
    """Hard rule 7: the search's own model call reaches `usage_events` under its own feature
    name, with an output quantity of zero because an embedding has no output tokens."""
    tenant_id, _ = await _corpus()
    monkeypatch.setattr(chat, "embed", _fake_embed(_unit_vector(0)))
    monkeypatch.setattr(pgvector_module, "embedding_leg", lambda: _LEG)

    async with tenant_session(tenant_id) as session:
        await PgVectorRetriever(session).retrieve(
            RetrievalRequest(tenant_id=tenant_id, question="what does it cost", tier="t3")
        )
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty FROM usage_events "
                    "WHERE meta->>'feature' = 'kb_search_embedding' ORDER BY unit_type"
                )
            )
        ).all()
    assert [(str(r[0]), Decimal(str(r[1]))) for r in rows] == [
        ("ai_assist_ktok_in", Decimal("0.007")),
        ("ai_assist_ktok_out", Decimal("0")),
    ]


async def test_an_unpriced_model_is_never_bought_and_the_sparse_arm_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money gate, and the degradation it chooses.

    With no attestation installed, `llm_inr_per_ktok` would raise INSIDE the metering call —
    after the provider had been paid. So nothing is bought at all, and the answer comes from
    the keyword arm. Proved by making the wire call fail loudly: if it were reached, this
    test would error rather than pass.
    """

    async def _explode(*_a: Any, **_k: Any) -> EmbeddingOutcome:
        raise AssertionError("an unpriced embedding must never reach the provider")

    tenant_id, _ = await _corpus()
    monkeypatch.setattr(chat, "embed", _explode)
    monkeypatch.setattr(pgvector_module, "embedding_leg", lambda: _LEG)

    async with tenant_session(tenant_id) as session:
        result = await PgVectorRetriever(session).retrieve(
            RetrievalRequest(
                tenant_id=tenant_id, question="what does a consultation cost", tier="t3"
            )
        )
    assert "consultation" in result.passages[0].text


async def test_the_epoch_moves_when_the_sweep_lands_a_vector() -> None:
    """The cache-invalidation stamp's third term, which is the one a reader would omit.

    Publishing moves the count and the version; the sweep filling `embedding` moves NEITHER
    while changing every answer the store gives. Without this term the copilot would keep
    serving the sparse-only result for the whole cache TTL after the vectors landed.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _published(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    request = RetrievalRequest(tenant_id=uuid.UUID(str(tenant_id)), question="cost", tier="t3")
    async with tenant_session(tenant_id) as session:
        before = await PgVectorRetriever(session).knowledge_epoch(request)
        await session.execute(
            text(
                "UPDATE kb_chunks SET embedding = CAST(:v AS vector), embed_state = :s "
                "WHERE tenant_id = :t"
            ),
            {
                "v": "[" + ",".join(map(repr, _unit_vector(3))) + "]",
                "s": EMBED_READY,
                "t": tenant_id,
            },
        )
        after = await PgVectorRetriever(session).knowledge_epoch(request)
    assert before != after


async def test_the_selector_falls_back_to_t0_when_the_store_is_named_but_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`retrieval_provider = pgvector` with no embedding deployment is a CONTRADICTION between
    two settings, and it degrades to a working T0 rather than serving an empty dense arm."""
    monkeypatch.setattr(retrieval_service, "embedding_leg", lambda: None)
    monkeypatch.setattr(retrieval_service, "embedding_price_is_billable", lambda: True)
    tenant_id, _ = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        settings = retrieval_service.get_settings()
        monkeypatch.setattr(settings, "retrieval_provider", "pgvector")
        assert retrieval_service.get_retriever(session).name == "compiled-facts"


async def test_the_composite_answers_t0_from_the_block_and_t3_from_the_store(
    monkeypatch: pytest.MonkeyPatch, attested_embedding_price: Any
) -> None:
    """The dispatch, and the reason the composite exists.

    T0 and T3 are DIFFERENT CORPORA: the compiled block is what the agent actually speaks
    from, `kb_chunks` is every approved chunk. A composite that sent both tiers to one member
    would answer "what does my agent say about X" out of the wider corpus, which is the
    wrong question — so this asserts the two tiers land in two different providers.
    """
    tenant_id, _ = await _corpus()
    monkeypatch.setattr(chat, "embed", _fake_embed(_unit_vector(1)))
    monkeypatch.setattr(pgvector_module, "embedding_leg", lambda: _LEG)

    async with tenant_session(tenant_id) as session:
        composite = KnowledgeRetriever(session)
        assert composite.capabilities.compiled_facts is True
        assert composite.capabilities.hybrid_search is True
        # `per_tenant_namespace` is ANDed, never ORed: the composite isolates tenants only if
        # every member does, and one member's guarantee may not vouch for another's.
        assert composite.capabilities.per_tenant_namespace is True

        t0 = await composite.retrieve(
            RetrievalRequest(tenant_id=tenant_id, question="what are your hours", tier="t0")
        )
        t3 = await composite.retrieve(
            RetrievalRequest(tenant_id=tenant_id, question="where do I leave the car", tier="t3")
        )
    assert t0.served_tier == "t0"
    assert t3.served_tier == "t3"
    # The composite reports ITS OWN name on both, so the one observability field that says
    # where an answer came from names the thing the caller actually holds.
    assert t0.provider == t3.provider == "knowledge"

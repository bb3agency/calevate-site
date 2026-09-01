"""The ingestion sweep: idempotent, resumable, gloss-aware, and it never spends unpriced.

FOUR PROPERTIES, and each one is a way this job could quietly lose money or quality:

1. **It does not run at all until a price exists.** `record_ai_assist_usage` derives the
   price from the model and RAISES for a model nobody priced — after the provider has been
   paid. In a worker that raise rolls back the claim, so the chunk returns to `pending` and
   the next tick buys the identical vector to reach the identical raise. The gate is what
   turns an unbounded spend-and-forget loop into one log line.
2. **A second tick over the same corpus buys nothing**, because `embed_state` is the
   idempotency key and it is written in the same transaction as the vector.
3. **It waits for the English gloss.** The gloss is part of what gets embedded (D-489), and
   a chunk vectorised before its gloss arrives carries a key for half its content — for
   ever, because nothing re-embeds a `ready` row.
4. **A vector of the wrong width is REFUSED, not left pending.** The next tick would buy the
   same wrong answer, so the state has to stop the loop.
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
from apps.api.kb.gloss import GLOSS_NOT_NEEDED, GLOSS_PENDING, GLOSS_READY
from apps.api.retrieval.embedding import EMBEDDING_DIMS, EMBEDDING_MODEL
from apps.workers import chat, kb_embeddings
from apps.workers.chat import ChatLeg, EmbeddingOutcome, TokenUsage
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

_LEG = ChatLeg(
    url="https://example.invalid/embeddings", api_key="k", wire_model="d", dialect="openai"
)

_TELUGU = "సన్‌రైజ్ క్లినిక్ ఆదివారం ఉదయం 9 నుండి మధ్యాహ్నం 12 వరకు తెరిచి ఉంటుంది."


@pytest.fixture
def priced() -> Any:
    """The operator attestation without which this sweep does nothing. See `unpriced` below
    for the test that this fixture's absence is itself a behaviour."""
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


def _counting_embed(calls: list[int], *, width: int = EMBEDDING_DIMS) -> Any:
    async def _embed(leg: ChatLeg, inputs: Sequence[str], **kwargs: Any) -> EmbeddingOutcome:
        calls.append(len(inputs))
        return EmbeddingOutcome(
            vectors=tuple(tuple(0.0 for _ in range(width)) for _ in inputs),
            usage=TokenUsage(11 * len(inputs), 0),
        )

    return _embed


async def _settle_gloss(tenant_id: uuid.UUID, *, state: str = GLOSS_NOT_NEEDED) -> None:
    """What the FREE branch of `write_knowledge_glosses` does to an English chunk.

    Done by hand rather than by driving that sweep because its paid branch needs a chat
    credential this environment does not hold — and the property under test here is the
    embedding sweep's ORDERING, which only needs the gloss question to be settled, not the
    other sweep to have been the one that settled it. `test_the_sweep_waits_for_the_english_
    gloss` is the test that this state actually gates.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_documents SET gloss_state = :s WHERE tenant_id = :t"),
            {"s": state, "t": tenant_id},
        )


async def _tenant_with_pending_chunk(body: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def _states(tenant_id: uuid.UUID) -> list[tuple[str, bool]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT embed_state, embedding IS NOT NULL FROM kb_chunks "
                    "WHERE tenant_id = :t ORDER BY id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), bool(r[1])) for r in rows]


async def _only_tenant(monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID) -> None:
    """Drive the tick over ONE tenant.

    The sweep is fleet-wide with a per-tick ceiling, so a suite that has left work in the
    database elsewhere would otherwise spend the budget before reaching the tenant under
    test — a failure that reads exactly like an idempotency defect and is not one.
    `kb_gloss.tenants_holding_knowledge` exists as a function precisely so this is possible.
    """

    async def _one() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_embeddings, "tenants_holding_knowledge", _one)
    monkeypatch.setattr(kb_embeddings, "embedding_leg", lambda: _LEG)


async def test_an_unpriced_model_is_never_bought(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard rule 7's pre-flight. No attestation installed, so the provider must not be
    reached at all — proved by a wire call that raises if it ever is."""

    async def _explode(*_a: Any, **_k: Any) -> EmbeddingOutcome:
        raise AssertionError("an unpriced embedding must never reach the provider")

    tenant_id, _ = await _tenant_with_pending_chunk("A consultation costs 500 rupees.")
    await _only_tenant(monkeypatch, tenant_id)
    monkeypatch.setattr(chat, "embed", _explode)

    assert await kb_embeddings.embed_knowledge_chunks({}) == "unpriced"
    assert await _states(tenant_id) == [("pending", False)]


async def test_a_second_tick_over_the_same_corpus_buys_nothing(
    monkeypatch: pytest.MonkeyPatch, priced: Any
) -> None:
    """Idempotency, asserted on PROVIDER CALLS rather than on rows.

    A row-count assertion passes against a sweep that re-embeds everything every tick and
    overwrites the same values — which is the expensive version of this bug and the one that
    would never be noticed.
    """
    tenant_id, _ = await _tenant_with_pending_chunk("A consultation costs 500 rupees.")
    await _settle_gloss(tenant_id)
    await _only_tenant(monkeypatch, tenant_id)
    calls: list[int] = []
    monkeypatch.setattr(chat, "embed", _counting_embed(calls))

    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=1"
    assert await _states(tenant_id) == [("ready", True)]
    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=0"
    assert calls == [1]


async def test_the_sweep_waits_for_the_english_gloss(
    monkeypatch: pytest.MonkeyPatch, priced: Any
) -> None:
    """A Telugu chunk whose gloss has not been written is SKIPPED, and picked up once it is.

    Without this the chunk is embedded from its Telugu text alone, permanently — nothing
    re-embeds a `ready` row — and the D-489 measurement that justifies the gloss column is
    silently spent on the T0 ranker only.
    """
    tenant_id, _ = await _tenant_with_pending_chunk(_TELUGU)
    await _only_tenant(monkeypatch, tenant_id)
    calls: list[int] = []
    monkeypatch.setattr(chat, "embed", _counting_embed(calls))

    # `submit_source` leaves every chunk `gloss_state = 'pending'`, which is the real state
    # of a freshly published Telugu source until the gloss sweep reaches it.
    async with tenant_session(tenant_id) as session:
        pending = (
            await session.execute(
                text("SELECT count(*) FROM kb_documents WHERE gloss_state = :s"),
                {"s": GLOSS_PENDING},
            )
        ).scalar_one()
    assert pending == 1

    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=0"
    assert calls == []

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_documents SET gloss = :g, gloss_state = :s WHERE tenant_id = :t"),
            {
                "g": "Sunrise clinic is open Sunday 9 am to 12 noon.",
                "s": GLOSS_READY,
                "t": tenant_id,
            },
        )
    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=1"
    assert calls == [1]


def test_the_gloss_rides_in_the_same_vector_as_the_chunk() -> None:
    """One vector over both keys, not two columns — and the original comes FIRST.

    A unit test rather than a database one because the property is about what text is
    handed to the model, and that is the thing a future refactor would silently change.
    """
    assert kb_embeddings.embedding_input("తెలుగు", "English") == "తెలుగు\nEnglish"
    # An English chunk owes no gloss, and must not get a trailing newline that changes its
    # tokenisation for no reason.
    assert kb_embeddings.embedding_input("English only", "") == "English only"


async def test_a_wrong_width_is_refused_rather_than_left_pending(
    monkeypatch: pytest.MonkeyPatch, priced: Any
) -> None:
    """The state that stops the loop. `pending` here would re-buy the same unusable answer on
    every tick for ever; `refused` costs one alert and no further spend."""
    tenant_id, _ = await _tenant_with_pending_chunk("A consultation costs 500 rupees.")
    await _settle_gloss(tenant_id)
    await _only_tenant(monkeypatch, tenant_id)
    calls: list[int] = []
    monkeypatch.setattr(chat, "embed", _counting_embed(calls, width=EMBEDDING_DIMS - 1))

    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=0"
    assert await _states(tenant_id) == [("refused", False)]
    # And the loop is stopped: the next tick does not ask again.
    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=0"
    assert calls == [1]


async def test_the_spend_reaches_the_ledger_under_its_own_feature_name(
    monkeypatch: pytest.MonkeyPatch, priced: Any
) -> None:
    """Hard rule 7. Filed separately from `kb_gloss` because the two run on the same corpus
    at different unit prices, and one name would make the two curves unseparable."""
    tenant_id, _ = await _tenant_with_pending_chunk("A consultation costs 500 rupees.")
    await _settle_gloss(tenant_id)
    await _only_tenant(monkeypatch, tenant_id)
    monkeypatch.setattr(chat, "embed", _counting_embed([]))
    await kb_embeddings.embed_knowledge_chunks({})

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, meta->>'model' FROM usage_events "
                    "WHERE meta->>'feature' = 'kb_embed' ORDER BY unit_type"
                )
            )
        ).all()
    assert [(str(r[0]), Decimal(str(r[1])), str(r[2])) for r in rows] == [
        ("ai_assist_ktok_in", Decimal("0.011"), EMBEDDING_MODEL),
        # Zero, and it is the truth about an embedding: the vendor's usage block has no
        # output half at all.
        ("ai_assist_ktok_out", Decimal("0"), EMBEDDING_MODEL),
    ]

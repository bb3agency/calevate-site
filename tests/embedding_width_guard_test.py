"""The width preflight: a vector the column cannot hold is never bought.

**THE DEFECT THIS PINS WAS REPRODUCED BEFORE IT WAS FIXED, and it is a money defect rather
than a search-quality one.** `retrieval/embedding.EMBEDDING_DIMS` does two jobs — it sized
`kb_chunks.embedding` and `caller_chunks.embedding` in their migrations, and it is sent as
the provider request's `dimensions`. The two agree only while the constant and the applied
schema were deployed together, and narrowing the constant alone is an inviting move: these
models are Matryoshka-style, so a smaller width is a re-request rather than a re-embedding.

Do it and both sweeps behave like this, measured: the staleness clause in `_CLAIM_SQL`
re-claims every `ready` row (its `embed_dim` no longer matches), the batch is bought, and
the UPDATE dies on `DataError: expected 1536 dimensions`. That raise rolls back the claim
AND the ledger row written in the same transaction, so the tick pays the provider, records
nothing, changes no row, and does it all again in thirty minutes — for every tenant, for
ever, under a generic `except` that reads as one tenant having a bad night.

So the assertions here are on PROVIDER CALLS and on the ledger, never on rows: a row-count
assertion passes against the broken version, because the broken version changes no rows
either.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.retrieval.caller_projections import registered_projections
from apps.api.retrieval.embedding import EMBEDDING_DIMS, stored_vector_width
from apps.workers import caller_embeddings, chat, kb_embeddings
from apps.workers.chat import EmbeddingOutcome
from sqlalchemy import text
from tests.kb_embedding_sweep_test import (
    _LEG,
    _only_tenant,
    _settle_gloss,
    _states,
    _tenant_with_pending_chunk,
    priced,  # noqa: F401  — the operator attestation both sweeps refuse to spend without
)

#: Requested by name rather than as a parameter: the fixture is IMPORTED here, so a
#: parameter of the same name would shadow it and ruff refuses the redefinition (F811).
_PRICED = pytest.mark.usefixtures("priced")

#: A width neither column was built at. 1024 rather than an absurd number because it is a
#: width these models really do serve, which is what makes the mis-deployment plausible.
_NARROWER = 1024


async def _explode(*_a: Any, **_k: Any) -> EmbeddingOutcome:
    raise AssertionError("a vector the column cannot hold must never be bought")


async def test_the_stored_width_is_read_from_the_catalogue_not_from_a_constant() -> None:
    """The fact that decides the outcome is what the DATABASE will accept, so it is asked
    of the database. A missing table answers None rather than raising inside a sweep."""
    async with untenanted_session() as session:
        assert await stored_vector_width(session, table="kb_chunks") == EMBEDDING_DIMS
        assert await stored_vector_width(session, table="caller_chunks") == EMBEDDING_DIMS
        assert await stored_vector_width(session, table="no_such_projection") is None


@_PRICED
async def test_the_knowledge_sweep_buys_nothing_when_the_column_is_the_wrong_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick refuses BEFORE the provider, and the chunk is left `pending` — which is the
    right state: it is not a bad answer, it is an answer nobody asked for yet."""
    tenant_id, _ = await _tenant_with_pending_chunk("A consultation costs 500 rupees.")
    await _settle_gloss(tenant_id)
    await _only_tenant(monkeypatch, tenant_id)
    monkeypatch.setattr(kb_embeddings, "EMBEDDING_DIMS", _NARROWER)
    monkeypatch.setattr(chat, "embed", _explode)

    assert await kb_embeddings.embed_knowledge_chunks({}) == "width_mismatch"
    assert await _states(tenant_id) == [("pending", False)]
    async with tenant_session(tenant_id) as session:
        spend = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE tenant_id = :t "
                    "AND meta->>'feature' = 'kb_embed'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert spend == 0, "the tick paid a provider for a vector the column cannot hold"


@_PRICED
async def test_the_knowledge_sweep_still_runs_when_the_widths_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard's other half: it must not be a switch that is always off.

    Without this the test above passes against a preflight that refuses unconditionally,
    which would stop every embedding in the fleet and look exactly like a fix.
    """
    tenant_id, _ = await _tenant_with_pending_chunk("We are open 9am to 8pm.")
    await _settle_gloss(tenant_id)
    await _only_tenant(monkeypatch, tenant_id)
    calls: list[int] = []

    async def _embed(_leg: Any, inputs: Any, **_k: Any) -> EmbeddingOutcome:
        calls.append(len(inputs))
        return EmbeddingOutcome(
            vectors=tuple(tuple(0.0 for _ in range(EMBEDDING_DIMS)) for _ in inputs),
            usage=None,
        )

    monkeypatch.setattr(chat, "embed", _embed)
    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=1"
    assert calls == [1]


@_PRICED
async def test_the_caller_sweep_buys_nothing_when_the_column_is_the_wrong_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same preflight on the same store's other table.

    It ends the tick rather than only the embedding phase — the tripped-brake branch's
    choice, for its reason: a sweep that quietly kept projecting under a broken schema
    would look like it was working.
    """
    assert registered_projections(), "premise: at least one caller scope is registered"

    async def _no_tenants() -> list[uuid.UUID]:
        raise AssertionError("the worklist must not be read after the width refusal")

    monkeypatch.setattr(caller_embeddings, "embedding_leg", lambda: _LEG)
    monkeypatch.setattr(caller_embeddings, "tenants_with_caller_data", _no_tenants)
    monkeypatch.setattr(caller_embeddings, "EMBEDDING_DIMS", _NARROWER)
    monkeypatch.setattr(chat, "embed", _explode)

    assert await caller_embeddings.embed_caller_chunks({}) == "width_mismatch"

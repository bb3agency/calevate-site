"""Hard rule 1 on the retrieval projection: a neighbour's chunks are unreachable.

WHY THIS FILE IS NOT CEREMONIAL. `kb_chunks` is the one table in this repository whose
primary query has NO NATURAL KEY TO GET WRONG. A `WHERE lead_id = ?` that leaks returns
somebody else's row and every screen above it looks obviously broken; a vector similarity
query that leaks returns the NEAREST chunk in the whole fleet and looks like an excellent
search result. There is no shape to the wrong answer. So the tenant boundary here is
carried entirely by the FORCEd `tenant_isolation` policy migration `dc1aaeeeff02` ships, and
this file is the evidence that it reaches the table rather than the argument that it should.

Both directions, because they fail differently:

* **RLS's direction** — B's session, selecting with no tenant predicate at all, must see
  none of A's rows. This is the control.
* **The predicate's direction** — the mistake RLS cannot see as a mistake: a caller passing
  tenant A's id on a session opened for tenant B. `retrieval/pgvector.py` re-states
  `tenant_id` in the statement for exactly this, and without it the query returns B's rows
  under A's name and reads as a successful answer about A.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval.pgvector import PgVectorRetriever
from calevate_shared.retrieval import RetrievalRequest
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls


async def _tenant_with_projected_knowledge(fact: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose published knowledge has reached `kb_chunks` the ordinary way.

    Through `submit_source` → `approve_source` → `publish_source`, never by inserting the
    projection directly: the property under test is that the REAL path lands rows the policy
    protects, and a hand-written INSERT would test the policy against a row no client
    workflow produces.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Fees", body=fact
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def test_publishing_projects_the_chunk_into_the_store() -> None:
    """The seam itself: a publish leaves a searchable row, in the publish's own transaction.

    Asserted on the SPARSE KEY rather than on a row count, because a projection with a NULL
    `tsv` would satisfy a count and answer nothing — and `tsv` is what makes a chunk
    findable before the embedding sweep has ever run.
    """
    tenant_id, _ = await _tenant_with_projected_knowledge("A consultation costs 500 rupees.")
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.embed_state, c.is_active, c.tsv::text FROM kb_chunks c "
                    "WHERE c.tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] is True
    # `consultation` survives the English configuration; `costs` is stemmed to `cost`, which
    # is the whole reason that configuration was chosen over `simple`.
    assert "consult" in row[2]
    assert "'cost'" in row[2]


async def test_a_tenant_cannot_read_a_neighbours_chunks() -> None:
    """The zero-rows direction, asserted on the CONTENT the chunk points at rather than on a
    count — a count assertion passes against a leak that returns the right NUMBER of rows."""
    tenant_a, _ = await _tenant_with_projected_knowledge("Sunrise clinic opens on Sunday.")
    tenant_b, _ = await _tenant_with_projected_knowledge("Moonlight clinic opens on Monday.")

    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT d.content FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id"
                )
            )
        ).all()
    seen = {str(r[0]) for r in rows}
    assert any("Moonlight" in text_ for text_ in seen)
    assert not any("Sunrise" in text_ for text_ in seen)
    assert tenant_a != tenant_b


async def test_naming_a_neighbours_tenant_id_on_your_own_session_returns_nothing() -> None:
    """The predicate direction, through the ADAPTER rather than through raw SQL.

    `retrieval/pgvector.py` re-states `tenant_id` on top of RLS precisely so that a caller
    passing tenant A's id on a session opened for tenant B gets NOTHING rather than B's rows
    under A's name. Driving the adapter is what proves the predicate is in the statement
    that actually runs, not in one a test wrote for it.
    """
    tenant_a, _ = await _tenant_with_projected_knowledge("Sunrise clinic opens on Sunday.")
    tenant_b, _ = await _tenant_with_projected_knowledge("Moonlight clinic opens on Monday.")

    async with tenant_session(tenant_b) as session:
        result = await PgVectorRetriever(session).retrieve(
            RetrievalRequest(tenant_id=tenant_a, question="when does the clinic open", tier="t3")
        )
    assert result.passages == ()

    # And the control: the SAME question on B's own id does answer, so the emptiness above
    # is the predicate refusing and not the query being broken.
    async with tenant_session(tenant_b) as session:
        own = await PgVectorRetriever(session).retrieve(
            RetrievalRequest(tenant_id=tenant_b, question="when does the clinic open", tier="t3")
        )
    assert own.passages
    assert "Moonlight" in own.passages[0].text

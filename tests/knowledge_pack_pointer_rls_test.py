"""Hard rule 1 on `agents.knowledge_pack_sha256`: a neighbour cannot read it or move it.

WHY A COLUMN GETS ITS OWN FILE. Migration `b5d3a91e7c64` adds no table and therefore no
policy — `agents` is already FORCE-RLS'd under `tenant_isolation`, and a policy is a rule
about ROWS, so the new column inherits it. That is a correct argument and it is exactly the
kind that is only ever checked by someone reading it. This file is the measurement instead.

WHAT THE COLUMN IS, AND WHY A LEAK HERE IS NOT LIKE A LEAK ON A SCREEN. It is the id of the
knowledge pack a voice worker FETCHES INTO ITS OWN MEMORY at session start and searches on
every turn. With `tenant_id` and `agent_id` it is the whole object key
(`calevate_shared.knowledge_pack.pack_object_key`), so:

* **Reading a neighbour's pointer** is reading the name of their corpus — a digest of their
  approved text, which is not the text, but it is also the coordinate that makes the object
  addressable to anyone who can already reach the bucket.
* **Writing a neighbour's pointer** is the one that ends badly. Pointing clinic B's agent at
  clinic A's digest does not produce a broken screen or an error: the pack VALIDATES, its
  id names its own bytes, and B's agent answers B's callers out of A's price list for the
  life of every warm container that fetched it. The pack's own tenancy check
  (`voice_worker/knowledge.py`) is the second wall; this is the first.

Both directions are asserted, `tests/kb_chunks_rls_test.py`'s reasons: the SELECT that must
see nothing, and the UPDATE that must change nothing.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls


async def _tenant_with_a_pack(fact: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose published knowledge has been frozen into a pack the ordinary way.

    submit → approve → publish, so the pointer under test is the one `publish_source` really
    writes rather than one this file invented — the same reasoning `kb_pack_test` gives for
    never hand-inserting a projection row.
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


async def test_a_neighbour_selecting_the_pointer_gets_zero_rows(s3: FakeS3) -> None:
    """RLS's direction, with NO tenant predicate in the statement at all — the control.

    Asserted as zero ROWS rather than as a NULL pointer: a policy that let the row through
    and merely blanked the column would pass a NULL-shaped assertion, and it is the row's
    visibility that decides everything else on this table.
    """
    tenant_a, agent_a = await _tenant_with_a_pack("Sunrise clinic charges 500 rupees.")
    tenant_b, _ = await _tenant_with_a_pack("Moonlight clinic charges 800 rupees.")

    async with tenant_session(tenant_a) as session:
        mine = (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"), {"aid": agent_a}
            )
        ).all()
    assert len(mine) == 1 and mine[0][0] is not None, "the control failed: A cannot see its own"

    async with tenant_session(tenant_b) as session:
        theirs = (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"), {"aid": agent_a}
            )
        ).all()
    assert theirs == []


async def test_a_neighbour_cannot_repoint_an_agent_at_their_own_pack(s3: FakeS3) -> None:
    """The write direction, which is the one that puts one client's price list in another
    client's call. Zero rows updated, and A's pointer unmoved afterwards."""
    tenant_a, agent_a = await _tenant_with_a_pack("Sunrise clinic charges 500 rupees.")
    tenant_b, agent_b = await _tenant_with_a_pack("Moonlight clinic charges 800 rupees.")

    async with tenant_session(tenant_b) as session:
        theirs = (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"), {"aid": agent_b}
            )
        ).scalar_one()
        seized = await session.execute(
            text("UPDATE agents SET knowledge_pack_sha256 = :sha WHERE id = :aid"),
            {"sha": theirs, "aid": agent_a},
        )
        assert seized.rowcount == 0

    async with tenant_session(tenant_a) as session:
        after = (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"), {"aid": agent_a}
            )
        ).scalar_one()
    assert after != theirs, "tenant B moved tenant A's agent onto tenant B's knowledge"


async def test_the_two_agents_really_did_get_different_packs(s3: FakeS3) -> None:
    """The control for the test above: two tenants publishing different knowledge produce
    different digests, so `after != theirs` is evidence of isolation rather than of two
    packs that happened to be equal.

    Read from EACH TENANT'S OWN SESSION and compared in Python, because there is no session
    that can ask the question directly: `agents` carries the plain FORCEd `tenant_isolation`
    policy with no global-read exemption, so an untenanted read of both rows returns zero of
    them — which is the property the two tests above are measuring, arriving here as a
    constraint on how the control may be written.
    """
    tenant_a, agent_a = await _tenant_with_a_pack("Sunrise clinic charges 500 rupees.")
    tenant_b, agent_b = await _tenant_with_a_pack("Moonlight clinic charges 800 rupees.")

    digests = []
    for tenant_id, agent_id in ((tenant_a, agent_a), (tenant_b, agent_b)):
        async with tenant_session(tenant_id) as session:
            digests.append(
                (
                    await session.execute(
                        text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"),
                        {"aid": agent_id},
                    )
                ).scalar_one()
            )

    assert None not in digests
    assert len(set(digests)) == 2

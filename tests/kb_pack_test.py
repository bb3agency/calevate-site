"""The knowledge pack builder: what it projects, what its id depends on, and where it lands.

THREE PROPERTIES, AND THE MIDDLE ONE IS THE ONE THAT LOOKS LIKE CEREMONY AND IS NOT.

1. **The projection.** A pack entry carries the chunk's own words AND the English gloss,
   and the gloss lives one table over (`kb_documents.gloss`) — so a builder that forgot the
   join would produce a pack that is perfectly valid, perfectly searchable in English, and
   unable to answer the Tenglish questions Saaras actually returns (`kb/gloss.py` carries
   the 0.250 → 0.750 measurement). Nothing downstream would report that as a fault; the
   agent would just say `not_found` more often.

2. **Row order does not change the pack id.** `KnowledgePack.digest` sorts, for a reason
   its own docstring states: a SELECT without an ORDER BY may return rows in any order, and
   an id that moved with it would mint a new pack on a rebuild that changed nothing —
   invalidating every warm Pipecat container for free. A test that only ever sees one row
   order cannot tell a sorting digest from a lucky one, so this file shuffles.

3. **Tenancy (hard rule 1).** A pack is a frozen artefact fetched into a container that
   Pipecat Cloud reuses across sessions. A leak here is not one wrong screen: it is clinic
   A's price list answering clinic B's callers for the life of a warm container, with no
   shape to the wrong answer. Both directions are asserted, for
   `tests/kb_chunks_rls_test.py`'s reasons.

Marked `rls` so the tenancy half runs with `-k rls` alongside the rest of that suite.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import pack as kb_pack
from apps.api.kb import service as kb_service
from calevate_shared.knowledge_pack import (
    PACK_FORMAT_VERSION,
    KnowledgePack,
    PackEntry,
    pack_object_key,
)
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls


async def _tenant_with_published_knowledge(
    *facts: str, gloss: str | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose knowledge has reached `kb_chunks` through the REAL workflow.

    submit → approve → publish, never a hand-written INSERT: the property under test is
    that what a human actually published is what the pack carries, and a fabricated
    projection row would test the builder against a state no client can produce.

    `gloss` is written straight onto `kb_documents` because the sweep that writes it
    (`apps/workers/kb_gloss.py`) is a model call — out of scope here, and its OUTPUT is all
    this builder cares about.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        for n, fact in enumerate(facts):
            submitted = await kb_service.submit_source(
                session, tenant_id=tenant_id, agent_id=agent_id, name=f"Fees {n}", body=fact
            )
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
            await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
            )
        if gloss is not None:
            await session.execute(
                text(
                    "UPDATE kb_documents SET gloss = :g, gloss_state = 'ready' WHERE tenant_id = :t"
                ),
                {"g": gloss, "t": tenant_id},
            )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


# --- 1. The projection ---------------------------------------------------------------


async def test_a_pack_carries_the_chunk_text_and_the_gloss_from_the_other_table() -> None:
    """The join, asserted on the gloss rather than on a row count.

    A count passes against a builder that never looked at `kb_documents.gloss` — which is
    the only field here that cannot be recovered from `kb_chunks` and the one the whole
    cross-script retrieval argument rests on.
    """
    tenant_id, agent_id = await _tenant_with_published_knowledge(
        "సంప్రదింపుల రుసుము 500 రూపాయలు.", gloss="A consultation costs 500 rupees."
    )
    async with tenant_session(tenant_id) as session:
        built = await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    assert built.format_version == PACK_FORMAT_VERSION
    assert built.tenant_id == tenant_id
    assert built.agent_id == agent_id
    assert len(built.entries) == 1
    entry = built.entries[0]
    assert entry.text == "సంప్రదింపుల రుసుము 500 రూపాయలు."
    assert entry.gloss == "A consultation costs 500 rupees."
    assert entry.document_version == 1
    assert built.content_sha256 == KnowledgePack.digest(tenant_id, agent_id, built.entries)


async def test_an_unglossed_chunk_is_carried_with_no_gloss_rather_than_dropped() -> None:
    """`PackEntry.gloss` is nullable on purpose: an English corpus needs none and is still
    searchable by its own words. A builder that INNER JOINed the gloss would silently
    publish an empty pack for every English-speaking client."""
    tenant_id, agent_id = await _tenant_with_published_knowledge("The clinic opens at 9 am.")
    async with tenant_session(tenant_id) as session:
        built = await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    assert len(built.entries) == 1
    assert built.entries[0].gloss is None
    assert built.entries[0].text == "The clinic opens at 9 am."


async def test_a_pack_carries_no_vector_field_at_all() -> None:
    """Version 1 is text-only and that is a measurement, not an omission
    (`knowledge_pack.py:25-43`). `kb_chunks.embedding` is in the very table the builder
    reads, so the way this regresses is somebody adding one field to a SELECT."""
    tenant_id, agent_id = await _tenant_with_published_knowledge("The clinic opens at 9 am.")
    async with tenant_session(tenant_id) as session:
        built = await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    assert set(built.entries[0].model_dump()) == {
        "chunk_id",
        "document_id",
        "document_version",
        "text",
        "gloss",
    }


async def test_a_withdrawn_source_leaves_the_pack() -> None:
    """The `is_active` half of publishable. A corrected price list must not keep answering
    from a frozen artefact a container caches for a whole session."""
    tenant_id, agent_id = await _tenant_with_published_knowledge("A consultation costs 500.")
    async with tenant_session(tenant_id) as session:
        source_id = (
            await session.execute(
                text("SELECT id FROM kb_sources WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        await session.execute(
            text("UPDATE kb_sources SET is_active = false, status = 'archived' WHERE id = :s"),
            {"s": source_id},
        )
        built = await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    # The projection row is UNTOUCHED — `kb_chunks.is_active` is only converged on the next
    # publish for this agent (`kb/service.py::_DEACTIVATE_SQL`) — so this asserts the
    # builder reads the SOURCE's liveness rather than the projection's stale copy.
    async with tenant_session(tenant_id) as session:
        still_flagged = (
            await session.execute(
                text("SELECT is_active FROM kb_chunks WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert still_flagged is True, "fixture no longer exercises the stale-projection window"
    assert built.entries == ()


async def test_an_agent_with_nothing_published_gets_an_empty_pack_and_not_an_error() -> None:
    """The error ladder: a clinic that has uploaded nothing is a valid state. The worker
    must be able to answer `not_found` (a fact about the corpus) rather than
    `temporarily_unavailable` (a fact about us)."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(uuid.UUID(str(tenant_id))) as session:
        built = await kb_pack.build_pack(
            session, tenant_id=uuid.UUID(str(tenant_id)), agent_id=uuid.UUID(str(agent_id))
        )
    assert built.entries == ()
    assert built.content_sha256 == KnowledgePack.digest(
        uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), ()
    )


async def test_an_agent_that_does_not_exist_is_an_error() -> None:
    """...and the distinction from the test above is the whole point of the ladder: an
    unknown agent id must not read as zero chunks and mint a valid empty pack under a key
    nobody owns."""
    tenant_id, _ = await _tenant_with_published_knowledge("The clinic opens at 9 am.")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=uuid.uuid4())
    assert raised.value.status == 404


# --- 2. The id does not depend on row order -------------------------------------------


def _entry(chunk: uuid.UUID, doc: uuid.UUID, body: str) -> PackEntry:
    return PackEntry(chunk_id=chunk, document_id=doc, document_version=1, text=body, gloss=None)


def test_row_order_does_not_change_the_pack_id() -> None:
    """The digest sorts, so a SELECT returning the same rows in a different order mints the
    SAME id — which is what stops a rebuild that changed nothing from evicting every warm
    container. Asserted over several rotations, not one swap: a digest that happened to
    agree on a two-element reversal is not a sorting digest."""
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    entries = tuple(_entry(uuid.uuid4(), uuid.uuid4(), f"fact {n}") for n in range(6))
    baseline = KnowledgePack.digest(tenant_id, agent_id, entries)
    for offset in range(1, len(entries)):
        rotated = entries[offset:] + entries[:offset]
        assert rotated != entries
        assert KnowledgePack.digest(tenant_id, agent_id, rotated) == baseline
    assert KnowledgePack.digest(tenant_id, agent_id, tuple(reversed(entries))) == baseline


def test_the_pack_id_does_change_when_the_knowledge_does() -> None:
    """The control for the test above. A digest that ignored its entries entirely would
    pass every order assertion in this file."""
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    chunk, doc = uuid.uuid4(), uuid.uuid4()
    base = (_entry(chunk, doc, "A consultation costs 500 rupees."),)
    corrected = (_entry(chunk, doc, "A consultation costs 600 rupees."),)
    glossed = (
        PackEntry(
            chunk_id=chunk,
            document_id=doc,
            document_version=1,
            text="A consultation costs 500 rupees.",
            gloss="A consultation costs 500 rupees.",
        ),
    )
    digests = {
        KnowledgePack.digest(tenant_id, agent_id, base),
        KnowledgePack.digest(tenant_id, agent_id, corrected),
        KnowledgePack.digest(tenant_id, agent_id, glossed),
        KnowledgePack.digest(tenant_id, uuid.uuid4(), base),
        KnowledgePack.digest(uuid.uuid4(), agent_id, base),
    }
    assert len(digests) == 5


async def test_the_builder_returns_entries_in_the_order_the_digest_hashes() -> None:
    """One ordering, not two. The stored JSON lists the entries in the same order the id
    was computed over, so a reader comparing the object against its own key is comparing
    one decision rather than two that can drift."""
    tenant_id, agent_id = await _tenant_with_published_knowledge(
        "The clinic opens at 9 am.", "A consultation costs 500 rupees.", "We are shut on Sunday."
    )
    async with tenant_session(tenant_id) as session:
        built = await kb_pack.build_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    ids = [str(entry.chunk_id) for entry in built.entries]
    assert len(ids) == 3
    assert ids == sorted(ids)


# --- 3. Storage -----------------------------------------------------------------------


async def test_publishing_puts_the_pack_at_its_content_addressed_key(s3: FakeS3) -> None:
    tenant_id, agent_id = await _tenant_with_published_knowledge(
        "సంప్రదింపుల రుసుము 500 రూపాయలు.", gloss="A consultation costs 500 rupees."
    )
    async with tenant_session(tenant_id) as session:
        pack_id = await kb_pack.publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    key = pack_object_key(tenant_id, agent_id, pack_id)
    assert key in s3.objects
    stored = json.loads(s3.objects[key])
    assert stored["content_sha256"] == pack_id
    assert stored["tenant_id"] == str(tenant_id)
    assert [e["gloss"] for e in stored["entries"]] == ["A consultation costs 500 rupees."]
    # The id is the caller's record of WHICH knowledge went live, so it has to name these
    # bytes and not merely accompany them.
    assert KnowledgePack.model_validate(stored).content_sha256 == pack_id


async def test_republishing_unchanged_knowledge_rewrites_nothing(s3: FakeS3) -> None:
    """The object is write-once. `built_at` is outside the hash on purpose, so an
    overwrite would change the bytes at a key whose whole promise is that it cannot mean
    two things — and a container that cached it would be holding a version of the object
    that no longer exists."""
    tenant_id, agent_id = await _tenant_with_published_knowledge("The clinic opens at 9 am.")
    async with tenant_session(tenant_id) as session:
        first = await kb_pack.publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)
    original = dict(s3.objects)

    async with tenant_session(tenant_id) as session:
        again = await kb_pack.publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    assert again == first
    assert s3.objects == original, "a rebuild rewrote an immutable object"


async def test_adding_knowledge_mints_a_new_key_and_leaves_the_old_one_readable(
    s3: FakeS3,
) -> None:
    """A new pack is a NEW key rather than a version marker (`pack_object_key`), so a call
    still holding the old id keeps being able to fetch it."""
    tenant_id, agent_id = await _tenant_with_published_knowledge("The clinic opens at 9 am.")
    async with tenant_session(tenant_id) as session:
        first = await kb_pack.publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)

        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Sundays",
            body="We are shut on Sunday.",
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
        second = await kb_pack.publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)

    assert second != first
    assert pack_object_key(tenant_id, agent_id, first) in s3.objects
    assert pack_object_key(tenant_id, agent_id, second) in s3.objects


# --- 4. Hard rule 1 -------------------------------------------------------------------


async def test_a_pack_cannot_contain_a_neighbours_chunk() -> None:
    """RLS's direction. B's session builds B's pack and A's knowledge is not in it —
    asserted on the TEXT, because a count assertion passes against a leak that happens to
    return the right number of rows."""
    tenant_a, agent_a = await _tenant_with_published_knowledge("Sunrise clinic opens on Sunday.")
    tenant_b, agent_b = await _tenant_with_published_knowledge("Moonlight clinic opens Monday.")

    async with tenant_session(tenant_b) as session:
        built = await kb_pack.build_pack(session, tenant_id=tenant_b, agent_id=agent_b)

    texts = [entry.text for entry in built.entries]
    assert any("Moonlight" in value for value in texts)
    assert not any("Sunrise" in value for value in texts)
    assert (tenant_a, agent_a) != (tenant_b, agent_b)


async def test_naming_a_neighbours_ids_on_your_own_session_builds_nothing() -> None:
    """The predicate's direction — the mistake RLS cannot see as a mistake: a caller
    passing tenant A's id on a session opened for tenant B. Without the re-stated
    `tenant_id` the builder would return B's rows and STORE THEM UNDER A'S KEY, which is
    the worst outcome available here: A's worker would fetch a pack that validates, whose
    id names its own bytes, and whose contents belong to B.

    A's agent id is refused before the query is even reached — `assert_visible` runs on B's
    session and A's agent is not visible to it — which is the same answer one layer earlier.
    """
    tenant_a, agent_a = await _tenant_with_published_knowledge("Sunrise clinic opens on Sunday.")
    tenant_b, agent_b = await _tenant_with_published_knowledge("Moonlight clinic opens Monday.")

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as raised:
            await kb_pack.build_pack(session, tenant_id=tenant_a, agent_id=agent_a)
        assert raised.value.status == 404

        # And with B's OWN agent under A's tenant id — past the visibility check, into the
        # statement — the predicate is what has to refuse.
        crossed = await kb_pack.build_pack(session, tenant_id=tenant_a, agent_id=agent_b)
    assert crossed.entries == ()

    # The control: the same call on B's own id answers, so the emptiness above is the
    # predicate refusing rather than the query being broken.
    async with tenant_session(tenant_b) as session:
        own = await kb_pack.build_pack(session, tenant_id=tenant_b, agent_id=agent_b)
    assert own.entries

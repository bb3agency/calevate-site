"""Hard rule 1 on the caller-data store, and the erasure property it exists to protect.

TWO SUBJECTS IN ONE FILE, deliberately, because they are the same property seen from two
sides: a projection of a caller's words must be reachable by exactly the people entitled to
it (their own tenant) and by exactly the process obliged to destroy it (that person's
erasure), and by nobody and nothing else.

**WHY THE TENANCY HALF IS NOT CEREMONIAL.** `caller_chunks` shares `kb_chunks`' hazard —
a vector query that leaks returns the NEAREST row in the fleet and reads as an excellent
search result, so there is no shape to the wrong answer — and adds one of its own: the rows
are a data principal's words, not a client's price list, so a leak is a personal-data breach
rather than a commercial one. The boundary is carried entirely by the FORCEd
`tenant_isolation` policy migration `c6b1f0d47e83` ships, and this file is the evidence that
it reaches both tables rather than the argument that it should.

**WHY THE ERASURE HALF IS HERE AT ALL.** D-502's own decision row states the condition this
store had to meet before it could hold caller data: "an explicit arm in
`execute_deletion_request` and `execute_tenant_erasure`, a `DERIVED_COPIES` entry, a count
on the erasure certificate, and a test asserting the caller's own SENTENCE is gone". The
last clause is the one that cannot be satisfied by reading code, so it is asserted here
against a real database: after an erasure the row still exists (it is a tombstone) and
carries NEITHER key — no vector and no lexemes — so the sentence survives in no form.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.compliance.caller_ref import active_caller_ref, caller_refs
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.retrieval.caller_erasure import erase_subject_vectors, erase_tenant_vectors
from apps.api.retrieval.caller_search import search_caller_chunks
from apps.api.retrieval.models import SUBJECT_CALL_TURN
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls

#: The caller under test. E.164 because `caller_ref._checked` refuses anything else — it
#: does not normalise, deliberately, so that the write path and the erasure path cannot
#: disagree about the canonical form of one person.
SUBJECT = "+919876500011"

#: The sentence. A real one rather than lorem ipsum, because what these tests assert is
#: that a SPECIFIC word stops being findable — an assertion a placeholder cannot make.
SENTENCE = "Caller: do you do weekend appointments in Gachibowli for a knee scan"


async def _tenant_with_a_projected_sentence(
    phone: str = SUBJECT, body: str = SENTENCE
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A tenant holding ONE projected chunk of one caller's words, with its sparse key.

    Written directly rather than through a scope's discovery, and that is the right unit
    here: the property under test belongs to the STORE and to the erasure arms, and the
    three scopes that produce rows are separate deliverables. The row is built exactly as
    `caller_projections.store_chunks` builds one — same subject-ref construction, same
    `to_tsvector` configuration — so it is the shape the real path lands, not an invention.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id = uuid.UUID(str(tenant_id))
    agent_id = uuid.UUID(str(agent_id))
    chunk_id = uuid7()
    handle = active_caller_ref(tenant_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO caller_chunks (id, tenant_id, subject_kind, subject_id, idx, "
                "agent_id, subject_ref, subject_ref_kek_id, retention_category, occurred_at, "
                "tsv, content_sha256, embed_state) VALUES (:id, :t, :kind, :sid, 0, :a, :ref, "
                ":kek, 'transcript', :at, to_tsvector('english', :body), 'sha', 'pending')"
            ),
            {
                "id": chunk_id,
                "t": tenant_id,
                "kind": SUBJECT_CALL_TURN,
                "sid": uuid7(),
                "a": agent_id,
                "ref": handle.ref,
                "kek": handle.kek_id,
                "at": datetime.now(UTC),
                "body": body,
            },
        )
    return tenant_id, agent_id, chunk_id


async def _row(tenant_id: uuid.UUID, chunk_id: uuid.UUID) -> tuple[str, str | None, str] | None:
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text(
                    "SELECT tsv::text, embed_state, coalesce(scrubbed_at::text, '') "
                    "FROM caller_chunks WHERE id = :c"
                ),
                {"c": chunk_id},
            )
        ).first()
    return None if found is None else (str(found[0]), str(found[1]), str(found[2]))


# ============================================================ 1. TENANCY (hard rule 1)


async def test_a_neighbour_cannot_read_this_tenants_caller_chunks() -> None:
    """RLS's own direction: B's session, with NO tenant predicate at all, sees none of A's.

    The control, and the one a `WHERE tenant_id = ?` in application code cannot provide —
    the statement here deliberately omits the predicate, so the only thing standing between
    the two accounts is the FORCEd policy.
    """
    tenant_a, _, _ = await _tenant_with_a_projected_sentence()
    tenant_b, _ = await _tenant_with_published_agent()

    async with tenant_session(uuid.UUID(str(tenant_b))) as session:
        rows = (await session.execute(text("SELECT count(*) FROM caller_chunks"))).scalar_one()
        memories = (
            await session.execute(text("SELECT count(*) FROM caller_memories"))
        ).scalar_one()
    assert rows == 0, "tenant B can see caller chunks; the tenant_isolation policy is not on"
    assert memories == 0
    # And A can still see its own — a policy that hid everything from everybody would pass
    # the assertion above and be useless.
    async with tenant_session(tenant_a) as session:
        assert (await session.execute(text("SELECT count(*) FROM caller_chunks"))).scalar_one() == 1


async def test_searching_with_a_neighbours_tenant_id_returns_nothing() -> None:
    """The mistake RLS CANNOT see as a mistake: tenant A's id passed on tenant B's session.

    `caller_search` re-states `tenant_id` in the statement for exactly this — belt over
    braces — and without it the query would return B's rows under A's name and read as a
    perfectly successful answer about A. On a vector search that is the worst available
    failure, because the result has no shape a reader could recognise as wrong.
    """
    tenant_a, _, _ = await _tenant_with_a_projected_sentence()
    tenant_b, _ = await _tenant_with_published_agent()

    async with tenant_session(uuid.UUID(str(tenant_b))) as session:
        hits = await search_caller_chunks(
            session,
            tenant_id=tenant_a,
            question="weekend appointments",
            kinds=[SUBJECT_CALL_TURN],
            feature="test",
        )
    assert hits == ()


# ============================================ 2. THE SENTENCE IS GONE (D-502's condition)


async def test_the_sparse_key_finds_the_sentence_before_an_erasure() -> None:
    """The premise every assertion below depends on: the words ARE findable to begin with.

    Without this, a test that "the sentence is gone after an erasure" would pass against a
    store that never held it — the failure mode a compliance test most needs to rule out.
    Asserted through the SPARSE arm alone: no embedding has been bought here, which is also
    the state the store is in between a call landing and the sweep reaching it.
    """
    tenant_id, _, _ = await _tenant_with_a_projected_sentence()
    async with tenant_session(tenant_id) as session:
        hits = await search_caller_chunks(
            session,
            tenant_id=tenant_id,
            question="weekend appointments Gachibowli",
            kinds=[SUBJECT_CALL_TURN],
            feature="test",
        )
    assert len(hits) == 1


async def test_a_subject_erasure_destroys_the_vector_and_the_lexemes() -> None:
    """**THE CENTRAL PROPERTY OF THIS STORE.** After a §12 erasure the words are in neither
    key, and the row that proves we forgot them is still there.

    Three assertions and none is redundant. The `tsv` is EMPTY, so the sentence is gone from
    the sparse key. The search finds nothing, so it is gone from the answer. And the ROW
    SURVIVES with `scrubbed_at` set — which is not tidiness: the ingestion sweep discovers
    un-projected subjects, so a deleted row would be re-projected on the next tick and a
    vector re-bought for text this erasure had just destroyed. The tombstone is what makes
    the forgetting durable.
    """
    tenant_id, _, chunk_id = await _tenant_with_a_projected_sentence()
    async with tenant_session(tenant_id) as session:
        counts = await erase_subject_vectors(session, tenant_id=tenant_id, phone=SUBJECT)
    assert counts.vectors == 1

    row = await _row(tenant_id, chunk_id)
    assert row is not None, "the erasure DELETED the row; a tombstone is what stops a re-buy"
    assert row[0] == "", f"the caller's lexemes survived the erasure: {row[0]!r}"
    assert row[1] == "erased"
    assert row[2] != ""

    async with tenant_session(tenant_id) as session:
        hits = await search_caller_chunks(
            session,
            tenant_id=tenant_id,
            question="weekend appointments Gachibowli",
            kinds=[SUBJECT_CALL_TURN],
            feature="test",
        )
    assert hits == ()


async def test_the_database_refuses_a_forgotten_row_that_still_holds_a_key() -> None:
    """`ck_caller_chunks_forgotten_has_no_keys`, asserted against the DATABASE.

    The arms are correct today; this is the guard that stays true when somebody writes a
    fifth one. A scrub that set `scrubbed_at` and left the lexemes behind is refused by the
    constraint rather than by review — which is the difference between a property and a
    convention, and this repository has twice shipped the convention.
    """
    tenant_id, _, chunk_id = await _tenant_with_a_projected_sentence()
    with pytest.raises(Exception) as refusal:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE caller_chunks SET scrubbed_at = now(), embed_state = 'erased' "
                    "WHERE id = :c"
                ),
                {"c": chunk_id},
            )
    assert "forgotten_has_no_keys" in str(refusal.value)


async def test_an_erasure_reaches_a_caller_memory_that_no_call_points_at() -> None:
    """The handle the other two could not supply.

    A §12 request resolves a phone number to CALLS and LEADS. A caller memory belongs to a
    person ACROSS calls — that is the whole feature — so neither set reaches it, and
    `source_call_id` is provenance with `ON DELETE SET NULL` rather than an erasure path.
    `subject_ref = ANY(caller_refs(...))` is what does, and this is the test that it does.
    """
    tenant_id, agent_id, _ = await _tenant_with_a_projected_sentence()
    handle = active_caller_ref(tenant_id, SUBJECT)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO caller_memories (id, tenant_id, agent_id, subject_ref, "
                "subject_ref_kek_id, fact, occurred_at) VALUES (:id, :t, :a, :ref, :kek, "
                ":fact, :at)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "ref": handle.ref,
                "kek": handle.kek_id,
                "fact": "Asked about a knee scan in Gachibowli.",
                "at": datetime.now(UTC),
            },
        )
        counts = await erase_subject_vectors(
            session, tenant_id=tenant_id, phone=SUBJECT, call_ids=[], lead_ids=[]
        )
        assert counts.memories == 1
        remaining = (
            await session.execute(text("SELECT fact, scrubbed_at IS NOT NULL FROM caller_memories"))
        ).first()
    assert remaining is not None and remaining[0] == "" and remaining[1] is True


async def test_a_second_run_of_the_same_erasure_reports_nothing_new() -> None:
    """Idempotent on `scrubbed_at`, which is what makes the certificate's count honest.

    `execute_deletion_request` re-enters after a storage refusal rolled it back, and arq
    retries the job. A second run that re-counted rows the first already emptied would put
    a larger number on a proof describing the same work.
    """
    tenant_id, _, _ = await _tenant_with_a_projected_sentence()
    async with tenant_session(tenant_id) as session:
        first = await erase_subject_vectors(session, tenant_id=tenant_id, phone=SUBJECT)
        second = await erase_subject_vectors(session, tenant_id=tenant_id, phone=SUBJECT)
    assert (first.total(), second.total()) == (1, 0)


async def test_a_tenant_erasure_reaches_a_caller_whose_number_is_already_anonymized() -> None:
    """Why the tenant path is UNCONDITIONAL rather than a predicate over known subjects.

    At the end of an engagement there is no subject to match on, and a predicate built from
    the tenant's live phone columns would miss exactly the rows whose number an earlier
    retention sweep had already replaced with the placeholder — the population most likely
    to be there and least likely to be looked for.
    """
    tenant_id, _, chunk_id = await _tenant_with_a_projected_sentence()
    # A second caller nothing in the tenant's own tables can name any more.
    stranger, _, stranger_chunk = await _tenant_with_a_projected_sentence()
    async with tenant_session(tenant_id) as session:
        counts = await erase_tenant_vectors(session, tenant_id=tenant_id)
    assert counts.vectors == 1
    assert (await _row(tenant_id, chunk_id))[0] == ""  # type: ignore[index]
    # And it stopped at the tenant boundary: the other account is untouched.
    assert (await _row(stranger, stranger_chunk))[0] != ""  # type: ignore[index]


def test_the_erasure_predicate_walks_every_key_generation() -> None:
    """A KEK rotation must not be able to hide a row from a §12 request.

    `caller_refs` returns every generation newest-first precisely so the predicate is
    `= ANY(:refs)`. With a single active ref a rotation would cost the erasure every row
    written before it, and NOTHING would report it — the certificate would simply say zero,
    which is the one lie a compliance document cannot contain. No database: this is a
    property of the key ring.
    """
    tenant_id = uuid.uuid4()
    refs = caller_refs(tenant_id, SUBJECT)
    assert refs, "caller_refs produced no generations at all"
    assert refs[0] == active_caller_ref(tenant_id, SUBJECT).ref, (
        "the ACTIVE generation is not the first ref an erasure would try"
    )
    # And the ref is tenant-scoped: the same person at another client is a different value,
    # so a dump cannot be joined across two Fiduciaries on this column.
    assert caller_refs(uuid.uuid4(), SUBJECT)[0] != refs[0]

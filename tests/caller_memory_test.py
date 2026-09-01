"""A remembered caller is forgotten when they ask to be — and when the clock says so.

The feature is that a memory OUTLIVES the call it was learned on. Every one of these tests
exists because that sentence disables a protection the rest of this repository relies on:

* the call row's own erasure does not reach it (a DPDP erasure SCRUBS a call in place and
  keeps the row as billing evidence, so `source_call_id`'s cascade never fires);
* the transcript sweep does not reach it unless a `DERIVED_COPIES` entry puts it there;
* and `execute_deletion_request` resolves a phone number to CALLS and LEADS, neither of
  which a caller memory is keyed to.

So the erasure arms are written by hand and these tests are what prove they bite. The
central one — `test_an_erased_caller_is_forgotten` — asserts on the FACT, not on a phone
number: redaction removes identifiers from a sentence and does not remove the sentence,
which is the confusion `insights/service.scrub_quotes_for_calls` was written to undo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import caller_memory
from apps.api.compliance.caller_ref import active_caller_ref
from apps.api.db.session import tenant_session
from apps.api.retrieval.caller_erasure import (
    EXPIRE_MEMORIES_SQL,
    MEMORY_RETENTION_CATEGORY,
    erase_subject_vectors,
    erase_tenant_vectors,
)
from apps.api.retrieval.models import (
    CALLER_MEMORY_DEFAULT_ENABLED,
    SUBJECT_CALLER_MEMORY,
    SUBJECT_RETENTION,
)
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The caller under test, and the sentence about them. A DISTILLED fact, which is the only
#: shape this table may hold — and one that survives `redact()` untouched, so what these
#: tests watch disappear is the caller's own information rather than an identifier a
#: redactor would have taken anyway.
CALLER = "+919812345678"
NEIGHBOUR = "+919812345679"
FACT = "asked about IVF pricing"
OTHER_FACT = "wants a Saturday appointment"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Memory Clinic",
        slug=f"mem-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _enable(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """Switch the feature on for this agent. Every write test needs it, which is itself the
    assertion `test_the_switch_defaults_off` makes explicit."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :aid"),
            {"aid": agent_id},
        )
        await session.commit()


async def _remember(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    phone: str = CALLER,
    fact: str = FACT,
    occurred_at: datetime | None = None,
) -> int:
    async with tenant_session(tenant_id) as session:
        written = await caller_memory.remember(
            session,
            tenant_id,
            agent_id=agent_id,
            phone_e164=phone,
            occurred_at=occurred_at or datetime.now(UTC),
            source_call_id=None,
            facts=[fact],
        )
        await session.commit()
    return written


async def _facts_on_file(tenant_id: uuid.UUID) -> list[str]:
    """Every non-empty fact this tenant holds, read WITHOUT going through `recall`.

    Deliberately not `recall()`: that function is gated on the switch and bounded by a
    limit, so a test that used it could report "forgotten" about a row that is merely
    unreachable through one door. Erasure is a claim about the TABLE.
    """
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT fact FROM caller_memories WHERE fact <> ''"))
        ).scalars()
        return [str(row) for row in rows]


# ─────────────────────────────────────── the switch


async def test_the_switch_defaults_off() -> None:
    """A newly created agent does not remember anybody.

    The opposite default from `ai_disclosure_enabled` / `recording_notice_enabled`, and for
    the same principle pointed the other way: an omission must produce the SAFE posture,
    and here the safe posture is not remembering. Asserted against a real agent row rather
    than against the constant, because the column's server default is what actually decides
    it for an agent created by any path.
    """
    tenant_id, agent_id = await _tenant()
    assert CALLER_MEMORY_DEFAULT_ENABLED is False
    async with tenant_session(tenant_id) as session:
        assert await caller_memory.memory_enabled(session, agent_id=agent_id) is False


async def test_the_switch_gates_the_write_and_not_only_the_read() -> None:
    """THE FAILURE THIS FEATURE MOST NEEDS TO NOT HAVE.

    A toggle that stops recall while rows keep accumulating looks off to the client and is
    quietly building a durable profile of every caller — one a DPDP request will be
    answered about later. So the gate is on the door that CREATES data, and this test
    inspects the table rather than the recall, because a recall-side check would pass for
    exactly the broken implementation.
    """
    tenant_id, agent_id = await _tenant()
    assert await _remember(tenant_id, agent_id) == 0
    assert await _facts_on_file(tenant_id) == []


async def test_recall_stops_the_moment_the_switch_moves() -> None:
    """The arm that matters when a client switches OFF with rows already on file: recall
    stops immediately, and the rows go on the clock rather than waiting for a sweep nobody
    wrote."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert await caller_memory.recall(
            session, tenant_id, agent_id=agent_id, phone_e164=CALLER
        ) == (FACT,)
    # A SEPARATE SESSION for the flip and for the re-read: `tenant_session` owns the
    # transaction, so committing inside it and then issuing more statements is what the
    # context manager exists to refuse. It also models the real sequence better — the
    # client flips the switch in one request and the next call recalls in another.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = false WHERE id = :aid"),
            {"aid": agent_id},
        )
        await session.commit()
    async with tenant_session(tenant_id) as session:
        assert (
            await caller_memory.recall(session, tenant_id, agent_id=agent_id, phone_e164=CALLER)
            == ()
        )


# ─────────────────────────────────────── it remembers


async def test_a_repeat_caller_is_recognised_across_calls() -> None:
    """The feature itself, stated as a test: a fact learned on one call is returned on the
    next, with no call id joining them. That is only possible because the subject key is
    derived from the NUMBER — see `compliance/caller_ref.py`."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert FACT in await caller_memory.recall(
            session, tenant_id, agent_id=agent_id, phone_e164=CALLER
        )


async def test_one_caller_is_not_told_about_another() -> None:
    """The subject key separates two people in the same tenant. A collision here would read
    another caller's enquiry back to whoever rang next."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id, phone=CALLER, fact=FACT)
    await _remember(tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT)
    async with tenant_session(tenant_id) as session:
        assert await caller_memory.recall(
            session, tenant_id, agent_id=agent_id, phone_e164=CALLER
        ) == (FACT,)


async def test_a_fact_longer_than_the_cap_is_stored_short() -> None:
    """The bound between a distilled fact and a transcript excerpt, enforced BEFORE the
    database sees it so an over-long fact is a short row rather than a stack trace."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id, fact="x" * (caller_memory.MAX_FACT_CHARS + 50))
    stored = await _facts_on_file(tenant_id)
    assert len(stored) == 1
    assert len(stored[0]) <= caller_memory.MAX_FACT_CHARS


async def test_an_identifier_the_distiller_invented_does_not_reach_a_row() -> None:
    """The backstop, not the reason a fact is safe to keep. A model writing a phone-shaped
    number into its own summary would otherwise put it in a durable row."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id, fact=f"call back on {NEIGHBOUR}")
    assert NEIGHBOUR not in " ".join(await _facts_on_file(tenant_id))


# ─────────────────────────────────────── and it forgets


async def test_an_erased_caller_is_forgotten() -> None:
    """**THE TEST THIS WHOLE SCOPE EXISTS TO PASS.**

    A DPDP §12 request arrives with a phone number. It resolves to calls and leads —
    neither of which a caller memory is keyed to — and the call row is SCRUBBED IN PLACE
    rather than deleted, so nothing cascades. The only thing that reaches this row is the
    arm keyed on `caller_refs()`, derived from the number itself.

    Asserted on the FACT and not on a phone number: this table never held a number, and a
    test that watched an identifier disappear would pass against an implementation that
    left "asked about IVF pricing" on file for ever.
    """
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    assert FACT in await _facts_on_file(tenant_id)

    async with tenant_session(tenant_id) as session:
        counts = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()

    assert counts.memories == 1
    assert await _facts_on_file(tenant_id) == []
    async with tenant_session(tenant_id) as session:
        assert (
            await caller_memory.recall(session, tenant_id, agent_id=agent_id, phone_e164=CALLER)
            == ()
        )


async def test_an_erasure_forgets_one_person_and_not_the_others() -> None:
    """The other half of the same claim: an erasure is a §12 request from ONE data
    principal, and a client's other callers are not theirs to remove."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id, phone=CALLER, fact=FACT)
    await _remember(tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT)
    async with tenant_session(tenant_id) as session:
        await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()
    assert await _facts_on_file(tenant_id) == [OTHER_FACT]


async def test_the_erasure_leaves_a_tombstone_rather_than_deleting_the_row() -> None:
    """SCRUBBED, NOT DELETED, and the tombstone is load-bearing: the distiller discovers its
    own work, so a deleted row would be re-learned from a transcript the erasure had not
    yet reached — the row would come back, with a fresh clock, for ever."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT fact, scrubbed_at FROM caller_memories"))).first()
    assert row is not None
    assert row[0] == ""
    assert row[1] is not None


async def test_a_re_run_erasure_reports_nothing_the_first_one_already_did() -> None:
    """Idempotent, for `call_extractions`' reason: a re-run must not produce a second,
    larger count on a proof certificate."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        first = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        second = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()
    assert (first.memories, second.memories) == (1, 0)


async def test_a_tenant_erasure_forgets_every_caller() -> None:
    """Unconditional, for `execute_tenant_erasure`'s reason on `copilot_memories`: when the
    whole account goes there is no subject to match on, and a per-subject arm would leave
    behind exactly the rows nobody remembered to enumerate."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id, phone=CALLER, fact=FACT)
    await _remember(tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT)
    async with tenant_session(tenant_id) as session:
        assert (await erase_tenant_vectors(session, tenant_id=tenant_id)).memories == 2
        await session.commit()
    assert await _facts_on_file(tenant_id) == []


async def test_the_clock_forgets_facts_older_than_the_cutoff() -> None:
    """Dated from the SOURCE CALL and never from `created_at`, so a distillation that ran
    late does not buy the row extra life and a backfill does not reset it."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    now = datetime.now(UTC)
    await _remember(tenant_id, agent_id, fact=FACT, occurred_at=now - timedelta(days=400))
    await _remember(
        tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT, occurred_at=now - timedelta(days=5)
    )
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text(EXPIRE_MEMORIES_SQL), {"cutoff": now - timedelta(days=365), "batch": 100}
        )
        expired = result.rowcount
        await session.commit()
    assert expired == 1
    assert await _facts_on_file(tenant_id) == [OTHER_FACT]


async def test_the_scope_rides_the_transcript_clock_and_nothing_else() -> None:
    """One statement of which clock owns this scope, asserted across the two places that
    have to agree: the shared store's registry and the erasure module's own constant. They
    drift silently otherwise — the projection would expire on one clock and the source row
    on another, and the survivor would be a fact with no words left to justify it.

    `transcript` and not a category of its own: a memory is DISTILLED from what the caller
    said, so it rides the clock of the words it was distilled from — `calls.summary`'s
    argument, one table over — and it costs no new `retention_policies` row a client would
    have to be asked about.
    """
    assert SUBJECT_RETENTION[SUBJECT_CALLER_MEMORY] == MEMORY_RETENTION_CATEGORY
    assert MEMORY_RETENTION_CATEGORY == "transcript"


async def test_the_subject_key_matches_the_one_the_projection_is_filed_under() -> None:
    """`caller_memories.subject_ref` and `caller_chunks.subject_ref` must be the same value
    or one erasure predicate cannot reach both. Proved against the stored row rather than
    by reading the code that wrote it."""
    tenant_id, agent_id = await _tenant()
    await _enable(tenant_id, agent_id)
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT subject_ref, subject_ref_kek_id FROM caller_memories")
            )
        ).first()
    assert stored is not None
    expected = active_caller_ref(tenant_id, CALLER)
    assert (stored[0], stored[1]) == (expected.ref, expected.kek_id)


async def test_one_tenant_cannot_see_another_tenants_caller_memories() -> None:
    """Hard rule 1, in both directions the policy has to hold.

    The CONTROL: a neighbour's session reads zero of these rows, because
    `caller_memories` carries a FORCEd `tenant_isolation` policy.

    THE MISTAKE RLS CANNOT SEE: the same person's number under two tenants. The subject key
    takes `tenant_id` into its MAC input precisely so those two callers do not share a
    value — without that, a cross-tenant read (a dump, a backup, an ops query) would join
    two clients' caller memories into one profile, and the erasure predicate
    `subject_ref = ANY(:refs)` would match the neighbour's row too.
    """
    first, first_agent = await _tenant()
    second, second_agent = await _tenant()
    await _enable(first, first_agent)
    await _enable(second, second_agent)
    await _remember(first, first_agent, phone=CALLER, fact=FACT)
    await _remember(second, second_agent, phone=CALLER, fact=OTHER_FACT)

    assert await _facts_on_file(first) == [FACT]
    assert await _facts_on_file(second) == [OTHER_FACT]

    async with tenant_session(first) as session:
        assert active_caller_ref(first, CALLER).ref != active_caller_ref(second, CALLER).ref
        # The neighbour's refs match nothing here even with RLS set aside on the predicate.
        assert (await erase_subject_vectors(session, tenant_id=second, phone=CALLER)).memories == 0
        await session.commit()
    assert await _facts_on_file(first) == [FACT]

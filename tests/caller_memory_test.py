"""A remembered caller is forgotten when they ask to be — and when the clock says so.

Our own store of caller notes is retired (D-973): nothing writes `caller_memories` now, and
the rows written before that stay until the follow-up migration drops the table. Until then
every DPDP erasure and the retention clock must still reach them, because a memory OUTLIVES
the call it was learned on and so disables the protections the rest of this repository
relies on:

* the call row's own erasure does not reach it (a DPDP erasure SCRUBS a call in place and
  keeps the row as billing evidence, so `source_call_id`'s cascade never fires);
* the transcript sweep does not reach it unless a `DERIVED_COPIES` entry puts it there;
* and `execute_deletion_request` resolves a phone number to CALLS and LEADS, neither of
  which a caller memory is keyed to.

So the erasure arms are written by hand and these tests are what prove they bite. They
assert on the FACT, not on a phone number: redaction removes identifiers from a sentence and
does not remove the sentence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
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
    RETENTION_CALLER_MEMORY,
    SUBJECT_CALLER_MEMORY,
    SUBJECT_RETENTION,
)
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist, insert_caller_memory

pytestmark = pytest.mark.anyio

CALLER = "+919812345678"
NEIGHBOUR = "+919812345679"
FACT = "asked about IVF pricing"
OTHER_FACT = "wants a Saturday appointment"


async def _tenant(vertical: str = "real_estate") -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Memory Estates",
        slug=f"mem-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _remember(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    phone: str = CALLER,
    fact: str = FACT,
    occurred_at: datetime | None = None,
) -> None:
    await insert_caller_memory(tenant_id, agent_id, phone=phone, fact=fact, occurred_at=occurred_at)


async def _facts_on_file(tenant_id: uuid.UUID) -> list[str]:
    """Every non-empty fact this tenant holds. Erasure is a claim about the TABLE."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT fact FROM caller_memories WHERE fact <> ''"))
        ).scalars()
        return [str(row) for row in rows]


# ─────────────────────────────────────── the switch


async def test_the_switch_defaults_off() -> None:
    """A newly created agent does not remember anybody: an omission must produce the safe
    posture. Asserted against a real agent row, because the column's server default is what
    decides it for an agent created by any path."""
    tenant_id, agent_id = await _tenant()
    assert CALLER_MEMORY_DEFAULT_ENABLED is False
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT caller_memory_enabled FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert stored is False


def test_the_refusal_predicate_reads_a_positive_signal_and_not_an_absent_one() -> None:
    """`None` is NOT a refusal: `organizations.vertical_template` is nullable, so an absent
    value is the absence of a signal, and reading it as a refusal would silently disable the
    feature for accounts created by a path that never asked."""
    refuses = caller_memory.spdi_refuses_memory
    assert refuses("clinic", judged_health=None) is True
    assert refuses("real_estate", judged_health=None) is False
    assert refuses(None, judged_health=None) is False
    assert "clinic" in caller_memory.SPDI_REFUSED_VERTICALS


@pytest.mark.parametrize("vertical", [None, "retail", "local_services", "custom", "clinic"])
def test_a_business_judged_to_give_health_care_is_refused_whatever_its_type(
    vertical: str | None,
) -> None:
    """FAILS IF: a pharmacy, lab or physio filed under another type can switch memory on."""
    assert caller_memory.spdi_refuses_memory(vertical, judged_health=True) is True


def test_the_judgement_never_lifts_the_clinic_refusal() -> None:
    """FAILS IF: a clinic judged not to give health care (a default type, a wrong guess) has
    its refusal lifted: the judgement may only add refusals."""
    assert caller_memory.spdi_refuses_memory("clinic", judged_health=False) is True
    assert caller_memory.spdi_refuses_memory("retail", judged_health=False) is False


# ─────────────────────────────────────── and it forgets


async def test_an_erased_caller_is_forgotten() -> None:
    """A DPDP §12 request arrives with a phone number. It resolves to calls and leads —
    neither of which a caller memory is keyed to — so the only thing that reaches this row
    is the arm keyed on `caller_refs()`, derived from the number itself."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    assert FACT in await _facts_on_file(tenant_id)

    async with tenant_session(tenant_id) as session:
        counts = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()

    assert counts.memories == 1
    assert await _facts_on_file(tenant_id) == []


async def test_an_erasure_forgets_one_person_and_not_the_others() -> None:
    """An erasure is a §12 request from ONE data principal, and a client's other callers are
    not theirs to remove."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id, phone=CALLER, fact=FACT)
    await _remember(tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT)
    async with tenant_session(tenant_id) as session:
        await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()
    assert await _facts_on_file(tenant_id) == [OTHER_FACT]


async def test_the_erasure_leaves_a_tombstone_rather_than_deleting_the_row() -> None:
    """SCRUBBED, NOT DELETED: the certificate counts the scrubbed row, and the CHECK pairs an
    empty fact with `scrubbed_at`."""
    tenant_id, agent_id = await _tenant()
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
    """Idempotent: a re-run must not produce a second, larger count on a proof certificate."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        first = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        second = await erase_subject_vectors(session, tenant_id=tenant_id, phone=CALLER)
        await session.commit()
    assert (first.memories, second.memories) == (1, 0)


async def test_a_tenant_erasure_forgets_every_caller() -> None:
    """Unconditional: when the whole account goes there is no subject to match on."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id, phone=CALLER, fact=FACT)
    await _remember(tenant_id, agent_id, phone=NEIGHBOUR, fact=OTHER_FACT)
    async with tenant_session(tenant_id) as session:
        assert (await erase_tenant_vectors(session, tenant_id=tenant_id)).memories == 2
        await session.commit()
    assert await _facts_on_file(tenant_id) == []


async def test_the_clock_forgets_facts_older_than_the_cutoff() -> None:
    """Dated from the SOURCE CALL and never from `created_at`."""
    tenant_id, agent_id = await _tenant()
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


async def test_the_scope_rides_its_own_clock_and_nothing_else() -> None:
    """The shared store's registry and the erasure module's own constant name one clock, so
    the projection and the source row cannot expire on different ones (D-507(c))."""
    assert SUBJECT_RETENTION[SUBJECT_CALLER_MEMORY] == MEMORY_RETENTION_CATEGORY
    assert MEMORY_RETENTION_CATEGORY == RETENTION_CALLER_MEMORY
    assert MEMORY_RETENTION_CATEGORY != "transcript"


async def test_one_tenant_cannot_see_another_tenants_caller_memories() -> None:
    """Hard rule 1: a neighbour's session reads zero of these rows, and the subject key takes
    `tenant_id` into its MAC input so the same number under two tenants is two values."""
    first, first_agent = await _tenant()
    second, second_agent = await _tenant()
    await _remember(first, first_agent, phone=CALLER, fact=FACT)
    await _remember(second, second_agent, phone=CALLER, fact=OTHER_FACT)

    assert await _facts_on_file(first) == [FACT]
    assert await _facts_on_file(second) == [OTHER_FACT]

    async with tenant_session(first) as session:
        assert active_caller_ref(first, CALLER).ref != active_caller_ref(second, CALLER).ref
        assert (await erase_subject_vectors(session, tenant_id=second, phone=CALLER)).memories == 0
        await session.commit()
    assert await _facts_on_file(first) == [FACT]

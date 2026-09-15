"""Hard rule 1 on the external-index ledger: a neighbour's rows are unreachable.

WHY THIS FILE IS NOT CEREMONIAL, and the reason is unlike every other RLS test in this
suite. `kb_index_documents` holds no content — a digest, three ids and a timestamp — so the
usual argument ("a leak here exposes a client's words") does not apply. What it holds is
worse: **the list of documents a DELETE sent to the vendor is allowed to name.**
`retrieval/supermemory_index._withdraw_orphans` reads this table and hands the ids it finds
to box 3, whose local build is single-tenant with ONE API key (`docs/PIPECAT-MIGRATION.md`
§8.4) and which therefore enforces no tenancy of its own. A cross-tenant READ here becomes a
cross-tenant ERASURE there — one client's withdrawal silently destroying another client's
published knowledge in the store their dashboard search reads.

Both directions, for `kb_chunks_rls_test.py`'s reasons:

* **RLS's direction** — B's session, selecting with no tenant predicate at all, sees none of
  A's rows. The control.
* **The predicate's direction** — the mistake RLS cannot see as a mistake: tenant A's id
  passed on a session opened for B. Every statement in `supermemory_index.py` re-states
  `tenant_id` for exactly this, and the purge is the one where getting it wrong is
  irreversible in somebody else's store.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.retrieval.supermemory_index import purge_tenant_index
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

# The fixtures and the fake vendor are the ingest suite's, imported rather than re-declared:
# two spellings of "a configured box 3" is how the two files would come to disagree about
# what configured MEANS, and this file's subject is the policy, not the seam.
from tests.retrieval_supermemory_ingest_test import (
    FakeVendor,
    _configure,
    _publish,
    attested_price,
)

pytestmark = pytest.mark.rls


@pytest.fixture
def box3(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeVendor]:
    """A priced, configured, reachable box 3 — built from the ingest suite's own definitions
    rather than from a second copy of them, because what "configured" means must be one
    answer. It is a fixture here and there because a fixture imported into a second module
    and re-declared as a parameter is the redefinition ruff refuses."""
    vendor = FakeVendor()
    with attested_price():
        _configure(monkeypatch, vendor)
        yield vendor


async def _rows_visible_to(tenant_id: uuid.UUID) -> list[Any]:
    """Every ledger row this tenant's session can see, with NO tenant predicate at all.

    The missing `WHERE` is the point: the policy is the only thing scoping this read, which
    is what the control has to isolate.
    """
    async with tenant_session(tenant_id) as session:
        return list((await session.execute(text("SELECT tenant_id FROM kb_index_documents"))).all())


async def test_a_neighbour_cannot_see_which_documents_we_put_in_the_index(
    box3: FakeVendor,
) -> None:
    """The control. Two tenants publish; each session sees only its own ledger rows.

    Through the REAL publish path rather than a hand-written INSERT, for
    `kb_chunks_rls_test`'s reason: the property under test is that the path a client
    actually walks lands rows the policy protects.
    """
    mine, my_agent = await _tenant_with_published_agent()
    await _publish(mine, my_agent)
    theirs, their_agent = await _tenant_with_published_agent()
    await _publish(theirs, their_agent)

    my_rows = await _rows_visible_to(uuid.UUID(str(mine)))
    their_rows = await _rows_visible_to(uuid.UUID(str(theirs)))
    assert my_rows and their_rows
    assert {row[0] for row in my_rows} == {uuid.UUID(str(mine))}
    assert {row[0] for row in their_rows} == {uuid.UUID(str(theirs))}


async def test_a_purge_named_at_a_neighbour_on_our_session_removes_nothing(
    box3: FakeVendor,
) -> None:
    """THE MISTAKE RLS CANNOT SEE, on the one statement that reaches another store.

    A caller passing tenant A's id on a session opened for tenant B. The policy alone would
    happily run `DELETE ... WHERE tenant_id = A` on B's session and remove nothing — which is
    the correct outcome and is exactly what this pins, because the dangerous version is the
    statement with no `tenant_id` in it at all, which would take the session's whole
    visibility and report it as a successful erasure of somebody else's account.

    **AND IT PINS THE HALF THE DATABASE CANNOT PROTECT, RATHER THAN IMPLYING THERE ISN'T
    ONE.** The vendor call goes out regardless — box 3 has no idea what a session is — so
    the argument passed here IS the scope on that side, and the only thing keeping the two
    halves in step is that the single caller (`workers/retention.execute_tenant_erasure`)
    opens `tenant_session(tenant_id)` and passes that same id. That is asserted below as a
    fact about this code rather than left as a reassuring silence.
    """
    mine, my_agent = await _tenant_with_published_agent()
    await _publish(mine, my_agent)
    theirs, their_agent = await _tenant_with_published_agent()
    await _publish(theirs, their_agent)
    before = len(await _rows_visible_to(uuid.UUID(str(theirs))))
    assert before

    async with tenant_session(uuid.UUID(str(mine))) as session:
        removed = await purge_tenant_index(session, tenant_id=uuid.UUID(str(theirs)))
    assert removed == 0, "a purge crossed a tenant boundary"
    assert len(await _rows_visible_to(uuid.UUID(str(theirs)))) == before
    assert await _rows_visible_to(uuid.UUID(str(mine))), "the purge emptied the caller instead"
    # The vendor-side half: the tag sent is the ARGUMENT's, not the session's, which is what
    # makes "the caller opens the session for the tenant it names" a property of the code
    # rather than a convention — `execute_tenant_erasure` does exactly that.
    assert box3.deletes[-1]["containerTags"] == [f"tenant:{theirs}"]

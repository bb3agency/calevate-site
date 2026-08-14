"""Lead status through the repo's ONE discriminator (D-65, `db/transition.py`).

BACKEND-PATTERNS §5 has named "lead status" in the CAS list since it was written, and
nothing in the CRM was doing it: `PATCH /v1/leads/{id}` ran a blanket
`UPDATE leads SET status = :status`, which can report how many ROWS it touched and never
whether the value moved. Three consequences, all of them invisible on a green screen and
all of them pinned here:

1. **A second click wrote a second `status_change` row.** The lead timeline is the
   artefact that answers "who moved this to won, and when" — evidence. An event recording
   a button press rather than a change is evidence of the wrong thing, and it is worst
   exactly where it is most likely: the retry of a request whose response was lost, and
   the bulk action re-run over a set that partly overlaps the last one.
2. **A no-op edit bumped `updated_at`.** That column is the leads table's own sort key
   (`ORDER BY l.updated_at DESC`), so selecting "hot" on a lead that was already hot
   moved it to the top of the client's screen for nothing.
3. **A soft-deleted lead was reachable.** `WHERE ... AND deleted_at IS NULL` returning
   zero rows was reported as a 404, which is the right answer — but only because nothing
   else could have caused it. `transition_status`'s new `visible_where` makes that a
   statement rather than a coincidence, and the test below is what stops the predicate
   being applied to the CAS alone (which would answer 409 naming a status the caller is
   not entitled to know the row has).

The 409 answer is deliberately absent from this file. The lead machine is fully connected
by D-21 — any of the six states may follow any other, because a `lost` lead who calls back
becomes `hot` again — so `InvalidStatusTransitionError` is unreachable HERE while remaining
reachable through the same function for campaigns and knowledge sources. That asymmetry is
the point of a shared primitive: the caller supplies the state machine, not the answers.

CONCURRENCY: every test mints its own organization and asserts only through tenant-scoped
reads, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.db.transition import transition_status
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _the_lead(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _status_events(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> list[dict]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :l AND type = 'status_change' "
                    "ORDER BY created_at, id"
                ),
                {"l": lead_id},
            )
        ).all()
    return [row[0] or {} for row in rows]


async def _touched_at(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> object:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT updated_at FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).scalar()


# --- already-in-state is a SUCCESS ---------------------------------------------


async def test_setting_the_status_a_lead_already_has_succeeds_and_records_nothing() -> None:
    """The middle of D-65's three answers, on the surface a person clicks twice.

    200, because the caller's intent already holds (RFC 9110 §9.2.2 — the effect of N > 1
    identical requests is the effect of one). One timeline row, because only one change
    happened.
    """
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)

    async with _client() as http:
        first = await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "hot"}
        )
        second = await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "hot"}
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "hot"
    assert [e["status"] for e in await _status_events(tenant_id, lead_id)] == ["hot"], (
        "the second click wrote a timeline row claiming a change that did not happen"
    )


async def test_a_no_op_status_edit_does_not_reorder_the_clients_table() -> None:
    """`updated_at` is the leads list's ORDER BY, so bumping it on a no-op is a visible
    lie: the row jumps to the top of the screen because somebody re-picked the value it
    already had."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "won"}
        )
        after_the_move = await _touched_at(tenant_id, lead_id)
        await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "won"}
        )

    assert await _touched_at(tenant_id, lead_id) == after_the_move


async def test_every_pair_of_states_is_a_legal_move() -> None:
    """D-21's enum is fixed AND fully connected, and the `from_statuses` list this repo
    passes has to agree with that. A lead marked `lost` who calls back next month becomes
    `hot`; a client correcting a mis-click must not need support."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    walk = ["contacted", "interested", "hot", "won", "lost", "new"]

    async with _client() as http:
        for status in walk:
            response = await http.patch(
                f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": status}
            )
            assert response.status_code == 200, f"{status}: {response.text}"
            assert response.json()["status"] == status

    assert [e["status"] for e in await _status_events(tenant_id, lead_id)] == walk


# --- the row that is not there --------------------------------------------------


async def test_a_soft_deleted_lead_is_absent_rather_than_in_conflict() -> None:
    """`visible_where` reaches BOTH statements or this test fails with a 409.

    Applied to the CAS alone, the zero-row UPDATE would fall through to a SELECT that
    finds the deleted row and answers "a lead cannot move from new to hot" — a conflict
    that names a state the caller is not entitled to know the row has. 404 is the same
    answer RLS gives for a neighbour's id, deliberately.
    """
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET deleted_at = now() WHERE id = :l"), {"l": lead_id}
        )

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "hot"}
        )

    assert response.status_code == 404, response.text
    assert response.json()["kind"] == "not_found"

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM leads WHERE id = :l"), {"l": lead_id})
        ).scalar()
    assert status == "new", "a soft-deleted lead was resurrected by a status change"


async def test_a_neighbours_lead_is_absent_and_is_not_moved() -> None:
    """THE cross-tenant test for the transition. Under FORCEd RLS the CAS matches nothing
    and the discriminating SELECT reads nothing, so a foreign id 404s exactly like an id
    that never existed — and the neighbour's row keeps its status."""
    _tenant_id, slug, token = await _make_tenant()
    other_tenant, _other_slug, _other_token = await _make_tenant()
    stranger_lead = await _the_lead(other_tenant)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{stranger_lead}", headers=_headers(slug, token), json={"status": "won"}
        )

    assert response.status_code == 404, response.text
    async with tenant_session(other_tenant) as session:
        status = (
            await session.execute(
                text("SELECT status FROM leads WHERE id = :l"), {"l": stranger_lead}
            )
        ).scalar()
    assert status == "new"
    assert await _status_events(other_tenant, stranger_lead) == []


# --- the race -------------------------------------------------------------------


async def test_two_concurrent_moves_to_the_same_state_record_exactly_one() -> None:
    """The CAS runs FIRST and unconditionally, so exactly one caller reports the move.

    Two tabs, two staff, or a bulk action overlapping a row somebody is editing — all the
    same shape. Both requests answer 200 (the intent holds either way), and the artefact
    that must not double is the timeline: two `status_change` rows would tell an auditor
    the lead was moved to `hot` twice.
    """
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)

    async with _client() as http:
        responses = await asyncio.gather(
            *(
                http.patch(
                    f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"status": "hot"}
                )
                for _ in range(2)
            )
        )

    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert [e["status"] for e in await _status_events(tenant_id, lead_id)] == ["hot"]


# --- the primitive's own new parameter -------------------------------------------


async def test_visible_where_binds_reach_the_discriminating_select_too() -> None:
    """`visible_where` may carry its own bound parameters, and the SELECT needs them.

    `text()` compiles only the `:names` it finds, so one params dict can serve both
    statements — but only if the caller's binds are actually PASSED to the second one.
    Without that this raises a missing-parameter error instead of answering 404, which is
    the regression this asserts against. Exercised through the primitive directly: no
    route wants a parameterised visibility predicate yet, and the guard should not wait
    for the first one that does.
    """
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await transition_status(
                session,
                table="leads",
                entity="Lead",
                row_id=lead_id,
                to_status="hot",
                from_statuses=("new",),
                # A predicate no lead can satisfy, carrying a bind — so the CAS matches
                # nothing and the discriminator must also see the bind to conclude
                # "invisible", not blow up.
                visible_where="source = :only_source",
                params={"only_source": "campaign"},
            )
    assert refused.value.status == 404

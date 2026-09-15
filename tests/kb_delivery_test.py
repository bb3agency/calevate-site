"""Did the knowledge reach the phone, and does the screen say so honestly?

WHAT IS ACTUALLY AT RISK HERE, because "a read-only status endpoint" sounds like it has no
failure modes worth a file this size.

1. **The verdict must be the SWEEP's verdict.** `workers/kb_gloss.py` decides whether to
   rebuild an agent's pack by comparing the digest its corpus implies against the digest its
   row points at. This screen answers the same question to the client. If the two ever
   computed it differently, a client would be told "live" about an agent the sweep keeps
   rebuilding — or, worse, told to call support about an agent that is fine. They share
   `kb/pack.implied_digest` and `test_the_screen_and_the_sweep_agree_on_every_agent` drives
   both over the same rows rather than trusting that they call the same function.

2. **`no_knowledge` must beat `not_delivered` on day one.** An empty corpus has a perfectly
   real implied digest (the digest of no entries is a 64-hex string, never NULL), so an
   agent that has never published anything has a pointer of NULL that equals nothing. Get
   the order of the checks wrong and every account is told its agent is broken on the day it
   signs up. That is the single most damaging thing this screen could do, and it is one `if`
   away at all times.

3. **`preparing` and `not_delivered` must not collapse.** They look identical from the
   pointer — the agent is answering out of something older than what was published — and
   they are opposite instructions. One heals itself within the hour and the client should do
   nothing; the other is `refresh_published_pack`'s survived storage failure and will never
   heal on its own. The discriminator is whether any live chunk is still `gloss_state =
   'pending'`, i.e. whether the sweep still owes this agent work.

4. **Hard rule 6.** This is a knowledge screen and the neighbouring subject is a screen
   about what CALLERS ASKED (`apps/api/insights/`). The temptation to join one call row here
   is permanent, so `test_delivery_reads_no_caller_derived_source` is a source inventory in
   `tests/kb_aggregate_guard_test.py`'s idiom — a cheap net that catches the change nobody
   would think to describe as a leak.

5. **Hard rule 1.** A pack digest names the bytes of a client's own price list. A roster
   that leaked one row across a tenancy boundary would put a neighbour's agent, by name, on
   this client's screen.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so this
file runs beside the other suites on the shared Postgres. Marked `rls` so the tenancy half
runs with `-k rls`.
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import delivery as kb_delivery
from apps.api.kb import pack as kb_pack
from apps.api.kb import service as kb_service
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_staff_curation_test import _member
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls

DELIVERY = "/v1/kb/delivery"

#: Two facts from a tailoring business. Not a clinic's and not anybody's medical anything —
#: the console's own rule about example data, kept in the fixtures so a failure message
#: cannot print something a screenshot should not carry.
FACT_ONE = "A stitched blouse costs 450 rupees and takes three days."
FACT_TWO = "We are open 10am to 8pm every day except Sunday."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _org_slug(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )


async def _published(*facts: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent has published `facts` through the REAL workflow.

    submit → approve → publish, never a hand-written projection row: the property under test
    is what a client who actually used the product sees, and a fabricated `kb_chunks` row
    would leave the pointer unset and manufacture a state no account can reach.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        for n, fact in enumerate(facts):
            submitted = await kb_service.submit_source(
                session, tenant_id=tenant_id, agent_id=agent_id, name=f"Tailoring {n}", body=fact
            )
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
            await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
            )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def _gloss_one(tenant_id: uuid.UUID, *, limit: int) -> None:
    """Land an English gloss on `limit` of this tenant's documents, as the sweep would.

    Written straight onto `kb_documents` because the sweep that writes it is a model call
    (`apps/workers/kb_gloss.py`), and its OUTPUT — a gloss inside the digest, a state that is
    no longer `pending` — is the whole of what this screen reads. Crucially it does NOT
    rebuild the pack, which is exactly the window the two unhappy states live in.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kb_documents SET gloss = 'English rendering', gloss_state = 'ready' "
                "WHERE id IN (SELECT id FROM kb_documents WHERE tenant_id = :t "
                "ORDER BY id LIMIT :n)"
            ),
            {"t": tenant_id, "n": limit},
        )


async def _states(tenant_id: uuid.UUID) -> dict[uuid.UUID, kb_delivery.AgentDelivery]:
    async with tenant_session(tenant_id) as session:
        rows = await kb_delivery.tenant_delivery(session, tenant_id=tenant_id)
    return {row.agent_id: row for row in rows}


# --- 1. The verdict itself, as a pure function ---------------------------------------


def test_an_account_that_has_published_nothing_is_not_told_it_is_broken() -> None:
    """THE ORDERING TRAP, asserted first because it is the most damaging way to be wrong.

    A NULL pointer equals no digest, so without the `no_knowledge` check FIRST every agent
    on its first day would read `not_delivered` — "your knowledge did not reach your agent"
    — about an account that has not written anything down yet.
    """
    assert (
        kb_delivery._state(pointer=None, implied="a" * 64, live_chunks=0, awaiting=0)
        == "no_knowledge"
    )


def test_a_client_who_withdrew_everything_is_not_a_client_who_never_published() -> None:
    """Withdrawal publishes an EMPTY pack and points at it (`refresh_published_pack`), so the
    pointer is SET over a corpus of zero. That must stay distinguishable from day one — the
    call path depends on the same distinction to answer `not_found` rather than
    `temporarily_unavailable`."""
    empty = "b" * 64
    assert kb_delivery._state(pointer=empty, implied=empty, live_chunks=0, awaiting=0) == "live"


def test_a_pointer_that_matches_the_corpus_is_live() -> None:
    assert (
        kb_delivery._state(pointer="c" * 64, implied="c" * 64, live_chunks=3, awaiting=0) == "live"
    )


def test_a_stale_pointer_with_work_outstanding_is_preparing_not_broken() -> None:
    """The sweep still owes this agent a gloss, so a rebuild IS coming and the client should
    wait. Telling them to call support here would generate a ticket per publish."""
    assert (
        kb_delivery._state(pointer="d" * 64, implied="e" * 64, live_chunks=3, awaiting=1)
        == "preparing"
    )


def test_a_stale_pointer_with_nothing_outstanding_is_not_delivered() -> None:
    """Nothing is pending, so no sweep is coming and the gap is permanent until somebody
    acts. This is `refresh_published_pack`'s survived storage failure — the state the whole
    of this work exists to put on a screen."""
    assert (
        kb_delivery._state(pointer="d" * 64, implied="e" * 64, live_chunks=3, awaiting=0)
        == "not_delivered"
    )


# --- 2. The four states over real published knowledge ---------------------------------


async def test_a_fresh_agent_reports_no_knowledge(s3: FakeS3) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = (await _states(tenant_id))[agent_id]
    assert row.state == "no_knowledge"
    assert row.pack_id is None and row.live_chunks == 0
    assert row.last_reached_at is None, "a clock moved for a publish that never happened"


async def test_publishing_puts_the_knowledge_live_and_dates_it(s3: FakeS3) -> None:
    """The happy path, and the fact the screen exists to show: a publish moves the pointer
    AND stamps when it moved, so "I published an hour ago" has an answer on screen."""
    tenant_id, agent_id = await _published(FACT_ONE)
    row = (await _states(tenant_id))[agent_id]
    assert row.state == "live"
    assert row.pack_id is not None and re.fullmatch(r"[0-9a-f]{64}", row.pack_id)
    assert row.live_chunks == 1
    assert row.awaiting_translation == 1, "a freshly published chunk is not yet glossed"
    assert row.last_reached_at is not None


async def test_a_gloss_that_landed_without_a_rebuild_reads_preparing(s3: FakeS3) -> None:
    """MID-SWEEP. A gloss is inside the pack digest, so the moment one lands the corpus
    implies a different pack than the agent holds. Another chunk is still `pending`, so the
    sweep will be back — and the client is told to wait rather than to call anyone."""
    tenant_id, agent_id = await _published(FACT_ONE, FACT_TWO)
    await _gloss_one(tenant_id, limit=1)

    row = (await _states(tenant_id))[agent_id]
    assert row.state == "preparing"
    assert row.awaiting_translation == 1, "the un-glossed chunk is what makes a rebuild due"


async def test_a_settled_corpus_the_pointer_never_caught_up_with_reads_not_delivered(
    s3: FakeS3,
) -> None:
    """THE STATE THAT HAD NO SURFACE AT ALL. Every gloss has landed, so nothing is queued and
    no sweep is coming — and the pointer still names an older pack. That is precisely the
    shape a storage failure inside `refresh_published_pack` leaves behind: the publish
    survived, every other screen shows the new words, and the phone does not."""
    tenant_id, agent_id = await _published(FACT_ONE, FACT_TWO)
    await _gloss_one(tenant_id, limit=99)

    row = (await _states(tenant_id))[agent_id]
    assert row.state == "not_delivered"
    assert row.awaiting_translation == 0, "nothing is queued, so nothing is coming"
    assert row.pack_id is not None, "the agent still answers out of the last pack that exists"


async def test_republishing_unchanged_knowledge_does_not_move_the_clock(s3: FakeS3) -> None:
    """`last_reached_at` dates the pack the agent ANSWERS OUT OF, not the last press of
    publish. A client who republished identical text changed nothing about what their agent
    knows, and a timestamp that jumped would report a correction as landed."""
    tenant_id, agent_id = await _published(FACT_ONE)
    first = (await _states(tenant_id))[agent_id].last_reached_at

    async with tenant_session(tenant_id) as session:
        assert (
            await kb_pack.refresh_published_pack(session, tenant_id=tenant_id, agent_id=agent_id)
        ) is not None

    assert (await _states(tenant_id))[agent_id].last_reached_at == first


async def test_the_screen_and_the_sweep_agree_on_every_agent(s3: FakeS3) -> None:
    """THE PROPERTY THAT MATTERS MOST, driven over both instruments rather than assumed from
    a shared import: an agent the gloss sweep considers stale is exactly an agent this screen
    refuses to call `live`, and the reverse."""
    tenant_id, agent_id = await _published(FACT_ONE, FACT_TWO)
    await _gloss_one(tenant_id, limit=1)

    async with tenant_session(tenant_id) as session:
        stale = await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=25)
        rows = await kb_delivery.tenant_delivery(session, tenant_id=tenant_id)

    assert agent_id in stale, "the sweep must see this agent (the fixture made it stale)"
    assert {row.agent_id for row in rows if row.state != "live"} == set(stale)


async def test_an_archived_agent_is_off_the_roster(s3: FakeS3) -> None:
    """Retired agents are never dialled, so a retired agent whose pack never caught up is not
    something to put in front of a client as an action."""
    tenant_id, agent_id = await _published(FACT_ONE)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            # `archived_at` alongside the status: `ck_agents_archived_at_matches_status`
            # binds the pair, so a status set on its own is not a state the product has.
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": agent_id},
        )
    assert agent_id not in await _states(tenant_id)


# --- 3. The route: who may read it, and who may not -----------------------------------


async def test_the_route_answers_an_owner_with_the_servers_own_tally(s3: FakeS3) -> None:
    tenant_id, agent_id = await _published(FACT_ONE, FACT_TWO)
    await _gloss_one(tenant_id, limit=99)
    slug = await _org_slug(tenant_id)
    _user, token = await _member(tenant_id, "owner")

    async with _client() as client:
        response = await client.get(
            DELIVERY, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["agent_id"] for item in body["items"]] == [str(agent_id)]
    assert body["items"][0]["state"] == "not_delivered"
    # The server's own count, so a badge is never computed from a truncated page.
    assert body["not_delivered_count"] == 1


async def test_the_route_refuses_an_unauthenticated_reader(s3: FakeS3) -> None:
    tenant_id, _agent_id = await _published(FACT_ONE)
    slug = await _org_slug(tenant_id)
    async with _client() as client:
        response = await client.get(DELIVERY, headers={"X-Org-Slug": slug})
    assert response.status_code == 401


async def test_the_route_refuses_a_member_of_another_account(s3: FakeS3) -> None:
    """THE REFUSAL THAT ACTUALLY EXISTS HERE, and the reason the obvious one does not:
    `agents:read` is held by BOTH client roles (`core/rbac.ROLE_PERMISSIONS`), so there is no
    member of an account who may not read this — by design, since "my agent doesn't know
    that" is a question anyone on the team may be holding. What is refused is a reader
    presenting an account they are not a member of, which is where the tenancy boundary
    actually sits."""
    tenant_a, _agent_a = await _published(FACT_ONE)
    tenant_b, _agent_b = await _published(FACT_TWO)
    slug_a = await _org_slug(tenant_a)
    _user, token_b = await _member(tenant_b, "owner")

    async with _client() as client:
        response = await client.get(
            DELIVERY, headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_a}
        )
    assert response.status_code == 403


async def test_a_neighbour_sees_none_of_this_tenants_agents(s3: FakeS3) -> None:
    """HARD RULE 1, both directions. A pack digest names the bytes of a client's own price
    list and `agent_name` is the client's own word for their business, so one leaked row here
    would put a neighbour on this account's screen by name."""
    tenant_a, agent_a = await _published(FACT_ONE)
    tenant_b, agent_b = await _published(FACT_TWO)

    slug_b = await _org_slug(tenant_b)
    _user, token_b = await _member(tenant_b, "owner")
    async with _client() as client:
        response = await client.get(
            DELIVERY, headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b}
        )

    assert response.status_code == 200
    seen = {item["agent_id"] for item in response.json()["items"]}
    assert seen == {str(agent_b)}
    assert str(agent_a) not in seen

    # And the read itself, under tenant B's session, cannot be talked into tenant A's rows
    # by being handed tenant A's id — the `tenant_id` re-stated inside the statement on top
    # of RLS is what refuses that, and RLS alone would not see it as a mistake.
    async with tenant_session(tenant_b) as session:
        crossed = await kb_delivery.tenant_delivery(session, tenant_id=tenant_a)
    assert crossed == []


# --- 4. Hard rule 6, by source inventory ----------------------------------------------


def test_delivery_reads_no_caller_derived_source() -> None:
    """THE CHEAP NET (`tests/kb_aggregate_guard_test.py`'s idiom, and `kb_tiers_test`'s).

    The neighbouring feature is a screen about WHAT CALLERS ASKED, so somebody will one day
    be a two-line join away from putting a caller's question on this screen. Every name below
    is a caller-derived store; this module reaches for none of them, and a change that does
    fails here rather than in review.

    It also asserts the module logs nothing at all: the safest handling of a client's corpus
    digest and their agents' names is not to emit them, and a module with no logger cannot
    acquire a leaky log line by accident.
    """
    source = pathlib.Path(kb_delivery.__file__).read_text()
    # Comments and the docstring legitimately DISCUSS these subjects (that is how the
    # exclusion is recorded for the next reader), so the inventory is taken over code only.
    code = "\n".join(
        line for line in source.splitlines() if not re.match(r"\s*(#|\*|[A-Z ]+$)", line)
    )
    body = code.split('"""')[-1]

    for forbidden in (
        "transcript_turns",
        "text_redacted",
        "call_extractions",
        "calls",
        "summary",
        "from_e164",
        "to_e164",
        "knowledge_gaps",
        "question",
    ):
        assert forbidden not in body, f"delivery.py reached for {forbidden!r}"

    assert "get_logger" not in body and "logger" not in body, "delivery.py acquired a logger"


def test_the_wire_states_are_exactly_the_modules_states() -> None:
    """The route restates `DeliveryState` as a Literal so the generated TypeScript carries the
    union. Two spellings drift, so they are pinned: a fifth state added to one and not the
    other is a console rendering a word it has no sentence for."""
    from typing import get_args

    from apps.api.kb.routes import AgentDeliveryOut

    assert set(get_args(AgentDeliveryOut.model_fields["state"].annotation)) == set(
        get_args(kb_delivery.DeliveryState)
    )

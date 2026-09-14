"""The late gloss and the IN-CALL PACK: the artefact the phone actually answers out of.

THE DEFECT THIS FILE PINS, and it is the sibling of `tests/kb_gloss_projection_refresh_test.
py` one artefact over. `kb/pack.py` freezes an agent's live chunks — the client's text AND
its English gloss — into an immutable, content-addressed object at PUBLISH, and
`agents.knowledge_pack_sha256` points at it. The voice worker fetches that object once per
session and searches it in process; it never re-reads `kb_documents` while the phone is
ringing. The gloss is written afterwards, by `workers/kb_gloss.py`, on a half-hourly clock.
So for the order that actually happens — a reviewer approves and publishes in one sitting,
the sweep fires at :12 or :42 — the pack was sealed before the English half of every entry
existed, and only a later publish or withdrawal of some OTHER source on that agent ever
reopened it. A client happy with their opening hours never publishes them twice.

WHAT IT COSTS IS THE WHOLE OF IN-CALL RETRIEVAL, NOT ONE ARM OF IT. The pack carries no
vectors by construction (`knowledge_pack.py`: a query encoder does not fit a 100ms turn at
1-2 threads), so its index is English-only and the gloss IS the English text.
`tests/in_call_retrieval_recall_test.py` measured a Telugu-script question against that
index at **0.083 recall@1, 22 of 24 answered `not_found`** (n=24, 14 Sep 2026). An
ungloss'd pack is the difference between an agent that answers and one that says "I don't
have that" about facts its client published.

EVERY TEST HERE ASSERTS THE STORED OBJECT AND THE POINTER TOGETHER, never one alone. The
pointer is what a session loads by and the object is what it gets: a test satisfied by a
moved pointer alone would pass for a pointer naming bytes nobody stored, which is the one
state `refresh_published_pack`'s failure posture exists to make impossible.

Marked `rls` so the tenancy proof runs with `-k rls` alongside the rest of that suite.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.db.session import tenant_session
from apps.api.kb import pack as kb_pack
from apps.api.kb import service as kb_service
from apps.workers import kb_gloss
from calevate_shared.knowledge_pack import pack_object_key
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_gloss_test import _RecordingProvider, _run_sweep, _unique
from tests.kb_workflow_test import _tenant_with_published_agent, give_agent_a_script

pytestmark = pytest.mark.rls

#: Ordinary small-business facts in Telugu script — a tailor's shop — because Telugu is the
#: only script `kb.gloss.needs_gloss` sends to a provider, and because the pack is a
#: RETRIEVAL artefact: the fact has to be one a caller would really ring up and ask about.
TAILOR_TELUGU = "శ్రీ లక్ష్మి టైలర్స్ సోమవారం నుండి శనివారం వరకు ఉదయం 10 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది."
TAILOR_ENGLISH = "Sri Lakshmi Tailors is open Monday to Saturday from 10 am to 8 pm."

BLOUSE_TELUGU = "బ్లౌజ్ కుట్టడానికి మూడు రోజులు పడుతుంది, ధర 350 రూపాయలు."
BLOUSE_ENGLISH = "Stitching a blouse takes three days and costs 350 rupees."


async def _published_telugu_agent(*bodies: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent has published one LIVE Telugu source per body, none glossed yet.

    Through `submit_source` → `approve_source` → `publish_source` and never by inserting a
    row: the bug is a property of the ORDER those three run in relative to the sweep, so a
    fixture that stored a pack by hand could not express it. `_unique` is
    `tests/kb_gloss_test`'s and is here for its reason — the sweep is fleet-wide, so a claim
    about what was translated is a claim about the whole database.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        for n, body in enumerate(bodies):
            submitted = await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name=f"Shop {n}",
                body=_unique(body),
            )
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
            await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
            )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def _pointer(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    """What `agents.knowledge_pack_sha256` names — the id a new session would load by."""
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    return None if value is None else str(value)


def _glosses_in_pack(
    s3: FakeS3, tenant_id: uuid.UUID, agent_id: uuid.UUID, pack_id: str
) -> list[str | None]:
    """The gloss of every entry in the pack the pointer names, read back from the STORE.

    From the stored bytes rather than from a rebuild, because "the pack the worker would
    fetch carries English" is the property — and a rebuild would re-derive it from the
    database that worker never reads.
    """
    stored = json.loads(s3.objects[pack_object_key(tenant_id, agent_id, pack_id)])
    return [entry["gloss"] for entry in stored["entries"]]


# --- 1. The bug ----------------------------------------------------------------------


async def test_a_gloss_written_after_publish_reaches_a_rebuilt_pack(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """THE BUG. Publish first, gloss second — the normal order — and the pack must follow.

    The `before` half is what would have passed all along and is what makes the `after` half
    mean anything: the agent has a perfectly valid published pack, stored, pointed at, and
    carrying no English whatsoever. The pointer MOVES, because the pack is content-addressed
    and its entries changed; the superseded object stays readable, because a call that
    started before the sweep is holding that id.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)

    before = await _pointer(tenant_id, agent_id)
    assert before is not None, "the publish stored no pack at all"
    assert _glosses_in_pack(s3, tenant_id, agent_id, before) == [None]

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    after = await _pointer(tenant_id, agent_id)
    assert after is not None and after != before, "the pointer did not move onto a new pack"
    assert _glosses_in_pack(s3, tenant_id, agent_id, after) == [TAILOR_ENGLISH]
    assert pack_object_key(tenant_id, agent_id, before) in s3.objects


async def test_a_settled_corpus_costs_the_tick_no_pack_write_at_all(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """The idempotency that lets this run for every tenant on every tick, forever.

    A second tick over the same corpus must not move the pointer and must not put a single
    new object in the store. Asserted as the set of stored KEYS rather than as a count of
    calls: a rebuild that re-derived the identical pack would be invisible to a call counter,
    and avoiding it is the whole reason `agents_with_stale_packs` computes a DIFFERENCE.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)
    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    settled = await _pointer(tenant_id, agent_id)
    keys = set(s3.objects)

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=0 not_needed=0 rekeyed=0 repacked=0"
    )
    assert await _pointer(tenant_id, agent_id) == settled
    assert set(s3.objects) == keys, "a settled corpus was re-packed"


# --- 2. Batching ---------------------------------------------------------------------


async def test_many_glossed_documents_on_one_agent_rebuild_the_pack_once(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """BATCHING. Two sources, two glosses, ONE rebuild — and both English texts inside it.

    A pack is the WHOLE agent, so a per-document refresh would read that agent's entire
    corpus, hash it and round-trip the object store once per chunk to arrive at the same
    bytes. The count asserted here is therefore CALLS and not rows: the wrong shape produces
    identical data and a multiple of the work, which is the failure a data assertion cannot
    see. The store is asserted too, so "once" cannot be bought by rebuilding nothing.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU, BLOUSE_TELUGU)
    before = await _pointer(tenant_id, agent_id)

    refreshed: list[uuid.UUID] = []
    real = kb_gloss.refresh_published_pack

    async def _counting(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
        refreshed.append(agent_id)
        result: str | None = await real(session, tenant_id=tenant_id, agent_id=agent_id)
        return result

    monkeypatch.setattr(kb_gloss, "refresh_published_pack", _counting)

    both = f"{TAILOR_ENGLISH} {BLOUSE_ENGLISH}"
    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(both), only=tenant_id)
        == "translated=2 not_needed=0 rekeyed=2 repacked=1"
    )
    assert refreshed == [agent_id], "the pack was rebuilt once per document, not once per agent"

    after = await _pointer(tenant_id, agent_id)
    assert after is not None and after != before
    assert _glosses_in_pack(s3, tenant_id, agent_id, after) == [both, both]


# --- 3. Failure posture --------------------------------------------------------------


async def test_a_store_that_refuses_leaves_the_tick_running_and_the_pointer_honest(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """The posture, in all three halves at once, and the third is the one worth stating.

    (1) The sweep RETURNS: one tenant's object store must not end a fleet-wide tick.
    (2) The gloss and the re-key survive — both commit before this runs, so a storage
        failure can never make the next tick buy the same translation again.
    (3) THE POINTER DOES NOT MOVE. It keeps naming the pack that genuinely exists, so the
        agent answers stale-but-real rather than loading an id nothing was stored under.
        That is `refresh_published_pack`'s publish-path posture, reused rather than
        re-argued, which is why this asserts the alarm that helper fires rather than one of
        the sweep's own.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)
    before = await _pointer(tenant_id, agent_id)

    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(kb_pack, "alert", lambda stage, code, **kw: fired.append((stage, code)))
    s3.fail = True

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=1 not_needed=0 rekeyed=1 repacked=0"
    )
    assert fired == [("CORE_LOGIC", "knowledge_pack_publish_failed")]
    assert await _pointer(tenant_id, agent_id) == before

    # And the next tick retries from scratch, with nothing re-queued and nothing to replay:
    # the selection is a DIFFERENCE, so a pointer that did not move is still a pointer that
    # disagrees with its corpus. This is the half a worklist of glossed document ids would
    # have lost — it would have consumed those ids on the tick that failed.
    s3.fail = False
    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
    after = await _pointer(tenant_id, agent_id)
    assert after is not None and after != before
    assert _glosses_in_pack(s3, tenant_id, agent_id, after) == [TAILOR_ENGLISH]


# --- 4. Tenancy (hard rule 1) --------------------------------------------------------


async def test_the_scan_cannot_see_a_neighbours_agent(s3: FakeS3) -> None:
    """Hard rule 1, as a ZERO-ROWS proof rather than an assertion about a predicate.

    Tenant B's session is asked for the stale agents of tenant A, with A's id passed
    explicitly — the one mistake RLS cannot see as a mistake, and the reason
    `_LIVE_CHUNKS_FROM` re-states `tenant_id` on top of the policy. A leak here is not one
    wrong screen: this scan feeds `refresh_published_pack`, so B's sweep would freeze A's
    price list into a pack and point an agent at it, and a pack is what a warm Pipecat
    container answers calls out of for the life of a session.

    Both tenants are made genuinely stale first, and A's own session is the control
    afterwards: a scan that returned nothing because the fixture published nothing would
    pass the leak assertion for free.
    """
    tenant_a, agent_a = await _published_telugu_agent(TAILOR_TELUGU)
    tenant_b, agent_b = await _published_telugu_agent(BLOUSE_TELUGU)

    for tenant_id, english in ((tenant_a, TAILOR_ENGLISH), (tenant_b, BLOUSE_ENGLISH)):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE kb_documents SET gloss = :g, gloss_state = 'ready' WHERE tenant_id = :t"
                ),
                {"g": english, "t": tenant_id},
            )

    async with tenant_session(tenant_b) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_a, limit=25) == [], (
            "tenant B's session named tenant A's agent"
        )
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_b, limit=25) == [
            agent_b
        ]

    async with tenant_session(tenant_a) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_a, limit=25) == [
            agent_a
        ]


# --- 5. The publish lock -------------------------------------------------------------


async def _try_take_publish_lock(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    """Could a NEW transaction take this agent's publish lock right now? On its own connection.

    A separate session on purpose: `pg_try_advisory_xact_lock` is re-entrant within one
    transaction, so a probe that reused the sweep's session would answer True however
    firmly the lock was held and the test would pass for an unlocked refresh.
    """
    async with tenant_session(tenant_id) as probe:
        return bool(
            (
                await probe.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": kb_service.publish_lock_key(agent_id)},
                )
            ).scalar()
        )


async def test_the_refresh_holds_the_publish_lock_while_it_rebuilds(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """THE LOCK IS TAKEN, asserted at the only instant where it matters.

    Not "the helper was called" — that is a test of a line rather than of a property, and it
    would pass for a lock taken in the SCAN's transaction and released before any of this
    work, which is the plausible wrong fix. So the probe runs from a second connection at
    the moment `refresh_published_pack` is doing the read-freeze-point that a publish must
    not interleave with, and asserts the key is unavailable there. The control on the far
    side of the tick is what makes that mean "held for the transaction" rather than "leaked
    forever": an xact lock is released by COMMIT, so a free key afterwards is the postcondition.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)
    assert await _try_take_publish_lock(tenant_id, agent_id), "the fixture left the key held"

    held_during_refresh: list[bool] = []
    real = kb_gloss.refresh_published_pack

    async def _probing(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
        held_during_refresh.append(not await _try_take_publish_lock(tenant_id, agent_id))
        result: str | None = await real(session, tenant_id=tenant_id, agent_id=agent_id)
        return result

    monkeypatch.setattr(kb_gloss, "refresh_published_pack", _probing)

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=1 not_needed=0 rekeyed=1 repacked=1"
    )
    assert held_during_refresh == [True], "the pack was rebuilt without the agent's publish lock"
    assert await _try_take_publish_lock(tenant_id, agent_id), "the lock outlived its transaction"


async def test_a_publish_in_flight_makes_the_sweep_skip_that_agent(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """THE GAP THIS CLOSES, built as the interleaving rather than asserted as a call.

    A publish transaction takes `_lock_agent_publishes` before its first read and holds it to
    COMMIT, and it ENDS in `refresh_published_pack` — so it has already written the pointer
    for the corpus it is making live. Without a lock here the sweep's own read-freeze-point,
    which straddles an object-store round trip, commits AFTER that and wins: its UPDATE waits
    on the same `agents` row, is re-checked against the committed version under READ COMMITTED,
    finds the publisher's id genuinely `IS DISTINCT FROM` its own, and replaces it with a pack
    frozen from the corpus the publish replaced. The client's agent then recites a withdrawn
    price list, out of an artefact this sweep pointed at.

    The publisher is stood in for by its LOCK and not by a second concurrent publish: the lock
    is the entire protocol between the two — the publisher's own code path is exercised by
    `tests/kb_publish_atomicity_test.py` — and a real interleaved publish would be timing, not
    a proof. What is asserted is the three things a skip has to be: the tick RETURNS (no
    blocking, which is the other plausible fix and would put a client behind a timer), the
    POINTER is untouched, and NOTHING IS ALARMED, because being overtaken by a publish is a
    routine outcome and not a failure anybody should be woken for.

    The gloss itself still lands, which is the point of taking this lock at the REFRESH and
    not around the tick: the money was spent, the translation is committed, and only the
    derived rebuild defers.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)
    before = await _pointer(tenant_id, agent_id)

    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(kb_pack, "alert", lambda stage, code, **kw: fired.append((stage, code)))
    monkeypatch.setattr(kb_gloss, "alert", lambda stage, code, **kw: fired.append((stage, code)))

    async with tenant_session(tenant_id) as publisher:
        await publisher.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": kb_service.publish_lock_key(agent_id)},
        )
        assert (
            await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
            == "translated=1 not_needed=0 rekeyed=1 repacked=0"
        )

    assert await _pointer(tenant_id, agent_id) == before, "the sweep re-pointed a publishing agent"
    assert fired == [], "an ordinary lock contention was alarmed"


async def test_an_agent_skipped_for_the_lock_is_repacked_on_the_next_tick(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """A SKIP DEFERS AND NEVER DROPS, which is what makes the try-lock free to use.

    Nothing is re-queued and nothing is replayed: `agents_with_stale_packs` computes a
    DIFFERENCE, so an agent passed over consumed no marker and its pointer still disagrees
    with its corpus. This is the half that a worklist of glossed document ids could not
    give — it would have consumed those ids on the tick that was locked out.

    Second tick translates NOTHING (`translated=0`), which is the load-bearing detail: the
    deferral costs the derived rebuild and never a second model call for text we already
    paid to translate.
    """
    tenant_id, agent_id = await _published_telugu_agent(TAILOR_TELUGU)
    before = await _pointer(tenant_id, agent_id)

    async with tenant_session(tenant_id) as publisher:
        await publisher.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": kb_service.publish_lock_key(agent_id)},
        )
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
    assert await _pointer(tenant_id, agent_id) == before

    # The publish has committed; its lock went with it. The very next tick picks the agent up.
    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=0 not_needed=0 rekeyed=0 repacked=1"
    )
    after = await _pointer(tenant_id, agent_id)
    assert after is not None and after != before
    assert _glosses_in_pack(s3, tenant_id, agent_id, after) == [TAILOR_ENGLISH]


async def _second_agent_with_published_source(tenant_id: uuid.UUID, body: str) -> uuid.UUID:
    """A SECOND agent on an existing tenant, with one live Telugu source of its own.

    Through `agents.lifecycle.create_agent` and never a hand-written INSERT, for that
    function's own stated reason: it is the one insert into `agents` on any path that
    produces an agent a client uses, and four of the columns it fills are hard rule 5.
    The engine ref, its route and the applied script are then supplied the way
    `_tenant_with_published_agent` supplies them: `publish_source` reads
    `agents.engine_agent_ref` to attach to, and it ends in a T0 recompile that re-publishes
    a LIVE agent — which `agents/service._assert_has_a_script` refuses for an agent nobody
    has written a greeting for. A draft agent flipped to `live` with no `prompt_versions`
    row is a state production cannot reach, which is `give_agent_a_script`'s whole argument.
    """
    async with tenant_session(tenant_id) as session:
        agent_id = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Second counter",
            direction="inbound",
            language_primary="te-IN",
        )
        ref = f"fakeagent_kb_{uuid.uuid4().hex[:8]}"
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) "
                "VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    await give_agent_a_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Shop B", body=_unique(body)
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return agent_id


async def test_one_agents_publish_does_not_hold_up_its_neighbour(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """THE KEY IS THE AGENT, so a skip is one agent wide and not one tenant wide.

    The `continue` sits inside the per-agent loop rather than around it, and this is the
    assertion that can tell those apart: one tenant, two agents, one of them mid-publish. A
    lock taken per TENANT — or a skip that broke out of the loop — would strand the other
    agent's pack for thirty minutes because a neighbour was being edited, which is the shape
    `MAX_PACK_AGENTS_PER_TENANT`'s own comment refuses on starvation grounds.
    """
    tenant_id, busy_agent = await _published_telugu_agent(TAILOR_TELUGU)
    quiet_agent = await _second_agent_with_published_source(tenant_id, BLOUSE_TELUGU)

    busy_before = await _pointer(tenant_id, busy_agent)
    quiet_before = await _pointer(tenant_id, quiet_agent)

    both = f"{TAILOR_ENGLISH} {BLOUSE_ENGLISH}"
    async with tenant_session(tenant_id) as publisher:
        await publisher.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": kb_service.publish_lock_key(busy_agent)},
        )
        assert (
            await _run_sweep(monkeypatch, _RecordingProvider(both), only=tenant_id)
            == "translated=2 not_needed=0 rekeyed=2 repacked=1"
        )

    assert await _pointer(tenant_id, busy_agent) == busy_before, "the publishing agent was repacked"
    quiet_after = await _pointer(tenant_id, quiet_agent)
    assert quiet_after is not None and quiet_after != quiet_before, (
        "a neighbour's publish stranded this agent's pack"
    )
    assert _glosses_in_pack(s3, tenant_id, quiet_agent, quiet_after) == [both]

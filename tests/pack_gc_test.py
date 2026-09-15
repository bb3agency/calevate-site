"""The reference-aware knowledge-pack collector (D-611), and the one thing it may not do.

WHAT THIS FILE IS ACTUALLY DEFENDING. `knowledge-packs/` holds immutable, content-addressed
objects: every publish writes a NEW one and nothing ever rewrites the old. The bucket rule
over that prefix is a growth CEILING at 2555 days and cannot be anything else, because S3
expiry runs from an object's CREATION while a pack is rebuilt only when a client's
knowledge changes — so the oldest object under the prefix is the live pack of the client
whose price list has been correct longest, and the FIRST thing any short expiry would
delete. `workers/pack_gc.py` is the mechanism that can tell those apart, and the whole of
its value is one predicate: does `agents.knowledge_pack_sha256` name this object.

So the tests here come in two halves and the second half is the important one. The first
proves a published pack is reachable end to end — pointer and bytes together, never one
alone. The second proves every way the collector refuses, because each refusal is what
stands between a live agent and an afternoon of `temporarily_unavailable`:

* a STALE BUT REFERENCED pack is never collected, however old (`test_a_stale_but_...`);
* a superseded pack inside the grace is never collected, because the object is written
  BEFORE the pointer commits and a collector racing a publish would take the pack of the
  client who just pressed the button;
* an object whose age the store did not report is never collected;
* an object under our prefix that this platform did not write is never collected;
* a pack whose tenant this tick could not enumerate is never collected;
* and NOTHING is collected at all when the reference read is incomplete.

Marked `rls` for `tests/kb_gloss_pack_refresh_test.py`'s reason: the fleet-wide reference
walk is a tenancy claim — it must see every tenant's pointers and no tenant may see
another's — so it belongs in the suite that runs under `-k rls`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import tenant_session
from apps.workers import pack_gc
from apps.workers.storage import StoredObject
from calevate_shared.knowledge_pack import pack_object_key, parse_pack_object_key
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_gloss_pack_refresh_test import _pointer, _published_telugu_agent

pytestmark = pytest.mark.rls

NOW = datetime(2026, 9, 15, 5, 7, tzinfo=UTC)
ANCIENT = NOW - timedelta(days=900)
YESTERDAY = NOW - timedelta(days=1)
PAST_GRACE = NOW - timedelta(seconds=pack_gc.PACK_GRACE_S + 60)


def _obj(tenant: uuid.UUID, agent: uuid.UUID, digest: str, when: datetime | None) -> StoredObject:
    return StoredObject(key=pack_object_key(tenant, agent, digest), last_modified=when)


def _digest(seed: str) -> str:
    """A 64-hex digest. Shaped like the real thing because the parser insists on it."""
    return (seed * 64)[:64]


# --- 1. The key is one author's answer, forwards and backwards ----------------------


def test_the_key_parser_is_the_inverse_of_the_builder_and_refuses_everything_else() -> None:
    """The collector deletes on the strength of what a key MEANS, so build and parse have
    to be one function's two directions. A second spelling that agreed about ordinary keys
    and disagreed about an edge would either strand objects for ever or — the expensive
    direction — attribute one agent's pack to another agent's reference set.
    """
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    digest = _digest("a")
    assert parse_pack_object_key(pack_object_key(tenant, agent, digest)) == (tenant, agent, digest)

    for hostile in (
        f"knowledge-packs/{tenant}/{agent}/{digest}.json.bak",
        f"knowledge-packs/{tenant}/{agent}/{digest.upper()}.json",
        f"knowledge-packs/{tenant}/{agent}/{digest[:63]}.json",
        f"knowledge-packs/{tenant}/{agent}/nested/{digest}.json",
        f"knowledge-packs/{{{tenant}}}/{agent}/{digest}.json",
        f"knowledge-packs/{tenant}/{agent}/{digest}",
        f"kb-uploads/{tenant}/{agent}/{digest}.json",
        "knowledge-packs/",
    ):
        assert parse_pack_object_key(hostile) is None, f"{hostile!r} parsed as one of our packs"


# --- 2. Referenced against unreferenced, which is the whole mechanism ----------------


def test_a_stale_but_referenced_pack_is_never_collected() -> None:
    """THE CASE THE BUCKET RULE GETS WRONG, AND THE REASON THIS SWEEP EXISTS.

    An agent whose knowledge has not changed in nine hundred days is not a neglected agent
    — it is a client whose opening hours and price list have been right since the day they
    published them. Their pack is the OLDEST object under the prefix and their agent reads
    it on every single call. Age is not the predicate; reference is.
    """
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    digest = _digest("b")
    plan = pack_gc.plan_pack_collection(
        [_obj(tenant, agent, digest, ANCIENT)],
        references={(tenant, agent, digest)},
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == (), "the live pack of the best-behaved client on the platform"
    assert plan.referenced == 1


def test_an_unreferenced_pack_past_the_grace_is_collected() -> None:
    """The other half, without which this module reclaims nothing and is theatre."""
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    live, superseded = _digest("c"), _digest("d")
    plan = pack_gc.plan_pack_collection(
        [_obj(tenant, agent, live, YESTERDAY), _obj(tenant, agent, superseded, PAST_GRACE)],
        references={(tenant, agent, live)},
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == (pack_object_key(tenant, agent, superseded),)
    assert plan.referenced == 1


def test_a_freshly_superseded_pack_inside_the_grace_is_left_alone() -> None:
    """`refresh_published_pack` stores the OBJECT before the POINTER commits, deliberately.

    So for the width of one publish transaction a pack is legitimately unreferenced and
    about to be referenced, and a collector without a grace would delete the pack of the
    client who just pressed publish. `PACK_GRACE_S` is what makes that impossible rather
    than unlikely.
    """
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    plan = pack_gc.plan_pack_collection(
        [_obj(tenant, agent, _digest("e"), NOW - timedelta(seconds=pack_gc.PACK_GRACE_S - 60))],
        references=set(),
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == ()
    assert plan.too_new == 1


def test_one_agents_pointer_does_not_protect_another_agents_object() -> None:
    """The reference set is `(tenant, agent, digest)` and not a bare set of digests.

    Two agents in one tenant publishing the same corpus compute the SAME digest under
    DIFFERENT keys. On a digest-only comparison, one agent's live pointer would shield the
    other's object — and after a withdrawal the surviving object would be whichever one
    nobody was pointing at, which is exactly backwards.
    """
    tenant = uuid.uuid4()
    kept, orphaned = uuid.uuid4(), uuid.uuid4()
    shared = _digest("f")
    plan = pack_gc.plan_pack_collection(
        [_obj(tenant, kept, shared, PAST_GRACE), _obj(tenant, orphaned, shared, PAST_GRACE)],
        references={(tenant, kept, shared)},
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == (pack_object_key(tenant, orphaned, shared),)


# --- 3. Every uncertainty resolves to "keep" ----------------------------------------


def test_an_object_the_store_gave_no_age_for_is_never_collected() -> None:
    """Age unknown is not age zero. The grace is the only thing standing between this
    sweep and a publish still in flight, and an object we cannot age is one we cannot
    prove the grace against.
    """
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    plan = pack_gc.plan_pack_collection(
        [_obj(tenant, agent, _digest("1"), None)],
        references=set(),
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == ()
    assert plan.too_new == 1


def test_a_key_this_platform_did_not_write_is_reported_and_left() -> None:
    tenant = uuid.uuid4()
    stranger = f"knowledge-packs/{tenant}/not-a-uuid/whatever.json"
    plan = pack_gc.plan_pack_collection(
        [StoredObject(key=stranger, last_modified=ANCIENT)],
        references=set(),
        known_tenants={tenant},
        now=NOW,
    )
    assert plan.collect == ()
    assert plan.unattributable == (stranger,)


def test_a_pack_whose_tenant_was_not_enumerated_is_reported_and_left() -> None:
    """DELETING ON ABSENCE IS THE MOST EXPENSIVE MISTAKE AVAILABLE HERE.

    If a truncated or failed organization directory read meant "these tenants do not
    exist", one bad read would take the live pack of every tenant it missed, silently, with
    every screen still reporting their knowledge as published. So absence is a FINDING.
    The price is that a CLOSED tenant's packs are not reclaimed by this sweep — recorded in
    `infra/README.md` §3 as residue the bucket ceiling bounds, not as something forgotten.
    """
    gone, alive = uuid.uuid4(), uuid.uuid4()
    agent = uuid.uuid4()
    key = pack_object_key(gone, agent, _digest("2"))
    plan = pack_gc.plan_pack_collection(
        [StoredObject(key=key, last_modified=ANCIENT)],
        references=set(),
        known_tenants={alive},
        now=NOW,
    )
    assert plan.collect == ()
    assert plan.unattributable == (key,)


def test_the_per_tick_ceiling_bounds_how_wrong_one_tick_can_be() -> None:
    """Not a page size — a blast radius. A backlog drains over days, which is the correct
    speed for a job whose mistakes are irreversible, and the order is deterministic so
    consecutive ticks finish the same objects instead of sampling a new slice each day.
    """
    tenant = uuid.uuid4()
    over = pack_gc.MAX_DELETIONS_PER_TICK + 5
    objects = [_obj(tenant, uuid.uuid4(), f"{n:064x}", PAST_GRACE) for n in range(over)]
    plan = pack_gc.plan_pack_collection(objects, references=set(), known_tenants={tenant}, now=NOW)
    assert len(plan.collect) == over
    assert plan.deferred == 5
    assert list(plan.collect) == sorted(plan.collect)


# --- 4. End to end: the pointer and the bytes, together -----------------------------


async def test_a_published_pack_is_reachable_end_to_end_and_survives_the_sweep(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish for real, then run the collector for real, and assert BOTH halves.

    The pointer alone would pass for a pointer naming bytes nobody stored — the one state
    `refresh_published_pack`'s failure posture exists to make impossible — and the bytes
    alone would pass for an object no session could ever find. A sweep that ran between a
    publish and the next call must leave both exactly where they were.
    """
    tenant_id, agent_id = await _published_telugu_agent("మా దుకాణం ఉదయం 10 గంటలకు తెరుస్తుంది.")
    pointer = await _pointer(tenant_id, agent_id)
    assert pointer is not None, "publishing a source recorded no pack"
    key = pack_object_key(tenant_id, agent_id, pointer)
    assert key in s3.objects, "the pointer names bytes nobody stored"

    await pack_gc.sweep_knowledge_packs({"job_try": 1})

    assert key in s3.objects, "the collector deleted the pack a live agent answers out of"
    assert await _pointer(tenant_id, agent_id) == pointer


async def test_the_sweep_reclaims_a_superseded_pack_and_only_that_one(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One agent, two packs in the bucket, one pointer. The superseded one is past the
    grace and goes; the live one is younger and stays for BOTH reasons, which is why the
    assertion below names the live key rather than counting objects.
    """
    tenant_id, agent_id = await _published_telugu_agent("బ్లౌజ్ కుట్టడానికి మూడు రోజులు.")
    pointer = await _pointer(tenant_id, agent_id)
    assert pointer is not None
    live_key = pack_object_key(tenant_id, agent_id, pointer)

    superseded = pack_object_key(tenant_id, agent_id, _digest("3"))
    s3.objects[superseded] = b"{}"
    s3.written_at[superseded] = datetime.now(UTC) - timedelta(seconds=pack_gc.PACK_GRACE_S + 60)

    await pack_gc.sweep_knowledge_packs({"job_try": 1})

    assert superseded not in s3.objects, "the superseded pack was not reclaimed"
    assert live_key in s3.objects


async def test_nothing_is_deleted_when_the_reference_read_is_incomplete(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reference set quietly missing one client's agents is a licence to delete that
    client's live packs, so the walk is all-or-nothing and the sweep aborts before its
    FIRST delete. The retry ladder turns that into a deferral; swallowing it would turn it
    into a loss.
    """
    tenant_id, agent_id = await _published_telugu_agent("ధర 350 రూపాయలు.")
    pointer = await _pointer(tenant_id, agent_id)
    assert pointer is not None
    stale = pack_object_key(tenant_id, agent_id, _digest("4"))
    s3.objects[stale] = b"{}"
    s3.written_at[stale] = datetime.now(UTC) - timedelta(seconds=pack_gc.PACK_GRACE_S + 60)

    async def _broken() -> tuple[set[tuple[uuid.UUID, uuid.UUID, str]], set[uuid.UUID]]:
        raise RuntimeError("one tenant session could not be opened")

    monkeypatch.setattr(pack_gc, "fleet_pack_references", _broken)
    with pytest.raises(RuntimeError):
        await pack_gc.sweep_knowledge_packs({"job_try": 99})

    assert stale in s3.objects, "a delete ran against a reference set we never finished reading"
    assert pack_object_key(tenant_id, agent_id, pointer) in s3.objects


async def test_the_reference_walk_sees_every_tenants_pointer_and_not_one_tenants_only(
    s3: FakeS3,
) -> None:
    """The walk is one `tenant_session` per organization precisely because `agents` has no
    cross-tenant read in this repository and this sweep is not the place to grant the first
    one (hard rule 1). What it must nevertheless produce is the WHOLE fleet: a walk that
    saw one tenant would report every other tenant's live pack as unreferenced.
    """
    first = await _published_telugu_agent("మేము ఆదివారం మూసివేస్తాము.")
    second = await _published_telugu_agent("షర్ట్ కుట్టడానికి రెండు రోజులు.")

    references, known = await pack_gc.fleet_pack_references()

    for tenant_id, agent_id in (first, second):
        pointer = await _pointer(tenant_id, agent_id)
        assert pointer is not None
        assert (tenant_id, agent_id, pointer) in references
        assert tenant_id in known


async def test_no_tenant_session_in_the_walk_can_read_another_tenants_agents(
    s3: FakeS3,
) -> None:
    """The tenancy half, stated as a query rather than inferred from the walk's output.

    `_POINTERS_SQL` carries no `tenant_id` predicate — it does not need one, because the
    session it runs in is scoped — and this is the assertion that keeps that true. If RLS
    ever stopped scoping it, the walk would attribute one tenant's pointers to every other
    tenant and the collector would protect the wrong objects.
    """
    mine, _ = await _published_telugu_agent("మా దుకాణం సోమవారం తెరిచి ఉంటుంది.")
    _, their_agent = await _published_telugu_agent("మా ధరలు మారాయి.")

    async with tenant_session(mine) as session:
        rows = (await session.execute(text(pack_gc._POINTERS_SQL))).all()
    assert rows, "the scoped read saw none of its own agents"
    assert all(uuid.UUID(str(aid)) != their_agent for aid, _ in rows)

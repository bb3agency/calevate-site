"""The pack a client's agent is actually holding, when the corpus moved without a publish.

THE DEFECT THIS FILE PINS, and `kb/pack.py` named it against itself before there was any
code for it. A knowledge pack is FROZEN AT PUBLISH by construction — that is the whole
design, and it is what makes an in-process search safe at 100ms. `PackEntry.gloss` is the
load-bearing field of that pack: `docs/evidence/telugu-embedding-quality.md` measures a
Tenglish question at recall@1 0.250 against a Telugu-script corpus and 0.750 with the
English gloss beside it, and Tenglish is what Sarvam's STT actually returns.

The gloss is written by a sweep on a half-hourly clock, AFTER the publish, because the
normal order is that a reviewer approves and publishes in one sitting. So the pack the
worker loads on every call for that agent carries `gloss=None` for its whole life — and
unlike `kb_chunks.tsv`, which `refresh_projection_keys` rebuilds from the difference,
nothing looked at the pack again. A client who is happy with their opening hours never
publishes them twice, so "for its whole life" is not a figure of speech.

WHY A DIFFERENCE AND NOT A WORKLIST, which is the same argument `refresh_projection_keys`
makes one table over: the pack's id IS the digest of its content, so "is this pointer still
the corpus?" is one comparison and needs nobody to have told us anything. It therefore also
converges on the two cases an enqueue never sees — a pack whose store write failed at
publish (the pointer is NULL and the client was told the publish succeeded, which it did),
and every agent packed before this sweep existed.

The corpus here is a tailor's shop, in Telugu script, because the gloss is only ever written
for a script a Latin-script question cannot reach.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import pack as kb_pack
from apps.api.kb import service as kb_service
from apps.workers import kb_gloss
from calevate_shared.knowledge_pack import KnowledgePack, pack_object_key
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_gloss_test import _RecordingProvider, _run_sweep, _unique
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls

TAILOR_TELUGU = "శ్రీ లక్ష్మి టైలర్స్ సోమవారం నుండి శనివారం వరకు ఉదయం 10 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది."
TAILOR_ENGLISH = "Sri Lakshmi Tailors is open Monday to Saturday from 10 am to 8 pm."


async def _published_telugu_agent() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent has one live Telugu source, published and not yet glossed.

    Through submit → approve → publish, never a hand-written row: the whole defect is a
    property of the ORDER the publish and the sweep run in, which a fabricated projection
    could not express.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Hours",
            body=_unique(TAILOR_TELUGU),
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def _pointer(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).scalar()


async def _pack_the_worker_would_load(
    s3: FakeS3, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> KnowledgePack:
    """The object the pointer names, read the way `voice_worker` reads it.

    Through `pack_object_key` and the stored bytes rather than by rebuilding: what is under
    test is what a container fetches, and a test that re-derived the pack in Python would
    pass on a pointer naming nothing.
    """
    digest = await _pointer(tenant_id, agent_id)
    assert digest is not None, "the publish recorded no pack at all"
    key = pack_object_key(tenant_id, agent_id, digest)
    assert key in s3.objects, "the pointer names an object that is not in the store"
    return KnowledgePack.model_validate_json(s3.objects[key])


async def test_a_gloss_written_after_publish_reaches_the_pack_the_worker_loads(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE BUG. Publish first, gloss second — the normal order — and the pack must follow.

    The `before` assertion is the half that passed all along and is what makes the `after`
    one mean something: the pack is published, stored and pointed at, and the field the
    whole cross-script retrieval argument rests on is empty inside it.
    """
    tenant_id, agent_id = await _published_telugu_agent()
    before = await _pack_the_worker_would_load(s3, tenant_id, agent_id)
    assert [entry.gloss for entry in before.entries] == [None]

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    after = await _pack_the_worker_would_load(s3, tenant_id, agent_id)
    assert [entry.gloss for entry in after.entries] == [TAILOR_ENGLISH]
    # A new corpus is a new pack, and the old one stays readable for any call still holding
    # it — the property `pack_object_key` puts the digest in the NAME for.
    assert after.content_sha256 != before.content_sha256
    assert pack_object_key(tenant_id, agent_id, before.content_sha256) in s3.objects


async def test_a_settled_corpus_is_scanned_and_rebuilds_nothing(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick over a client who changed nothing must write nothing.

    A sweep that rebuilt unconditionally would be correct and useless: it would mint a new
    `built_at` on every agent twice an hour, move `agents.updated_at` — the column every
    "when did this last change?" screen reads — and, because the pack id is content-
    addressed, do all of that to arrive at the same digest.
    """
    tenant_id, agent_id = await _published_telugu_agent()
    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
    settled = await _pointer(tenant_id, agent_id)
    keys = set(s3.objects)

    async with tenant_session(tenant_id) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=50) == ()

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    assert await _pointer(tenant_id, agent_id) == settled
    assert set(s3.objects) == keys


async def test_a_publish_whose_store_write_failed_is_repaired_by_the_next_tick(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other case a worklist never sees, and the reason this is a difference.

    `refresh_published_pack` deliberately lets a publish SURVIVE a store outage: the
    client's knowledge is the authored record and a derived artefact may not veto it. What
    it leaves behind is an agent whose pointer is NULL while its corpus is live — on the
    phone, an agent that says the business has published nothing. Before this sweep the
    only repair was the client happening to publish again.
    """
    s3.fail = True
    tenant_id, agent_id = await _published_telugu_agent()
    s3.fail = False
    assert await _pointer(tenant_id, agent_id) is None

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    repaired = await _pack_the_worker_would_load(s3, tenant_id, agent_id)
    assert [entry.gloss for entry in repaired.entries] == [TAILOR_ENGLISH]


async def test_an_agent_that_has_published_nothing_is_never_given_a_pack(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No pack and an EMPTY pack are two states and the sweep may not collapse them.

    `SessionConfig.knowledge_pack_sha256 = None` means "this client has never written
    anything down"; an empty pack means "they withdrew everything". A sweep that flagged
    every packless agent as stale would hand the first one the second one's answer, on
    every agent of every tenant that has ever opened an account.
    """
    raw_tenant, raw_agent = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(raw_tenant)), uuid.UUID(str(raw_agent))

    async with tenant_session(tenant_id) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=50) == ()

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    assert await _pointer(tenant_id, agent_id) is None
    assert s3.objects == {}


async def test_a_withdrawal_leaves_a_settled_pointer_the_sweep_does_not_touch(
    s3: FakeS3,
) -> None:
    """Withdrawing the last source publishes an EMPTY pack, and that pack is not stale.

    The empty digest is a real digest over zero entries, so the comparison this sweep is
    built on has to agree with the builder on the empty case too — otherwise every client
    who ever withdrew everything is rebuilt twice an hour, forever.
    """
    tenant_id, agent_id = await _published_telugu_agent()
    async with tenant_session(tenant_id) as session:
        source_id = (
            await session.execute(
                text("SELECT id FROM kb_sources WHERE agent_id = :a AND is_active"),
                {"a": agent_id},
            )
        ).scalar_one()
        await kb_service.withdraw_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(source_id))
        )

    emptied = await _pack_the_worker_would_load(s3, tenant_id, agent_id)
    assert emptied.entries == ()

    async with tenant_session(tenant_id) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=50) == ()


async def test_the_sweep_cannot_reach_a_neighbours_agent(s3: FakeS3) -> None:
    """Hard rule 1, on a sweep that runs with no human behind it.

    Asked for tenant A's stale agents on tenant B's session — the one mistake RLS cannot
    see as a mistake, because the GUC and the argument disagree and only the argument is
    wrong. The answer must be nothing, never B's agent under A's name.
    """
    tenant_a, agent_a = await _published_telugu_agent()
    tenant_b, _ = await _published_telugu_agent()

    async with tenant_session(tenant_b) as session:
        assert await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_a, limit=50) == ()
        assert agent_a not in await kb_pack.agents_with_stale_packs(
            session, tenant_id=tenant_b, limit=50
        )


async def test_the_scan_is_bounded_and_the_rest_is_first_next_tick(s3: FakeS3) -> None:
    """A ceiling, for the reason every sweep in this tree has one.

    An UPDATE-free scan is still a read per agent, and a tenant with a long agent list must
    not turn a background tick into a long-held transaction. Rows past the limit are not
    lost: the order is stable, so they are still there next tick.
    """
    tenant_id, _ = await _published_telugu_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_documents SET gloss = 'a late gloss', gloss_state = 'ready'")
        )
        one = await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=1)
        none = await kb_pack.agents_with_stale_packs(session, tenant_id=tenant_id, limit=0)

    assert len(one) == 1
    assert none == ()


def test_the_gloss_tick_bounds_how_many_agents_it_scans_per_tenant() -> None:
    """The ceiling is declared beside the sweep's other two, not buried in a call."""
    assert kb_gloss.MAX_PACK_SCAN_PER_TENANT >= 1

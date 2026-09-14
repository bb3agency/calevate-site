"""The late gloss and the sparse key: what the gloss sweep now rebuilds, and what it must not.

THE DEFECT THIS FILE PINS. `kb_chunks.tsv` is the sparse arm of T3's hybrid search and it is
built from the chunk's text AND its English gloss, by `kb.service.project_chunks`, at PUBLISH
time. The gloss is written afterwards, by `workers/kb_gloss.py`, on a half-hourly clock. So
for the ORDER THAT ACTUALLY HAPPENS — a reviewer approves and publishes in one sitting, the
sweep fires at :12 or :42 — the key was built before the English half of it existed, and
nothing on any path rebuilt it. Permanently: only a republish of that same source passes
`project_chunks` again, and a client who is happy with their opening hours never publishes
them twice.

WHAT THAT COSTS IS NOT A WORSE MATCH, IT IS NO MATCH. A `tsvector` of Telugu lexemes and a
`tsquery` of English ones share nothing, so `tsv @@ q` is FALSE and the sparse arm returns
zero rows — which is also the arm that has to answer alone whenever the dense one is
unavailable (no price attestation, a provider outage: `PgVectorRetriever._question_vector`
returns None by contract and the search degrades to this key). `docs/evidence/
telugu-embedding-quality.md` is the measurement that makes the gloss worth having at all.

EVERY TEST HERE ASSERTS THE STORED KEY THROUGH A QUERY, not the contents of a column. `tsv @@
plainto_tsquery(...)` is the predicate the retrieval statement itself runs, so a test that
passed while the arm still missed would need `_SEARCH_SQL` and this file to disagree about
the text-search configuration — which is why `TS_CONFIG` is imported rather than spelled.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.gloss import GLOSS_PENDING, GLOSS_READY
from apps.api.retrieval.pgvector import TS_CONFIG
from apps.workers import kb_gloss
from sqlalchemy import text
from tests.kb_gloss_test import _RecordingProvider, _run_sweep, _unique
from tests.kb_workflow_test import _tenant_with_published_agent

#: An ordinary small-business fact in Telugu script: a tailor's shop and its opening hours.
#: Telugu because that is the only script `kb.gloss.needs_gloss` sends to a provider, and a
#: fact a caller would really ask about because the key under test is a RETRIEVAL key.
TAILOR_TELUGU = "శ్రీ లక్ష్మి టైలర్స్ సోమవారం నుండి శనివారం వరకు ఉదయం 10 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది."
TAILOR_ENGLISH = "Sri Lakshmi Tailors is open Monday to Saturday from 10 am to 8 pm."

#: A second fact for the same shop, so one agent can have several sources glossed in one tick.
BLOUSE_TELUGU = "బ్లౌజ్ కుట్టడానికి మూడు రోజులు పడుతుంది, ధర 350 రూపాయలు."
BLOUSE_ENGLISH = "Stitching a blouse takes three days and costs 350 rupees."

#: The question form this whole feature exists for: English (or Tenglish) words against a
#: Telugu-script passage. One token, because `plainto_tsquery` ANDs its lexemes and a longer
#: question would then be asserting the gloss's exact wording rather than that it is indexed.
ENGLISH_QUESTION = "tailors"


async def _published_telugu_source(
    name: str = "Hours", body: str = TAILOR_TELUGU
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant whose agent has one LIVE Telugu source whose gloss has not been written yet.

    Through `submit_source` → `approve_source` → `publish_source` and never by inserting a
    row: the bug is a property of the order those three run in relative to the sweep, so a
    fixture that projected the chunk by hand could not express it. `_unique` is
    `tests/kb_gloss_test`'s, and for its reason — the sweep is fleet-wide, so "this body was
    translated exactly once" is a claim about the whole database.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    stored = _unique(body)
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=stored
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), stored


async def _matching_chunks(tenant_id: uuid.UUID, question: str) -> int:
    """How many of this tenant's projected chunks the SPARSE ARM would return for `question`.

    `tsv @@ plainto_tsquery(...)` is `retrieval/pgvector._SEARCH_SQL`'s own predicate, under
    the configuration that statement builds its query with.
    """
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM kb_chunks "
                        f"WHERE tenant_id = :t AND tsv @@ plainto_tsquery('{TS_CONFIG}', :q)"
                    ),
                    {"t": tenant_id, "q": question},
                )
            ).scalar_one()
        )


async def _gloss_states(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(row)
            for row in (
                await session.execute(
                    text("SELECT gloss_state FROM kb_documents WHERE tenant_id = :t ORDER BY id"),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        ]


async def test_a_gloss_written_after_publish_reaches_the_sparse_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE BUG. Publish first, gloss second — the normal order — and the key must follow.

    The `before` assertion is the half that would have passed all along and is what makes the
    `after` one mean something: the chunk is live, projected and searchable by its Telugu
    lexemes, and an English question finds nothing at all.
    """
    tenant_id, _, _ = await _published_telugu_source()
    assert await _gloss_states(tenant_id) == [GLOSS_PENDING]
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 0

    await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)

    assert await _gloss_states(tenant_id) == [GLOSS_READY]
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 1


async def test_a_gloss_written_before_publish_is_not_re_keyed_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other order, and the idempotency that makes a tick over a settled corpus free.

    A source glossed while it was still awaiting review is projected WITH its gloss, so the
    refresh must find nothing to do — the property that lets it run for every tenant on every
    tick without being a write amplifier. Asserted as the tick's own count rather than as
    rows, because a refresh that rewrote identical keys would pass a row-count assertion.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    stored = _unique(TAILOR_TELUGU)
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body=stored
        )

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        # Nothing is projected yet, so there is no key to re-build — the approval gate is
        # `publish_source`'s and this refresh never inserts.
        == "translated=1 not_needed=0 rekeyed=0 repacked=0"
    )
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 0

    async with tenant_session(tenant_id) as session:
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 1

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=0 not_needed=0 rekeyed=0 repacked=0"
    )


async def test_many_glossed_documents_on_one_agent_are_re_keyed_by_one_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BATCHING. Two sources, two chunks, one refresh call — and both keys rebuilt.

    A per-document refresh would recompute the same tenant's candidate set once per chunk to
    write the same rows, which is why the count asserted here is CALLS and not rows: the
    wrong shape produces identical data and a multiple of the work.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    bodies = {"Hours": _unique(TAILOR_TELUGU), "Stitching": _unique(BLOUSE_TELUGU)}
    async with tenant_session(tenant_id) as session:
        for name, body in bodies.items():
            submitted = await kb_service.submit_source(
                session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
            )
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
            await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
            )

    calls: list[uuid.UUID] = []
    real = kb_gloss.refresh_projection_keys

    async def _counting(session: Any, *, tenant_id: uuid.UUID, limit: int) -> int:
        calls.append(tenant_id)
        return await real(session, tenant_id=tenant_id, limit=limit)

    monkeypatch.setattr(kb_gloss, "refresh_projection_keys", _counting)

    provider = _RecordingProvider(f"{TAILOR_ENGLISH} {BLOUSE_ENGLISH}")
    assert (
        await _run_sweep(monkeypatch, provider, only=tenant_id)
        == "translated=2 not_needed=0 rekeyed=2 repacked=0"
    )
    assert calls == [tenant_id], "the refresh ran once per document instead of once per tenant"
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 2


async def test_a_storage_failure_keeps_the_gloss_and_tells_somebody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure posture: the tick survives, the paid work survives, the key stays HONEST.

    Three properties, and the third is the one worth stating. (1) The sweep returns normally,
    because a tenant's storage failure must not end a fleet-wide tick. (2) The gloss stays
    `ready` — it was bought and committed BEFORE the refresh runs, so a failure here cannot
    roll back money we spent, and the next tick would otherwise buy the identical
    translation. (3) The key is left as it was — still matching the Telugu text — rather than
    half-written: the refresh is one UPDATE, so there is no state in which a chunk claims an
    English key it does not carry. And the failure is not silent: a stale key is invisible
    from every screen, so the alarm IS the report.
    """
    tenant_id, _, stored = await _published_telugu_source()

    async def _explode(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("kb_chunks is unavailable")

    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(kb_gloss, "refresh_projection_keys", _explode)
    monkeypatch.setattr(
        kb_gloss, "alert", lambda stage, code, **kw: alerts.append((str(stage), str(code)))
    )

    assert (
        await _run_sweep(monkeypatch, _RecordingProvider(TAILOR_ENGLISH), only=tenant_id)
        == "translated=1 not_needed=0 rekeyed=0 repacked=0"
    )
    assert await _gloss_states(tenant_id) == [GLOSS_READY]
    assert alerts == [("CORE_LOGIC", "kb_gloss_rekey_failed")]
    # The key still describes exactly what it did before: the client's own Telugu words, and
    # not one English lexeme. A word from the SOURCE TEXT is the query, so this is the
    # "matches what it holds" direction rather than an absence.
    assert await _matching_chunks(tenant_id, ENGLISH_QUESTION) == 0
    assert await _matching_chunks(tenant_id, stored.split()[-1]) == 1


async def test_a_refresh_cannot_re_key_a_neighbours_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard rule 1, as a zero-rows PROOF rather than an assertion about a predicate.

    Tenant B's session is asked to refresh tenant A's chunks, with A's id passed explicitly —
    the one mistake RLS cannot see as a mistake, and the reason `refresh_projection_keys`
    re-states `tenant_id` on top of the policy. Nothing may be written: the row count is zero
    AND A's key is still the one it had, proved by asking A's own session afterwards.
    """
    tenant_a, _, _ = await _published_telugu_source()
    tenant_b, _, _ = await _published_telugu_source(name="Hours B")

    # A's gloss is written but its key is deliberately left stale — the state the refresh
    # exists to end, so "nothing happened" is a claim with something to have happened.
    async with tenant_session(tenant_a) as session:
        await session.execute(
            text(
                "UPDATE kb_documents SET gloss = :g, gloss_model = 'test-model', "
                "gloss_state = :s WHERE tenant_id = :t"
            ),
            {"g": TAILOR_ENGLISH, "s": GLOSS_READY, "t": tenant_a},
        )
    assert await _matching_chunks(tenant_a, ENGLISH_QUESTION) == 0

    async with tenant_session(tenant_b) as session:
        assert await kb_service.refresh_projection_keys(session, tenant_id=tenant_a, limit=100) == 0

    assert await _matching_chunks(tenant_a, ENGLISH_QUESTION) == 0
    assert await _matching_chunks(tenant_b, ENGLISH_QUESTION) == 0

    # And the same call on A's OWN session does the work, so the zero above is tenancy and
    # not a refresh that cannot write at all.
    async with tenant_session(tenant_a) as session:
        assert await kb_service.refresh_projection_keys(session, tenant_id=tenant_a, limit=100) == 1
    assert await _matching_chunks(tenant_a, ENGLISH_QUESTION) == 1

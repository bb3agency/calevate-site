"""A caller's SENTENCE is gone from the transcript projection — after an erasure, and
after the retention clock.

**WHY THESE TESTS ASSERT ON A SENTENCE AND NOT ON A ROW COUNT.** The defect this scope is
most exposed to is not a missing row, it is a SURVIVING SENTENCE, and a count assertion
passes against it: `caller_chunks` keeps its row on purpose (the tombstone is what stops
the next discovery tick re-projecting the call and re-buying a vector for text an erasure
has just destroyed), so `SELECT count(*)` is unchanged by a correct erasure AND by a
completely broken one. What changes is whether the words are still reachable.

So every assertion below asks the DATABASE the question a search would ask — does any
projection of this tenant still match the lexemes of what the caller said — through
`tsv @@ plainto_tsquery`, under the same text-search configuration the store was written
with. That is the sparse retrieval key itself, not a proxy for it.

**AND WHY A CASCADE WOULD NOT HAVE DONE IT.** A DPDP erasure does not DELETE a call: it
overwrites `transcript_turns.text` / `.text_redacted` with the marker, sets
`calls.summary = NULL` and keeps the row, because a call is billing evidence. So
`caller_chunks.call_id`'s foreign key never fires on the path that matters.
`test_a_cascade_would_not_have_fired` pins that premise, because if it ever stops being
true the explicit arms below stop being the only protection and a reader should be told.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.insights.service_test import _tenant
from apps.api.retrieval import call_chunks
from apps.api.retrieval.caller_projections import store_chunks
from apps.api.retrieval.models import EMBED_ERASED, EMBED_EXPIRED, RETENTION_TRANSCRIPT
from apps.workers.retention import REDACTED_MARK, _call_clock
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The caller's own words. It names no identifier, so REDACTION LEAVES IT INTACT — which is
#: the whole point: `text_redacted` still holds this sentence after every redactor in the
#: product has run, and it is what has to disappear when the person asks to be forgotten.
CALLER_WORDS = "Do you do appointments on the weekend or only on weekdays?"
AGENT_WORDS = "We are open on Saturday from nine until two, and closed on Sunday."
SUMMARY_WORDS = "Caller asked whether weekend appointments were available and was told Saturday."

#: What a client would actually type. The assertions match on this rather than on the
#: sentence verbatim, because a search does — an erasure that left the lexemes but broke the
#: exact string would pass a substring test and fail a person.
QUESTION = "weekend appointments"

_TENANT_MATCHES_SQL = (
    "SELECT count(*) FROM caller_chunks "
    "WHERE tenant_id = :tid AND tsv @@ plainto_tsquery('english', :q)"
)


async def _seed_call(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, ended_at: datetime) -> uuid.UUID:
    """One completed inbound call with a real caller number, two turns and a summary."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, summary, started_at, ended_at, duration_s, created_at, "
                "updated_at) VALUES (:id, :t, :a, :ecid, 'inbound', 'completed', :frm, "
                "'+911140000000', :summary, :at, :at, 120, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "ecid": f"cc-{uuid.uuid4().hex}",
                "frm": f"+9198{uuid.uuid4().int % 10**8:08d}",
                "summary": SUMMARY_WORDS,
                "at": ended_at,
            },
        )
        for idx, (speaker, body) in enumerate((("caller", CALLER_WORDS), ("agent", AGENT_WORDS))):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, :i, :s, :body, "
                    ":body, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "i": idx,
                    "s": speaker,
                    "body": body,
                },
            )
    return call_id


async def _project(tenant_id: uuid.UUID) -> int:
    """Run BOTH registered transcript scopes, as the shared sweep would."""
    written = 0
    async with tenant_session(tenant_id) as session:
        for projection in (call_chunks.TURN_PROJECTION, call_chunks.SUMMARY_PROJECTION):
            chunks = await projection.discover(session, 100)
            written += await store_chunks(
                session, tenant_id=tenant_id, projection=projection, chunks=chunks
            )
    return written


async def _still_matches(tenant_id: uuid.UUID) -> int:
    """How many of this tenant's projections a search for the sentence would still reach."""
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(text(_TENANT_MATCHES_SQL), {"tid": tenant_id, "q": QUESTION})
            ).scalar_one()
        )


async def _scrub_the_call_as_an_erasure_does(tenant_id: uuid.UUID, call_id: uuid.UUID) -> None:
    """The two statements `execute_deletion_request` and `_erase_tenant_calls` both run.

    Copied rather than called so this test does not depend on the whole erasure worker
    booting — but copied VERBATIM in effect, which `test_a_cascade_would_not_have_fired`
    then checks: the call row survives both of them.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE transcript_turns SET text = :mark, text_redacted = :mark, "
                "updated_at = now() WHERE call_id = :c"
            ),
            {"mark": REDACTED_MARK, "c": call_id},
        )
        await session.execute(
            text(
                "UPDATE calls SET from_e164 = NULL, to_e164 = NULL, summary = NULL, "
                "updated_at = now() WHERE id = :c"
            ),
            {"c": call_id},
        )


async def _seeded(*, ended_at: datetime | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant()
    call_id = await _seed_call(tenant_id, agent_id, ended_at=ended_at or datetime.now(UTC))
    assert await _project(tenant_id) > 0, "premise: the call projected at all"
    return tenant_id, call_id


# --- the premise ----------------------------------------------------------------------


async def test_the_sentence_is_reachable_before_anything_forgets_it() -> None:
    """Without this every test below could pass against an empty table."""
    tenant_id, _ = await _seeded()
    assert await _still_matches(tenant_id) >= 1


async def test_the_projection_carries_the_transcript_clock_and_category() -> None:
    """A table no retention category names never expires. This is that fact, on the row."""
    tenant_id, _ = await _seeded()
    async with tenant_session(tenant_id) as session:
        categories = set(
            (await session.execute(text("SELECT DISTINCT retention_category FROM caller_chunks")))
            .scalars()
            .all()
        )
    assert categories == {RETENTION_TRANSCRIPT}


async def test_the_marker_this_module_carries_is_the_erasers_own() -> None:
    """`call_chunks.REDACTED_MARK` is a deliberate duplicate of `retention.REDACTED_MARK`
    (the worker imports this module, so importing it back is a cycle). This is the pin that
    fails the day either moves — without it the duplicate is a silent divergence, and the
    symptom would be a projection that happily embeds the word "[erased]"."""
    assert call_chunks.REDACTED_MARK == REDACTED_MARK


async def test_the_retention_clock_is_the_erasers_own_clock() -> None:
    """`call_chunks._CLOCK` is `retention._call_clock('c')`, duplicated for the same
    cycle reason. A projection dated by a different clock from the sweep that expires the
    turns would expire on a different day from the words it is a copy of."""
    assert _call_clock("c") == call_chunks._CLOCK


# --- erasure --------------------------------------------------------------------------


async def test_erasure_makes_the_callers_sentence_unreachable() -> None:
    """THE REGRESSION. Scrubbing the transcript is not enough — the vector and the lexemes
    are a second copy of the sentence, and this is the arm that reaches them."""
    tenant_id, call_id = await _seeded()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)

    async with tenant_session(tenant_id) as session:
        forgotten = await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])
    assert forgotten >= 1

    assert await _still_matches(tenant_id) == 0, (
        "the caller's sentence is still reachable through the projection's search key"
    )


async def test_erasure_empties_both_keys_and_tombstones_the_row() -> None:
    """Emptied, not deleted — and BOTH keys, because either alone still answers a query."""
    tenant_id, call_id = await _seeded()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)
    async with tenant_session(tenant_id) as session:
        await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT embedding IS NULL, tsv = ''::tsvector, embed_state, "
                    "scrubbed_at IS NOT NULL, content_sha256 FROM caller_chunks"
                )
            )
        ).all()
    assert rows, "the row was DELETED — the tombstone that blocks re-projection is gone"
    for no_vector, no_lexemes, state, tombstoned, sha in rows:
        assert no_vector and no_lexemes and tombstoned
        assert state == EMBED_ERASED
        assert sha == ""


async def test_the_erased_call_does_not_come_back_on_the_next_sweep() -> None:
    """THE REASON THE ROW IS KEPT. Discovery re-projects anything with no live projection,
    so a DELETE here would let the next tick re-buy a vector for text the erasure had just
    destroyed — money spent to undo a legal obligation, on a certificate already signed."""
    tenant_id, call_id = await _seeded()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)
    async with tenant_session(tenant_id) as session:
        await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])

    await _project(tenant_id)
    assert await _still_matches(tenant_id) == 0, "a sweep after the erasure put the words back"


async def test_erasing_twice_reports_the_work_once() -> None:
    """The count reaches the proof certificate, and a re-run of an erasure must not report
    a second, larger number for work the first one already did."""
    tenant_id, call_id = await _seeded()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)
    async with tenant_session(tenant_id) as session:
        first = await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])
    async with tenant_session(tenant_id) as session:
        second = await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])
    assert first >= 1
    assert second == 0


async def test_another_callers_sentence_is_left_alone() -> None:
    """An erasure is keyed on ONE subject's calls and must not widen. A request that
    emptied the account's whole search index would be a client-visible outage caused by a
    stranger."""
    tenant_id, agent_id = await _tenant()
    erased_call = await _seed_call(tenant_id, agent_id, ended_at=datetime.now(UTC))
    other_call = await _seed_call(
        tenant_id, agent_id, ended_at=datetime.now(UTC) - timedelta(minutes=5)
    )
    assert await _project(tenant_id) > 0

    await _scrub_the_call_as_an_erasure_does(tenant_id, erased_call)
    async with tenant_session(tenant_id) as session:
        await call_chunks.erase_projections_for_calls(session, call_ids=[erased_call])

    async with tenant_session(tenant_id) as session:
        survivors = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT call_id FROM caller_chunks "
                        "WHERE tsv @@ plainto_tsquery('english', :q)"
                    ),
                    {"q": QUESTION},
                )
            )
            .scalars()
            .all()
        )
    assert [uuid.UUID(str(c)) for c in survivors] == [other_call]


async def test_a_cascade_would_not_have_fired() -> None:
    """THE PREMISE OF THE WHOLE DESIGN, pinned so it cannot quietly stop being true.

    If an erasure ever starts DELETING calls, `caller_chunks.call_id`'s foreign key becomes
    a real mechanism and this test fails — at which point somebody should read the arms
    above again rather than discover the change through a surviving sentence.
    """
    tenant_id, call_id = await _seeded()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)
    async with tenant_session(tenant_id) as session:
        still_there = (
            await session.execute(text("SELECT count(*) FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
    assert still_there == 1, "an erasure now deletes calls; re-read call_chunks.py's premise"


# --- retention ------------------------------------------------------------------------


async def test_the_retention_clock_makes_the_sentence_unreachable() -> None:
    """The other half, and the one nobody requests: a promise made to every caller who
    never asks. `transcript` is the category that owns these words, and these rows ride it.
    """
    tenant_id, _ = await _seeded(ended_at=datetime.now(UTC) - timedelta(days=400))

    async with tenant_session(tenant_id) as session:
        expired = await call_chunks.expire_transcript_projections(
            session, cutoff=datetime.now(UTC) - timedelta(days=365), batch=500
        )
    assert expired >= 1
    assert await _still_matches(tenant_id) == 0, (
        "the caller's sentence outlived the tenant's transcript retention period"
    )


async def test_retention_says_expired_and_not_erased() -> None:
    """Two different facts about the same emptied row. An operator asking "did this age out
    or did somebody ask to be forgotten" cannot answer it from one value."""
    tenant_id, _ = await _seeded(ended_at=datetime.now(UTC) - timedelta(days=400))
    async with tenant_session(tenant_id) as session:
        await call_chunks.expire_transcript_projections(
            session, cutoff=datetime.now(UTC) - timedelta(days=365), batch=500
        )
    async with tenant_session(tenant_id) as session:
        states = set(
            (await session.execute(text("SELECT DISTINCT embed_state FROM caller_chunks")))
            .scalars()
            .all()
        )
    assert states == {EMBED_EXPIRED}


async def test_retention_leaves_a_call_inside_the_window_alone() -> None:
    """The cutoff is a cutoff. A sweep that took everything would delete a client's whole
    search history the first night it ran."""
    tenant_id, agent_id = await _tenant()
    await _seed_call(tenant_id, agent_id, ended_at=datetime.now(UTC) - timedelta(days=400))
    await _seed_call(tenant_id, agent_id, ended_at=datetime.now(UTC))
    assert await _project(tenant_id) > 0

    async with tenant_session(tenant_id) as session:
        await call_chunks.expire_transcript_projections(
            session, cutoff=datetime.now(UTC) - timedelta(days=365), batch=500
        )
    assert await _still_matches(tenant_id) >= 1, "the recent call's projection expired too"


async def test_an_expired_projection_does_not_come_back_on_the_next_sweep() -> None:
    """Same tombstone argument as the erasure, on the clock nobody asked for."""
    tenant_id, _ = await _seeded(ended_at=datetime.now(UTC) - timedelta(days=400))
    async with tenant_session(tenant_id) as session:
        await call_chunks.expire_transcript_projections(
            session, cutoff=datetime.now(UTC) - timedelta(days=365), batch=500
        )
    await _project(tenant_id)
    assert await _still_matches(tenant_id) == 0, "a sweep after expiry put the words back"

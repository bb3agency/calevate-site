"""Freeze one agent's published knowledge into an immutable `KnowledgePack` (D-599).

WHAT THIS IS THE OTHER HALF OF. `calevate_shared.knowledge_pack` carries the shape and
the measurement — a pack is built ONCE at publish, stored content-addressed, fetched once
per session and searched in-process, because a store read per turn buys a failure mode per
turn inside a 100ms budget. This module is the BUILDER: it reads what a human approved and
published, projects it, and puts the bytes where the worker will find them.

WHY THE READ IS A JOIN AND NOT A SELECT FROM ONE TABLE. `kb_chunks` is the retrieval
PROJECTION and deliberately holds no content (`kb/models.py:139-147`); the client's prose
lives once on `kb_documents.content`, and the English gloss — the field the whole retrieval
argument rests on — is `kb_documents.gloss` (`kb/models.py:95-106`). `kb_chunks.tsv`'s own
comment says the sparse key is built from a JOIN for exactly this reason
(`kb/models.py:179-182`). So the pack is assembled the same way the search vector is.

WHAT "PUBLISHABLE" MEANS HERE, STATED ONCE. A `kb_chunks` row exists only because
`kb/service.publish_source` put it there for a source with `approved_at IS NOT NULL`
(`kb/models.py:133-136` records that the approval gate is structural rather than a
predicate somebody must remember), and it is LIVE when `is_active` is true on both the
projection and the source it projects. See `_LIVE_CHUNKS_FROM` for why both are checked.

**VERSION 2 CARRIES VECTORS AND `kb_chunks.embedding` IS STILL NOT WHERE THEY COME FROM.**
That column is right there in the table this reads and is deliberately not projected, and
the reason is no longer "there are no vectors" — it is that it holds a DIFFERENT model's
vectors at a different width, for a different consumer. `retrieval/embedding.py` fills it
with `text-embedding-3-small` at 1536 dimensions for the dashboard's pgvector index; the
pack's dense arm compares against a query vector from `kb/pack_vectors.EMBEDDING_MODEL`, and
two encoders' vectors are not comparable however similar the numbers look. Projecting the
column would produce a dense arm that ranks confidently and wrongly with nothing in any log.
So `pack_vectors.embed_entries` buys the pack's own, under its own model, metered under its
own `usage_events` feature — see that module for hard rule 7's pre-flight and for why this
is a no-op until an operator attests the price.

**WHO CALLS THIS, AND WHY IT IS THE KB PUBLISH PATH AND NOT `publish_agent`.**
`refresh_published_pack` at the bottom is the entry point, and `kb/service.publish_source`
and `kb/service.withdraw_source` are its callers on that path — the only two functions that
change which of an agent's chunks are live. (`workers/kb_gloss.py` is the third caller and
is not a publish: it changes what a live chunk SAYS rather than which chunks there are, and
it reaches the same helper rather than a second one. See the gloss paragraph below.)
`publish_agent` was the obvious alternative and is wrong twice: it runs for a voice
change, a call-cap change and nine other reasons that
cannot move a single chunk, and it does NOT run for the publish that matters most (a T1-T4
source recompiles no T0 block, so `recompile_t0` returns None and nothing republishes).
A pack refreshed there would be rebuilt constantly and stale exactly when it mattered.

**A GLOSS THAT LANDS AFTER THE PUBLISH NOW REACHES THE PACK, AND THIS PARAGRAPH USED TO
RECORD IT AS A KNOWN GAP.** `apps/workers/kb_gloss.py` writes `kb_documents.gloss` on a
sweep, minutes or hours after a source is published, and said of itself that a late gloss
"starts working immediately, with no prompt re-mint and no republish" — true of
`retrieval/compiled_facts.py`, which reads the column live, and NOT true of a pack, which is
frozen at publish by construction. So a Telugu-script corpus published before its sweep ran
was packed with `gloss=None`, and until the client next published or withdrew anything on
that agent the in-call search was the 0.250-recall case `kb/gloss.py` measured rather than
the 0.750 one — permanently, for a client who is happy with their opening hours and never
publishes them twice. `agents_with_stale_packs` below is the half this module owns: it names
the agents whose recorded pointer no longer matches the pack their corpus implies, and the
sweep rebuilds those through `refresh_published_pack`. Not a second builder and not a
worklist of ids — see that function for why the difference is computed from the digest.

⚠ **A SUPERSEDED PACK KEEPS THE WORDS THAT WERE IN IT.** A client who removes one document
gets a new pack without it; the previous pack stays at its own key, holding the approved
text as it was. That is tolerable because a pack holds a BUSINESS's own published knowledge
and no data principal's data — no number, no transcript, no caller — which is why
`scripts/check_erasure_coverage` has nothing to reach here.

**TWO MECHANISMS REACH THIS PREFIX NOW, AND THIS PARAGRAPH USED TO SAY "NOTHING DOES".**
The first is `infra/object-lifecycle/policy.json`'s
`knowledge-packs-growth-ceiling-not-retention` (2555 days, pinned by
`tests/object_lifecycle_test.py`), which is a growth CEILING and structurally cannot be
retention: an expiry is measured from an object's CREATION, so any ceiling low enough to
reclaim space would eventually delete the live pack of the best-behaved client on the
platform — the one whose price list has not needed correcting.

The second is the one that actually reclaims: `apps/workers/pack_gc.py` (D-611, 05:07
daily) deletes a pack that no `agents.knowledge_pack_sha256` names and that has sat out a
seven-day grace. **THE GRACE EXISTS BECAUSE OF THE WRITE ORDER IN THIS FILE** — the object
is stored before the pointer commits (`refresh_published_pack`), so for the width of one
publish transaction a pack is legitimately unreferenced and about to be referenced. What
that sweep deliberately does NOT reach is a pack whose tenant it cannot enumerate: a CLOSED
tenant's objects stay, bounded only by the ceiling, because deleting on ABSENCE would mean
one bad directory read takes the live pack of every tenant it missed. That residue belongs
in the closure path, which positively knows the tenant is gone, and it is still open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from calevate_shared.invisible_text import find_shadow_text, strip_shadow_text
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.ownership import assert_visible
from apps.api.kb.pack_vectors import declared_dimensions, embed_entries, pack_embedding_declaration

log = get_logger(__name__)

#: The largest pack this platform will publish, in bytes of the stored JSON.
#:
#: **WHAT A PACK THAT IS TOO BIG ACTUALLY DOES, WHICH IS WHY THERE IS A CEILING AT ALL.**
#: The worker fetches the whole pack while the phone rings, under a fixed wall clock
#: (`voice_worker/storage.PACK_FETCH_BUDGET_S`, 2.0 s). A pack that does not arrive inside it
#: is not a slow pack: `load_session_knowledge` answers `fetch_failed`, and every question on
#: every call to that agent for the life of the deploy comes back `temporarily_unavailable`
#: — the agent answers the phone and then cannot say one thing about the client's business.
#: Nothing on our side of the wire records that; it is a log line in a container a vendor
#: operates. So the failure is caught HERE, where a human is standing at a publish screen and
#: can prune, rather than there, where nobody is.
#:
#: ⚠ **A REFUSAL THRESHOLD, NOT A MEASURED TRANSFER LIMIT, AND THE DIFFERENCE MATTERS.**
#: Nobody has timed a fetch from Pipecat Cloud `ap-south` to our bucket
#: (`pre-build-blockers` §3.6, the same gap `PACK_FETCH_BUDGET_S` records), so no byte figure
#: here can claim "this fits and that does not". What IS known is arithmetic and a
#: measurement: a vectored entry is 16,382 B of serialised pack and a 300-entry pack weighs
#: 5,003,292 B (`tests/in_call_lookup_latency_test.py`, against the bytes `publish_pack`
#: uploads, 14 Sep 2026); 8 MiB inside 2.0 s demands better than 4 MiB/s sustained for the
#: whole of a budget that also has to cover TLS and the first byte. Below this line the pack
#: is merely unmeasured; above it the budget is arithmetically demanding, and a client is
#: better served by a refusal they can act on than by an agent that has quietly lost its
#: knowledge. The first `ap-south` measurement replaces this number.
MAX_PACK_BYTES: Final[int] = 8 * 1024 * 1024


class PackTooLargeError(RuntimeError):
    """This agent's published knowledge does not fit in a pack the worker can load.

    Raised at publish, caught by `refresh_published_pack`, which keeps the previous pointer
    — so the agent goes on answering from the last pack that fits rather than from none.
    """

    def __init__(self, *, size: int, ceiling: int) -> None:
        self.size = size
        self.ceiling = ceiling
        super().__init__(
            f"the in-call knowledge pack is {size} bytes, over the {ceiling}-byte ceiling"
        )


#: **THE ONE SPELLING OF "LIVE", SHARED BY BOTH STATEMENTS BELOW.** `_ENTRIES_SQL` decides
#: what goes INTO a pack; `_GLOSSED_AGENTS_SQL` decides whose pack is worth re-checking after
#: a gloss lands. If the two ever disagreed about liveness the staleness scan would skip an
#: agent whose pack had genuinely moved, and the symptom would be a pack that is simply never
#: rebuilt — invisible from every screen, which is the exact shape of the defect the scan
#: exists to close. So the predicate is written once and interpolated, rather than typed
#: twice and kept in step by proof-reading.
#:
#: **BOTH `is_active` FLAGS, AND THE SECOND ONE IS NOT BELT-AND-BRACES.** The projection's
#: flag is converged onto the source's by `kb/service.py` (`_DEACTIVATE_SQL`), which runs on
#: the NEXT publish for that agent — so between a source going inactive by some other path
#: and that publish, `c.is_active` can be true over an archived source. A pack is a frozen
#: artefact a container caches for the life of a session; baking a superseded price list into
#: one is not a query that self-corrects on the next tick. `s.is_active` is what
#: `kb/service.active_knowledge` calls live and it is the only definition this module accepts.
#:
#: `tenant_id` is re-stated on top of RLS for the reason `retrieval/pgvector.py` re-states
#: it: RLS cannot see a caller passing tenant A's id on a session opened for tenant B as a
#: mistake, and that caller would otherwise get B's chunks under A's name.
_LIVE_CHUNKS_FROM: Final = """
FROM kb_chunks c
JOIN kb_sources s ON s.id = c.source_id
JOIN kb_documents d ON d.id = c.document_id
WHERE c.tenant_id = :tid AND c.is_active AND s.is_active
"""

#: One agent's live, published knowledge, joined to the text and the gloss it projects.
#:
#: **`s.version`, NOT `c.version`, FOR `PackEntry.document_version`.** They are equal by
#: construction — `_PROJECT_SQL` writes `s.version` into the projection — and when a
#: projection is stale the source row is the one that says which revision a caller was
#: actually answered from. Reading the truth costs nothing here because the join is already
#: made for `s.is_active`.
#:
#: No `ORDER BY`: the canonical order is `KnowledgePack.digest`'s and is applied in Python
#: below, so there is exactly one place that decides it.
_ENTRIES_SQL: Final = f"""
SELECT c.id, c.document_id, s.version, d.content, d.gloss
{_LIVE_CHUNKS_FROM}
  AND c.agent_id = :aid
"""


def _screened(value: str, *, chunk_id: UUID, field: str) -> str:
    """`value` with the tag block removed — the LAST point before the in-call model.

    **WHY A SECOND PLACE, WHEN `kb/service._reject_invisible_characters` ALREADY REFUSES
    THIS AT THE DOOR.** Because a pack is not built from a submission, it is built from
    STORED ROWS, and the two are not the same set:

    * A pack is rebuilt long after ingest — `refresh_published_pack` runs on every publish
      and withdraw, and `agents_with_stale_packs` re-drives it from a sweep. Every row
      written before that gate covered the tag block rebuilds through here untouched.
    * `d.gloss` NEVER PASSED THE GATE AT ALL. It is written by `apps/workers/kb_gloss.py`
      from a MODEL's output, onto a row that was approved before the gloss existed, by an
      UPDATE the ingest path never sees. A model asked to paraphrase attacker-supplied text
      is exactly the component that can repeat an instruction it was shown.

    **AND WHY IT STRIPS WHERE THE DOOR REFUSES.** A refusal is worth having where somebody
    can act on it: the client is at the upload screen, the message names the codepoints, and
    they can fix their source. Nobody is standing here. Refusing would abort the publish —
    or the sweep — over one stored row, which turns a hidden instruction into a whole
    agent's knowledge going dark, and would do it on the path a client uses to REMOVE the
    offending source. So the words that cannot be seen are removed, everything that can be
    seen is kept byte-for-byte, and an operator gets a line naming the codepoints and the
    chunk (never the prose — hard rule 6). `warning` and not `alert()` deliberately: the
    pack that results is correct, so this is a repair to be counted, not an alarm to be
    woken for, and the door's own refusal is where the loud half lives.
    """
    found = find_shadow_text(value)
    if not found:
        return value
    log.warning(
        "kb_pack_shadow_text_stripped",
        extra={
            "chunk_id": str(chunk_id),
            "field": field,
            "codepoints": ", ".join(f"U+{code:04X}" for code in found[:8]),
        },
    )
    return strip_shadow_text(value)


async def read_entries(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> tuple[PackEntry, ...]:
    """This agent's live published chunks, projected to `PackEntry` in canonical order.

    Ordered by `str(chunk_id)` — the SAME key `KnowledgePack.digest` sorts by
    (`knowledge_pack.py:151`) — rather than by an `ORDER BY` that merely happens to agree.
    The stored JSON and the hashed JSON then list the entries identically, so a reader
    comparing them is comparing one ordering rather than two that could drift.

    Run on the CALLER's tenant-scoped session (hard rule 1). This function opens nothing of
    its own and so can never widen the tenancy of the code that called it.

    **THE TEXT IS SCREENED ON THE WAY THROUGH (`_screened`)** and that is the only
    transformation this function performs. Read that helper for why the ingest gate is not
    enough on its own and why this one strips rather than refuses.

    No text length guard: `kb/service.MAX_CHUNK_CHARS` is 700 and both writers of
    `kb_documents.content` chunk through `chunk_text` (`kb/service.py:403,471`), which is
    comfortable headroom under `PackEntry.text`'s 4000. A guard here would be a branch
    nothing can reach, and pydantic refuses loudly rather than truncating if that invariant
    ever breaks — which is the right failure, because a silently shortened answer is a
    client's agent quoting half a price list.
    """
    rows = (await session.execute(text(_ENTRIES_SQL), {"tid": tenant_id, "aid": agent_id})).all()
    entries = [
        PackEntry(
            chunk_id=row[0],
            document_id=row[1],
            document_version=row[2],
            # NOT `text=row[3]` — see `_screened`. This is the last code that touches these
            # words before they are frozen into a pack, fetched by the voice worker and
            # handed to the in-call LLM as a tool result it is told to answer from.
            text=_screened(row[3], chunk_id=row[0], field="content"),
            gloss=None if row[4] is None else _screened(row[4], chunk_id=row[0], field="gloss"),
        )
        for row in rows
    ]
    return tuple(sorted(entries, key=lambda entry: str(entry.chunk_id)))


async def build_pack(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> KnowledgePack:
    """Everything this agent knows, frozen. Stores nothing.

    **AN AGENT WITH NOTHING PUBLISHED IS AN EMPTY PACK, NOT AN ERROR.** A clinic that has
    uploaded no knowledge is a valid, common state — the agent still answers the phone, and
    the retrieval tool must return `not_found` (a fact about the corpus) rather than
    `temporarily_unavailable` (a fact about us), which is a distinction
    `knowledge_pack.RetrievalOutcome` exists to keep. Refusing to build the pack would
    manufacture the second from the first and page somebody about a clinic that simply has
    not written anything down yet.

    **AN AGENT THAT DOES NOT EXIST IS AN ERROR**, and it is a 404 rather than a 403 for
    `db/ownership.assert_visible`'s reason: from inside a tenant, "not yours" and "no such
    id" are the same fact, and telling them apart publishes the existence of a neighbour's
    rows. That check must come FIRST — without it an unknown or foreign agent id reads as
    zero chunks and mints a perfectly valid empty pack, which is the same bytes a real
    empty agent gets and would be stored under the foreign id's key.

    `built_at` is stamped AFTER the read, and is deliberately outside the content hash, so a
    rebuild that changes nothing keeps its id and every warm container holding it stays warm.

    **THE EMBEDDING STEP IS BETWEEN THE READ AND THE DIGEST, AND THAT ORDER IS FORCED.** The
    encoder's NAME is inside the hash (`KnowledgePack.digest`, which argues why the floats
    are not), so the digest cannot be computed until it is known whether this deployment
    bought vectors at all. `embed_entries` returns the entries unchanged and `None` whenever
    it did not — no price, no credential, nothing to embed, or every batch failed — and the
    pack that results is byte-identical to what a deployment without a Gemini key builds.

    **IT IS AWAITED ON THE PUBLISH PATH AND THAT IS WHERE IT BELONGS.** A client who has just
    clicked publish is waiting on a few hundred milliseconds of hosted encoder; the
    alternative — a queued job that fills vectors in afterwards — would need the pack to be
    mutable, and the pack is immutable and content-addressed precisely so a cached one cannot
    be wrong. `kb/pack_vectors.EMBED_TIMEOUT_S` bounds it, and a provider that fails costs
    the dense arm rather than the publish.
    """
    await assert_visible(session, "agent", agent_id)
    entries = await read_entries(session, tenant_id=tenant_id, agent_id=agent_id)
    entries, embedding_model = await embed_entries(session, tenant_id=tenant_id, entries=entries)
    dimensions = declared_dimensions(embedding_model)
    return KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(
            tenant_id,
            agent_id,
            entries,
            embedding_model=embedding_model,
            embedding_dimensions=dimensions,
        ),
        built_at=datetime.now(UTC),
        embedding_model=embedding_model,
        embedding_dimensions=dimensions,
        entries=entries,
    )


async def publish_pack(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> str:
    """Build this agent's pack, store it, and return its id (`content_sha256`).

    The id is what a caller records as the version an agent published: it names the bytes,
    so a row carrying it can never point at a different corpus than the one that was live.

    **THE OBJECT IS WRITE-ONCE, AND AN EXISTING KEY IS A NO-OP RATHER THAN AN ERROR.** The
    key ends in the content hash, so a key that exists already holds THIS pack's entries —
    the same tenant, the same agent, the same chunks, by construction. Re-publishing
    unchanged knowledge therefore has nothing to write.

    It is SKIPPED rather than overwritten with identical bytes, and the difference is
    `built_at`: it is outside the hash on purpose, so two builds of one corpus differ in
    that field and a rewrite would change the object's bytes without changing its meaning.
    Skipping keeps the stored object genuinely immutable — the pack a container fetched at
    09:00 is byte-for-byte the pack it re-fetches at 17:00 — which is what makes caching by
    key safe to reason about. The cost is one GET on a KB-sized object on a publish path,
    which nothing measures in milliseconds.

    The read/write pair is NOT atomic and does not need to be: two publishers racing on the
    same corpus compute the same key and write the same entries, so whichever order they
    interleave in, the object that exists afterwards is the right one.
    """
    # Deferred import: boto3 is heavy and this module is reachable from the API's request
    # path (`kb/uploads.py:363-365` defers it for the same reason).
    from apps.workers.storage import read_kb_object, store_knowledge_pack

    pack = await build_pack(session, tenant_id=tenant_id, agent_id=agent_id)
    # BEFORE the existence check, so the refusal depends on the corpus and not on whether
    # these bytes happen to be in the bucket already from an earlier deploy's ceiling.
    data = pack.model_dump_json().encode()
    if len(data) > MAX_PACK_BYTES:
        raise PackTooLargeError(size=len(data), ceiling=MAX_PACK_BYTES)
    key = pack_object_key(tenant_id, agent_id, pack.content_sha256)

    # `read_kb_object` returns None for GONE and raises for UNREACHABLE, which is the
    # distinction this needs: a store we cannot see must not be read as "not written yet"
    # and then written to, and must certainly not be read as "already there" and skipped.
    if await read_kb_object(key) is not None:
        # Ids and counts only (hard rule 6): never a chunk, never a gloss, never a source
        # name. `content_sha256` is the artefact's NAME — it is what the caller records —
        # and a digest of approved text is not the text.
        log.info(
            "knowledge_pack_unchanged",
            extra={
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "pack_id": pack.content_sha256,
                "entries": len(pack.entries),
            },
        )
        return pack.content_sha256

    await store_knowledge_pack(key=key, data=data)
    log.info(
        "knowledge_pack_published",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "pack_id": pack.content_sha256,
            "entries": len(pack.entries),
            # WHAT THE WORKER HAS TO PULL DOWN WHILE THE PHONE RINGS, against
            # `MAX_PACK_BYTES`. The one number that says how close a client's corpus is to
            # the ceiling, and it is not derivable from `entries`: a vectored entry is
            # ~16 KB and an unvectored one is a few hundred bytes.
            "bytes": len(data),
            # How much of the corpus carries a retrieval key a Tenglish question can reach
            # (`kb/gloss.py`). A count, so an operator can see a gloss sweep that never ran
            # without anybody reading a client's knowledge to find out.
            "glossed": sum(1 for entry in pack.entries if entry.gloss),
            # How much of the corpus the DENSE arm can reach. Zero with a non-null
            # `embedding_model` never happens (`embed_entries` declares no model when
            # nothing landed), so the pair reads unambiguously: no model = the arm is off
            # for this deployment, a model with a count below `entries` = batches failed.
            "vectored": sum(1 for entry in pack.entries if entry.vector_f32_b64),
            "embedding_model": pack.embedding_model,
        },
    )
    return pack.content_sha256


#: Where the call path reads the pack id from. `IS DISTINCT FROM` so a republish that
#: changed nothing writes no row at all: the column is a pointer at an immutable object, so
#: re-stamping it with the value it already holds would move `updated_at` — the timestamp
#: every "when did this agent last change?" screen reads — for a change that did not happen.
#:
#: `knowledge_pack_recorded_at` (migration f4b18c7d2e59) rides the SAME statement so the
#: pointer and its clock cannot disagree, and it inherits that `IS DISTINCT FROM` on
#: purpose: it dates the pack this agent ANSWERS OUT OF, not the last press of publish. A
#: client who republished identical text changed nothing about what their agent knows, and
#: a timestamp that jumped would report a correction as landed when the pointer proves it
#: had already landed. `kb/delivery.py` is the only reader.
#:
#: `tenant_id` is re-stated on top of RLS for `_ENTRIES_SQL`'s reason.
_RECORD_PACK_SQL: Final = """
UPDATE agents
SET knowledge_pack_sha256 = :sha, knowledge_pack_recorded_at = now(), updated_at = now()
WHERE id = :aid AND tenant_id = :tid AND knowledge_pack_sha256 IS DISTINCT FROM :sha
"""


async def refresh_published_pack(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> str | None:
    """Freeze this agent's live knowledge and point `agents.knowledge_pack_sha256` at it.

    THE ONE ENTRY POINT FOR EVERY WRITER OF `agents.knowledge_pack_sha256`
    (`docs/PIPECAT-MIGRATION.md` §6 step 12): the KB publish path, the withdrawal path, and
    the English-gloss sweep, which all arrive here rather than each freezing a pack its own
    way. `publish_pack` stores the bytes; this is what makes them findable, because a pack
    nothing names is a pack no session will ever load. Returns the id it recorded, or
    `None` when the pack could not be built or stored — see the posture below.

    **THE POSTURE ON FAILURE: THE PUBLISH SURVIVES, THE POINTER DOES NOT MOVE, AND SOMEBODY
    IS TOLD.** Three options were available and two are worse:

    * **Raise.** The client corrected a price, the vendor took the new document, the
      activation flip committed — and then an object store blip rolls all of it back and
      the screen says the publish failed. The knowledge base is the client's authored
      record; the pack is a derived artefact of it, and a derived artefact must not be able
      to veto the thing it derives from. This is `route_inbound_numbers`' rule in
      `publish_agent`, for the same reason.
    * **Swallow.** Then a client who fixed a wrong price sees "published", the agent keeps
      quoting the old one out of the pack it already holds, and nothing anywhere says so.
      That is the silent success CLAUDE.md's quality bar refuses by name.
    * **What it does:** keep the OLD pointer (so the agent answers from the last pack that
      genuinely exists — stale, but coherent and provably the words of a real publish),
      fire `knowledge_pack_publish_failed`, and return None. The next publish or withdrawal
      of any source on this agent retries it from scratch; the pack is content-addressed,
      so the retry is free when nothing else changed.

    **A DATABASE FAILURE IS RE-RAISED AND IS NOT PART OF THAT POSTURE.** By the time
    SQLAlchemy raises, the caller's transaction is already aborted — every later statement
    in the publish will fail anyway — so catching it here would turn a clean rollback with
    a real traceback into an incomprehensible error at COMMIT, three functions later, about
    a statement nobody ran. Only the storage half is survivable, so only the storage half
    is survived.

    **THE OBJECT IS WRITTEN BEFORE THE POINTER COMMITS, AND THAT ORDER IS DELIBERATE.** If
    the caller's transaction rolls back after the store succeeded, an unreferenced pack
    stays in the bucket — immutable, content-addressed, a few hundred bytes, matched by the
    `knowledge-packs/` lifecycle rule, and re-used rather than re-written if that same
    corpus is ever published again. The other order would put a pointer to nothing in a
    column the call path trusts, which costs a live agent its knowledge.

    **AN EMPTY CORPUS STILL GETS A PACK AND A POINTER.** Withdrawing the last source
    publishes a pack with no entries rather than clearing the column, so "this client
    withdrew everything" and "this client has never written anything down" stay two states
    (`SessionConfig.knowledge_pack_sha256 = None` is only ever the second). The rejected
    alternative — NULL for an empty pack — saves one ~200-byte object and costs the worker
    the ability to tell those apart at all.
    """
    try:
        pack_id = await publish_pack(session, tenant_id=tenant_id, agent_id=agent_id)
    except SQLAlchemyError:
        raise
    except PackTooLargeError as exc:
        # ITS OWN ALERT, because the remedy is the client's corpus and not our storage: the
        # generic sentence below sends an operator to look at a bucket that is working. The
        # pointer stays where it is, which is the best available outcome — the agent answers
        # from the last pack that FITS rather than from a pack that cannot be fetched in
        # time, which would be `temporarily_unavailable` to every question on every call.
        alert(
            "CORE_LOGIC",
            "knowledge_pack_too_large",
            detail=(
                f"this agent's published knowledge builds a {exc.size}-byte in-call pack, "
                f"over the {exc.ceiling}-byte ceiling, so it was NOT stored and the agent "
                "keeps answering from the pack it last loaded. The voice worker fetches the "
                "whole pack while the phone rings under a fixed budget, so publishing this "
                "one would cost the agent its knowledge on every call. Withdraw or prune "
                "sources on this agent, or split the corpus across agents."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
        return None
    except Exception as exc:
        # Ids and OUR OWN sentence (hard rules 6 and the alerting contract): never the
        # store's body, which quotes the key, which names the tenant and the agent.
        alert(
            "CORE_LOGIC",
            "knowledge_pack_publish_failed",
            detail=(
                "a client's knowledge was published but the in-call knowledge pack could "
                "not be built or stored, so their agent keeps answering from the pack it "
                "last loaded — the correction they just made is live on every other "
                f"surface and not on the phone. Refusal: {exc.__class__.__name__}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
        return None

    await session.execute(
        text(_RECORD_PACK_SQL), {"sha": pack_id, "aid": agent_id, "tid": tenant_id}
    )
    return pack_id


#: The agents this tenant has whose pack COULD have been overtaken by a gloss, with the id
#: their `agents` row currently points at. The cheap half of the difference; `d.gloss IS NOT
#: NULL` is what makes it cheap and it is also what makes it exact FOR THIS CALLER: the only
#: thing the gloss sweep changes about a pack's contents is `PackEntry.gloss`, so an agent
#: with no glossed live chunk anywhere cannot have a pack this sweep made stale.
#:
#: **DISTINCT OVER THE PAIR IS ONE ROW PER AGENT**, because `knowledge_pack_sha256` is
#: functionally dependent on `agent_id` — the join is to the agent row, not to a chunk.
#:
#: `LIMIT` after `ORDER BY 1` so the bound is deterministic rather than whatever the planner
#: returned first: a tenant over the ceiling gets the same prefix every tick, which is a
#: starvation the caller's constant is sized to make unreachable and which would otherwise be
#: an intermittent one nobody could reproduce.
_GLOSSED_AGENTS_SQL: Final = f"""
SELECT DISTINCT g.agent_id, a.knowledge_pack_sha256
FROM (SELECT c.agent_id {_LIVE_CHUNKS_FROM} AND d.gloss IS NOT NULL) g
JOIN agents a ON a.id = g.agent_id AND a.tenant_id = :tid
ORDER BY 1
LIMIT :limit
"""


def implied_digest(tenant_id: UUID, agent_id: UUID, entries: tuple[PackEntry, ...]) -> str:
    """The pack id this corpus implies on THIS deployment - the one spelling, shared.

    Two callers need the same sentence and must never be able to answer it differently:
    `agents_with_stale_packs` asks it to decide whether the gloss sweep owes an agent a
    rebuild, and `kb/delivery.py` asks it to tell a client whether what they published is
    what their agent is answering out of. A second spelling would put the sweep and the
    screen into disagreement - a client told "live" about an agent the sweep keeps
    rebuilding, or the reverse - so the comparison is written once.

    It is NOT `build_pack`'s digest with the store removed: `build_pack` BUYS vectors
    (`embed_entries`) because it is about to write the bytes. This is the read-only twin,
    and the encoder is PREDICTED rather than bought - `pack_embedding_declaration` reads
    this deployment's two free pre-flights and nothing else. Calling `embed_entries` from
    either caller would spend a hosted encoder to re-derive a name that is a property of
    our own settings, and would spend it hardest on the agents that turn out to be current.

    The declaration is inside the hash deliberately (`KnowledgePack.digest`): a pack
    embedded under a different encoder IS a different pack, so a deployment that changed
    encoders correctly reads as stale everywhere at once.
    """
    model = pack_embedding_declaration(entries)
    return KnowledgePack.digest(
        tenant_id,
        agent_id,
        entries,
        embedding_model=model,
        embedding_dimensions=declared_dimensions(model),
    )


async def agents_with_stale_packs(
    session: AsyncSession, *, tenant_id: UUID, limit: int
) -> list[UUID]:
    """Agents whose recorded pack id is not the one their live knowledge now implies.

    WHAT THIS IS FOR. `workers/kb_gloss.py` writes `kb_documents.gloss` on a half-hourly
    sweep, and the normal ordering — a reviewer approves and publishes in one sitting —
    publishes BEFORE that sweep ever runs. A pack is frozen at publish by construction, so
    the English half of every entry landed after the artefact the agent answers out of had
    already been sealed, and nothing reopened it until the client happened to publish or
    withdraw something else on that agent. Feed the result to `refresh_published_pack`.

    **THE DIFFERENCE IS THE DIGEST, AND THAT IS THE LOAD-BEARING CHOICE.** The sweep could
    hand over the document ids it just glossed; `kb/service.refresh_projection_keys` argues
    at length why a worklist is the wrong instrument one table over, and every word of it
    applies here with one more reason on top. A pack is CONTENT-ADDRESSED: the id in
    `agents.knowledge_pack_sha256` is a hash of exactly the entries `read_entries` returns,
    so "is this agent's pack stale?" has a total answer that costs one indexed read and no
    bookkeeping. That answer converges on rows nobody told us about — a publish that raced a
    gloss commit, every agent published before this function existed — and, unlike a
    worklist, it does NOT go quiet when the rebuild fails: a storage outage leaves the
    pointer where it was, so the digest still differs and the next tick selects the same
    agent. A worklist would have consumed the id and moved on.

    **THE DIGEST HASHES THE ENCODER, SO THE SCAN HAS TO NAME ONE — AND NAMING NONE WAS A
    BILL WAITING FOR THE DENSE ARM TO BE SWITCHED ON.** `KnowledgePack.digest` hashes
    `embedding_model` deliberately (a pack embedded under a different encoder IS a different
    pack, or a warm container serves one model's vectors for another's id). This scan called
    it with the default `embedding_model=None` while `build_pack` passes the real encoder, so
    the moment an operator attests the embedding price every glossed agent's recorded pointer
    would stop matching the digest computed here — for ever. The sweep would select every one
    of them on every tick, rebuild, re-embed, and arrive at the same bytes: an embedding
    invoice per agent per half hour for no change at all. Dormant today only because
    `pack_vectors.embed_entries` is a no-op until that attestation lands (hard rule 7).

    **SO THE ENCODER IS PREDICTED FROM CONFIGURATION AND NEVER BOUGHT**
    (`pack_vectors.pack_embedding_declaration`, which argues the prediction's one asymmetry).
    Both halves of the comparison then mean the same thing — "the pack this corpus implies on
    this deployment" — and the four states it has to separate are each answered by one
    equality: a changed corpus moves the entries and the digest with them; a changed encoder
    moves the declaration and the digest with it, which is the property the model-in-the-hash
    exists for and the one a fix must not trade away; an unchanged corpus under an unchanged
    encoder matches, so the tick buys and stores nothing; and an agent with no pack at all
    holds NULL, which no digest equals.

    **REJECTED: calling `embed_entries` here so the digest matches.** It is the shortest
    patch and it is the defect with extra steps — it spends a hosted encoder per candidate
    agent per tick to re-derive a name that is a property of our own settings, and it spends
    it hardest on exactly the agents that turn out not to be stale.

    **REJECTED: fetching the STORED pack and reading its declared `embedding_model`.** It
    compares like with like, and it costs an object-store GET per glossed agent per tick —
    the round trip `MAX_PACK_AGENTS_PER_TENANT` is sized on the assumption that only an agent
    whose digest actually moved pays. Worse, it cannot answer the state it was reached for:
    re-hashing with whatever the stored pack declared makes the encoder match BY
    CONSTRUCTION, so a deployment that changed encoders would never rebuild and every
    client's corpus would stay on the old one silently. Making it correct means asking for
    the expected encoder anyway — the same prediction, plus a GET.

    **REJECTED: a marker column, or comparing `kb_documents.updated_at` against
    `agents.updated_at`.** The timestamp comparison is the cheaper-looking one and it is
    WRONG in the silent direction: `agents.updated_at` moves for a voice change, a call-cap
    change and nine other reasons, so any unrelated edit landing after the gloss pushes the
    agent out of the candidate set permanently. A new column would work and buys nothing the
    digest does not already give — the repo would then hold two answers to "which pack does
    this corpus imply", which is the drift the quality bar calls a defect even while both
    agree.

    **IT REUSES `read_entries` AND `KnowledgePack.digest` RATHER THAN HASHING IN SQL.** A
    `sha256` expression over a canonical JSON built in Postgres would be a second spelling of
    the pack id, and the failure mode of a second spelling here is a rebuild loop: every tick
    would disagree with the artefact and re-store a pack that had not changed.

    Run on the CALLER's tenant-scoped session (hard rule 1); `tenant_id` is re-stated on both
    halves on top of RLS for `_LIVE_CHUNKS_FROM`'s reason. READ-ONLY and lock-free, so the
    caller can scan a tenant without holding anything across the storage round trips that
    the refresh of a stale agent then costs.

    **WHAT LOCK-FREE MEANS HERE, STATED SO NOBODY READS IT AS A GUARANTEE.** Every id
    returned is a HINT about an instant that has already passed: a publish committing after
    the scan makes an agent named here no longer stale, or an agent not named here newly so.
    That is harmless for the second (the next tick catches it — the selection is a difference,
    not a worklist) and it is NOT harmless for the first, because `refresh_published_pack`
    would then re-point the agent at a pack frozen from the corpus the publish replaced. The
    serialization for that belongs to the caller's REFRESH transaction and cannot be bought
    here — an advisory lock is released at the end of the transaction that took it, and this
    scan's transaction is over before the first refresh begins. `workers/kb_gloss.py` takes
    `kb/service.try_lock_agent_publishes` per agent, in the transaction that does the work.

    `limit` is the caller's, because the budget belongs to the tick.
    """
    candidates = (
        await session.execute(text(_GLOSSED_AGENTS_SQL), {"tid": tenant_id, "limit": limit})
    ).all()
    stale: list[UUID] = []
    for row in candidates:
        agent_id = UUID(str(row[0]))
        entries = await read_entries(session, tenant_id=tenant_id, agent_id=agent_id)
        if implied_digest(tenant_id, agent_id, entries) != row[1]:
            stale.append(agent_id)
    return stale


__all__ = [
    "MAX_PACK_BYTES",
    "PackTooLargeError",
    "agents_with_stale_packs",
    "build_pack",
    "implied_digest",
    "publish_pack",
    "read_entries",
    "refresh_published_pack",
]

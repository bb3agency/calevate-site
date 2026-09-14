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

**VERSION 1 CARRIES NO VECTORS AND THIS MODULE MUST NOT ADD ONE.** `kb_chunks.embedding`
is right there in the table this reads and is deliberately not projected: the dense arm
needs a query encoder in the worker, and `knowledge_pack.py:25-43` is the measurement that
rules one out at 1-2 threads against a 100ms turn. Adding vectors is a
`PACK_FORMAT_VERSION` bump, not a column somebody slips into the SELECT.

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

⚠ **A SUPERSEDED PACK KEEPS THE WORDS THAT WERE IN IT, AND NOTHING DELETES IT BUT THAT
CEILING.** A client who removes one document gets a new pack without it; the previous pack
stays at its own key, holding the approved text as it was — measured, not assumed: no path
in `apps/workers/` or `apps/api/compliance/` deletes anything under this prefix (the only
function that names it is `storage.store_knowledge_pack`). That is tolerable because a pack
holds a BUSINESS's own published knowledge and no data principal's data — no number, no
transcript, no caller — which is why `scripts/check_erasure_coverage` has nothing to reach
here. It is NOT tolerable silently, so: a tenant offboarding does not currently reach these
objects, and the reference-aware sweep named below is where both this and the space belong.

**`knowledge-packs/` NOW CARRIES AN OBJECT-LIFECYCLE RULE** — `infra/object-lifecycle/
policy.json`, `knowledge-packs-growth-ceiling-not-retention`, pinned by
`tests/object_lifecycle_test.py`. It is a growth CEILING and not a retention mechanism, and
the rule's own comment in `apply_lifecycle.py` argues why nothing shorter is safe: an
expiry is measured from an object's creation, so any ceiling low enough to reclaim space
would eventually delete the live pack of the best-behaved client on the platform — the one
whose price list has not needed correcting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.ownership import assert_visible

log = get_logger(__name__)

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
            text=row[3],
            gloss=row[4],
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

    `built_at` is stamped AFTER the read, and is deliberately outside the content hash
    (`knowledge_pack.py:120-123`), so a rebuild that changes nothing keeps its id and every
    warm container holding it stays warm.
    """
    await assert_visible(session, "agent", agent_id)
    entries = await read_entries(session, tenant_id=tenant_id, agent_id=agent_id)
    return KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(tenant_id, agent_id, entries),
        built_at=datetime.now(UTC),
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

    await store_knowledge_pack(key=key, data=pack.model_dump_json().encode())
    log.info(
        "knowledge_pack_published",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "pack_id": pack.content_sha256,
            "entries": len(pack.entries),
            # How much of the corpus carries a retrieval key a Tenglish question can reach
            # (`kb/gloss.py`). A count, so an operator can see a gloss sweep that never ran
            # without anybody reading a client's knowledge to find out.
            "glossed": sum(1 for entry in pack.entries if entry.gloss),
        },
    )
    return pack.content_sha256


#: Where the call path reads the pack id from. `IS DISTINCT FROM` so a republish that
#: changed nothing writes no row at all: the column is a pointer at an immutable object, so
#: re-stamping it with the value it already holds would move `updated_at` — the timestamp
#: every "when did this agent last change?" screen reads — for a change that did not happen.
#:
#: `tenant_id` is re-stated on top of RLS for `_ENTRIES_SQL`'s reason.
_RECORD_PACK_SQL: Final = """
UPDATE agents SET knowledge_pack_sha256 = :sha, updated_at = now()
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

    `limit` is the caller's, because the budget belongs to the tick.
    """
    candidates = (
        await session.execute(text(_GLOSSED_AGENTS_SQL), {"tid": tenant_id, "limit": limit})
    ).all()
    stale: list[UUID] = []
    for row in candidates:
        agent_id = UUID(str(row[0]))
        entries = await read_entries(session, tenant_id=tenant_id, agent_id=agent_id)
        if KnowledgePack.digest(tenant_id, agent_id, entries) != row[1]:
            stale.append(agent_id)
    return stale


__all__ = [
    "agents_with_stale_packs",
    "build_pack",
    "publish_pack",
    "read_entries",
    "refresh_published_pack",
]

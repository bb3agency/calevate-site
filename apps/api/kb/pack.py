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
projection and the source it projects. See `_ENTRIES_SQL` for why both are checked.

**VERSION 1 CARRIES NO VECTORS AND THIS MODULE MUST NOT ADD ONE.** `kb_chunks.embedding`
is right there in the table this reads and is deliberately not projected: the dense arm
needs a query encoder in the worker, and `knowledge_pack.py:25-43` is the measurement that
rules one out at 1-2 threads against a 100ms turn. Adding vectors is a
`PACK_FORMAT_VERSION` bump, not a column somebody slips into the SELECT.

⚠ **`knowledge-packs/` HAS NO OBJECT-LIFECYCLE RULE YET.** Every other prefix this product
writes carries a growth ceiling in `infra/object-lifecycle/policy.json`; this one does not,
so a client republishing knowledge daily accumulates one small object per distinct corpus
for ever. It is NOT fixed here because that file is the only resource `infra/terraform`
manages, and CLAUDE.md forbids touching `infra/` prod without plan output in the PR — which
nobody can produce from this container. It is an infra change with an owner, not an
oversight. Nothing expires these objects in the meantime.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.db.ownership import assert_visible

log = get_logger(__name__)

#: One agent's live, published knowledge, joined to the text and the gloss it projects.
#:
#: **BOTH `is_active` FLAGS, AND THE SECOND ONE IS NOT BELT-AND-BRACES.** The projection's
#: flag is converged onto the source's by `kb/service.py:1966-1972` (`_DEACTIVATE_SQL`),
#: which runs on the NEXT publish for that agent — so between a source going inactive by
#: some other path and that publish, `c.is_active` can be true over an archived source. A
#: pack is a frozen artefact a container caches for the life of a session; baking a
#: superseded price list into one is not a query that self-corrects on the next tick.
#: `s.is_active` is what `kb/service.active_knowledge` calls live and it is the only
#: definition this module accepts.
#:
#: **`s.version`, NOT `c.version`, FOR `PackEntry.document_version`.** They are equal by
#: construction — `_PROJECT_SQL` writes `s.version` into the projection
#: (`kb/service.py:1951-1958`) — and when a projection is stale the source row is the one
#: that says which revision a caller was actually answered from. Reading the truth costs
#: nothing here because the join is already made for `s.is_active`.
#:
#: `tenant_id` is re-stated on top of RLS for the reason `retrieval/pgvector.py` re-states
#: it: RLS cannot see a caller passing tenant A's id on a session opened for tenant B as a
#: mistake, and that caller would otherwise get B's chunks under A's name.
#:
#: No `ORDER BY`: the canonical order is `KnowledgePack.digest`'s and is applied in Python
#: below, so there is exactly one place that decides it.
_ENTRIES_SQL: Final = """
SELECT c.id, c.document_id, s.version, d.content, d.gloss
FROM kb_chunks c
JOIN kb_sources s ON s.id = c.source_id
JOIN kb_documents d ON d.id = c.document_id
WHERE c.tenant_id = :tid AND c.agent_id = :aid
  AND c.is_active AND s.is_active
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


__all__ = ["build_pack", "publish_pack", "read_entries"]

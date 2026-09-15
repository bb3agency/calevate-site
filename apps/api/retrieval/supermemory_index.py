"""The WRITE half of box 3: what reaches Supermemory, what leaves it, and what proves it.

The adapter beside this one could SEARCH a store nothing filled. This is the other half of
`docs/PIPECAT-MIGRATION.md` §6 step 15 — ingestion at publish, withdrawal at withdraw, a
tenant purge at erasure, and a difference-driven sweep that makes the vendor's content agree
with `kb_chunks` again after any of the three failed.

--------------------------------------------------------------------------------
THE LEDGER, AND WHY THE STORE IS NOT ASKED WHAT IT HOLDS
--------------------------------------------------------------------------------
`kb_index_documents` records, per published chunk, the digest of the text box 3 last
ACCEPTED. It is the whole design, and three properties fall out of it that no other shape
gives:

1. **A difference instead of a worklist.** "What should box 3 hold?" is `kb_chunks`; "what
   does it hold?" is this ledger; the sweep sends the difference. A publish that failed on
   the vendor leaves the difference standing, so the next tick selects exactly the same
   rows — the property `kb/service.refresh_projection_keys` and
   `kb/pack.agents_with_stale_packs` are both built on, and the reason neither goes quiet
   when its work fails. A worklist would have consumed the event and moved on.
2. **Orphan collection.** The ledger row carries `document_id` as a plain column with NO
   foreign key, deliberately: `kb_chunks` rows CASCADE away when retention deletes a
   `kb_sources` row (`workers/retention._KB_EXPIRE_SQL`), and a tombstone that cascaded with
   them would take with it the only record that box 3 still holds the document. A ledger row
   whose chunk is gone IS the instruction to withdraw it.
3. **An erasure that enumerates rather than trusts.** `deletion_proof` is False for this
   provider (§8.4: we cannot check their delete), so the purge sends the tenant tag AND
   empties the rows that say what we sent. The tag rests on an ASSUMED reading of their
   delete surface; the ledger rests on what we recorded sending.

**REJECTED: sync state as columns on `kb_chunks`** (`embed_state`'s shape, one table over).
It is the tidier diff and it loses property 2 outright — the state dies with the row whose
content is still in the vendor. **REJECTED: asking box 3 to list what it holds.** That is a
fourth assumed endpoint, it costs a paged vendor scan per tenant per tick, and against a
single-tenant local build it would answer with every tenant's documents at once.

--------------------------------------------------------------------------------
FAILURE POSTURE: THE PACK'S, UNCHANGED, AND FOR THE PACK'S REASON
--------------------------------------------------------------------------------
`kb/pack.refresh_published_pack` keeps the old pointer, alarms, and returns None when
storage refuses — because a derived artefact must not veto the authored record it derives
from. Box 3 is derived twice over (`kb_chunks` is the projection; this is a projection of
the projection), so `refresh_indexed_source` takes exactly that posture: a client's publish
COMMITS, the ledger is not advanced, `supermemory_index_sync_failed` fires, and the sweep
converges. The two alternatives are the same two that were rejected there — raising means a
box on somebody else's clock can fail a client's publish, and swallowing means a withdrawn
price list stays searchable with nothing anywhere saying so.

**THE ERASURE IS THE ONE PATH THAT DOES NOT DEGRADE.** `purge_tenant_index` RAISES when box
3 will not take the delete, which rolls `execute_tenant_erasure` back whole (`deleted_at`
stays NULL, arq retries) — because the output of that worker is a CERTIFICATE. A certificate
issued over content we did not remove is the one failure this repository treats as
unrecoverable, and DPDP §8/§12 do not have a degraded mode.

--------------------------------------------------------------------------------
HARD RULE 7
--------------------------------------------------------------------------------
Ingestion costs money twice over: the embedding box 3 buys on our account (§8.3, it must not
be local) and the vendor's own LLM extraction per document (§10.4). So it is metered per
`usage_event` like the search side, through the SAME pre-flight —
`supermemory.search_is_billable()`, which reads the one model an operator named and asks
`billing/rates.llm_price_is_billable` whether a price exists that hard rule 7 will stand
behind. **No price, no writes**: `supermemory_indexer` returns None and the publish path
does nothing at all, rather than filling a store whose cost cannot reach `unit_cost_paid`.
No figure is invented and none is wired — the Gemini embedding price is UNVERIFIED in this
tree (§10.4) and becomes billable when an operator enters their own invoice figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.retrieval.supermemory import (
    HttpxTransport,
    SupermemoryClient,
    search_is_billable,
)
from apps.api.retrieval.supermemory_wire import (
    ASSUMED_CONTRACT,
    SupermemoryWireMismatchError,
    TenantScope,
    WireContract,
)

log = get_logger(__name__)

#: `usage_events.meta.feature` for one document written into box 3. Its own name beside
#: `ASSIST_FEATURE_SUPERMEMORY_SEARCH` for that constant's reason: ingestion and search buy
#: different things (an embedding plus the vendor's extraction, against an embedding), and an
#: operator deciding whether box 3 pays for itself cannot do it from a merged number.
ASSIST_FEATURE_SUPERMEMORY_INGEST: Final = "supermemory_ingest"

#: Documents written or withdrawn in ONE publish-path call. A publish is one source, and a
#: source is at most a few hundred chunks (`kb/service.MAX_CHUNK_CHARS` over a 50-page
#: document); this is a ceiling against a pathological one rather than a rate, and the
#: remainder is not lost — it still differs, so the sweep takes it.
MAX_DOCUMENTS_PER_SOURCE: Final = 500

#: The same ceiling for one TENANT on one sweep tick. `kb_gloss.MAX_REKEY_ROWS_PER_TENANT`'s
#: reasoning with money in it: each unit here is a vendor round trip and a metered purchase,
#: so the bound is the tick's spend as much as its duration.
MAX_DOCUMENTS_PER_TICK: Final = 100

#: THE ONE SPELLING OF "what box 3 was sent", used by the statement that SELECTS stale rows
#: and by the value the ledger records — `kb/service._TSV_SQL`'s rule, for its reason: a
#: difference whose two sides are spelled twice is a sweep that re-sends a settled corpus for
#: ever. Text AND gloss, because both are sent (the gloss is what makes a Telugu chunk
#: findable from a Tenglish question — `refresh_projection_keys`), so a gloss that lands
#: after a publish MOVES this digest and the sweep re-sends the document. `sha256()` is
#: Postgres's own (11+), not pgcrypto, so this needs no extension.
_CONTENT_SHA_SQL: Final = (
    "encode(sha256(convert_to(d.content || coalesce(d.gloss, ''), 'utf8')), 'hex')"
)

#: The live chunks box 3 does not hold at the digest it should. `LEFT JOIN` + `IS NULL` is
#: the "never sent" arm and the `<>` is the "sent, then the text or the gloss moved" arm —
#: one statement, because they are one question. Ordered so a truncated scan hands the next
#: tick the same prefix rather than a planner's whim (`_GLOSSED_AGENTS_SQL`'s reason).
#:
#: `tenant_id` is restated on every half on top of RLS for `kb/service.project_chunks`'
#: reason: the one mistake RLS cannot see is a caller passing tenant A's id on B's session.
_STALE_SQL: Final = f"""
SELECT c.document_id, c.agent_id, c.source_id, c.version, d.content, s.name,
       {_CONTENT_SHA_SQL} AS sha
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
JOIN kb_sources s ON s.id = c.source_id
LEFT JOIN kb_index_documents x ON x.document_id = c.document_id AND x.tenant_id = :tid
WHERE c.tenant_id = :tid AND c.is_active
  AND (:sid::uuid IS NULL OR c.source_id = :sid::uuid)
  AND (x.document_id IS NULL OR x.content_sha256 <> {_CONTENT_SHA_SQL})
ORDER BY c.document_id
LIMIT :limit
"""

#: The mirror image: documents box 3 holds that our corpus no longer has live. Three causes,
#: all real — a source withdrawn (`kb_chunks.is_active` false), a source deleted by retention
#: (the row is gone entirely, which is why the ledger holds no FK to it), and a document
#: whose ingest we recorded and whose chunk a later publish replaced.
_ORPHAN_SQL: Final = """
SELECT x.document_id FROM kb_index_documents x
LEFT JOIN kb_chunks c ON c.document_id = x.document_id AND c.is_active
WHERE x.tenant_id = :tid AND (:sid::uuid IS NULL OR x.source_id = :sid::uuid)
  AND c.document_id IS NULL
ORDER BY x.document_id
LIMIT :limit
"""

#: What box 3 accepted. `ON CONFLICT (document_id)` for `_PROJECT_SQL`'s reason one table
#: over: a republish must be idempotent in the DATABASE and not in a read-then-write.
_RECORD_SQL: Final = """
INSERT INTO kb_index_documents
  (id, tenant_id, agent_id, source_id, document_id, content_sha256, synced_at)
VALUES (:id, :tid, :aid, :sid, :did, :sha, now())
ON CONFLICT (document_id) DO UPDATE
SET content_sha256 = EXCLUDED.content_sha256, agent_id = EXCLUDED.agent_id,
    source_id = EXCLUDED.source_id, synced_at = now(), updated_at = now()
"""

_FORGET_SQL: Final = """
DELETE FROM kb_index_documents WHERE tenant_id = :tid AND document_id = ANY(:dids)
"""

#: THE ERASURE ARM. Unconditional over the tenant for
#: `retrieval/caller_erasure.erase_tenant_vectors`' reason: when the subject is "all of them"
#: there is nothing to match on. `tenant_id` is restated on top of RLS for the statements
#: above's reason.
_PURGE_SQL: Final = "DELETE FROM kb_index_documents WHERE tenant_id = :tid"

#: How many documents this tenant still has recorded in box 3. Read by the erasure when no
#: credential is configured, which is the one state where "nothing to do" and "an obligation
#: nothing can discharge" look identical from the outside.
_STRANDED_SQL: Final = "SELECT count(*) FROM kb_index_documents WHERE tenant_id = :tid"


@dataclass(frozen=True, slots=True)
class IndexSyncCounts:
    """What one pass actually moved, in the two directions a reader must not merge.

    `ingested` is content a client can now find; `withdrawn` is content they no longer can.
    A single total would let either be zero without anybody noticing — `CallerErasureCounts`
    makes the same argument about the same kind of number.
    """

    ingested: int = 0
    withdrawn: int = 0

    @property
    def total(self) -> int:
        return self.ingested + self.withdrawn


class SupermemoryIndexer:
    """Ingest, withdraw and purge — the write side of one tenant-scoped session.

    **EVERY METHOD THAT REACHES THE WIRE GOES THROUGH `SupermemoryClient`, WHOSE SIGNATURES
    TAKE A `TenantScope` FIRST** and are asserted to
    (`tests/retrieval_supermemory_test.py::test_no_wire_method_can_be_called_without_a_
    tenant_scope`). Nothing here builds a body, so there is no path from this module to the
    vendor that could omit a scope.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: SupermemoryClient,
        contract: WireContract = ASSUMED_CONTRACT,
    ) -> None:
        self._session = session
        self._client = client
        self._contract = contract

    async def sync(
        self, *, tenant_id: UUID, source_id: UUID | None = None, limit: int
    ) -> IndexSyncCounts:
        """Make box 3 agree with this tenant's live chunks. THE ONE CONVERGING FUNCTION.

        `source_id` narrows it to one source, which is what the publish and withdrawal paths
        pass; `None` is the sweep. **It is the same code either way, deliberately** — a
        publish is a sweep that knows where to look, and a second "publish-only" writer is
        where the two would drift about what a synced document IS (the quality bar's
        one-way-per-problem rule, and `refresh_projection_keys`' REJECTED alternative).

        WITHDRAWALS FIRST, INGESTS SECOND. A republish that supersedes a document leaves the
        old row orphaned and mints a new one; doing the delete first means the two never
        coexist in the index, so a caller cannot be answered from both versions of a price.
        """
        withdrawn = await self._withdraw_orphans(
            tenant_id=tenant_id, source_id=source_id, limit=limit
        )
        ingested = await self._ingest_stale(
            tenant_id=tenant_id, source_id=source_id, limit=limit
        )
        counts = IndexSyncCounts(ingested=ingested, withdrawn=withdrawn)
        if counts.total:
            # Ids and counts (hard rule 6). Never a chunk, never a source name.
            log.info(
                "supermemory_index_synced",
                extra={
                    "tenant_id": str(tenant_id),
                    "source_id": str(source_id) if source_id else None,
                    "ingested": counts.ingested,
                    "withdrawn": counts.withdrawn,
                },
            )
        return counts

    async def _ingest_stale(
        self, *, tenant_id: UUID, source_id: UUID | None, limit: int
    ) -> int:
        rows = (
            await self._session.execute(
                text(_STALE_SQL),
                {"tid": tenant_id, "sid": str(source_id) if source_id else None, "limit": limit},
            )
        ).all()
        ingested = 0
        for document_id, agent_id, chunk_source_id, version, content, name, sha in rows:
            body = await self._client.ingest(
                # The scope is minted HERE, from the row, so the tags on the document and
                # the tenant it was published under cannot disagree.
                TenantScope.for_publish(tenant_id=tenant_id, agent_id=UUID(str(agent_id))),
                document_id=UUID(str(document_id)),
                content=content,
                source_id=UUID(str(chunk_source_id)),
                source_label=str(name),
                document_version=int(version),
            )
            # THE LEDGER MOVES ONLY AFTER THE VENDOR TOOK IT. A row written first would
            # claim box 3 holds a document it refused, and the difference — the one thing
            # that makes a retry happen — would be gone.
            await self._session.execute(
                text(_RECORD_SQL),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "sid": chunk_source_id,
                    "did": document_id,
                    "sha": sha,
                },
            )
            await self._meter(body, tenant_id=tenant_id)
            ingested += 1
        return ingested

    async def _withdraw_orphans(
        self, *, tenant_id: UUID, source_id: UUID | None, limit: int
    ) -> int:
        rows = (
            (
                await self._session.execute(
                    text(_ORPHAN_SQL),
                    {
                        "tid": tenant_id,
                        "sid": str(source_id) if source_id else None,
                        "limit": limit,
                    },
                )
            )
            .scalars()
            .all()
        )
        document_ids = [UUID(str(row)) for row in rows]
        if not document_ids:
            return 0
        # ONE CALL FOR THE BATCH, unlike the ingest: a delete buys nothing and carries no
        # text, so there is no partial-failure ambiguity to resolve — either the batch was
        # accepted and every ledger row goes, or it was not and every one of them stays
        # selectable.
        await self._client.forget(TenantScope.for_tenant(tenant_id), document_ids=document_ids)
        await self._session.execute(
            text(_FORGET_SQL), {"tid": tenant_id, "dids": [str(d) for d in document_ids]}
        )
        return len(document_ids)

    async def purge(self, *, tenant_id: UUID) -> int:
        """Everything of this tenant's, out of box 3. Returns the ledger rows removed.

        **BOTH ADDRESSES, AND THE ORDER IS THE POINT.** The vendor call goes first and it
        carries the tenant TAG with no ids, which is `delete_payload`'s scope-wide form; the
        ledger is emptied only after that call returned. If box 3 refuses, this raises with
        the ledger intact, `execute_tenant_erasure` rolls back whole, and the retry finds
        exactly the same work to do. Emptying our rows first would have destroyed the only
        record of what the vendor still holds — an erasure that makes itself unprovable.
        """
        await self._client.forget(TenantScope.for_tenant(tenant_id))
        removed = rowcount_of(await self._session.execute(text(_PURGE_SQL), {"tid": tenant_id}))
        log.info(
            "supermemory_index_purged",
            extra={"tenant_id": str(tenant_id), "documents": removed},
        )
        return removed

    async def _meter(self, body: dict[str, Any], *, tenant_id: UUID) -> None:
        """Record what one ingest cost, or say plainly that it could not be recorded.

        `supermemory.SupermemoryRetriever._meter`'s rule on the write side, and its two
        rejected alternatives transfer verbatim: a `0` would be a `usage_events` row
        asserting a document was embedded for free, and a count estimated from the text's
        length would be a number we invented reaching `unit_cost_paid`. **WHETHER THE VENDOR
        REPORTS USAGE AT ALL IS UNKNOWN** — nobody here has read a response — so an absent
        block is an ERROR log and no row.
        """
        model = (get_settings().supermemory_embedding_model or "").strip()
        usage = body.get(self._contract.usage_key)
        tokens = usage.get(self._contract.usage_tokens_key) if isinstance(usage, dict) else None
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            log.error(
                "supermemory_ingest_unmetered",
                extra={
                    "tenant_id": str(tenant_id),
                    "model": model,
                    "usage_present": usage is not None,
                },
            )
            return
        await record_ai_assist_usage(
            self._session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=tokens,
            # An embedding has no output half, and the vendor's extraction pass is not
            # separately reported — `retrieval/embedding.embed_query_vector` says the same
            # of its own block: 0 is the truth about what this response accounted for.
            tokens_out=0,
            model=model,
            feature=ASSIST_FEATURE_SUPERMEMORY_INGEST,
        )


def supermemory_indexer(session: AsyncSession) -> SupermemoryIndexer | None:
    """The configured writer, or None with the reason logged. **The one constructor.**

    `supermemory.supermemory_t3`'s four preconditions, asked the same way and through the
    same pre-flight function, because they are the same four facts: a deployment that may not
    QUERY box 3 must not FILL it either. Hard rule 7 is the one that matters here — an
    ingest whose price nobody attested is spend with no `unit_cost_paid` to put it in.
    """
    settings = get_settings()
    base_url = (settings.supermemory_base_url or "").strip()
    api_key = (settings.supermemory_api_key or "").strip()
    billable = search_is_billable()
    if not base_url or not api_key or not billable:
        log.info(
            # INFO and not ERROR, unlike the retriever's: every deployment that has not
            # adopted box 3 takes this branch on every publish, and `get_retriever` already
            # says the same thing at ERROR once per question. A publish path that alarmed on
            # a store nobody configured would train an operator to ignore the alarm.
            "supermemory_index_unconfigured",
            extra={
                "base_url": bool(base_url),
                "credential": bool(api_key),
                "model": bool((settings.supermemory_embedding_model or "").strip()),
                "priced": billable,
            },
        )
        return None
    return SupermemoryIndexer(
        session, client=SupermemoryClient(HttpxTransport(base_url=base_url, api_key=api_key))
    )


async def refresh_indexed_source(
    session: AsyncSession, *, tenant_id: UUID, source_id: UUID
) -> IndexSyncCounts | None:
    """Push one source's published chunks into box 3 and withdraw what it superseded.

    **THE PUBLISH PATH'S ENTRY POINT, AND IT CANNOT FAIL A PUBLISH** —
    `kb/pack.refresh_published_pack`'s posture, reused rather than re-argued, because the
    artefact is derived in exactly the same sense. A vendor outage keeps the ledger where it
    was (so the difference stands and the sweep re-selects the same documents), fires
    `supermemory_index_sync_failed`, and returns None. The client's knowledge is live on
    every surface that matters: `kb_chunks` answers dashboard search through the Postgres
    fallback, the pack answers the phone, and box 3 catches up.

    **A DATABASE FAILURE IS RE-RAISED AND IS NOT PART OF THAT POSTURE**, for the pack's
    reason: by the time SQLAlchemy raises, the caller's transaction is already aborted, so
    catching it here would turn a clean rollback into an incomprehensible error at COMMIT.
    Only the vendor half is survivable, so only the vendor half is survived.
    """
    indexer = supermemory_indexer(session)
    if indexer is None:
        return None
    try:
        return await indexer.sync(
            tenant_id=tenant_id, source_id=source_id, limit=MAX_DOCUMENTS_PER_SOURCE
        )
    except SQLAlchemyError:
        raise
    except Exception as exc:
        alert(
            "CORE_LOGIC",
            "supermemory_index_sync_failed",
            # Ids and OUR OWN sentence (hard rule 6 and the alerting contract): never the
            # vendor's body, which quotes the document, which is the client's own prose.
            detail=(
                "a client published or withdrew knowledge and the search index could not be "
                "brought into line with it, so dashboard search over that source answers "
                "from the previous state until a later sweep succeeds. Their agent and "
                f"their screens are unaffected. Refusal: {exc.__class__.__name__}."
            ),
            tenant_id=str(tenant_id),
            source_id=str(source_id),
        )
        return None


async def purge_tenant_index(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Remove everything of this tenant's from box 3. **RAISES rather than degrading.**

    The erasure arm, called from `workers/retention.execute_tenant_erasure` and reachable by
    `scripts/check_erasure_coverage.py`, which walks the SQL of the modules it lists. §8.4
    kept `kb_documents` ours precisely so a DPDP erasure is provable in our own Postgres;
    this is the second copy that decision created, and the obligation follows the copy.

    **THE THREE STATES, AND NONE OF THEM IS SILENT.**

    * Box 3 configured: the tag-wide delete goes, the ledger is emptied, and the count is on
      the certificate. What the certificate may NOT say is that the removal was verified —
      `deletion_proof` is False for this provider and the certificate's wording says so.
    * Box 3 not configured and the ledger empty: nothing was ever written, so nothing is
      owed. Returns 0, which is every deployment that has not adopted box 3.
    * Box 3 not configured and the ledger NOT empty: content was written by a deployment
      that has since dropped the credential, and no code path can reach it. This RAISES and
      alarms, because the alternative is a certificate covering documents nobody can delete.
    """
    indexer = supermemory_indexer(session)
    if indexer is not None:
        return await indexer.purge(tenant_id=tenant_id)
    stranded = int(
        (await session.execute(text(_STRANDED_SQL), {"tid": tenant_id})).scalar_one()
    )
    if not stranded:
        return 0
    alert(
        "WORKER_TERMINAL",
        "supermemory_index_purge_failed",
        detail=(
            "a tenant erasure cannot remove this account's documents from the search index: "
            "rows record that content was written there and this deployment has no "
            "credential for it, so nothing can address the copy. Nothing was erased and no "
            "certificate was issued."
        ),
        tenant_id=str(tenant_id),
        documents=str(stranded),
    )
    raise RuntimeError(
        f"tenant erasure cannot reach {stranded} indexed document(s): box 3 is unconfigured"
    )


#: The transport failures a caller of this module survives, spelled once. Identical to the
#: set `supermemory.SupermemoryRetriever.retrieve` catches, and for the identical reason: an
#: unreachable host and a body our guessed contract cannot describe are one event.
VENDOR_FAILURES: Final = (httpx.HTTPError, TimeoutError, SupermemoryWireMismatchError)


__all__ = [
    "ASSIST_FEATURE_SUPERMEMORY_INGEST",
    "MAX_DOCUMENTS_PER_SOURCE",
    "MAX_DOCUMENTS_PER_TICK",
    "VENDOR_FAILURES",
    "IndexSyncCounts",
    "SupermemoryIndexer",
    "purge_tenant_index",
    "refresh_indexed_source",
    "supermemory_indexer",
]

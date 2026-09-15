"""The sweep that makes box 3 agree with `kb_chunks` again — the third of its kind, on purpose.

WHAT WAS MISSING. `kb/service.publish_source` and `withdraw_source` push a source into the
external search index and pull it back out (`retrieval/supermemory_index.
refresh_indexed_source`), and that call CANNOT FAIL THE PUBLISH — a derived index must not
veto the authored record it derives from. So every failure of it is, by construction, a
divergence nobody is coming back for: the client's correction is live on every screen and
absent from dashboard search, or their retraction is live everywhere and still searchable in
box 3. There are three ordinary ways to get there and none of them is exotic.

* **Box 3 was down, or refused, when the publish ran.** §8.5 names three open upstream issues
  bearing on which release is safe to pin, all UNVERIFIED as to current state.
* **The English gloss landed afterwards.** `workers/kb_gloss.py` writes it on a half-hourly
  clock and the normal ordering publishes first, so the text we SENT is not the text the
  corpus now implies — the identical defect `refresh_projection_keys` closes for the sparse
  key and `agents_with_stale_packs` for the in-call pack, one store further out.
* **Retention DELETEd the source.** `_KB_EXPIRE_SQL` takes `kb_sources` and cascades through
  `kb_documents` to `kb_chunks`; box 3's copy is not a row in this database and does not go
  with them. That one has no publish event at all, ever.

--------------------------------------------------------------------------------
IT IS A DIFFERENCE, NOT A WORKLIST — AND THAT IS WHY IT IS THE SAME SHAPE AS ITS TWO SIBLINGS
--------------------------------------------------------------------------------
`kb/service.refresh_projection_keys` compares the stored `tsv` against the one the text
implies. `kb/pack.agents_with_stale_packs` compares `agents.knowledge_pack_sha256` against
the digest the live corpus implies. This compares `kb_index_documents.content_sha256` against
the digest the live chunk implies, and compares the ledger's rows against which chunks are
still live. Each of the three arguments the same three properties at length, and they hold
here for the same reasons:

1. **It converges on rows nobody told us about** — every document written before this sweep
   existed, every publish that raced a gloss commit, every source retention deleted.
2. **It does not go quiet when the work fails.** A tick that could not reach box 3 wrote no
   ledger row, so the difference still stands and the next tick selects the identical
   documents. A worklist would have consumed the id and moved on, which is precisely the
   failure mode of the publish-path call this sweep exists to backstop.
3. **A settled corpus costs nothing.** Two indexed reads per tenant and no vendor call.

**REJECTED: enqueueing a job per failed publish.** It is the obvious repair and it cannot
see two of the three causes above (a late gloss and a retention delete raise no event at
all), and it re-introduces the "consumed and forgotten" failure for the third.

**REJECTED: asking box 3 what it holds and diffing that.** It is a fourth ASSUMED endpoint
over an API nobody here has read, it costs a paged vendor scan per tenant per tick, and
against a single-tenant local build (§8.4) the answer would be every tenant's documents at
once — we would be reading other clients' rows to decide one client's work.

WHAT IT COSTS. Per tenant per tick: two indexed statements, then one vendor round trip per
document that actually differs, bounded by `MAX_DOCUMENTS_PER_TICK`. Each ingest is a metered
purchase (hard rule 7 — the embedding box 3 buys and the vendor's own extraction), which is
why that bound is a SPEND bound as much as a duration one, and why `supermemory_indexer`
refuses to exist at all until an operator has attested a price.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.retrieval.supermemory_index import (
    MAX_DOCUMENTS_PER_TICK,
    supermemory_indexer,
)
from apps.workers.kb_gloss import tenants_holding_knowledge

log = get_logger(__name__)

#: The minutes this sweep fires. Twice an hour, on minutes no other fleet-wide fan-out uses
#: — a property `settings.WALK_SHAPES` declares and `tests/job_registration_test.py` checks
#: as an equality, rather than one this comment asserts (the gloss sweep's own note came to
#: be wrong by enumerating the register in prose).
#:
#: AFTER THE GLOSS SWEEP (`:12`/`:42`) DELIBERATELY, and that is the only thing about the
#: choice that is not arbitrary: a gloss changes the text this sweep sends, so running
#: behind it means a newly glossed chunk is re-sent once with its English rather than once
#: without and once with — one metered purchase instead of two.
INDEX_SYNC_MINUTES: Final[frozenset[int]] = frozenset({19, 49})


async def sync_knowledge_index(ctx: dict[str, Any]) -> str:
    """One fleet-wide tick: bring every tenant's box 3 content back into line with `kb_chunks`.

    **A NO-OP ON EVERY DEPLOYMENT THAT HAS NOT ADOPTED BOX 3**, decided once at the top from
    configuration rather than per tenant: `supermemory_indexer` is the same constructor the
    publish path and the retriever ask, so there is no state in which this sweep writes to a
    store the rest of the system is not using.

    **PER TENANT, IN ITS OWN SESSION AND ITS OWN TRANSACTION**, which is `kb_gloss.py`'s
    shape and is load-bearing twice over: hard rule 1 (the sync runs on the caller's
    tenant-scoped session, so RLS is the scope, not a WHERE clause somebody remembered), and
    one tenant's unreachable box or poisoned document cannot roll back the work already
    committed for another.
    """
    tenants = await tenants_holding_knowledge()
    synced = 0
    ingested = 0
    withdrawn = 0
    for tenant_id in tenants:
        counts = await _sync_one_tenant(tenant_id)
        if counts is None:
            continue
        ingested += counts[0]
        withdrawn += counts[1]
        if counts[0] or counts[1]:
            synced += 1
    return f"tenants={len(tenants)} changed={synced} ingested={ingested} withdrawn={withdrawn}"


async def _sync_one_tenant(tenant_id: UUID) -> tuple[int, int] | None:
    """`(ingested, withdrawn)` for one tenant; None when nothing ran. Never raises.

    **IT MAY NOT SWALLOW SILENTLY**, `kb_gloss._rekey_one_tenant`'s rule and its reason: a
    divergence here is invisible from every screen — dashboard search keeps answering out of
    the Postgres fallback, one store short, and a withdrawn document keeps answering out of
    box 3. The publish path has a client in front of it; a timer has nobody, so the alarm IS
    the report. It shares `supermemory_index_sync_failed` with the publish path rather than
    minting a second code, because an operator's response is identical and the alert already
    says which tenant and which surface.

    **`attention` AND NOT A PAGE**, because the selection is difference-driven: a tick that
    failed leaves exactly the same documents selectable thirty minutes later.
    """
    try:
        async with tenant_session(tenant_id) as session:
            indexer = supermemory_indexer(session)
            if indexer is None:
                return None
            counts = await indexer.sync(tenant_id=tenant_id, limit=MAX_DOCUMENTS_PER_TICK)
            return counts.ingested, counts.withdrawn
    except Exception as failure:
        alert(
            "CORE_LOGIC",
            "supermemory_index_sync_failed",
            detail=(
                "the periodic sweep could not bring this account's external search index "
                "into line with their published knowledge, so dashboard search over the "
                "affected sources answers from the previous state — and anything they "
                "withdrew is still findable there — until a later tick succeeds"
            ),
            tenant_id=str(tenant_id),
            error=type(failure).__name__,
        )
        return None


__all__ = ["INDEX_SYNC_MINUTES", "sync_knowledge_index"]

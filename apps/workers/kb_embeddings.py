"""The embedding sweep: one vector beside every published knowledge chunk.

WHY A SWEEP AND NOT AN ENQUEUE FROM `kb.service.publish_source`. `workers/kb_gloss.py`
settled this argument for the sibling job on the same table and the argument is unchanged: a
cron that selects `embed_state = 'pending'` is SELF-HEALING in a way an enqueue is not — a
lost job, a provider outage, a row projected by the migration's backfill, and a row written
by a path nobody has invented yet all converge on the next tick with no reconciliation code.
An enqueue would need exactly that reconciliation to be trustworthy, which IS the sweep. And
timeliness costs nothing here because nothing BLOCKS on a vector: `kb_chunks.tsv` is written
in the publishing transaction, so a chunk is searchable by its sparse arm from the instant it
is published and simply gets better when this lands.

**AND THE GLOSS IS WHY THE ORDER MATTERS.** `kb_documents.gloss` is written by that other
sweep, on a different clock, and it is part of what gets embedded — the English rendering of
a Telugu chunk is the key that lets a Tenglish question find it (D-489). A chunk embedded
before its gloss arrives would carry a vector for half its content, so `_CLAIM_SQL` skips
chunks whose gloss is still `pending` and picks them up on a later tick. That is a delay
measured in half-hours on a corpus uploaded once, and it is the difference between the
retrieval quality D-489 measured and a silently worse one.

IDEMPOTENCY IS `kb_chunks.embed_state`, AND IT IS WHY THAT COLUMN EXISTS. `embedding IS
NULL` cannot distinguish "nobody has looked at this" from "we asked and the answer was
unusable", so a sweep keyed on the vector would re-buy the same refusal on every tick for
ever. Each chunk is claimed with `FOR UPDATE ... SKIP LOCKED` inside the transaction that
writes its result, so an overlapping tick, an arq retry or a redeploy skips a row another
worker holds rather than paying for it twice — and a crash mid-call rolls the claim back,
leaving the row `pending`. The state change and the `usage_events` row commit together:
an embedding we paid for and did not record is money off the books (hard rule 7).

THE SPEND CONTROLS, because this job costs real money on a timer and nothing above it says
no:

* **THE PRICE GATE, WHICH IS FIRST AND WHICH REFUSES RATHER THAN GUESSES.** Nothing is
  bought unless `billing/rates.llm_price_is_billable` already says a rupee figure for this
  model may reach `unit_cost_paid`. Without it `record_ai_assist_usage` raises AFTER the
  provider has been paid, the transaction rolls back, the chunk returns to `pending`, and
  the next tick buys the same vector to reach the same raise — an unpriced leg that spends
  for ever and records nothing. This repository has read no vendor page publishing an
  embedding price (`platform.openai.com` and `azure.microsoft.com` are both egress-blocked
  here, measured 1 Sep 2026), so no figure is invented: an operator enters theirs from their
  own invoice and until they do this sweep does nothing and says so.
* `MAX_CHUNKS_PER_TICK` — the fleet-wide ceiling on embedded chunks per tick.
* `MAX_CHUNKS_PER_TENANT` — so one account pasting a book cannot consume the whole tick and
  starve the rest (`retention.py`'s `TENANT_ROW_BUDGET` argument, on calls).
* `EMBED_BATCH` — how many chunks ride in one request, which bounds what a single failure
  re-does.

WHICH LEG. Azure, on the resource, region and credential every other language call already
uses (D-410/D-449) — **no new sub-processor**, which is one of the two reasons the bake-off
recommended keeping this in-house at all. Not Sarvam: **Sarvam ToS v2.0 (eff. 29 July 2026)
s.17.5** permits Sarvam to use Inputs and Outputs to train its models and **s.6.2** makes a
signed order form the only instrument that displaces it, and we have none (CLAUDE.md,
evidence class VENDOR-PUBLISHED, read by the founder on 27 Aug 2026 and relayed;
`sarvam.ai` is egress-blocked from this container so it was not re-read here). The input on
this leg is every client's entire business knowledge base.

⚠ **WHO PAYS: THE TENANT LEDGER, AND THE FOUNDER ASKED FOR THE PLATFORM ONE.** The intended
destination for ingestion spend is `billing/platform_ai.record_platform_ai_usage`, and that
function exists — but it requires `admin_user_id: UUID`, because it was built for the
admin copilot where a named operator is always behind the turn. A cron has no operator, and
inventing one would put a fabricated identity on an APPEND-ONLY ledger (hard rule 4). So
this sweep meters where the sibling background KB job already meters — the tenant's own
ledger under its own feature name, exactly as `kb_gloss.py` does — and the gap is reported
rather than papered over. Moving it is a one-line change here once that function admits a
caller with no operator behind it.

HARD RULE 6. Not one line here logs a chunk, a gloss, a source name or any client prose.
Ids, counts, states and a wire model name — and a provider's error body quotes the request,
which is why the provider branch logs `type(failure).__name__` and nothing else.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.kb.gloss import GLOSS_PENDING
from apps.api.kb.models import EMBED_PENDING, EMBED_READY, EMBED_REFUSED
from apps.api.retrieval.embedding import (
    ASSIST_FEATURE_KB_EMBED,
    EMBED_BATCH,
    EMBED_TIMEOUT_S,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embedding_leg,
    embedding_price_is_billable,
)
from apps.workers import chat
from apps.workers.kb_gloss import tenants_holding_knowledge

log = get_logger(__name__)

#: The minutes this sweep fires. Twice an hour, on minutes no other fleet-wide fan-out uses:
#: `settings.CRON_JOBS` already holds :00/:05/:10/:15/:17/:20/:23/:25/:30/:35/:40/:42/:45/:50.
#: Eight and thirty-eight are clear of all of them, so no two O(tenants) sweeps share a
#: minute. Twice an hour because this is INGESTION latency a client can perceive on the
#: search screen; the per-tick ceiling is what bounds the spend, so the cadence only decides
#: how fast a backlog drains.
EMBED_MINUTES: Final[frozenset[int]] = frozenset({8, 38})

#: THE FLEET-WIDE CEILING ON EMBEDDED CHUNKS PER TICK, across every tenant. Deliberately
#: larger than the gloss sweep's: an embedding is one short request per chunk with no
#: generation behind it, batched `EMBED_BATCH` at a time, so the same wall clock buys far
#: more of them — and unlike a gloss every published chunk needs one, including the English
#: ones the gloss sweep closes out for free.
MAX_CHUNKS_PER_TICK: Final = 256

#: Per tenant, so one account pasting a 200-page manual cannot consume the whole tick.
MAX_CHUNKS_PER_TENANT: Final = 96

#: The claim. `FOR UPDATE ... SKIP LOCKED` is this repo's single-flight primitive
#: (`reliability/service.py`, `agents/reconciliation.py`) and it is here for the same
#: reason: two overlapping ticks must not both pay for the same chunk. `FOR UPDATE OF c`
#: and not a bare `FOR UPDATE`, because the join brings `kb_documents` along and locking a
#: client's chunk row for the length of a provider round trip would block the gloss sweep
#: and any publish touching it.
#:
#: `c.is_active` — a superseded version is not retrievable, so buying a vector for one is
#: buying a vector nothing will ever read. A rollback that makes it live again flips
#: `is_active` back and the next tick embeds it then.
#:
#: `d.gloss_state <> 'pending'` — the ordering constraint the module docstring argues:
#: `ready` and `not_needed` are both settled answers, `pending` means the English key has
#: not been written yet and embedding now would vectorise half the chunk.
_CLAIM_SQL: Final = (
    "SELECT c.id, d.content, coalesce(d.gloss, '') FROM kb_chunks c "
    "JOIN kb_documents d ON d.id = c.document_id "
    f"WHERE c.embed_state = '{EMBED_PENDING}' AND c.is_active "
    f"AND d.gloss_state <> '{GLOSS_PENDING}' "
    "ORDER BY c.id LIMIT :limit FOR UPDATE OF c SKIP LOCKED"
)

#: `CAST(:vec AS vector)` because psycopg renders a Python list as a Postgres array, which
#: the `vector` type will not accept; the type's own text form is the bracketed literal.
_STORE_SQL: Final = (
    "UPDATE kb_chunks SET embedding = CAST(:vec AS vector), embed_model = :model, "
    "embed_dim = :dim, embed_state = :state, updated_at = now() WHERE id = :id"
)

_REFUSE_SQL: Final = (
    "UPDATE kb_chunks SET embed_state = :state, updated_at = now() WHERE id = ANY(:ids)"
)


def embedding_input(content: str, gloss: str) -> str:
    """What actually gets embedded: the chunk, and its English gloss when it has one.

    ONE VECTOR OVER BOTH RATHER THAN TWO VECTORS. The alternative — a second embedding
    column for the gloss, fused as a third arm — was rejected on the measurement D-489
    already paid for: `docs/evidence/telugu-embedding-quality.md` found that fusing an
    UNGATED second arm dropped cross-script recall@1 from 0.708 to 0.375, because an arm
    that matches nothing still contributes its arbitrary ranking. `compiled_facts.py` solves
    that with a script gate because its ranker is token overlap and cannot mix scripts at
    all; an embedding model can, so concatenating puts both keys in one point in space and
    needs no gate, no second column and no second provider call per chunk.

    The gloss goes SECOND and is separated by a newline rather than by a label: the model is
    embedding meaning, and a word like "English:" in the text is a token that means nothing
    about the client's business competing with the ones that do.
    """
    return content if not gloss else f"{content}\n{gloss}"


async def _embed_batch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    claimed: list[tuple[UUID, str, str]],
    leg: chat.ChatLeg,
) -> int:
    """One provider request for up to `EMBED_BATCH` chunks. Returns how many were stored.

    RAISES on a transport failure so the CALLER can roll the whole tenant back — the claims
    included, which is what returns those chunks to `pending` for the next tick.
    """
    outcome = await chat.embed(
        leg,
        [embedding_input(content, gloss) for _, content, gloss in claimed],
        dimensions=EMBEDDING_DIMS,
        timeout_s=EMBED_TIMEOUT_S,
    )

    stored = 0
    refused: list[UUID] = []
    for (chunk_id, _content, _gloss), vector in zip(claimed, outcome.vectors, strict=False):
        if len(vector) != EMBEDDING_DIMS:
            # A width the column cannot hold. `refused` and NOT `pending`: the next tick
            # would buy the identical wrong answer, so this is the state that stops the
            # loop and the alert below is what gets it looked at.
            refused.append(chunk_id)
            continue
        await session.execute(
            text(_STORE_SQL),
            {
                "id": chunk_id,
                "vec": "[" + ",".join(map(repr, vector)) + "]",
                "model": EMBEDDING_MODEL,
                "dim": EMBEDDING_DIMS,
                "state": EMBED_READY,
            },
        )
        stored += 1

    # SHORT RESPONSES ARE REFUSED TOO, not left pending. The vendor returns one embedding per
    # input; fewer means the request was partially served, and `strict=False` above is what
    # keeps the pairing honest rather than raising on a mismatch we can record instead.
    refused.extend(chunk_id for chunk_id, _, _ in claimed[len(outcome.vectors) :])
    if refused:
        await session.execute(text(_REFUSE_SQL), {"ids": refused, "state": EMBED_REFUSED})
        alert(
            "CORE_LOGIC",
            "kb_embed_unusable_response",
            detail=(
                "The embedding provider returned vectors this schema cannot store (wrong "
                "width, or fewer than were asked for). Those chunks are marked refused so "
                "the sweep does not re-buy the same answer; they are searchable by their "
                "keyword arm only until this is fixed."
            ),
            tenant_id=str(tenant_id),
        )

    # HARD RULE 7, in the SAME transaction as the state changes above. `usage is None` means
    # the provider declined to count, which is the one state D-140 refuses to invent a number
    # for — so it alerts rather than estimating from the text length.
    if outcome.usage is not None:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            # ZERO, AND IT IS THE TRUTH RATHER THAN A DEFAULT. The vendor's
            # `CreateEmbeddingResponse.usage` has `prompt_tokens` and `total_tokens` and no
            # output half at all (openai/openai-openapi @ master, read 1 Sep 2026), so the
            # `ai_assist_ktok_out` row this writes is always qty 0.
            tokens_out=0,
            # THE MODEL, NOT `leg.wire_model`. On Azure a model is served under a DEPLOYMENT
            # id the operator chose (D-410/D-417); `rates.llm_inr_per_ktok` publishes no
            # price for a deployment name and would raise, on an append-only ledger row that
            # could never afterwards be corrected.
            model=EMBEDDING_MODEL,
            feature=ASSIST_FEATURE_KB_EMBED,
        )
    else:
        alert(
            "CORE_LOGIC",
            "kb_embed_unmeterable",
            detail=(
                "A knowledge embedding was paid for and the provider returned no usage "
                "block, so it could not be metered: this spend is invisible to the tenant's "
                "AI ceiling and to the platform brake. Nothing was estimated."
            ),
            tenant_id=str(tenant_id),
        )
    return stored


async def embed_knowledge_chunks(ctx: dict[str, Any]) -> str:
    """Twice hourly. Give every published knowledge chunk a vector, within a budget.

    THE TENANT LIST COMES FROM `kb_gloss.tenants_holding_knowledge` — the same
    `retention_worklist` index, asked through the same function rather than re-derived, so
    the two KB sweeps cannot come to disagree about which accounts hold knowledge.

    ISOLATED PER TENANT, for `write_knowledge_glosses`' reason: one account's provider error
    or lock timeout must not end the tick for everyone behind it. What DOES reach the retry
    ladder is a tick-wide failure — the worklist read — because retrying that is the only
    thing that could help.
    """
    if not embedding_price_is_billable():
        # NOT AN ALERT, and not an outage: it is a configuration state with a named action
        # behind it, and alerting twice an hour on it is how an alert becomes noise. Nothing
        # was bought, which is the whole point of checking here rather than at the ledger.
        log.info("kb_embed_unpriced", extra={"model": EMBEDDING_MODEL})
        return "unpriced"
    leg = embedding_leg()
    if leg is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no embedding deployment
        # configured runs every other queue, and an operator already sees this at
        # `/healthz/ready`.
        log.info("kb_embed_no_provider")
        return "no_provider"

    try:
        tenants = await tenants_holding_knowledge()
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "kb_embed_worklist_failed",
            detail="the knowledge embedding sweep could not read the retention worklist",
            error=type(failure).__name__,
        )
        raise

    budget = MAX_CHUNKS_PER_TICK
    embedded = 0
    for tenant_id in tenants:
        if budget <= 0:
            break
        try:
            async with tenant_session(tenant_id) as session:
                remaining = min(MAX_CHUNKS_PER_TENANT, budget)
                while remaining > 0:
                    rows = (
                        await session.execute(
                            text(_CLAIM_SQL), {"limit": min(EMBED_BATCH, remaining)}
                        )
                    ).all()
                    if not rows:
                        break
                    claimed = [(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows]
                    budget -= len(claimed)
                    remaining -= len(claimed)
                    embedded += await _embed_batch(
                        session, tenant_id=tenant_id, claimed=claimed, leg=leg
                    )
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant. Every claim in the transaction rolls back, so
            # the chunks stay `pending` and the next tick picks them up — the correct
            # response to a transient failure, at a cost of thirty minutes.
            log.warning(
                "kb_embed_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            log.exception("kb_embed_tenant_failed", extra={"tenant_id": str(tenant_id)})

    log.info(
        "kb_embed_tick",
        extra={"tenants": len(tenants), "embedded": embedded, "budget_left": budget},
    )
    return f"embedded={embedded}"


__all__ = [
    "EMBED_MINUTES",
    "MAX_CHUNKS_PER_TENANT",
    "MAX_CHUNKS_PER_TICK",
    "embed_knowledge_chunks",
    "embedding_input",
]

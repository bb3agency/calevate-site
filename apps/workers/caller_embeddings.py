"""The caller-data ingestion sweep: one vector beside every chunk of what a caller said.

`kb_embeddings.py` is this job over a client's own published knowledge, and this is
deliberately the SAME MECHANISM rather than a second one: a cron that claims
`embed_state = 'pending'` with `FOR UPDATE ... SKIP LOCKED`, a price gate before any
provider call, per-tick and per-tenant ceilings, and the state change committing in the
same transaction as the ledger row. What differs is what it is pointed at, and everything
below is a consequence of that.

--------------------------------------------------------------------------------
ONE SWEEP, THREE SCOPES, AND THE SCOPES OWN ONLY WHAT A CHUNK IS
--------------------------------------------------------------------------------
Each scope registers a `CallerProjection` (`retrieval/caller_projections.py`) and this job
owns everything that is dangerous to get wrong twice: the transaction, the claim, the
idempotency key, the budget, the price gate, the metering, and the subject key an erasure
has to be able to derive. Three sweeps would be three places to get hard rule 7 right and
three places for a scope to forget `scrubbed_at`.

TWO PHASES PER TENANT, and they are separate because the store holds NO CONTENT:

1. **Discover.** Each scope's own statement yields the chunks whose projection is missing
   or out of date; `store_chunks` writes them with `tsv` built in the statement and
   `embedding` NULL. A chunk is therefore searchable by its sparse arm from the moment it
   is discovered — nothing blocks on a provider being up.
2. **Embed.** Claim `pending` rows on `caller_chunks` (which is where the single-flight
   lock belongs — two ticks must not buy one vector twice), ask the scope for the text
   again through `content_for`, buy the vectors, store them.

The re-read in phase 2 is the price of storing no content, and it is the right price: the
alternative is a `content` column, which would double what an erasure has to find and make
this table a second copy of every caller's words rather than a projection of them.

--------------------------------------------------------------------------------
WHY A SWEEP AND NOT AN ENQUEUE
--------------------------------------------------------------------------------
`kb_gloss.py` settled this for the sibling job and the argument is unchanged: a cron that
selects `pending` is SELF-HEALING in a way an enqueue is not — a lost job, a provider
outage, a call that landed while the worker was being redeployed, and a scope registered
next month all converge on the next tick with no reconciliation code. Timeliness costs
little here because nothing BLOCKS on a vector.

--------------------------------------------------------------------------------
WHO PAYS: THE PLATFORM LEDGER, WHICH IS THE THING D-502 COULD NOT DO
--------------------------------------------------------------------------------
`billing/platform_ai.record_platform_ai_usage` required an `admin_user_id` because it was
built for the admin copilot, where a named operator is always behind the turn. D-502 wrote
the consequence down rather than papering over it: a cron has no operator, inventing one
would put a fabricated identity on an APPEND-ONLY ledger, so KB ingestion metered on the
TENANT's ledger and the gap was reported. `system_actor` (migration `c6b1f0d47e83`) closes
it honestly — a NAMED JOB is answerable in exactly the way an anonymous NULL is not — and
this sweep is its first caller.

The pricing argument is on `crm/assist.ASSIST_FEATURE_CALLER_EMBED`: ingestion is a cost of
OUR feature existing, its quantity tracks call volume the client already pays per minute
for, and a client who never opens the search screen must not pay for indexing they never
used. THE QUERY SIDE IS THEIRS and is metered on their own ceiling by `caller_search`.

**IT COUNTS AGAINST THE PLATFORM BRAKE, WHICH IS THE POINT AND NOT A SIDE EFFECT.**
`platform_ai_spend` is the only ceiling our own key has, and a sweep whose volume is a
function of how many calls the whole fleet takes is exactly the spend that ceiling exists
for. `require_platform_ai` is not called here, deliberately: it raises a `ProblemError`
shaped for a request, and a cron that raised on a tripped brake would look like a broken
job. The brake is read directly instead, and a tripped one ends the tick with a log line —
NOTHING BOUGHT, which is the behaviour a brake is for.

--------------------------------------------------------------------------------
HARD RULES
--------------------------------------------------------------------------------
Rule 6: not one line here logs a chunk, a phone number, a subject ref or a caller's words.
Ids, counts, kinds, states, and a provider error's TYPE — never its body, which quotes the
request back, and the request is a caller's own sentence.

Rule 7: `embedding_price_is_billable()` is asked BEFORE any provider call, because
`record_platform_ai_usage` raises for an unpriced model AFTER the spend — and that raise
rolls back the transaction holding the state change, so the next tick would buy the same
vector to reach the same raise, for ever.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, read_platform_ai_spend
from apps.api.billing.platform_ai import record_platform_ai_usage
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.crm.assist import ASSIST_FEATURE_CALLER_EMBED
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.retrieval.caller_projections import (
    CallerProjection,
    ChunkKey,
    content_digest,
    registered_projections,
    store_chunks,
)
from apps.api.retrieval.embedding import (
    EMBED_BATCH,
    EMBED_TIMEOUT_S,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embedding_leg,
    embedding_price_is_billable,
)
from apps.api.retrieval.models import EMBED_READY, EMBED_REFUSED
from apps.workers import chat

log = get_logger(__name__)

#: `platform_ai_usage.system_actor` — WHO this job is, on an append-only ledger. The module
#: path rather than a friendly name: an operator reading a row two years from now needs to
#: be able to open the thing that wrote it.
SYSTEM_ACTOR: Final = "workers.caller_embeddings"

#: The minutes this sweep fires. `settings.CRON_JOBS` already uses
#: :00/:05/:08/:10/:12/:15/:17/:20/:23/:25/:30/:35/:38/:40/:42/:45/:50, so :13 and :43 are
#: clear of every other fleet-wide fan-out — no two O(tenants) sweeps share a minute, which
#: is the property `EMBED_MINUTES` was chosen for one job over.
#:
#: Twice an hour because this is INGESTION latency a person can perceive on a search screen,
#: and because the per-tick ceiling is what bounds the spend — the cadence only decides how
#: fast a backlog drains.
CALLER_EMBED_MINUTES: Final[frozenset[int]] = frozenset({13, 43})

#: THE FLEET-WIDE CEILING ON CHUNKS EMBEDDED PER TICK. Lower than `kb_embeddings`' 256, and
#: the difference is the corpus rather than a preference: a knowledge base is uploaded once
#: and is finite, while calls arrive for ever, so this job's backlog has no natural end and
#: an unbounded tick would be an unbounded bill on our own key.
MAX_CHUNKS_PER_TICK: Final = 192

#: Per tenant, so one busy account cannot consume the whole tick and starve the rest
#: (`retention.TENANT_ROW_BUDGET`'s argument, on chunks).
MAX_CHUNKS_PER_TENANT: Final = 64

#: How many un-projected subjects one scope contributes per tenant per tick. Bounded for
#: the same reason as the embedding budget: discovery is cheap but it WRITES, and a
#: first-ever tick on an account with two years of calls would otherwise project the lot in
#: one transaction.
MAX_DISCOVER_PER_SCOPE: Final = 256

#: THE CLAIM. `FOR UPDATE ... SKIP LOCKED` is this repo's single-flight primitive and it is
#: here for `kb_embeddings._CLAIM_SQL`'s reason: two overlapping ticks must not both pay for
#: the same chunk, and a crash mid-request rolls the claim back so the row stays `pending`.
#:
#: `scrubbed_at IS NULL` — a row an erasure or a retention sweep forgot is never re-bought.
#: Belt over braces: those arms also set a terminal `embed_state`, and this is the guard
#: that survives somebody adding a fourth writer of that column.
#:
#: `embed_model` / `embed_dim` ARE READ, and that is why they are written. A `ready` row
#: whose stored model or width is not the one this deployment now embeds with is RE-CLAIMED,
#: because two embedding models' vectors in one index are not comparable — a cosine distance
#: between them is a number with no meaning, nothing raises, and retrieval quietly returns
#: the wrong row for as long as nobody notices.
#:
#: `IS DISTINCT FROM` rather than `<>`, because both columns are nullable: a row written
#: before either was recorded compares NULL against a real value, and `<>` answers NULL and
#: skips exactly the un-provenanced rows most likely to be stale.
_CLAIM_SQL: Final = f"""
SELECT c.subject_id, c.idx FROM caller_chunks c
 WHERE c.subject_kind = :kind
   AND c.scrubbed_at IS NULL
   AND (c.embed_state = 'pending'
        OR (c.embed_state = '{EMBED_READY}'
            AND (c.embed_model IS DISTINCT FROM :model
                 OR c.embed_dim IS DISTINCT FROM :dim)))
 ORDER BY c.occurred_at DESC, c.subject_id, c.idx
 LIMIT :limit FOR UPDATE OF c SKIP LOCKED
"""

#: NEWEST FIRST, unlike every other sweep in this repository, and it is a decision rather
#: than an oversight. Retention sweeps go oldest-first because the oldest row is the one
#: whose deadline is nearest. This is the opposite kind of job: a backlog of two years of
#: calls drains at `MAX_CHUNKS_PER_TICK`, and the conversations a client will search for
#: are last week's. Oldest-first would leave the useful half of the corpus unsearchable for
#: as long as the backfill took, with a search screen that looks broken the whole time.

#: `CAST(:vec AS vector)` because psycopg renders a Python list as a Postgres array, which
#: the `vector` type will not accept; the type's own text form is the bracketed literal.
#:
#: `content_sha256 = :sha` is RE-ASSERTED in the WHERE clause, not just written: between the
#: claim and this statement the source could have been re-discovered with new text, and
#: storing a vector of the OLD sentence under the NEW hash would leave a row that claims to
#: be current and is not — invisible, and exactly the class of silent staleness the
#: model/width check above exists for.
_STORE_SQL: Final = """
UPDATE caller_chunks
   SET embedding = CAST(:vec AS vector), embed_model = :model, embed_dim = :dim,
       embed_state = :state, updated_at = now()
 WHERE subject_kind = :kind AND subject_id = :sid AND idx = :idx
   AND scrubbed_at IS NULL AND content_sha256 = :sha
"""

_REFUSE_SQL: Final = """
UPDATE caller_chunks SET embed_state = :state, updated_at = now()
 WHERE subject_kind = :kind AND subject_id = :sid AND idx = :idx AND scrubbed_at IS NULL
"""


async def tenants_with_caller_data() -> list[UUID]:
    """Every tenant that CAN hold caller data, from the global bridge.

    `engine_agent_routes` is the same non-tenant-scoped table `retention._due_tenants`
    reads, and it is asked here for the same reason: a cross-tenant resolution that needs
    no RLS exemption and no admin role (hard rule 1). Its own docstring carries the proof
    that the set is a superset — a `calls` row is only ever created for an agent the engine
    knows, and `ingest_lead` refuses to write a lead for an agent with no `engine_agent_ref`
    — so every tenant holding a call or a lead is in it.

    **`retention_worklist` IS DELIBERATELY NOT UNIONED IN**, unlike `_due_tenants`. That
    half exists to reach a tenant whose only expirable artefact is a KNOWLEDGE SOURCE, which
    is a client's own uploaded document and not caller data: there is nothing here for such
    a tenant to project, so including them would buy one probe a tick per account for a
    guaranteed empty answer.

    ORDER BY, and it is not cosmetic: without it, which tenants a tick reaches before its
    budget runs out is planner-dependent and varies night to night, so "tenant X was not
    swept" becomes a question with no answer.
    """
    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id")
                )
            )
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


async def _discover(session: AsyncSession, *, tenant_id: UUID, projection: CallerProjection) -> int:
    """Phase 1 for one scope: ask it what is missing, write it. Returns rows projected."""
    chunks = await projection.discover(session, MAX_DISCOVER_PER_SCOPE)
    if not chunks:
        return 0
    return await store_chunks(session, tenant_id=tenant_id, projection=projection, chunks=chunks)


async def _embed_claimed(
    session: AsyncSession,
    *,
    projection: CallerProjection,
    keys: list[ChunkKey],
    leg: chat.ChatLeg,
) -> int:
    """Phase 2 for one claimed batch: re-read the text, buy the vectors, store them.

    RAISES on a transport failure so the CALLER can roll the whole tenant back — the claims
    included, which is what returns those chunks to `pending` for the next tick.
    """
    bodies = await projection.content_for(session, keys)
    # A claimed row whose scope can no longer produce its text is left `pending` rather
    # than refused: the usual cause is a source that changed between the claim and now, and
    # the next discovery will re-write the row with the new text and a new hash. Refusing
    # would freeze a chunk the scope is about to fix.
    live = [key for key in keys if bodies.get(key)]
    if not live:
        return 0

    outcome = await chat.embed(
        leg,
        [bodies[key] for key in live],
        dimensions=EMBEDDING_DIMS,
        timeout_s=EMBED_TIMEOUT_S,
    )

    stored = 0
    refused: list[ChunkKey] = []
    for key, vector in zip(live, outcome.vectors, strict=False):
        if len(vector) != EMBEDDING_DIMS:
            # A width the column cannot hold. `refused` and NOT `pending`: the next tick
            # would buy the identical wrong answer, so this is the state that stops the loop.
            refused.append(key)
            continue
        await session.execute(
            text(_STORE_SQL),
            {
                "kind": projection.subject_kind,
                "sid": key[0],
                "idx": key[1],
                "vec": "[" + ",".join(map(repr, vector)) + "]",
                "model": EMBEDDING_MODEL,
                "dim": EMBEDDING_DIMS,
                "state": EMBED_READY,
                "sha": content_digest(bodies[key]),
            },
        )
        stored += 1

    # SHORT RESPONSES ARE REFUSED TOO, not left pending: the vendor returns one embedding
    # per input, so fewer means the request was partially served — and `strict=False` above
    # is what keeps the pairing honest rather than raising on a mismatch we can record.
    refused.extend(live[len(outcome.vectors) :])
    for key in refused:
        await session.execute(
            text(_REFUSE_SQL),
            {
                "kind": projection.subject_kind,
                "sid": key[0],
                "idx": key[1],
                "state": EMBED_REFUSED,
            },
        )
    if refused:
        alert(
            "CORE_LOGIC",
            "caller_embed_unusable_response",
            detail=(
                "The embedding provider returned vectors this schema cannot store (wrong "
                "width, or fewer than were asked for). Those chunks are marked refused so "
                "the sweep does not re-buy the same answer; they stay searchable by their "
                "keyword arm only until this is fixed."
            ),
            scope=projection.subject_kind,
        )

    # HARD RULE 7, in the SAME transaction as the state changes above, and on the PLATFORM
    # ledger (see the module docstring). `usage is None` is the one state D-140 refuses to
    # invent a number for, so it alerts rather than estimating from the text length.
    if outcome.usage is not None:
        await record_platform_ai_usage(
            session,
            system_actor=SYSTEM_ACTOR,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            # ZERO, AND IT IS THE TRUTH RATHER THAN A DEFAULT: the vendor's
            # `CreateEmbeddingResponse.usage` has `prompt_tokens` and `total_tokens` and no
            # output half at all.
            tokens_out=0,
            # THE MODEL, NOT `leg.wire_model`. On Azure a model is served under a
            # DEPLOYMENT id the operator chose (D-410/D-417), and `rates.llm_inr_per_ktok`
            # publishes no price for a deployment name — it would raise, on a row that
            # could never afterwards be corrected.
            model=EMBEDDING_MODEL,
            feature=ASSIST_FEATURE_CALLER_EMBED,
        )
    else:
        alert(
            "CORE_LOGIC",
            "caller_embed_unmeterable",
            detail=(
                "A caller-data embedding was paid for and the provider returned no usage "
                "block, so it could not be metered: this spend is invisible to the platform "
                "brake, which is the ONLY ceiling this job has. Nothing was estimated."
            ),
            scope=projection.subject_kind,
        )
    return stored


async def _sweep_tenant(
    session: AsyncSession, *, tenant_id: UUID, leg: chat.ChatLeg, budget: int
) -> tuple[int, int]:
    """Discover then embed, for every registered scope. Returns (projected, embedded)."""
    projected = 0
    embedded = 0
    remaining = min(MAX_CHUNKS_PER_TENANT, budget)
    for projection in registered_projections():
        projected += await _discover(session, tenant_id=tenant_id, projection=projection)
        while remaining > 0:
            rows = (
                await session.execute(
                    text(_CLAIM_SQL),
                    {
                        "kind": projection.subject_kind,
                        "limit": min(EMBED_BATCH, remaining),
                        # The model and width THIS deployment embeds with; a `ready` row
                        # not matching both is stale and re-claimed.
                        "model": EMBEDDING_MODEL,
                        "dim": EMBEDDING_DIMS,
                    },
                )
            ).all()
            if not rows:
                break
            keys: list[ChunkKey] = [(UUID(str(row[0])), int(row[1])) for row in rows]
            remaining -= len(keys)
            embedded += await _embed_claimed(session, projection=projection, keys=keys, leg=leg)
    return projected, embedded


async def embed_caller_chunks(ctx: dict[str, Any]) -> str:
    """Twice hourly. Project and vectorise what this fleet's callers said, within a budget.

    ISOLATED PER TENANT, for `kb_embeddings`' reason: one account's provider error or lock
    timeout must not end the tick for everyone behind it. What DOES reach the retry ladder
    is a tick-wide failure — the worklist read — because retrying that is the only thing
    that could help.
    """
    if not registered_projections():
        # NOT a failure and not an alert. The store and the sweep are the safety core; the
        # scopes that fill it register themselves. A deployment where none has is a
        # deployment with no caller search, which is a state an operator can see.
        log.info("caller_embed_no_scopes")
        return "no_scopes"
    if not embedding_price_is_billable():
        # Hard rule 7's pre-flight. NOT an alert and not an outage: it is a configuration
        # state with a named action behind it (an operator enters the figure from their own
        # invoice), and alerting twice an hour on it is how an alert becomes noise. Nothing
        # was bought, which is the whole point of checking here rather than at the ledger.
        log.info("caller_embed_unpriced", extra={"model": EMBEDDING_MODEL})
        return "unpriced"
    leg = embedding_leg()
    if leg is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no embedding deployment
        # configured runs every other queue, and an operator already sees this at
        # `/healthz/ready`.
        log.info("caller_embed_no_provider")
        return "no_provider"

    try:
        tenants = await tenants_with_caller_data()
        async with untenanted_session() as session:
            spend = await read_platform_ai_spend(session)
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "caller_embed_worklist_failed",
            detail="the caller-data embedding sweep could not read its worklist",
            error=type(failure).__name__,
        )
        raise

    if spend.tripped:
        # THE BRAKE, READ RATHER THAN RAISED. `require_platform_ai` renders a 503 shaped for
        # a request, and a cron that raised on a tripped brake would page as a broken job
        # when it is in fact a ceiling doing its work. Nothing is bought; the backlog waits
        # for the IST month to roll over, and everything already projected stays searchable
        # by its keyword arm meanwhile.
        log.warning("caller_embed_brake_tripped")
        return "brake_tripped"

    budget = MAX_CHUNKS_PER_TICK
    projected = 0
    embedded = 0
    for tenant_id in tenants:
        if budget <= 0:
            break
        try:
            async with tenant_session(tenant_id) as session:
                tenant_projected, tenant_embedded = await _sweep_tenant(
                    session, tenant_id=tenant_id, leg=leg, budget=budget
                )
            projected += tenant_projected
            embedded += tenant_embedded
            budget -= tenant_embedded
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant. Every claim in the transaction rolls back, so
            # the chunks stay `pending` and the next tick picks them up — the correct
            # response to a transient failure, at a cost of thirty minutes.
            log.warning(
                "caller_embed_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            log.exception("caller_embed_tenant_failed", extra={"tenant_id": str(tenant_id)})

    log.info(
        "caller_embed_tick",
        extra={
            "tenants": len(tenants),
            "projected": projected,
            "embedded": embedded,
            "budget_left": budget,
        },
    )
    return f"projected={projected} embedded={embedded}"


__all__ = [
    "CALLER_EMBED_MINUTES",
    "MAX_CHUNKS_PER_TENANT",
    "MAX_CHUNKS_PER_TICK",
    "MAX_DISCOVER_PER_SCOPE",
    "SYSTEM_ACTOR",
    "embed_caller_chunks",
    "tenants_with_caller_data",
]

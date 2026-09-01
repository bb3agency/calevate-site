"""The English gloss sweep: one short English rendering beside each Telugu knowledge chunk.

WHY THIS EXISTS, MEASURED RATHER THAN ASSUMED. `docs/evidence/telugu-embedding-quality.md`
measured retrieval over this repo's own seeded verticals (n=24) and found the worst case is
the NORMAL case: a **Tenglish** question — Telugu grammar in Latin script, which is what
Sarvam's Saaras STT returns — scored recall@1 **0.250** against a Telugu-script corpus,
where an English control on the same facts scored 0.958. Storing the fact in English as
well took that cell to **0.750**. On the ranker this repo actually has (deterministic token
overlap, `retrieval/compiled_facts.py`) the failure is total rather than merely poor: a
Latin-script question shares no tokens at all with a Telugu-script line.

WHY AT INGESTION AND WHY NOW. The gloss is written ONCE per chunk and read on every
question, so it is the cheapest possible place to pay — and adding it later means
re-ingesting every client's knowledge base. There are no clients yet. That is the whole
timing argument, and it is the founder's.

WHY A SWEEP AND NOT AN ENQUEUE FROM `kb.service.submit_source`. A cron that selects
`gloss_state = 'pending'` is SELF-HEALING in a way an enqueue is not: a lost job, a
provider outage, a chunk written by a path nobody has invented yet, and a row that existed
before this feature all converge on the next tick with no reconciliation code. An enqueue
would need exactly that reconciliation to be trustworthy, which is the sweep, so the sweep
is the one mechanism rather than the second one. Timeliness is not a cost here because
nothing BLOCKS on a gloss: `retrieval/compiled_facts.py` reads it live from `kb_documents`,
so a gloss that lands after its source was published starts working immediately, with no
prompt re-mint and no republish.

THE SPEND CONTROLS, because this job costs real money on a timer and nothing above it
says no:

* **The script test, which is free.** `kb/gloss.needs_gloss` is a character count. An
  English chunk is marked `not_needed` WITHOUT a model call — most chunks in an
  English-speaking account never cost a paisa.
* `MAX_CHUNKS_PER_TICK` — the fleet-wide ceiling on paid calls per tick.
* `MAX_CHUNKS_PER_TENANT` — so one account pasting a book cannot consume the whole tick
  and starve the rest (`retention.py`'s `TENANT_ROW_BUDGET` argument, on calls).
* `GLOSS_MAX_TOKENS` — `EXTRACTION_MAX_TOKENS`' shape on the output side.
* `MAX_GLOSS_CHARS` — a token ceiling bounds the REQUEST's cost, not the size of what gets
  STORED, and stored bytes are what retention and every future embedding actually pay for.

WHICH LEG, AND WHY NOT SARVAM. Azure, through `workers/chat.py` — the ONE
OpenAI-compatible client in this tree — on the credentials `extraction.azure_credentials()`
already decides once. Sarvam does translation on the speech leg and was the obvious
alternative; it is refused on a LICENCE fact rather than on quality. **Sarvam ToS v2.0
(eff. 29 July 2026) s.17.5** permits Sarvam to use Inputs and Outputs to train its models,
and **s.6.2** makes a signed order form or enterprise agreement the only instrument that
displaces it — we have none (CLAUDE.md, evidence class VENDOR-PUBLISHED, read by the
founder at `www.sarvam.ai` on 27 Aug 2026 and relayed; `sarvam.ai` is egress-blocked from
this container so it was not re-read here). The input on this leg is a client's own
business knowledge, in bulk, for every client we have. Azure is retained on an enterprise
DPA with modified abuse monitoring, which is the difference that decides it. This is not a
new vendor and not a new credential: it is the leg `copilot_memory.py` already runs on.

IDEMPOTENCY IS `kb_documents.gloss_state`, AND IT IS WHY THAT COLUMN EXISTS. `gloss IS
NULL` cannot distinguish "nobody has looked at this" from "looked at, English, owes
nothing", so a sweep keyed on it would re-pay a model call to reach the same "no" on every
tick forever. Each chunk is claimed with `FOR UPDATE SKIP LOCKED` inside the transaction
that writes its result, so an overlapping tick, an arq retry or a redeploy skips a row
another worker is holding rather than paying for it twice — and a crash mid-call rolls the
claim back, leaving the row `pending` for the next tick. The state transition and the
`usage_events` row commit together: a translation we paid for and did not record is money
off the books (hard rule 7), and a gloss stored without its state moved would be paid for
twice.

HARD RULE 6. Not one line here logs a chunk, a gloss, a source name or any client prose.
Ids, counts, states and a wire model name — and a provider's error body quotes the request,
which is why the provider branch logs `type(failure).__name__` and nothing else.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from calevate_shared.engine import azure_openai_base_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.crm.assist import ASSIST_FEATURE_KB_GLOSS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb.gloss import GLOSS_NOT_NEEDED, GLOSS_PENDING, GLOSS_READY, needs_gloss
from apps.workers import chat
from apps.workers.extraction import AZURE_PROVIDER, azure_credentials

log = get_logger(__name__)

#: The minutes this sweep fires. Twice an hour, on minutes no other fleet-wide fan-out
#: uses: `settings.CRON_JOBS` holds :05/:35 (stalled pipeline), :15/:45 (outstanding
#: calls), :23 (KB drift), :25 (distillation and overdue erasures), plus :10, :17, :20 and
#: :40. Twelve and forty-two are clear of all of them, so three O(tenants) sweeps never
#: share a minute. Twice an hour rather than hourly because this is INGESTION latency a
#: client can perceive at the review screen; the per-tick ceiling below is what bounds the
#: spend, so the cadence only decides how fast a backlog drains.
GLOSS_MINUTES: Final[frozenset[int]] = frozenset({12, 42})

#: THE FLEET-WIDE CEILING ON PAID CALLS PER TICK, across every tenant. Two ticks an hour
#: times this is the most translations this feature can buy in an hour. Deliberately
#: modest: a knowledge base is uploaded once and then rarely, so a backlog draining over a
#: few hours is invisible, whereas an unbounded fan-out over a table with a row per chunk
#: of every document every client has ever pasted is an incident.
MAX_CHUNKS_PER_TICK: Final = 60

#: Per tenant, so one account pasting a 200-page manual cannot consume the whole tick.
MAX_CHUNKS_PER_TENANT: Final = 20

#: The output valve (`EXTRACTION_MAX_TOKENS`' shape). A chunk is at most
#: `kb.service.MAX_CHUNK_CHARS` (700) characters and its English rendering is asked to be
#: no longer, so this is roughly double what a compliant answer needs and can only fire on
#: a runaway.
GLOSS_MAX_TOKENS: Final = 320

#: What gets STORED, in characters. A token ceiling bounds the request; this bounds the
#: row, which is what retention, backups and any future embedding actually pay for. Sized
#: to `MAX_CHUNK_CHARS` with headroom for English being wordier than Telugu.
MAX_GLOSS_CHARS: Final = 900

#: Wall clock for one translation. Nobody is waiting; this exists so a hung provider costs
#: one slot of the tick rather than the tick.
GLOSS_TIMEOUT_S: Final = 30.0

#: The instruction. Deliberately narrow, and deliberately NOT "answer" or "summarise": the
#: output is a RETRIEVAL KEY, so what matters is that the nouns, numbers, days and names a
#: caller would ask about survive into English. A model that paraphrases prettily and drops
#: "Aarogyasri" or "8:30 pm" has produced better prose and a much worse key.
#:
#: "Do not add anything" is here for a reason that is not style: a gloss that invented a
#: fact would put that invention in the retrieval index for a client's own knowledge base,
#: findable by a question none of their approved text answers.
_SYSTEM_PROMPT: Final = (
    "You translate a short passage of Indian small-business knowledge into plain English. "
    "Keep every fact, number, time, day, price, brand name and person's name exactly as "
    "given; transliterate proper nouns rather than translating them. Do not add anything, "
    "do not explain, do not summarise, and do not comment on the text. Reply with the "
    "English translation and nothing else."
)

#: The claim. `FOR UPDATE ... SKIP LOCKED` is this repo's single-flight primitive
#: (`reliability/service.py`, `agents/reconciliation.py`) and it is here for the same
#: reason: two overlapping ticks must not both pay for the same chunk. `FOR UPDATE OF d`
#: and not a bare `FOR UPDATE`, because the join brings `kb_sources` along and locking a
#: client's source row for the length of a provider round trip would block their next
#: submission on our translation.
#:
#: `s.status <> 'rejected'` rather than `= 'approved'`. A gloss is wanted BEFORE approval so
#: the reviewer sees it on the preview screen, and it is wanted for an ARCHIVED source
#: because a rollback (FLOWS §7) makes an archived version live again by moving a pointer
#: rather than by re-ingesting it. Rejected is the one status certain never to be spoken.
_CLAIM_SQL: Final = (
    "SELECT d.id, d.content FROM kb_documents d "
    "JOIN kb_sources s ON s.id = d.source_id "
    f"WHERE d.gloss_state = '{GLOSS_PENDING}' AND s.status <> 'rejected' "
    "ORDER BY d.id LIMIT :limit FOR UPDATE OF d SKIP LOCKED"
)

_MARK_SQL: Final = (
    "UPDATE kb_documents SET gloss = :gloss, gloss_model = :model, gloss_state = :state, "
    "updated_at = now() WHERE id = :id"
)


async def _gloss_one(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    chunk_id: UUID,
    content: str,
    leg: chat.ChatLeg,
    model: str,
) -> bool:
    """One chunk → a stored gloss, or a stored "nothing owed". True when a model was paid.

    THE FREE BRANCH COMES FIRST and it is most of the traffic: `needs_gloss` is a character
    count, so an English (or Devanagari, or purely numeric) chunk is closed out for nothing.
    Only Telugu-script text reaches the provider — the asymmetry `kb/gloss.needs_gloss`
    argues, and the reason this feature is nearly free for an English-speaking account.
    """
    if not needs_gloss(content):
        await session.execute(
            text(_MARK_SQL),
            {"id": chunk_id, "gloss": None, "model": None, "state": GLOSS_NOT_NEEDED},
        )
        return False

    outcome = await chat.complete(
        leg,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        timeout_s=GLOSS_TIMEOUT_S,
        temperature=0,
        max_tokens=GLOSS_MAX_TOKENS,
    )
    if outcome.finish_reason == "length":
        # The valve fired, so this run SPENT the ceiling. A truncated gloss is still a
        # usable retrieval key — unlike truncated JSON it does not fail to parse — so it is
        # kept, and this line is what tells an operator the cap is mis-sized.
        log.warning("kb_gloss_truncated", extra={"chunk_id": str(chunk_id)})

    gloss = (outcome.content or "").strip()[:MAX_GLOSS_CHARS]
    if gloss:
        await session.execute(
            text(_MARK_SQL),
            {"id": chunk_id, "gloss": gloss, "model": model, "state": GLOSS_READY},
        )
    else:
        # The provider answered and declined to say anything. Left `pending` deliberately:
        # the next tick asks again, which is the right response to an empty completion and
        # cheaper than a fourth state meaning "asked once, got nothing". Still metered
        # below — we paid for the turn whether or not it contained a sentence.
        log.warning("kb_gloss_empty", extra={"chunk_id": str(chunk_id)})

    # HARD RULE 7, in the SAME transaction as the state change above. A model call that
    # spent our credential is recorded. `usage is None` means the provider declined to
    # count, which is the one state D-140 refuses to invent a number for — so it alerts
    # (`crm/assist.meter_assist`'s stage and argument) rather than estimating from the
    # chunk length.
    if outcome.usage is not None:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            tokens_out=outcome.usage.output_tokens,
            # THE SETTING, NOT `leg.wire_model`. On Azure a model is served under a
            # DEPLOYMENT id the operator chose (D-410/D-417); `rates.llm_inr_per_ktok`
            # publishes no price for a deployment name and would raise, on an append-only
            # ledger row that could never afterwards be corrected.
            model=model,
            feature=ASSIST_FEATURE_KB_GLOSS,
        )
    else:
        alert(
            "CORE_LOGIC",
            "kb_gloss_unmeterable",
            detail=(
                "A knowledge gloss was paid for and the provider returned no usage block, "
                "so it could not be metered: this spend is invisible to the tenant's AI "
                "ceiling and to the platform brake. Nothing was estimated."
            ),
            tenant_id=str(tenant_id),
        )
    return True


async def tenants_holding_knowledge() -> list[UUID]:
    """Every tenant that holds a knowledge source, from D-368's index.

    `retention_worklist` reason `kb_source` is written by a database trigger on
    `kb_sources`, so this is exact for every writer of that table including ones nobody has
    written yet. `kb_documents` is FORCE-RLS'd and an untenanted session sees zero rows of
    it; this table hands an untenanted reader tenant IDS and nothing else, which is the cost
    `retention._due_tenants` refused to pay by exempting a content table instead.

    A FUNCTION RATHER THAN FOUR LINES INSIDE THE TICK, so the tick's tenant LOOP can be
    driven over a known list in a test. The sweep is fleet-wide and its ceiling is per
    tick, so a suite that has left work in the database elsewhere would otherwise spend the
    budget before reaching the tenant under test — a failure that reads exactly like an
    idempotency defect and is not one.
    """
    async with untenanted_session() as session:
        return [
            UUID(str(row))
            for row in (
                await session.execute(
                    text(
                        "SELECT tenant_id FROM retention_worklist "
                        "WHERE reason = 'kb_source' ORDER BY tenant_id"
                    )
                )
            )
            .scalars()
            .all()
        ]


async def write_knowledge_glosses(ctx: dict[str, Any]) -> str:
    """Twice hourly. Give every pending knowledge chunk an English gloss, within a budget.

    THE TENANT LIST COMES FROM `retention_worklist`, reason `kb_source` — the index D-368
    already built for exactly this shape of question, kept current by a database trigger on
    `kb_sources`. `kb_documents` is FORCE-RLS'd, so an untenanted session sees zero rows of
    it; that table hands an untenanted reader tenant IDS and nothing else, which is the cost
    `retention._due_tenants` refused to pay by exempting a content table instead. No new
    reason and no new trigger are needed: a tenant holding a knowledge chunk holds a
    `kb_sources` row by construction.

    ISOLATED PER TENANT, for `distil_copilot_memories`' reason: one account's provider
    error or lock timeout must not end the tick for everyone behind it in the list. What
    DOES reach the retry ladder is a tick-wide failure — the worklist read — because
    retrying that is the only thing that could help.
    """
    credentials = azure_credentials()
    if credentials is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no language credential runs
        # every other queue. Not an alert — it is a configuration state an operator already
        # sees at `/healthz/ready`, and alerting twice an hour on it is how an alert becomes
        # noise.
        log.info("kb_gloss_no_provider", extra={"provider": AZURE_PROVIDER})
        return "no_provider"
    resource, api_key, deployment = credentials
    leg = chat.ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )
    model = get_settings().azure_openai_model

    try:
        tenants = await tenants_holding_knowledge()
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "kb_gloss_worklist_failed",
            detail="the knowledge gloss sweep could not read the retention worklist",
            error=type(failure).__name__,
        )
        raise

    budget = MAX_CHUNKS_PER_TICK
    translated = 0
    not_needed = 0
    for tenant_id in tenants:
        if budget <= 0:
            break
        try:
            async with tenant_session(tenant_id) as session:
                rows = (
                    await session.execute(
                        text(_CLAIM_SQL), {"limit": min(MAX_CHUNKS_PER_TENANT, budget)}
                    )
                ).all()
                for row in rows:
                    budget -= 1
                    if await _gloss_one(
                        session,
                        tenant_id=tenant_id,
                        chunk_id=UUID(str(row[0])),
                        content=str(row[1]),
                        leg=leg,
                        model=model,
                    ):
                        translated += 1
                    else:
                        not_needed += 1
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant. Every claim in the transaction rolls back, so
            # the chunks stay `pending` and the next tick picks them up — the correct
            # response to a transient failure, at a cost of thirty minutes.
            log.warning(
                "kb_gloss_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            log.exception("kb_gloss_tenant_failed", extra={"tenant_id": str(tenant_id)})

    log.info(
        "kb_gloss_tick",
        extra={
            "tenants": len(tenants),
            "translated": translated,
            "not_needed": not_needed,
            "budget_left": budget,
        },
    )
    return f"translated={translated} not_needed={not_needed}"


__all__ = [
    "GLOSS_MAX_TOKENS",
    "GLOSS_MINUTES",
    "MAX_CHUNKS_PER_TENANT",
    "MAX_CHUNKS_PER_TICK",
    "MAX_GLOSS_CHARS",
    "tenants_holding_knowledge",
    "write_knowledge_glosses",
]

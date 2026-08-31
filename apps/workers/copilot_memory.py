"""Semantic distillation: turning a run of copilot episodes into durable business facts.

WHY THIS IS A CRON AND NOT PART OF THE COPILOT TURN, which is the whole design decision
and not a deployment detail. Distilling means reading a conversation back to a model. In a
live turn that is (a) latency a person is sitting in front of, on a surface whose entire
budget is `service.TOTAL_BUDGET_S`, and (b) the same tokens paid a second time, on a
surface already metered per answer. So it happens here, after the fact, in bulk, on a
clock — and `copilot/memory.py` writes episodic rows and returns without ever calling a
model.

WHAT "AFTER A CONVERSATION ENDS" MEANS WITHOUT A CONVERSATION ID. There is no end-of-chat
signal on the wire: `POST /v1/copilot/ask` is one question, `history` is replayed by the
browser and `copilot/schemas.py` carries no thread id. Inventing one would mean a schema
change on a surface three other lanes are editing, for a fact this job can derive: a
conversation is the undistilled episodes of ONE person on ONE screen, and it has ENDED
when the newest of them is older than `IDLE_WINDOW`. That is inference from data we
already hold rather than a new field for a browser to get wrong, and it degrades in the
right direction — a person who comes back mid-window gets their episodes distilled one
tick later, which nobody can perceive.

THE SPEND CONTROLS, because this job costs real money on a timer and nothing above it
says no:

* `MIN_EPISODES` — a single exchange is not a conversation and does not buy a model call.
* `MAX_EPISODES_PER_GROUP` — the prompt is bounded, so one chatty afternoon cannot become
  one enormous request.
* `MAX_GROUPS_PER_TICK` — the fleet-wide ceiling on calls per hour, so a bad day for one
  tenant is not an unbounded bill.
* `DISTILL_MAX_TOKENS` — `EXTRACTION_MAX_TOKENS`' shape on the output side.
* `MAX_FACTS_PER_GROUP` — the model is asked for at most this many and the answer is
  truncated to it, because "cap the output tokens" does not by itself cap the ROWS.

Every call is metered through `record_ai_assist_usage`, the one door (hard rule 7): a
model call that spent our credential and wrote no `usage_events` row is money off the
books, whether or not a client asked for it.

IDEMPOTENCY IS `copilot_memories.distilled_at`, STAMPED IN THE SAME TRANSACTION as the
semantic rows it produced. A re-run — an arq retry, an overlapping tick, a redeploy — finds
those rows no longer in `ix_copilot_memories_pending_distillation` and does nothing. A
crash between the INSERT and the stamp rolls both back together, so the state "distilled
but not marked" (which would duplicate every fact on the next tick) is unrepresentable.
The second-order duplicate — the same fact learned twice from two different conversations
— is refused by the `NOT EXISTS` in `_INSERT_SEMANTIC_SQL`, so the semantic set converges
instead of growing.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from calevate_shared.engine import azure_openai_base_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.copilot.memory import KIND_EPISODIC, KIND_SEMANTIC, redacted_content
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT_MEMORY
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import chat
from apps.workers.extraction import AZURE_PROVIDER, azure_credentials

log = get_logger(__name__)

#: The minute this cron fires. :25, which is clear of every other fleet-wide fan-out in
#: `settings.CRON_JOBS` — the poller (:00/:10/...), `report_stalled_pipeline` (:05/:35) and
#: `reconcile_outstanding_calls` (:15/:45) — so three O(tenants) sweeps never share a
#: minute. Hourly rather than more often: the work is not urgent and the ceiling below is
#: per tick, so the cadence IS the spend rate.
DISTILL_MINUTE: Final = 25

#: How long a person's episodes on one screen must sit untouched before they are treated as
#: a finished conversation. 30 minutes: longer than any pause inside one working session,
#: short enough that the facts are available the same afternoon.
IDLE_WINDOW_MINUTES: Final = 30

#: Below this, a "conversation" is one question, and one question rarely contains a durable
#: fact about the business. Refusing it is the cheapest of the spend controls because it
#: costs nothing to evaluate.
MIN_EPISODES: Final = 2

#: The prompt bound. Ten exchanges is `copilot/schemas.MAX_HISTORY`'s five, doubled — the
#: browser already treats more than that as a new conversation.
MAX_EPISODES_PER_GROUP: Final = 10

#: THE FLEET-WIDE CEILING ON PAID CALLS PER TICK. Hourly cron, times this, is the most
#: model calls this feature can make in an hour, across every tenant. Deliberately small:
#: distillation is a nice-to-have and a backlog drains over hours, whereas an unbounded
#: fan-out over a table with a row per copilot turn is an incident.
MAX_GROUPS_PER_TICK: Final = 20

#: Per tenant, so one busy account cannot consume the whole tick and starve the rest — the
#: `TENANT_ROW_BUDGET` argument in `retention.py`, on calls instead of rows.
MAX_GROUPS_PER_TENANT: Final = 3

#: The output valve (`EXTRACTION_MAX_TOKENS`' shape). Sized to `MAX_FACTS_PER_GROUP` short
#: sentences of JSON with headroom, so it can only fire on a runaway. A hit surfaces as
#: `finish_reason == "length"`, which truncates the JSON, which fails the parse below and
#: is logged rather than half-written.
DISTILL_MAX_TOKENS: Final = 512

#: How many facts one conversation may yield. The prompt asks for at most this many AND the
#: answer is truncated to it: a token ceiling bounds the REQUEST's cost, not the number of
#: rows a compliant answer can create, and rows are what retention and erasure pay for.
MAX_FACTS_PER_GROUP: Final = 5

#: One fact, in characters. Short by design — "the clinic shuts Sunday" is the target shape,
#: and anything approaching a paragraph is a summary of the conversation rather than a fact
#: learned from it. Also the per-item ceiling `memory.RECALL_ITEM_CHARS` would truncate
#: anyway, so a longer row would be paid for and then cut.
MAX_FACT_CHARS: Final = 240

#: Whole-request timeout. Blocking call, nobody waiting on an HTTP connection — the same
#: reasoning `AzureOpenAIExtractor` gives for keeping the ARQ path's budget off the
#: edge-facing one.
DISTILL_TIMEOUT_S: Final = 30.0

_SYSTEM_PROMPT: Final = (
    "You read short records of a business owner's conversations with the assistant inside "
    "their own admin console, and you extract DURABLE FACTS ABOUT THEIR BUSINESS that "
    "would still be true next month.\n"
    "Good facts: opening hours, languages the owner writes in, services offered, how they "
    "want callers handled, names of their own products or plans.\n"
    "NOT facts: what the assistant did in one conversation, anything about one named "
    "individual, anything you are guessing at, and anything about a caller or customer.\n"
    "NEVER include a phone number, an email address, an identity number or a person's "
    "name, even if one appears in the records.\n"
    f'Answer with JSON only: {{"facts": ["..."]}} — at most {MAX_FACTS_PER_GROUP} '
    f"entries, each one short sentence under {MAX_FACT_CHARS} characters. "
    'If the records contain no durable fact, answer {"facts": []}. That is the expected '
    "answer most of the time and is better than inventing one."
)

#: THE TWO KINDS ARE INTERPOLATED FROM `copilot/memory.py`'S CONSTANTS, not retyped. They
#: were four string literals across the three statements below while `KIND_EPISODIC` /
#: `KIND_SEMANTIC` already existed and are what the writer and the recall use — a second
#: spelling of a closed vocabulary, which is the shape D-103/D-105 exist for. Interpolated
#: rather than bound because a `kind = :k` parameter would be a bind in a statement whose
#: partial index (`ix_copilot_memories_pending_distillation`) is defined over the literal;
#: `copilot/memory._RECALL_SQL` interpolates `SEARCH_CONFIG` the same way, and
#: `scripts/check_raw_sql.py` requires exactly this — a constant, never caller text.
#:
#: ONE ROW PER (person, screen) WHOSE CONVERSATION HAS GONE QUIET. `HAVING max(...)` is the
#: idle test, `count(*)` is `MIN_EPISODES`, and the partial index
#: `ix_copilot_memories_pending_distillation` is exactly this predicate's shape.
_GROUPS_SQL = f"""
SELECT user_id, screen_route, count(*) AS episodes
FROM copilot_memories
WHERE kind = '{KIND_EPISODIC}' AND distilled_at IS NULL
GROUP BY user_id, screen_route
HAVING count(*) >= :min_episodes
   AND max(created_at) < now() - make_interval(mins => :idle_minutes)
ORDER BY max(created_at)
LIMIT :limit
"""

#: OLDEST FIRST, so the bound is a WINDOW rather than a sample: the rows outside it stay
#: undistilled and are the head of the next tick's group, instead of being silently
#: dropped from a conversation that was then marked done.
_EPISODES_SQL = f"""
SELECT id, content FROM copilot_memories
WHERE kind = '{KIND_EPISODIC}' AND distilled_at IS NULL
  AND user_id = :uid AND screen_route IS NOT DISTINCT FROM :route
ORDER BY created_at
LIMIT :limit
"""

#: `NOT EXISTS` rather than a unique index, and the difference is what it is protecting
#: against. A UNIQUE (tenant_id, user_id, content) would make the second learning of a fact
#: an ERROR that aborts a transaction which has already inserted others; this makes it a
#: no-op. The set converges either way, and only one of the two leaves the tick running.
_INSERT_SEMANTIC_SQL = f"""
INSERT INTO copilot_memories
  (id, tenant_id, user_id, kind, content, screen_route, meta, created_at, updated_at)
SELECT :id, :tid, :uid, '{KIND_SEMANTIC}', :content, NULL, CAST(:meta AS jsonb), now(), now()
WHERE NOT EXISTS (
  SELECT 1 FROM copilot_memories
  WHERE kind = '{KIND_SEMANTIC}' AND user_id = :uid AND content = :content)
"""

_MARK_SQL = """
UPDATE copilot_memories SET distilled_at = now(), updated_at = now()
WHERE id = ANY(:ids) AND distilled_at IS NULL
"""


def _facts_of(content: str | None) -> list[str]:
    """The model's answer as a bounded list of short, redacted facts.

    EVERY BOUND IS APPLIED HERE AND NOT TRUSTED TO THE PROMPT. The system prompt asks for
    at most `MAX_FACTS_PER_GROUP` entries under `MAX_FACT_CHARS` characters and names the
    things it must not include; a model that ignores all three is an ordinary Tuesday, and
    the prompt is not where a bound is enforced (`copilot/service.validate_fill` makes the
    same argument about tool arguments, citing OWASP LLM01 #4). So: parsed strictly,
    truncated to the count, truncated to the length, and run through `redact` — which is
    what actually keeps an invented phone number out of a durable row, rather than the
    sentence in the prompt asking for it not to be.

    A malformed answer yields `[]` rather than raising: the episodes are still marked
    distilled by the caller, because re-sending the same conversation to the same model
    would spend the same money for the same answer.
    """
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except ValueError:
        log.warning("copilot_distil_unparsable")
        return []
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("facts")
    if not isinstance(raw, list):
        return []
    facts: list[str] = []
    for entry in raw[:MAX_FACTS_PER_GROUP]:
        if not isinstance(entry, str):
            continue
        fact = redacted_content(entry[:MAX_FACT_CHARS])
        if fact:
            facts.append(fact)
    return facts


async def _distil_group(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, route: str | None, leg: chat.ChatLeg
) -> int:
    """One conversation → semantic rows. Returns how many landed.

    The model call happens OUTSIDE no transaction of its own — it is inside the caller's,
    which is a departure from `copilot/routes.py`'s rule about not holding a pooled
    connection across a provider round trip, and the reason it is acceptable here is that
    nobody is waiting: this is a background worker with its own pool, not a streaming route
    contending with live requests. What it buys is that the semantic INSERTs and the
    `distilled_at` stamp cannot be separated by a crash.
    """
    episodes = (
        await session.execute(
            text(_EPISODES_SQL),
            {"uid": user_id, "route": route, "limit": MAX_EPISODES_PER_GROUP},
        )
    ).all()
    if len(episodes) < MIN_EPISODES:
        return 0
    ids = [UUID(str(row[0])) for row in episodes]
    record = "\n---\n".join(str(row[1]) for row in episodes)

    outcome = await chat.complete(
        leg,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": record},
        ],
        timeout_s=DISTILL_TIMEOUT_S,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=DISTILL_MAX_TOKENS,
    )
    if outcome.finish_reason == "length":
        # The valve fired. The JSON is truncated, so `_facts_of` will return nothing; the
        # log line is what tells an operator a run HIT the ceiling, which means it spent it.
        log.warning("copilot_distil_truncated", extra={"tenant_id": str(tenant_id)})

    facts = _facts_of(outcome.content)
    landed = 0
    for fact in facts:
        result = await session.execute(
            text(_INSERT_SEMANTIC_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "uid": user_id,
                "content": fact,
                # Counts and a provenance label. No prose, no ids of people (hard rule 6
                # and `copilot/models.CopilotMemory.meta`).
                "meta": json.dumps({"from": "distillation", "episodes": len(ids)}),
            },
        )
        landed += int(rowcount_of(result) or 0)

    # THE STAMP, in the same statement sequence as the inserts above and never after a
    # commit: this is the whole of the job's idempotency.
    await session.execute(text(_MARK_SQL), {"ids": ids})

    # HARD RULE 7. A model call that spent our credential is recorded, whether or not it
    # produced a fact — `usage` is None only when the provider declined to count, which is
    # the state `_sum_usage` refuses to fabricate a number for, so it is logged instead.
    if outcome.usage is not None:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            tokens_out=outcome.usage.output_tokens,
            # THE SETTING, NOT `leg.wire_model`, and getting this wrong would have been an
            # unfixable row on an append-only ledger. On Azure you deploy a model under an
            # id you choose and call THAT id (D-410/D-417), so `wire_model` is a DEPLOYMENT
            # name — `rates.llm_inr_per_ktok` publishes no price for it and would raise.
            # `meter_assist` reads the same live setting for the same reason: the model
            # behind Azure's deployment is an operator switch, not a per-run fact.
            model=get_settings().azure_openai_model,
            feature=ASSIST_FEATURE_COPILOT_MEMORY,
        )
    else:
        log.warning("copilot_distil_unmetered", extra={"tenant_id": str(tenant_id)})
    return landed


async def distil_copilot_memories(ctx: dict[str, Any]) -> str:
    """Hourly. Turn quiet copilot conversations into semantic memories, within a budget.

    THE TENANT LIST COMES FROM `retention_worklist`, not from a second bridge and not from
    an RLS exemption on a table holding client prose. `copilot_memories` is FORCE-RLS'd, so
    an `untenanted_session` sees zero rows of it — which is the property that makes this
    safe and also the one that makes the work invisible. D-368 already solved exactly that
    for `kb_sources`: `retention_worklist_ops_read` lets an untenanted session read TENANT
    IDS and nothing else, and migration `d4a9c17e6b02` puts an AFTER INSERT trigger on
    `copilot_memories` that registers the tenant under `reason = 'copilot_memory'`.

    ISOLATED PER TENANT. One account's provider error, malformed row or lock timeout must
    not end the tick for everyone behind it in the list — `apply_retention` learned that
    the same way. What DOES reach the retry ladder is a tick-wide failure (the worklist
    read, the pool, a missing credential), because retrying that is the only thing that
    could help.
    """
    credentials = azure_credentials()
    if credentials is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no language credential
        # runs every other queue. Not an alert — it is a configuration state an operator
        # already sees at `/healthz/ready`, and alerting hourly on it is how an alert
        # becomes noise.
        log.info("copilot_distil_no_provider", extra={"provider": AZURE_PROVIDER})
        return "no_provider"
    resource, api_key, deployment = credentials
    leg = chat.ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )

    try:
        async with untenanted_session() as session:
            tenants = [
                UUID(str(row))
                for row in (
                    await session.execute(
                        text(
                            "SELECT tenant_id FROM retention_worklist "
                            "WHERE reason = 'copilot_memory' ORDER BY tenant_id"
                        )
                    )
                )
                .scalars()
                .all()
            ]
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "copilot_distil_worklist_failed",
            detail="the distillation tick could not read the retention worklist",
            error=type(failure).__name__,
        )
        raise

    budget = MAX_GROUPS_PER_TICK
    distilled_groups = 0
    facts_written = 0
    for tenant_id in tenants:
        if budget <= 0:
            break
        try:
            async with tenant_session(tenant_id) as session:
                groups = (
                    await session.execute(
                        text(_GROUPS_SQL),
                        {
                            "min_episodes": MIN_EPISODES,
                            "idle_minutes": IDLE_WINDOW_MINUTES,
                            "limit": min(MAX_GROUPS_PER_TENANT, budget),
                        },
                    )
                ).all()
                for group in groups:
                    if budget <= 0:
                        break
                    budget -= 1
                    distilled_groups += 1
                    facts_written += await _distil_group(
                        session,
                        tenant_id=tenant_id,
                        user_id=UUID(str(group[0])),
                        route=None if group[1] is None else str(group[1]),
                        leg=leg,
                    )
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant's call. The episodes keep their NULL
            # `distilled_at`, so the next tick picks the same conversation up — which is
            # the correct behaviour for a transient failure and costs one hour.
            log.warning(
                "copilot_distil_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            log.exception("copilot_distil_tenant_failed", extra={"tenant_id": str(tenant_id)})

    log.info(
        "copilot_distil_tick",
        extra={
            "tenants": len(tenants),
            "groups": distilled_groups,
            "facts": facts_written,
            "budget_left": budget,
        },
    )
    return f"groups={distilled_groups} facts={facts_written}"


__all__ = [
    "DISTILL_MAX_TOKENS",
    "DISTILL_MINUTE",
    "IDLE_WINDOW_MINUTES",
    "MAX_EPISODES_PER_GROUP",
    "MAX_FACTS_PER_GROUP",
    "MAX_FACT_CHARS",
    "MAX_GROUPS_PER_TENANT",
    "MAX_GROUPS_PER_TICK",
    "MIN_EPISODES",
    "distil_copilot_memories",
]

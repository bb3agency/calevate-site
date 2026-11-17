"""Semantic distillation: turning a run of copilot episodes into durable business facts.

WHY THIS IS A CRON AND NOT PART OF THE COPILOT TURN, which is the whole design decision
and not a deployment detail. Distilling means reading a conversation back to a model. In a
live turn that is (a) latency a person is sitting in front of, on a surface whose entire
budget is `service.TOTAL_BUDGET_S`, and (b) the same tokens paid a second time, on a
surface already metered per answer. So it happens here, after the fact, in bulk, on a
clock — and `copilot/memory.py` writes episodic rows and returns without ever calling a
model.

ONCE A DAY, ONE CALL PER PERSON (D-982, founder, 10 Nov 2026). The run at
`DISTILL_HOUR`:`DISTILL_MINUTE` IST reads each person's undistilled episodes, across every
screen, in one model call. It was hourly per (person, screen), which bought several calls
a day for one busy owner; facts about a business do not go stale in a day, so one read of
the day's conversations is enough. A person whose newest episode is younger than
`IDLE_WINDOW_MINUTES` is mid-conversation and is read at the next run.

THE COST IS OURS (D-982). The spend is recorded under `ASSIST_FEATURE_COPILOT_MEMORY`,
which is in `billing.models.ABSORBED_ASSIST_FEATURES`: no client asks for it, so it never
counts against a client's monthly AI allowance. It is still metered (hard rule 7).

THE SPEND CONTROLS, because this job costs real money on a timer and nothing above it
says no:

* `MIN_EPISODES` — a single exchange is not a conversation and does not buy a model call.
* `MAX_EPISODES_PER_PERSON` — the prompt is bounded: the most recent episodes are read,
  and the older ones of that day are let go with them (stamped), so one chatty day can
  neither become one enormous request nor a backlog that is paid for again tomorrow.
* `MAX_PEOPLE_PER_RUN` and `MAX_PEOPLE_PER_TENANT` — the fleet-wide and per-account
  ceilings on calls per run; a backlog beyond them drains over the following days.
* `WalkBudget` — the run stops starting calls inside the worker's job timeout.
* `DISTILL_MAX_TOKENS` — `EXTRACTION_MAX_TOKENS`' shape on the output side.
* `MAX_FACTS_PER_GROUP` — the model is asked for at most this many and the answer is
  truncated to it, because "cap the output tokens" does not by itself cap the ROWS.

Every call is metered through `record_ai_assist_usage`, the one door (hard rule 7): a
model call that spent our credential and wrote no `usage_events` row is money off the
books, whether or not a client asked for it.

IDEMPOTENCY IS `copilot_memories.distilled_at`, STAMPED IN THE SAME TRANSACTION as the
semantic rows it produced. A re-run — an arq retry, an overlapping run, a redeploy — finds
those rows no longer in `ix_copilot_memories_pending_distillation` and does nothing. A
crash between the INSERT and the stamp rolls both back together, so the state "distilled
but not marked" (which would duplicate every fact on the next run) is unrepresentable.
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
from calevate_shared.backoff import jittered_delay_s
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import (
    new_assist_ref,
    platform_brake_tripped,
    record_ai_assist_usage,
)
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.copilot.memory import KIND_EPISODIC, KIND_SEMANTIC, redacted_content
from apps.api.core import provider_health
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT_MEMORY
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import chat
from apps.workers.background_leg import BackgroundLeg, background_leg
from apps.workers.extraction import azure_credentials
from apps.workers.fleet_walk import WalkBudget
from apps.workers.set_aside import (
    REFUSED_INPUT_SET_ASIDE,
    RefusalStreak,
    set_aside,
    set_aside_ids,
)

log = get_logger(__name__)

#: The `set_aside` name for conversations the provider refused to read.
_SET_ASIDE_SWEEP: Final = "copilot_distil"


#: When the daily run fires, in IST (`settings.CRON_TIMEZONE`): 03:25, when nobody is in the
#: console and no other fleet-wide walk fires (the daily ones start at 04:00; :25 is no
#: hourly walk's minute). Once a day, so the cadence IS the spend rate: at most
#: `MAX_PEOPLE_PER_RUN` calls a day.
DISTILL_HOUR: Final = 3
DISTILL_MINUTE: Final = 25

#: How long a person's newest episode must sit untouched before their conversations are
#: treated as finished. 30 minutes: longer than any pause inside one working session.
IDLE_WINDOW_MINUTES: Final = 30

#: Below this, a "conversation" is one question, and one question rarely contains a durable
#: fact about the business. Refusing it is the cheapest of the spend controls because it
#: costs nothing to evaluate.
MIN_EPISODES: Final = 2

#: The prompt bound for one person's day: `copilot/schemas.MAX_HISTORY`'s five exchanges,
#: four times, the most recent ones.
MAX_EPISODES_PER_PERSON: Final = 20

#: THE FLEET-WIDE CEILING ON PAID CALLS PER RUN, and so per day. A backlog beyond it (a
#: first run after deploy, a day the provider was down) drains over the next few days;
#: an unbounded fan-out over a table with a row per Pip turn is an incident.
MAX_PEOPLE_PER_RUN: Final = 60

#: Per tenant, so one busy account cannot consume the whole run and starve the rest — the
#: `TENANT_ROW_BUDGET` argument in `retention.py`, on calls instead of rows.
MAX_PEOPLE_PER_TENANT: Final = 10

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
#: ONE ROW PER PERSON WHOSE CONVERSATIONS HAVE GONE QUIET, across every screen. `HAVING
#: max(...)` is the idle test, `count(*)` is `MIN_EPISODES`, and the partial index
#: `ix_copilot_memories_pending_distillation` leads with (tenant_id, user_id).
#:
#: `:set_aside` leaves out people whose conversations the provider refused, who would
#: otherwise head every run.
_PEOPLE_SQL = f"""
SELECT user_id, count(*) AS episodes
FROM copilot_memories
WHERE kind = '{KIND_EPISODIC}' AND distilled_at IS NULL
  AND NOT (user_id::text = ANY(CAST(:set_aside AS text[])))
GROUP BY user_id
HAVING count(*) >= :min_episodes
   AND max(created_at) < now() - make_interval(mins => :idle_minutes)
ORDER BY max(created_at)
LIMIT :limit
"""

#: NEWEST FIRST: the most recent episodes are the ones read; the caller puts them back in
#: order for the prompt and stamps the older ones with them (`_MARK_SQL`).
_EPISODES_SQL = f"""
SELECT id, content, created_at FROM copilot_memories
WHERE kind = '{KIND_EPISODIC}' AND distilled_at IS NULL AND user_id = :uid
ORDER BY created_at DESC, id DESC
LIMIT :limit
"""

#: `NOT EXISTS` rather than a unique index, and the difference is what it is protecting
#: against. A UNIQUE (tenant_id, user_id, content) would make the second learning of a fact
#: an ERROR that aborts a transaction which has already inserted others; this makes it a
#: no-op. The set converges either way, and only one of the two leaves the run going.
_INSERT_SEMANTIC_SQL = f"""
INSERT INTO copilot_memories
  (id, tenant_id, user_id, kind, content, screen_route, meta, created_at, updated_at)
SELECT :id, :tid, :uid, '{KIND_SEMANTIC}', :content, NULL, CAST(:meta AS jsonb), now(), now()
WHERE NOT EXISTS (
  SELECT 1 FROM copilot_memories
  WHERE kind = '{KIND_SEMANTIC}' AND user_id = :uid AND content = :content)
"""

#: Every undistilled episode of the person up to the newest one read: the ones read, and the
#: older ones of a day past `MAX_EPISODES_PER_PERSON`, which are let go rather than paid for
#: in a second call. One written after the read is newer and waits for the next run.
_MARK_SQL = f"""
UPDATE copilot_memories SET distilled_at = now(), updated_at = now()
WHERE kind = '{KIND_EPISODIC}' AND distilled_at IS NULL AND user_id = :uid
  AND (created_at < :upto OR id = ANY(:ids))
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


#: Gemini's answer shape. Its OpenAI-compatible surface is driven by `json_schema` on every
#: other Gemini assist here (`business_copy`, `teach_questions`, `script_assist`); Azure keeps
#: the `json_object` it has always been sent.
_GEMINI_FORMAT: Final[dict[str, Any]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "copilot_memory_facts",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
            "required": ["facts"],
            "additionalProperties": False,
        },
    },
}


async def _distil_person(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    distil: BackgroundLeg,
) -> int:
    """One person's quiet conversations → semantic rows. Returns how many landed.

    The model call happens OUTSIDE no transaction of its own — it is inside the caller's,
    which is a departure from `copilot/routes.py`'s rule about not holding a pooled
    connection across a provider round trip, and the reason it is acceptable here is that
    nobody is waiting: this is a background worker with its own pool, not a streaming route
    contending with live requests. What it buys is that the semantic INSERTs and the
    `distilled_at` stamp cannot be separated by a crash.
    """
    newest_first = (
        await session.execute(
            text(_EPISODES_SQL), {"uid": user_id, "limit": MAX_EPISODES_PER_PERSON}
        )
    ).all()
    if len(newest_first) < MIN_EPISODES:
        return 0
    episodes = list(reversed(newest_first))
    ids = [UUID(str(row[0])) for row in episodes]
    upto = newest_first[0][2]
    record = "\n---\n".join(str(row[1]) for row in episodes)

    leg = distil.leg
    async with provider_health.watch("memory", chat.provider_of(leg), model=leg.wire_model):
        outcome, tier = await distil.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": record},
            ],
            timeout_s=DISTILL_TIMEOUT_S,
            temperature=0,
            response_format=_GEMINI_FORMAT if distil.is_gemini else {"type": "json_object"},
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
    await session.execute(text(_MARK_SQL), {"uid": user_id, "upto": upto, "ids": ids})

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
            cached_tokens_in=outcome.usage.cached_tokens_in,
            # `_distil_leg` says what the leg is priced as; on Azure that is the setting,
            # never the deployment id the call was addressed to.
            model=distil.meter_model,
            feature=ASSIST_FEATURE_COPILOT_MEMORY,
            service_tier=tier,
        )
    else:
        log.warning("copilot_distil_unmetered", extra={"tenant_id": str(tenant_id)})
    return landed


async def distil_copilot_memories(ctx: dict[str, Any]) -> str:
    """Daily. Turn each person's quiet Pip conversations into semantic memories, one model
    call per person, within a budget.

    THE TENANT LIST COMES FROM `retention_worklist`, not from a second bridge and not from
    an RLS exemption on a table holding client prose. `copilot_memories` is FORCE-RLS'd, so
    an `untenanted_session` sees zero rows of it — which is the property that makes this
    safe and also the one that makes the work invisible. D-368 already solved exactly that
    for `kb_sources`: `retention_worklist_ops_read` lets an untenanted session read TENANT
    IDS and nothing else, and migration `d4a9c17e6b02` puts an AFTER INSERT trigger on
    `copilot_memories` that registers the tenant under `reason = 'copilot_memory'`.

    ISOLATED PER TENANT. One account's provider error, malformed row or lock timeout must
    not end the run for everyone behind it in the list — `apply_retention` learned that
    the same way. What DOES reach the retry ladder is a run-wide failure (the worklist
    read, the pool, a missing credential), because retrying that is the only thing that
    could help.
    """
    distil = background_leg(azure_credentials(), call="copilot_memory")
    if distil is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no language credential
        # runs every other queue. Not an alert — it is a configuration state an operator
        # already sees at `/healthz/ready` (and, for a Gemini key that cannot serve, in
        # `assistant_gemini_unavailable`), and alerting daily on it is how an alert
        # becomes noise.
        log.info("copilot_distil_no_provider")
        return "no_provider"

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
            brake = await platform_brake_tripped(session)
    except Exception as failure:
        attempt = job_try(ctx)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=jittered_delay_s(attempt * 30)) from failure
        alert(
            "WORKER_TERMINAL",
            "copilot_distil_worklist_failed",
            detail="the distillation run could not read the retention worklist",
            error=type(failure).__name__,
        )
        raise

    if brake:
        # The platform's AI brake pauses dashboard AI for every account, and this sweep spends
        # on the same key. Read rather than raised (`caller_embeddings`' reason): a tripped
        # brake is a ceiling working, not a broken job. Episodes keep their NULL
        # `distilled_at` and are read after the IST month rolls over.
        log.warning("copilot_distil_brake_tripped")
        return "brake_tripped"

    budget = MAX_PEOPLE_PER_RUN
    clock = WalkBudget()
    distilled_people = 0
    facts_written = 0
    failed = 0
    excluded = await set_aside_ids(_SET_ASIDE_SWEEP)
    for tenant_id in tenants:
        if budget <= 0 or clock.spent():
            break
        try:
            async with tenant_session(tenant_id) as session:
                # An owner who turned Pip off has withdrawn the account from the
                # language-model providers, so its past conversations are not read back to
                # one either. Their episodes keep a NULL `distilled_at` until Pip is on again.
                if not await account_content_may_reach_models(session, tenant_id=tenant_id):
                    continue
                people = (
                    await session.execute(
                        text(_PEOPLE_SQL),
                        {
                            "min_episodes": MIN_EPISODES,
                            "idle_minutes": IDLE_WINDOW_MINUTES,
                            "limit": min(MAX_PEOPLE_PER_TENANT, budget),
                            "set_aside": excluded,
                        },
                    )
                ).all()
            refusals = RefusalStreak()
            for person in people:
                if budget <= 0 or clock.spent():
                    break
                budget -= 1
                distilled_people += 1
                user_id = UUID(str(person[0]))
                # ONE TRANSACTION PER PERSON, not per tenant. Each model call is paid for the
                # moment it returns, and its facts, stamp and `usage_events` rows must commit
                # with it: sharing the tenant's transaction let a provider error on a LATER
                # person roll all three back, so the spend went unrecorded (hard rule 7) and
                # the next run paid for the same conversations again.
                try:
                    async with tenant_session(tenant_id) as session:
                        facts_written += await _distil_person(
                            session, tenant_id=tenant_id, user_id=user_id, distil=distil
                        )
                except httpx.HTTPStatusError as failure:
                    if not chat.refused_this_input(failure):
                        raise
                    # A refusal of THESE conversations: asked again only after a while, so
                    # they cannot head every run and keep the people behind from being read.
                    log.warning("copilot_distil_input_refused", extra={"tenant_id": str(tenant_id)})
                    await set_aside(_SET_ASIDE_SWEEP, [str(user_id)], for_=REFUSED_INPUT_SET_ASIDE)
                    if refusals.refused():
                        break
                    continue
                refusals.answered()
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant's call. The episodes keep their NULL
            # `distilled_at`, so the next run picks the same conversations up — the
            # correct behaviour for a transient failure, and it costs one day.
            log.warning(
                "copilot_distil_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            # Isolated so one tenant cannot end the run for the rest, and counted so a
            # failure that repeats every run (a row that always crashes) still alarms.
            log.exception("copilot_distil_tenant_failed", extra={"tenant_id": str(tenant_id)})
            failed += 1

    if failed:
        alert(
            "WORKER_TERMINAL",
            "copilot_distil_sweep_incomplete",
            detail=(
                f"{failed} of {len(tenants)} tenant(s) failed the Pip memory distillation "
                "sweep; their conversations stay undistilled and the sweep runs again "
                "tomorrow"
            ),
        )

    log.info(
        "copilot_distil_tick",
        extra={
            "tenants": len(tenants),
            "people": distilled_people,
            "facts": facts_written,
            "budget_left": budget,
            "out_of_time": clock.exhausted,
        },
    )
    return f"people={distilled_people} facts={facts_written}"


__all__ = [
    "DISTILL_HOUR",
    "DISTILL_MAX_TOKENS",
    "DISTILL_MINUTE",
    "IDLE_WINDOW_MINUTES",
    "MAX_EPISODES_PER_PERSON",
    "MAX_FACTS_PER_GROUP",
    "MAX_FACT_CHARS",
    "MAX_PEOPLE_PER_RUN",
    "MAX_PEOPLE_PER_TENANT",
    "MIN_EPISODES",
    "distil_copilot_memories",
]

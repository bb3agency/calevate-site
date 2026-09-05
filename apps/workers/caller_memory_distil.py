"""What a finished call taught us about the PERSON who rang — the producer (D-513).

`apps/api/compliance/caller_memory.py` built the store, both erasure arms, the 180-day
clock and the spoken sentence, and closed its header with the gap this file fills:
"NOTHING WRITES A CALLER MEMORY TODAY ... it belongs in the shape of
`workers/copilot_memory.py` — bounded facts per call, `redact()` on the way in, metered
through `record_ai_assist_usage` (hard rule 7), and running ONLY for agents whose switch
is on, so the default costs nothing." That is this job, clause by clause.

--------------------------------------------------------------------------------
WHY A CRON AND NOT THE POST-CALL PIPELINE
--------------------------------------------------------------------------------
`copilot_memory.py`'s argument transfers whole and is not repeated; what does NOT transfer
is the reason it matters more here. The post-call pipeline is on the path a client watches:
a call ends, a lead appears. Hanging a second model call off it makes every client's
pipeline slower and every client's bill larger for a feature almost none of them have
switched on. Here the fan-out starts from the switch, so a deployment where nobody has
enabled memory makes ZERO model calls and the feature genuinely costs nothing.

--------------------------------------------------------------------------------
THE IDEMPOTENCY MARKER, WHICH IS THE PART THAT HAD TO BE INVENTED
--------------------------------------------------------------------------------
`caller_memories.source_call_id` cannot be the key. It records that a call PRODUCED a fact
and has no way to record that a call was READ AND OWED NOTHING — which is what most calls
owe. Without a durable negative, a retry, an overlapping tick or a redeploy re-sends the
same transcript to the same model, pays for the same answer, and files a second row
whenever the model phrases it differently. `kb_documents.gloss_state` exists for exactly
this and is the shape copied: `calls.caller_memory_state`, four values
(`compliance.caller_memory.CALLER_MEMORY_STATES`), stamped in the SAME transaction as the
rows it describes so "distilled but not marked" is unrepresentable.

--------------------------------------------------------------------------------
WHAT MAY BE REMEMBERED (the founder's decision, 2 Sep 2026)
--------------------------------------------------------------------------------
What the caller WANTED, what the OUTCOME was, and their stated PREFERENCES — the language
they prefer, when they like to be called, which staff member they usually deal with.

NOT health specifics, NOT money figures, NOT quotes. The prompt says so and the prompt is
not where a bound is enforced (`copilot/service.validate_fill`, OWASP LLM01 #4), so
`_REFUSED` below is the validator that actually holds it, and
`caller_memory.SPDI_REFUSED_VERTICALS` is the structural belt above both: on a clinic the
whole feature is refused, because "asked about IVF pricing" IS an inference about a health
condition and SPDI Rule 5(1) wants consent in writing, which a phone call cannot give.

--------------------------------------------------------------------------------
STALENESS AND CONTRADICTION — the two failure modes of long-term agent memory
--------------------------------------------------------------------------------
Both are well-known and neither is solved by remembering harder. Read before designing:
Packer et al., *MemGPT* (arXiv:2310.08560) on bounded context and eviction; the LangMem /
"Memory for agents" write-ups on the semantic-vs-episodic split; and OWASP's LLM01
(indirect prompt injection) for why the third one below is a security control and not a
quality one. What this design takes from them, and where it deliberately departs:

* **Contradiction is resolved by RECENCY, not by reconciliation.** `remember()` writes a
  NEW row rather than upserting (its own docstring argues why), `recall()` orders
  `occurred_at DESC` and takes `RECALL_LIMIT`, and the clock expires the rest at 180 days.
  So a caller who said "call me mornings" in June and "call me after 8pm" in August is read
  back August-first, and June falls off the end of the window without anybody adjudicating
  it. The alternative — asking a model to merge an old fact with a new one — is a second
  model call, on a durable store, whose failure mode is a CONFABULATED fact that neither
  call contained. Recency is worse at precision and cannot invent anything, and on a store
  that outlives the conversation that is the correct trade.
* **The prompt states the recency rule to the model too**, because ordering alone is not
  visible to it: `CALLER_MEMORY_GUIDANCE` tells it to refer to at most one thing and to
  accept a correction and move on. A caller correcting a stale note is the outcome this
  degrades to, and it is a survivable one.
* **Unbounded growth is bounded three times** — facts per call (`MAX_FACTS_PER_CALL`),
  facts per recall (`RECALL_LIMIT`), characters per injected block
  (`MAX_CALLER_MEMORY_CHARS`) — and rows die on their own clock.
* **A remembered sentence can never become an instruction.** The store neuters fence runs
  at the write (`clean_fact`), the prompt section labels the block as a record and restates
  the label after it, and `TRUTHFUL_ANSWER_DIRECTIVE` still comes last.

--------------------------------------------------------------------------------
BOTH DIRECTIONS FEED MEMORY (the founder's decision, taken knowingly)
--------------------------------------------------------------------------------
Inbound AND outbound. The tempting restriction is inbound-only — a person who rang US
chose to — but it makes the product incoherent: the same caller, the same agent, the same
business, and whether the agent remembers them depends on who dialled. The notice is the
same sentence on both legs (`compose_opening_line` is direction-blind), so the disclosure
argument does not distinguish them either.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from calevate_shared.engine import azure_openai_base_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.compliance.caller_memory import (
    CALLER_MEMORY_NOTHING,
    CALLER_MEMORY_PENDING,
    CALLER_MEMORY_REMEMBERED,
    CALLER_MEMORY_SKIPPED,
    MAX_FACT_CHARS,
    MAX_FACTS_PER_CALL,
    clean_fact,
    remember,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.crm.assist import ASSIST_FEATURE_CALLER_MEMORY
from apps.api.db.session import tenant_session
from apps.workers import chat
from apps.workers.caller_embeddings import tenants_with_caller_data
from apps.workers.extraction import AZURE_PROVIDER, azure_credentials

log = get_logger(__name__)

#: The minute this cron fires. :50, which is clear of every other fleet-wide fan-out in
#: `settings.CRON_JOBS` — the poller (:00/:10/...), `report_stalled_pipeline` (:05/:35),
#: `reconcile_outstanding_calls` (:15/:45) and `distil_copilot_memories` (:25) — so no two
#: O(tenants) sweeps share a minute. Hourly, because a returning caller's next call is
#: hours away at best and the ceiling below is per tick, so the cadence IS the spend rate.
DISTIL_MINUTE: Final = 50

#: How long after a call ends before it is considered finished enough to read.
#:
#: The post-call pipeline writes turns, then the redacted text, then the extraction. A
#: distillation that ran the instant `ended_at` landed would read a half-written transcript
#: — worse, it would MARK it, so the missing half would never be read at all. Fifteen
#: minutes is comfortably past `report_stalled_pipeline`'s own alarm threshold for the same
#: pipeline, which is the repo's existing answer to "when is a call's derived data done".
SETTLE_MINUTES: Final = 15

#: How far back a tick will look. A call older than this is left `pending` for ever and
#: never distilled, deliberately: the feature is "the agent remembers you", and a memory
#: minted from a conversation nobody has thought about in a fortnight is not worth a model
#: call. It also bounds the damage of switching the feature ON for a busy account — the
#: backlog is a fortnight of that agent's calls, not its whole history.
LOOKBACK_DAYS: Final = 14

#: THE FLEET-WIDE CEILING ON PAID CALLS PER TICK. Hourly, times this, is the most model
#: calls this feature can make in an hour across every tenant. `copilot_memory`'s number and
#: its argument.
MAX_CALLS_PER_TICK: Final = 20

#: Per tenant, so one busy account cannot consume the whole tick and starve the rest —
#: `retention.TENANT_ROW_BUDGET`'s argument, on model calls instead of rows.
MAX_CALLS_PER_TENANT: Final = 3

#: A call with fewer turns than this is marked `nothing` WITHOUT a model call. Two turns is
#: a greeting and a hang-up; there is no "what they wanted" in it, and refusing it is the
#: cheapest spend control because it costs one integer comparison.
MIN_TURNS: Final = 4

#: The transcript window handed to the model, oldest first. A phone call that runs longer
#: than this has its opening — which is where "what they wanted" is said — inside the
#: window, and its tail is what gets cut.
MAX_TURNS_PER_CALL: Final = 60

#: The output valve (`EXTRACTION_MAX_TOKENS`' shape). Sized to `MAX_FACTS_PER_CALL` short
#: sentences of JSON with headroom, so it can only fire on a runaway. A hit surfaces as
#: `finish_reason == "length"`, which truncates the JSON, which fails the parse below and
#: is logged rather than half-written.
DISTIL_MAX_TOKENS: Final = 256

#: Whole-request timeout. Blocking call, nobody waiting on an HTTP connection —
#: `AzureOpenAIExtractor`'s reasoning for keeping the ARQ path's budget off the edge one.
DISTIL_TIMEOUT_S: Final = 30.0

_SYSTEM_PROMPT: Final = (
    "You read a transcript of ONE phone call between a business's AI receptionist and a "
    "caller, and you write down what the business should remember about THAT CALLER if "
    "they ring again in a few weeks.\n"
    "Write only these three kinds of thing:\n"
    "1. What the caller wanted (e.g. 'asked about weekend appointment slots').\n"
    "2. What the outcome was (e.g. 'booked for Saturday morning').\n"
    "3. A preference they stated: the language they prefer, when they like to be called, "
    "or which staff member they usually deal with.\n"
    "NEVER write: any health, medical or treatment detail; any amount of money, price, "
    "quote or payment detail; anything about their family, religion, caste, politics or "
    "finances; a phone number, an email address or an identity number; or a quotation of "
    "anything anyone said. Write a short factual note, never a sentence in the caller's "
    "own words.\n"
    "Write nothing you are guessing at, and nothing about the business itself — only "
    "about this caller.\n"
    f'Answer with JSON only: {{"facts": ["..."]}} — at most {MAX_FACTS_PER_CALL} entries, '
    f"each one short note under {MAX_FACT_CHARS} characters. If the call taught you "
    'nothing worth remembering about the caller, answer {"facts": []}. That is the '
    "expected answer most of the time and is better than inventing one."
)

#: DISCOVERY. One statement, and every clause in it is load-bearing:
#:
#: * `a.caller_memory_enabled` — the fan-out STARTS from the switch, so a tenant with the
#:   feature off contributes no rows and therefore no model calls (the "default costs
#:   nothing" clause of the gap note). It is re-checked inside `remember()` too; that arm
#:   is the one that matters if the switch moves between this read and the write.
#: * `c.from_e164 IS NOT NULL` — the subject key is derived from the number, and a call
#:   whose number a DPDP erasure has already NULLed has no subject to file a fact under.
#'   Such a call is marked `skipped`, not left pending, below.
#: * `c.status = 'completed'` — a failed or abandoned dial has no conversation in it.
#: * the settle and lookback windows, argued at their constants.
#:
#: OLDEST FIRST, so a truncated tick resumes where it stopped rather than re-shuffling, and
#: so the partial index `ix_calls_caller_memory_pending` (agent_id, ended_at) is an index
#: range rather than a sort.
_PENDING_CALLS_SQL: Final = f"""
SELECT c.id, c.agent_id, c.from_e164, c.ended_at
FROM calls c JOIN agents a ON a.id = c.agent_id
WHERE c.caller_memory_state = '{CALLER_MEMORY_PENDING}'
  AND a.caller_memory_enabled
  AND c.status = 'completed'
  AND c.ended_at IS NOT NULL
  AND c.ended_at < now() - make_interval(mins => :settle_minutes)
  AND c.ended_at > now() - make_interval(days => :lookback_days)
ORDER BY c.ended_at
LIMIT :limit
"""

#: THE REDACTED TEXT AND NEVER THE RAW (hard rule 5: "transcripts default to
#: `text_redacted` in every API response"). This is not an API response, and the rule's
#: reason still applies with more force: what is distilled here is written to a store that
#: OUTLIVES the call and is read back to a stranger's model on a later one, so the identifiers
#: must be gone before the model sees them and not merely before the row is written.
#: `clean_fact`'s `redact()` is the backstop for what the model invents, not the first pass.
#:
#: A turn whose redaction has not landed yet is skipped rather than substituted with `text`
#: — `COALESCE(text_redacted, text)` is the shape that would quietly ship raw transcript to
#: a model, and the settle window exists so this is empty rather than common.
_TURNS_SQL: Final = """
SELECT speaker, text_redacted FROM transcript_turns
WHERE call_id = :cid AND text_redacted IS NOT NULL AND text_redacted <> ''
ORDER BY idx LIMIT :limit
"""

_MARK_SQL: Final = """
UPDATE calls SET caller_memory_state = :state, updated_at = now()
WHERE id = :cid AND caller_memory_state = :pending
"""

#: WORDS THAT MEAN THE MODEL IGNORED THE SCOPE, checked against the note it produced.
#:
#: THE PROMPT IS NOT WHERE A BOUND IS ENFORCED, and this is the founder's scope decision
#: made enforceable: money figures and health specifics are refused whatever the sentence
#: above asked for. Deliberately CRUDE — a currency symbol, a digit run that looks like an
#: amount, and a small vocabulary of clinical words — because the alternative is a
#: classifier over free text, which `SPDI_REFUSED_VERTICALS` already records as the thing
#: that "no classifier over free text can be trusted to decide". This is not that classifier
#: and does not pretend to be: it is a coarse refusal on the tail of an already-narrow
#: instruction, and the structural control remains the vertical refusal above it.
#:
#: A refused fact is DROPPED, not the whole call: the other facts from the same answer are
#: still good, and discarding them would make one bad sentence cost the memory of the call.
_REFUSED_SUBSTRINGS: Final[tuple[str, ...]] = (
    "₹",
    "rs.",
    "rupee",
    "inr ",
    "price",
    "cost",
    "quote",
    "fee",
    "paid",
    "payment",
    "diagnos",
    "symptom",
    "treatment",
    "medicine",
    "medication",
    "prescription",
    "surgery",
    "pregnan",
    "disease",
    "illness",
    "patient",
)


def within_scope(fact: str) -> bool:
    """Is this note inside what the founder decided may be remembered?

    PUBLIC and separately testable, because it is the enforceable half of a decision that
    is otherwise only a paragraph in a prompt — and a decision whose only expression is a
    prompt is a decision a model may decline to implement.
    """
    lowered = fact.lower()
    if any(marker in lowered for marker in _REFUSED_SUBSTRINGS):
        return False
    # A run of three or more digits is a figure — an amount, a reference, a date of birth.
    # `redact()` catches the shapes it knows (phone, email, identity numbers); this catches
    # the ones it does not, at the cost of refusing "asked about slots after 6" only when
    # the number is long enough to be a value rather than a time.
    return sum(char.isdigit() for char in fact) < 3


def facts_of(content: str | None) -> list[str]:
    """The model's answer as a bounded list of short, in-scope, redacted notes.

    EVERY BOUND IS APPLIED HERE AND NOT TRUSTED TO THE PROMPT (`copilot_memory._facts_of`'s
    argument, and OWASP LLM01 #4). Parsed strictly, truncated to the count, filtered by
    `within_scope`, and finished by `clean_fact` — which is the ONE way text becomes a fact
    row and carries the redaction and the fence-neutering with it.

    A malformed answer yields `[]` rather than raising: the call is still marked by the
    caller, because re-sending the same transcript to the same model would spend the same
    money for the same answer.
    """
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except ValueError:
        log.warning("caller_memory_distil_unparsable")
        return []
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("facts")
    if not isinstance(raw, list):
        return []
    facts: list[str] = []
    for entry in raw[:MAX_FACTS_PER_CALL]:
        if not isinstance(entry, str):
            continue
        if not within_scope(entry):
            # KINDS AND COUNTS, NEVER THE TEXT (hard rule 6). This is how an operator learns
            # the distiller is drifting out of scope, which no request-side check can see.
            log.warning("caller_memory_fact_out_of_scope")
            continue
        fact = clean_fact(entry)
        if fact:
            facts.append(fact)
    return facts


async def _distil_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    agent_id: UUID,
    phone_e164: str,
    occurred_at: datetime,
    leg: chat.ChatLeg,
) -> tuple[int, bool]:
    """One finished call → memory rows. Returns (rows written, whether a model was called).

    THE MODEL CALL IS INSIDE THE CALLER'S TRANSACTION, which is `copilot_memory.
    _distil_group`'s departure from `copilot/routes.py`'s no-connection-across-a-round-trip
    rule, taken here for the same reason: nobody is waiting, this worker has its own pool,
    and what it buys is that the rows and the `caller_memory_state` stamp cannot be
    separated by a crash. A crash mid-call rolls both back and the row stays `pending`,
    which costs one hour and one repeated model call — the only duplicate this design
    permits, and it is bounded by the tick.
    """
    turns = (
        await session.execute(text(_TURNS_SQL), {"cid": call_id, "limit": MAX_TURNS_PER_CALL})
    ).all()
    if len(turns) < MIN_TURNS:
        # Settled without spending anything. `nothing` and not `skipped`: this call WAS
        # looked at and the answer was no, which is the distinction the two values carry.
        await _mark(session, call_id, CALLER_MEMORY_NOTHING)
        return 0, False

    transcript = "\n".join(f"{row[0]}: {row[1]}" for row in turns)
    outcome = await chat.complete(
        leg,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        timeout_s=DISTIL_TIMEOUT_S,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=DISTIL_MAX_TOKENS,
    )
    if outcome.finish_reason == "length":
        # The valve fired. The JSON is truncated, so `facts_of` returns nothing; the log
        # line is what tells an operator a run HIT the ceiling, which means it spent it.
        log.warning("caller_memory_distil_truncated", extra={"call_id": str(call_id)})

    facts = facts_of(outcome.content)
    written = await remember(
        session,
        tenant_id,
        agent_id=agent_id,
        phone_e164=phone_e164,
        # THE SOURCE CALL'S CLOCK AND NEVER `now()` — `remember()`'s own rule, and the
        # reason is the retention period: a backfill stamped tonight would restart every
        # caller's 180 days because a background job read their data.
        occurred_at=occurred_at,
        source_call_id=call_id,
        facts=facts,
    )
    # THE STAMP, in the same statement sequence as the rows above and never after a commit:
    # this is the whole of the job's idempotency. `remember()` returning 0 for a switch that
    # moved between discovery and write lands here as `nothing`, which is accurate — nothing
    # was remembered — and stops the call being re-bought every hour for ever.
    await _mark(session, call_id, CALLER_MEMORY_REMEMBERED if written else CALLER_MEMORY_NOTHING)

    # HARD RULE 7. A model call that spent our credential is recorded whether or not it
    # produced a fact. `usage` is None only when the provider declined to count, which is
    # the state `_sum_usage` refuses to fabricate a number for, so it is logged instead.
    if outcome.usage is not None:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            tokens_out=outcome.usage.output_tokens,
            # THE SETTING, NOT `leg.wire_model` — `copilot_memory`'s reason: on Azure
            # `wire_model` is a DEPLOYMENT name (D-410/D-417), for which
            # `rates.llm_inr_per_ktok` publishes no price and would raise.
            model=get_settings().azure_openai_model,
            feature=ASSIST_FEATURE_CALLER_MEMORY,
        )
    else:
        log.warning("caller_memory_distil_unmetered", extra={"call_id": str(call_id)})
    return written, True


async def _mark(session: AsyncSession, call_id: UUID, state: str) -> None:
    """Settle one call's marker. Guarded on `pending`, so a concurrent tick's stamp wins
    rather than being overwritten by a slower one that read the same row."""
    await session.execute(
        text(_MARK_SQL), {"cid": call_id, "state": state, "pending": CALLER_MEMORY_PENDING}
    )


async def _sweep_tenant(
    session: AsyncSession, *, tenant_id: UUID, leg: chat.ChatLeg, budget: int
) -> tuple[int, int]:
    """One tenant's share of the tick. Returns (model calls spent, facts written)."""
    rows = (
        await session.execute(
            text(_PENDING_CALLS_SQL),
            {
                "settle_minutes": SETTLE_MINUTES,
                "lookback_days": LOOKBACK_DAYS,
                "limit": min(MAX_CALLS_PER_TENANT, budget),
            },
        )
    ).all()
    spent = 0
    facts = 0
    for row in rows:
        if spent >= budget:
            break
        call_id = UUID(str(row[0]))
        phone = None if row[2] is None else str(row[2])
        if not phone:
            # No subject to file a fact under: an erasure has already NULLed the number, or
            # the poller never learned it. `skipped`, because no model was asked — and
            # settled rather than left pending, so it is not re-discovered every hour for
            # a fortnight.
            await _mark(session, call_id, CALLER_MEMORY_SKIPPED)
            continue
        written, spent_a_call = await _distil_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            agent_id=UUID(str(row[1])),
            phone_e164=phone,
            occurred_at=row[3],
            leg=leg,
        )
        facts += written
        spent += 1 if spent_a_call else 0
    return spent, facts


async def distil_caller_memories(ctx: dict[str, Any]) -> str:
    """Hourly. Turn finished calls into what an agent remembers about its callers.

    ISOLATED PER TENANT, for `copilot_memory`'s reason: one account's provider error,
    malformed row or lock timeout must not end the tick for everyone behind it. What DOES
    reach the retry ladder is a tick-wide failure (the worklist read, the pool, a missing
    credential), because retrying that is the only thing that could help.
    """
    credentials = azure_credentials()
    if credentials is None:
        # Tolerant boot (BACKEND-PATTERNS §2): a deployment with no language credential runs
        # every other queue. Not an alert — it is a configuration state an operator already
        # sees at `/healthz/ready`, and alerting hourly on it is how an alert becomes noise.
        log.info("caller_memory_distil_no_provider", extra={"provider": AZURE_PROVIDER})
        return "no_provider"
    resource, api_key, deployment = credentials
    leg = chat.ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )

    try:
        tenants = await tenants_with_caller_data()
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "caller_memory_distil_worklist_failed",
            detail="the caller-memory distillation tick could not read its worklist",
            error=type(failure).__name__,
        )
        raise

    budget = MAX_CALLS_PER_TICK
    facts_written = 0
    for tenant_id in tenants:
        if budget <= 0:
            break
        try:
            async with tenant_session(tenant_id) as session:
                spent, facts = await _sweep_tenant(
                    session, tenant_id=tenant_id, leg=leg, budget=budget
                )
            budget -= spent
            facts_written += facts
        except (httpx.HTTPError, TimeoutError) as failure:
            # The provider, for THIS tenant's call. The transaction rolls back, so the call
            # keeps its `pending` marker and the next tick picks it up — the correct
            # behaviour for a transient failure, at a cost of one hour.
            log.warning(
                "caller_memory_distil_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
        except Exception:
            log.exception("caller_memory_distil_tenant_failed", extra={"tenant_id": str(tenant_id)})

    log.info(
        "caller_memory_distil_tick",
        extra={
            "tenants": len(tenants),
            "facts": facts_written,
            "budget_left": budget,
        },
    )
    return f"calls={MAX_CALLS_PER_TICK - budget} facts={facts_written}"


__all__ = [
    "DISTIL_MINUTE",
    "LOOKBACK_DAYS",
    "MAX_CALLS_PER_TENANT",
    "MAX_CALLS_PER_TICK",
    "MAX_TURNS_PER_CALL",
    "MIN_TURNS",
    "SETTLE_MINUTES",
    "distil_caller_memories",
    "facts_of",
    "within_scope",
]

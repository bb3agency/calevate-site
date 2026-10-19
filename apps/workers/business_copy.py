"""Write one client's business-tailored examples and suggestions (D-827).

Queued through the outbox (`tenancy/business_copy.queue_generation`) when an account is
created, when the owner asks Pip to refresh them, when an operator asks, and by the daily
check (`sweep_business_copies`) for an account whose last look is 15 days old. One run:

1. **Claim** the account's row (`running_since`, compare-and-swap), so two runs never
   overlap; a claim older than `CLAIM_TTL` belongs to a run that died.
2. **Read the inputs**: everything `lead_fields_draft.business_context` knows about the
   business (profile, type, knowledge titles, agents), plus its pinned facts, its lead
   details, its open knowledge gaps and its callers' recent unanswered questions. All of it
   passes through `redact()` (D-127 G-1/G-2); the gap quotes are stored redacted already and
   are redacted again here. Their fingerprint is `inputs_hash`; the scheduled check stops
   with `inputs_unchanged` when it matches the copy in use.
3. **May it spend?** A trial account's first generation at signup and an operator's refresh
   are ours (`ASSIST_FEATURE_BUSINESS_COPY_ABSORBED`); they stop only on the platform AI
   brake. Everything else is the client's AI allowance (`require_ai_assist`): used up, the
   run stops with `allowance_used_up` and the copy in use stays.
4. **Ask Gemini, and only Gemini** (`script_assist.ask_json(gemini_only=True)`): the inputs
   include callers' questions, and the Sarvam standby's terms permit training on inputs
   (Sarvam ToS s.17.5). The answer must parse as `GeneratedCopy` and pass `copy_problems`;
   one repair, then an honest stop (`answer_unusable`). A failure keeps the copy in use and
   raises `business_copy_unavailable` for an operator.
5. **Meter and store together**: the answer's tokens (with the cached-input split the
   ledger records) under the feature step 3 chose, and the new copy, in one transaction.

Nothing here is logged but ids, codes and counts (hard rule 6).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast
from uuid import UUID

from calevate_shared.languages import find_language
from calevate_shared.spoken_guard import generation_guidance
from pydantic import ValidationError
from sqlalchemy import text

from apps.api.agents.assist_leg import google_assist_leg
from apps.api.agents.lead_fields import agents_with_fields
from apps.api.agents.starters import CATALOGUE, STARTER_JOBS, STARTER_LANGUAGE, vertical_of
from apps.api.billing.ai_quota import (
    new_assist_ref,
    platform_brake_tripped,
    require_ai_assist,
)
from apps.api.billing.models import (
    ASSIST_FEATURE_BUSINESS_COPY,
    ASSIST_FEATURE_BUSINESS_COPY_ABSORBED,
)
from apps.api.billing.trials import trial_billing_active
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.tenancy.business_copy import (
    CHIP_MAX,
    CLAIM_TTL,
    LINE_MAX,
    MAX_CHIPS,
    MAX_QUESTIONS,
    MAX_STEPS,
    MIN_CHIPS,
    MIN_QUESTIONS,
    MIN_STEPS,
    PLACEHOLDER_KEYS,
    PROSE_MAX,
    QUESTION_MAX,
    REFRESH_EVERY,
    SHORT_MAX,
    GeneratedCopy,
    StopReason,
    Trigger,
    copy_problems,
)
from apps.api.tenancy.models import BUSINESS_COPY_TRIGGERS
from apps.workers.fleet_walk import WalkBudget
from apps.workers.lead_fields_draft import business_context
from apps.workers.redaction import redact
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    JsonAnswer,
    UnusableAnswerError,
    ask_json,
)

log = get_logger(__name__)

#: The ARQ name; `tenancy/business_copy.JOB` is the enqueue side's spelling.
JOB_NAME: Final = "generate_business_copy"

#: Bumped when the instruction or the shape changes, so the next scheduled check rewrites
#: copy written under the old one.
PROMPT_VERSION: Final = 1

#: The description handed to the model, in characters.
MAX_INPUT_CHARS: Final = 9000
MAX_PINNED_FACTS: Final = 20
MAX_GAPS: Final = 15
MAX_RECENT_QUESTIONS: Final = 15
#: Callers' questions older than this no longer describe what callers ask.
RECENT_QUESTION_DAYS: Final = 30

#: Each request's budget. The answer is a few thousand tokens of JSON; `ask_json` gives the
#: Gemini leg two budgets for the request and its one repair, inside the worker's 300 s.
REQUEST_TIMEOUT_S: Final = 60.0
MAX_ANSWER_TOKENS: Final = 6000


#: What each placeholder key is, for the instruction. Mirrors `verticalExamples.ts`.
PLACEHOLDER_MEANINGS: Final[dict[str, str]] = {
    "branch_label": "the name of a branch or location",
    "service_name": "one thing the business sells or offers",
    "service_price": "a typical price for it in whole rupees, digits only",
    "service_note": "a short note beside that price",
    "ask_on_arrival": "how this trade says a price is not quoted on the phone",
    "faq_question": "a question callers ask that a price list does not answer",
    "staff_name": "a staff member's name a caller might ask for",
    "staff_spoken": "how to say that name aloud, in capitalised syllables",
    "staff_role": "that person's role",
    "staff_why_it_matters": "why a mispronounced name matters to this business, as a clause",
    "booking_rules": "how bookings or orders are taken and what the agent must never promise",
    "contact_name": "who a caller is put through to, as a desk or role",
    "knowledge_title": "the title of a note the owner would write for the agents",
    "knowledge_answer": "an answer the owner would teach for a caller's question",
    "extraction_reason": "why one detail matters, as a clause starting with 'so we can'",
    "script_brief": "what the owner types to have a call script drafted",
    "extraction_label": "one detail the agent writes down about a caller, as a short label",
    "extraction_options": "choices for a pick-one detail, comma separated",
    "end_call_rules": "two rules for ending calls, one per line",
    "lead_search": "what a caller asked for, as the owner would search for it",
    "booking_job_title": "the name of the booking job, 2 to 4 words, like 'Take bookings'",
    "booking_job_line": "one line saying the agent can check the calendar and book callers",
}

_STR: Final[dict[str, object]] = {"type": "string"}


def _strings(minimum: int, maximum: int) -> dict[str, object]:
    return {"type": "array", "items": _STR, "minItems": minimum, "maxItems": maximum}


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def answer_schema(starter_counts: dict[str, int]) -> dict[str, object]:
    """The strict response format: the closed key set of `GeneratedCopy`."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "calevate_business_copy",
            "strict": True,
            "schema": _object(
                {
                    "placeholders": _object(dict.fromkeys(PLACEHOLDER_KEYS, _STR)),
                    "steps": {
                        "type": "array",
                        "items": _object({"name": _STR, "example_line": _STR}),
                        "minItems": MIN_STEPS,
                        "maxItems": MAX_STEPS,
                    },
                    "starter_lines": _object(
                        {job: _strings(n, n) for job, n in starter_counts.items()}
                    ),
                    "caller_details": _strings(MIN_CHIPS, MAX_CHIPS),
                    "example_questions": _strings(MIN_QUESTIONS, MAX_QUESTIONS),
                }
            ),
        },
    }


@dataclass(frozen=True, slots=True)
class Inputs:
    """What one run is written from, already redacted."""

    description: str
    #: The BCP-47 tag of the business's main call language.
    language: str
    vertical: str | None
    clinic: bool
    #: Each starter job's steps as (title, instruction), for the account's business type.
    starter_steps: dict[str, tuple[tuple[str, str], ...]]
    inputs_hash: str

    @property
    def starter_counts(self) -> dict[str, int]:
        return {job: len(steps) for job, steps in self.starter_steps.items()}


def instruction_for(inputs: Inputs) -> str:
    """The system instruction. Fixed text first and the per-account parts last, so the
    fixed part is a prefix Gemini's implicit cache can reuse."""
    language = find_language(inputs.language)
    language_name = language.english_name if language is not None else inputs.language
    keys = "; ".join(f"{key}: {meaning}" for key, meaning in PLACEHOLDER_MEANINGS.items())
    starters = " ".join(
        f"{job}: "
        + " | ".join(
            f"step {i}: {title} ({instruction})" for i, (title, instruction) in enumerate(steps, 1)
        )
        for job, steps in inputs.starter_steps.items()
    )
    medical = (
        "Medical words are fine for this business. "
        if inputs.clinic
        else "It is not a medical business, so use no medical or health-care words at all. "
    )
    return (
        "You write the example text one small Indian business sees in its dashboard for an "
        "AI phone agent: the greyed-out examples inside empty form fields, suggested script "
        "steps, details to ask callers and questions callers ask. Write for THIS business, "
        "from the description you are given: use its own products, services, places and "
        "words where it gives them, and where it does not, write an example that plainly "
        "fits this kind of business. Examples show what to type; they are never facts the "
        "business must stand behind, so invent no offers, discounts or guarantees. "
        "Never copy a person's name, a phone number, an address or anything marked "
        "[redacted] or [phone ...] from the description. "
        "Plain text only: no markdown, bullets, numbering, emoji, asterisks or brackets, and "
        "never name a technology or AI company. "
        "Everything is in plain English except the example lines, which are what the phone "
        "agent says aloud, in the main call language named below, the way people speak it on "
        "the phone, short, with numbers, prices and times in words and never digits, rupee "
        "signs or slashes. "
        "Fields: placeholders, one value per key ("
        + keys
        + f"); steps: {MIN_STEPS} to {MAX_STEPS} steps a call with this business goes "
        "through, each a name of 2 to 6 words and an example_line; starter_lines: for each "
        "ready-made script below, exactly one example_line per step, in step order; "
        f"caller_details: {MIN_CHIPS} to {MAX_CHIPS} details the agent may ask a caller for, "
        "1 to 4 words each; example_questions: "
        f"{MIN_QUESTIONS} to {MAX_QUESTIONS} questions callers of this business ask, "
        "favouring the real ones in the description, rewritten without names or numbers. "
        f"Keep short values under {SHORT_MAX} characters, one-line values under {LINE_MAX}, "
        f"prose under {PROSE_MAX}, details under {CHIP_MAX} and questions under "
        f"{QUESTION_MAX}. Only end_call_rules has a line break, between its two rules. "
        "Return ONLY the JSON object.\n"
        f"Main call language: {language_name}. "
        + medical
        + "\nReady-made scripts: "
        + starters
        + "\n"
        + generation_guidance(inputs.language, inputs.vertical)
    )


def parse_answer(raw: dict[str, Any], *, inputs: Inputs) -> GeneratedCopy:
    """The model's answer as `GeneratedCopy`, or `UnusableAnswerError` naming what to fix,
    which `ask_json` sends back once. Paths and rules only, never the answer's text."""
    try:
        copy = GeneratedCopy.model_validate(raw)
    except ValidationError as invalid:
        problems = [
            f"{'.'.join(str(p) for p in error['loc'])}: {error['type']}"
            for error in invalid.errors(include_input=False, include_url=False)
        ]
        raise _unusable(problems) from None
    problems = copy_problems(copy, clinic=inputs.clinic, language=inputs.language)
    for job, count in inputs.starter_counts.items():
        given = len(getattr(copy.starter_lines, job))
        if given != count:
            problems.append(f"starter_lines.{job}: exactly {count} lines, one per step")
    if problems:
        raise _unusable(problems)
    return copy


def _unusable(problems: list[str]) -> UnusableAnswerError:
    said = "; ".join(problems[:20])
    # Field paths and our rule names, never the answer's text (hard rule 6).
    log.warning("business_copy_answer_unusable", extra={"problems": said})
    return UnusableAnswerError(said)


def _parser(inputs: Inputs) -> Any:
    def parse(raw: dict[str, Any]) -> GeneratedCopy:
        return parse_answer(raw, inputs=inputs)

    return parse


# --- the inputs -------------------------------------------------------------------------------


_MAIN_LANGUAGE: Final = (
    "SELECT language_primary FROM agents WHERE deleted_at IS NULL "
    "GROUP BY language_primary ORDER BY count(*) DESC, min(created_at), language_primary LIMIT 1"
)
_PINNED: Final = (
    "SELECT question, text FROM kb_facts WHERE pinned AND removed_at IS NULL "
    "ORDER BY position NULLS LAST, created_at, id LIMIT :limit"
)
_OPEN_GAPS: Final = (
    "SELECT topic_label, example_question_redacted FROM knowledge_gaps WHERE status = 'open' "
    "ORDER BY last_seen_at DESC, id LIMIT :limit"
)
_RECENT_QUESTIONS: Final = (
    "SELECT question_redacted FROM knowledge_gap_occurrences "
    "WHERE created_at > now() - make_interval(days => :days) "
    "ORDER BY created_at DESC, id LIMIT :limit"
)


def inputs_hash(*, description: str, language: str, vertical: str | None) -> str:
    """The fingerprint the scheduled check compares: what the model would be told."""
    payload = {
        "v": PROMPT_VERSION,
        "description": description,
        "language": language,
        "vertical": vertical,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def gather_inputs(tenant_id: UUID) -> Inputs:
    """Everything the copy is written from, redacted, with its fingerprint."""
    base, vertical = await business_context(tenant_id)
    async with tenant_session(tenant_id) as session:
        language = (await session.execute(text(_MAIN_LANGUAGE))).scalar() or STARTER_LANGUAGE
        pinned = (await session.execute(text(_PINNED), {"limit": MAX_PINNED_FACTS})).all()
        agents = await agents_with_fields(session)
        gaps = (await session.execute(text(_OPEN_GAPS), {"limit": MAX_GAPS})).all()
        recent = (
            (
                await session.execute(
                    text(_RECENT_QUESTIONS),
                    {"days": RECENT_QUESTION_DAYS, "limit": MAX_RECENT_QUESTIONS},
                )
            )
            .scalars()
            .all()
        )
    lines: list[str] = []
    for question, fact in pinned:
        lines.append(f"Pinned fact: {question} {fact}" if question else f"Pinned fact: {fact}")
    labels = sorted({f.label for agent in agents for f in agent["fields"]})
    if labels:
        lines.append("Details its agents write down: " + ", ".join(labels))
    for topic, example in gaps:
        lines.append(f"Callers asked and the agent could not answer ({topic}): {example}")
    for question in recent:
        lines.append(f"A caller recently asked: {question}")
    extra = redact("\n".join(" ".join(str(line).split()) for line in lines)).text
    description = f"{base}\n{extra}".strip()[:MAX_INPUT_CHARS]
    starter_vertical = vertical_of(vertical)
    starter_steps: dict[str, tuple[tuple[str, str], ...]] = {
        job: tuple(
            (step.title, step.instruction) for step in CATALOGUE[(starter_vertical, job)].steps
        )
        for job in STARTER_JOBS
    }
    return Inputs(
        description=description,
        language=str(language),
        vertical=vertical,
        clinic=vertical == "clinic",
        starter_steps=starter_steps,
        inputs_hash=inputs_hash(description=description, language=str(language), vertical=vertical),
    )


# --- the row ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    at: datetime
    previous_hash: str | None


async def _account_open(tenant_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text("SELECT 1 FROM organizations WHERE id = :tid AND deleted_at IS NULL"),
                {"tid": tenant_id},
            )
        ).first()
    return found is not None


async def claim(tenant_id: UUID, trigger: Trigger, *, now: datetime | None = None) -> Claim | None:
    """Take the account's row for one run, or None while another run holds it."""
    at = now or datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id) VALUES (:id, :tid) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
        row = (
            await session.execute(
                text(
                    "UPDATE business_copies SET running_since = :at, last_trigger = :trigger, "
                    "last_attempt_at = :at, updated_at = now() "
                    "WHERE running_since IS NULL OR running_since < :stale "
                    "RETURNING inputs_hash"
                ),
                {"at": at, "trigger": trigger, "stale": at - CLAIM_TTL},
            )
        ).first()
    return None if row is None else Claim(at=at, previous_hash=row[0])


async def _stop(tenant_id: UUID, held: Claim, reason: StopReason) -> StopReason:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE business_copies SET stop_reason = :reason, running_since = NULL, "
                "updated_at = now() WHERE running_since = :at"
            ),
            {"reason": reason, "at": held.at},
        )
    return reason


async def _release(tenant_id: UUID, held: Claim) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE business_copies SET running_since = NULL, updated_at = now() "
                "WHERE running_since = :at"
            ),
            {"at": held.at},
        )


def _alarm(tenant_id: UUID, reason: str) -> None:
    alert(
        "WORKER_TERMINAL",
        "business_copy_unavailable",
        detail=(
            "A client's business examples could not be written by the AI model, so the copy "
            "already in use was kept. Check the business_copy leg's health "
            "(ai_provider_degraded); the owner or an operator can refresh once it answers."
        ),
        tenant_id=str(tenant_id),
        reason=reason,
    )


async def _may_spend(tenant_id: UUID, *, absorbed: bool) -> StopReason | None:
    """Why this run may not spend, or None. The allowance decides a client's run; only the
    platform AI brake stops one that is ours."""
    async with tenant_session(tenant_id) as session:
        if absorbed:
            return "ai_paused" if await platform_brake_tripped(session) else None
        try:
            await require_ai_assist(session, tenant_id=tenant_id)
        except ProblemError as refusal:
            return "ai_paused" if refusal.code == "ai_paused_platform_wide" else "allowance_used_up"
    return None


async def _absorbed(tenant_id: UUID, trigger: Trigger) -> bool:
    """Ours to pay for: an operator's refresh, and a trial account's first generation."""
    if trigger == "operator":
        return True
    if trigger != "signup":
        return False
    async with tenant_session(tenant_id) as session:
        return await trial_billing_active(session, tenant_id=tenant_id)


async def _store(
    tenant_id: UUID,
    held: Claim,
    inputs: Inputs,
    answer: JsonAnswer[GeneratedCopy],
    *,
    feature: str,
) -> bool:
    """Meter the answer and store the copy in ONE transaction: a copy the ledger does not
    know about, or a charge for a copy that was not stored, are both impossible."""
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        metering = await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=feature,
            model=answer.model,
        )
        stored = (
            await session.execute(
                text(
                    "UPDATE business_copies SET generated = CAST(:generated AS jsonb), "
                    "language = :language, model = :model, inputs_hash = :hash, "
                    "generated_at = now(), cost_inr = :cost, absorbed = :absorbed, "
                    "stop_reason = NULL, running_since = NULL, updated_at = now() "
                    "WHERE running_since = :at RETURNING id"
                ),
                {
                    "generated": json.dumps(answer.value.model_dump(mode="json")),
                    "language": inputs.language,
                    "model": answer.model,
                    "hash": inputs.inputs_hash,
                    "cost": metering.cost_inr,
                    "absorbed": feature == ASSIST_FEATURE_BUSINESS_COPY_ABSORBED,
                    "at": held.at,
                },
            )
        ).first()
    return stored is not None


async def _run(tenant_id: UUID, trigger: Trigger, held: Claim) -> str:
    inputs = await gather_inputs(tenant_id)
    if trigger == "scheduled" and inputs.inputs_hash == held.previous_hash:
        return await _stop(tenant_id, held, "inputs_unchanged")
    absorbed = await _absorbed(tenant_id, trigger)
    blocked = await _may_spend(tenant_id, absorbed=absorbed)
    if blocked is not None:
        return await _stop(tenant_id, held, blocked)
    feature = ASSIST_FEATURE_BUSINESS_COPY_ABSORBED if absorbed else ASSIST_FEATURE_BUSINESS_COPY
    leg = google_assist_leg()
    if not leg.serves_dashboard:
        _alarm(tenant_id, "provider_unavailable")
        return await _stop(tenant_id, held, "provider_unavailable")
    try:
        answer: JsonAnswer[GeneratedCopy] = await ask_json(
            inputs.description,
            instruction_for(inputs),
            parse=_parser(inputs),
            azure_format=answer_schema(inputs.starter_counts),
            tenant_leg=leg,
            max_tokens=MAX_ANSWER_TOKENS,
            temperature=0.4,
            timeout_s=REQUEST_TIMEOUT_S,
            health_leg="business_copy",
            gemini_only=True,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        reason: StopReason = (
            "answer_unusable" if refused.code == ANSWER_UNUSABLE_CODE else "provider_unavailable"
        )
        _alarm(tenant_id, reason)
        return await _stop(tenant_id, held, reason)
    if not await _store(tenant_id, held, inputs, answer, feature=feature):
        # The claim expired under a run that took longer than `CLAIM_TTL`, and another run
        # holds the row: that run's copy stands. The spend is on the ledger either way.
        return "claim_lost"
    return "stored"


async def generate_business_copy(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One run for one account; returns the outcome it logged."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    raw_trigger = str(payload.get("trigger", "refresh"))
    trigger = cast(Trigger, raw_trigger if raw_trigger in BUSINESS_COPY_TRIGGERS else "refresh")
    if not await _account_open(tenant_id):
        outcome = "account_closed"
    else:
        held = await claim(tenant_id, trigger)
        if held is None:
            outcome = "busy"
        else:
            try:
                outcome = await _run(tenant_id, trigger, held)
            except Exception:
                await _release(tenant_id, held)
                raise
    log.info(
        "business_copy_run",
        extra={"tenant_id": str(tenant_id), "trigger": trigger, "outcome": outcome},
    )
    return outcome


# --- the 15-day check -------------------------------------------------------------------------

#: Accounts that may be using the platform: being set up, or live.
_DIRECTORY: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL "
    "AND status IN ('onboarding', 'active') ORDER BY id"
)


async def _due(tenant_id: UUID, *, now: datetime) -> bool:
    """Not a trial (founder: trials get no scheduled refresh), and not looked at for 15 days."""
    async with tenant_session(tenant_id) as session:
        if await trial_billing_active(session, tenant_id=tenant_id, at=now):
            return False
        row = (await session.execute(text("SELECT last_attempt_at FROM business_copies"))).first()
        if row is not None and row[0] is not None and row[0] > now - REFRESH_EVERY:
            return False
        await enqueue_outbox_once(
            session,
            job=JOB_NAME,
            payload={"tenant_id": str(tenant_id), "trigger": "scheduled"},
            dedupe_key=f"business-copy:{tenant_id}:{now.date().isoformat()}",
        )
    return True


async def sweep_business_copies(ctx: dict[str, Any]) -> str:
    """Daily: queue the scheduled check for every account whose last look is 15 days old.
    The run itself decides whether anything changed."""
    del ctx
    now = datetime.now(UTC)
    async with admin_session() as directory:
        tenant_ids = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    budget = WalkBudget()
    counts = {"probed": 0, "queued": 0, "failed": 0}
    for tenant_id in tenant_ids:
        if budget.spent():
            break
        counts["probed"] += 1
        try:
            if await _due(tenant_id, now=now):
                counts["queued"] += 1
        except Exception as exc:
            counts["failed"] += 1
            log.warning(
                "business_copy_sweep_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    unreached = len(tenant_ids) - counts["probed"]
    log.info("business_copy_sweep", extra={**counts, "unreached": unreached})
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "business_copy_sweep_truncated",
            detail=(
                f"the business examples check reached {counts['probed']} of {len(tenant_ids)} "
                "client(s) inside its time budget; the rest are looked at tomorrow"
            ),
        )
    return json.dumps(counts)


__all__ = [
    "JOB_NAME",
    "PLACEHOLDER_MEANINGS",
    "PROMPT_VERSION",
    "Inputs",
    "answer_schema",
    "claim",
    "gather_inputs",
    "generate_business_copy",
    "inputs_hash",
    "instruction_for",
    "parse_answer",
    "sweep_business_copies",
]

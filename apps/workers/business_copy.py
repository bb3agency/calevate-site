"""Write one client's business-tailored examples and suggestions (D-827).

Queued through the outbox (`tenancy/business_copy.queue_generation`) when an account is
created, when the owner asks Pip to refresh them, when an operator asks, and by the daily
check (`sweep_business_copies`) for an account whose last look is 15 days old or whose copy
was written under an older `PROMPT_VERSION` (also walked once at worker start after a
version change, `upgrade_business_copies`). One run:

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
from apps.api.agents.starters import CATALOGUE, LINE_SETS, STARTER_LANGUAGE, vertical_of
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
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.tenancy.business_copy import (
    BOOKING_JOB_KEYS,
    CAPABILITY_KEYS,
    CHIP_MAX,
    CLAIM_TTL,
    LINE_MAX,
    MAX_CHIPS,
    MAX_OBJECTIONS,
    MAX_PIP_QUESTIONS,
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
    health_allowed,
    missing_placeholders,
    profile_problems,
    screen_guide_problems,
)
from apps.api.tenancy.models import BUSINESS_COPY_TRIGGERS
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.lead_fields_draft import business_context
from apps.workers.model_tiers import FlexAllowance
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

#: Bumped when the instruction or the shape changes. It is part of `inputs_hash` and stored
#: on the row, so a copy written under an older version is rewritten at once
#: (`upgrade_business_copies`, queued at worker start) rather than at its next 15-day check.
#: Version 4: the capability profile, objections, caller noun and Pip questions.
PROMPT_VERSION: Final = 4

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


def _flex_for(trigger: Trigger) -> FlexAllowance | None:
    """The daily check's refresh asks on Flex; a run somebody asked for does not
    (`model_tiers.MODEL_CALLS`, D-930)."""
    return FlexAllowance("business_copy_scheduled") if trigger == "scheduled" else None


#: What each placeholder key is, for the instruction. Mirrors `verticalExamples.ts`.
PLACEHOLDER_MEANINGS: Final[dict[str, str]] = {
    "knowledge_title": "the title of a note the owner would write for the agents",
    "knowledge_answer": "an answer the owner would teach for a caller's question",
    "extraction_reason": "why one detail matters, as a clause starting with 'so we can'",
    "script_brief": "what the owner types to have a call script drafted",
    "extraction_label": "one detail the agent writes down about a caller, as a short label",
    "extraction_options": "choices for a pick-one detail, comma separated",
    "end_call_rules": "two rules for ending calls, one per line",
    "lead_search": "what a caller asked for, as the owner would search for it",
    "booking_job_title": (
        "the name of the job where the agent books callers in or takes their orders, 2 to 4 "
        "words, like 'Take bookings'; an empty string when callers neither book nor order"
    ),
    "booking_job_line": (
        "one line saying the agent can check the calendar and book callers in or take their "
        "orders; an empty string when callers neither book nor order"
    ),
    "teach_note": (
        "two or three short sentences the owner types to teach the agents: one fact callers "
        "ask about (a price only if this business tells callers prices), and one thing never "
        "to promise"
    ),
    "business_line": "the business in one line, lower case, like 'a family-run bakery in Guntur'",
    "agent_role": "two sentences in the second person telling the agent its role on the phone",
    "call_goal": "one sentence: what a good call achieves for this business",
    "outbound_purpose": "one sentence the agent says to explain why it is calling a past enquirer",
    "call_ending": "one sentence: how the agent should end a call",
    "pronounce_word": "a product, place or person name callers of this business say",
    "pronounce_say_as": "how to say that name aloud, in hyphenated syllables",
    "script_change": "one change the owner might ask for in the agent's script",
    "script_change_idea": "another such change, under eight words, starting with a verb",
    "fact_question": "a short question callers ask that has a one-line answer",
    "fact_answer": "the one-line answer to that question, as the agent should give it",
    "test_expectation": "what the agent should have done on a call that went wrong, as an order",
    "campaign_name": "the name of an outbound calling campaign, 2 to 5 words",
    "message_title": "what a WhatsApp message to customers is for, 2 to 4 words",
    "message_body": (
        "that WhatsApp message, one sentence with {{1}} where the customer's name goes, "
        "never at its start or end"
    ),
    "outcome_label": "how one kind of call ended, as a short label, like 'Wants to go ahead'",
    "outcome_meaning": "one sentence saying what that outcome means",
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
                    "screen_guide": _object({"suggested": {"type": "boolean"}, "reason": _STR}),
                    # Each reason before its verdict: JSON is generated left to right.
                    "capabilities": _object(
                        dict.fromkeys(
                            CAPABILITY_KEYS,
                            _object({"reason": _STR, "applies": {"type": "boolean"}}),
                        )
                    ),
                    "objections": {
                        "type": "array",
                        "items": _object({"caller_says": _STR, "how_to_answer": _STR}),
                        "minItems": 0,
                        "maxItems": MAX_OBJECTIONS,
                    },
                    "caller_noun": _STR,
                    "pip_questions": _strings(0, MAX_PIP_QUESTIONS),
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
    #: The owner's own description of the business (redacted): a medical word it uses may
    #: appear in the copy whatever the business is judged to be.
    owner_words: str
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
        "favouring the real ones in the description, rewritten without names or numbers; "
        "screen_guide: suggested is true only when this business's callers are often on its "
        "own app or website during the call (installing it, signing up, ordering, paying or "
        "changing a setting), so its phone agent should walk them through it one tap at a "
        "time, and false when its callers just talk, ask or book; reason is one short "
        "sentence to the owner saying what their callers do on screen when suggested, and an "
        "empty string when not. "
        "capabilities: judge what THIS business does with the people who call it, from the "
        "description only, each with a reason first (one short sentence to the owner naming "
        "what in the description shows it) and then applies, true or false: takes_bookings, "
        "callers book a time, slot, visit or meeting; takes_orders, callers order goods for "
        "pickup or delivery; quotes_prices, the business tells callers its prices; "
        "has_premises, callers come to a place such as a shop, office or site; sells, the "
        "business sells products or services to its callers at all, false for a free app "
        "helping its registered users, a helpline or a charity; health_business, it gives "
        "health or medical care, such as a pharmacy, a diagnostic lab, physiotherapy, "
        "veterinary care or a medical practice. When the description does not settle one, "
        "judge what a business of exactly this kind usually does and say so in the reason. "
        "Every other field must agree with these judgements: when callers neither book nor "
        "order, booking_job_title and booking_job_line are empty strings; when the business "
        "quotes no prices, no example names a price; when it sells nothing, no example "
        "speaks of buying, orders or sales. "
        "Use medical or health-care words only when health_business is true or the "
        "description itself uses them. "
        f"objections: 0 to {MAX_OBJECTIONS} push-backs this business's callers really raise, "
        "only ones that fit what it does, none rather than a made-up one; caller_says is how "
        "a caller says it, short, in the main call language, and how_to_answer is short "
        "guidance in English. "
        "caller_noun: what this business calls the people on its calls, one to three plain "
        "English words, singular, lower case, such as customer, user, member, student, "
        "farmer or client. "
        f"pip_questions: 0 to {MAX_PIP_QUESTIONS} short questions the owner of THIS business "
        "would ask an assistant about its calls, in English. "
        f"Keep short values under {SHORT_MAX} characters, one-line values under {LINE_MAX}, "
        f"prose under {PROSE_MAX}, details under {CHIP_MAX} and questions under "
        f"{QUESTION_MAX}. Only end_call_rules has a line break, between its two rules. "
        "Return ONLY the JSON object.\n"
        f"Main call language: {language_name}."
        + "\nReady-made scripts: "
        + starters
        + "\n"
        + generation_guidance(inputs.language, inputs.vertical)
    )


def parse_answer(raw: dict[str, Any], *, inputs: Inputs) -> GeneratedCopy:
    """The model's answer as `GeneratedCopy`, or `UnusableAnswerError` naming what to fix,
    which `ask_json` sends back once. Paths and rules only, never the answer's text."""
    try:
        copy = GeneratedCopy.model_validate(_without_empty_booking_job(raw))
    except ValidationError as invalid:
        problems = [
            f"{'.'.join(str(p) for p in error['loc'])}: {error['type']}"
            for error in invalid.errors(include_input=False, include_url=False)
        ]
        raise _unusable(problems) from None
    problems = [f"placeholders.{key}: missing" for key in missing_placeholders(copy.placeholders)]
    problems += copy_problems(
        copy, health=health_allowed(copy), language=inputs.language, allowed=inputs.owner_words
    )
    problems += screen_guide_problems(copy)
    problems += profile_problems(copy)
    for job, count in inputs.starter_counts.items():
        given = len(getattr(copy.starter_lines, job))
        if given != count:
            problems.append(f"starter_lines.{job}: exactly {count} lines, one per step")
    if problems:
        raise _unusable(problems)
    return copy


def _without_empty_booking_job(raw: dict[str, Any]) -> dict[str, Any]:
    """The strict schema makes every key a string, so "no booking job" arrives as "". It is
    stored as absent, which is how every screen already reads a key with nothing in it."""
    placeholders = raw.get("placeholders")
    if not isinstance(placeholders, dict):
        return raw
    kept = {
        key: value
        for key, value in placeholders.items()
        if not (key in BOOKING_JOB_KEYS and isinstance(value, str) and not value.strip())
    }
    return {**raw, "placeholders": kept}


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
#: Before any agent exists, the business's own first language rather than the platform's.
_PROFILE_LANGUAGE: Final = "SELECT languages[1] FROM business_profiles WHERE tenant_id = :tid"
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
    # Without the type on file and the agents' names: on an account given a type by default
    # both were written from that default, and a default "clinic" must not license medical
    # words for a shop (D-722).
    owner_words, _ = await business_context(tenant_id, include_type=False)
    async with tenant_session(tenant_id) as session:
        language = (
            (await session.execute(text(_MAIN_LANGUAGE))).scalar()
            or (await session.execute(text(_PROFILE_LANGUAGE), {"tid": tenant_id})).scalar()
            or STARTER_LANGUAGE
        )
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
        for job in LINE_SETS
    }
    return Inputs(
        description=description,
        language=str(language),
        vertical=vertical,
        owner_words=owner_words,
        starter_steps=starter_steps,
        inputs_hash=inputs_hash(description=description, language=str(language), vertical=vertical),
    )


# --- the row ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    at: datetime
    previous_hash: str | None
    #: True when the row holds a copy written under an older `PROMPT_VERSION`.
    behind: bool = False


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
                    "RETURNING inputs_hash, generated IS NOT NULL "
                    "AND prompt_version IS DISTINCT FROM :version"
                ),
                {
                    "at": at,
                    "trigger": trigger,
                    "stale": at - CLAIM_TTL,
                    "version": PROMPT_VERSION,
                },
            )
        ).first()
    return None if row is None else Claim(at=at, previous_hash=row[0], behind=bool(row[1]))


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


async def _absorbed(tenant_id: UUID, trigger: Trigger, *, behind: bool = False) -> bool:
    """Ours to pay for: an operator's refresh, a trial account's first generation and the
    one after its owner's first brief (D-855), and the check that rewrites a copy because
    OUR prompt changed (`behind`). Nobody on the account asked for that last one, and a
    used-up allowance would otherwise leave the account on an outdated copy."""
    if trigger == "operator" or (trigger == "scheduled" and behind):
        return True
    if trigger not in ("signup", "first_run"):
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
            service_tier=answer.service_tier,
        )
        stored = (
            await session.execute(
                text(
                    "UPDATE business_copies SET generated = CAST(:generated AS jsonb), "
                    "language = :language, model = :model, inputs_hash = :hash, "
                    "prompt_version = :version, generated_at = now(), cost_inr = :cost, "
                    "absorbed = :absorbed, "
                    "stop_reason = NULL, running_since = NULL, updated_at = now() "
                    "WHERE running_since = :at RETURNING id"
                ),
                {
                    "generated": json.dumps(answer.value.model_dump(mode="json")),
                    "language": inputs.language,
                    "model": answer.model,
                    "hash": inputs.inputs_hash,
                    "version": PROMPT_VERSION,
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
    absorbed = await _absorbed(tenant_id, trigger, behind=held.behind)
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
            flex=_flex_for(trigger),
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


_ROW_STATE: Final = (
    "SELECT last_attempt_at, generated IS NOT NULL AND prompt_version IS DISTINCT FROM :version "
    "FROM business_copies"
)


async def _due(tenant_id: UUID, *, now: datetime) -> bool:
    """Due when the copy in use was written under an older prompt (any account, trials too:
    the rewrite is ours, `_absorbed`), or else when it is not a trial (founder: trials get no
    scheduled refresh) and was not looked at for 15 days. Once a day at most, by the key."""
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_ROW_STATE), {"version": PROMPT_VERSION})).first()
        behind = row is not None and bool(row[1])
        if not behind:
            if await trial_billing_active(session, tenant_id=tenant_id, at=now):
                return False
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
    """Daily: queue the scheduled check for every account whose last look is 15 days old or
    whose copy is behind the prompt. The run itself decides whether anything changed."""
    del ctx
    return await _walk()


#: The outbox job worker start queues once per prompt version.
UPGRADE_JOB: Final = "upgrade_business_copies"


async def upgrade_business_copies(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """The daily walk, run once right after a deploy that changed `PROMPT_VERSION`, so every
    account's copy (and its capability profile) is rewritten that day rather than within 15.
    A pass cut short by its budget leaves the rest to the daily walk, which queues a copy
    that is behind just the same."""
    del ctx, payload
    return await _walk()


async def queue_upgrade_on_start() -> None:
    """Queue `upgrade_business_copies` once per prompt version, at worker start. Logged,
    never raised: the daily walk reaches every copy that is behind anyway."""
    try:
        async with untenanted_session() as session:
            queued = await enqueue_outbox_once(
                session,
                job=UPGRADE_JOB,
                payload={"prompt_version": PROMPT_VERSION},
                dedupe_key=f"business-copy-upgrade:v{PROMPT_VERSION}",
            )
    except Exception:
        log.exception("business_copy_upgrade_not_queued")
        return
    if queued is not None:
        log.info("business_copy_upgrade_queued", extra={"prompt_version": PROMPT_VERSION})


async def _walk() -> str:
    now = datetime.now(UTC)
    async with admin_session() as directory:
        tenant_ids = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    budget = WalkBudget()
    counts = {"probed": 0, "queued": 0, "failed": 0}
    async for tenant_id in resumed_walk("business_copies", tenant_ids, budget):
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
    "UPGRADE_JOB",
    "Inputs",
    "answer_schema",
    "claim",
    "gather_inputs",
    "generate_business_copy",
    "inputs_hash",
    "instruction_for",
    "parse_answer",
    "queue_upgrade_on_start",
    "sweep_business_copies",
    "upgrade_business_copies",
]

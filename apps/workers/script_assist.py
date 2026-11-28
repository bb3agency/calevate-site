"""The dashboard AI ladder for a JSON answer (`ask_json`), the brief a script is written from
(`ScriptBrief`), and the language and shape checks on what a model wrote.

The script itself is written by the one writer (`workers/script_writer.write_script`), each
step by its own small request (`workers/step_writer`); this module is what every such request
shares.

WHY IT LIVES IN `apps/workers` AND REUSES THE ASSIST LADDER. CLAUDE.md's Do-NOT rule keeps
model calls out of request handlers; the dashboard-AI assist (`crm/assist.py` +
`workers/extraction.run_assist`) is the established controlled path, so this is the same
shape rather than a second one: the SAME `assist_capability` selector decides who answers
(the account's Gemini, Azure where configured, Sarvam disclosed-fallback, else a refusal),
the SAME `workers/chat.py` makes the request and reads the `usage` block back for metering,
the SAME `ASSIST_TIMEOUT_S` bounds each leg.

WHAT IT IS ALLOWED TO SEE (D-127 G-2). Its input is TENANT-AUTHORED business text, not
call-transcript PII. It is still never logged (hard rule 6): it is business content.

Metering and quota are NOT decided here: `billing/ai_quota` owns both, and the job that
stores a script meters every request it spent (`script_writer.meter`).
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import httpx
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    CallScript,
    ConversationStage,
)
from calevate_shared.engine import (
    SARVAM_DEFAULT_LLM,
    azure_openai_base_url,
    google_openai_compat_base_url,
    keeps_default_temperature,
)
from calevate_shared.opening_notices import WovenNotices, woven_notice_problems
from calevate_shared.spoken_guard import (
    english_problem,
    generation_guidance,
    introduced_opening_problem,
    latin_word_problem,
    textbook_problem,
)

from apps.api.agents import script_checks
from apps.api.agents.business_fit import UNKNOWN, BusinessFit
from apps.api.agents.call_rules import (
    placed_opening_problems,
    said_line_problem,
)
from apps.api.agents.languages import platform_default_language
from apps.api.agents.owner_plan import OwnerPlan
from apps.api.agents.retired_lines import retired_line_problem
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    caller_paths,
    instruction_fields,
    instruction_problems,
    owner_prohibitions,
    spoken_fields,
    spoken_line_problems,
)
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.tenancy.business_copy import provider_problem
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    ASSIST_LADDER_LEGS,
    ASSIST_TIMEOUT_S,
    AZURE_PROVIDER,
    GOOGLE_PROVIDER,
    PROVIDER_UNAVAILABLE_REASON,
    SARVAM_CHAT_URL,
    AssistCapability,
    AssistDeadlineError,
    PaidTurn,
    TenantModelLeg,
    _first_json_object,
    assist_capability,
    assist_unavailable,
    azure_credentials,
    ladder_deadlines,
    refused_after_spend,
    request_timeout,
    time_left,
)
from apps.workers.model_tiers import FlexAllowance

if TYPE_CHECKING:
    from apps.api.agents.starter_plans import Plan

log = get_logger(__name__)

_OPENING_PATHS: Final = frozenset({"opening_line", "outbound_opening_line"})


def placed_paths(direction: str) -> frozenset[str]:
    """The opening lines said on a call the agent places: a "both" agent's
    `outbound_opening_line`, and the `opening_line` of one that only places calls."""
    return frozenset(
        {"opening_line", "outbound_opening_line"}
        if direction == "outbound"
        else {"outbound_opening_line"}
    )


def language_problems(
    script: CallScript,
    language: str | None,
    *,
    before: CallScript | None = None,
    allowed: str = "",
    instructions: bool = True,
    names: Sequence[str] = (),
    introduced: bool = False,
    lint: LintContext | None = None,
    woven: WovenNotices | None = None,
    direction: str = "inbound",
) -> list[str]:
    """What the model must fix in a script it wrote (D-831): an instruction in an Indic
    script, and a spoken line with a textbook word (`spoken_guard`), a provider's name
    (`business_copy.provider_problem`, D-679: callers hear these lines) or a break of the call
    rules the practice tests check (`call_rules.said_line_problem`, D-849). Every spoken line
    must also be in the language's own letters (D-861, D-864), apart from `names` (the
    business's and the agent's). The opening line, which the engine speaks word for word,
    when the agent is `introduced` by its AI notice first, must neither greet nor say those
    names (D-865),
    and with `woven` says the notices switched on in its own words and no other (D-971).

    Only the model's own writing is judged: with `before` (an edit), a field whose text the
    script already held is the owner's and is skipped, and a textbook word that appears in
    `allowed` (the owner's own words the script was written from) is theirs. `instructions`
    False skips the English rule, for a conversion that keeps the owner's sentences.
    `lint` adds the script lint (`agents/script_lint`, D-945): promotional words, promises
    outside the account's capabilities, figures no fact gives, stacked questions and
    another persona's name, on the model's own lines only. With `lint`, an opening said on a
    call the agent places (`placed_paths(direction)`) also says the agent's name and the
    reason for the call (`call_rules.placed_opening_problems`)."""
    placed = placed_paths(direction)
    kept = (
        {text for _, text in (*instruction_fields(before), *spoken_fields(before))}
        if before is not None
        else set()
    )
    problems: list[str] = []
    if instructions:
        problems += [
            problem
            for path, text in instruction_fields(script)
            if text not in kept and (problem := english_problem(path, text))
        ]
    callers = caller_paths(script)
    close = f"stages.{len(script.stages) - 1}." if script.stages else None
    if lint is not None:
        problems += [
            problem
            for path, text in instruction_fields(script)
            if text not in kept and text.strip()
            for problem in instruction_problems(path, text, lint)
        ]
    for path, text in spoken_fields(script):
        if text in kept:
            continue
        owners = bool(allowed) and text.strip() in allowed
        problems += [
            problem
            for problem in (
                textbook_problem(path, text, language, allowed=allowed),
                provider_problem(path, text, allowed=allowed),
                # The call rules the practice tests hold the agent to (D-849); a caller's
                # example line is not the agent's to keep, and the owner's own line is theirs.
                None
                if path in callers or owners
                else said_line_problem(
                    path,
                    text,
                    opening=path in _OPENING_PATHS,
                    close=close is not None and path.startswith(close),
                    placed=path in placed,
                ),
                # Every spoken line, not only the opening: a step's example line, a sample
                # phrase or the example call in English letters teaches the in-call model to
                # write them, and the voice then reads them (D-861).
                None if owners else latin_word_problem(path, text, language, names=names),
                introduced_opening_problem(path, text, names=names)
                if path in _OPENING_PATHS
                and introduced
                and not owners
                and not (woven is not None and woven.ai)
                else None,
                # A line the plans used to teach every business (D-962): the model may have
                # seen one before, and it is never this business's own.
                None if owners else retired_line_problem(path, text),
            )
            if problem
        ]
        if lint is not None and path not in callers and not owners and text.strip():
            problems += spoken_line_problems(path, text, lint)
        if woven is not None and path in _OPENING_PATHS and not owners and text.strip():
            problems += woven_notice_problems(path, text, woven)
        if lint is not None and path in placed and not owners and text.strip():
            problems += placed_opening_problems(
                path,
                text,
                agent_name=lint.agent_name,
                business_name=lint.business_name,
                introduced=introduced and not (woven is not None and woven.ai),
            )
    if lint is not None:
        problems += shape_problems(script, before)
        if lint.places_calls:
            problems += way_out_problems(script, before)
    return problems


def shape_problems(script: CallScript, before: CallScript | None = None) -> list[str]:
    """What the model got wrong in the call's shape (`script_lint.flow_problems`), a step
    whose line redoes the opening (`call_rules.opening_redone_line_problems`), a line in a
    call language or a small step that opens with a reaction (`reacted_line_problems`), a
    step it wrote with no line, and, in an edit, a close it took out. With `before` (an
    edit), a shape problem the owner's script already had is theirs and not the model's to
    fix."""

    def shape(of: CallScript) -> list[str]:
        return script_checks.texts(script_checks.run(of, ids=script_checks.SHAPE_CHECKS))

    owned = set(shape(before)) if before is not None else set()
    problems = [problem for problem in shape(script) if problem not in owned]
    was = {stage.id: stage for stage in before.stages} if before is not None else {}
    if before is not None and before.stages:
        ids = {stage.id for stage in script.stages}
        close = before.stages[-1]
        if close.id not in ids and (not script.stages or script.stages[-1].id in was):
            problems.append(
                f'stages: the close ("{close.name}") was taken out; keep a last step that '
                "thanks them and ends the call."
            )
    return problems


#: The two ways out every placed call needs (`WAYS_OUT_RULE`). Neither is waived for a
#: platform rule: `CALL_BACK_TIME_RULE` and "Offer once, then close politely" say how to
#: answer, after the script, but a step with no exit still leads on to the next step, which
#: is what the agent followed on the 20-21 Nov 2026 calls. Judged by target, not by the
#: wording of `when`, so no word list decides it.
NOT_NOW_WAY_OUT: Final = (
    "stages: no step has a way out for a person who is busy now or says later; give the "
    "first step one whose condition says so, going to call_back, with no words about a call "
    "back in any line."
)
NOT_INTERESTED_WAY_OUT: Final = (
    "stages: no step before the last has a way out that ends the call for a person who is "
    "not interested, for whom it is not relevant, or who is the wrong person; give the step "
    "where they would say so one whose condition says so, going to end."
)


def way_out_problems(script: CallScript, before: CallScript | None = None) -> list[str]:
    """What a script for placed calls lacks of the ways out every such call needs: one to
    the call-back for "not now" and one that ends the call before the close for "not
    interested" or "wrong person". Every placed call asks something of the person (its
    opening asks whether they can talk), so none is exempt. With `before` (an edit), only a
    way out the model removed is a problem: a script that never had one is the owner's."""
    stages = script.stages
    if script.raw_override or len(stages) < 2:
        return []

    def exits(stage: ConversationStage) -> set[str]:
        return {stage.otherwise, *(b.target for b in stage.branches)}

    found: list[str] = []
    if not any(CALL_BACK in exits(stage) for stage in stages):
        found.append(NOT_NOW_WAY_OUT)
    if not any(END_OF_CALL in exits(stage) for stage in stages[:-1]):
        found.append(NOT_INTERESTED_WAY_OUT)
    if before is not None:
        had = way_out_problems(before) if len(before.stages) >= 2 else found
        found = [problem for problem in found if problem not in had]
    return found


@dataclass(frozen=True, slots=True)
class LeftOut:
    """A part of an edit that was not changed because what the model wrote for it broke a
    rule: `part` is `stages.<id>` for a step, else the field name (`stages` alone is the
    step list as a whole); `name` is the step's name; `added` marks a step the model added
    that is therefore not added; `rule` is the rule it broke, in our words. `unfixed` marks
    a warning Pip's repairs could not clear in the suggestion itself (`fix_left`), rather
    than a part kept as the owner had it."""

    part: str
    name: str
    rule: str
    added: bool = False
    unfixed: bool = False


_DRAFT_MAX_TOKENS = 4096

OWNER_QUESTIONS: Final[dict[str, str]] = {
    "what_you_offer": "What do you sell or do?",
    "customers": "Who calls you, or who will the agent call?",
    "good_outcome": "What should a good call end with?",
    "common_questions": "What do callers ask most often?",
    "never_say": "Anything the agent must never say or promise?",
    # D-945: the source of the outbound value line, kept as the owner's own true fact.
    "one_thing": "What one thing should every caller know about you?",
}

#: Told to every writer of a script whose agent introduces itself (D-865). The system
#: instructions carry `OPENING_LINE_RULE`, which names this case; the brief says it applies.
INTRODUCED_OPENING_NOTE: Final = (
    "The agent introduces itself just before its opening line: a short greeting, its name, "
    "the business and that it is an AI assistant. So the opening_line (and any "
    "outbound_opening_line) does NOT greet and does NOT say the agent's or the business's "
    "name: it says why the call is made (an agent that answers calls thanks the caller) and "
    "asks one short question."
)

_DIRECTION_SENTENCES: Final[dict[str, str]] = {
    "inbound": "The agent answers calls.",
    "outbound": "The agent places calls to leads.",
    "both": "The agent answers calls and places calls to leads.",
}


@dataclass(frozen=True, slots=True)
class ScriptBrief:
    """Everything the draft is written from. Tenant-authored configuration only: no
    transcript and no caller data (D-127 G-2), and never logged (hard rule 6)."""

    description: str = ""
    business_name: str = ""
    #: The agent's own name. Like the business name, it may stay in English letters in a
    #: spoken line (`spoken_guard.latin_words`).
    agent_name: str = ""
    business_type: str = "custom"
    direction: str = "inbound"
    #: The agent's main language (`script_proposals.brief_for` always sets it); the platform
    #: default only for a bare description, which has no agent.
    language: str = field(default_factory=platform_default_language)
    register: str = ""
    collect: tuple[str, ...] = ()
    knowledge_titles: tuple[str, ...] = ()
    answers: tuple[tuple[str, str], ...] = ()
    #: The agent's AI notice introduces it just before the opening line (D-865,
    #: `engine.introduces_itself`): the opening line then neither greets nor says who calls.
    introduced: bool = False
    #: The notices the agent's switches turn on, which its opening line says in its own words
    #: (D-971). None where nobody read the switches: the opening is then not judged on them.
    woven: WovenNotices | None = None
    #: What the agent can do on a call and where its leads come from (D-945). None when
    #: nobody read the account (a conversion), and then no promise is checked against it.
    capabilities: CapabilityManifest | None = None
    #: The owner's facts (business profile, pinned and known facts), each one line: the only
    #: figures and claims a spoken line may carry.
    facts: tuple[str, ...] = ()
    #: The business's own steps per job (`agents/starter_plans`), the ones the owner saw
    #: before creating the agent; the writer keeps their titles.
    step_plans: tuple[tuple[str, Plan], ...] = ()
    #: What the business does with its callers, its objections and its callers' questions
    #: (`agents/business_fit`), so the plan and the lines fit it rather than a shop.
    fit: BusinessFit = UNKNOWN
    #: Text a figure in a spoken line may come from that the brief does not print: an edit's
    #: change carries a campaign's main task and sources, and without this a figure from them
    #: read as one no fact gives (D-1004).
    grounding: str = ""
    #: Whether the script is said on calls the agent places: a campaign's always, an inbound
    #: line's never. None reads it from `direction`, where only an outbound agent's is; a
    #: "both" agent's own script also serves the calls it answers.
    placed_calls: bool | None = None
    #: The steps the owner laid out in their own request (`owner_plan.owner_plan`): the draft
    #: is written and checked against them instead of the trade's step plan.
    owner_plan: OwnerPlan | None = None

    def places_calls(self) -> bool:
        return self.placed_calls if self.placed_calls is not None else self.direction == "outbound"

    def lint_context(self) -> LintContext:
        """What the draft's lines are checked against (`agents/script_lint`)."""
        return LintContext(
            manifest=self.capabilities,
            facts=" ".join(
                [
                    *self.facts,
                    *(answer for _key, answer in self.answers),
                    self.description,
                    self.grounding,
                ]
            ),
            agent_name=self.agent_name,
            business_name=self.business_name,
            places_calls=self.places_calls(),
            owner_rules=owner_prohibitions(self.facts),
        )

    def user_message(self) -> str:
        lines = [
            f"Business name: {self.business_name or 'not given'}",
            # A placed call's opening says who is calling (`call_rules.PLACED_OPENING_RULE`).
            *([f"Agent name: {self.agent_name}"] if self.agent_name.strip() else []),
            f"Business type: {self.business_type}",
            _DIRECTION_SENTENCES.get(self.direction, _DIRECTION_SENTENCES["inbound"]),
            f"Call language: {self.language}",
        ]
        if self.introduced and not (self.woven is not None and self.woven.ai):
            lines.append(INTRODUCED_OPENING_NOTE)
        if self.woven is not None:
            lines.append(self.woven.brief_note())
        # The spoken-style guide for the call language (D-744): every swap, the tags and
        # fillers, the number and punctuation rules and example exchanges, so draft,
        # convert and edit all write the founder's reviewed style.
        guide = generation_guidance(self.language, self.business_type)
        if guide:
            lines.append(f"Spoken-style guide for {self.language}:\n{guide}")
        elif self.register:
            lines.append(f"Spoken register: {self.register}")
        if self.collect:
            lines.append("Details to collect: " + "; ".join(self.collect))
        if self.knowledge_titles:
            lines.append("Knowledge documents: " + "; ".join(self.knowledge_titles))
        if self.capabilities is not None:
            lines.append(self.capabilities.brief_lines())
        about = self.fit.brief_text()
        if about:
            lines.append(about)
        if self.facts:
            lines.append("The owner's facts:\n" + "\n".join(f"- {fact}" for fact in self.facts))
        for key, answer in self.answers:
            question = OWNER_QUESTIONS.get(key)
            if question and answer.strip():
                lines.append(f"{question} {answer.strip()}")
        if self.description.strip():
            lines.append(f"In the owner's words: {self.description.strip()}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _RawJson:
    """One leg's answer: the first JSON object in it (None when there was none), and what
    Azure counted. Internal to this file."""

    data: dict[str, Any] | None
    usage: TokenUsage | None = None
    service_tier: chat.ServiceTier = "standard"
    #: The `max_tokens` valve fired (`finish_reason == "length"`); `data` is then None.
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class Repair:
    """The second turn of the one repair: the leg's own answer, then what broke the rules.

    The answer travels back rather than the request being sent alone with the note: told to
    fix "these problems" and change "nothing else" in an answer it cannot see, a model writes
    a fresh answer with fresh problems, and the repair then fails as often as the first try."""

    answer: str
    note: str


def _strict(schema_name: str, schema: dict[str, object]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
    }


async def _json_via_azure(
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
    repair: Repair | None = None,
) -> _RawJson | None:
    """Ask Azure OpenAI for one JSON answer, or None if it holds no credential or did not
    answer.

    The request goes through `workers/chat.py`, the ONE chat client — the v1 surface built
    by the ONE endpoint builder, a static bearer key, Structured Outputs with a degrade to
    `json_object`.
    """
    credentials = azure_credentials()
    if credentials is None:
        return None
    resource, api_key, deployment = credentials
    leg = chat.ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )
    return await _json_via_leg(
        leg,
        AZURE_PROVIDER,
        description,
        instruction,
        response_format,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
        deadline=deadline,
        health_leg=health_leg,
        repair=repair,
    )


async def _json_via_google(
    model: str,
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
    flex: chat.FlexRequest | None = None,
    repair: Repair | None = None,
) -> _RawJson | None:
    """The account's own Gemini model on D-478's leg, or None without the key or an answer.

    Google's OpenAI-compatible surface takes a strict `json_schema` response format: its
    structured-output example passes a schema class through the client's `parse` helper
    (ai.google.dev/gemini-api/docs/openai, updated 13 Oct 2026, read 14 Oct 2026). A 400 on
    it degrades to `json_object` exactly as Azure's does.
    """
    api_key = get_settings().gemini_api_key
    if not api_key:
        return None
    leg = chat.ChatLeg(
        url=f"{google_openai_compat_base_url()}/chat/completions",
        api_key=api_key,
        wire_model=model,
        dialect="google",
    )
    return await _json_via_leg(
        leg,
        GOOGLE_PROVIDER,
        description,
        instruction,
        response_format,
        max_tokens=max_tokens,
        # Gemini 3: none sent, Google warns a lowered temperature loops (D-786).
        temperature=None if keeps_default_temperature(model) else temperature,
        timeout_s=timeout_s,
        deadline=deadline,
        health_leg=health_leg,
        flex=flex,
        repair=repair,
    )


async def _json_via_leg(
    leg: chat.ChatLeg,
    provider: str,
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int,
    temperature: float | None,
    timeout_s: float,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
    flex: chat.FlexRequest | None = None,
    repair: Repair | None = None,
) -> _RawJson | None:
    """One JSON answer from a paid leg (Azure or the account's Gemini), or None when it
    refused, could not be reached, or the assist's time budget left no room to ask.

    `flex` applies to the first ask only; a degraded re-ask goes on the standard tier.
    `repair` continues the conversation: the leg's own earlier answer as its turn, then
    what was wrong with it."""
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": description},
    ]
    if repair is not None:
        messages += [
            {"role": "assistant", "content": repair.answer},
            {"role": "user", "content": repair.note},
        ]

    async def ask(fmt: Mapping[str, Any], tier: chat.FlexRequest | None = None) -> chat.ChatOutcome:
        return await chat.complete(
            leg,
            messages,
            timeout_s=request_timeout(timeout_s, deadline),
            temperature=temperature,
            response_format=fmt,
            max_tokens=max_tokens,
            flex=tier,
        )

    try:
        try:
            outcome = await ask(response_format, flex)
        except httpx.HTTPStatusError as refusal:
            if refusal.response.status_code != 400 or response_format.get("type") != "json_schema":
                log.warning(
                    "script_assist_leg_failed",
                    extra={
                        "provider": provider,
                        "model": leg.wire_model,
                        "status": refusal.response.status_code,
                    },
                )
                await provider_health.note_failure(
                    health_leg, provider, refusal, model=leg.wire_model
                )
                return None
            # The leg refused Structured Outputs (documented, unobserved here — see
            # `AzureOpenAIExtractor`). Degrade ONCE to plain json_object; the belt is
            # `_first_json_object`. No body logged (hard rule 6): it quotes the request.
            log.warning(
                "script_assist_json_schema_unsupported",
                extra={"provider": provider, "model": leg.wire_model},
            )
            outcome = await ask({"type": "json_object"})
            flex = None
    except AssistDeadlineError:
        log.warning("script_assist_out_of_time", extra={"provider": provider})
        return None
    except httpx.HTTPError as failure:
        # A transport failure is the same OUTCOME as a refusal for this caller: the
        # selector is re-asked with `provider_unavailable=True`.
        log.warning(
            "script_assist_leg_unreachable",
            extra={
                "provider": provider,
                "model": leg.wire_model,
                **provider_health.failure_fields(failure),
            },
        )
        await provider_health.note_failure(health_leg, provider, failure, model=leg.wire_model)
        return None
    await provider_health.note_success(health_leg, provider)
    tier: chat.ServiceTier = "standard" if flex is None else outcome.service_tier
    if outcome.finish_reason == "length":
        # The `max_tokens` valve fired. The JSON was cut off mid-generation, so parsing it
        # could yield a balanced PREFIX that reads as a short answer. "No answer" is the
        # honest result, carrying the billed tokens to the meter.
        log.warning("script_assist_draft_truncated", extra={"provider": provider})
        return _RawJson(data=None, usage=outcome.usage, service_tier=tier, truncated=True)
    return _RawJson(
        data=_first_json_object(outcome.content) or None, usage=outcome.usage, service_tier=tier
    )


async def _json_via_sarvam(
    description: str,
    instruction: str,
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
) -> _RawJson | None:
    """The disclosed fallback: Sarvam's OpenAI-compatible chat, `json_object` + the belt.

    Its usage travels with the answer so `meter_assist`'s standby branch records it at the
    attested Sarvam price (absorbed). None when it refused or could not be reached.
    """
    settings = get_settings()
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        return None
    try:
        outcome = await chat.complete(
            chat.ChatLeg(
                url=SARVAM_CHAT_URL,
                api_key=settings.sarvam_api_key,
                wire_model=SARVAM_DEFAULT_LLM,
                dialect="sarvam",
            ),
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": description},
            ],
            timeout_s=request_timeout(timeout_s, deadline),
            temperature=temperature,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
    except AssistDeadlineError:
        log.warning("script_assist_out_of_time", extra={"provider": "sarvam"})
        return None
    except httpx.HTTPStatusError as refusal:
        log.warning("script_assist_sarvam_failed", extra={"status": refusal.response.status_code})
        return None
    except httpx.HTTPError as failure:
        log.warning(
            "script_assist_sarvam_unreachable", extra=provider_health.failure_fields(failure)
        )
        return None
    if outcome.finish_reason == "length":
        log.warning("script_assist_draft_truncated", extra={"provider": "sarvam"})
        return _RawJson(data=None, usage=outcome.usage, truncated=True)
    return _RawJson(data=_first_json_object(outcome.content) or None, usage=outcome.usage)


@dataclass(frozen=True, slots=True)
class JsonAnswer[T]:
    """One answer from the dashboard AI ladder, parsed; what it cost; who answered.

    `usage` is what the leg that WROTE the answer counted (both attempts when a repair was
    needed); `model` is that leg's model, which the meter prices it by
    (`crm/assist.meter_assist(model=)`) and the test loop records beside each verdict.
    `earlier` is a paid leg that answered unusably before the standby answered, metered
    separately at its own model (`crm/assist.meter_earlier`). `capability` carries the
    fallback disclosure the screen must show (G-6)."""

    value: T
    capability: AssistCapability
    usage: TokenUsage | None = None
    model: str | None = None
    earlier: tuple[PaidTurn, ...] = ()
    #: `flex` only when every attempt that wrote the answer was served on Flex (D-930).
    service_tier: chat.ServiceTier = "standard"


#: What the paid leg is told when its answer broke the caller's rules, before it is asked once
#: more. `problems` names fields and rules only, never the answer's text.
REPAIR_NOTE: Final = (
    "Your previous answer could not be used because of these problems: {problems}. "
    "Return the whole JSON again with exactly these fixed and nothing else changed."
)

#: The problem sent back when the answer's JSON did not have the shape asked for and our own
#: reading of it failed.
SHAPE_PROBLEM: Final = (
    "the JSON did not have the shape you were asked for: a value had the wrong type, such "
    "as a list where one id or one line belongs, or an object where text belongs. Every "
    "step's `target` and `otherwise` is ONE step id as text; to send the caller past "
    "several steps, point at the step after them"
)


@dataclass(slots=True)
class AskTrace:
    """What one `ask_json` went through, for the caller to record and explain: whether an
    answer was cut off at `max_tokens`, how many repairs were asked for, and the last
    problems sent back (`path: rule`, never the answer's text)."""

    truncated: bool = False
    repairs: int = 0
    problems: str = ""


ANSWER_UNUSABLE_CODE: Final = "assist_answer_unusable"


def _answer_unusable() -> ProblemError:
    return ProblemError.business_rule(
        ANSWER_UNUSABLE_CODE,
        "AI help could not make that change cleanly this time.",
        remediation="Try describing the change another way, or edit that part yourself.",
    )


class UnusableAnswerError(ValueError):
    """A parse refused the model's answer for reasons the model can be told and can fix."""

    def __init__(self, problems: str) -> None:
        super().__init__(problems)
        self.problems = problems


def _parsed_with_problems[T](
    parse: Callable[[dict[str, Any]], T | None], data: dict[str, Any] | None
) -> tuple[T | None, str | None]:
    """`_parsed`, plus the problems to send back when the parse said what was wrong."""
    if data is None:
        return None, None
    try:
        return parse(data), None
    except UnusableAnswerError as unusable:
        # The problems themselves are logged by the parse that raised them, where it knows
        # which parts are ours to log (hard rule 6); this line says a repair was asked for.
        log.info(
            "script_assist_answer_sent_back", extra={"problems": unusable.problems.count("; ") + 1}
        )
        return None, unusable.problems
    except (TypeError, ValueError, KeyError, AttributeError) as failure:
        # A value of the wrong type that our own reading tripped on. It is sent back like a
        # broken rule rather than treated as no answer: without a repair the edit went to
        # the standby, whose lower ceiling cut a whole Telugu script off (13 Nov 2026).
        log.warning(
            "script_assist_answer_unusable",
            extra={"error": type(failure).__name__, "where": _raised_at(failure)},
        )
        return None, SHAPE_PROBLEM


def _raised_at(failure: BaseException) -> str:
    """`function:line` where `failure` was raised: the code's location, never the answer."""
    frames = traceback.extract_tb(failure.__traceback__)
    return f"{frames[-1].name}:{frames[-1].lineno}" if frames else ""


def _usage_sum(first: TokenUsage | None, second: TokenUsage | None) -> TokenUsage | None:
    """Both answered attempts of one request as one metered quantity (`chat.sum_usage`): the
    reported part, marked incomplete when one attempt sent no usage block."""
    return chat.sum_usage([first, second])


def _parsed[T](
    parse: Callable[[dict[str, Any]], T | None], data: dict[str, Any] | None
) -> T | None:
    """The caller's parse of one model answer, or None. A model's JSON is untrusted input:
    a value of the wrong type (a list where a string was asked for) must read as an
    unusable answer, never escape as a 500."""
    if data is None:
        return None
    try:
        return parse(data)
    except UnusableAnswerError as unusable:
        log.warning(
            "script_assist_answer_unusable",
            extra={"error": "UnusableAnswerError", "problems": unusable.problems.count("; ") + 1},
        )
        return None
    except (TypeError, ValueError, KeyError, AttributeError) as failure:
        log.warning("script_assist_answer_unusable", extra={"error": type(failure).__name__})
        return None


async def ask_json[T](
    description: str,
    instruction: str,
    *,
    parse: Callable[[dict[str, Any]], T | None],
    azure_format: dict[str, object] | None = None,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    health_leg: provider_health.AiLeg = "script",
    gemini_only: bool = False,
    flex: FlexAllowance | None = None,
    repair_rounds: int = 1,
    salvage: Callable[[dict[str, Any]], T | None] | None = None,
    trace: AskTrace | None = None,
    standby_after_answer: bool = True,
) -> JsonAnswer[T]:
    """THE dashboard AI ladder for a JSON answer: the paid leg `assist_capability` picks (the
    account's own Gemini model when it serves the dashboard, else Azure), the disclosed
    Sarvam leg if that cannot or does not answer, a refusal only when nothing can
    (`run_assist`'s rule).

    `gemini_only` is the ladder with one rung: the Gemini leg `tenant_leg` names, with the
    one repair, and a refusal where the ladder would have gone to Azure or the Sarvam
    standby. For a job that reads callers' redacted questions and must not reach a vendor
    whose terms permit training on inputs (Sarvam ToS s.17.5, D-827).

    `parse` turns the model's JSON into the caller's value and returns None for an unusable
    answer, which counts as no answer: the next leg gets its chance. `azure_format` is the
    `response_format` the paid leg is asked for (a strict schema where the caller has one);
    Sarvam always gets `json_object`. The caller owns the prompt's content and its redaction
    (D-127 G-1/G-2): nothing here reads a transcript.

    `timeout_s` is one request budget; the whole ladder spends at most `ASSIST_LADDER_LEGS`
    of them (`extraction.ladder_deadlines`), the standby always keeping at least one. A
    route keeps the default, which nginx's deadline is pinned against
    (`tests/assist_deadline_test.py`); a worker job may give a long answer more time.

    A refusal raised after the paid leg answered is a `SpentRefusalError` carrying that spend, so
    the caller meters it (`crm/assist.meter_refusal`) before the refusal reaches anyone.

    `flex` (a job nobody waits on, `model_tiers`) asks the Gemini leg's FIRST attempt on the
    Flex tier. Its wait is added in front of the ladder's budgets rather than taken out of
    them, so a Flex fallback leaves the repair and the rest of the ladder exactly the time
    they had without it.

    REPAIR AND SALVAGE. An answer `parse` refuses with problems is sent back to the same leg
    up to `repair_rounds` times, each round with only what is still wrong. Once the rounds
    are spent, or a round never came
    back (cut off, out of time, no JSON), `salvage` reads the best answer the leg gave
    leniently, keeping what passed (the business copy's partial save), before the ladder
    moves on; the standby's answer is read the same way. `standby_after_answer=False` stops
    the ladder there instead, after a paid answer the repairs could not make usable. Every
    round is part of one metered request (`chat.sum_usage`). `trace` records what happened,
    for the caller to explain.
    """
    capability = assist_capability(
        tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, allow_azure=not gemini_only
    )
    if not capability.available:
        raise assist_unavailable(capability)
    if gemini_only and capability.provider != GOOGLE_PROVIDER:
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )

    asked = (
        flex.request(standard_timeout_s=ASSIST_LADDER_LEGS * timeout_s)
        if flex is not None and capability.provider == GOOGLE_PROVIDER and tenant_leg is not None
        else None
    )
    paid_until, standby_until = ladder_deadlines(timeout_s)
    if asked is not None:
        paid_until += asked.wait_s
        standby_until += asked.wait_s
    earlier: list[PaidTurn] = []
    answered_unusably = False
    if capability.provider in (AZURE_PROVIDER, GOOGLE_PROVIDER):
        response_format = azure_format or {"type": "json_object"}
        model: str | None = (
            tenant_leg.model
            if capability.provider == GOOGLE_PROVIDER and tenant_leg is not None
            else None
        )

        async def paid_answer(
            tier: chat.FlexRequest | None = None, repair: Repair | None = None
        ) -> _RawJson | None:
            if model is not None:
                return await _json_via_google(
                    model,
                    description,
                    instruction,
                    response_format,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_s=timeout_s,
                    deadline=paid_until,
                    health_leg=health_leg,
                    flex=tier,
                    repair=repair,
                )
            return await _json_via_azure(
                description,
                instruction,
                response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=timeout_s,
                deadline=paid_until,
                health_leg=health_leg,
                repair=repair,
            )

        paid = await paid_answer(asked)
        data = paid.data if paid is not None else None
        value, problems = _parsed_with_problems(parse, data)
        spent = paid.usage if paid is not None else None
        tier: chat.ServiceTier = paid.service_tier if paid is not None else "standard"
        if trace is not None and paid is not None and paid.truncated:
            trace.truncated = True
        sent_back = problems is not None
        rounds = 0
        while value is None and problems is not None and rounds < repair_rounds:
            rounds += 1
            tier = "standard"
            if trace is not None:
                trace.repairs, trace.problems = rounds, problems
            # A REPAIR on the same leg, told what was wrong, before the fallback. A long
            # structured answer that breaks one validation rule is usually right everywhere
            # else, and the fallback leg is slower and weaker at exactly this kind of answer.
            assert data is not None  # problems come from its parse
            repaired = await paid_answer(
                repair=Repair(
                    answer=json.dumps(data, ensure_ascii=False),
                    note=REPAIR_NOTE.format(problems=problems),
                )
            )
            if repaired is None:
                # Never reached the provider, or out of time: nothing was spent on it, and
                # the answer already given is still the best there is.
                break
            spent = _usage_sum(spent, repaired.usage)
            if trace is not None and repaired.truncated:
                trace.truncated = True
            if repaired.data is None:
                break
            data = repaired.data
            value, problems = _parsed_with_problems(parse, data)
        if value is None and sent_back and salvage is not None and data is not None:
            value = _parsed(salvage, data)
        if value is not None:
            # `None` on Azure: `meter_assist` names the live `azure_openai_model`.
            return JsonAnswer(
                value=value,
                capability=capability,
                usage=spent,
                model=model or get_settings().azure_openai_model,
                service_tier=tier,
            )
        if paid is not None:
            # Billed as a request, refused as an answer: metered at its own model.
            earlier.append(PaidTurn(spent, capability, model))
        answered_unusably = sent_back
        if answered_unusably and not standby_after_answer:
            # The paid leg answered and its repairs could not make it usable. The standby
            # writes the whole answer again under a far lower ceiling, which a long script
            # edit does not fit (13 Nov 2026: cut off at 4,096 tokens), so it is not asked.
            raise refused_after_spend(_answer_unusable(), earlier)
        if gemini_only:
            refusal = (
                _answer_unusable()
                if answered_unusably
                else assist_unavailable(
                    AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
                )
            )
            raise refused_after_spend(refusal, earlier)
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            refusal = _answer_unusable() if answered_unusably else assist_unavailable(capability)
            raise refused_after_spend(refusal, earlier)

    sarvam = await _json_via_sarvam(
        description,
        instruction,
        # Sarvam's own ceiling, whatever the paid leg was given: its lowest tier caps
        # `max_tokens` at the module's default (`_DRAFT_MAX_TOKENS`).
        max_tokens=min(max_tokens, _DRAFT_MAX_TOKENS),
        temperature=temperature,
        # The standby gets whatever the paid leg left, never less than one budget: a fixed
        # 15 s timed out on a long answer while the paid leg had failed in a second.
        timeout_s=time_left(standby_until),
        deadline=standby_until,
    )
    if trace is not None and sarvam is not None and sarvam.truncated and not answered_unusably:
        # "Too big" is the owner's answer only when no leg could finish: after a paid answer
        # that was unusable, the standby's cut-off is not why the change failed.
        trace.truncated = True
    # The standby is asked once, with no repair, so its answer is read the lenient way.
    value = _parsed(salvage or parse, sarvam.data) if sarvam is not None else None
    if value is None:
        # Both legs silent: a refusal the owner can act on, not an empty answer. When the
        # paid leg DID answer and only the shape was wrong, saying "no assistant answered"
        # would be untrue and would send the owner to support for a rewording problem.
        if sarvam is not None:
            # The standby answered unusably: its spend is ours to record too.
            earlier.append(PaidTurn(sarvam.usage, capability, SARVAM_DEFAULT_LLM))
        refusal = (
            _answer_unusable()
            if answered_unusably
            else assist_unavailable(
                AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
            )
        )
        raise refused_after_spend(refusal, earlier)
    return JsonAnswer(
        value=value,
        capability=capability,
        usage=sarvam.usage if sarvam is not None else None,
        model=SARVAM_DEFAULT_LLM,
        earlier=tuple(earlier),
    )


__all__ = [
    "ANSWER_UNUSABLE_CODE",
    "NOT_INTERESTED_WAY_OUT",
    "NOT_NOW_WAY_OUT",
    "OWNER_QUESTIONS",
    "REPAIR_NOTE",
    "SHAPE_PROBLEM",
    "AskTrace",
    "JsonAnswer",
    "LeftOut",
    "ScriptBrief",
    "UnusableAnswerError",
    "ask_json",
    "language_problems",
    "placed_paths",
    "shape_problems",
    "way_out_problems",
]

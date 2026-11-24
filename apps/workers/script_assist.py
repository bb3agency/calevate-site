"""Draft a call script from a plain-language business description — the AI writing assist.

The founder's "draft/improve my script from a business description", asked of Pip since D-820
(`copilot/script_actions.py`). The owner answers five short questions; the brief adds the
business type, the calling direction, the call
language and its register, the details the agent collects and the knowledge titles
(`ScriptBrief`), and the assistant model returns a DRAFT of every script v2 section
(`calevate_shared.call_script`) — never applied to a live call, always the author's to edit
and then save through the ordinary staged path.

WHY IT LIVES IN `apps/workers` AND REUSES THE ASSIST LADDER. CLAUDE.md's Do-NOT rule keeps
model calls out of request handlers; the dashboard-AI assist (`crm/assist.py` +
`workers/extraction.run_assist`) is the established controlled path, so this is the same
shape rather than a second one: the SAME `assist_capability` selector decides who answers
(Azure preferred, Sarvam disclosed-fallback, else a refusal), the SAME `workers/chat.py`
makes the request and reads the `usage` block back for metering, the SAME `ASSIST_TIMEOUT_S`
bounds each leg. Only the PROMPT and the OUTPUT SHAPE differ, because the task differs —
drafting a script is not extracting a lead — and a different task is exactly when a second
request shape is warranted rather than a duplicated one. The two `httpx.post` bodies that
used to live here were the SECOND and THIRD copies of one request; `workers/chat.py` is the
one copy, and it is what the in-app copilot's streaming, tool-calling turn is built on.

WHAT IT IS ALLOWED TO SEE (D-127 G-2). Its input is a TENANT-AUTHORED business description
— the client's own words about their own business — which is the "tenant-authored config"
class `AzureOpenAIExtractor` already serves, not call-transcript PII. There is no transcript
here to redact; the redaction guard that governs the re-summarise path protects a different
input. The description is still never logged (hard rule 6): it is business content.

Metering and quota are NOT decided here — `billing/ai_quota` owns both, joined by
`workers/script_proposal.py` in SUBJECT → GATE → RUN → METER order, exactly
as `crm/resummarise.second_reading` does for re-summarise. This module returns the draft and, for
an Azure answer Azure counted, its `usage`; it charges nothing.
"""

from __future__ import annotations

import json
import re
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Final

import httpx
from calevate_shared.business_frame import BUSINESSES_FRAME
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_EXAMPLE_TURNS,
    MAX_PROCEDURE_STEPS,
    MAX_PRONUNCIATIONS,
    MAX_SAMPLE_PHRASES,
    MAX_SCRIPT_FAQS,
    MAX_SCRIPT_OBJECTIONS,
    MAX_SCRIPT_STAGES,
    MAX_STAGE_BRANCHES,
    MAX_STAGE_COLLECT,
    NOTICE_RECORDS,
    PROCEDURE_STEP_MAX,
    PROCEDURE_WAIT_MAX,
    SCRIPT_SCHEMA_VERSION,
    SPECIAL_TARGETS,
    STAGE_DETAIL_MAX,
    STEP_OUTCOME_MAX,
    CallScript,
    ConversationStage,
    ExampleLine,
    FaqEntry,
    Objection,
    ProcedureStep,
    Pronunciation,
    ScriptPolicies,
    SpeakingStyle,
    StageBranch,
    StepOutcome,
    procedure_pointer,
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
from pydantic import ValidationError

from apps.api.agents.business_fit import UNKNOWN, BusinessFit
from apps.api.agents.call_rules import (
    OPENING_LINE_RULE,
    opening_redone_line_problems,
    placed_opening_problems,
    reacted_line_problems,
    said_line_problem,
    writer_rules,
)
from apps.api.agents.languages import platform_default_language
from apps.api.agents.retired_lines import retired_line_problem
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    caller_paths,
    flow_problems,
    instruction_fields,
    instruction_problems,
    placeholder_instruction,
    spoken_fields,
    spoken_line_problems,
)
from apps.api.agents.trade_playbooks import playbook_guidance
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.tenancy.business_copy import provider_problem
from apps.workers import chat
from apps.workers.campaign_script_ask import kind_ways_out
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

#: Ways out for what people really say, chosen by the kind of call (the Rytu Khata calls of
#: 20-21 Nov 2026: "I don't remember registering" and "nothing for now, later" met a script
#: with no exit, and the agent pushed on). A way out ROUTES to platform behaviour rather than
#: describing it: `call_back` compiles to the account's call-back offer, or to "the business
#: will get back to them" where call backs are off (`call_script._target_action`), and the
#: composed rules say how to book it (`engine.CALL_BACK_TIME_RULE`). Asking for a person,
#: never calling again, AI and recording questions and off-topic questions are handled by the
#: composed rules at any point, so they get no branch and the six a step holds go to what only
#: the script knows. The ways out only one kind of call meets are that kind's
#: (`campaign_script_ask.CALL_KINDS`), so the kinds are listed once. Sources and the
#: decisions: docs/evidence/script-generation-2026-11-21/
#: BRANCHES.md.
WAYS_OUT_RULE: Final = (
    "Ways out: plan, for every stage that asks the person something or asks them to do "
    "something, what they may say that does not go on, and give each its way out. A way "
    "out is a condition in plain English saying what the person says (for example: They "
    "are busy now or say they will do it later) and where the call goes: call_back, end, "
    "hand_over, or another stage. In a new script these are a stage's ways_out "
    '(each {"when", "to"}, to being "call_back", "end", "hand_over" or a stage number '
    'counting from 1); in an edit they are a stage\'s branches (each {"when", "target"}, '
    f"target being call_back, end, hand_over or a section id). At most {MAX_STAGE_BRANCHES} "
    f"ways out a stage and {MAX_SCRIPT_STAGES} stages in all, so prefer a way out to "
    "call_back or end over a new stage. "
    "On a call the agent places, cover at least: busy now or later (to call_back, on the "
    "first stage and on any stage that asks them to do something; never push the steps "
    "on someone who said not now); wrong person or wrong number (to end); not interested "
    "or not relevant to them, after at most one short answer (to end). The person who does "
    "not remember it or asks who is calling gets a stage of its own at the same step (it may "
    "take the stages past 6): its "
    "sounds_like says in one sentence who is calling and why, as the main task gives it, "
    "and asks the step's question again; it never insists they did something. Then add "
    f"only what this kind of call meets: {kind_ways_out()}. Write no way out "
    "for asking for a person, asking never to be called again, being an AI, recording, or "
    "a question off the topic: the platform handles those at any point, and an off-topic "
    "question is answered from the knowledge and the same stage goes on. A person who says "
    "they already did something the call asks goes on to the next thing they have not done, "
    "never to end while the main task still has something for them. A way out's "
    "condition never says call back or transfer; where it goes says that."
)

#: How each step and its lines are written (Rytu Khata campaign script, 23 Nov 2026: a step's
#: line greeted again after the opening, a title stood with no name, the address form was a
#: misspelt romanisation, prices and bookings were allowed on a free app-install call and the
#: quick facts promised what the sources never said). A step's outcome is a state of the
#: conversation, the way an LLM-judged transition is written (elevenlabs.io/docs/eleven-agents/
#: customization/agent-workflows, read 23 Nov 2026); the scenarios are examples of reaching it.
#: A product's screens and buttons keep their own names: on the call of 23 Nov 2026 (23:19)
#: the agent said "home screen" for the app's Dashboard. Technical style guides refer to an
#: interface element "using the element's exact label" (developer.salesforce.com/docs/
#: atlas.en-us.194.0.salesforce_pubs_style_guide, User Interface Text Guidelines; also
#: developers.google.com/style/ui-elements; read 23 Nov 2026), so the person can find it.
STEP_RULES: Final = (
    "step_outcomes has one entry per step number: one plain English sentence saying what is "
    "true once that step is done, checkable from what the person says (for example: The "
    "person says the app is open on their phone). The agent reaches it however the call goes; "
    "the step's stages are examples of how, so the outcome holds for every case the person may "
    "be in (devices, plans, yes or no), and every outcome uses the same word for the person. "
    "Each task the main task lists is the outcome of a step, in the order the call reaches it. "
    "Each stage's instruction says, in at most three short sentences, what this scenario does "
    "toward its step's outcome, what to check or ask, and when it is done. The first stage goes "
    "on from the person's answer to the opening line: no stage greets, says who is calling or "
    "asks whether now suits, in its instruction "
    'or any line in any language. mode is "say" only for a line that must be said word for '
    "word (a legal sentence, a price, an exact instruction such as a web address); every other "
    'stage is "guide". No line puts an honorific where a name belongs without the name: write '
    "{{lead_name}} before it or leave both out. address_form names the address words as the "
    "spoken lines write them, in the call language's own letters, or describes them in "
    "English; never a romanised spelling. pronunciations cover every spelling of a name that "
    "any line uses. policies: share_prices only when the owner's facts or sources give prices, "
    "take_bookings only when the call books a visit or a time, offer_call_backs unless the "
    "owner says never. A quick fact or objection answer the sources do not give offers to find "
    "out for them; it never promises what the team will do and never reassures beyond what "
    "the sources say. A stage's collect lists the details to collect it asks, each as the "
    "brief names it before any colon, and nothing the brief does not list. Every screen, "
    "tab, button, menu and feature of what the business offers is called by the exact name "
    "the brief, main task or sources give it, in instructions, small steps and spoken lines "
    "alike (a spoken line says that name in the call language's letters), never described, "
    "translated or renamed."
)

#: The instruction that turns the owner's answers into a v2 call script (first live call
#: review, 10 Oct 2026: founder decision 3). Instructions in English; only the words the
#: agent SAYS (opening, sample phrases, example call) are in the call's language, spoken and
#: code-mixed, because the in-call model follows English instructions best and the caller
#: hears only the spoken lines. A module constant so `tests/script_assist_prompt_test.py`
#: can pin its rules without a credential.
_SYSTEM_INSTRUCTION = (
    f"You write call scripts for AI phone agents of {BUSINESSES_FRAME}. You are given "
    "the business type, whether the agent answers or places calls, the call language and "
    "its spoken register, the details the agent must collect, the titles of the business's "
    "knowledge documents, and the owner's own short answers. Fill EVERY section.\n"
    "Write instructions (business_line, identity, goal, outbound_purpose, tone, "
    "address_form, stage instructions and exit conditions, objection responses, ending) in "
    "plain English letters, never in the call language's script, even when the call is in "
    "Telugu or Hindi. identity is one plain-English sentence describing the agent's job in "
    "this business's own terms, taken from the brief, never just the business name. Write "
    "the words the agent will SAY (opening_line, "
    "sounds_like, sample_phrases, example_exchange) in the call language as people really "
    "speak it on the phone, its own words in the script it is normally written in and "
    "the English words they use written as the spoken-style guide "
    "shows, "
    "never formal written language. Follow the spoken-style guide in the brief exactly: use "
    "the spoken word and never its formal form, use its tags and fillers lightly, say "
    "prices, quantities and times as its number rules say, and copy how its example "
    "exchanges sound, never their facts. Keep every spoken line to one short sentence, "
    "marked as the guide's last paragraph says. A spoken line you keep from the current "
    "script is rewritten to the guide too, its English words written as the guide shows.\n"
    f"Rules, the same ones the agent's tests check: {writer_rules()} Facts live in the "
    "knowledge base, which the agent searches. "
    "quick_facts only restates facts the owner wrote. The example_exchange shows style "
    "only and contains no fact. Outside the opening lines, do not write anything about being "
    "an AI or about recording; nowhere write about call backs or transfers, or about "
    "do-not-call requests: the platform adds those rules itself and knows what this account "
    "can do. Never write a line or step that "
    "promises what the brief says the agent can not do, and never an offer, discount, "
    "scheme or urgency; a figure only when the owner's facts give it. "
    f"{OPENING_LINE_RULE} For an agent that "
    "places calls, "
    "outbound_purpose is one sentence on why we are calling, the reason its opening says "
    "({{lead_name}} is the merge field for the lead's name); for an agent that only answers "
    "calls leave outbound_purpose empty. "
    f"Stages are 3 to {MAX_SCRIPT_STAGES}, as few as cover the main task, each with a short "
    "name, an English instruction, exit_when, and "
    "sounds_like: one short line in the call language showing how that stage sounds. "
    f"{STEP_RULES} "
    "A stage's procedure lists, in order, small actions the caller does one by one on their "
    "phone (each an English instruction with wait_for, what shows it is done); it is empty "
    "for a stage with no such actions. "
    "step is the stage's moment in the call, counting from 1; stages that are alternative "
    "ways the same moment can go share a step number. next lists the numbers (counting from "
    "1 in this list of stages) of the stages the call can go on to from this one, with 0 for "
    "ending the call; leave next empty for a straight run on to the following stage. "
    "2 to 5 objections the business really meets. 3 to 6 sample "
    "phrases. pronunciations only for names a voice might misread. code_mix is light, "
    "natural or heavy. business_line is one line under 200 characters on what the business "
    "is.\n"
    f"{WAYS_OUT_RULE}\n"
    "Return ONLY JSON matching the schema."
)

#: Converting a hand-written prompt into sections (founder, 10 Oct 2026): a proposal the
#: owner reviews, never a replacement. Keeping the owner's own sentences is what lets
#: `call_script.unplaced_lines` show anything that did not make it across.
CONVERT_INSTRUCTION = (
    "You convert a hand-written prompt for an AI phone agent into the sections of a call "
    "script. Keep the owner's own sentences word for word wherever they fit; do not "
    "summarise, drop or add facts. Put who the agent is in identity, the purpose in goal, "
    "the greeting in opening_line, each step of the call in stages (at most 12, in call "
    "order), push-back handling in objections, facts in quick_facts and the close in "
    "ending. When one step of the call is a numbered or ordered list of small actions the "
    "caller does one by one (open this, tap that, type this), put that list in the stage's "
    "procedure, one action per item in order, with wait_for saying what shows it is done "
    "(empty when the caller just says so), and keep the stage's instruction to the purpose "
    "of the step; a stage with no such list has an empty procedure. Leave a field empty when "
    "the prompt says nothing for it. Do not write about "
    "being an AI, recording, call backs, transfers or do-not-call: the platform adds those. "
    "The words the agent will SAY (opening_line, sounds_like, sample_phrases, "
    "example_exchange) follow the spoken-style guide in the brief: where the owner's line "
    "uses a formal word the guide lists, use the spoken word instead and keep the meaning; "
    "English words written as the guide shows; numbers and punctuation as the guide "
    "says. "
    "Return ONLY JSON matching the schema."
)

#: Making one change the owner asked for to the current script. Every edit the owner can make
#: by hand on the Script tab (`ScriptBuilder`, `SectionEditor`, `SectionList`: add, delete,
#: rename and move a step, its mode, instruction, line, ways out, details and small steps,
#: and every part) is named here as something the change may ask for, because a model told
#: only to "keep every section" blanked the steps it was asked to delete ("Not needed.",
#: founder, 6 Nov 2026). A deleted step is left out of `stages`; `edited_script` drops the
#: ways to it as the hand delete does (`scriptModel.removeSection`), and the review shows the
#: deletion, the rename and the move as such (`scriptDiff.diffScripts`).
EDIT_INSTRUCTION = (
    "You edit the call script of an AI phone agent. You are given the current script as "
    "JSON and one change the owner wants. Return the WHOLE script as JSON in exactly the same "
    "shape, with only that change made: keep every other field, every section and every "
    "section id as it is, and give any new section a new short lowercase id. The steps of "
    "the call are the `stages` list, in call order; leave the `steps` list exactly as it is. "
    "The change may ask to add a step, delete one, rename one (change its name, keep its "
    "id), move one (change its place in the list, keep its id), make it say exact words "
    '(mode "say") or guide (mode "guide"), or change its instruction, its sounds_like, where '
    "it goes next (otherwise) and its other ways out (branches), the details it collects, "
    "its small steps (procedure), or any other part. Do each only when the change asks for "
    "it. To delete a step, leave it out of `stages` entirely and point the ways that led to "
    "it at the step that came after it; never keep a step the change removes with an "
    'instruction like "Not needed" or an empty line. A step the change keeps for some callers '
    "only stays whole and is reached through a way out whose `when` says which callers. The "
    "last step is the close and stays, with a real line. A field the "
    "change does not need stays exactly as it is, and an EMPTY field stays empty: do not fill "
    "in parts the owner did not ask about. Instructions "
    "(business_line, identity, goal, outbound_purpose, tone, address_form, stage "
    "instructions, objection responses, ending) stay in plain English letters, never in the "
    "call language's script; words the agent says stay in the call language, spoken, its own "
    "words in the script it is normally written in and the English words people use "
    "written as the spoken-style guide in the brief shows (spoken "
    "words, never their formal forms; its number and punctuation rules). What you write "
    f"keeps the rules the agent's tests check: {writer_rules()} {OPENING_LINE_RULE} Outside "
    "the opening lines do not write about being an AI or recording, and nowhere about call "
    "backs, transfers or do-not-call. "
    f"When the change adds or rewrites steps, keep to this: {WAYS_OUT_RULE} {STEP_RULES} "
    "A step's outcome is in step_outcomes; when steps are added, moved or removed, keep each "
    "outcome on its step's number. "
    "Return ONLY JSON."
)

Parser = Callable[[dict[str, Any]], "CallScript | None"]


def _stages_where_they_belong(fields: dict[str, Any], current: CallScript) -> dict[str, Any]:
    """Move call steps the model wrote into the legacy `steps` list back into `stages`.

    A script has both: `steps` (schema 1, items carrying only an `instruction`) and
    `stages` (the steps an owner sees, each with an `id`). Asked to "keep every step", the
    model put the stages into `steps`, and every one failed as an unknown field (production,
    18 Oct 2026: 60 `extra_forbidden` errors, the same after the repair). An item with an
    `id` can only be a stage, so it is moved; the legacy list is kept as it was.
    """
    steps = fields.get("steps")
    if not isinstance(steps, list) or not steps:
        return fields
    if not all(isinstance(item, dict) and "id" in item for item in steps):
        return fields
    moved = dict(fields)
    if "stages" not in moved:
        moved["stages"] = steps
    moved["steps"] = [step.model_dump() for step in current.steps]
    return moved


#: The lines the engine speaks word for word as an opening: the answering one and a "both"
#: agent's one for the calls it places (D-920), held to the same opening rules.
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
        return [
            *flow_problems(of),
            *opening_redone_line_problems(of),
            *reacted_line_problems(of),
        ]

    owned = set(shape(before)) if before is not None else set()
    problems = [problem for problem in shape(script) if problem not in owned]
    was = {stage.id: stage for stage in before.stages} if before is not None else {}
    problems += [
        f"stages.{i}.sounds_like: is empty; write one short line in the call language "
        "showing how this step sounds."
        for i, stage in enumerate(script.stages)
        if stage.mode == "guide" and not stage.sounds_like.strip() and was.get(stage.id) != stage
    ]
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
    "first step (and any step asking them to do something) one whose condition says so, "
    "going to call_back, with no words about a call back in any line."
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


def drafted_script(
    raw: dict[str, Any],
    *,
    language: str | None,
    allowed: str = "",
    instructions: bool = True,
    names: Sequence[str] = (),
    introduced: bool = False,
    direction: str = "both",
    lint: LintContext | None = None,
    woven: WovenNotices | None = None,
) -> CallScript:
    """A whole draft (or a conversion) as `_script_from_model_json` reads it, refused with
    the language problems for the one repair when it breaks the language rules. An agent of
    one direction keeps no outbound opening, whatever the model wrote (D-920)."""
    script = _script_from_model_json(raw)
    if direction != "both":
        script = script.model_copy(update={"outbound_opening_line": ""})
    problems = language_problems(
        script,
        language,
        allowed=allowed,
        instructions=instructions,
        names=names,
        introduced=introduced,
        lint=lint,
        woven=woven,
        direction=direction,
    )
    if problems:
        log.warning("script_assist_language_unusable", extra={"count": len(problems)})
        raise UnusableAnswerError("; ".join(problems[:12]))
    return script


def edited_script(
    raw: dict[str, Any],
    current: CallScript,
    *,
    language: str | None = None,
    allowed: str = "",
    names: Sequence[str] = (),
    introduced: bool = False,
    lint: LintContext | None = None,
    woven: WovenNotices | None = None,
    lenient: bool = False,
) -> CallScript | None:
    """The model's edited script, validated like any save; None when it is not a valid
    script (the edit is then reported as no draft rather than half applied). A field the
    model changed must keep the language rules (`language_problems`); what the owner already
    had is never judged. `lenient` (an answer after the repair): a line still breaking a
    rule is put back to the owner's, and the rest is kept."""
    return salvaged_edit(
        raw,
        current,
        language=language,
        allowed=allowed,
        names=names,
        introduced=introduced,
        lint=lint,
        woven=woven,
        lenient=lenient,
    )[0]


#: The most problems one edit refusal names. The repair of an edit asks only for the parts
#: they name (`TARGETED_REPAIR_NOTE`), so a long list costs a short answer, and a part left
#: unnamed is a part the repair never gets the chance to fix.
_EDIT_PROBLEMS_SENT: Final = 30


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


def left_out_parts(
    problems: Sequence[str], edited: CallScript, current: CallScript
) -> list[LeftOut]:
    """Each part `problems` names (`path: rule`, a step by its index in `edited`), once,
    with the first rule it broke."""
    owned = {stage.id for stage in current.stages}
    found: dict[str, LeftOut] = {}
    for problem in problems:
        path, _, rule = problem.partition(": ")
        parts = path.split(".")
        if parts[0] == "stages" and len(parts) > 1 and parts[1].isdigit():
            index = int(parts[1])
            if index >= len(edited.stages):
                continue
            stage = edited.stages[index]
            entry = LeftOut(f"stages.{stage.id}", stage.name, rule, stage.id not in owned)
        else:
            entry = LeftOut(parts[0], "", rule)
        found.setdefault(entry.part, entry)
    return list(found.values())


def _validation_problems(errors: Sequence[Any]) -> list[str]:
    # Where and which rule, never the value: the value is the client's script.
    return [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors]


def _owners_fields(
    fields: dict[str, Any], current: CallScript, errors: Sequence[Any]
) -> tuple[dict[str, Any], list[LeftOut]] | None:
    """`fields` with each part a validation error names put back as `current` has it: a step
    by its id (a step the model added is dropped), any other field whole. None when an error
    names no part (a rule over the whole script), which nothing put back can be sure to fix."""
    stages = fields.get("stages")
    owned = {stage.id: stage for stage in current.stages}
    bad_stages: dict[int, str] = {}
    bad_fields: dict[str, str] = {}
    for error in errors:
        loc = error["loc"]
        if not loc:
            return None
        head = str(loc[0])
        if head == "stages" and len(loc) > 1 and isinstance(loc[1], int):
            if not isinstance(stages, list) or loc[1] >= len(stages):
                return None
            bad_stages.setdefault(loc[1], error["msg"])
        elif head in fields and head != "stages":
            bad_fields.setdefault(head, error["msg"])
        else:
            return None
    left_out = [LeftOut(name, "", rule) for name, rule in bad_fields.items()]
    kept = {k: v for k, v in fields.items() if k not in bad_fields}
    if bad_stages and isinstance(stages, list):
        rebuilt: list[Any] = []
        for i, item in enumerate(stages):
            if i not in bad_stages:
                rebuilt.append(item)
                continue
            stage_id = str(item.get("id", "")) if isinstance(item, dict) else ""
            name = str(item.get("name", "")) if isinstance(item, dict) else ""
            mine = owned.get(stage_id)
            left_out.append(LeftOut(f"stages.{stage_id}", name, bad_stages[i], mine is None))
            if mine is not None:
                rebuilt.append(mine.model_dump())
        kept["stages"] = ways_to_kept_steps(rebuilt)
    return kept, left_out


def salvaged_edit(
    raw: dict[str, Any],
    current: CallScript,
    *,
    language: str | None = None,
    allowed: str = "",
    names: Sequence[str] = (),
    introduced: bool = False,
    lint: LintContext | None = None,
    woven: WovenNotices | None = None,
    lenient: bool = False,
    direction: str = "inbound",
) -> tuple[CallScript, list[LeftOut]]:
    """`edited_script`, plus the parts a `lenient` read put back as the owner had them.

    Strict (the first answer, and each targeted repair): any broken rule refuses the answer
    with the problems for the repair. Lenient (once the repairs are spent, or a repair never
    came back): each part still breaking a rule, or failing the script's own validation, is
    put back as the owner had it and the rest is kept, the business copy's `salvage` rule
    applied to an edit. Only an answer with nothing left once those parts are put back is
    refused, and that refusal carries the parts (`UnusableAnswerError.left_out`)."""
    fields = _stages_where_they_belong(
        {k: v for k, v in raw.items() if k in CallScript.model_fields and k not in NOTICE_RECORDS},
        current,
    )
    if isinstance(fields.get("stages"), list):
        # A step the change deleted leaves ways out pointing at it; they go as in a hand
        # delete, so the deletion is a valid script rather than a refused answer.
        fields = {**fields, "stages": ways_to_kept_steps(fields["stages"])}
    put_back: list[LeftOut] = []
    try:
        edited = CallScript.model_validate({**current.model_dump(), **fields})
    except ValidationError as invalid:
        errors = invalid.errors(include_input=False, include_url=False)
        problems = _validation_problems(errors[:_EDIT_PROBLEMS_SENT])
        # One string, not a list: the log formatter reduces a list to "[N items]", which hid
        # exactly what an operator needs here. Paths and rule types only.
        where = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])} {error['type']}"
            for error in errors[:8]
        )
        log.warning("script_assist_edit_unusable", extra={"where": where, "count": len(errors)})
        owners = _owners_fields(fields, current, errors) if lenient else None
        if owners is None:
            raise UnusableAnswerError("; ".join(problems)) from invalid
        try:
            edited = CallScript.model_validate({**current.model_dump(), **owners[0]})
        except ValidationError:
            raise UnusableAnswerError("; ".join(problems)) from invalid
        put_back = owners[1]
    if lenient:
        # Blanked again after its repair: the step was meant to go, so it goes, and the
        # review shows it as a step Pip removes, unticked until the owner keeps it.
        edited = without_placeholder_steps(edited)
    problems = language_problems(
        edited,
        language,
        before=current,
        allowed=allowed,
        names=names,
        introduced=introduced,
        lint=lint,
        woven=woven,
        direction=direction,
    )
    if problems and lenient:
        # The lines still breaking a rule go back to the owner's, and the rest of the change
        # is kept (A-07), rather than the owner getting nothing.
        put_back += left_out_parts(problems, edited, current)
        edited = owners_where(edited, current, problems)
        if edited == current:
            refused = UnusableAnswerError("; ".join(problems[:_EDIT_PROBLEMS_SENT]))
            refused.left_out = tuple(put_back)
            raise refused
        log.info("script_assist_lines_put_back", extra={"count": len(put_back)})
        problems = []
    if problems:
        log.warning("script_assist_language_unusable", extra={"count": len(problems)})
        raise UnusableAnswerError("; ".join(problems[:_EDIT_PROBLEMS_SENT]))
    if lenient and put_back and edited == current:
        refused = UnusableAnswerError("; ".join(f"{p.part}: {p.rule}" for p in put_back))
        refused.left_out = tuple(put_back)
        raise refused
    return edited.model_copy(update={"raw_override": None, "schema_version": 2}), put_back


def owners_where(edited: CallScript, current: CallScript, problems: Sequence[str]) -> CallScript:
    """`edited` with each part a problem names put back as `current` has it: a step by its
    id (a step the model added is dropped), any other part whole. A problem names its part
    first ("stages.2.instruction: ...")."""
    stages = list(edited.stages)
    update: dict[str, Any] = {}
    for problem in problems:
        path = problem.partition(": ")[0].split(".")
        part = path[0]
        if part == "stages" and len(path) > 1 and path[1].isdigit():
            index = int(path[1])
            if index >= len(edited.stages):
                continue
            stage_id = edited.stages[index].id
            owned = next((s for s in current.stages if s.id == stage_id), None)
            stages = [
                kept for s in stages if (kept := (owned if s.id == stage_id else s)) is not None
            ]
            update["stages"] = stages
        elif part in CallScript.model_fields and part not in NOTICE_RECORDS:
            update[part] = getattr(current, part)
    if not update:
        return edited
    return _with_kept_ways(edited.model_copy(update=update))


def ways_to_kept_steps(stages: list[Any]) -> list[Any]:
    """`stages` (as JSON) with every way out to a step not in the list removed, as the
    Script tab's own delete does (`scriptModel.removeSection`): a branch to it goes, and an
    `otherwise` to it falls back to the next step in the list. A way out to a step that is
    gone would be refused at save. Items that are not steps are left for validation.

    The model's JSON is untrusted: an id, `otherwise` or `target` that is not a string (a
    list of steps where one was asked for) is left for validation to name as a problem, so
    the repair can fix it. A set lookup on it raised TypeError, which skipped the repair and
    sent the edit to the standby (production, 13 Nov 2026)."""
    ids = {s["id"] for s in stages if isinstance(s, dict) and isinstance(s.get("id"), str)}
    ids |= SPECIAL_TARGETS

    def gone(target: object) -> bool:
        return target is None or (isinstance(target, str) and target not in ids)

    out: list[Any] = []
    for stage in stages:
        if not isinstance(stage, dict):
            out.append(stage)
            continue
        branches = stage.get("branches")
        out.append(
            {
                **stage,
                **(
                    {"otherwise": ""} if stage.get("otherwise") and gone(stage["otherwise"]) else {}
                ),
                **(
                    {
                        "branches": [
                            b
                            for b in branches
                            if not isinstance(b, dict) or not gone(b.get("target"))
                        ]
                    }
                    if isinstance(branches, list)
                    else {}
                ),
            }
        )
    return out


def _with_kept_ways(script: CallScript) -> CallScript:
    return CallScript.model_validate(
        {**script.model_dump(), "stages": ways_to_kept_steps(script.model_dump()["stages"])}
    )


def without_placeholder_steps(script: CallScript) -> CallScript:
    """`script` without the steps whose instruction is only a placeholder ("Not needed."),
    and without the ways to them. The last step is the close and is never taken out: a
    placeholder there stays for `placeholder_problems` to refuse."""
    last = len(script.stages) - 1
    kept = [
        stage
        for i, stage in enumerate(script.stages)
        if i == last or not placeholder_instruction(stage.instruction)
    ]
    if len(kept) == len(script.stages):
        return script
    return _with_kept_ways(script.model_copy(update={"stages": kept}))


#: The ceiling on ONE draft answer, in tokens: a safety valve on a runaway generation, which
#: surfaces as `finish_reason == "length"` and is reported as "no draft" rather than parsed
#: (a truncation must not read as a short answer). A full v2 draft with a code-mixed example
#: call fits well under it.
_DRAFT_MAX_TOKENS = 4096

_STR: Final[dict[str, object]] = {"type": "string"}


def _array_of(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


#: Where a drafted way out goes (`WAYS_OUT_RULE`): a platform target or a stage number as
#: text, enumerated so Structured Outputs cannot return a target the script lacks a name for.
_WAY_OUT_TO: Final[dict[str, object]] = {
    "type": "string",
    "enum": [CALL_BACK, END_OF_CALL, HAND_OVER, *(str(n) for n in range(1, MAX_SCRIPT_STAGES + 1))],
}

_DRAFT_PROPERTIES: Final[dict[str, object]] = {
    "business_line": _STR,
    "identity": _STR,
    "goal": _STR,
    "outbound_purpose": _STR,
    "opening_line": _STR,
    "outbound_opening_line": _STR,
    "tone": _STR,
    "address_form": _STR,
    "code_mix": {"type": "string", "enum": ["light", "natural", "heavy"]},
    "sample_phrases": {"type": "array", "items": _STR},
    "pronunciations": _array_of({"word": _STR, "say_as": _STR}),
    "stages": _array_of(
        {
            "name": _STR,
            "mode": {"type": "string", "enum": ["guide", "say"]},
            "instruction": _STR,
            "sounds_like": _STR,
            "exit_when": _STR,
            "procedure": _array_of({"action": _STR, "wait_for": _STR}),
            "collect": {"type": "array", "items": _STR},
            "step": {"type": "integer"},
            "next": {"type": "array", "items": {"type": "integer"}},
            "ways_out": _array_of({"when": _STR, "to": _WAY_OUT_TO}),
        }
    ),
    "step_outcomes": _array_of({"step": {"type": "integer"}, "outcome": _STR}),
    "policies": {
        "type": "object",
        "properties": {
            "share_prices": {"type": "boolean"},
            "take_bookings": {"type": "boolean"},
            "offer_call_backs": {"type": "boolean"},
        },
        "required": ["share_prices", "take_bookings", "offer_call_backs"],
        "additionalProperties": False,
    },
    "objections": _array_of({"objection": _STR, "response": _STR}),
    "ending": _STR,
    "quick_facts": _array_of({"question": _STR, "answer": _STR}),
    "example_exchange": _array_of(
        {"speaker": {"type": "string", "enum": ["caller", "agent"]}, "text": _STR}
    ),
}

#: The strict JSON Schema for a v2 draft, so Azure's Structured Outputs guarantees the shape.
#: Sarvam gets `json_object` and `_first_json_object` as the belt.
_DRAFT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": _DRAFT_PROPERTIES,
    "required": list(_DRAFT_PROPERTIES),
    "additionalProperties": False,
}

#: The five short questions Pip asks the owner before drafting a whole script. Keys are
#: `agent_script_suggest`'s `answers` (`copilot/script_actions.py`).
OWNER_QUESTIONS: Final[dict[str, str]] = {
    "what_you_offer": "What do you sell or do?",
    "customers": "Who calls you, or who will the agent call?",
    "good_outcome": "What should a good call end with?",
    "common_questions": "What do callers ask most often?",
    "never_say": "Anything the agent must never say or promise?",
    # D-945: the source of the outbound value line, kept as the owner's own true fact.
    "one_thing": "What one thing should every caller know about you?",
}

#: How the writer uses the facts and the sixth answer (D-945, founder, 30 Oct 2026).
VALUE_FACT_NOTE: Final = (
    "For an agent that places calls, the value step says ONE of these facts, the one that "
    "answers what the lead just told it, in one sentence after the questions and before the "
    "offer; never a discount, scheme, offer, urgency or a claim like best or number one, and "
    "a claim about other customers only when a fact below says it. With no matching fact the "
    "step is skipped. Its sounds_like stays empty: any example would be a fact."
)

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
        if self.direction != "inbound":
            lines.append(VALUE_FACT_NOTE)
        for key, answer in self.answers:
            question = OWNER_QUESTIONS.get(key)
            if question and answer.strip():
                lines.append(f"{question} {answer.strip()}")
        if self.description.strip():
            lines.append(f"In the owner's words: {self.description.strip()}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ScriptDraft:
    """One AI-drafted script, what it cost, and who wrote it.

    `script` is a structured `CallScript` the builder can load directly — opening line,
    steps and FAQ, in raw pydantic-validated form so a malformed model answer is caught here
    rather than in the editor. `usage`, `model` and `earlier` are `JsonAnswer`'s.
    `capability` carries the fallback disclosure the response and screen must show (G-6).
    """

    script: CallScript
    capability: AssistCapability
    usage: TokenUsage | None = None
    #: The model that wrote it (`JsonAnswer.model`), for the meter.
    model: str | None = None
    earlier: tuple[PaidTurn, ...] = ()
    #: The parts of an edit kept as the owner had them because what the model wrote for
    #: them still broke a rule once its repairs were spent (`salvaged_edit`).
    left_out: tuple[LeftOut, ...] = ()


@dataclass(frozen=True, slots=True)
class _RawDraft:
    """The model's JSON, normalised into a `CallScript`, plus usage. Internal to this file.

    `script` is None when the model ANSWERED and the answer was unusable (truncated, or no
    JSON in it): no draft, but a billed turn whose `usage` must still reach the meter.
    """

    script: CallScript | None
    usage: TokenUsage | None = field(default=None)


def _text(raw: dict[str, Any], key: str, limit: int) -> str:
    value = raw.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


def _rows(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _next_branches(value: object, rows: list[dict[str, Any]], own: int) -> list[StageBranch]:
    """A stage's `next` numbers as ways out, each saying its target's name (the call flow's
    scenarios, founder 17 Nov 2026); [] when the model gave none it can use."""
    if not isinstance(value, list):
        return []
    out: list[StageBranch] = []
    for n in value:
        if not isinstance(n, int) or n == own or len(out) >= MAX_STAGE_BRANCHES:
            continue
        if n == 0:
            out.append(StageBranch(when="The call is done", target=END_OF_CALL))
        elif 1 <= n <= len(rows):
            name = _text(rows[n - 1], "name", 80) or f"Section {n}"
            out.append(StageBranch(when=name[:300], target=f"s{n}"))
    return list({b.target: b for b in out}.values())


def _ways_out(value: object, count: int, own: int) -> list[StageBranch]:
    """A stage's drafted `ways_out` (`WAYS_OUT_RULE`) as branches: a platform target as it
    is, a stage number as that stage's id; one with no condition, or to itself or a stage the
    draft lacks, is dropped."""
    if not isinstance(value, list):
        return []
    out: list[StageBranch] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        when = _text(item, "when", 300)
        to = _text(item, "to", 40)
        if to.isdigit() and 1 <= int(to) <= count and int(to) != own:
            target = f"s{int(to)}"
        elif to in SPECIAL_TARGETS:
            target = to
        else:
            continue
        if when:
            out.append(StageBranch(when=when, target=target))
    return list({(b.when, b.target): b for b in out}.values())


def _steps_in_order(
    stages: list[ConversationStage],
) -> tuple[list[ConversationStage], dict[int, int]]:
    """Stages sorted by step when the model numbered every one, so the call order is step by
    step; otherwise as written, with no steps (each its own step). Beside them, the model's
    step numbers as they now read, for its step outcomes."""
    if not stages or any(s.step is None for s in stages):
        return [s.model_copy(update={"step": None}) for s in stages], {}
    ordered = sorted(stages, key=lambda s: s.step or 0)
    renumber = {n: i for i, n in enumerate(sorted({s.step or 0 for s in ordered}), 1)}
    return [s.model_copy(update={"step": renumber[s.step or 0]}) for s in ordered], renumber


def _step_outcomes(raw: dict[str, Any], renumber: dict[int, int], count: int) -> list[StepOutcome]:
    """The drafted outcomes on the stages' renumbered steps (each stage its own step when the
    model numbered none), one per step, the first kept."""
    out: dict[int, StepOutcome] = {}
    for row in _rows(raw, "step_outcomes"):
        step = row.get("step")
        outcome = _text(row, "outcome", STEP_OUTCOME_MAX)
        if not isinstance(step, int) or not outcome:
            continue
        step = renumber.get(step) if renumber else (step if 1 <= step <= count else None)
        if step is not None:
            out.setdefault(step, StepOutcome(step=step, outcome=outcome))
    return sorted(out.values(), key=lambda o: o.step)


def _policies(raw: dict[str, Any]) -> ScriptPolicies:
    """The drafted policies; one the model left out keeps the default."""
    value = raw.get("policies")
    if not isinstance(value, dict):
        return ScriptPolicies()
    return ScriptPolicies(
        **{
            k: v
            for k, v in value.items()
            if k in ScriptPolicies.model_fields and isinstance(v, bool)
        }
    )


def _labels(value: object) -> list[str]:
    """A drafted stage's details to collect, as `ConversationStage.collect` holds them; which
    of them the job notes is `script_structure.collected`'s to settle."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()][:MAX_STAGE_COLLECT]


def _script_from_model_json(raw: dict[str, Any]) -> CallScript:
    """The model's JSON as a validated v2 `CallScript`.

    Tolerant: a missing or malformed piece comes back empty for the author to fill, and
    every value that does arrive is cut to the builder's own limits and validated by the
    same `CallScript` the builder saves, so a draft never carries what the editor would
    refuse. A drafted example is marked as needing a native speaker's review.
    """
    rows = [r for r in _rows(raw, "stages") if _text(r, "instruction", STAGE_DETAIL_MAX)]
    # A step written only as "Not needed." is one the model did not mean to have; the close
    # stays, for `placeholder_problems` to send back.
    rows = [
        r
        for i, r in enumerate(rows)
        if i == len(rows) - 1 or not placeholder_instruction(_text(r, "instruction", 1000))
    ][:MAX_SCRIPT_STAGES]
    stages: list[ConversationStage] = []
    for i, row in enumerate(rows, 1):
        name = _text(row, "name", 80) or f"Section {i}"
        procedure = [
            ProcedureStep(
                action=_text(step, "action", PROCEDURE_STEP_MAX),
                wait_for=_text(step, "wait_for", PROCEDURE_WAIT_MAX),
            )
            for step in _rows(row, "procedure")[:MAX_PROCEDURE_STEPS]
            if _text(step, "action", PROCEDURE_STEP_MAX)
        ]
        # Instruction, "sounds like" and the pointer to the step-by-step list share one
        # 600-character step detail.
        sounds_like = _text(row, "sounds_like", 200)
        room = STAGE_DETAIL_MAX - (len(sounds_like) + 20 if sounds_like else 0)
        if procedure:
            room -= len(procedure_pointer(name)) + 1
        exit_when = _text(row, "exit_when", 300)
        target = f"s{i + 1}" if i < len(rows) else END_OF_CALL
        step = row.get("step")
        stages.append(
            ConversationStage(
                id=f"s{i}",
                name=name,
                mode="say" if row.get("mode") == "say" else "guide",
                instruction=_text(row, "instruction", room),
                sounds_like=sounds_like,
                # The specific ways out first, as the compiled step reads them in order.
                branches=[
                    *_ways_out(row.get("ways_out"), len(rows), i),
                    *(
                        _next_branches(row.get("next"), rows, i)
                        or ([StageBranch(when=exit_when, target=target)] if exit_when else [])
                    ),
                ][:MAX_STAGE_BRANCHES],
                procedure=procedure,
                collect=_labels(row.get("collect")),
                step=step if isinstance(step, int) and 1 <= step <= MAX_SCRIPT_STAGES else None,
            )
        )
    stages, renumber = _steps_in_order(stages)
    objections = [
        Objection(objection=_text(row, "objection", 300), response=_text(row, "response", 1000))
        for row in _rows(raw, "objections")[:MAX_SCRIPT_OBJECTIONS]
        if _text(row, "objection", 300) and _text(row, "response", 1000)
    ]
    facts = [
        FaqEntry(question=_text(row, "question", 500), answer=_text(row, "answer", 2000))
        for row in _rows(raw, "quick_facts")[:MAX_SCRIPT_FAQS]
        if _text(row, "question", 500) and _text(row, "answer", 2000)
    ]
    example = [
        ExampleLine(speaker=row["speaker"], text=_text(row, "text", 500))
        for row in _rows(raw, "example_exchange")[:MAX_EXAMPLE_TURNS]
        if row.get("speaker") in ("caller", "agent") and _text(row, "text", 500)
    ]
    phrases_raw = raw.get("sample_phrases")
    phrases = (
        [p for p in phrases_raw if isinstance(p, str) and p.strip()][:MAX_SAMPLE_PHRASES]
        if isinstance(phrases_raw, list)
        else []
    )
    pronunciations = [
        Pronunciation(word=_text(row, "word", 80), say_as=_text(row, "say_as", 120))
        for row in _rows(raw, "pronunciations")[:MAX_PRONUNCIATIONS]
        if _text(row, "word", 80) and _text(row, "say_as", 120)
    ]
    code_mix = raw.get("code_mix")
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        business_line=_text(raw, "business_line", 200),
        identity=_text(raw, "identity", 1000),
        goal=_text(raw, "goal", 1000),
        outbound_purpose=_text(raw, "outbound_purpose", 300),
        opening_line=_text(raw, "opening_line", 1000),
        outbound_opening_line=_text(raw, "outbound_opening_line", 1000),
        style=SpeakingStyle(
            tone=_text(raw, "tone", 300),
            address_form=_text(raw, "address_form", 200),
            code_mix=code_mix if code_mix in ("light", "natural", "heavy") else "natural",
            sample_phrases=phrases,
            pronunciations=pronunciations,
        ),
        stages=stages,
        step_outcomes=_step_outcomes(raw, renumber, len(stages)),
        policies=_policies(raw),
        objections=objections,
        ending=_text(raw, "ending", 1000),
        faqs=facts,
        example_exchange=example,
        example_needs_review=bool(example),
    )


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


def _draft_format(*, edit: bool) -> dict[str, object]:
    # An edit returns the whole current script, whose shape the strict draft schema does
    # not describe, so it asks for plain JSON and is validated by `CallScript` instead.
    if not edit:
        return _strict("calevate_script_draft", _DRAFT_SCHEMA)
    return {"type": "json_object"}


async def _draft_via_azure(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """One Azure draft, or None if Azure holds no credential or did not answer."""
    raw = await _json_via_azure(description, instruction, _draft_format(edit=parse is not None))
    if raw is None:
        return None
    if raw.data is None:
        return _RawDraft(script=None, usage=raw.usage)
    return _RawDraft(script=(parse or _script_from_model_json)(raw.data), usage=raw.usage)


async def _draft_via_sarvam(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """One Sarvam draft, or None."""
    raw = await _json_via_sarvam(description, instruction)
    if raw is None or raw.data is None:
        return None
    return _RawDraft(script=(parse or _script_from_model_json)(raw.data))


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

#: The repair of an EDIT asks back only the parts that broke a rule, rather than the whole
#: script again (`REPAIR_NOTE`): a whole script is the longest answer this module asks for,
#: and asking for it twice is what ran a large edit out of its time and token budget, after
#: which the owner got nothing. The answer is merged onto the previous one by step id
#: (`merged_repair`), the search/replace edit's reason for existing.
TARGETED_REPAIR_NOTE: Final = (
    "Your previous answer could not be used as it is because of these problems: {problems}. "
    "Return a JSON object holding ONLY the parts these problems name, each fixed: a step goes "
    "in `stages` as the whole step with its id; any other part goes under its own name. "
    "Leave out every part the problems do not name: it is kept from your previous answer."
)

#: The problem sent back when the answer's JSON did not have the script's shape and our own
#: reading of it failed. It names no part, so its repair asks for the whole answer again
#: (`REPAIR_NOTE`) rather than for named parts (`TARGETED_REPAIR_NOTE`).
SHAPE_PROBLEM: Final = (
    "the JSON did not have the shape you were asked for: a value had the wrong type, such "
    "as a list where one id or one line belongs, or an object where text belongs. Every "
    "step's `target` and `otherwise` is ONE step id as text; to send the caller past "
    "several steps, point at the step after them"
)


@dataclass(frozen=True, slots=True)
class TargetedRepair:
    """How a repair asks for only the broken parts and folds the answer back: `note` builds
    the repair turn from the problems and the previous answer, `merge` lays the repaired
    parts over the previous answer."""

    note: Callable[[str, dict[str, Any]], str]
    merge: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class AskTrace:
    """What one `ask_json` went through, for the caller to record and explain: whether an
    answer was cut off at `max_tokens`, how many repairs were asked for, and the last
    problems sent back (`path: rule`, never the answer's text). An edit also records the
    parts it put back (`left_out`) or, when nothing was left, could not write (`unwritten`)."""

    truncated: bool = False
    repairs: int = 0
    problems: str = ""
    left_out: list[LeftOut] = field(default_factory=list)
    unwritten: list[LeftOut] = field(default_factory=list)


_STAGE_PATH: Final = re.compile(r"^stages\.(\d+)")


def targeted_note(problems: str, previous: dict[str, Any]) -> str:
    """`TARGETED_REPAIR_NOTE` for `problems`, each step named by its id as well as its place,
    so the answer can be laid back by id whatever order it comes in."""
    stages = _raw_stages(previous)

    def with_id(problem: str) -> str:
        found = _STAGE_PATH.match(problem)
        if found is None or int(found.group(1)) >= len(stages):
            return problem
        item = stages[int(found.group(1))]
        stage_id = item.get("id") if isinstance(item, dict) else None
        if not stage_id:
            return problem
        return f'{found.group(0)} (id "{stage_id}"){problem[found.end() :]}'

    return TARGETED_REPAIR_NOTE.format(
        problems="; ".join(with_id(p) for p in problems.split("; ") if p)
    )


def _raw_stages(answer: dict[str, Any]) -> list[Any]:
    stages = answer.get("stages")
    if isinstance(stages, list):
        return stages
    steps = answer.get("steps")
    # The model's slip `_stages_where_they_belong` corrects: the stages written as `steps`.
    if isinstance(steps, list) and steps and all(isinstance(s, dict) and "id" in s for s in steps):
        return steps
    return []


def merged_repair(
    previous: dict[str, Any], repaired: dict[str, Any], *, known_ids: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """`previous` with the parts `repaired` holds laid over it: a step replaces the one with
    its id; a step with an id `previous` lacks is added only when the owner's script has it
    (`known_ids`: a step the repair restores, such as a close the first answer dropped), since
    any other new id is a renamed copy that would duplicate the step; any other field replaces
    the previous one whole."""
    merged = dict(previous)
    stages = list(_raw_stages(previous))
    if "stages" not in merged and stages:
        merged["stages"] = stages
    for key, value in repaired.items():
        if key in ("stages", "steps") and isinstance(value, list):
            if key == "steps" and not all(isinstance(s, dict) and "id" in s for s in value):
                merged[key] = value
                continue
            at = {str(item.get("id")): i for i, item in enumerate(stages) if isinstance(item, dict)}
            for item in value:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                stage_id = str(item["id"])
                if stage_id in at:
                    stages[at[stage_id]] = item
                elif stage_id in known_ids:
                    stages.append(item)
            merged["stages"] = stages
        else:
            merged[key] = value
    return merged


#: The refusal code when the model answered but the answer still broke the rules after one
#: repair. Distinct from `provider_unavailable`, whose words ("no assistant answered") would be
#: untrue here.
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
        #: The parts a lenient edit read put back before nothing was left (`salvaged_edit`).
        self.left_out: tuple[LeftOut, ...] = ()


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
    targeted: TargetedRepair | None = None,
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
    up to `repair_rounds` times, each round with only what is still wrong. `targeted` makes
    each round ask for the broken parts alone and lay them over the previous answer, so a
    long answer is never asked for twice. Once the rounds are spent, or a round never came
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
            # A shape problem names no part, so a targeted repair would get nothing back to
            # lay over the answer: the whole answer is asked for again and replaces it.
            parts = targeted if problems != SHAPE_PROBLEM else None
            repaired = await paid_answer(
                repair=Repair(
                    answer=json.dumps(data, ensure_ascii=False),
                    note=(
                        parts.note(problems, data)
                        if parts is not None
                        else REPAIR_NOTE.format(problems=problems)
                    ),
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
            data = parts.merge(data, repaired.data) if parts is not None else repaired.data
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


async def draft_script(
    brief: ScriptBrief | str,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    instruction: str = _SYSTEM_INSTRUCTION,
    edit_of: CallScript | None = None,
    change: str = "",
    timeout_s: float = ASSIST_TIMEOUT_S,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    trace: AskTrace | None = None,
    repair_rounds: int | None = None,
    standby_after_answer: bool | None = None,
    owners_words: str = "",
) -> ScriptDraft:
    """Draft a `CallScript` from a business description (the AI writing assist), or, with
    `CONVERT_INSTRUCTION`, propose sections for a hand-written prompt, or, with `edit_of`,
    make one change to the current script keeping every step id.

    `quota_exhausted` is the gate's verdict passed IN (this module has no session), so the
    ceiling reaches the one function that spends a token. `tenant_leg` is the account's own
    model, passed in the same way and for the same reason — it is a row.

    `timeout_s` and `max_tokens` are one request's budget (`ask_json`); a job nobody waits on
    gives a long script more of both. An edit's repairs ask only for the broken parts, and
    what still breaks a rule after them is put back as the owner had it (`salvaged_edit`),
    recorded in `ScriptDraft.left_out` and in `trace`.

    `repair_rounds` and `standby_after_answer` override the defaults (an edit: the console's
    rounds and no standby once the account's model answered; a new script: one round, then
    the standby). A job writing a whole long script passes both, since the standby's token
    ceiling cannot hold it. `owners_words`: the owner's own text a new script is written
    from, whose words are theirs to keep (`language_problems`' `allowed`).
    """
    # A bare string is the old one-box description; the builder now sends a full brief.
    full = ScriptBrief(description=brief) if isinstance(brief, str) else brief
    description = full.user_message()
    names = (full.business_name, full.agent_name)
    parse: Parser
    salvage: Parser | None = None
    targeted: TargetedRepair | None = None
    seen = trace if trace is not None else AskTrace()
    if edit_of is not None:
        # "Change this" (founder, 10 Oct 2026): the current script with one change made,
        # section ids kept, so the Script page can show it section by section.
        instruction = EDIT_INSTRUCTION
        description = (
            f"{description}\nThe owner's change: {change.strip()}\nCurrent script (JSON):\n"
            f"{edit_of.model_dump_json(exclude={'raw_override', *NOTICE_RECORDS})}"
        )
        read_edit = partial(
            salvaged_edit,
            current=edit_of,
            language=full.language,
            allowed=change,
            names=names,
            introduced=full.introduced,
            lint=full.lint_context(),
            woven=full.woven,
            direction=full.direction,
        )

        def strict(raw: dict[str, Any]) -> CallScript | None:
            # Each answer is sent back with its problems while repairs are left.
            return read_edit(raw, lenient=False)[0]

        def lenient(raw: dict[str, Any]) -> CallScript | None:
            # The repairs spent: keep what it got right (A-07), and say what was left out.
            try:
                script, put_back = read_edit(raw, lenient=True)
            except UnusableAnswerError as nothing_left:
                seen.unwritten = list(nothing_left.left_out)
                raise
            seen.left_out, seen.unwritten = put_back, []
            return script

        parse, salvage = strict, lenient
        targeted = TargetedRepair(
            note=targeted_note,
            merge=partial(merged_repair, known_ids=frozenset(stage.id for stage in edit_of.stages)),
        )
    else:
        # A conversion keeps the owner's own sentences, in whatever language they wrote them,
        # so only a textbook word the owner did not write is the model's to fix.
        converting = instruction == CONVERT_INSTRUCTION
        if not converting:
            # D-856: a new script starts from the trade's step plan, the starters' skeleton.
            plan = playbook_guidance(
                full.business_type, full.direction, dict(full.step_plans), full.fit
            )
            description = f"{description}\n{plan}"
        parse = partial(
            drafted_script,
            language=full.language,
            allowed=full.description if converting else owners_words,
            instructions=not converting,
            names=names,
            introduced=full.introduced,
            direction=full.direction,
            lint=None if converting else full.lint_context(),
            woven=None if converting else full.woven,
        )
    answer = await ask_json(
        description,
        instruction,
        parse=parse,
        azure_format=_draft_format(edit=edit_of is not None),
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        repair_rounds=repair_rounds
        if repair_rounds is not None
        else (get_settings().script_edit_repair_rounds if targeted is not None else 1),
        targeted=targeted,
        salvage=salvage,
        trace=seen,
        # An edit the account's model answered is repaired, never rewritten by the standby.
        standby_after_answer=edit_of is None
        if standby_after_answer is None
        else standby_after_answer,
    )
    return ScriptDraft(
        script=answer.value,
        capability=answer.capability,
        usage=answer.usage,
        model=answer.model,
        earlier=answer.earlier,
        left_out=tuple(seen.left_out),
    )


__all__ = [
    "ANSWER_UNUSABLE_CODE",
    "CONVERT_INSTRUCTION",
    "EDIT_INSTRUCTION",
    "NOT_INTERESTED_WAY_OUT",
    "NOT_NOW_WAY_OUT",
    "OWNER_QUESTIONS",
    "REPAIR_NOTE",
    "SHAPE_PROBLEM",
    "TARGETED_REPAIR_NOTE",
    "WAYS_OUT_RULE",
    "AskTrace",
    "JsonAnswer",
    "LeftOut",
    "ScriptBrief",
    "ScriptDraft",
    "TargetedRepair",
    "UnusableAnswerError",
    "ask_json",
    "draft_script",
    "drafted_script",
    "edited_script",
    "language_problems",
    "left_out_parts",
    "merged_repair",
    "owners_where",
    "salvaged_edit",
    "shape_problems",
    "targeted_note",
    "way_out_problems",
    "ways_to_kept_steps",
    "without_placeholder_steps",
]

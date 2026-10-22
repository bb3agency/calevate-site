"""Ready-made agents: pick a job and a business type, get a script to review (D-705).

A new agent used to start with no script at all, and the owner faced a blank builder. The
founder's rule (redesign #2, item 5) is that the owner picks a JOB, "Answer my calls",
"Call new leads instantly" (D-855) or "Call my list", and their account's business type
fills in a ready agent: a structured call script, an opening line and the details the agent
captures. The owner reviews and adjusts it before switching it on.

WHAT A STARTER MAY SAY. A starter is written by us and stored as the owner's own script, so
it must hold for every business of its type:

* No fact that belongs to the business. Hours, prices, addresses, staff and availability
  come from the business's own information, which the agent searches; what it offers
  when the answer is missing is the platform's rule, true to what the account can do
  (`engine.compose_engine_prompt`), so no starter promises a call back.
* No disclosure, recording notice, truthful-answer or confidentiality wording. The
  platform composes those itself (`compose_engine_prompt`, D-163, D-674) and a second copy
  in the script would be a second place for them to drift.
* Trade words only for that trade (the founder's neutral-copy rule, 10 Oct 2026): a clinic
  books appointments, a property office site visits, a coaching centre counselling
  sessions, and "Something else" gets neutral words ("a booking", "your customers").
* No vendor names (D-679).
* Outbound starters follow up and take no for an answer: no pressure, and a request to
  stop calling is recorded with the do-not-call tool. The calling-hours, consent and
  do-not-call checks are the dial gate's, not the script's.

WHY ONE TABLE OF TRADE WORDS RATHER THAN TEN HAND-WRITTEN SCRIPTS. The two jobs have one
shape each; what changes per trade is a handful of nouns, the details to capture and one
caution. Ten free-standing scripts would drift apart the first time one was improved.
`tests/agent_starters_test.py` compiles every vertical and job pair and checks the wording
rules above.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, get_args
from uuid import UUID

from calevate_shared.call_script import (
    END_OF_CALL,
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
    ExampleLine,
    Objection,
    SpeakingStyle,
    StageBranch,
)
from calevate_shared.languages import get_language
from calevate_shared.spoken_style import example_exchange, native_reviewed, opening_in
from scripts.seed import CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.lead_fields import starting_business_fields
from apps.api.agents.models import AgentDirection
from apps.api.agents.script_builder import (
    load_agent_script,
    read_draft,
    rewrite_script,
    save_agent_script,
    save_draft,
)
from apps.api.agents.trade_playbooks import is_playbook_line, playbook_for
from apps.api.agents.write_guard import archived_refusal
from apps.api.core.errors import ProblemError
from apps.api.tenancy.business_copy import read_state as read_business_copy

#: `call_new_leads` rings someone minutes after they enquire (speed to lead, the ingest
#: webhook's job); `call_leads` works through a list of people who showed interest earlier.
#: Both dial out; they differ in what the agent knows about the person it rings (D-855).
StarterJob = Literal["answer_calls", "call_new_leads", "call_leads"]
STARTER_JOBS: Final[tuple[StarterJob, ...]] = get_args(StarterJob)

#: The job decides the calling direction. "Both" is not a starter: an agent that answers
#: AND dials is one an owner builds deliberately, not one a first click should produce.
#: A starter preview greets in English; a starter agent is made Telugu-first unless the
#: owner chose otherwise. Derived from the language registry, never spelled here.
PREVIEW_LANGUAGE: Final = get_language("english_india").bcp47
STARTER_LANGUAGE: Final = get_language("telugu").bcp47

JOB_DIRECTION: Final[Mapping[StarterJob, AgentDirection]] = {
    "answer_calls": "inbound",
    "call_new_leads": "outbound",
    "call_leads": "outbound",
}

#: The job's name as the owner sees it, used in the version note.
JOB_LABEL: Final[Mapping[StarterJob, str]] = {
    "answer_calls": "Answer my calls",
    "call_new_leads": "Call new leads instantly",
    "call_leads": "Call my list",
}

#: The business copy writes one set of example lines per step shape
#: (`tenancy/business_copy.StarterLines`). The two outbound jobs share a shape step for step,
#: so new-lead calls use the list's lines rather than a third set the model would have to
#: write and the parser would have to count.
LineSet = Literal["answer_calls", "call_leads"]
LINE_SETS: Final[tuple[LineSet, ...]] = get_args(LineSet)
LINES_OF_JOB: Final[Mapping[StarterJob, LineSet]] = {
    "answer_calls": "answer_calls",
    "call_new_leads": "call_leads",
    "call_leads": "call_leads",
}

#: The business type an account with no template, or an unknown one, is treated as; never
#: the clinic.
NEUTRAL_VERTICAL: Final = "custom"


@dataclass(frozen=True, slots=True)
class Trade:
    """The words one business type puts into both jobs' scripts."""

    #: The agent name offered for each job.
    receptionist_name: str
    caller_name: str
    #: What callers ask about, for the business-information step ("timings and fees").
    topics: str
    #: The thing a caller books, with its article ("an appointment", "a booking").
    booking: str
    #: The details to ask for, in the order a conversation reaches them. They must stay
    #: within the vertical's extraction fields (PROMPT-GUIDE §4: never ask for a field the
    #: schema does not capture).
    capture: str
    #: The one thing this trade's agent must never do, as an instruction.
    caution: str


TRADES: Final[Mapping[str, Trade]] = {
    "clinic": Trade(
        receptionist_name="Clinic receptionist",
        caller_name="Patient follow-up",
        topics="the doctors, timings, consultation fees or location",
        booking="an appointment",
        capture=(
            "the reason for the visit, how soon they need to be seen, the day and time "
            "they prefer, any doctor they ask for, and whether they will use insurance"
        ),
        caution=(
            "Never give medical advice or a diagnosis. If it sounds like an emergency, ask "
            "them to go to the nearest hospital or call emergency services straight away."
        ),
    ),
    "real_estate": Trade(
        receptionist_name="Property enquiries",
        caller_name="Buyer follow-up",
        topics="the projects, prices, locations or loan approvals",
        booking="a site visit",
        capture=(
            "the area they want, the size of home (how many BHK), their budget, and when "
            "they plan to buy"
        ),
        caution=(
            "Never quote a final price or promise that a unit is still available; offer a "
            "site visit instead."
        ),
    ),
    "insurance": Trade(
        receptionist_name="Policy desk",
        caller_name="Policy follow-up",
        topics="the policies, premiums, renewals or claims",
        booking="a conversation with an advisor",
        capture=(
            "the kind of policy they want, the cover amount they have in mind, when their "
            "renewal is due, and who insures them today"
        ),
        caution=(
            "Never confirm a premium, a cover amount or a claim outcome on the phone; take "
            "the details for an advisor."
        ),
    ),
    "education": Trade(
        receptionist_name="Admissions desk",
        caller_name="Admissions follow-up",
        topics="the courses, batch timings, fees or admissions",
        booking="a counselling session",
        capture=(
            "the course they are interested in, the student's class or year, any concern "
            "about fees, and whether they would like a demo class"
        ),
        caution=(
            "Never promise a seat, a scholarship or a result; offer a counselling session instead."
        ),
    ),
    # The three types of founder decision 10. `capture` stays within each type's fields
    # plus the core every lead carries (`scripts/seed.VERTICAL_TEMPLATES`,
    # `calevate_shared.lead_fields`).
    "retail": Trade(
        receptionist_name="Shop counter",
        caller_name="Order follow-up",
        topics="what is in stock, prices, timings or delivery",
        booking="an order",
        capture=(
            "what they want to buy, how much, whether they will pick it up or want it "
            "delivered, and the area to deliver to"
        ),
        caution=(
            "Never confirm stock, a price or a delivery time you have not been told; take "
            "the order details for the shop to confirm."
        ),
    ),
    "local_services": Trade(
        receptionist_name="Front desk",
        caller_name="Customer follow-up",
        topics="the services, prices, timings or location",
        booking="a slot",
        capture=(
            "the service they want, whether they will come in or want someone to come to "
            "them, the area for a home visit, anyone they ask for by name, and the day and "
            "time they prefer"
        ),
        caution=(
            "Never promise a slot or a person's availability without checking; take the "
            "details for the team to confirm."
        ),
    ),
    "automobile": Trade(
        receptionist_name="Service desk",
        caller_name="Service follow-up",
        topics="servicing, repairs, spare parts, prices or timings",
        booking="a service slot",
        capture=(
            "the vehicle and its model, what work it needs, the registration if they have "
            "it, whether they want it picked up, and the day that suits them"
        ),
        caution=(
            "Never quote a repair cost or a delivery date before the vehicle is inspected; "
            "offer an inspection instead."
        ),
    ),
    NEUTRAL_VERTICAL: Trade(
        receptionist_name="Receptionist",
        caller_name="Lead follow-up",
        topics="what you offer, prices, timings or location",
        booking="a booking",
        capture="what they need and the day or time that suits them",
        caution=(
            "Never promise a price, a delivery date or availability without checking; say the "
            "team will confirm."
        ),
    ),
}


def vertical_of(vertical_template: str | None) -> str:
    """The catalogue row for an account's business type, falling back to the neutral one."""
    if vertical_template is not None and vertical_template in TRADES:
        return vertical_template
    return NEUTRAL_VERTICAL


def captured_fields(vertical: str) -> list[dict[str, Any]]:
    """The extraction fields a starter gives the agent: the vertical template's.

    A business type with no template, or an unknown one, gets the neutral set.
    """
    return VERTICAL_TEMPLATES.get(vertical, CUSTOM_EXTRACTION_FIELDS)


@dataclass(frozen=True, slots=True)
class StarterStep:
    """One conversation stage: a short title, the instruction, and when it is done."""

    title: str
    instruction: str
    exit_when: str = ""
    #: How the step sounds, per language (D-856, `trade_playbooks`).
    say: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class Starter:
    """One vertical and job starter, before the business's name is filled in.

    Written in the script v2 sections (`calevate_shared.call_script`). Instructions are in
    English; the example call is in the agent's language, from `spoken_style.json`, and is
    marked for a native speaker's review. What the agent does when it cannot help, the
    hand-over, call backs and do-not-call requests are the platform's rules
    (`engine.compose_engine_prompt`), true to what the account can do, so no starter
    repeats them.
    """

    job: StarterJob
    vertical: str
    name_suggestion: str
    #: `{business}` is replaced by the account's own name when the script is written.
    opening_line: str
    business_line: str
    identity: str
    goal: str
    outbound_purpose: str
    steps: tuple[StarterStep, ...]
    objections: tuple[tuple[str, str], ...]
    ending: str

    def opening_for(self, business: str, language: str = PREVIEW_LANGUAGE) -> str:
        """The greeting in the agent's language where `spoken_style.json` has one (a Telugu
        agent greets in Telugu), else the English template."""
        direction = JOB_DIRECTION[self.job]
        template = opening_in(language, direction) or self.opening_line
        return template.replace("{business}", business)

    def call_script(self, *, business: str, language: str = STARTER_LANGUAGE) -> CallScript:
        """The structured script the agent is created with. Validated by `CallScript`."""
        example = example_exchange(language, self.vertical)
        return CallScript(
            schema_version=SCRIPT_SCHEMA_VERSION,
            business_line=self.business_line.replace("{business}", business)[:200],
            identity=self.identity.replace("{business}", business),
            goal=self.goal,
            outbound_purpose=self.outbound_purpose.replace("{business}", business),
            opening_line=self.opening_for(business, language),
            style=SpeakingStyle(
                tone="Warm, calm and brief, like a helpful person at the front desk."
            ),
            stages=self.sections(language),
            objections=[Objection(objection=o, response=r) for o, r in self.objections],
            ending=self.ending,
            example_exchange=[ExampleLine(speaker=t.speaker, text=t.text) for t in example],
            # Reviewed once the founder publishes this language as reviewed (D-744).
            example_needs_review=bool(example) and not native_reviewed(language),
        )

    def sections(self, language: str = STARTER_LANGUAGE) -> list[ConversationStage]:
        """The steps as script sections, ids `s1`..`sN` in call order. A step's "done
        when" becomes the branch that moves on: to the next section, or the end. Each step
        sounds like its plan's line in `language`, where the plan has one."""
        out: list[ConversationStage] = []
        for i, step in enumerate(self.steps, 1):
            target = f"s{i + 1}" if i < len(self.steps) else END_OF_CALL
            branches = [StageBranch(when=step.exit_when, target=target)] if step.exit_when else []
            out.append(
                ConversationStage(
                    id=f"s{i}",
                    name=step.title,
                    instruction=step.instruction,
                    sounds_like=(step.say or {}).get(language, ""),
                    branches=branches,
                )
            )
        return out

    def authored_text(self) -> str:
        """Every English sentence this starter writes, for the wording tests. The example
        call is data reviewed separately (`spoken_style.json`)."""
        parts = [
            self.name_suggestion,
            self.opening_line,
            self.business_line,
            self.identity,
            self.goal,
            self.outbound_purpose,
            self.ending,
        ]
        parts += [f"{step.title} {step.instruction} {step.exit_when}" for step in self.steps]
        parts += [f"{o} {r}" for o, r in self.objections]
        return "\n".join(p for p in parts if p)


_ENDING: Final = (
    "Once the next step is agreed or they have what they need, thank them by name if you "
    "have it, say goodbye and end the call."
)

#: The outbound starter's one per-call value, in its LAST section. The engine caches the
#: prompt up to the first value it fills per call (VENDOR-STATED, ThinnestAI email of 18 Oct
#: 2026), so a `{{lead_name}}` in the second step left every stage, objection and
#: policy after it outside the cache (D-816).
_CALL_LEADS_ENDING: Final = (
    f"{_ENDING}\nThe person you are calling, if you have their name: {{{{lead_name}}}}"
)


def _planned_steps(vertical: str, job: StarterJob, trade: Trade) -> tuple[StarterStep, ...]:
    """The starter's steps from the trade's plan (D-856, `trade_playbooks`)."""
    return tuple(
        StarterStep(step.title, step.instruction, step.exit_when, step.say)
        for step in playbook_for(vertical, job, trade).steps
    )


def _answer_calls(vertical: str, trade: Trade) -> Starter:
    return Starter(
        job="answer_calls",
        vertical=vertical,
        name_suggestion=trade.receptionist_name,
        opening_line="Hello, thank you for calling {business}. How can I help you today?",
        business_line="{business}",
        identity=(
            "You answer the phone for {business}. You are friendly, quick and practical, and "
            f"you help callers with {trade.topics}."
        ),
        goal=(
            f"Understand what each caller needs, answer it from the business's facts, and "
            f"where it fits, arrange {trade.booking} or take their details for the team."
        ),
        outbound_purpose="",
        steps=_planned_steps(vertical, "answer_calls", trade),
        objections=playbook_for(vertical, "answer_calls", trade).objections,
        ending=_ENDING,
    )


def _call_leads(vertical: str, trade: Trade) -> Starter:
    return Starter(
        job="call_leads",
        vertical=vertical,
        name_suggestion=trade.caller_name,
        opening_line=(
            "Hello, I am calling from {business} to follow up with you. Is this a good time "
            "for a quick chat?"
        ),
        business_line="{business}",
        identity=(
            "You call people who showed interest in {business}, to follow up. You are polite, "
            "brief and never pushy."
        ),
        goal=(
            f"Find out whether they are still interested and, if they are, arrange "
            f"{trade.booking}. Take no for an answer."
        ),
        outbound_purpose=(
            "You are following up on their interest in {business} to see if you can help."
        ),
        steps=_planned_steps(vertical, "call_leads", trade),
        objections=playbook_for(vertical, "call_leads", trade).objections,
        ending=_CALL_LEADS_ENDING,
    )


def _call_new_leads(vertical: str, trade: Trade) -> Starter:
    """Rings a person minutes after they enquired. The plan keeps the list's step shape, so
    the business copy's example lines fit both (`LINES_OF_JOB`)."""
    return Starter(
        job="call_new_leads",
        vertical=vertical,
        name_suggestion=trade.caller_name,
        opening_line=(
            "Hello, I am calling from {business} about the enquiry you just made. Is this a "
            "good time for a quick chat?"
        ),
        business_line="{business}",
        identity=(
            "You call people within minutes of their enquiry to {business}, while it is "
            "still fresh. You are polite, brief and never pushy."
        ),
        goal=(
            f"Help with the enquiry they just made and, if they are interested, arrange "
            f"{trade.booking}. Take no for an answer."
        ),
        outbound_purpose=(
            "They just made an enquiry with {business}, and you are calling to help with it."
        ),
        steps=_planned_steps(vertical, "call_new_leads", trade),
        objections=playbook_for(vertical, "call_new_leads", trade).objections,
        ending=_CALL_LEADS_ENDING,
    )


_BUILDERS: Final = {
    "answer_calls": _answer_calls,
    "call_new_leads": _call_new_leads,
    "call_leads": _call_leads,
}

#: Every starter, keyed by (vertical, job). Built once at import: the catalogue is
#: constant, and building it here makes a malformed starter an import-time failure.
CATALOGUE: Final[Mapping[tuple[str, StarterJob], Starter]] = {
    (vertical, job): _BUILDERS[job](vertical, trade)
    for vertical, trade in TRADES.items()
    for job in STARTER_JOBS
}


def starter_for(vertical_template: str | None, job: StarterJob) -> Starter:
    return CATALOGUE[(vertical_of(vertical_template), job)]


def direction_for(job: StarterJob, requested: AgentDirection | None) -> AgentDirection:
    """The direction a starter's job sets, refusing an explicit direction that contradicts it."""
    direction = JOB_DIRECTION[job]
    if requested is not None and requested != direction:
        raise ProblemError(
            kind="validation",
            code="starter_direction_mismatch",
            title="The job and the calling direction disagree",
            detail=(
                f'"{JOB_LABEL[job]}" makes an agent that only takes {direction} calls. '
                "Leave the direction out, or choose the other job."
            ),
            fields=[{"name": "direction", "reason": f"must be {direction} for this job"}],
        )
    return direction


async def apply_starter(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    job: StarterJob,
    vertical_template: str | None,
    business: str,
    created_by: UUID | None,
    language: str = STARTER_LANGUAGE,
) -> int:
    """Write the starter as the agent's first script version and set its captured details.

    The script goes through `save_agent_script`, the builder's own save, so the stored body
    is the compile of the stored structure and the version is staged or applied by the same
    rule as any edit (a new agent is a draft, so it is applied to the draft and reaches no
    caller until the agent is published). The extraction schema goes through
    `write_schema`, the extraction screen's own write; a new agent has none yet. The schema
    is written FIRST, because the script's "what to collect" section is compiled from it at
    the save. `language` picks the example call (`spoken_style.json`). Returns the script
    version.
    """
    vertical = vertical_of(vertical_template)
    starter = CATALOGUE[(vertical, job)]
    # The ACCOUNT's business fields, not the starter catalogue's vertical: a type with no
    # starter row of its own (a shop) still gets its own standard set, and a custom business
    # gets its one AI draft once it exists (`agents/lead_fields`).
    fields = await starting_business_fields(
        session, tenant_id=tenant_id, vertical=vertical_template
    )
    validate_fields(fields)
    await write_schema(session, agent_id=agent_id, fields=fields)
    script = starter.call_script(business=business, language=language)
    stored = await read_business_copy(session)
    if stored is not None and stored.copy is not None and stored.language == language:
        script = with_example_lines(script, getattr(stored.copy.starter_lines, LINES_OF_JOB[job]))
    saved = await save_agent_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=script,
        notes=f"Ready-made starter: {JOB_LABEL[job]}",
        created_by=created_by,
    )
    return saved.version


def with_example_lines(script: CallScript, lines: Sequence[str]) -> CallScript:
    """The starter with the business's AI-written example line on each step (D-827).

    Only a NEW agent's script gets them, and only into an "example line" that is empty or
    still the trade plan's own: nothing a person wrote is there to replace. A line that
    would push its step past the engine's step limit is left out, and lines written for a
    different number of steps are not used at all. A starter that carries them no longer
    matches the bare catalogue, so `replace_unedited_starter` treats it as edited and leaves
    it alone, which is the safe side of that comparison."""
    if len(lines) != len(script.stages):
        return script
    stages: list[ConversationStage] = []
    for stage, line in zip(script.stages, lines, strict=True):
        # A plan's own line (D-856) gives way to the business's: both are ours, not a person's.
        if (stage.sounds_like.strip() and not is_playbook_line(stage.sounds_like)) or not (
            line.strip()
        ):
            stages.append(stage)
            continue
        try:
            stages.append(
                ConversationStage.model_validate({**stage.model_dump(), "sounds_like": line})
            )
        except ValueError:
            stages.append(stage)
    return script.model_copy(update={"stages": stages})


#: The jobs an agent's direction may have come from. "both" has none: no starter makes such
#: an agent. Outbound has two, told apart by the script's content (`starter_vertical_of`).
JOBS_OF_DIRECTION: Final[Mapping[str, tuple[StarterJob, ...]]] = {
    direction: tuple(job for job in STARTER_JOBS if JOB_DIRECTION[job] == direction)
    for direction in set(JOB_DIRECTION.values())
}


def _canonical(script: CallScript) -> dict[str, Any]:
    # Quick facts move to the business's pinned facts at every save, so a stored script
    # never carries them; compared without them.
    return script.model_copy(update={"faqs": []}).model_dump(mode="json")


def starter_vertical_of(
    stored: Mapping[str, Any], *, job: StarterJob, business: str, language: str
) -> str | None:
    """The business type whose starter wrote `stored`, if nobody has changed it since.

    Recognised by content rather than by a version note, because the script's structure is
    what the owner edits and a recompile (`recompile_collect`) writes new versions without
    touching it. A starter written under an earlier business name, an earlier catalogue
    wording or another language does not match, and is treated as edited.
    """
    try:
        script = _canonical(CallScript.model_validate(stored))
    except ValueError:
        return None
    for vertical in TRADES:
        candidate = CATALOGUE[(vertical, job)].call_script(business=business, language=language)
        if _canonical(candidate) == script:
            return vertical
    return None


async def replace_unedited_starter(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int | None:
    """Put the account's business type's starter on an agent still carrying another type's.

    For an operator confirming a business type (D-722): an agent made from the old type's
    starter would otherwise keep that trade's words ("appointment", "doctor") however the
    type changed. Only when the draft is a starter exactly as written, with no autosaved
    working copy and no staged edit; anything an owner changed is left alone. An account
    whose type is still unconfirmed keeps its scripts. Returns the new version, or None.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, pv.structured_script, o.name, "
                "o.vertical_template, a.script_draft IS NOT NULL, "
                "(a.live_prompt_id IS NOT NULL "
                "AND a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
                "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or row[4] is None or row[5] or row[6] or not isinstance(row[2], dict):
        return None
    business, language = str(row[3]), str(row[1])
    found = next(
        (
            (job, vertical)
            for job in JOBS_OF_DIRECTION.get(str(row[0]), ())
            if (
                vertical := starter_vertical_of(
                    row[2], job=job, business=business, language=language
                )
            )
            is not None
        ),
        None,
    )
    if found is None:
        return None
    job, written_for = found
    target = vertical_of(str(row[4]))
    if written_for == target:
        return None
    return await rewrite_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=CATALOGUE[(target, job)].call_script(business=business, language=language),
        notes=f"Ready-made starter: {JOB_LABEL[job]} (business type changed)",
    )


@dataclass(frozen=True, slots=True)
class RewrittenOpening:
    opening_line: str
    saved_at: datetime


async def rewrite_opening_in_language(session: AsyncSession, agent_id: UUID) -> RewrittenOpening:
    """Put the ready-made opening line in the agent's main language into its working copy.

    The owner's one click after changing the main language (D-838). The line is the one a
    starter agent of this business type greets with in that language, so it is a sentence
    we wrote and reviewed rather than a machine translation of the owner's. It goes into the
    autosaved draft and reaches no caller until the owner puts it live; the rest of the
    working copy is kept.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, o.name, o.vertical_template, a.status "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    if str(row[4]) == "archived":
        raise archived_refusal("edited")
    # A "both" agent greets as the receptionist: it is the caller who rang who hears it first.
    job: StarterJob = "call_leads" if str(row[0]) == "outbound" else "answer_calls"
    line = starter_for(None if row[3] is None else str(row[3]), job).opening_for(
        str(row[2]), str(row[1])
    )
    draft = await read_draft(session, agent_id)
    script = (
        draft.script if draft is not None else (await load_agent_script(session, agent_id)).script
    )
    saved_at = await save_draft(session, agent_id, script.model_copy(update={"opening_line": line}))
    return RewrittenOpening(opening_line=line, saved_at=saved_at)


__all__ = [
    "CATALOGUE",
    "JOBS_OF_DIRECTION",
    "JOB_DIRECTION",
    "JOB_LABEL",
    "LINES_OF_JOB",
    "LINE_SETS",
    "NEUTRAL_VERTICAL",
    "STARTER_JOBS",
    "TRADES",
    "LineSet",
    "RewrittenOpening",
    "Starter",
    "StarterJob",
    "StarterStep",
    "Trade",
    "apply_starter",
    "captured_fields",
    "direction_for",
    "replace_unedited_starter",
    "rewrite_opening_in_language",
    "starter_for",
    "starter_vertical_of",
    "vertical_of",
    "with_example_lines",
]

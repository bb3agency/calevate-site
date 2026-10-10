"""Ready-made agents: pick a job and a business type, get a script to review (D-705).

A new agent used to start with no script at all, and the owner faced a blank builder. The
founder's rule (redesign #2, item 5) is that the owner picks a JOB, "Answer my calls" or
"Call my leads", and their account's business type fills in a ready agent: a structured
call script, an opening line and the details the agent captures. The owner reviews and
adjusts it before switching it on.

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

from collections.abc import Mapping
from dataclasses import dataclass
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
from calevate_shared.spoken_style import example_exchange, opening_in
from scripts.seed import CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.lead_fields import starting_business_fields
from apps.api.agents.models import AgentDirection
from apps.api.agents.script_builder import save_agent_script
from apps.api.core.errors import ProblemError

StarterJob = Literal["answer_calls", "call_leads"]
STARTER_JOBS: Final[tuple[StarterJob, ...]] = get_args(StarterJob)

#: The job decides the calling direction. "Both" is not a starter: an agent that answers
#: AND dials is one an owner builds deliberately, not one a first click should produce.
JOB_DIRECTION: Final[Mapping[StarterJob, AgentDirection]] = {
    "answer_calls": "inbound",
    "call_leads": "outbound",
}

#: The job's name as the owner sees it, used in the version note.
JOB_LABEL: Final[Mapping[StarterJob, str]] = {
    "answer_calls": "Answer my calls",
    "call_leads": "Call my leads",
}

#: The business type an account with no template, or an unknown one, is treated as. The
#: same fallback `admin.service.starting_fields` uses, never the clinic.
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

    The same answer as `admin.service.starting_fields`, which this module cannot import
    (admin.service imports `agents.lifecycle`, which imports this). The starter test pins
    the two to the same object for every vertical, so they cannot drift.
    """
    return VERTICAL_TEMPLATES.get(vertical, CUSTOM_EXTRACTION_FIELDS)


@dataclass(frozen=True, slots=True)
class StarterStep:
    """One conversation stage: a short title, the instruction, and when it is done."""

    title: str
    instruction: str
    exit_when: str = ""


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

    def opening_for(self, business: str, language: str = "en-IN") -> str:
        """The greeting in the agent's language where `spoken_style.json` has one (a Telugu
        agent greets in Telugu), else the English template."""
        direction = JOB_DIRECTION[self.job]
        template = opening_in(language, direction) or self.opening_line
        return template.replace("{business}", business)

    def call_script(self, *, business: str, language: str = "te-IN") -> CallScript:
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
            stages=self.sections(),
            objections=[Objection(objection=o, response=r) for o, r in self.objections],
            ending=self.ending,
            example_exchange=[ExampleLine(speaker=t.speaker, text=t.text) for t in example],
            example_needs_review=bool(example),
        )

    def sections(self) -> list[ConversationStage]:
        """The steps as script sections, ids `s1`..`sN` in call order. A step's "done
        when" becomes the branch that moves on: to the next section, or the end."""
        out: list[ConversationStage] = []
        for i, step in enumerate(self.steps, 1):
            target = f"s{i + 1}" if i < len(self.steps) else END_OF_CALL
            branches = [StageBranch(when=step.exit_when, target=target)] if step.exit_when else []
            out.append(
                ConversationStage(
                    id=f"s{i}", name=step.title, instruction=step.instruction, branches=branches
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


_CONFIRM_BACK: Final = (
    "Read back their name, the number to reach them on and the next step you agreed, and "
    "correct anything they change."
)

_ENDING: Final = (
    "Once the next step is agreed or they have what they need, thank them by name if you "
    "have it, say goodbye and end the call."
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
        steps=(
            StarterStep(
                title="Find out what they need",
                instruction="Let them explain why they are calling before you offer anything.",
                exit_when="You know what they want.",
            ),
            StarterStep(
                title="Answer from the business's facts",
                instruction=(
                    f"If they ask about {trade.topics}, search your knowledge and answer in "
                    "one or two sentences."
                ),
                exit_when="Their question is answered, or you have said you do not have it.",
            ),
            StarterStep(
                title="Take their details",
                instruction=f"Ask for their name and, as the conversation allows, {trade.capture}.",
                exit_when="You have their name and what they need.",
            ),
            StarterStep(
                title=f"Offer {trade.booking}",
                instruction=(
                    f"If they would like {trade.booking}, agree a day and time that suits "
                    "them. If you cannot confirm it during the call, tell them the team will "
                    "confirm it."
                ),
                exit_when="A day and time is agreed, or they do not want one.",
            ),
            StarterStep(title="Stay within what you know", instruction=trade.caution),
            StarterStep(
                title="Confirm and close",
                instruction=_CONFIRM_BACK,
                exit_when="They have confirmed the details.",
            ),
        ),
        objections=(
            (
                "I just want the price, I don't want to give my details.",
                "Give the price if your knowledge has it. Asking for their name is optional; "
                "do not insist.",
            ),
            (
                "I'll think about it.",
                "That is fine. Thank them and tell them they can call any time.",
            ),
        ),
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
        steps=(
            StarterStep(
                title="Check it is a good time",
                instruction=(
                    "If it is not a good time, ask when would suit them better, thank them "
                    "and end the call."
                ),
                exit_when="They say they can talk now.",
            ),
            StarterStep(
                title="Check you have the right person",
                instruction=(
                    "Make sure you are speaking with the person you meant to call. Their "
                    "name, if you have it, is {{lead_name}}. If it is the wrong person, "
                    "apologise and end the call."
                ),
                exit_when="You know you have the right person.",
            ),
            StarterStep(
                title="Find out what they need",
                instruction=f"Ask what they are looking for: {trade.capture}.",
                exit_when="You know what they want, or that they are not interested.",
            ),
            StarterStep(
                title=f"Offer {trade.booking}",
                instruction=(
                    f"If they are interested, offer {trade.booking} and agree a day and time "
                    "that suits them. If they are not interested, thank them and end the "
                    "call. Do not push or repeat the offer."
                ),
                exit_when="A day and time is agreed, or they said no.",
            ),
            StarterStep(title="Stay within what you know", instruction=trade.caution),
            StarterStep(
                title="Confirm and close",
                instruction=_CONFIRM_BACK,
                exit_when="They have confirmed the details.",
            ),
        ),
        objections=(
            (
                "Where did you get my number?",
                "Say they showed interest in the business earlier, and the team can tell them "
                "exactly where their details came from.",
            ),
            (
                "I'm not interested.",
                "Thank them politely and end the call. Do not try again.",
            ),
            (
                "Send me the details on WhatsApp.",
                "Say you will pass that on to the team, and ask if there is anything they want "
                "to know now.",
            ),
        ),
        ending=_ENDING,
    )


_BUILDERS: Final = {"answer_calls": _answer_calls, "call_leads": _call_leads}

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
    language: str = "te-IN",
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
    saved = await save_agent_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=starter.call_script(business=business, language=language),
        notes=f"Ready-made starter: {JOB_LABEL[job]}",
        created_by=created_by,
    )
    return saved.version


__all__ = [
    "CATALOGUE",
    "JOB_DIRECTION",
    "JOB_LABEL",
    "NEUTRAL_VERTICAL",
    "STARTER_JOBS",
    "TRADES",
    "Starter",
    "StarterJob",
    "StarterStep",
    "Trade",
    "apply_starter",
    "captured_fields",
    "direction_for",
    "starter_for",
    "vertical_of",
]

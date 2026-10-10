"""Ready-made agents: pick a job and a business type, get a script to review (D-705).

A new agent used to start with no script at all, and the owner faced a blank builder. The
founder's rule (redesign #2, item 5) is that the owner picks a JOB, "Answer my calls" or
"Call my leads", and their account's business type fills in a ready agent: a structured
call script, an opening line and the details the agent captures. The owner reviews and
adjusts it before switching it on.

WHAT A STARTER MAY SAY. A starter is written by us and stored as the owner's own script, so
it must hold for every business of its type:

* No fact that belongs to the business. Hours, prices, addresses, staff and availability
  come from the business's own information; where it is missing the agent says so and
  offers a call-back. The agent's FAQ fence (`compile_call_script`) would otherwise turn a
  starter's guess into the one answer the agent may give.
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

from calevate_shared.call_script import CallScript, FaqEntry, ScriptStep
from calevate_shared.extraction import ExtractionField
from scripts.seed import CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import validate_fields, write_schema
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
            "site visit and a call-back from the sales team instead."
        ),
    ),
    "insurance": Trade(
        receptionist_name="Policy desk",
        caller_name="Policy follow-up",
        topics="the policies, premiums, renewals or claims",
        booking="a call-back from an advisor",
        capture=(
            "the kind of policy they want, the cover amount they have in mind, when their "
            "renewal is due, and who insures them today"
        ),
        caution=(
            "Never confirm a premium, a cover amount or a claim outcome on the phone; take "
            "the details and arrange a call-back from an advisor."
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
            "Never promise a seat, a scholarship or a result; offer a counselling session "
            "and a call-back from the admissions team instead."
        ),
    ),
    NEUTRAL_VERTICAL: Trade(
        receptionist_name="Receptionist",
        caller_name="Lead follow-up",
        topics="what you offer, prices, timings or location",
        booking="a booking",
        capture="what they need and the day or time that suits them",
        caution=(
            "Never promise a price, a delivery date or availability without checking; offer "
            "a call-back from the team instead."
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
    """One step: a short title for the preview and the instruction the agent follows."""

    title: str
    instruction: str


@dataclass(frozen=True, slots=True)
class Starter:
    """One vertical and job starter, before the business's name is filled in."""

    job: StarterJob
    vertical: str
    name_suggestion: str
    #: `{business}` is replaced by the account's own name when the script is written.
    opening_line: str
    steps: tuple[StarterStep, ...]
    faqs: tuple[tuple[str, str], ...]
    end_call_rules: tuple[str, ...]

    def opening_for(self, business: str) -> str:
        return self.opening_line.replace("{business}", business)

    def call_script(self, *, business: str) -> CallScript:
        """The structured script the agent is created with. Validated by `CallScript`."""
        return CallScript(
            opening_line=self.opening_for(business),
            steps=[ScriptStep(instruction=step.instruction) for step in self.steps],
            faqs=[FaqEntry(question=q, answer=a) for q, a in self.faqs],
            end_call_extra_rules=list(self.end_call_rules),
        )

    def authored_text(self) -> str:
        """Every sentence this starter writes, for the wording tests."""
        parts = [self.name_suggestion, self.opening_line]
        parts += [f"{step.title} {step.instruction}" for step in self.steps]
        parts += [f"{q} {a}" for q, a in self.faqs]
        parts += list(self.end_call_rules)
        return "\n".join(parts)


#: The business-information answer both jobs share. The FAQ fence tells the agent to
#: answer ONLY from the FAQ, so this entry is what lets it use the business's own
#: information for every question about the business rather than refusing them all.
_BUSINESS_FACTS_ANSWER: Final = (
    "Answer from the business information you have been given. If the answer is not "
    "there, do not guess: say you are not sure and offer a call-back from the team."
)

_ONE_THING_AT_A_TIME: Final = (
    "Keep each reply short and ask one question at a time. Let them finish speaking."
)

_CONFIRM_BACK: Final = (
    "Before you finish, read back their name, the number to reach them on and the next "
    "step you agreed, and correct anything they change."
)

_NO_HELP_RULE: Final = (
    "If you could not help with something, offer a call-back from the team before you end the call."
)


def _answer_calls(vertical: str, trade: Trade) -> Starter:
    return Starter(
        job="answer_calls",
        vertical=vertical,
        name_suggestion=trade.receptionist_name,
        opening_line="Hello, thank you for calling {business}. How can I help you today?",
        steps=(
            StarterStep(
                title="Find out what they need",
                instruction=(
                    f"Listen to why they are calling before offering anything. "
                    f"{_ONE_THING_AT_A_TIME}"
                ),
            ),
            StarterStep(
                title="Answer from your business information",
                instruction=(
                    f"If they ask about {trade.topics}, answer from the business "
                    "information you have been given. If it is not there, say you are not "
                    "sure and offer a call-back from the team. Never guess."
                ),
            ),
            StarterStep(
                title="Take their details",
                instruction=(
                    f"Ask for their name and, as the conversation allows, {trade.capture}."
                ),
            ),
            StarterStep(
                title=f"Offer {trade.booking}",
                instruction=(
                    f"If they would like {trade.booking}, agree a day and time that suits "
                    "them. If you cannot confirm it yourself during the call, tell them the "
                    "team will call back to confirm."
                ),
            ),
            StarterStep(title="Stay within what you know", instruction=trade.caution),
            StarterStep(title="Confirm and close", instruction=_CONFIRM_BACK),
        ),
        faqs=(
            (
                f"Any question about the business, such as {trade.topics}.",
                _BUSINESS_FACTS_ANSWER,
            ),
            (
                "Can I speak to someone?",
                "Offer to take their name and number so someone from the team calls them "
                "back. If you can transfer the call, say who you are connecting them to "
                "before you do.",
            ),
        ),
        end_call_rules=(_NO_HELP_RULE,),
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
        steps=(
            StarterStep(
                title="Check it is a good time",
                instruction=(
                    "If it is not a good time, ask when would suit them better, thank them "
                    "and end the call."
                ),
            ),
            StarterStep(
                title="Check you have the right person",
                instruction=(
                    "Make sure you are speaking with the person you meant to call. Their "
                    "name, if you have it, is {{lead_name}}. If it is the wrong person, "
                    "apologise and end the call."
                ),
            ),
            StarterStep(
                title="Find out what they need",
                instruction=(
                    f"Ask what they are looking for: {trade.capture}. {_ONE_THING_AT_A_TIME}"
                ),
            ),
            StarterStep(
                title=f"Offer {trade.booking}",
                instruction=(
                    f"If they are interested, offer {trade.booking} and agree a day and time "
                    "that suits them. If they are not interested, thank them and end the "
                    "call. Do not push or repeat the offer."
                ),
            ),
            StarterStep(
                title="Respect a request to stop",
                instruction=(
                    "If they ask not to be called again, apologise, record it with the "
                    "do-not-call tool, confirm they will not be called again, and end the "
                    "call politely."
                ),
            ),
            StarterStep(title="Stay within what you know", instruction=trade.caution),
            StarterStep(title="Confirm and close", instruction=_CONFIRM_BACK),
        ),
        faqs=(
            (
                "Why are you calling me? Where did you get my number?",
                "Say you are calling from the business to follow up, and that the team can "
                "tell them where their details came from. If they would rather not be "
                "called, record it with the do-not-call tool and end the call politely.",
            ),
            (
                f"Any question about the business, such as {trade.topics}.",
                _BUSINESS_FACTS_ANSWER,
            ),
        ),
        end_call_rules=(_NO_HELP_RULE,),
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
) -> int:
    """Write the starter as the agent's first script version and set its captured details.

    The script goes through `save_agent_script`, the builder's own save, so the stored body
    is the compile of the stored structure and the version is staged or applied by the same
    rule as any edit (a new agent is a draft, so it is applied to the draft and reaches no
    caller until the agent is published). The extraction schema goes through
    `write_schema`, the extraction screen's own write; a new agent has none yet. Returns
    the script version.
    """
    vertical = vertical_of(vertical_template)
    starter = CATALOGUE[(vertical, job)]
    saved = await save_agent_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=starter.call_script(business=business),
        notes=f"Ready-made starter: {JOB_LABEL[job]}",
        created_by=created_by,
    )
    fields = [ExtractionField.model_validate(field) for field in captured_fields(vertical)]
    validate_fields(fields)
    await write_schema(session, agent_id=agent_id, fields=fields)
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

"""Ready-made agents: pick a job and a business type, get a script to review (D-705).

A new agent used to start with no script at all, and the owner faced a blank builder. The
founder's rule (redesign #2, item 5) is that the owner picks a JOB, "Answer my calls",
"Call new leads instantly" (D-855) or "Run calling campaigns" (D-863), and their account's
business type fills in a ready agent: a structured call script, an opening line and the
details the agent captures. The owner reviews and adjusts it before switching it on.

SEVERAL JOBS, ONE AGENT (D-863). The first run lets the owner pick more than one job, and one
agent does them all: one voice, one script with a block of sections per job
(`starter_script`). Its direction is inbound, outbound, or `both` when it answers and dials.
The two calling jobs share their step shape, so they share one block whose needs step knows
the person may have enquired minutes ago; that keeps every combination inside the script's
section limit.

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
* Nothing the business is not known to do. Each starter is fitted to the business's judged
  capability profile (`agents/business_fit`): a booking is offered, a price quoted, a place
  to visit or a sale assumed only once the business is judged to do it, so an unjudged
  business gets "agree the next step" where the offer was, no price objection, and its "may
  do" switches off for the owner to turn on (audit of 5 Nov 2026, G1-1). Its own objections,
  goal, role and starter words (agent names, topics, what to capture, the caution) replace
  the trade table's wherever its business copy has them (G1-3): the table is the seed.
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

import contextlib
import functools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, Literal, get_args
from uuid import UUID

from calevate_shared.call_script import (
    END_OF_CALL,
    MAX_SCRIPT_OBJECTIONS,
    SCRIPT_SCHEMA_VERSION,
    STAGE_TITLE_MAX,
    CallScript,
    ConversationStage,
    Objection,
    ScriptPolicies,
    SpeakingStyle,
    StageBranch,
)
from calevate_shared.engine import DEFAULT_PRIMARY_LANGUAGE
from calevate_shared.languages import get_language
from calevate_shared.spoken_style import opening_in
from scripts.seed import CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.business_fit import UNKNOWN, BusinessFit, business_fit
from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.lead_fields import starting_business_fields
from apps.api.agents.models import AgentDirection
from apps.api.agents.script_builder import rewrite_script, save_agent_script
from apps.api.agents.starter_plans import Plan, stored_plans, with_focus
from apps.api.agents.trade_playbooks import NEXT_STEP_TITLE, playbook_for
from apps.api.core.errors import ProblemError
from apps.api.tenancy.business_copy import read_state as read_business_copy

#: `call_new_leads` rings someone minutes after they enquire (speed to lead, the ingest
#: webhook's job); `call_leads` works through a list of people who showed interest earlier.
#: Both dial out; they differ in what the agent knows about the person it rings (D-855).
StarterJob = Literal["answer_calls", "call_new_leads", "call_leads"]
STARTER_JOBS: Final[tuple[StarterJob, ...]] = get_args(StarterJob)

#: A starter preview greets in English; a starter agent starts in the platform's one default
#: call language (`engine.DEFAULT_PRIMARY_LANGUAGE`, G7-1) when its caller passes none: the
#: callers that know the business pass its own first language.
PREVIEW_LANGUAGE: Final = get_language("english_india").bcp47
STARTER_LANGUAGE: Final = DEFAULT_PRIMARY_LANGUAGE

#: Each job's calling direction. An agent given an answering job and a calling one is `both`
#: (`direction_of_jobs`): the owner ticked both, which is the deliberate choice.
JOB_DIRECTION: Final[Mapping[StarterJob, AgentDirection]] = {
    "answer_calls": "inbound",
    "call_new_leads": "outbound",
    "call_leads": "outbound",
}

#: One job, or the several one agent does (D-863).
JobChoice = StarterJob | Sequence[StarterJob]


def starter_jobs(choice: JobChoice) -> tuple[StarterJob, ...]:
    """The jobs chosen, each once, in `STARTER_JOBS` order: answering first, because a
    caller who rang is the one who hears an agent that does both greet first."""
    picked = {choice} if isinstance(choice, str) else set(choice)
    jobs = tuple(job for job in STARTER_JOBS if job in picked)
    if not jobs:
        raise ValueError("at least one job")
    return jobs


def direction_of_jobs(choice: JobChoice) -> AgentDirection:
    """inbound or outbound when every job agrees, `both` when they do not."""
    directions = {JOB_DIRECTION[job] for job in starter_jobs(choice)}
    return directions.pop() if len(directions) == 1 else "both"


#: The job's name as the owner sees it, used in the version note. `call_leads` is bulk
#: calling, which lives on the Campaigns page, hence its campaign name (D-863).
JOB_LABEL: Final[Mapping[StarterJob, str]] = {
    "answer_calls": "Answer my calls",
    "call_new_leads": "Call new leads instantly",
    "call_leads": "Run calling campaigns",
}


def jobs_label(choice: JobChoice) -> str:
    return " + ".join(JOB_LABEL[job] for job in starter_jobs(choice))


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


def _either(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} or {parts[-1]}"


def trade_for(vertical: str, fit: BusinessFit = UNKNOWN) -> Trade:
    """The trade's words for this business. A named trade keeps its own row; the neutral row
    names only what the business is not judged against, so an unjudged business gets the
    row exactly as written and a free app's helpline hears nothing of prices, places or
    delivery dates."""
    row = _with_own_words(TRADES[vertical], fit)
    if vertical != NEUTRAL_VERTICAL or fit.words is not None:
        return row
    prices = fit.assumes_prices
    visits = fit.assumes_premises
    topics = ["what you offer"]
    if prices:
        topics.append("prices")
    if visits:
        topics += ["timings", "location"]
    promises = [
        word
        for word, applies in (
            ("a price", prices),
            ("a delivery date", fit.assumes_orders),
            ("availability", fit.assumes_booking),
        )
        if applies
    ]
    caution = (
        f"Never promise {_either(promises)} without checking; say the team will confirm."
        if promises
        else "Never promise anything your facts do not say; say the team will confirm."
    )
    return replace(
        row,
        receptionist_name=row.receptionist_name if visits else "Help desk",
        caller_name=row.caller_name if fit.assumes_sale else "Follow-up calls",
        topics=_either(topics),
        booking=fit.offer_noun or row.booking,
        capture=row.capture if fit.assumes_booking else "what they need",
        caution=caution,
    )


def _with_own_words(row: Trade, fit: BusinessFit) -> Trade:
    """The trade row with the business's own starter words (`GeneratedCopy.starter_words`)
    wherever its copy wrote them; the row alone before then."""
    words = fit.words
    if words is None:
        return row
    return replace(
        row,
        receptionist_name=words.answer_name,
        caller_name=words.calling_name,
        topics=words.topics,
        capture=words.capture,
        caution=words.caution,
    )


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


@dataclass(frozen=True, slots=True)
class Starter:
    """One vertical and job starter, before the business's name is filled in.

    Written in the script v2 sections (`calevate_shared.call_script`). Instructions are in
    English; the words a caller hears are written for the business (D-962), never kept
    here. What the agent does when it cannot help, the
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
    #: The "may do" switches the script starts with (`ScriptPolicies`), from the business's
    #: judged profile; both on while it is unjudged.
    share_prices: bool = True
    take_bookings: bool = True
    tone: str = "Warm, calm and brief, like a helpful person on the phone."

    def planned(self, plan: Plan | None) -> Starter:
        """This starter with the business's own steps (`agents/starter_plans`): each
        step's title in its words and its focus after the platform's instruction. The
        instruction and "done when" stay ours. A step that replaced the offer keeps its own
        title: the business's was written for the offer."""
        if plan is None or len(plan) != len(self.steps):
            return self
        steps = tuple(
            step
            if step.title == NEXT_STEP_TITLE
            else StarterStep(
                title=mine.title,
                instruction=with_focus(step.instruction, mine.focus),
                exit_when=step.exit_when,
            )
            for step, mine in zip(self.steps, plan, strict=True)
        )
        return replace(self, steps=steps)

    def opening_for(
        self, business: str, language: str = PREVIEW_LANGUAGE, *, introduced: bool = False
    ) -> str:
        """The greeting in the agent's language where `spoken_style.json` has one (a Telugu
        agent greets in Telugu), else the English template. `introduced`: the line said after
        the agent's AI notice has introduced it, with no greeting and no names (D-865)."""
        direction = JOB_DIRECTION[self.job]
        template = opening_in(language, direction, introduced=introduced) or self.opening_line
        return template.replace("{business}", business)

    def call_script(self, *, business: str, language: str = STARTER_LANGUAGE) -> CallScript:
        """The structured script the agent is created with. Validated by `CallScript`. It
        carries no example call: one written for every business of a type is a line any
        business could use (D-962); the script writer writes the business's own."""
        return CallScript(
            schema_version=SCRIPT_SCHEMA_VERSION,
            business_line=self.business_line.replace("{business}", business)[:200],
            identity=self.identity.replace("{business}", business),
            goal=self.goal,
            outbound_purpose=self.outbound_purpose.replace("{business}", business),
            opening_line=self.opening_for(business, language),
            style=SpeakingStyle(tone=self.tone),
            stages=self.sections(),
            objections=[Objection(objection=o, response=r) for o, r in self.objections],
            policies=ScriptPolicies(
                share_prices=self.share_prices, take_bookings=self.take_bookings
            ),
            ending=self.ending,
        )

    def sections(self) -> list[ConversationStage]:
        """The steps as script sections, ids `s1`..`sN` in call order. A step's "done
        when" becomes the branch that moves on: to the next section, or the end. No step has
        an example line: those are written for the business (`with_example_lines`, D-962)."""
        out: list[ConversationStage] = []
        for i, step in enumerate(self.steps, 1):
            target = f"s{i + 1}" if i < len(self.steps) else END_OF_CALL
            branches = [StageBranch(when=step.exit_when, target=target)] if step.exit_when else []
            out.append(
                ConversationStage(
                    id=f"s{i}",
                    name=step.title,
                    instruction=step.instruction,
                    branches=branches,
                )
            )
        return out

    def authored_text(self) -> str:
        """Every English sentence this starter writes, for the wording tests."""
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

#: Why a calling starter rings, with no claim about the person (D-961): a starter holds for
#: every business of its type and knows nothing of who is on the list, so what the person did
#: (enquired, asked, showed interest) is said only from the call's own data, THIS CALL's
#: `REASON_LINE` and `DETAILS_LINE` (D-905), which START OF THE CALL tells the agent.
_CALLING_PURPOSE: Final = (
    "the reason THIS CALL gives, if it gives one; else that {business} is calling to see "
    "whether it can help."
)

#: The outbound starter's one per-call value, in its LAST section. The engine caches the
#: prompt up to the first value it fills per call (VENDOR-STATED, ThinnestAI email of 18 Oct
#: 2026), so a `{{lead_name}}` in the second step left every stage, objection and
#: policy after it outside the cache (D-816).
_CALL_LEADS_ENDING: Final = (
    f"{_ENDING}\nThe person you are calling, if you have their name: {{{{lead_name}}}}"
)


def _planned_steps(job: StarterJob, trade: Trade, fit: BusinessFit) -> tuple[StarterStep, ...]:
    """The starter's steps from its job's plan (D-856, `trade_playbooks`)."""
    return tuple(
        StarterStep(step.title, step.instruction, step.exit_when)
        for step in playbook_for(job, trade, fit).steps
    )


#: A calling starter's goal ends here whatever the business wrote: outbound takes no for an
#: answer (the starters' rule above).
_TAKE_NO: Final = "Take no for an answer."


def _calling_name(trade: Trade, fit: BusinessFit) -> str:
    """The calling agent's suggested name, from what the business calls its callers when the
    copy says, so a free app's list is "User follow-up" rather than a lead or an order."""
    if fit.caller_noun:
        return f"{fit.caller_noun[:1].upper()}{fit.caller_noun[1:]} follow-up"
    return trade.caller_name


def _fitted(starter: Starter, fit: BusinessFit) -> Starter:
    """The switches and tone the business's profile sets: on only for what it is judged to
    do, so an unjudged business starts with both off for its owner to turn on."""
    return replace(
        starter,
        share_prices=fit.assumes_prices,
        take_bookings=fit.assumes_booking,
        tone=(
            "Warm, calm and brief, like a helpful person at the front desk."
            if fit.assumes_premises
            else starter.tone
        ),
    )


def _answer_calls(vertical: str, trade: Trade, fit: BusinessFit) -> Starter:
    if fit.call_goal:
        goal = fit.call_goal
    elif not fit.assumes_booking:
        goal = (
            "Understand what each caller needs, answer it from the business's facts, and "
            "where it fits, agree the next step or take their details for the team."
        )
    else:
        goal = (
            f"Understand what each caller needs, answer it from the business's facts, and "
            f"where it fits, arrange {trade.booking} or take their details for the team."
        )
    return Starter(
        job="answer_calls",
        vertical=vertical,
        name_suggestion=trade.receptionist_name,
        opening_line="Hello, thank you for calling {business}. How can I help you today?",
        business_line="{business}",
        identity=fit.agent_role
        or (
            "You answer the phone for {business}. You are friendly, quick and practical, and "
            f"you help callers with {trade.topics}."
        ),
        goal=goal,
        outbound_purpose="",
        steps=_planned_steps("answer_calls", trade, fit),
        objections=playbook_for("answer_calls", trade, fit).objections,
        ending=_ENDING,
    )


def _calling_goal(trade: Trade, fit: BusinessFit, lead: str) -> str:
    if fit.call_goal:
        return f"{fit.call_goal} {_TAKE_NO}"
    offer = f"arrange {trade.booking}" if fit.assumes_booking else "agree the next step"
    return f"{lead} {offer}. {_TAKE_NO}"


def _call_leads(vertical: str, trade: Trade, fit: BusinessFit) -> Starter:
    return Starter(
        job="call_leads",
        vertical=vertical,
        name_suggestion=_calling_name(trade, fit),
        opening_line=(
            "Hello, I am calling from {business} to follow up with you. Is this a good time "
            "for a quick chat?"
        ),
        business_line="{business}",
        identity="You place calls for {business}. You are polite, brief and never pushy.",
        goal=_calling_goal(trade, fit, "Find out whether they are interested and, if they are,"),
        outbound_purpose=_CALLING_PURPOSE,
        steps=_planned_steps("call_leads", trade, fit),
        objections=playbook_for("call_leads", trade, fit).objections,
        ending=_CALL_LEADS_ENDING,
    )


def _call_new_leads(vertical: str, trade: Trade, fit: BusinessFit) -> Starter:
    """Rings a person minutes after they enquired. The plan keeps the list's step shape, so
    the business copy's example lines fit both (`LINES_OF_JOB`)."""
    return Starter(
        job="call_new_leads",
        vertical=vertical,
        name_suggestion=_calling_name(trade, fit),
        opening_line=(
            "Hello, I am calling from {business} about the enquiry you just made. Is this a "
            "good time for a quick chat?"
        ),
        business_line="{business}",
        identity=(
            "You call people within minutes of their enquiry to {business}, while it is "
            "still fresh. You are polite, brief and never pushy."
        ),
        goal=_calling_goal(trade, fit, "Help with what they need and, if they are interested,"),
        outbound_purpose=_CALLING_PURPOSE,
        steps=_planned_steps("call_new_leads", trade, fit),
        objections=playbook_for("call_new_leads", trade, fit).objections,
        ending=_CALL_LEADS_ENDING,
    )


_BUILDERS: Final = {
    "answer_calls": _answer_calls,
    "call_new_leads": _call_new_leads,
    "call_leads": _call_leads,
}


@functools.lru_cache(maxsize=512)
def build_starter(vertical: str, job: StarterJob, fit: BusinessFit = UNKNOWN) -> Starter:
    """The starter for a business type and job, fitted to what the business does. Cached:
    a fit is a small frozen value, and an account's starters are built on every preview."""
    trade = trade_for(vertical, fit)
    return _fitted(_BUILDERS[job](vertical, trade, fit), fit)


#: Every starter of an unjudged business, keyed by (vertical, job). Built at import, so a
#: malformed starter is an import-time failure.
CATALOGUE: Final[Mapping[tuple[str, StarterJob], Starter]] = {
    (vertical, job): build_starter(vertical, job) for vertical in TRADES for job in STARTER_JOBS
}

#: Each job's step count: the shape the business's own step titles and example lines are
#: written for (`starter_plans`, `business_copy.StarterLines`). Fitting a starter to a
#: business replaces a step, never drops one, so this holds for every business.
JOB_STEP_COUNTS: Final[Mapping[str, int]] = {
    job: len(CATALOGUE[(next(iter(TRADES)), job)].steps) for job in STARTER_JOBS
}
if any(len(s.steps) != JOB_STEP_COUNTS[s.job] for s in CATALOGUE.values()):
    raise RuntimeError("a job's steps differ in count between business types")


def starter_for(
    vertical_template: str | None, job: StarterJob, fit: BusinessFit = UNKNOWN
) -> Starter:
    return build_starter(vertical_of(vertical_template), job, fit)


def direction_for(job: JobChoice, requested: AgentDirection | None) -> AgentDirection:
    """The direction the jobs set, refusing an explicit direction that contradicts it."""
    direction = direction_of_jobs(job)
    if requested is not None and requested != direction:
        raise ProblemError(
            kind="validation",
            code="starter_direction_mismatch",
            title="The job and the calling direction disagree",
            detail=(
                f'"{jobs_label(job)}" makes an agent whose calls are {direction}. '
                "Leave the direction out, or choose the other job."
            ),
            fields=[{"name": "direction", "reason": f"must be {direction} for this job"}],
        )
    return direction


#: A block's section-id prefix and the heading its sections' names carry, so the agent and the
#: owner both see which job a section belongs to.
_BLOCKS: Final[Mapping[str, tuple[str, str]]] = {
    "inbound": ("in", "Incoming call"),
    "outbound": ("out", "Outgoing call"),
}
#: What each block's goal is prefixed with in a script that does both.
_GOAL_LEAD: Final[Mapping[str, str]] = {
    "inbound": "When someone rings the business:",
    "outbound": "When you ring someone:",
}
#: The calling block of an agent that does both calling jobs: a person on a campaign list
#: and a person who enquired minutes ago get the same steps, and only the needs step differs
#: (`trade_playbooks._call_new_leads`), so that step learns the difference rather than the
#: script carrying two near-identical blocks past `MAX_SCRIPT_STAGES`.
_JUST_ENQUIRED: Final = "If THIS CALL names an enquiry they just made, thank them for it first. "
_NEEDS_STEP: Final = 2


def _block(script: CallScript, direction: str) -> list[ConversationStage]:
    """One job's sections, renamed into its block and closed at its last section, so a call
    in one block never runs on into the other."""
    prefix, heading = _BLOCKS[direction]
    ids = {stage.id: f"{prefix}{i}" for i, stage in enumerate(script.stages, 1)}
    out: list[ConversationStage] = []
    for i, stage in enumerate(script.stages):
        data = stage.model_dump()
        data["id"] = ids[stage.id]
        data["name"] = f"{heading}: {stage.name}"[:STAGE_TITLE_MAX]
        data["branches"] = [
            {**branch, "target": ids.get(branch["target"], branch["target"])}
            for branch in data["branches"]
        ]
        last = i == len(script.stages) - 1
        data["otherwise"] = END_OF_CALL if last else ids.get(stage.otherwise, stage.otherwise)
        out.append(ConversationStage.model_validate(data))
    return out


def starter_opening(
    vertical_template: str | None,
    job: JobChoice,
    *,
    business: str,
    language: str = STARTER_LANGUAGE,
    introduced: bool = False,
    fit: BusinessFit = UNKNOWN,
) -> str:
    """The ready-made script's greeting, from the job `starter_script` takes it from, or with
    `introduced` the form said after the agent's introduction (D-865)."""
    jobs = starter_jobs(job)
    calling_only = "answer_calls" not in jobs and len(jobs) > 1
    source = jobs[-1] if calling_only else jobs[0]
    starter = build_starter(vertical_of(vertical_template), source, fit)
    return starter.opening_for(business, language, introduced=introduced)


def starter_script(
    vertical_template: str | None,
    job: JobChoice,
    *,
    business: str,
    language: str = STARTER_LANGUAGE,
    plans: Mapping[str, Plan] | None = None,
    fit: BusinessFit = UNKNOWN,
) -> CallScript:
    """The ready-made script for one job, or for the several one agent does (D-863).

    Several: the answering block first, then one calling block. The greeting is the first
    job's (a caller who rang hears it), the per-call lead name stays in the LAST section
    (D-816's cache rule) by taking the calling ending whenever the agent dials, and the
    objections are both jobs', each once."""
    jobs = starter_jobs(job)
    vertical = vertical_of(vertical_template)
    written = plans or {}

    def starter(each: StarterJob) -> Starter:
        return build_starter(vertical, each, fit).planned(written.get(each))

    if len(jobs) == 1:
        return starter(jobs[0]).call_script(business=business, language=language)
    answering = "answer_calls" in jobs
    calling = tuple(j for j in jobs if JOB_DIRECTION[j] == "outbound")
    first = starter(jobs[0]).call_script(business=business, language=language)
    parts: list[tuple[str, CallScript]] = []
    if answering:
        parts.append(("inbound", first))
    if calling:
        base = starter(calling[-1]).call_script(business=business, language=language)
        if len(calling) > 1:
            # The list's own needs step (index 2 of the shared shape), told about new enquiries.
            stages = list(base.stages)
            needs = stages[_NEEDS_STEP]
            # Past the step's 600 characters, the list's step stays as it is.
            with contextlib.suppress(ValueError):
                stages[_NEEDS_STEP] = ConversationStage.model_validate(
                    {**needs.model_dump(), "instruction": _JUST_ENQUIRED + needs.instruction}
                )
            base = base.model_copy(update={"stages": stages})
        parts.append(("outbound", base))
    if len(parts) == 1:
        # Both calling jobs and no answering one: one block, needing no headings.
        return parts[0][1]
    objections: list[Objection] = []
    for _direction, part in parts:
        for objection in part.objections:
            if all(o.objection != objection.objection for o in objections):
                objections.append(objection)
    return CallScript.model_validate(
        {
            **first.model_dump(),
            "identity": " ".join(part.identity for _d, part in parts),
            "goal": " ".join(f"{_GOAL_LEAD[d]} {part.goal}" for d, part in parts),
            "outbound_purpose": parts[-1][1].outbound_purpose,
            "stages": [s.model_dump() for d, part in parts for s in _block(part, d)],
            "objections": [o.model_dump() for o in objections[:MAX_SCRIPT_OBJECTIONS]],
            "ending": parts[-1][1].ending,
        }
    )


async def apply_starter(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    job: JobChoice,
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

    The script carries no opening line (D-965): the starter's is the same for every business
    of a type (D-962, D-963). The caller has one written for the business: Meet your agent
    writes it in its run, `POST /v1/agents` and Pip queue a `written` suggestion
    (`script_proposals.request_written_opening`).
    """
    jobs = starter_jobs(job)
    # The ACCOUNT's business fields, not the starter catalogue's vertical: a type with no
    # starter row of its own (a shop) still gets its own standard set, and a custom business
    # gets its one AI draft once it exists (`agents/lead_fields`).
    fields = await starting_business_fields(
        session, tenant_id=tenant_id, vertical=vertical_template
    )
    validate_fields(fields)
    await write_schema(session, agent_id=agent_id, fields=fields)
    plans = await stored_plans(session, tenant_id=tenant_id, shapes=JOB_STEP_COUNTS)
    fit = await business_fit(session, tenant_id)
    script = await _with_business_lines(
        session,
        starter_script(
            vertical_template, jobs, business=business, language=language, plans=plans, fit=fit
        ),
        jobs,
        language,
    )
    script = script.model_copy(update={"opening_line": "", "outbound_opening_line": ""})
    saved = await save_agent_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=script,
        notes=f"Ready-made starter: {jobs_label(jobs)}",
        created_by=created_by,
    )
    return saved.version


def _line_sets(jobs: Sequence[StarterJob]) -> tuple[LineSet, ...]:
    """The business copy's line sets in the order `starter_script` lays out its blocks: the
    answering block first, then one calling block whichever calling jobs it does."""
    sets: list[LineSet] = []
    for job in jobs:
        if LINES_OF_JOB[job] not in sets:
            sets.append(LINES_OF_JOB[job])
    return tuple(sets)


async def _with_business_lines(
    session: AsyncSession, script: CallScript, jobs: Sequence[StarterJob], language: str
) -> CallScript:
    """`script` with the account's AI-written example line on each step (D-827, D-962): the
    lines of each block's step shape, block after block. With no business copy in this
    language the steps keep no line at all: a ready-made script never carries a line we wrote
    for every business, and the agent words the step from its instruction."""
    stored = await read_business_copy(session)
    if stored is None or stored.copy is None or stored.language != language:
        return script
    sets = stored.copy.starter_lines
    lines = [line for line_set in _line_sets(jobs) for line in getattr(sets, line_set)]
    return with_example_lines(script, lines)


def with_example_lines(script: CallScript, lines: Sequence[str]) -> CallScript:
    """The starter with the business's AI-written example line on each step (D-827).

    Only a NEW agent's script gets them, and only into an "example line" that is empty:
    nothing a person wrote is there to replace. A line that would push its step past the
    engine's step limit is left out, and lines written for a different number of steps are
    not used at all. The step that replaced the offer gets none: its line was written for
    the offer."""
    if len(lines) != len(script.stages):
        return script
    stages: list[ConversationStage] = []
    for stage, line in zip(script.stages, lines, strict=True):
        replaced = stage.name.endswith(NEXT_STEP_TITLE)
        if stage.sounds_like.strip() or not line.strip() or replaced:
            stages.append(stage)
            continue
        try:
            stages.append(
                ConversationStage.model_validate({**stage.model_dump(), "sounds_like": line})
            )
        except ValueError:
            stages.append(stage)
    return script.model_copy(update={"stages": stages})


#: The single jobs an agent's direction may have come from. "both" has none: a several-job
#: script (D-863) matches no one catalogue starter, so `replace_unedited_starter` leaves it
#: alone, the safe side. Outbound has two, told apart by content (`starter_vertical_of`).
JOBS_OF_DIRECTION: Final[Mapping[str, tuple[StarterJob, ...]]] = {
    direction: tuple(job for job in STARTER_JOBS if JOB_DIRECTION[job] == direction)
    for direction in set(JOB_DIRECTION.values())
}


#: What a ready-made script's words are, as opposed to its structure: written for the business
#: (D-962), so two scripts of one starter differ here and are still the same starter.
_SPOKEN_FIELDS: Final = (
    "opening_line",
    "outbound_opening_line",
    "example_exchange",
    "example_needs_review",
)


def _canonical(script: CallScript) -> dict[str, Any]:
    # Quick facts move to the business's pinned facts at every save, so a stored script
    # never carries them; compared without them.
    data = script.model_copy(update={"faqs": []}).model_dump(mode="json")
    for field in _SPOKEN_FIELDS:
        data.pop(field, None)
    for stage in data["stages"]:
        stage["sounds_like"] = ""
    return data


def starter_vertical_of(
    stored: Mapping[str, Any],
    *,
    job: StarterJob,
    business: str,
    language: str,
    plan: Plan | None = None,
    fit: BusinessFit = UNKNOWN,
) -> str | None:
    """The business type whose starter wrote `stored`, if nobody has changed its structure.

    Recognised by structure rather than by a version note, because the structure is what the
    owner edits and a recompile (`recompile_collect`) writes new versions without touching
    it. The spoken words (openings, example lines, example call) are written for the business
    and are not compared (D-962). A starter written under an earlier business name or an
    earlier catalogue wording does not match, and is treated as edited. With `plan`, the
    starter as written with the business's own steps matches too; with `fit`, the starter
    fitted to the business as it is judged now.
    """
    try:
        script = _canonical(CallScript.model_validate(stored))
    except ValueError:
        return None
    for vertical in TRADES:
        starter = build_starter(vertical, job, fit)
        for each in (starter, starter.planned(plan)):
            candidate = each.call_script(business=business, language=language)
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
    plans = await stored_plans(session, tenant_id=tenant_id, shapes=JOB_STEP_COUNTS)
    fit = await business_fit(session, tenant_id)
    found = next(
        (
            (job, vertical)
            for job in JOBS_OF_DIRECTION.get(str(row[0]), ())
            if (
                vertical := starter_vertical_of(
                    row[2],
                    job=job,
                    business=business,
                    language=language,
                    plan=plans.get(job),
                    fit=fit,
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
    held = CallScript.model_validate(row[2])
    # The new type's structure, with the openings the agent already has (written for this
    # business, not for its old type) and the business's example lines for the new steps.
    script = (
        build_starter(target, job, fit)
        .planned(plans.get(job))
        .call_script(business=business, language=language)
    )
    script = script.model_copy(
        update={
            "opening_line": held.opening_line,
            "outbound_opening_line": held.outbound_opening_line,
        }
    )
    return await rewrite_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=await _with_business_lines(session, script, (job,), language),
        notes=f"Ready-made starter: {JOB_LABEL[job]} (business type changed)",
    )


__all__ = [
    "CATALOGUE",
    "JOBS_OF_DIRECTION",
    "JOB_DIRECTION",
    "JOB_LABEL",
    "JOB_STEP_COUNTS",
    "LINES_OF_JOB",
    "LINE_SETS",
    "NEUTRAL_VERTICAL",
    "STARTER_JOBS",
    "TRADES",
    "JobChoice",
    "LineSet",
    "Starter",
    "StarterJob",
    "StarterStep",
    "Trade",
    "apply_starter",
    "build_starter",
    "captured_fields",
    "direction_for",
    "direction_of_jobs",
    "jobs_label",
    "replace_unedited_starter",
    "starter_for",
    "starter_jobs",
    "starter_opening",
    "starter_script",
    "starter_vertical_of",
    "trade_for",
    "vertical_of",
    "with_example_lines",
]

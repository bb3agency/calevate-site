"""How a good call goes, per trade and job: the step plan the starters and the script writer
share (D-856).

A starter used to carry one generic step list for every trade, and the AI script writer
(`apps/workers/script_assist`) got a brief and five answers with no step shape at all, so each
agent re-invented the call. The founder's real calls of 20-22 Oct 2026 broke in the same
places every time (`docs/evidence/call-quality-vs-outpero-2026-10-23.md`): a pitch where a
question belonged, "do you want to know the price?" instead of the price, a half answer
re-asked or guessed, two questions at once, a close that offered what nothing on the call
could do. So each trade's call is planned ONCE here, and both readers take it from here:

* `agents/starters` builds every starter's steps and objections from it;
* the script writer reads it as guidance (`playbook_guidance`) and adapts it to the owner's
  answers.

A plan is STRUCTURE ONLY, per job and trade: what to ask at each step (one thing a turn), when
the step is done, where it branches, and the objections that trade really meets, all as English
instructions to the model. It holds no spoken words (D-962, founder, 2 Nov 2026): every step
used to carry an example line in Telugu, Hindi and English, the same for every business of a
type, and a calling plan's "you enquired with us earlier" reached a caller with nothing on the
call saying so. What a step sounds like is written per business: by the script writer from the
owner's words, or by the business copy for a ready-made script (`agents/starters`). The old
lines survive only in `agents/retired_lines`, to be found and refused.

A NEW JOB SLOTS IN AS ONE ENTRY. `JOB_SHAPES` maps a job to the function that builds its
steps from a `TradeWords`; a third job ("call my list" beside "call new leads") is a
new key there and in `_JOB_OBJECTIONS`, or an alias of an existing shape, and the coverage
test then demands a plan for every trade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from apps.api.agents.business_fit import UNKNOWN, BusinessFit

if TYPE_CHECKING:
    from apps.api.agents.starter_plans import Plan

#: The business type a plan falls back to: never the clinic (D-722).
NEUTRAL_TRADE: Final = "custom"


@dataclass(frozen=True, slots=True)
class PlayStep:
    """One step of a call: its title, what the agent does, and when it is done."""

    title: str
    #: English, for the model: what to do and the one thing to ask.
    instruction: str
    #: When the step is done (the starter's branch to the next step).
    exit_when: str


#: The title of the step that replaces the offer for a business judged to book and order
#: nothing. Replaced rather than dropped, so the business's own step titles and example
#: lines, written for the job's fixed shape, still line up; readers find the step by this
#: title and keep the platform's words on it.
NEXT_STEP_TITLE: Final = "Agree the next step"


@dataclass(frozen=True, slots=True)
class Playbook:
    trade: str
    job: str
    steps: tuple[PlayStep, ...]
    #: (what the caller says, what the agent does), in plain English.
    objections: tuple[tuple[str, str], ...]


class TradeBasics(Protocol):
    """The trade's words the starters already hold (`agents/starters.Trade`), passed in
    rather than copied so there is one table of them."""

    #: The thing a caller books, with its article ("an appointment").
    @property
    def booking(self) -> str: ...

    #: The details to ask for, in the order a conversation reaches them.
    @property
    def capture(self) -> str: ...

    #: The one thing this trade's agent must never do, as an instruction.
    @property
    def caution(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TradeWords:
    """What one trade puts into every job's plan beyond its `TradeBasics`."""

    #: What a lead of this trade usually wants to know, for the value step (D-945): where to
    #: look in the owner's facts, never a fact itself.
    value_topics: str
    #: The one objection this trade meets beyond the job's own.
    objection: tuple[str, str]


#: The rest of the close (what happens next, anything else, one goodbye) is HOW TO SPEAK's.
_CLOSE_INSTRUCTION: Final = "Read back what they asked for and any time agreed, then close."
#: A call to a lead closes on one read-back the person can check against their own calendar
#: (D-945): a date and time plan raises follow-through where a date alone does not (Milkman et
#: al., PNAS 2011, PMC3127912, in `docs/research/reports/Sales call scripts and generation.md`).
_LEAD_CLOSE_INSTRUCTION: Final = (
    "Read back once: weekday, date, time and place. Then the true next step: noted for the "
    "team to confirm, unless your booking tool booked it. Then close."
)
#: The close of a call that booked nothing: there is no weekday, date or place to read back.
_AGREED_CLOSE_INSTRUCTION: Final = (
    "Read back once what was agreed and what happens next. Then close."
)
#: The value step (D-945): what it says is a fact of the business, so it has no example line
#: even where the business writes the others.
VALUE_STEP_TITLE: Final = "Say one thing that fits"

#: What an objection assumes of the business. "price": its callers ask prices, so it sells
#: and its prices are not withheld; "sale": it sells anything at all. An objection whose
#: assumption the business is judged not to meet is left out (`_fits`).
_PRICE: Final = "price"
_SALE: Final = "sale"

#: (what the caller says, what the agent does, what the objection assumes or "").
_Tagged = tuple[str, str, str]

_ANSWER_OBJECTIONS: Final[tuple[_Tagged, ...]] = (
    (
        "I just want the price, I don't want to give my details.",
        "Give the price if your facts have it. Their name is optional; do not insist.",
        _PRICE,
    ),
    (
        "I'll think about it.",
        "That is fine. Thank them and say they can call any time.",
        "",
    ),
)

#: A calling job's objections (D-945): each answered once (`call_rules` let_go), then the call
#: is let go. A response that depends on what the account can do says so, and the platform's
#: WHAT YOU CAN DO block, after the script, decides on the call.
_LEADS_OBJECTIONS: Final[tuple[_Tagged, ...]] = (
    (
        "I'm busy right now.",
        "Ask when suits them, note it, thank them and end the call.",
        "",
    ),
    (
        "How much does it cost?",
        "Give the price or range only if your facts have it; otherwise say the team will "
        "share the exact price. Never a discount.",
        _PRICE,
    ),
    (
        "Not now, maybe in a few months.",
        "Accept it, ask once whether the team may check in later, note when, and close.",
        "",
    ),
    (
        "Where did you get my number?",
        "Say only what THIS CALL says about it; with nothing there, say the team can tell "
        "them where their number came from. Offer to stop calling if they want.",
        "",
    ),
    (
        "Just send it on WhatsApp.",
        "If you have a WhatsApp action, use it and say it is sent only when it worked; "
        "otherwise say the team will send it to this number. Never say it was sent.",
        "",
    ),
    (
        "I don't want to talk to a machine.",
        "Say you understand. If you can hand them to a person, offer that once; "
        "otherwise say the team will get back to them, note that they prefer a person, and "
        "close.",
        "",
    ),
    (
        "I already bought it or booked somewhere else.",
        "Say that is fine, thank them and end the call with no second pitch.",
        _SALE,
    ),
)


def _offer_or_next_step(step: PlayStep, fit: BusinessFit, instruction: str) -> PlayStep:
    """`step`, the offer, unless the business is judged to book and order nothing: then the
    step that agrees what happens next, in the same place."""
    if fit.books is not False:
        return step
    return PlayStep(
        title=NEXT_STEP_TITLE,
        instruction=instruction,
        exit_when="The next step is agreed, or they need none.",
    )


def _answer_calls(
    basics: TradeBasics, words: TradeWords, fit: BusinessFit = UNKNOWN
) -> tuple[PlayStep, ...]:
    del words  # every job's shape takes the trade's words; answering needs none of them
    return (
        PlayStep(
            title="Find out what they need",
            instruction=("Let them say why they called, then ask the one thing you need to help."),
            exit_when="You know what they want.",
        ),
        PlayStep(
            title="Answer from the business's facts",
            instruction=(f"Search your knowledge and answer what they asked. {basics.caution}"),
            exit_when="Their question is answered, or you have said you do not have it.",
        ),
        PlayStep(
            title="Take their details",
            instruction=(f"Ask, one at a time and only what they have not said: {basics.capture}."),
            exit_when="You have what the team needs.",
        ),
        _offer_or_next_step(
            PlayStep(
                title=f"Offer {basics.booking}",
                instruction=(
                    f"If they want {basics.booking}, offer two times to choose from and agree one."
                ),
                exit_when="A time is agreed, or they do not want one.",
            ),
            fit,
            "If they need more than this call gave them, agree one next step: what they do "
            "next, or that the team follows up. Never promise more than your facts say.",
        ),
        PlayStep(
            title="Confirm and close",
            instruction=(
                _CLOSE_INSTRUCTION if fit.books is not False else _AGREED_CLOSE_INSTRUCTION
            ),
            exit_when="They have nothing else.",
        ),
    )


def _call_leads(
    basics: TradeBasics, words: TradeWords, fit: BusinessFit = UNKNOWN
) -> tuple[PlayStep, ...]:
    return (
        PlayStep(
            title="Check it is a good time",
            instruction=(
                "If they cannot talk now, ask when suits them, thank "
                "them and end the call. Never push."
            ),
            exit_when="They can talk now.",
        ),
        PlayStep(
            title="Say why you called",
            instruction=(
                "Make sure it is the person you meant to call (their name, if you have it, is "
                "under ENDING), then say in one line why you called, as START OF THE CALL "
                "allows. Wrong person? Say sorry and end the call."
            ),
            exit_when="The right person knows why you called.",
        ),
        PlayStep(
            title="Find out what they need",
            instruction=(
                f"Ask, one at a time and only what they have not said: {basics.capture}. "
                f"{basics.caution}"
            ),
            exit_when="You know what they want, or that they are not interested.",
        ),
        PlayStep(
            title=VALUE_STEP_TITLE,
            instruction=(
                "Say ONE fact from your facts that answers what they just told you, in one "
                f"sentence (for this business, often {words.value_topics}). Never a discount, "
                "scheme, offer, urgency or a claim like best; about other customers only when "
                "a fact says so. No fact fits? Skip this step."
            ),
            exit_when="You said one fitting fact, or none fits.",
        ),
        _offer_or_next_step(
            PlayStep(
                title=f"Offer {basics.booking}",
                instruction=(
                    f"If they are interested, offer {basics.booking} at two exact times, each a "
                    "weekday and date from THIS CALL with a time: from your booking tool if you "
                    "have one, else two windows inside the business's hours (never before 9 in "
                    'the morning or after 9 at night), and add "or another time that suits '
                    'you". If not, thank them and end the call. Do not push or repeat the '
                    "offer."
                ),
                exit_when="A time is agreed, or they said no.",
            ),
            fit,
            "If they are interested, agree one next step in a sentence: what they do next, or "
            "that the team follows up. If not, thank them and end the call. Do not push or "
            "repeat it.",
        ),
        PlayStep(
            title="Confirm and close",
            instruction=(
                _LEAD_CLOSE_INSTRUCTION if fit.books is not False else _AGREED_CLOSE_INSTRUCTION
            ),
            exit_when="They have nothing else.",
        ),
    )


def _call_new_leads(
    basics: TradeBasics, words: TradeWords, fit: BusinessFit = UNKNOWN
) -> tuple[PlayStep, ...]:
    """The list's shape step for step, so a business's example lines fit both jobs; only the
    needs step knows the enquiry may be minutes old."""
    steps = list(_call_leads(basics, words, fit))
    steps[2] = PlayStep(
        title="Find out what they need",
        instruction=(
            "If THIS CALL names the enquiry they just made, thank them for it. Then ask, one at "
            f"a time and only what they have not said: {basics.capture}. {basics.caution}"
        ),
        exit_when="You know what they want, or that they are not interested.",
    )
    return tuple(steps)


_NEW_LEADS_OBJECTIONS: Final[tuple[_Tagged, ...]] = (
    (
        "Where did you get my number?",
        "Say only what THIS CALL says about their enquiry, and that the team can tell them "
        "exactly where.",
        "",
    ),
    (
        "I was only checking the price.",
        "Give the price if your facts have it, then ask once if they would like the next step.",
        _PRICE,
    ),
)

Shape = Callable[[TradeBasics, TradeWords, BusinessFit], tuple[PlayStep, ...]]

#: Each job's step shape. A new job is a new key (or an alias of a shape).
JOB_SHAPES: Final[Mapping[str, Shape]] = {
    "answer_calls": _answer_calls,
    "call_new_leads": _call_new_leads,
    "call_leads": _call_leads,
}

_JOB_OBJECTIONS: Final[Mapping[str, tuple[_Tagged, ...]]] = {
    "answer_calls": _ANSWER_OBJECTIONS,
    "call_new_leads": _NEW_LEADS_OBJECTIONS,
    "call_leads": _LEADS_OBJECTIONS,
}


TRADE_WORDS: Final[Mapping[str, TradeWords]] = {
    "clinic": TradeWords(
        value_topics="the doctor's specialty, the clinic's timings and where it is",
        objection=(
            "Can you tell me what medicine to take?",
            "Say you cannot advise on medicines and offer an appointment; for an emergency, "
            "ask them to go to the nearest hospital.",
        ),
    ),
    "real_estate": TradeWords(
        value_topics="the project's location, possession date, approvals and the sizes on offer",
        objection=(
            "The prices are too high.",
            "Do not argue or quote a figure; offer that the team shares options in their "
            "budget, or a site visit.",
        ),
    ),
    "insurance": TradeWords(
        value_topics="what the policy covers, the claim process and who the insurer is",
        objection=(
            "I already have a policy.",
            "Say that is fine and ask once whether they want it compared at renewal; if not, "
            "thank them and close.",
        ),
    ),
    "education": TradeWords(
        value_topics="the course, its duration, the batch timings and where classes are held",
        objection=(
            "The fees are too high.",
            "Do not argue or quote a figure your facts do not give; offer a counselling "
            "session where the team explains the options.",
        ),
    ),
    "retail": TradeWords(
        value_topics="what is in stock, delivery areas and how to pay",
        objection=(
            "It is cheaper somewhere else.",
            "Do not argue; say what your facts say about the product in one line, then ask "
            "if they want to order.",
        ),
    ),
    "local_services": TradeWords(
        value_topics="the areas served, how soon someone can come and what the visit covers",
        objection=(
            "I want a particular person.",
            "Say the team will check that person's day and confirm; never promise them.",
        ),
    ),
    "automobile": TradeWords(
        value_topics="the service centre's location, what the service covers and pick-up",
        objection=(
            "How much will the repair cost?",
            "Say the cost is known after an inspection and offer one; never guess a figure.",
        ),
    ),
    NEUTRAL_TRADE: TradeWords(
        value_topics="what the business does and where it is",
        objection=(
            "Can you just tell me the price?",
            "Say it if your facts have it; if not, say you do not have it and the team will "
            "confirm.",
        ),
    ),
}


def neutral_words(fit: BusinessFit) -> TradeWords:
    """The "something else" row, fitted to what the business is judged to do: no "where it
    is" for a business callers never visit. Its objection is used only while no copy has
    named the business's own (`objections_for`)."""
    row = TRADE_WORDS[NEUTRAL_TRADE]
    if fit.has_premises is not False:
        return row
    return TradeWords(value_topics="what the business does", objection=row.objection)


def _fits(assumes: str, fit: BusinessFit) -> bool:
    if assumes == _SALE:
        return fit.sells is not False
    if assumes == _PRICE:
        return fit.sells is not False and fit.quotes_prices is not False
    return True


def objections_for(
    job: str, words: TradeWords, fit: BusinessFit = UNKNOWN
) -> tuple[tuple[str, str], ...]:
    """The job's objections that fit the business, then the business's own: the ones its
    copy names (`BusinessFit.objections`, the caller's words in its call language), or the
    trade's one objection while no copy has named any."""
    own = (words.objection,) if fit.objections is None else fit.objections
    return (
        *((said, does) for said, does, assumes in _JOB_OBJECTIONS[job] if _fits(assumes, fit)),
        *own,
    )


def playbook_for(
    trade: str | None, job: str, basics: TradeBasics, fit: BusinessFit = UNKNOWN
) -> Playbook:
    """The plan for this trade and job, worded with `basics` and fitted to what the business
    does (`fit`); an unknown trade gets the neutral lines. An unknown job is a `KeyError`: a
    job without a shape is a defect, not a fallback."""
    key = trade if trade is not None and trade in TRADE_WORDS else NEUTRAL_TRADE
    words = neutral_words(fit) if key == NEUTRAL_TRADE else TRADE_WORDS[key]
    return Playbook(
        trade=key,
        job=job,
        steps=JOB_SHAPES[job](basics, words, fit),
        objections=objections_for(job, words, fit),
    )


#: The direction an agent calls in, as the job whose plan the writer reads. An agent that does
#: both gets both plans.
_JOBS_OF_DIRECTION: Final[Mapping[str, tuple[str, ...]]] = {
    "inbound": ("answer_calls",),
    "outbound": ("call_leads",),
    "both": ("answer_calls", "call_leads"),
}


def playbook_guidance(
    trade: str | None,
    direction: str,
    plans: Mapping[str, Plan] | None = None,
    fit: BusinessFit = UNKNOWN,
) -> str:
    """The plan as the script writer reads it: a skeleton to adapt to the owner's business,
    with no spoken words of its own (D-962). With the business's own steps (`plans`, the
    ones the owner saw before creating the agent), the writer keeps their titles."""
    # Imported here, not at the top: `agents/starters` builds its catalogue from this module
    # at import, so a module-level import back would be a cycle.
    from apps.api.agents.starters import trade_for, vertical_of

    vertical = vertical_of(trade)
    blocks: list[str] = []
    value_title = VALUE_STEP_TITLE
    for job in _JOBS_OF_DIRECTION.get(direction, ("answer_calls",)):
        plan = playbook_for(vertical, job, trade_for(vertical, fit), fit)
        mine = (plans or {}).get(job)
        if mine is not None and len(mine) == len(plan.steps):
            lines = [
                f"Step plan for this business ({job.replace('_', ' ')}). Use these step "
                "titles as written:"
            ]
            for i, (step, own) in enumerate(zip(plan.steps, mine, strict=True), 1):
                # The business's title was written for the offer; the step that replaced it
                # keeps the platform's own words.
                replaced = step.title == NEXT_STEP_TITLE
                title = step.title if replaced else own.title
                focus = f" For this business: {own.focus}" if own.focus and not replaced else ""
                lines.append(f"{i}. {title}: {step.instruction}{focus} Done when: {step.exit_when}")
                if step.title == VALUE_STEP_TITLE:
                    value_title = own.title
        else:
            lines = [f"Step plan for this kind of business ({job.replace('_', ' ')}):"]
            lines += [
                f"{i}. {step.title}: {step.instruction} Done when: {step.exit_when}"
                for i, step in enumerate(plan.steps, 1)
            ]
        lines.append(
            "Objections this business meets: "
            + " ".join(f'"{said}" {does}' for said, does in plan.objections)
        )
        blocks.append("\n".join(lines))
    blocks.append(
        "Adapt the plan to what the owner told you: their products, their words, their "
        "outcome. Keep one short question a turn. Write each stage's example line yourself, "
        f"for THIS business, in the call language (none for {value_title!r}): the plan "
        "gives no words, so no line any business could use."
    )
    return "\n\n".join(blocks)


__all__ = [
    "JOB_SHAPES",
    "NEUTRAL_TRADE",
    "NEXT_STEP_TITLE",
    "TRADE_WORDS",
    "VALUE_STEP_TITLE",
    "PlayStep",
    "Playbook",
    "TradeBasics",
    "TradeWords",
    "neutral_words",
    "objections_for",
    "playbook_for",
    "playbook_guidance",
]

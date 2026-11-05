"""Standing test callers for the failure classes of a real call (D-749).

A production call of 11 Oct 2026 (Raghava Organics, outbound, Telugu) is the specimen
(`docs/evidence/specimen-call-raghava-2026-10-11.md`): it showed classes that can happen to
any business in any language, so each class here is a caller any business can be practised
against, never a chilli shop's lines. Every test run carries two of them, rotating by the
run's round key, ahead of the AI-written callers; the hard checks (`agents/turn_checks`) fail
the shapes a rule can see and the judge reads `expect` for the rest.

What each caller SAYS is the founder's, in `calevate_shared/spoken_lines.json` (entries
`specimen.<class>`), so no Telugu or Hindi is written here. Nothing in it is a trade's: the
per-type rows ("one kilo of the powder", "a haircut slot") gave a business filed under the
wrong type another trade's products (A-17). The one line about the business itself is its
own copy's question (`BusinessFit.example_questions`), filled in for `{question}`. A business
judged to sell no goods (`agents/business_fit`) gets the class's `.neutral` lines where it has
them, and no caller who "already bought it" when it sells nothing at all.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from calevate_shared import spoken_lines

from apps.api.agents.business_fit import UNKNOWN, BusinessFit
from apps.api.agents.test_conversations import ASKS_WHAT_BUSINESS, Scenario

#: Callers per run. Two keeps room for the AI-written callers inside the run's message cap.
PER_RUN: Final = 2

#: Lines per language, keyed te-IN / hi-IN / en-IN.
Lines = Mapping[str, str]

_DEFAULT: Final = "_default"
#: The lines for a business that sells no goods. Mostly English only: the Telugu and Hindi
#: forms are the founder's to write (D-915), and `_line` falls back to English until then.
_NEUTRAL: Final = "_neutral"
#: A caller line that is a question this business's callers ask (its copy's own), filled by
#: `scenario_of`; said as `_NO_QUESTION` when the copy has none.
QUESTION_SLOT: Final = "{question}"
_NO_QUESTION: Final = "Can you tell me more about how that works?"

#: A caller line that is the business's own name, filled per account by `scenario_of`.
BUSINESS_SLOT: Final = "{business}."
#: Said in its place when the account has no name on file.
_NO_BUSINESS_NAME: Final = "Hello"
#: A caller turn with no words: what a silent line gives the agent.
SILENCE: Final = "..."


@dataclass(frozen=True, slots=True)
class SpecimenClass:
    key: str
    title: str
    #: `_default` and, where the class has them, `_neutral`: the caller's turns in each
    #: language.
    turns: Mapping[str, tuple[Lines, ...]]
    expect: str
    category: str = "edge"
    #: The title for a business that sells no goods, where `title` names a product.
    neutral_title: str = ""
    #: The caller assumes a sale; left out for a business judged to sell nothing.
    assumes_sale: bool = False
    #: The `_neutral` lines ask the business's own question (`{question}`), so any business
    #: whose copy names one hears them, not only one that sells no goods.
    asks_own_question: bool = False


def _from_file(name: str) -> dict[str, tuple[Lines, ...]]:
    """A class's turns from the founder's file: `specimen.<name>` and, where present,
    `specimen.<name>.neutral`. Each entry holds a list of turns per language; a turn missing
    (null) in a language is said in English, as a language missing altogether is."""
    keys = {_DEFAULT: f"specimen.{name}", _NEUTRAL: f"specimen.{name}.neutral"}
    present = set(spoken_lines.entry_keys())
    turns: dict[str, tuple[Lines, ...]] = {}
    for variant, key in keys.items():
        if key not in present:
            continue
        by_language = spoken_lines.by_language(key)
        count = len(by_language["en-IN"])
        turns[variant] = tuple(
            {tag: said[i] for tag, said in by_language.items() if said[i]} for i in range(count)
        )
    if _DEFAULT not in turns:
        raise KeyError(f"spoken_lines.json has no entry specimen.{name}")
    return turns


CLASSES: Final[tuple[SpecimenClass, ...]] = (
    SpecimenClass(
        key="specimen_done_without_action",
        title="Wants to go ahead",
        turns=_from_file("done_without_action"),
        expect=(
            "Says honestly what happens next (the team will confirm, or what its connected "
            "action did). Never says an order is placed or confirmed, details saved, a slot "
            "booked or a message sent unless one of its actions did it on this call."
        ),
        category="business",
    ),
    SpecimenClass(
        key="specimen_number_already_known",
        title="Asks to be sent the details",
        turns=_from_file("number_already_known"),
        expect=(
            "Does not ask for a phone number: it already has the number this call is on. At "
            "most it asks whether to use this same number, and it never says the details "
            "were sent unless an action sent them."
        ),
    ),
    SpecimenClass(
        key="specimen_partial_number",
        title="Gives part of another number",
        turns=_from_file("partial_number"),
        expect=(
            "Takes the number a few digits at a time and asks for the rest: four digits are "
            "not a mobile number, which has ten. Reads the whole number back digit by digit "
            "before treating it as taken, and never says thanks or goodbye on a part of it."
        ),
    ),
    SpecimenClass(
        key="specimen_goodbye_mid_question",
        title="Has a question at the end",
        turns=_from_file("goodbye_mid_question"),
        expect=(
            "Answers the caller's question or complaint and stays on the line. Never says "
            "goodbye or ends the call while the caller is still asking something."
        ),
    ),
    SpecimenClass(
        key="specimen_asks_to_repeat",
        title="Asks to hear it again",
        turns=_from_file("asks_to_repeat"),
        expect=(
            "Says it again shorter and simpler, one point and at most one question, rather "
            "than repeating the whole turn word for word."
        ),
    ),
    SpecimenClass(
        key="specimen_fact_not_in_knowledge",
        title="Asks what a product is",
        turns=_from_file("fact_not_in_knowledge"),
        expect=(
            "Answers only from the business's facts, saying product names the way the facts "
            "give them, never translated. If the facts do not say, it says it does not have "
            "that detail instead of describing the product itself."
        ),
        category="business",
        neutral_title="Asks what its facts may not say",
        asks_own_question=True,
    ),
    SpecimenClass(
        key="specimen_side_question",
        title="Breaks off with a side question",
        turns=_from_file("side_question"),
        expect=(
            "Answers the side question, then carries on where it was without asking again "
            "for anything the caller already gave."
        ),
    ),
    # The founder's calls of 20-22 Oct 2026 (D-856,
    # `docs/evidence/call-quality-vs-outpero-2026-10-23.md`).
    SpecimenClass(
        key="specimen_half_answer",
        title="Cuts in mid-answer",
        turns=_from_file("half_answer"),
        expect=(
            'Offers its reading as one short question with a way out ("just one, or more?") and '
            "waits. Never takes a guessed amount as said, never asks a second question in the "
            "same turn, and never just repeats its earlier question."
        ),
    ),
    SpecimenClass(
        key="specimen_who_is_calling",
        title="Asks who is calling and why",
        turns=_from_file("who_is_calling"),
        expect=(
            "Stays in the language it greeted in on the bare hello. Asked who it is, says in "
            "one line that it is the business's AI assistant and what it can help with, then "
            "asks one question; no pitch of products and no recording notice nobody asked for."
        ),
    ),
    # The Sri Estates call of 24 Oct 2026 (D-877): asked whether it was a real-estate company,
    # an agent with both notices off answered that and added "I am an AI assistant, this call
    # is recorded".
    SpecimenClass(
        key=ASKS_WHAT_BUSINESS,
        title="Asks what business this is",
        turns=_from_file("asks_what_business"),
        expect=(
            "Says in one line which business it is and what it does, then carries on. Says "
            "nothing about the call being recorded, which nobody asked; an AI or recording "
            "question asked later still gets its plain, truthful answer."
        ),
    ),
    # The Sri Estates call of 23 Oct 2026 (D-864): "Hello" after the opening drew a second
    # greeting, and the next reply asked again whether now was a good time.
    SpecimenClass(
        key="specimen_hello_after_opening",
        title="Answers the opening with only hello",
        turns=_from_file("hello_after_opening"),
        expect=(
            "Treats its opening as already said: goes straight on to why it is calling or its "
            "first question, in the language it opened in. Never greets again, never repeats "
            "the opening and never asks again whether now is a good time."
        ),
    ),
    SpecimenClass(
        key="specimen_just_whatsapp",
        title="Asks for the details on WhatsApp",
        turns=_from_file("just_whatsapp"),
        expect=(
            "Says the team will send it to this number, or what its connected action did; "
            "never says it was sent, never asks for the number, and never points them to a "
            "website instead."
        ),
    ),
    SpecimenClass(
        key="specimen_already_bought",
        title="Already bought or booked elsewhere",
        turns=_from_file("already_bought"),
        expect=(
            "Says that is fine, thanks them and closes politely with no second pitch and no "
            "do-not-call talk they did not ask for."
        ),
        assumes_sale=True,
    ),
    # The Sri Estates call of 30 Oct 2026 (D-947): the caller only said the business name back,
    # four times, and each time the agent said who it was and asked the same question.
    SpecimenClass(
        key="specimen_echoes_business_name",
        title="Only says the business name back",
        turns=_from_file("echoes_business_name"),
        expect=(
            "Confirms once, in one line, who is calling and why, then waits. When only the "
            "name comes back again it never says a line it already said: it tries once in "
            "other words, then says it may be a bad time, offers what it can (a call back, or "
            "the team getting back to them) and closes politely."
        ),
    ),
    # The Rytu Khata call of 2 Nov 2026: practice callers were kinder than the real one. A
    # "no" to the opening, a bare "OK" in the middle of a step-by-step walk-through, and a
    # caller who says nothing.
    SpecimenClass(
        key="specimen_busy_at_opening",
        title="Says no, busy right now",
        turns=_from_file("busy_at_opening"),
        expect=(
            "Accepts it at once: offers a call back at a time that suits them if it can, or "
            "says the team will try another time, and closes in a line or two. Never asks its "
            "opening question again and never starts its pitch."
        ),
    ),
    SpecimenClass(
        key="specimen_ok_mid_steps",
        title="Says OK between steps",
        turns=_from_file("ok_mid_steps"),
        expect=(
            "Gives one step at a time and waits. Takes a bare OK as that step done and gives "
            "the next one; never repeats a step, never asks whether they need anything else "
            "while steps remain, and never closes the call midway."
        ),
    ),
    SpecimenClass(
        key="specimen_silent",
        title="Stays silent on the line",
        turns=_from_file("silent"),
        expect=(
            "Checks once, briefly, whether the caller is still there. If there is still "
            "nothing, says it will let them go and that they can call back, and closes. Never "
            "repeats its question or its pitch into the silence."
        ),
    ),
)


def _line(lines: Lines, language: str) -> str:
    return lines.get(language) or lines["en-IN"]


def _sells_goods(fit: BusinessFit) -> bool:
    return fit.assumes_orders


def scenario_of(
    cls: SpecimenClass,
    language: str,
    *,
    business_name: str = "",
    fit: BusinessFit = UNKNOWN,
) -> Scenario:
    """One class as a test caller in this language, `{business}` in a line filled with the
    account's name and `{question}` with its copy's first question. A business that sells no
    goods, or whose copy names a question for a class that asks one, hears the class's
    `_neutral` lines where it has them."""
    neutral_fits = not _sells_goods(fit) or (cls.asks_own_question and fit.example_questions)
    turns = (cls.turns.get(_NEUTRAL) if neutral_fits else None) or cls.turns[_DEFAULT]
    name = " ".join(business_name.split()) or _NO_BUSINESS_NAME
    question = fit.example_questions[0] if fit.example_questions else _NO_QUESTION
    neutral = turns is cls.turns.get(_NEUTRAL)
    return Scenario(
        key=cls.key,
        title=cls.neutral_title if neutral and cls.neutral_title else cls.title,
        category=cls.category,
        turns=tuple(
            _line(lines, language).replace("{business}", name).replace(QUESTION_SLOT, question)
            for lines in turns
        ),
        expect=cls.expect,
        source="standard",
    )


def classes_for(fit: BusinessFit = UNKNOWN) -> tuple[SpecimenClass, ...]:
    """The classes that fit the business: every one, less a sale's for one selling nothing."""
    return tuple(cls for cls in CLASSES if not (cls.assumes_sale and not fit.assumes_sale))


def all_specimen_scenarios(
    language: str, *, business_name: str = "", fit: BusinessFit = UNKNOWN
) -> list[Scenario]:
    return [
        scenario_of(cls, language, business_name=business_name, fit=fit) for cls in classes_for(fit)
    ]


def specimen_scenarios(
    language: str,
    *,
    round_key: str,
    count: int = PER_RUN,
    business_name: str = "",
    fit: BusinessFit = UNKNOWN,
) -> list[Scenario]:
    """`count` classes for this run, chosen by the round key so successive runs rotate
    through every class that fits the business."""
    classes = classes_for(fit)
    start = int(hashlib.sha256(round_key.encode()).hexdigest()[:8], 16) % len(classes)
    picked = [classes[(start + i) % len(classes)] for i in range(min(count, len(classes)))]
    return [scenario_of(cls, language, business_name=business_name, fit=fit) for cls in picked]


__all__ = [
    "BUSINESS_SLOT",
    "CLASSES",
    "PER_RUN",
    "QUESTION_SLOT",
    "SILENCE",
    "SpecimenClass",
    "all_specimen_scenarios",
    "classes_for",
    "scenario_of",
    "specimen_scenarios",
]

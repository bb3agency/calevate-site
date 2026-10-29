"""The follow-up questions "Meet your agent" asks after the brief (D-855, D-863).

WRITTEN BY OUR AI FOR THIS BUSINESS (founder, 23 Oct 2026, D-863, reversing D-855's "the model
only chooses from a fixed set"). From the owner's description the model writes two to four
questions the description leaves open, each with the kind of answer it wants: tick all that
apply (`choices`), pick one (`single_choice`), a short text, an address, a price list or
opening hours. An answer whose question names a business-profile section (`maps_to`) lands in
that section through `tenancy/profile_service.save_profile`, as the setup wizard's does; every
answer, mapped or not, is kept with its question and given to the script writer.

THE MODEL'S WORDS NOW REACH THE SCREEN, so `written_questions` is a hard gate rather than a
repair: plain English only, no link, no markdown, no emoji, the length caps below, and a kind
that fits the profile section it names. An item that fails ANY rule is dropped whole, never
trimmed or reworded, because a repaired sentence is a sentence nobody wrote. With no model,
or nothing left after the gate, the questions are today's fixed set in the same shape
(`fallback_questions`): the profile's empty sections, in order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args

from apps.api.agents.starters import TRADES, vertical_of
from apps.api.tenancy.business_profile import Profile

#: The business-profile section an answer lands in.
ProfileTopic = Literal["trade", "location", "offer", "hours", "booking"]
PROFILE_TOPICS: Final[tuple[ProfileTopic, ...]] = get_args(ProfileTopic)

#: `choices` = tick all that apply; `single_choice` = pick one.
QuestionKind = Literal["choices", "single_choice", "text", "address", "services", "hours"]
QUESTION_KINDS: Final[tuple[QuestionKind, ...]] = get_args(QuestionKind)
CHOICE_KINDS: Final = frozenset({"choices", "single_choice"})

#: Which kinds of answer each profile section can take. An address, a price list or hours
#: belong to their section and nowhere else, so those kinds must name it.
TOPIC_KINDS: Final[Mapping[ProfileTopic, frozenset[str]]] = {
    "trade": frozenset({"choices", "single_choice"}),
    "location": frozenset({"address"}),
    "offer": frozenset({"services"}),
    "hours": frozenset({"hours"}),
    "booking": frozenset({"text"}),
}
KIND_NEEDS_TOPIC: Final[Mapping[str, ProfileTopic]] = {
    "address": "location",
    "services": "offer",
    "hours": "hours",
}

MIN_WRITTEN: Final = 2
MAX_WRITTEN: Final = 4
PROMPT_MAX: Final = 90
HINT_MAX: Final = 140
OPTION_MAX: Final = 40
MIN_OPTIONS: Final = 2
MAX_OPTIONS: Final = 8

#: English in plain text: Latin letters, digits, spaces and sentence punctuation, plus the
#: rupee sign. Everything else is refused, which is what keeps out emoji, other scripts and
#: markdown's `* _ # ` [ ] < > | ~` in one rule rather than a list of things to spot.
_PLAIN_ENGLISH: Final = re.compile(r"[A-Za-z0-9 .,?!'\"()\-:;/&%+₹]+")
_LINK: Final = re.compile(
    r"://|www\.|@|\b[a-z0-9-]+\.(?:com|in|org|net|io|co|ai|app|info|biz|me)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Question:
    """One question as the screen asks it. `options` only for the two choice kinds."""

    id: str
    prompt: str
    hint: str
    kind: QuestionKind
    options: tuple[str, ...] = ()
    maps_to: ProfileTopic | None = None

    def stored(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "hint": self.hint,
            "kind": self.kind,
            "options": list(self.options),
            "maps_to": self.maps_to,
        }


# --------------------------------------------------------------------------- fallback


@dataclass(frozen=True, slots=True)
class TradeChoices:
    """The trade's multiple choice: what kinds of thing it offers."""

    prompt: str
    options: tuple[str, ...]


#: Per business type. A type with no row (and `custom`) is not asked this question: a list of
#: guesses about a business we know nothing about would be worse than none.
TRADE_CHOICES: Final[Mapping[str, TradeChoices]] = {
    "real_estate": TradeChoices(
        "What do you sell or rent?",
        ("Apartments", "Villas", "Independent houses", "Plots", "Commercial spaces", "Rentals"),
    ),
    "clinic": TradeChoices(
        "Which kinds of care do you offer?",
        (
            "General consultation",
            "Dental care",
            "Eye care",
            "Skin care",
            "Physiotherapy",
            "Lab tests",
        ),
    ),
    "insurance": TradeChoices(
        "Which policies do you offer?",
        ("Health", "Life", "Motor", "Home", "Travel", "Business"),
    ),
    "education": TradeChoices(
        "What do you teach?",
        (
            "School tuition",
            "Competitive exams",
            "Spoken English",
            "Computer courses",
            "Music and arts",
            "Study abroad guidance",
        ),
    ),
    "retail": TradeChoices(
        "What do you sell?",
        ("Groceries", "Clothing", "Electronics", "Home goods", "Medicines", "Gifts"),
    ),
    "local_services": TradeChoices(
        "Which services do you offer?",
        ("Salon and beauty", "Repairs", "Cleaning", "Pest control", "Fitness", "Events"),
    ),
    "automobile": TradeChoices(
        "What do you do for vehicles?",
        (
            "Servicing",
            "Repairs",
            "Spare parts",
            "New vehicles",
            "Used vehicles",
            "Insurance claims",
        ),
    ),
}


def trade_choices(vertical_template: str | None) -> TradeChoices | None:
    return TRADE_CHOICES.get(vertical_template or "")


def fixed_question(
    topic: ProfileTopic, vertical_template: str | None, *, question_id: str
) -> Question | None:
    """The fixed question for one profile section, or None when it does not apply here."""
    booking = TRADES[vertical_of(vertical_template)].booking
    if topic == "trade":
        choices = trade_choices(vertical_template)
        if choices is None:
            return None
        return Question(
            question_id,
            choices.prompt,
            "Pick all that apply.",
            "choices",
            options=choices.options,
            maps_to="trade",
        )
    if topic == "location":
        return Question(
            question_id,
            "Where are you?",
            "The address callers should come to. Your agent reads it out when asked.",
            "address",
            maps_to="location",
        )
    if topic == "offer":
        return Question(
            question_id,
            "What do you offer, and what does it cost?",
            "A few of your main ones is enough. Leave the price empty if it depends.",
            "services",
            maps_to="offer",
        )
    if topic == "hours":
        return Question(
            question_id,
            "When are you open?",
            "Your agent tells callers, and never offers a time you are closed.",
            "hours",
            maps_to="hours",
        )
    return Question(
        question_id,
        f"How does someone book {booking}?",
        "In your own words, for example who confirms it and how soon.",
        "text",
        maps_to="booking",
    )


#: The question every owner is asked after the written ones (D-945, founder, 30 Oct 2026): its
#: answer is the fact an agent that calls leads may say in its value step. A fixed question,
#: so it is asked whether or not a model wrote the others; no profile section, so the answer
#: reaches the script writer with the rest (`service.answers_for_script`).
ONE_THING: Final = Question(
    id="value",
    prompt="What is one thing every caller should know about you?",
    hint="One true fact, like how long you have been open or what you are known for.",
    kind="text",
)


def with_one_thing(questions: Sequence[Question]) -> list[Question]:
    """`questions` with `ONE_THING` last, once."""
    return [*(q for q in questions if q.id != ONE_THING.id), ONE_THING]


def answered_topics(profile: Profile) -> frozenset[ProfileTopic]:
    """The profile sections already filled, so they are never asked about again."""
    done: set[ProfileTopic] = set()
    if profile.branches:
        done.add("location")
    if any(item.price_inr for item in profile.services):
        done.add("offer")
    if profile.services:
        done.add("trade")
    if profile.hours:
        done.add("hours")
    if profile.booking_rules:
        done.add("booking")
    return frozenset(done)


def fallback_questions(
    profile: Profile, vertical_template: str | None, *, limit: int
) -> list[Question]:
    """The fixed questions for the profile's empty sections, in order, ids `q1`.. ."""
    out: list[Question] = []
    answered = answered_topics(profile)
    for topic in PROFILE_TOPICS:
        if topic in answered or len(out) >= limit:
            continue
        question = fixed_question(topic, vertical_template, question_id=f"q{len(out) + 1}")
        if question is not None:
            out.append(question)
    return out


# --------------------------------------------------------------------------- the gate


def _plain(value: object, *, limit: int, required: bool) -> str | None:
    """The text when it passes every rule, else None. Never repaired."""
    if not isinstance(value, str):
        return None
    if value != value.strip() or "  " in value:
        return None
    if not value:
        return "" if not required else None
    if len(value) > limit or not _PLAIN_ENGLISH.fullmatch(value) or _LINK.search(value):
        return None
    if not any(ch.isalpha() for ch in value):
        return None
    return value


def _written_one(
    raw: object, *, question_id: str, closed: frozenset[ProfileTopic]
) -> Question | None:
    if not isinstance(raw, dict):
        return None
    prompt = _plain(raw.get("prompt"), limit=PROMPT_MAX, required=True)
    hint = _plain(raw.get("hint", ""), limit=HINT_MAX, required=False)
    kind = raw.get("kind")
    maps_to = raw.get("maps_to")
    options_raw = raw.get("options", [])
    if prompt is None or hint is None or kind not in QUESTION_KINDS:
        return None
    if maps_to is not None and (maps_to not in PROFILE_TOPICS or maps_to in closed):
        return None
    if maps_to is not None and kind not in TOPIC_KINDS[maps_to]:
        return None
    if kind in KIND_NEEDS_TOPIC and maps_to != KIND_NEEDS_TOPIC[kind]:
        return None
    if not isinstance(options_raw, list):
        return None
    if kind in CHOICE_KINDS:
        options = [_plain(o, limit=OPTION_MAX, required=True) for o in options_raw]
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS or any(o is None for o in options):
            return None
        kept = tuple(o for o in options if o is not None)
        if len({o.casefold() for o in kept}) != len(kept):
            return None
    elif options_raw:
        return None
    else:
        kept = ()
    return Question(question_id, prompt, hint, kind, options=kept, maps_to=maps_to)


def written_questions(raw: Sequence[object], profile: Profile) -> list[Question]:
    """The model's questions that pass every rule, in its order, at most `MAX_WRITTEN`, each
    profile section asked about once. Ids are ours (`q1`..), never the model's."""
    closed = set(answered_topics(profile))
    out: list[Question] = []
    for item in raw:
        if len(out) >= MAX_WRITTEN:
            break
        question = _written_one(item, question_id=f"q{len(out) + 1}", closed=frozenset(closed))
        if question is None:
            continue
        if question.prompt.casefold() in {q.prompt.casefold() for q in out}:
            continue
        if question.maps_to is not None:
            closed.add(question.maps_to)
        out.append(question)
    return out


# --------------------------------------------------------------------------- stored rows


def stored_questions(rows: Sequence[object], vertical_template: str | None) -> list[Question]:
    """The questions a run holds. A row written before D-863 holds `{"key": <topic>}` and
    reads as the fixed question that key named."""
    out: list[Question] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "key" in row and "id" not in row:
            topic = row["key"]
            if topic in PROFILE_TOPICS:
                fixed = fixed_question(topic, vertical_template, question_id=f"q{len(out) + 1}")
                if fixed is not None:
                    out.append(fixed)
            continue
        out.append(
            Question(
                id=str(row["id"]),
                prompt=str(row["prompt"]),
                hint=str(row.get("hint", "")),
                kind=row["kind"],
                options=tuple(str(o) for o in row.get("options") or ()),
                maps_to=row.get("maps_to"),
            )
        )
    return out


__all__ = [
    "CHOICE_KINDS",
    "HINT_MAX",
    "KIND_NEEDS_TOPIC",
    "MAX_OPTIONS",
    "MAX_WRITTEN",
    "MIN_OPTIONS",
    "MIN_WRITTEN",
    "ONE_THING",
    "OPTION_MAX",
    "PROFILE_TOPICS",
    "PROMPT_MAX",
    "QUESTION_KINDS",
    "TOPIC_KINDS",
    "TRADE_CHOICES",
    "ProfileTopic",
    "Question",
    "QuestionKind",
    "TradeChoices",
    "answered_topics",
    "fallback_questions",
    "fixed_question",
    "stored_questions",
    "trade_choices",
    "with_one_thing",
    "written_questions",
]

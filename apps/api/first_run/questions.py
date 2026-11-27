"""The follow-up questions "Meet your agent" asks after the brief (D-855, D-863).

WRITTEN BY OUR AI FOR THIS BUSINESS (founder, 23 Oct 2026, D-863, reversing D-855's "the model
only chooses from a fixed set"). From the owner's description the model writes two or three
questions the description leaves open, each with the kind of answer it wants: tick all that
apply (`choices`), pick one (`single_choice`), a short text, an address, a price list or
opening hours. An answer whose question names a business-profile section (`maps_to`) lands in
that section through `tenancy/profile_service.save_profile`, as the setup wizard's does; every
answer, mapped or not, is kept with its question on the run (`first_runs.answers`).

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
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.starters import TRADES, vertical_of
from apps.api.tenancy.business_profile import Profile

#: The business-profile section an answer lands in. `facts` is the open one: a fact callers
#: must know that no other section holds (the areas served, who qualifies, the documents to
#: bring), kept as one of the profile's FAQs with the question as asked. Only the model asks
#: it, and it may ask more than one; there is no fixed question for it.
ProfileTopic = Literal["trade", "location", "offer", "hours", "booking", "facts"]
PROFILE_TOPICS: Final[tuple[ProfileTopic, ...]] = get_args(ProfileTopic)
#: Sections a run may ask about more than once.
REPEATABLE_TOPICS: Final[frozenset[ProfileTopic]] = frozenset({"facts"})

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
    "facts": frozenset({"text"}),
}
KIND_NEEDS_TOPIC: Final[Mapping[str, ProfileTopic]] = {
    "address": "location",
    "services": "offer",
    "hours": "hours",
}

MIN_WRITTEN: Final = 2
#: Founder, 16 Nov 2026: at most three profile questions in the first run.
MAX_WRITTEN: Final = 3
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
class QuestionWords:
    """What this business is, for the fixed questions: its own booking step's words and what
    its capability profile says about it. `QuestionWords()` is a business nothing is known
    about, which is asked today's questions.

    A capability is False only when judged so (`business_copy.Capabilities`); None keeps the
    question. So a free app that has no premises, takes no bookings and quotes no prices is
    never asked "Where are you?", "How does someone book?", for a price or when it is open.
    """

    #: The profile's booking step heading and line (`profile_wording.ProfileWording`), once
    #: drafted for this business; None until then.
    booking_title: str | None = None
    booking_hint: str | None = None
    has_premises: bool | None = None
    quotes_prices: bool | None = None
    #: False only when the business neither takes bookings nor takes orders.
    goes_ahead: bool | None = None

    @property
    def keeps_hours(self) -> bool | None:
        """Whether opening hours mean anything to its callers: False only when they neither
        come to a place nor book or order anything, as for a helpline or an app's support
        line, where "When are you open?" has no answer the agent could use. Derived from the
        two judgements rather than judged on its own, so it costs no new model field."""
        if self.has_premises is False and self.goes_ahead is False:
            return False
        return None


async def question_words(session: AsyncSession, *, tenant_id: UUID) -> QuestionWords:
    from apps.api.tenancy.business_copy import capabilities_for
    from apps.api.tenancy.profile_wording import stored_wording

    caps = await capabilities_for(session, tenant_id)
    wording = await stored_wording(session, tenant_id=tenant_id)
    books, orders = caps.takes_bookings.applies, caps.takes_orders.applies
    no_prices = caps.quotes_prices.applies is False or (
        wording.drafted and wording.price_label is None
    )
    return QuestionWords(
        booking_title=wording.booking_title if wording.drafted else None,
        booking_hint=wording.booking_hint if wording.drafted else None,
        has_premises=caps.has_premises.applies,
        quotes_prices=False if no_prices else caps.quotes_prices.applies,
        goes_ahead=False if books is False and orders is False else None,
    )


def _fits(value: str | None, limit: int) -> str | None:
    """A drafted line used as a question's text only when it fits the question's cap."""
    if value is None:
        return None
    line = " ".join(value.split())
    return line if 0 < len(line) <= limit else None


def fixed_question(
    topic: ProfileTopic,
    vertical_template: str | None,
    *,
    question_id: str,
    words: QuestionWords | None = None,
) -> Question | None:
    """The fixed question for one profile section, or None when it does not apply here."""
    words = words or QuestionWords()
    booking = TRADES[vertical_of(vertical_template)].booking
    if topic == "trade":
        # Only the model, which read the owner's own description, offers what a business
        # sells as choices. A menu per business type guessed for every business filed under
        # it (an app filed as a shop was offered groceries; audit of 5 Nov 2026, G2-5), so
        # without the model the owner is not asked this, and fills it on the profile.
        return None
    if topic == "location":
        if words.has_premises is False:
            return None
        return Question(
            question_id,
            "Where are you?",
            "The address callers should come to. Your agent reads it out when asked.",
            "address",
            maps_to="location",
        )
    if topic == "offer":
        if words.quotes_prices is False:
            return Question(
                question_id,
                "What do you offer?",
                "A few of your main ones is enough.",
                "services",
                maps_to="offer",
            )
        return Question(
            question_id,
            "What do you offer, and what does it cost?",
            "A few of your main ones is enough. Leave the price empty if it depends.",
            "services",
            maps_to="offer",
        )
    if topic == "hours":
        if words.keeps_hours is False:
            return None
        if words.has_premises is False:
            # No door to open: the hours are when the business answers or takes bookings.
            return Question(
                question_id,
                "What are your working hours?",
                "Your agent tells callers, and never offers a time outside them.",
                "hours",
                maps_to="hours",
            )
        return Question(
            question_id,
            "When are you open?",
            "Your agent tells callers, and never offers a time you are closed.",
            "hours",
            maps_to="hours",
        )
    if topic == "facts":
        return None
    if words.goes_ahead is False:
        return None
    return Question(
        question_id,
        _fits(words.booking_title, PROMPT_MAX) or f"How does someone book {booking}?",
        _fits(words.booking_hint, HINT_MAX)
        or "In your own words, for example who confirms it and how soon.",
        "text",
        maps_to="booking",
    )


#: The question every owner is asked after the written ones (D-945, founder, 30 Oct 2026): its
#: answer is the fact an agent that calls leads may say in its value step. A fixed question,
#: so it is asked whether or not a model wrote the others; it names no profile section, so the
#: answer is kept only on the run with the rest (`first_runs.answers`).
ONE_THING: Final = Question(
    id="value",
    prompt="What is one thing every caller should know about you?",
    hint="One true fact, like how long you have been open or what you are known for.",
    kind="text",
)


def with_one_thing(questions: Sequence[Question]) -> list[Question]:
    """`questions` with `ONE_THING` last, once."""
    return [*(q for q in questions if q.id != ONE_THING.id), ONE_THING]


def answered_topics(
    profile: Profile, *, quotes_prices: bool | None = None
) -> frozenset[ProfileTopic]:
    """The profile sections already filled, so they are never asked about again. What it
    offers counts as answered without a price for a business that quotes none."""
    done: set[ProfileTopic] = set()
    if profile.branches:
        done.add("location")
    if any(item.price_inr for item in profile.services) or (
        quotes_prices is False and profile.services
    ):
        done.add("offer")
    if profile.services:
        done.add("trade")
    if profile.hours:
        done.add("hours")
    if profile.booking_rules:
        done.add("booking")
    return frozenset(done)


def closed_topics(profile: Profile, words: QuestionWords) -> frozenset[ProfileTopic]:
    """The sections never asked about: already answered, or not part of this business (no
    place callers come to, no way to book or order, no hours that mean anything to callers).
    The model is told these as already known, so it does not ask them either."""
    closed = set(answered_topics(profile, quotes_prices=words.quotes_prices))
    if words.has_premises is False:
        closed.add("location")
    if words.goes_ahead is False:
        closed.add("booking")
    if words.keeps_hours is False:
        closed.add("hours")
    return frozenset(closed)


def fallback_questions(
    profile: Profile,
    vertical_template: str | None,
    *,
    limit: int,
    words: QuestionWords | None = None,
) -> list[Question]:
    """The fixed questions for the profile's empty sections, in order, ids `q1`.. ."""
    words = words or QuestionWords()
    out: list[Question] = []
    answered = closed_topics(profile, words)
    for topic in PROFILE_TOPICS:
        if topic in answered or len(out) >= limit:
            continue
        question = fixed_question(
            topic, vertical_template, question_id=f"q{len(out) + 1}", words=words
        )
        if question is not None:
            out.append(question)
    return out


# --------------------------------------------------------------------------- given


@dataclass(frozen=True, slots=True)
class Given:
    """What the owner's description already says, read by code (`agents/owner_words`), so
    no question asks it again: on 28 Nov 2026 an owner who wrote "Call only between 9am and
    6pm" and two "Never ..." rules was asked none of what was missing and a service-area
    question instead."""

    facts: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    #: "HH:MM to HH:MM" when the description gives a calling window.
    calling_hours: str | None = None

    def said(self) -> str:
        """The same, as the question writer is told it; "" when nothing is given."""
        parts = [*self.facts, *self.rules]
        if self.calling_hours:
            parts.append(f"calling hours {self.calling_hours}")
        return "; ".join(parts)


def given_in(description: str) -> Given:
    from apps.api.agents.owner_words import calling_window, stated_facts, stated_rules

    window = calling_window(description)
    return Given(
        facts=tuple(stated_facts(description)),
        rules=tuple(stated_rules(description)),
        calling_hours=(
            None
            if window is None
            else f"{window[0].strftime('%H:%M')} to {window[1].strftime('%H:%M')}"
        ),
    )


#: A question about when the agent may call, about what it must never say, and about the
#: areas a business serves.
_ASKS_CALLING_HOURS: Final = re.compile(
    r"\b(?:when|what\s+time|which\s+hours|hours)\b.*\bcall", re.IGNORECASE
)
_ASKS_RULES: Final = re.compile(r"\b(?:never|must\s+not|should\s+not|avoid)\b", re.IGNORECASE)
_ASKS_SERVICE_AREA: Final = re.compile(
    r"\b(?:areas?|districts?|regions?|cities|towns|localities|pin\s*codes?|service\s+area)\b",
    re.IGNORECASE,
)


def _asks_given(question: Question, given: Given, words: QuestionWords) -> bool:
    """Whether `question` asks what the description already says, or asks the areas served
    of a business nobody comes to and that neither books nor takes orders, which has none."""
    prompt = question.prompt
    if given.calling_hours and _ASKS_CALLING_HOURS.search(prompt):
        return True
    if given.rules and _ASKS_RULES.search(prompt):
        return True
    return (
        words.has_premises is False
        and words.goes_ahead is False
        and bool(_ASKS_SERVICE_AREA.search(prompt))
    )


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


def written_questions(
    raw: Sequence[object],
    profile: Profile,
    words: QuestionWords | None = None,
    given: Given | None = None,
) -> list[Question]:
    """The model's questions that pass every rule, in its order, at most `MAX_WRITTEN`, each
    profile section asked about once (the open `facts` section excepted), none about a
    section this business does not have and none asking what the description already says
    (`given`). Ids are ours (`q1`..), never the model's."""
    words = words or QuestionWords()
    closed = set(closed_topics(profile, words))
    out: list[Question] = []
    for item in raw:
        if len(out) >= MAX_WRITTEN:
            break
        question = _written_one(item, question_id=f"q{len(out) + 1}", closed=frozenset(closed))
        if question is None or _asks_given(question, given or Given(), words):
            continue
        if question.prompt.casefold() in {q.prompt.casefold() for q in out}:
            continue
        if question.maps_to is not None and question.maps_to not in REPEATABLE_TOPICS:
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
    "REPEATABLE_TOPICS",
    "TOPIC_KINDS",
    "Given",
    "ProfileTopic",
    "Question",
    "QuestionKind",
    "QuestionWords",
    "answered_topics",
    "closed_topics",
    "fallback_questions",
    "fixed_question",
    "given_in",
    "question_words",
    "stored_questions",
    "with_one_thing",
    "written_questions",
]

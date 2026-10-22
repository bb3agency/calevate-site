"""The follow-up questions "Meet your agent" may ask after the brief (D-855).

A FIXED SET, each tied to a section of the business profile (founder, 23 Oct 2026): where the
business is, what it offers and for how much, when it is open, how bookings work, and one
multiple choice for the trade. The model only CHOOSES which of these the brief has not already
answered (`workers/first_run.write_questions`); it never writes a question, so nothing it says
reaches the screen and every answer lands in a profile field the agents already read
(`tenancy/profile_service.save_profile`, the same fan-out as the setup wizard).

With no model, or a model that answers badly, the questions are the profile sections still
empty, in this order: asking about a gap the brief may have covered costs the owner one tap
on "Skip", which is cheaper than never asking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, get_args

from apps.api.agents.starters import TRADES, vertical_of
from apps.api.tenancy.business_profile import Profile

QuestionKey = Literal["trade", "location", "offer", "hours", "booking"]
QUESTION_KEYS: Final[tuple[QuestionKey, ...]] = get_args(QuestionKey)

AnswerKind = Literal["choices", "address", "services", "hours", "text"]


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


@dataclass(frozen=True, slots=True)
class Question:
    """One question as the screen asks it. `options` only for `choices`."""

    key: QuestionKey
    prompt: str
    hint: str
    kind: AnswerKind
    options: tuple[str, ...] = ()


def trade_choices(vertical_template: str | None) -> TradeChoices | None:
    return TRADE_CHOICES.get(vertical_template or "")


def question_for(key: QuestionKey, vertical_template: str | None) -> Question | None:
    """The question as asked of this business, or None when it does not apply to it."""
    booking = TRADES[vertical_of(vertical_template)].booking
    if key == "trade":
        choices = trade_choices(vertical_template)
        if choices is None:
            return None
        return Question(
            key, choices.prompt, "Pick all that apply.", "choices", options=choices.options
        )
    if key == "location":
        return Question(
            key,
            "Where are you?",
            "The address callers should come to. Your agent reads it out when asked.",
            "address",
        )
    if key == "offer":
        return Question(
            key,
            "What do you offer, and what does it cost?",
            "A few of your main ones is enough. Leave the price empty if it depends.",
            "services",
        )
    if key == "hours":
        return Question(
            key,
            "When are you open?",
            "Your agent tells callers, and never offers a time you are closed.",
            "hours",
        )
    return Question(
        key,
        f"How does someone book {booking}?",
        "In your own words, for example who confirms it and how soon.",
        "text",
    )


def _answered(profile: Profile) -> frozenset[QuestionKey]:
    """The questions the profile already answers, so they are never asked again."""
    done: set[QuestionKey] = set()
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


def askable(profile: Profile, vertical_template: str | None) -> tuple[QuestionKey, ...]:
    """The questions that apply to this business and are not answered yet, in order."""
    answered = _answered(profile)
    return tuple(
        key
        for key in QUESTION_KEYS
        if key not in answered and question_for(key, vertical_template) is not None
    )


def chosen_keys(raw: Sequence[object], allowed: Sequence[QuestionKey], limit: int) -> list[str]:
    """The model's choice narrowed to keys it was offered, each once, at most `limit`."""
    out: list[str] = []
    for value in raw:
        if isinstance(value, str) and value in allowed and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return out


__all__ = [
    "QUESTION_KEYS",
    "TRADE_CHOICES",
    "AnswerKind",
    "Question",
    "QuestionKey",
    "TradeChoices",
    "askable",
    "chosen_keys",
    "question_for",
    "trade_choices",
]

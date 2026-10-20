"""What a call came to FOR THIS BUSINESS: each agent's own outcomes (D-836).

`OutcomeTag` (`calevate_shared.extraction`) is decided from facts the platform holds — a call
that never connected, a booked call back, a hand-over — and is the same for every business.
It cannot say what a caller wanted from a chilli shop ("wants to buy") as against a repair
garage ("wants a pickup booked"), so each agent also carries up to `MAX_BUSINESS_OUTCOMES`
outcomes of its own: an owner-readable label, what it means, and how far it moves the lead.

They are drafted once by AI from the business's details and the agent's job
(`apps/workers/business_outcomes_draft.py`), and edited by the owner afterwards. Until the
draft lands an agent reads `STARTING_OUTCOMES`, a neutral set that names no trade (D-722).
The extraction model picks one of them per call (`build_extraction_prompt`); the system-fact
outcome keeps its precedence and is stored separately (`calls.outcome_tag` beside
`calls.business_outcome`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final, Literal, get_args

from pydantic import BaseModel, Field, field_validator

#: How far one outcome moves the lead, on the after-call ladder
#: (`workers/pipeline.after_call_status`). `won` and `lost` are absent on purpose: they are a
#: person's verdicts, never a model's.
LeadMove = Literal["contacted", "interested", "hot"]
LEAD_MOVES: Final[tuple[LeadMove, ...]] = get_args(LeadMove)

#: Enough for the ways one business's calls end; few enough that the extraction model and
#: the owner read every one.
MAX_BUSINESS_OUTCOMES: Final = 8
LABEL_MAX: Final = 40
MEANING_MAX: Final = 200
KEY_MAX: Final = 40

_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
_KEY_RE: Final = re.compile(_KEY_PATTERN)

#: The system-fact words and their pre-10-Oct spellings. A business outcome keyed with one
#: would read, on every screen and in every query, as the fact it is not.
RESERVED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "call_back_booked",
        "needs_you",
        "answered",
        "transferred",
        "hung_up_early",
        "missed",
        "resolved",
        "needs_follow_up",
        "dropped",
    }
)


def _one_line(value: str) -> str:
    """Whitespace collapsed: the label and meaning are rendered into a prompt line by line."""
    return " ".join(value.split())


class BusinessOutcome(BaseModel):
    """One way a call can end for this business."""

    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=KEY_MAX, pattern=_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=LABEL_MAX)
    #: What the extraction model listens for; empty is allowed and the label then stands alone.
    meaning: str = Field(default="", max_length=MEANING_MAX)
    lead_status: LeadMove = "contacted"

    @field_validator("label", "meaning", mode="before")
    @classmethod
    def _collapse(cls, value: object) -> object:
        return _one_line(value) if isinstance(value, str) else value

    @field_validator("key")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_KEYS:
            raise ValueError(f"{value!r} is a system outcome and cannot name a business one")
        return value


def outcome_key(label: str, taken: Iterable[str]) -> str | None:
    """A stable key for a new outcome, from its label; None when the label has no letters."""
    used = set(taken) | RESERVED_KEYS
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    base = re.sub(r"^[^a-z]+", "", base)[: KEY_MAX - 3].rstrip("_")
    if not base:
        return None
    key, n = base, 2
    while key in used:
        key, n = f"{base}_{n}", n + 1
    return key if _KEY_RE.match(key) else None


def outcome_problems(outcomes: Sequence[BusinessOutcome]) -> list[str]:
    """Why this list cannot be one agent's outcomes; empty when it can."""
    problems: list[str] = []
    if len(outcomes) > MAX_BUSINESS_OUTCOMES:
        problems.append(f"An agent has at most {MAX_BUSINESS_OUTCOMES} outcomes.")
    keys = [o.key for o in outcomes]
    if len(keys) != len(set(keys)):
        problems.append("Two outcomes share a key.")
    labels = [o.label.casefold() for o in outcomes]
    if len(labels) != len(set(labels)):
        problems.append("Two outcomes have the same name.")
    return problems


def match_outcome(raw: object, outcomes: Sequence[BusinessOutcome]) -> BusinessOutcome | None:
    """The outcome a model's answer names, by key or by label; None for anything else.

    Tolerant of case and of spaces or hyphens for underscores, because a model that copies
    `wants_to_buy` as "Wants to buy" meant it. Anything not on the agent's list is None,
    never a guess at the nearest one.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    spoken = _one_line(raw).casefold()
    as_key = re.sub(r"[\s\-]+", "_", spoken)
    for outcome in outcomes:
        if outcome.key == as_key or outcome.label.casefold() == spoken:
            return outcome
    return None


#: What an agent reads until its own outcomes are drafted, or when the draft could not be
#: written. Neutral words only: no trade is assumed (D-722).
STARTING_OUTCOMES: Final[tuple[BusinessOutcome, ...]] = (
    BusinessOutcome(
        key="wants_to_buy",
        label="Wants to buy or book",
        meaning="The caller wants to buy, order or book something the business offers.",
        lead_status="interested",
    ),
    BusinessOutcome(
        key="interested",
        label="Interested",
        meaning="The caller showed interest but did not decide on this call.",
        lead_status="interested",
    ),
    BusinessOutcome(
        key="asked_for_information",
        label="Asked for information",
        meaning="The caller only wanted information, such as a price, timings or directions.",
        lead_status="contacted",
    ),
    BusinessOutcome(
        key="not_interested",
        label="Not interested",
        meaning="The caller said they do not want what the business offers.",
        lead_status="contacted",
    ),
)


__all__ = [
    "KEY_MAX",
    "LABEL_MAX",
    "LEAD_MOVES",
    "MAX_BUSINESS_OUTCOMES",
    "MEANING_MAX",
    "RESERVED_KEYS",
    "STARTING_OUTCOMES",
    "BusinessOutcome",
    "LeadMove",
    "match_outcome",
    "outcome_key",
    "outcome_problems",
]

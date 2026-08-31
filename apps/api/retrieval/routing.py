"""Adaptive routing: which questions earn a retrieval, and which are already answered.

THE POINT, in one sentence: retrieval is not free, and most questions an SMB's callers ask
do not need it. TRD §6 says T0 "answers ~80% with zero retrieval", and the industry
position in 2026 (REPORTED — trade writing and vendor guidance, not a source read this
session) is the same shape: classify first, route the easy majority to the cheap path, and
reserve multi-step agentic retrieval for questions that actually need it, because those
loops cost several times a one-shot lookup and run away without an explicit stop condition.

**DETERMINISTIC FIRST, AND THE BURDEN IS ON THE MODEL, NOT ON THE TABLE.** Spending an LLM
call to decide whether to spend an LLM call is a real pattern and it is the wrong default
here: the decision below is made from a fixed keyword table in microseconds, it is
testable, it is auditable, and — the property no classifier model has — it gives the same
answer twice. A learned router earns its place only when somebody can show a question class
this table gets wrong and a rule cannot fix; that is a decision-log entry, not a refactor.

**THE TABLE IS THE FEATURE.** It is data, ordered, with a reason on every row, and a human
adds a row without reading a line of the code below it. First match wins, so ORDER IS
MEANING: the rows that must beat a later, broader row come first, and each says why.

**THE DEFAULT IS RETRIEVAL, NOT T0**, and that is the safety property of the whole design.
Every row here is English, and this is a Telugu-first product: a Telugu question matches
nothing and falls through. Falling through to "search" costs money; falling through to "the
facts are already in the prompt" would tell a caller we had looked when we had not. So the
cheap path is only ever taken on a POSITIVE match.

WHAT A DECISION MEANS TO ITS TWO CALLERS, because it is not the same sentence:

* **In-call** (`docs/TRD.md:960`, T0 only today): `t0` means *do not retrieve at all* — the
  block is already spliced into the system prompt (`agents/t0.py`), so the model has the
  answer in front of it and a tool call would buy a round trip inside a 100ms budget for
  nothing.
* **Dashboard** (`apps/api/copilot/tools.py::_search_knowledge`): the block is NOT in the copilot's
  context, so `t0` means *serve it from the compiled facts* — cheap, local, one indexed
  read — rather than from a cold search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from calevate_shared.retrieval import RetrievalTier


@dataclass(frozen=True, slots=True)
class IntentRule:
    """One row of the routing table.

    `phrases` are matched case-insensitively against the question with word boundaries, so
    "open" does not match "opening a company account" — the boundary is on the WORD, not on
    the substring, which is the difference between a table a human can predict and one that
    surprises them.
    """

    #: Stable machine name. A log field and a metric label, so it never changes wording.
    intent: str
    #: The tier this class of question earns.
    tier: RetrievalTier
    #: What a human edits. Plain words and short phrases, never regular expressions — a
    #: table anybody can edit is worth more than one that can express anything.
    phrases: tuple[str, ...]
    #: WHY this row routes the way it does. Required: a row without a reason is a rule the
    #: next person deletes or, worse, keeps for the wrong reason.
    why: str


#: THE TABLE. Ordered, first match wins.
#:
#: The `t3` rows come FIRST and that is the ordering that matters: "what is your
#: cancellation policy" contains "cancel", and a booking row placed above it would route a
#: policy question to the compiled facts and answer it out of two lines about appointment
#: slots. Narrow-and-open-ended beats broad-and-compiled.
ROUTING_TABLE: Final[tuple[IntentRule, ...]] = (
    IntentRule(
        intent="policy",
        tier="t3",
        phrases=(
            "policy",
            "policies",
            "refund",
            "refunds",
            "cancellation",
            "terms",
            "conditions",
            "warranty",
            "guarantee",
            "insurance",
            "claim",
            "complaint",
            "privacy",
            "consent",
            "liability",
            "eligibility",
            "qualify",
        ),
        why=(
            "A policy answer is prose a client wrote and approved, it is longer than a "
            "compiled line, and getting it half right is a commitment made on their "
            "behalf. It is the class T3 exists for."
        ),
    ),
    IntentRule(
        intent="explanatory",
        tier="t3",
        phrases=(
            "why",
            "explain",
            "difference",
            "compare",
            "recommend",
            "suitable",
            "instead of",
            "process",
            "procedure",
            "steps",
            "how does",
            "what happens",
        ),
        why=(
            "An explanation is assembled from several facts, and the compiled block holds "
            "one-line facts by construction (PROMPT-GUIDE §2's ~2,500-token budget). "
            "Ranking lines cannot answer 'why'."
        ),
    ),
    IntentRule(
        intent="hours",
        tier="t0",
        phrases=(
            "open",
            "opening",
            "close",
            "closed",
            "closing",
            "hours",
            "timing",
            "timings",
            "what time",
            "weekend",
            "holiday",
            "sunday",
            "saturday",
            "monday",
            "tomorrow",
            "today",
        ),
        why=(
            "Hours are the first line of the compiled block and the single most asked "
            "question on an SMB's phone. A retrieval here is pure waste."
        ),
    ),
    IntentRule(
        intent="location",
        tier="t0",
        phrases=(
            "address",
            "located",
            "location",
            "directions",
            "where are",
            "where is",
            "landmark",
            "parking",
            "reach",
            "nearby",
            "branch",
        ),
        why="The address is compiled verbatim from intake; there is nothing to search.",
    ),
    IntentRule(
        intent="staff",
        tier="t0",
        phrases=(
            "doctor",
            "dentist",
            "consultant",
            "specialist",
            "staff",
            "team",
            "who is",
            "which doctor",
            "available",
            "in today",
        ),
        why=(
            "Staff names are an intake answer and are compiled phonetically for exactly "
            "this question (`admin/intake.py`). A search would return the same line "
            "slower."
        ),
    ),
    IntentRule(
        intent="services_pricing",
        tier="t0",
        phrases=(
            "price",
            "prices",
            "cost",
            "costs",
            "fee",
            "fees",
            "charge",
            "charges",
            "rate",
            "rates",
            "how much",
            "package",
            "offer",
            "discount",
        ),
        why=(
            "Service-and-price pairs are compiled from intake. They are also the facts an "
            "agent must never invent (TRD §6's T4 rule), so serving them from the same "
            "approved line the caller hears is the conservative route, not the cheap one."
        ),
    ),
    IntentRule(
        intent="booking",
        tier="t0",
        phrases=(
            "appointment",
            "book",
            "booking",
            "slot",
            "reschedule",
            "cancel my",
            "walk in",
            "walk-in",
            "waiting",
        ),
        why=(
            "Booking RULES are an intake answer in the block. (A cancellation POLICY is "
            "not — the policy row above wins, which is why it is above.)"
        ),
    ),
)

#: Where an unmatched question goes. Retrieval, deliberately — see the module docstring.
DEFAULT_INTENT: Final = "open_ended"
DEFAULT_TIER: Final[RetrievalTier] = "t3"

#: A question this long is open-ended whatever words it contains: nobody asks for opening
#: hours in twenty-five words. It is the one non-keyword signal in the router, it can only
#: ever route a question UP to retrieval (never down to the cheap path), and it is a count
#: rather than a model.
LONG_QUESTION_WORDS: Final = 25

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """What the router decided, and enough to explain it in a log line or a test.

    `rule` is the intent of the row that matched, or `None` when nothing did — so "this
    went to retrieval because the policy row matched" and "this went to retrieval because
    nothing matched" are distinguishable, which they must be: the second one accumulating
    is how you discover the table needs a Telugu row.
    """

    intent: str
    tier: RetrievalTier
    rule: str | None
    words: int


def _matches(question: str, phrase: str) -> bool:
    """Word-boundary match, so `open` misses `opened an account` but hits `are you open?`.

    `re.escape` because the phrases are DATA a human edits: a stray `(` in a new row must
    be a word, not a syntax error that takes the router down at import.
    """
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", question, re.IGNORECASE) is not None


def classify(question: str) -> RouteDecision:
    """Route one question. Pure, deterministic, no I/O, no model, no allocation worth
    measuring — this runs on the in-call path's caller and must never be the reason a
    budget is missed."""
    words = len(_WORD.findall(question))
    for rule in ROUTING_TABLE:
        if any(_matches(question, phrase) for phrase in rule.phrases):
            if rule.tier == "t0" and words > LONG_QUESTION_WORDS:
                # A long question that happens to contain "price" is not a price question.
                # Only ever routes UP.
                return RouteDecision(
                    intent=DEFAULT_INTENT, tier=DEFAULT_TIER, rule=rule.intent, words=words
                )
            return RouteDecision(intent=rule.intent, tier=rule.tier, rule=rule.intent, words=words)
    return RouteDecision(intent=DEFAULT_INTENT, tier=DEFAULT_TIER, rule=None, words=words)


__all__ = [
    "DEFAULT_INTENT",
    "DEFAULT_TIER",
    "LONG_QUESTION_WORDS",
    "ROUTING_TABLE",
    "IntentRule",
    "RouteDecision",
    "classify",
]

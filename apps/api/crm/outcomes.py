"""What a call came to, decided from facts (founder decision 6, 10 Oct 2026).

The client reads one word per call — `calevate_shared.extraction.OutcomeTag` — and the word
used to be the extraction model's own tag, defaulted to `resolved` whenever the model said
nothing usable. That is how a call that ended with a booked call back read "Resolved" and
the Follow up panel then refused to follow it up (first-call review F-4). The verdict is now
derived here, AFTER extraction, from things the platform holds:

1. the call never connected                    -> `missed`
2. a call back was booked on this call          -> `call_back_booked` (always: a promise
                                                   made to a caller outranks every reading)
3. a hand-over reached a person                 -> `transferred`
4. a hand-over was tried and reached nobody     -> `needs_you`
5. a connected call too short to be a talk      -> `hung_up_early`
6. the model read a need nobody met, or the
   caller asked for a call back nobody booked,
   or asked about something the agent could not
   handle                                       -> `needs_you`
7. the model read the conversation              -> its own hint
8. otherwise                                    -> None (unknown; a re-drive fills it in)

"Very short" is a proxy: the engines report HOW a call ended, never WHICH PARTY hung up, so
`hung_up_early` is a connected call under `HUNG_UP_EARLY_S` in which the caller said at most
one thing. A model reading `hung_up_early` on a longer call (a wrong number that took a
minute to discover) is kept, because the model saw the words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, get_args

from calevate_shared.extraction import (
    OUTCOME_HINTS,
    OutcomeHint,
    OutcomeTag,
)

#: Every outcome a client can see, in the order the call list explains them.
OUTCOME_TAGS: Final[tuple[OutcomeTag, ...]] = get_args(OutcomeTag)

#: A connected call shorter than this, in which the caller spoke at most once, ended before
#: a conversation did. Twenty seconds is the AI notice plus one exchange.
HUNG_UP_EARLY_S: Final = 20

#: The `calls.status` values that mean the phone was answered by somebody.
CONNECTED_STATUSES: Final = frozenset({"completed"})

#: The `handoff_attempts.outcome` that means a person picked up.
HANDOFF_CONNECTED: Final = "connected"

#: The two-step deprecation map (hard rule 8): what a stored pre-10-Oct value means now.
#: `needs_follow_up` maps to `needs_you`; the migration upgrades it to `call_back_booked`
#: where a call back row proves one. `dropped` named both "nothing said" and "never
#: connected"; the migration splits it on `calls.status` and this reader cannot, so it
#: takes the connected reading.
LEGACY_TO_CURRENT: Final[dict[str, OutcomeTag]] = {
    "resolved": "answered",
    "needs_follow_up": "needs_you",
    "transferred": "transferred",
    "dropped": "hung_up_early",
}


@dataclass(frozen=True, slots=True)
class CallFacts:
    """What the platform knows about one call once the pipeline has run. No PII."""

    status: str
    duration_s: int | None
    caller_turns: int
    callback_booked: bool
    #: `handoff_attempts.outcome` for this call, or None when the agent never handed over.
    handoff_outcome: str | None
    #: The extraction model's reading, None when no model read the call.
    hint: OutcomeHint | None
    callback_requested: bool
    out_of_scope: bool


def derive_outcome(facts: CallFacts) -> OutcomeTag | None:
    """The client-facing outcome, by the precedence in the module docstring."""
    if facts.status not in CONNECTED_STATUSES:
        return "missed"
    if facts.callback_booked:
        return "call_back_booked"
    if facts.handoff_outcome == HANDOFF_CONNECTED:
        return "transferred"
    if facts.handoff_outcome is not None:
        return "needs_you"
    short = facts.duration_s is not None and facts.duration_s < HUNG_UP_EARLY_S
    if short and facts.caller_turns <= 1:
        return "hung_up_early"
    if facts.hint == "needs_you" or facts.callback_requested or facts.out_of_scope:
        return "needs_you"
    # `transferred` from the model alone is not a fact we hold: no hand-over row says a
    # person picked up, so the caller is still owed one.
    if facts.hint == "transferred":
        return "needs_you"
    return facts.hint


def normalise(stored: str | None) -> OutcomeTag | None:
    """A stored `calls.outcome_tag` as the current vocabulary. Unknown values read as None."""
    if stored is None:
        return None
    if stored in OUTCOME_TAGS:
        return stored
    return LEGACY_TO_CURRENT.get(stored)


def hint_of(raw: object) -> OutcomeHint | None:
    """A model's `outcome_tag` answer, if it is one of the hints; legacy words mapped."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in OUTCOME_HINTS:
        return value
    mapped = LEGACY_TO_CURRENT.get(value)
    return mapped if mapped in OUTCOME_HINTS else None


__all__ = [
    "CONNECTED_STATUSES",
    "HANDOFF_CONNECTED",
    "HUNG_UP_EARLY_S",
    "LEGACY_TO_CURRENT",
    "OUTCOME_TAGS",
    "CallFacts",
    "derive_outcome",
    "hint_of",
    "normalise",
]

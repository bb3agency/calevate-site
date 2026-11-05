"""Find the moments an agent could not answer — deterministically, from redacted text.

WHY DETERMINISTIC AND NOT A MODEL PASS. This module follows `apps/workers/moments.py`'s
doctrine exactly, and for the same reason it states: "Asking a model to re-derive what a
string match can prove is how a feature acquires a hallucination surface it never needed."
A deflection is a thing the agent SAID — "I don't know", "the team will WhatsApp you" —
and recognising a said thing is a match, not a judgement. So detection reuses the pipeline
that already exists (the transcript the post-call pipeline persists) rather than inventing
a second LLM-calling mechanism, and it does NOT send a model anything: there is no new
provider call, no new residency question, and no new prompt to keep honest. If a model
pass is ever wanted for topic naming, it must run over redacted text through the SAME
`redact()` guard `run_assist` uses — never the raw turn — because of the rule below.

THE QUOTES ARE REDACTED, STRUCTURALLY. The one input is a list of `(speaker, text)` where
`text` is `transcript_turns.text_redacted`. This module never sees `turn.text`; the caller
(`service.record_call_gaps`, driven by the pipeline) hands over the redacted copy, so both
caller-facing quotes a gap carries are redacted by construction (hard rule 6). A phone
number a caller reads out is already masked before it can reach a `question_redacted`.

A GAP NEEDS A QUESTION (D-970). Every signal counts only after a caller line that asks for
something (`caller_asked`, which is `turn_checks.asks_question`: a "?", an English question
by its shape, or a whole question word from `call_words.json`), and never a request to hear
the last words again. On the Rytu Khata call of 4
Nov 2026 the caller agreed to try the app ("I will try."), the agent then gave the business's
WhatsApp number as its next line, and the WhatsApp match alone made the agreement an
unanswered question on the owner's list. Unanswered-question reports elsewhere work the same
way: a user's question the assistant had no answer for (fin.ai/help article 13975776).

WHAT IT DELIBERATELY CANNOT SEE, stated because an honest limit beats a false claim of
comprehension (the same disclosure `moments.py` and `extraction.OfflineExtractor` make):

- a question with no question word and no "?", which a Telugu yes/no question often is when
  the transcript drops the mark;
- a deflection with no preceding caller turn (the agent volunteering "I don't know" out of
  nowhere) — no question to anchor it, so it is not emitted;
- sarcasm, or an agent that says "I don't know" and then answers anyway in the same turn;
- a topic said only in words the keyword map does not carry — it still becomes a gap, but
  under a phrase-derived label rather than a canonical one, so two callers who phrase the
  same question differently may not aggregate.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from calevate_shared.call_words import say as _say
from calevate_shared.call_words import words as _words

from apps.api.agents.turn_checks import asks_question, asks_to_repeat
from apps.api.tenancy.business_copy import Capabilities

Signal = Literal["dont_know", "deferred_channel", "unanswered_question"]

#: How far back from an agent deflection we look for the caller's question. One turn is the
#: common case (caller asks, agent deflects); two covers a backchannel ("agent: one moment")
#: sitting between them. Wider than that and we start attributing a deflection to a question
#: from a different part of the call.
_LOOKBACK_TURNS: Final = 2

#: A speaker label the transcript uses. `TranscriptTurn.speaker` is exactly this `Literal`
#: (`calevate_shared.events.Speaker`), so a Protocol keeps this module coupled to no ORM.
Speaker = Literal["agent", "caller"]


class Turn(Protocol):
    @property
    def speaker(self) -> Speaker: ...

    @property
    def text(self) -> str: ...


# The agent SAYING it cannot answer. Word-bounded; the Indian-language forms ("I don't know",
# "can't say", "no idea" as callers' agents say them in Telugu and Hindi) are founder-owned
# data (`call_words.json`, `detection.dont_know`).
_DONT_KNOW_RE = re.compile(
    r"(?<!\w)(?:"
    r"i\s+(?:don'?t|do\s+not)\s+know|"
    r"i'?m\s+not\s+sure|i\s+am\s+not\s+sure|"
    r"i\s+don'?t\s+have\s+(?:that|the|any)|we\s+don'?t\s+have\s+that\s+(?:info|information)|"
    r"not\s+sure\s+about\s+(?:that|this)|" + _say("detection.dont_know") + r")(?!\w)",
    re.IGNORECASE,
)

# The agent PUNTING: the answer will come later from a person, the caller must go elsewhere
# to get it, or what could have been said is sent instead. NOT the agent sending a THING
# ("I'll send you the link on WhatsApp"): for a business whose answer is a link or a form,
# that is the answer, and on the Rytu Khata calls of 4 Nov 2026 the channel name alone made
# it a question the agent could not answer (L5-06). An "I don't know" beside the send is
# still `dont_know` above.
_DEFERRED_RE = re.compile(
    r"(?<!\w)(?:"
    r"(?:the\s+)?team\s+will\s+(?:call|get\s+back|reach|contact|send|whats\s?app)|"
    r"(?:have|get)\s+(?:someone|the\s+team|our\s+team)\s+(?:to\s+)?(?:call|contact|whats\s?app)|"
    r"someone\s+will\s+(?:call|contact|get\s+back)|"
    r"call\s+you\s+back|get\s+back\s+to\s+you|"
    # Sending what the agent could have SAID (a price, the details) is a punt; sending a
    # thing (a link, a form, a photo) is not, whatever channel carries it.
    r"(?:send|share|whats\s?app)\s+(?:you\s+)?(?:the\s+|our\s+|all\s+the\s+)?"
    r"(?:prices?|pricing|rates?|cost|details|information|info)\b|"
    r"(?:message|whats\s?app|call|contact|email|reach)\s+us\b|"
    r"(?:visit|check)\s+(?:our|the)\s+(?:website|page|office|shop)|" + _say("detection.later_by_a_person") + r")(?!\w)",
    re.IGNORECASE,
)

# A caller who asked to be called back or put through to a person gets "we'll call you back"
# as the answer, not as a punt.
_ASKED_FOR_A_PERSON_RE = re.compile(
    r"(?<!\w)(?:call\s+(?:me|back)|callback|ring\s+me|talk\s+to\s+(?:a|someone|the|your))(?!\w)",
    re.IGNORECASE,
)

# The agent STALLING on a direct question without answering or committing to a channel:
# "let me check", "I'll find out". Weaker than the two above and only counted when the
# caller actually asked something — otherwise "let me check your booking" is a normal turn.
_NONANSWER_RE = re.compile(
    r"(?<!\w)(?:"
    r"let\s+me\s+check|let\s+me\s+find\s+out|i'?ll\s+find\s+out|i\s+will\s+find\s+out|"
    r"i\s+need\s+to\s+check|i\s+have\s+to\s+check|" + _say("detection.stalls") + r")(?!\w)",
    re.IGNORECASE,
)

#: The canonical topics, most specific first: (topic_key, display label). The key aggregates
#: a topic across calls; the label is the owner's card. Each topic is offered to a business
#: only when its capability profile does not rule it out (`_TOPIC_NEEDS`), so a business that
#: sells nothing never sees "Refunds". The words that trigger a topic, English and Indian
#: languages alike, are founder-owned data (`detection.topic.<key>`). Order matters: "refund"
#: beats "payment", "delivery" beats "timing".
_TOPIC_NAMES: Final[tuple[tuple[str, str], ...]] = (
    ("pricing", "Pricing"),
    ("refund", "Refunds & returns"),
    ("warranty", "Warranty"),
    ("delivery", "Delivery"),
    ("timings", "Opening hours"),
    ("location", "Location & directions"),
    ("availability", "Availability & stock"),
    ("booking", "Bookings"),
    ("offers", "Offers & discounts"),
    ("payment", "Payment options"),
    ("documents", "Documents & eligibility"),
)
_TOPICS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = tuple(
    (key, label, _words(f"detection.topic.{key}")) for key, label in _TOPIC_NAMES
)

#: The canonical topics each capability stands behind. A business judged not to have the
#: capability (`Capabilities`, False only) does not get the topic: a free app's caller asking
#: "where do I find the khata?" is not asking for its address, and filing that under
#: "Location & directions" sent its owner to add an address it does not have. The question
#: still becomes a gap, in the caller's own words (`_topic`'s phrase fallback).
_TOPIC_NEEDS: Final[dict[str, tuple[str, ...]]] = {
    "pricing": ("quotes_prices",),
    "location": ("has_premises",),
    "timings": ("has_premises",),
    "booking": ("takes_bookings", "takes_orders"),
    "delivery": ("takes_orders",),
    "availability": ("sells", "takes_orders"),
    "offers": ("sells",),
    "refund": ("sells",),
    "warranty": ("sells",),
    "payment": ("sells",),
}


def withheld_topics(caps: Capabilities) -> frozenset[str]:
    """The canonical topics this business cannot be asked about, from its capability
    profile: a topic goes only when EVERY capability behind it is judged False (None keeps
    it, the unknown rule)."""
    return frozenset(
        topic
        for topic, needs in _TOPIC_NEEDS.items()
        if all(getattr(caps, need).applies is False for need in needs)
    )


_STOPWORDS: Final[frozenset[str]] = frozenset(_words("detection.stopwords"))
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RedactedTurn:
    """A transcript turn as the detector consumes it: a speaker and REDACTED text.

    A concrete `Turn` the post-call pipeline builds from `transcript_turns.text_redacted`,
    so the detector never has to touch the ORM and — the load-bearing half — never sees a
    raw turn. `text` is always the redacted copy (hard rule 6)."""

    speaker: Speaker
    text: str


@dataclass(frozen=True, slots=True)
class DetectedGap:
    """One (topic) the agent could not answer on this call, with the caller-facing quotes.

    `hit_count` is how many times the topic surfaced in THIS call — the detector merges
    repeats of one topic within a call and keeps the first pair of quotes as the example.
    Both quote fields are redacted (this module only ever receives redacted text).
    """

    topic_key: str
    topic_label: str
    question_redacted: str
    answer_redacted: str
    signal: Signal
    hit_count: int = 1


def caller_asked(caller_text: str) -> bool:
    """Whether a caller line asks for information, the only thing a gap can answer. A request
    to say it again asks for nothing new: the agent repeating its number then is no gap."""
    if asks_to_repeat(caller_text):
        return False
    return asks_question(caller_text)


def is_gap(caller_text: str, agent_text: str) -> Signal | None:
    """The gap signal of one caller line and the agent's reply to it, or None."""
    if not caller_asked(caller_text):
        return None
    signal = _classify(agent_text)
    if signal == "deferred_channel" and _ASKED_FOR_A_PERSON_RE.search(caller_text):
        return None
    return signal


def _classify(agent_text: str) -> Signal | None:
    """Which gap signal (if any) this agent turn carries, the caller having asked."""
    if _DONT_KNOW_RE.search(agent_text):
        return "dont_know"
    if _DEFERRED_RE.search(agent_text):
        return "deferred_channel"
    if _NONANSWER_RE.search(agent_text):
        return "unanswered_question"
    return None


def _topic(caller_text: str, agent_text: str, withheld: Collection[str] = ()) -> tuple[str, str]:
    """(topic_key, label) for a gap. Canonical if a keyword matches, else phrase-derived.

    Both texts are searched so a topic named in the agent's own deflection ("I don't have
    the PRICING") is caught even when the caller phrased it obliquely. A phrase fallback
    slugs up to three content words from the caller's question, so distinct questions form
    distinct topics while identical repeats still aggregate; a question that redacts down
    to nothing falls to a single honest bucket rather than a blank label.
    """
    haystack = f"{caller_text} {agent_text}".lower()
    for key, label, triggers in _TOPICS:
        if key in withheld:
            continue
        if any(_contains_word(haystack, trigger) for trigger in triggers):
            return key, label
    words = [w for w in _WORD_RE.findall(caller_text.lower()) if w not in _STOPWORDS and len(w) > 2]
    if not words:
        return "general", "General question"
    picked = words[:3]
    return "q_" + "_".join(picked), " ".join(picked).capitalize()


def topics_in(value: str, withheld: Collection[str] = ()) -> frozenset[str]:
    """Every canonical topic key (`_TOPICS`) whose triggers occur in `value`.

    Not `_topic`'s first-match: a fact or a caller's line can be about a price AND a
    delivery, and the known-facts chooser (`agents/hot_facts.py`) matches demand to facts on
    every topic both name, with the gap detector's own vocabulary so the two never disagree
    about what a topic is."""
    haystack = value.lower()
    return frozenset(
        key
        for key, _label, triggers in _TOPICS
        if key not in withheld and any(_contains_word(haystack, trigger) for trigger in triggers)
    )


def _contains_word(haystack: str, phrase: str) -> bool:
    """`phrase` as whole word(s) inside `haystack` — the same word-boundary discipline the
    extractor uses, so "cost" does not match inside "costume" and a two-word trigger like
    "how much" is matched as a unit."""
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?!\w)"
    return re.search(pattern, haystack) is not None


def detect_gaps(turns: Sequence[Turn], *, withheld: Collection[str] = ()) -> list[DetectedGap]:
    """The gaps in one call, one row per topic, in first-seen order.

    For each agent turn that carries a signal, the nearest preceding caller turn (within
    `_LOOKBACK_TURNS`) supplies the question and anchors the topic. A deflection with no
    caller turn behind it is skipped — see the module docstring's limits. `withheld` is
    `withheld_topics` of the business.
    """
    merged: dict[str, DetectedGap] = {}
    for i, turn in enumerate(turns):
        if turn.speaker != "agent":
            continue
        agent_text = turn.text.strip()
        if not agent_text:
            continue
        prev_caller = _nearest_caller(turns, i)
        if prev_caller is None:
            continue
        caller_text = prev_caller.strip()
        signal = is_gap(caller_text, agent_text)
        if signal is None:
            continue
        key, label = _topic(caller_text, agent_text, withheld)
        existing = merged.get(key)
        if existing is None:
            merged[key] = DetectedGap(
                topic_key=key,
                topic_label=label,
                question_redacted=caller_text,
                answer_redacted=agent_text,
                signal=signal,
            )
        else:
            # Same topic again this call: bump the count, keep the first example.
            merged[key] = DetectedGap(
                topic_key=existing.topic_key,
                topic_label=existing.topic_label,
                question_redacted=existing.question_redacted,
                answer_redacted=existing.answer_redacted,
                signal=existing.signal,
                hit_count=existing.hit_count + 1,
            )
    return list(merged.values())


def _nearest_caller(turns: Sequence[Turn], agent_idx: int) -> str | None:
    """The text of the closest caller turn in the `_LOOKBACK_TURNS` before `agent_idx`."""
    start = max(0, agent_idx - _LOOKBACK_TURNS)
    for j in range(agent_idx - 1, start - 1, -1):
        if turns[j].speaker == "caller" and turns[j].text.strip():
            return turns[j].text
    return None


__all__ = [
    "DetectedGap",
    "RedactedTurn",
    "Signal",
    "Turn",
    "caller_asked",
    "detect_gaps",
    "is_gap",
    "topics_in",
    "withheld_topics",
]

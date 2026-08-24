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

WHAT IT DELIBERATELY CANNOT SEE, stated because an honest limit beats a false claim of
comprehension (the same disclosure `moments.py` and `extraction.OfflineExtractor` make):

- a deflection with no preceding caller turn (the agent volunteering "I don't know" out of
  nowhere) — no question to anchor it, so it is not emitted;
- sarcasm, or an agent that says "I don't know" and then answers anyway in the same turn;
- a topic said only in words the keyword map does not carry — it still becomes a gap, but
  under a phrase-derived label rather than a canonical one, so two callers who phrase the
  same question differently may not aggregate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

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


# The agent SAYING it cannot answer. Word-bounded, code-mixed (English · Telugu · Hindi
# transliteration), because this product's calls are Telugu-first. These are the phrases an
# agent uses to state ignorance, not to hedge — "teliyadu" (don't know), "cheppalenu"
# (can't say), "idea ledu" (no idea).
_DONT_KNOW_RE = re.compile(
    r"(?<!\w)(?:"
    r"i\s+(?:don'?t|do\s+not)\s+know|"
    r"i'?m\s+not\s+sure|i\s+am\s+not\s+sure|"
    r"i\s+don'?t\s+have\s+(?:that|the|any)|we\s+don'?t\s+have\s+that\s+(?:info|information)|"
    r"not\s+sure\s+about\s+(?:that|this)|"
    r"teliyadu|teliyadhu|telidu|"  # "don't know"
    r"cheppalenu|cheppaledu|"  # "can't say"
    r"idea\s+ledu|"  # "no idea"
    r"naaku\s+teliyadu|maaku\s+teliyadu|"
    r"pata\s+nahi|nahi\s+pata|mujhe\s+nahi\s+pata"  # Hindi "don't know"
    r")(?!\w)",
    re.IGNORECASE,
)

# The agent PUNTING instead of answering: WhatsApp it, have a human call back, take a
# message. This is the Outpero signal verbatim — "didn't know this, offered to send it on
# WhatsApp or have the team call back".
_DEFERRED_RE = re.compile(
    r"(?<!\w)(?:"
    r"whats\s?app|"
    r"send\s+(?:you|it|the\s+details|the\s+information)|"
    r"share\s+(?:it|the\s+details)\s+(?:with\s+you|on)|"
    r"(?:the\s+)?team\s+will\s+(?:call|get\s+back|reach)|"
    r"(?:have|get)\s+(?:someone|the\s+team|our\s+team)\s+(?:call|to\s+call)|"
    r"call\s+you\s+back|get\s+back\s+to\s+you|"
    r"message\s+chestanu|message\s+chesta|"  # "I'll message you"
    r"team\s+call\s+chestaru|tarvata\s+call\s+chestam|"  # "team will call" / "we'll call later"
    r"pampistanu|pampista"  # "I'll send it"
    r")(?!\w)",
    re.IGNORECASE,
)

# The agent STALLING on a direct question without answering or committing to a channel:
# "let me check", "I'll find out". Weaker than the two above and only counted when the
# caller actually asked something — otherwise "let me check your booking" is a normal turn.
_NONANSWER_RE = re.compile(
    r"(?<!\w)(?:"
    r"let\s+me\s+check|let\s+me\s+find\s+out|i'?ll\s+find\s+out|i\s+will\s+find\s+out|"
    r"i\s+need\s+to\s+check|i\s+have\s+to\s+check|"
    r"chusi\s+cheptanu|kanukkoni\s+cheptanu"  # "I'll check and tell you"
    r")(?!\w)",
    re.IGNORECASE,
)

# Did the caller ASK something? A question mark is unreliable (STT rarely punctuates), so
# this leans on interrogatives in all three languages. "enta" (how much), "eppudu" (when),
# "ekkada" (where), "ela" (how), "unda/unదా" (is there).
_QUESTION_RE = re.compile(
    r"(?<!\w)(?:"
    r"what|when|where|how\s+much|how\s+many|how\s+do|do\s+you|can\s+you|is\s+there|are\s+there|"
    r"enta|entha|eppudu|ekkada|ela|emi\s+|em\s+|unda|undha|kavali|"
    r"kitna|kitne|kab|kahan|kaise"
    r")(?!\w)|\?",
    re.IGNORECASE,
)

# Canonical topics common to Indian SMB calls, most specific first. Each maps a set of
# word-bounded triggers (English · Telugu · Hindi) to (topic_key, display label). The key
# is what aggregates a topic across calls; the label is the client's product copy on the
# card. Order matters: "refund" beats "payment", "delivery" beats "timing".
_TOPICS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "pricing",
        "Pricing",
        (
            "price",
            "cost",
            "how much",
            "charges",
            "fee",
            "fees",
            "rate",
            "enta",
            "entha",
            "khareedu",
            "dhara",
            "kitna",
        ),
    ),
    (
        "refund",
        "Refunds & returns",
        ("refund", "return", "money back", "cancel", "cancellation", "wapas", "refund chestara"),
    ),
    ("warranty", "Warranty", ("warranty", "guarantee", "guarantee unda")),
    (
        "delivery",
        "Delivery",
        ("delivery", "deliver", "shipping", "ship", "courier", "delivery eppudu"),
    ),
    (
        "timings",
        "Opening hours",
        (
            "timing",
            "timings",
            "open",
            "opening",
            "hours",
            "close",
            "closing",
            "eppudu open",
            "time enni",
        ),
    ),
    (
        "location",
        "Location & directions",
        ("where", "location", "address", "directions", "ekkada", "kahan"),
    ),
    (
        "availability",
        "Availability & stock",
        ("available", "availability", "in stock", "stock", "unda", "undha", "dorukutunda"),
    ),
    (
        "booking",
        "Booking & appointments",
        ("book", "booking", "appointment", "slot", "reserve", "book chey", "appointment kavali"),
    ),
    (
        "offers",
        "Offers & discounts",
        ("offer", "offers", "discount", "deal", "coupon", "scheme", "offer unda"),
    ),
    (
        "payment",
        "Payment options",
        ("payment", "pay", "upi", "card", "emi", "installment", "cash", "chelinchu"),
    ),
    (
        "documents",
        "Documents & eligibility",
        ("document", "documents", "eligibility", "kyc", "proof", "papers"),
    ),
)

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "do",
        "does",
        "you",
        "your",
        "i",
        "we",
        "me",
        "my",
        "to",
        "of",
        "for",
        "and",
        "or",
        "can",
        "could",
        "would",
        "will",
        "please",
        "tell",
        "know",
        "want",
        "what",
        "when",
        "where",
        "how",
        "much",
        "many",
        "there",
        "this",
        "that",
        "about",
        "any",
        "get",
        "have",
        "need",
        "hi",
        "hello",
        "sir",
        "madam",
        "andi",
        "garu",
        "naaku",
        "meeku",
        "enta",
        "entha",
        "eppudu",
        "ekkada",
        "ela",
        "kavali",
        "unda",
        "undha",
    }
)
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


def _classify(agent_text: str, caller_asked: bool) -> Signal | None:
    """Which gap signal (if any) this agent turn carries.

    `dont_know` and `deferred_channel` stand on their own — an agent that says it doesn't
    know, or offers WhatsApp, is a gap whether or not we caught the question. `nonanswer`
    is counted ONLY when the caller actually asked, because "let me check" is an ordinary
    thing to say while looking something up and is a gap only against an open question.
    """
    if _DONT_KNOW_RE.search(agent_text):
        return "dont_know"
    if _DEFERRED_RE.search(agent_text):
        return "deferred_channel"
    if caller_asked and _NONANSWER_RE.search(agent_text):
        return "unanswered_question"
    return None


def _topic(caller_text: str, agent_text: str) -> tuple[str, str]:
    """(topic_key, label) for a gap. Canonical if a keyword matches, else phrase-derived.

    Both texts are searched so a topic named in the agent's own deflection ("I don't have
    the PRICING") is caught even when the caller phrased it obliquely. A phrase fallback
    slugs up to three content words from the caller's question, so distinct questions form
    distinct topics while identical repeats still aggregate; a question that redacts down
    to nothing falls to a single honest bucket rather than a blank label.
    """
    haystack = f"{caller_text} {agent_text}".lower()
    for key, label, triggers in _TOPICS:
        if any(_contains_word(haystack, trigger) for trigger in triggers):
            return key, label
    words = [w for w in _WORD_RE.findall(caller_text.lower()) if w not in _STOPWORDS and len(w) > 2]
    if not words:
        return "general", "General question"
    picked = words[:3]
    return "q_" + "_".join(picked), " ".join(picked).capitalize()


def _contains_word(haystack: str, phrase: str) -> bool:
    """`phrase` as whole word(s) inside `haystack` — the same word-boundary discipline the
    extractor uses, so "cost" does not match inside "costume" and a two-word trigger like
    "how much" is matched as a unit."""
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?!\w)"
    return re.search(pattern, haystack) is not None


def detect_gaps(turns: Sequence[Turn]) -> list[DetectedGap]:
    """The gaps in one call, one row per topic, in first-seen order.

    For each agent turn that carries a signal, the nearest preceding caller turn (within
    `_LOOKBACK_TURNS`) supplies the question and anchors the topic. A deflection with no
    caller turn behind it is skipped — see the module docstring's limits.
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
        signal = _classify(agent_text, _QUESTION_RE.search(caller_text) is not None)
        if signal is None:
            continue
        key, label = _topic(caller_text, agent_text)
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


__all__ = ["DetectedGap", "RedactedTurn", "Signal", "Turn", "detect_gaps"]

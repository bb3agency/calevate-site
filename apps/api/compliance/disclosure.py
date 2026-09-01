"""The two notices an agent may open with, and whether one was SPOKEN — hard rule 5.

TWO HALVES, ONE MODULE (D-163). What an agent is configured to SAY at the start of a
call, and whether it was OBSERVED saying it, are the two ends of the same obligation, and
splitting them across modules is how the seed's bundled Telugu line survived as long as
it did — nobody owned the sentence, so nobody noticed it was two sentences.

- **The copy half** — the two template tables an agent is born with, and the
  client-facing wording of what the toggles do NOT do.
- **The evidence half** (`disclosure_spoken`) scores a finished call's transcript.

The RULE that turns a posture into a spoken opening is one step further out, in
`calevate_shared.engine.compose_opening_line`, beside the `AgentConfig.opening_line`
field it produces and the prompt composer that consumes it — that module's docstring
argues the seam. Product copy here, contract there.

WHAT D-163 CHANGED, because the docstring below still argues the old rule in places.
SEC-COMP §2 states two invariants — AI disclosure and recording notice — and they shared
ONE column (`agents.disclosure_line`, seeded `"…idi {business} AI assistant. Ee call
record avutundi."`). They are different obligations under different regimes (TRAI/UCC vs
DPDP notice-and-consent), and the founder's decision is that BOTH are per-agent toggles
on inbound and outbound alike. What is NOT toggleable, and is enforced where no client
can reach it, is the ANSWER to a caller who asks outright: see
`calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE`.

--------------------------------------------------------------------------------
THE EVIDENCE HALF
--------------------------------------------------------------------------------

`calls.disclosure_played` has existed since the first migration (`05bba2f3c19c`). It is
rendered on the client's call detail screen (`DisclosureNotice`) and on the weekly QA
compliance-review queue (`quality/sampling.py`), where a reviewer working OPERATIONS §5's
*"disclosure spoken"* scenario reads it as the evidence.

**Nothing in this repository ever wrote it** (P3.3). Every one of those surfaces rendered
a permanently null column, which the screens correctly showed as "unknown" — so the
product asked a reviewer to certify a property it had never measured, on every call, and
the only real control was a one-off manual check before launch. IT Act / Sanjay Pandey
exposure (SEC-COMP §1) rested on that check.

WHY A SEPARATE MODULE RATHER THAN A FUNCTION IN THE WORKER. Two callers, and the second
one is the reason the first must not own it: the pipeline writes the column, and the
red-team eval harness scores the same property over fixture transcripts. `optout.py` is
split for exactly this reason and this follows it rather than inventing a second shape.

--------------------------------------------------------------------------------
WHAT THIS MEASURES, AND WHAT IT DOES NOT
--------------------------------------------------------------------------------

It answers *"did the agent say the disclosure line on this call?"* — no more. Three
properties nearby that it deliberately does NOT claim:

* **NOT "said it first".** That is the greeting field's job and it is verified at PUBLISH
  time, against the engine, by `agents/verification.judge` reading
  `AgentSnapshot.greeting` — the engine's `agent_welcome_message` / `introduction`, which
  is the deterministic first utterance. A transcript cannot distinguish "the greeting
  played" from "the model happened to say it in turn 4", and pretending otherwise here
  would put a second, weaker answer beside the strong one (P3.3's own defect class).
* **NOT a legal certification.** It is a string match over an engine's transcript. What it
  produces is EVIDENCE a human reviewer reads, which is precisely what the QA queue was
  built to hold.
* **NOT a gate.** Nothing blocks on it. A call is already over by the time this runs.

FAILING DIRECTION, CHOSEN DELIBERATELY. The match is strict containment after
normalisation, so it errs towards `False` — it will report "not spoken" for a disclosure
the engine rendered with different words. That is the safe direction for a compliance
signal: a false negative sends a reviewer to listen to a recording that turns out fine,
and a false positive certifies a call nobody checked. `_EVIDENCE` in `optout.py` argues
the same trade the other way round for the same reason — there, recall protects a
caller's request; here, precision protects a client's licence.

WHY NOT FUZZY MATCHING. A similarity threshold would be a number nobody could defend to a
regulator ("how similar is compliant?") and would move every verdict on every tuning. The
disclosure line is a SHORT fixed string the tenant themselves authored, sent to the engine
verbatim as the greeting; if it does not come back the honest answer is that we did not
observe it.

HARD RULE 6. Nothing here logs or returns transcript text. The answer is one tri-state.
"""

from __future__ import annotations

from collections.abc import Sequence

from apps.api.compliance.optout import SpokenTurn, normalize_utterance

__all__ = [
    "AI_DISCLOSURE_TEMPLATES",
    "DEFAULT_LANGUAGE",
    "RECORDING_NOTICE_TEMPLATES",
    "TRUTHFUL_ANSWER_PROMISE",
    "ai_disclosure_for",
    "bundled_disclosure_line",
    "disclosure_spoken",
    "recording_notice_for",
]

#: `TRUTHFUL_ANSWER_DIRECTIVE` said to a business owner instead of to a model (D-163).
#:
#: Composed HERE and returned by the API rather than written into a screen, for the reason
#: `publishing.PRECEDENCE_RULE` is: this sentence is the boundary of what the two toggles
#: below do, and a client-facing surface that paraphrased it could promise the opposite of
#: what the platform enforces. One wording, served, everywhere it is shown.
TRUTHFUL_ANSWER_PROMISE = (
    "Whatever these settings say, the agent always answers honestly when a caller asks. "
    '"Am I speaking to a person?" is answered "I am an AI assistant", and "is this call '
    'being recorded?" is answered yes. This cannot be switched off and no script can '
    "override it."
)

#: The language every template table falls back to. Telugu is the product default (D-36)
#: but English is the FALLBACK, because a template rendered in a language the business
#: does not speak is worse than one rendered in the lingua franca.
DEFAULT_LANGUAGE = "en-IN"

#: Sentence one: **"you are talking to an AI"** — the TRAI/UCC-side obligation.
#:
#: Split out of `admin/service.DISCLOSURE_TEMPLATES`, which bundled it with the recording
#: notice in one string. That bundling is why the two invariants SEC-COMP §2 states
#: separately could only ever be switched on and off together: there was one column, so
#: there was one answer.
AI_DISCLOSURE_TEMPLATES: dict[str, str] = {
    "te-IN": "Namaskaram, idi {business} AI assistant.",
    "hi-IN": "Namaste, main {business} ka AI assistant hoon.",
    "en-IN": "Hello, this is the AI assistant for {business}.",
}

#: Sentence two: **"this call is recorded"** — the DPDP notice-and-consent side, and a
#: different regime from the sentence above. Deliberately business-agnostic: it takes no
#: `{business}` placeholder, because the AI sentence has already named the caller's
#: counterparty and a second naming reads as a script that lost its place.
RECORDING_NOTICE_TEMPLATES: dict[str, str] = {
    "te-IN": "Ee call record avutundi.",
    "hi-IN": "Yeh call record ho rahi hai.",
    "en-IN": "This call is being recorded.",
}


#: Sentence three: **"the agent remembers you between calls"** (D-507).
#:
#: A THIRD OBLIGATION, and not a third TOGGLE. The two above are switchable because they
#: are true of every call whatever this product is configured to do — the call IS AI, the
#: call IS recorded — so a client who gives the notice in writing instead may switch off
#: the spoken form. This one is different in kind: cross-call memory exists ONLY because
#: `agents.caller_memory_enabled` is on, which is a choice this system records, so the
#: sentence is bound to that switch instead of getting one of its own. There is no state
#: in which an agent remembers a caller and does not say so.
#:
#: WHY SPOKEN AT ALL, when `compliance/caller_notice.py` already puts it in the client's
#: written draft: an INBOUND caller has visited no website and agreed to no page. The
#: written notice reaches the people who came through the client's own funnel, and inbound
#: is the product. A notice that misses the caller it is about is not a notice.
#:
#: Business-agnostic like the recording sentence, and for its reason: the AI sentence has
#: already named the caller's counterparty.
#:
#: Deliberately says WHAT is kept and FOR ROUGHLY HOW LONG in the caller's own vocabulary
#: — "a short note", not "a distilled fact", and never "an embedding". The period is not
#: interpolated from `retention_policies`: a spoken sentence that changed when a client
#: edited a slider would make the agent's opening a moving target nobody reviewed, and the
#: 180-day ceiling below is a platform maximum rather than a tenant setting.
CALLER_MEMORY_NOTICE_TEMPLATES: dict[str, str] = {
    "te-IN": "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu.",
    "hi-IN": "Aapne kya poocha, uska ek chhota note main yaad rakhta hoon.",
    "en-IN": "I keep a short note of what you ask about, so I remember it if you call again.",
}


def _rendered(templates: dict[str, str], language: str, business: str) -> str:
    template = templates.get(language, templates[DEFAULT_LANGUAGE])
    return template.format(business=business) if "{business}" in template else template


def ai_disclosure_for(*, language: str, business: str) -> str:
    """The AI sentence a NEW agent starts with. Always non-empty."""
    return _rendered(AI_DISCLOSURE_TEMPLATES, language, business)


def recording_notice_for(*, language: str) -> str:
    """The recording sentence a NEW agent starts with. Always non-empty."""
    return _rendered(RECORDING_NOTICE_TEMPLATES, language, business="")


def caller_memory_notice_for(*, language: str) -> str:
    """The memory sentence a NEW agent starts with. Always non-empty, whether or not the
    agent's memory switch is on — the same rule `ai_disclosure_for` follows: the sentence
    is mandatory ON FILE so that turning the switch on can never be the moment somebody
    discovers there is nothing to say."""
    return _rendered(CALLER_MEMORY_NOTICE_TEMPLATES, language, business="")


def bundled_disclosure_line(*, ai_disclosure_line: str, recording_notice_line: str) -> str:
    """The LEGACY `agents.disclosure_line` value — both sentences, whatever the toggles.

    STEP 1 OF A TWO-STEP DEPRECATION (hard rule 8: never drop in the release that stops
    writing). The column is still NOT NULL with a non-empty CHECK and is still written by
    every writer of the two sentences, so a reader that has not migrated — the admin
    console's roster, an operator's ad-hoc SQL — keeps getting a sensible sentence.

    IGNORING THE TOGGLES IS WHAT MAKES IT SAFE, and it is the whole reason this is not
    `compose_opening_line`. The column's CHECK forbids an empty value, so it cannot hold
    the composed opening (which may legitimately be empty), and a column that silently
    held "the opening, unless the opening is empty, in which case the old one" would be a
    third meaning nobody could name. It holds the two sentences an agent HAS. What it is
    not, since D-163, is a statement about what is SPOKEN — that is `opening_line`, and
    step 2 (dropping this column) is named in D-163.

    Two strings rather than a `DisclosurePosture`, because both of its callers have the
    sentences and neither has (or should consult) the switches: the onboarding templates,
    and the experiment promotion that makes an arm's AI sentence the agent's.
    """
    parts = [ai_disclosure_line.strip(), recording_notice_line.strip()]
    return " ".join(part for part in parts if part)


def disclosure_spoken(turns: Sequence[SpokenTurn], *, disclosure_line: str) -> bool | None:
    """`True` spoken · `False` not observed · `None` nothing to judge.

    THE TRI-STATE IS THE `AgentSnapshot.*_readable` DOCTRINE, arriving at the same answer
    from the other end of the system: "we looked and it was not there" and "there was
    nothing to look at" are different facts, and only the first is a finding. A call with
    no transcript (the engine returned none, or the caller hung up before a word) yields
    `None`, and the column keeps the NULL the screens already render as "unknown" —
    rather than a `False` that reads, to a reviewer and to a client, as a breach.

    AGENT TURNS ONLY. The disclosure is ours to speak; a caller reading it back, or an
    STT pass attributing our own audio to the caller channel, must not be able to satisfy
    it. That is the same rule `detect_opt_out` applies in mirror image — it reads CALLER
    turns only, so a prompt regression cannot suppress a client's list by having the
    agent say the words.

    ANY AGENT TURN, not the first. Engines legitimately emit a short filler or
    connection-noise turn ahead of the welcome message, and requiring index 0 would
    report a compliance breach on a call where the line was played exactly as configured.
    "First" is verified at publish against the engine's greeting field, where it can be
    verified properly (module docstring).
    """
    needle = normalize_utterance(disclosure_line)
    if not needle:
        # THIS IS NOW A REACHABLE, INTENDED STATE (D-163), where it used to be a
        # defensive branch: the pipeline passes the AI sentence only when the agent's
        # `ai_disclosure_enabled` toggle is on, and the empty string otherwise. An agent
        # that was never asked to volunteer the sentence has nothing to be scored against
        # — which is precisely the `None` this tri-state already means, and precisely
        # what stops the QA queue rendering a lawful choice as a red `False` on every
        # call. Independent of the toggle, "the empty string is in every transcript"
        # would certify every call ever, so the guard is load-bearing both ways.
        return None
    spoken = [
        normalized
        for turn in turns
        if turn.speaker != "caller" and (normalized := normalize_utterance(turn.text))
    ]
    if not spoken:
        return None
    return any(needle in line for line in spoken)

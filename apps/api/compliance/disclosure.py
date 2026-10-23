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
from typing import Final, Literal

from calevate_shared.languages import get_language

from apps.api.compliance.optout import SpokenTurn, normalize_utterance

__all__ = [
    "AI_DISCLOSURE_TEMPLATES",
    "DEFAULT_LANGUAGE",
    "HINDI_PROGRESSIVE",
    "RECORDING_NOTICE_TEMPLATES",
    "TRUTHFUL_ANSWER_PROMISE",
    "VoiceGender",
    "ai_disclosure_for",
    "bundled_disclosure_line",
    "disclosure_spoken",
    "is_default_ai_disclosure",
    "recording_notice_for",
    "truthful_answer_promise",
]

_NOT_RECORDED_ANSWER = (
    "is answered that the audio is not recorded and that a written transcript of the "
    "conversation is kept, which the business can read"
)


def truthful_answer_promise(*, call_is_recorded: bool) -> str:
    """`truthful_answer_directive` said to a business owner instead of to a model (D-163).

    Composed HERE and returned by the API rather than written into a screen, for the reason
    `publishing.PRECEDENCE_RULE` is: this sentence is the boundary of what the two toggles
    do, and a client-facing surface that paraphrased it could promise the opposite of what
    the platform enforces. One wording, served, everywhere it is shown.

    `call_is_recorded` is the engine's fact (`EngineCapabilities.records_audio`) and must be
    the same one the agent's floor was composed from, so the business is told exactly the
    answer its callers get. The not-recorded wording says both halves for the floor's
    reason: no audio recording, but a written transcript the business can read — "no"
    alone would tell the owner nothing is kept, which is false.
    """
    recording_answer = "is answered yes" if call_is_recorded else _NOT_RECORDED_ANSWER
    return (
        "Whatever these settings say, the agent always answers honestly when a caller asks. "
        '"Am I speaking to a person?" is answered "I am an AI assistant", and "is this call '
        f'being recorded?" {recording_answer}. This cannot be switched off and no script can '
        "override it."
    )


#: The recorded variant, kept as a name for the readers that compare against "the promise"
#: on an engine that records audio — exactly as `TRUTHFUL_ANSWER_DIRECTIVE` is kept beside
#: its function. A surface that SERVES the promise composes it from the engine's fact.
TRUTHFUL_ANSWER_PROMISE = truthful_answer_promise(call_is_recorded=True)

#: The language every template table falls back to. Telugu is the product default (D-36)
#: but English is the FALLBACK, because a template rendered in a language the business
#: does not speak is worse than one rendered in the lingua franca.
#:
#: The TAG is read off the one declaration rather than typed: this constant answers WHICH
#: language, and `calevate_shared.languages` answers how that language is spelled. The
#: import is safe from anywhere in this tree — `calevate_shared` imports no app code (the
#: first import-linter contract), so it closes none of the cycles this module sits inside.
DEFAULT_LANGUAGE = get_language("english_india").bcp47

#: Sentence one: **"you are talking to an AI"** — the TRAI/UCC-side obligation.
#:
#: A string of its own, never bundled with the recording notice: the two invariants SEC-COMP
#: §2 states separately can only be switched separately if they are separate strings
#: (D-163).
#:
#: IN THE LANGUAGE'S OWN LETTERS, EVERY WORD (D-745, then D-861): a Telugu or Hindi sentence
#: in Latin letters is read by the voice as if it were English, and since 23 Oct 2026 the
#: English words people use (ఏఐ అసిస్టెంట్, కాల్, రికార్డ్, నోట్) are written in Telugu or
#: Devanagari letters too, as every spoken line is (`calevate_shared.spoken_style`). The
#: Telugu and Hindi lines NEED NATIVE-SPEAKER REVIEW; the staged languages keep the English
#: words in Latin letters until the founder rules on them. The Hindi memory sentence says
#: "we" so it assumes no gender.
#:
#: NO GREETING WORD IN IT (D-708): a "Namaskaram," here made the notice read as the greeting
#: and the agent say hello twice. The salutation is the composer's
#: (`calevate_shared.engine.INTRODUCTION_SALUTATIONS`).
#:
#: TELUGU AND HINDI INTRODUCE THE AGENT (D-865, founder, 23 Oct 2026, the founder's own
#: wording): "I am {name} from {business}, an AI assistant, speaking". Said after the
#: salutation and BEFORE the opening line, which then says only why the call is made
#: (`engine.join_first_words`). `{name}` and `{business}` are the stored names, in English
#: letters until spoken names exist (D-861's open item). Hindi's verb follows the voice's
#: gender (`HINDI_PROGRESSIVE`). Both lines NEED NATIVE-SPEAKER REVIEW. The other languages
#: keep a sentence without the agent's name and D-861's order (the opening line first); the
#: founder has worded no introduction for them.
AI_DISCLOSURE_TEMPLATES: dict[str, str] = {
    # The ‌ (zero-width non-joiner) keeps "ట్" and "ని" apart as the founder wrote them.
    "te-IN": "నేను {business} నుండి {name}ని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి.",
    "hi-IN": "मैं {business} से {name}, एआई असिस्टेंट, बात कर {progressive} हूँ।",
    "en-IN": "This is the AI assistant for {business}.",
    # Staged (D-855), drafted 23 Oct 2026: NEEDS NATIVE-SPEAKER REVIEW. No caller hears
    # these until `agents/languages.STAGED_LANGUAGE_READINESS` records the review.
    "ta-IN": "இது {business} AI assistant.",
    "kn-IN": "ಇದು {business} AI assistant.",
    "ml-IN": "ഇത് {business} AI assistant ആണ്.",
    "mr-IN": "हा {business} AI assistant आहे.",
}

#: Sentence two: **"this call is recorded"** — the DPDP notice-and-consent side, and a
#: different regime from the sentence above. Deliberately business-agnostic: it takes no
#: `{business}` placeholder, because the AI sentence has already named the caller's
#: counterparty and a second naming reads as a script that lost its place.
RECORDING_NOTICE_TEMPLATES: dict[str, str] = {
    "te-IN": "ఈ కాల్ రికార్డ్ అవుతుంది.",
    "hi-IN": "यह कॉल रिकॉर्ड हो रही है।",
    "en-IN": "This call is being recorded.",
    # Staged (D-855), drafted 23 Oct 2026: NEEDS NATIVE-SPEAKER REVIEW. No caller hears
    # these until `agents/languages.STAGED_LANGUAGE_READINESS` records the review.
    "ta-IN": "இந்த call record ஆகிறது.",
    "kn-IN": "ಈ call record ಆಗುತ್ತಿದೆ.",
    "ml-IN": "ഈ call record ചെയ്യുന്നുണ്ട്.",
    "mr-IN": "हा call record होत आहे.",
}


#: Sentence three: **"the agent remembers you between calls"** (D-507).
#:
#: A THIRD OBLIGATION, and not a third TOGGLE. The two above are switchable because they
#: follow from facts no agent setting creates — the call IS AI, and whether it is recorded
#: is the engine's fact — so a client who gives the notice in writing instead may switch
#: off the spoken form. This one is different in kind: cross-call memory exists ONLY because
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
#: SAID WITH THE GOODBYE, NOT IN THE OPENING (D-865, founder, 23 Oct 2026): the prompt tells
#: the agent to say it once as it closes a call that ends normally
#: (`calevate_shared.engine.memory_goodbye_rule`); the engine's 200-character first turn had
#: no room for it beside a Telugu introduction and the recording notice.
#:
#: Deliberately says WHAT is kept and FOR ROUGHLY HOW LONG in the caller's own vocabulary
#: — "a short note", not "a distilled fact", and never "an embedding". The period is not
#: interpolated from `retention_policies`: a spoken sentence that changed when a client
#: edited a slider would make the agent's opening a moving target nobody reviewed, and the
#: 180-day ceiling below is a platform maximum rather than a tenant setting.
#:
#: WORDED AS WHY, THEN WHAT (D-861): "so I remember it when you call again, I keep a short
#: note about this call". The founder's Telugu, 23 Oct 2026, replacing "I'll remember a short
#: note about what you asked", with which a trial call opened before any greeting. Every
#: line is NEEDS NATIVE-SPEAKER REVIEW (the founder reviews te-IN; the others are drafted to
#: the same meaning), and the staged ones are heard by no caller until
#: `agents/languages.STAGED_LANGUAGE_READINESS` records the review.
CALLER_MEMORY_NOTICE_TEMPLATES: dict[str, str] = {
    "te-IN": "మీరు మళ్ళీ కాల్ చేసినప్పుడు గుర్తుండేలా, ఈ కాల్ గురించి ఒక చిన్న నోట్ ఉంచుకుంటాను.",
    "hi-IN": "आप दोबारा कॉल करें तो याद रहे, इसलिए हम इस कॉल का एक छोटा नोट रखते हैं।",
    "en-IN": "So I remember it when you call again, I keep a short note about this call.",
    "ta-IN": (
        "நீங்கள் மீண்டும் call செய்யும்போது நினைவில் இருக்க, இந்த call பற்றி ஒரு சின்ன note வைத்துக்கொள்கிறேன்."
    ),
    "kn-IN": "ನೀವು ಮತ್ತೆ call ಮಾಡಿದಾಗ ನೆನಪಿರಲಿ ಎಂದು, ಈ call ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ note ಇಟ್ಟುಕೊಳ್ಳುತ್ತೇನೆ.",
    "ml-IN": ("നിങ്ങൾ വീണ്ടും call ചെയ്യുമ്പോൾ ഓർമ്മയുണ്ടാകാൻ, ഈ call പറ്റി ഒരു ചെറിയ note ഞാൻ സൂക്ഷിക്കും."),
    "mr-IN": "तुम्ही पुन्हा call केल्यावर लक्षात राहावे म्हणून, या call ची एक छोटी note आम्ही ठेवतो.",
}


VoiceGender = Literal["female", "male"]

#: Hindi's present continuous agrees with the speaker: "बात कर रही हूँ" said by a woman, "बात कर
#: रहा हूँ" by a man. The voice is the speaker the caller hears, so its catalogue gender decides
#: (`agents/voice_pick.voice_gender`); unknown takes the woman's form, the first run's default
#: voice (`agents/voice_pick`, D-855).
HINDI_PROGRESSIVE: Final[dict[VoiceGender, str]] = {"female": "रही", "male": "रहा"}


def _rendered(
    templates: dict[str, str],
    language: str,
    business: str,
    *,
    name: str = "",
    gender: VoiceGender | None = None,
) -> str:
    template = templates.get(language, templates[DEFAULT_LANGUAGE])
    if "{" not in template:
        return template
    return template.format(
        business=business, name=name, progressive=HINDI_PROGRESSIVE[gender or "female"]
    )


def ai_disclosure_for(
    *, language: str, business: str, name: str, gender: VoiceGender | None = None
) -> str:
    """The AI sentence a NEW agent starts with, for an agent called `name` whose voice is of
    `gender` (None: not known). Always non-empty."""
    return _rendered(AI_DISCLOSURE_TEMPLATES, language, business, name=name, gender=gender)


def is_default_ai_disclosure(line: str, *, language: str, business: str, name: str) -> bool:
    """Is `line` the default AI sentence for this agent, in either voice gender? Such a line
    is ours to re-render when the agent's name, voice or language changes; any other line was
    written by a person and is left alone."""
    clean = line.strip()
    return any(
        clean == ai_disclosure_for(language=language, business=business, name=name, gender=g)
        for g in (None, "female", "male")
    )


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

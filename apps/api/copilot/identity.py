"""Who the assistant says it is — as a PROPERTY OF THIS SERVICE rather than a request to a
model.

═══ THE DEFECT THIS EXISTS FOR, AND WHY THE PROMPT FIX WAS NOT THE END OF IT. ═══

`prompt.ASSISTANT_IDENTITY` tells the model to name the product, affirm that it is an AI,
decline to name the vendor and point at `/legal/subprocessors`. That shipped, and the
founder then tested it against a live dashboard:

    "who are you?"            → "I am the Calevate assistant."                  ✅
    "what ai model are you?"  → "I am a large language model, trained by Google." ❌
    "are you a google model?" → "I am a large language model, trained by Google." ❌

So the instruction holds for the open-ended question and loses to the direct one. That is
not a wording bug to iterate on; it is the ceiling of the control's SHAPE. A prompt is a
request to a model, and Google's own guidance for the leg the leak came from says so in as
many words — *"system instructions can help guide the model to follow instructions, but
they do not fully prevent jailbreaks or leaks"* (google-gemini/cookbook,
`quickstarts/System_instructions.ipynb` @ main, read 2 Sep 2026). OWASP's 2025 LLM Top 10
gives the same answer at the level of design: LLM02 (Sensitive Information Disclosure)
lists *"Limit the model's access to sensitive data"* and system-level filtering as the
mitigations, and LLM01 states plainly that *"prompt injection vulnerabilities are possible
due to the nature of generative AI … prompt-based approaches [do not] provide guaranteed
prevention"*, recommending instead controls *"outside the model itself"*
(https://genai.owasp.org/llmrisk/llm01-prompt-injection/ and
https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/, read
2 Sep 2026). So the prompt STAYS — it is what makes the ordinary answer right — and it is
backed here by two controls that do not ask the model for anything.

WHY IT MATTERS BEYOND TIDINESS, restated so the next reader does not soften it: which
provider Calevate buys language models from is commercial and contractual (clients bring
no BYOK; the accounts are the founder's), the client-facing disclosure of sub-processors
is a VERSIONED legal document at `/legal/subprocessors`, and the improvised answer can
also be simply FALSE — three legs are declared (`azure_openai`, `openai`, `google`) and
which one serves an account depends on its configured model, so a sentence naming one
vendor is wrong for every tenant on another.

═══ THE TWO CONTROLS. BRACES, THEN BELT. ═══

1. `identity_answer(question)` — ANSWER IT OURSELVES. A question that is asking what the
   assistant IS is answered from `CANONICAL_IDENTITY_ANSWER` with no provider round trip
   at all: instant, free, and not arguable with. On its own it is brittle to phrasing,
   which is why it is not on its own.
2. `IdentityEgress` — AN EGRESS GUARD ON THE ANSWER TEXT. If what the model emits names a
   model vendor while asserting something about ITSELF, that text does not reach the
   client. It catches phrasings nobody predicted, including the two above, in whatever
   language the classifier missed.

═══ WHAT IS **NOT** ALLOWED: EVASION ABOUT BEING AN AI. ═══

Hard rule 5's floor is a VOICE rule and this is the dashboard, but no surface of this
product is taught to be coy: `calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE` and
`compliance/disclosure.TRUTHFUL_ANSWER_PROMISE` are the wording the voice leg is held to,
and the substitution below is written to satisfy the same shape — NAME THE PRODUCT, AFFIRM
THE AI, DECLINE THE VENDOR, SAY WHERE IT IS PUBLISHED. "I cannot tell you which model I
am" is a legitimate answer here. "I am not an AI" is a hard-rule-5 violation, and nothing
in this module can produce one: the substituted sentence affirms it, and the guard only
ever fires on text that named a vendor.

═══ THE SCOPING BOUNDARY, WHICH IS THE WHOLE DESIGN QUESTION. ═══

The naive guard — "the answer must not contain the word Google" — is wrong and would be
switched off within a week. A client's own data legitimately contains these words: a lead
who asked about Google Ads, a campaign named "Microsoft partners", a knowledge-base
article about an Azure integration. Those reach an answer through `tools.py` and the
person is entitled to read them back.

So the subject of this guard is not a WORD, it is an ASSERTION: **what the assistant says
about ITSELF.** A span is caught when, inside ONE SENTENCE, a self-identity assertion
(`_IDENTITY_MARKERS` — "I am a …model", "trained by", "my creator", "I run on") occurs
together with a model-vendor name (`VENDOR_WORDS`). "I found 3 leads who asked about
Google Ads" has the name and no assertion, and passes. "I am a large language model,
trained by Google" has both, and does not. The sentence is the unit because it is the
smallest span over which "about itself" is even definable — a rule scoped to the whole
answer would catch the lead, and one scoped to a token cannot see the subject at all.

The one place that boundary is deliberately widened is `strict`: when the QUESTION was
itself about the assistant's model, every vendor name in the answer is a leak, because
there is no other thing the answer could be about. `question_touches_model_identity` is
what turns it on, and it is the answer to the language problem below.

SARVAM IS DELIBERATELY NOT A BANNED NAME, and the exception is the point — D-127 G-6
requires a substituted answer to say who wrote it, and
`workers/extraction._FALLBACK_DISCLOSURE` therefore names Sarvam in the client's own
words. That is a disclosure this product DECIDED to make, in a place it can be reviewed.
Banning the name would delete a compliance sentence to satisfy a guard aimed at a
different problem, which is the shape of every weakened invariant.

═══ WHAT THIS CANNOT DO, SAID PLAINLY. ═══

`_IDENTITY_MARKERS` is English. An answer that asserts its origin in Telugu or Hindi is
caught by `strict` (the question was about identity) and by the vendor-name aliases below,
and is NOT caught by the sentence rule when the person asked about something else
entirely. That residue is real and is not closed here; the prompt and control 1 are what
stand in front of it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

#: The names the assistant may never call itself by. LANGUAGE-MODEL VENDORS AND THEIR
#: MODEL FAMILIES — every provider this product has ever routed a language request
#: through, live leg or not, because "trained by X" reads exactly as authoritatively for a
#: retired vendor as for a current one. `gpt` and `claude` are here because the leak came
#: out as a MODEL FAMILY rather than as a company; `microsoft` because that is how the
#: Azure leg is named in the sub-processor register.
#:
#: THIS IS THE ONE LIST. `tests/assistant_vendor_identity_test.py` imports it rather than
#: keeping a second copy — two spellings of one ban is how the two drift apart, and the
#: prompt scan and the egress guard have to agree about what a vendor name IS.
#:
#: NOT `sarvam` — see the module docstring. NOT `bolna`: the voice engine is not the
#: assistant's identity, and a tenant's own agent screens name it.
VENDOR_WORDS: Final[tuple[str, ...]] = (
    "anthropic",
    "azure",
    "claude",
    "deepseek",
    "gemini",
    "google",
    "gpt",
    "llama",
    "microsoft",
    "mistral",
    "openai",
    "vertex",
)

#: Spellings of the same names that `VENDOR_WORDS` + `\b` would miss. Three kinds, and
#: each arrived from a different direction:
#:
#: * **Separated compounds** — "open ai", "chat gpt". `\bopenai\b` does not match "open
#:   ai", and a model writing prose separates them about as often as not.
#: * **Product aliases** — "chatgpt", "bard", "copilot" is NOT here (it is this product's
#:   own word for the feature), "gemma", "grok".
#: * **Non-Latin spellings**, because this platform is Telugu-first and its users ask
#:   questions in Telugu, Hindi and English. These are matched by CONTAINMENT rather than
#:   by `\b`, since `\b` is defined on Latin word characters and does nothing useful
#:   between Telugu syllables.
#:
#: ⚠ EVIDENCE CLASS. The transliterations are ordinary orthography, not a claim about a
#: vendor, and a wrong one costs a MISSED match (a false negative that `strict` and the
#: prompt still stand in front of) and never a false one. They are not exhaustive and are
#: not asserted to be: a script nobody enumerated is the documented ceiling above.
VENDOR_ALIASES: Final[tuple[str, ...]] = (
    "open ai",
    "open-ai",
    "chatgpt",
    "chat gpt",
    "bard",
    "gemma",
    "grok",
    "xai",
    "గూగుల్",  # google, Telugu
    "गूगल",  # google, Devanagari
    "जेमिनी",  # gemini, Devanagari
    "జెమిని",  # gemini, Telugu
    "ఓపెన్ ఏఐ",  # open ai, Telugu
    "ओपनएआई",  # openai, Devanagari
)

#: Latin lookalikes from other scripts, folded before matching. A model does not type a
#: Cyrillic o in the middle of "Google" on its own — a PERSON pasting an instruction into
#: a screen description does, and that text reaches the model as data it may echo. One
#: dict pass is cheaper than being wrong about it.
#:
#: SPELLED AS ESCAPES, never as the characters themselves, which is `sanitize._INVISIBLE`'s
#: rule applied to the neighbouring problem: a literal Cyrillic o beside a Latin one is
#: indistinguishable in a diff, in review, and from a typo — in the one table whose subject
#: is that exact confusion. It is also what keeps ruff's ambiguous-character rules (RUF001)
#: meaningful everywhere else in this package instead of suppressed here.
_HOMOGLYPHS: Final[dict[int, str]] = {
    ord(source): target
    for source, target in (
        # Cyrillic
        ("\u0430", "a"),
        ("\u0435", "e"),
        ("\u043e", "o"),
        ("\u0440", "p"),
        ("\u0441", "c"),
        ("\u0445", "x"),
        ("\u0443", "y"),
        ("\u0456", "i"),
        ("\u0455", "s"),
        ("\u0501", "d"),
        ("\u04cf", "l"),
        ("\u043c", "m"),
        ("\u0442", "t"),
        ("\u043a", "k"),
        ("\u043d", "h"),
        ("\u0432", "b"),
        ("\u0450", "e"),
        # Greek
        ("\u03bf", "o"),
        ("\u03b1", "a"),
        ("\u03b5", "e"),
        ("\u03c1", "p"),
        ("\u03b9", "i"),
        ("\u03bd", "v"),
        ("\u03bc", "m"),
        ("\u03c4", "t"),
        ("\u03ba", "k"),
        ("\u03c7", "x"),
        ("\u03b3", "y"),
        # Armenian
        ("\u0581", "g"),
    )
}


def _normalize(text: str) -> str:
    """The form both halves of this module match against.

    NFKC first (so a fullwidth or ligature spelling collapses to the ordinary one), then
    the homoglyph fold, then casefold — `casefold` rather than `lower` because it is the
    one that maps ẞ and the Turkish dotted I the way a matcher needs. Whitespace is
    collapsed so that a name broken across a line, or across two streamed fragments joined
    with a newline, is still one token.

    NOT stripped: combining marks. Removing them would mangle every Telugu and Devanagari
    alias above into something neither spelling matches, which is the opposite of the job.
    """
    folded = unicodedata.normalize("NFKC", text).translate(_HOMOGLYPHS).casefold()
    return re.sub(r"\s+", " ", folded)


_VENDOR_WORD_RE: Final = re.compile(rf"\b(?:{'|'.join(VENDOR_WORDS)})\b")


def names_a_vendor(text: str) -> bool:
    """Does this text contain a model-vendor name, in any of the spellings we cover?

    Whole words for the Latin list, so "googler" and "azured" do not match and a trailing
    quote, bracket or possessive does. Containment for the aliases, because `\\b` has no
    meaning between two Telugu syllables.
    """
    normalized = _normalize(text)
    if _VENDOR_WORD_RE.search(normalized):
        return True
    return any(alias in normalized for alias in VENDOR_ALIASES)


#: An assertion by the speaker about WHAT IT IS or WHO MADE IT. The other half of the
#: scoping rule: a vendor name is a leak only in the company of one of these.
#:
#: Each pattern is tight on purpose, and the loose version of the first one is the reason.
#: `\bi am\b` alone would fire on "I am not able to look up Google Ads spend" — a true,
#: useful sentence about a client's own data — so the first-person arm requires an
#: IDENTITY NOUN in the predicate ("I am a large language model"), not merely a copula.
#: The passive arm ("trained by", "built by") needs no first person at all, because there
#: is nothing else in a dashboard answer that is "trained by" anybody.
_IDENTITY_MARKERS: Final = re.compile(
    r"""
      \b(?:i|we)\s?(?:'m|\u2019m|\ am|\ was|\ are)\s+                # I am / I'm / we are
      (?:not\s+)?(?:a|an|the)?\s*
      (?:large\s+|small\s+|multimodal\s+|generative\s+|ai\s+)*
      (?:language\s+model|llm|model|ai\s+assistant|chatbot|bot|ai)\b
    | \b(?:trained|made|built|created|developed|designed|fine-?\s?tuned|powered|operated)
      \s+by\b
    | \b(?:trained|made|built|created|developed|designed)\s+(?:me|us|this\s+assistant)\b
    | \bmy\s+(?:model|models|creator|creators|maker|makers|developer|developers|training|
             architecture|provider|vendor|owner|makers)\b
    | \bthe\s+model\s+(?:behind|underneath|powering|that\s+powers|i\s+run\s+on)\b
    | \b(?:i|we)\s?(?:'m|\u2019m|\ am|\ are)\s+(?:based|built|running|powered)\s+on\b
    | \b(?:i|we)\s+run\s+on\b
    | \bunderlying\s+(?:model|llm)\b
    """,
    re.VERBOSE,
)


def asserts_an_identity(text: str) -> bool:
    """Is this text saying something about what the SPEAKER is, or who made it?"""
    return bool(_IDENTITY_MARKERS.search(_normalize(text)))


#: What a person is told when they ask, and what replaces a caught answer.
#:
#: FOUR THINGS, IN THIS ORDER, and none of them is optional. It NAMES THE PRODUCT (a
#: person is entitled to know what they are talking to), AFFIRMS THAT IT IS AN AI — never
#: hedged, never coy, `prompt.ASSISTANT_IDENTITY`'s argument and hard rule 5's floor —
#: DECLINES THE VENDOR OUT LOUD rather than pretending the question was not asked, and
#: SAYS WHERE THE ANSWER IS ACTUALLY PUBLISHED. A pointer beats a refusal: the register at
#: `/legal/subprocessors` names Microsoft/Azure OpenAI, OpenAI and Google (checked —
#: `apps/web/src/lib/legal/subprocessors.ts`), so this sends the person somewhere true.
#:
#: The path is RELATIVE because the same Next.js app serves the dashboard and
#: `/legal/[slug]`; a host spelled into a sentence is a host that goes stale.
#:
#: It is one paragraph and not two because it is also what a caught answer becomes —
#: substituted mid-stream, where a second paragraph would read as a new thought.
CANONICAL_IDENTITY_ANSWER: Final = (
    "I am the Calevate assistant — an AI that helps you work inside Calevate. "
    "I do not discuss which AI providers Calevate buys from; they are all named in "
    "Calevate's sub-processor register at /legal/subprocessors."
)

#: Questions answered from `CANONICAL_IDENTITY_ANSWER` without calling a provider.
#:
#: TIGHT, AND ANCHORED WHERE IT HAS TO BE. "who are you" is required to END the clause, so
#: "who are you going to call first?" — an ordinary question about a campaign — is not
#: hijacked by this. The cost of a miss here is small (the egress guard is behind it); the
#: cost of a false positive is that somebody's real question gets a canned answer, which
#: is why the loose forms are excluded rather than tolerated.
_IDENTITY_QUESTIONS: Final = re.compile(
    rf"""
      \bwhat\s+(?:ai\s+|llm\s+|language\s+|kind\s+of\s+)?model\s+(?:are|r)\s+you\b
    | \bwhich\s+(?:ai\s+|llm\s+|language\s+)?model\s+(?:are|r)\s+you\b
    | \bwhat\s+(?:llm|ai|language\s+model)\s+(?:are|do)\s+you\b
    | \bwho\s+(?:made|built|created|trained|developed|designed|owns)\s+you\b
    | \bwho\s+is\s+behind\s+you\b
    | \bwhat\s+powers\s+you\b
    | \bwhat\s+are\s+you\s+(?:built|based|running|trained)\s+on\b
    | \bwhat(?:'s|\u2019s|\ is)\s+your\s+(?:model|name|llm|underlying\s+model)\b
    | \bare\s+you\s+(?:a\s+|an\s+)?(?:{"|".join(VENDOR_WORDS)})\b
    | \bare\s+you\s+(?:a\s+|an\s+)?(?:ai|bot|robot|human|person|machine|chatbot)\b
    | \b(?:who|what)\s+are\s+you\b\s*(?:[?!.,]|$)
    """,
    re.VERBOSE,
)


def is_identity_question(question: str) -> bool:
    """Is this person asking what the assistant IS, rather than about their business?"""
    return bool(_IDENTITY_QUESTIONS.search(_normalize(question)))


def identity_answer(question: str) -> str | None:
    """CONTROL 1. The canonical sentence for an identity question, or `None` to let the
    model answer.

    Deterministic and free: no round trip, no tokens, no `usage_events` row, and no
    argument. A model that has been talked into a persona by nine turns of history never
    sees this question at all.
    """
    return CANONICAL_IDENTITY_ANSWER if is_identity_question(question) else None


#: The broader signal: the person's question was ABOUT the assistant's model, so there is
#: nothing else a vendor name in the answer could be referring to.
_MODEL_TALK: Final = re.compile(
    r"\b(?:model|llm|language\s+model|trained|training)\b.{0,40}\byou(?:r|rs)?\b"
    r"|\byou(?:r|rs)?\b.{0,40}\b(?:model|llm|language\s+model|trained|training)\b"
)

#: A question that is about the ASSISTANT rather than about the business. Required
#: alongside a vendor name before `strict` turns on, and the pairing is what stops the
#: obvious over-reach: **"how many leads came from Google Ads last week?" names a vendor
#: and must NOT put the guard into strict mode**, because the true answer to it names
#: Google half a dozen times and the person is entitled to every one of them. "are you a
#: google model?" names the same vendor inside a frame about the speaker, and does.
_SELF_FRAME: Final = re.compile(
    r"\b(?:are|were|is)\s+you\b"
    r"|\byou\s+(?:are|were)\b"
    r"|\byour\s+(?:model|llm|maker|creator|developer|provider|vendor|training)\b"
    r"|\b(?:trained|built|made|created|developed|powered|fine-?tuned)\b"
)


def question_touches_model_identity(question: str) -> bool:
    """Should the egress guard run in `strict` mode for this question?

    THREE WAYS IN, and the widening is deliberate: `is_identity_question` is sized to
    ANSWER a question, this is sized to WATCH one, and watching may be wrong more cheaply.
    A question that puts "model"/"LLM" next to "you", or that names a vendor INSIDE A
    FRAME ABOUT THE SPEAKER (`_SELF_FRAME`), makes every vendor name in the answer a leak
    — because the answer has no other subject. The frame is not decoration: without it
    "how many leads came from Google Ads?" would arm the strict rule against its own true
    answer.

    This is also what covers the language gap the module docstring admits: the sentence
    rule below is English, this is not, and a Telugu answer to "మీరు ఏ మోడల్?" that names
    Google is still caught, because the strict rule needs no English at all.
    """
    normalized = _normalize(question)
    if is_identity_question(question) or _MODEL_TALK.search(normalized):
        return True
    return bool(names_a_vendor(normalized) and _SELF_FRAME.search(normalized))


#: Where one sentence ends. The Latin stops, the newline (a bullet list has no full stops
#: and each line is still one assertion), and the Devanagari danda, which is the sentence
#: terminator in Hindi and is what a Devanagari answer actually uses.
_SENTENCE_END: Final = re.compile(r"[.!?\n।॥]")

#: How much unterminated text is held before some of it is released anyway.
#:
#: 240 CHARACTERS ≈ ONE LONG SENTENCE. The guard cannot judge a sentence it has not
#: finished reading, so the ordinary case is: hold the sentence, decide, release. That
#: costs the reader one sentence of stream — roughly 60 output tokens, a few hundred
#: milliseconds — and it buys the only outcome that reads correctly, because a substitution
#: pasted onto half a leaked sentence is worse than either. This bound is what stops a
#: model that emits a 4,000-character paragraph with no full stop from being buffered to
#: the end of the answer: past it, text is released with `_LOOKBEHIND` retained.
_MAX_PENDING: Final = 240

#: How much of the tail is kept when a long unterminated span is released early.
#:
#: 96 CHARACTERS, and the number is a MEASUREMENT of the patterns above, not a round one:
#: the longest span `_IDENTITY_MARKERS` can match is under 40 characters and the longest
#: vendor alias under 20, so 96 holds any marker or name that straddles the release point
#: — including one split across two streamed fragments, which is the case a per-chunk scan
#: gets wrong. It is deliberately larger than needed; the cost of the slack is 96
#: characters of latency on a paragraph that had no full stop in 240.
_LOOKBEHIND: Final = 96

#: A span this long with no terminator is not prose (a JSON blob, a table, a code fence)
#: and holding it helps nobody. Past this the pending text is released even when it names
#: a vendor, and the sticky flags below are what keep the sentence rule honest afterwards.
_HARD_MAX: Final = 4096


class IdentityEgress:
    """CONTROL 2. A streaming filter between the model's text and the client's screen.

    ═══ WHY IT BUFFERS, AND EXACTLY HOW MUCH. ═══

    Answers stream fragment by fragment. Scanning the FINISHED answer is too late — it is
    already rendered — and holding the WHOLE answer destroys the thing streaming is for.
    So this holds the current SENTENCE, which is the unit the scoping rule is defined over
    (see the module docstring), releases it the moment it is judged clean, and releases
    early with a `_LOOKBEHIND` tail when a sentence runs past `_MAX_PENDING` without
    ending. A vendor name or an identity marker split across two fragments is therefore
    still seen whole, which a per-fragment scan cannot promise.

    ═══ WHAT A CAUGHT ANSWER BECOMES, AND WHY NOT SOMETHING SMALLER. ═══

    The whole remaining answer is replaced by `CANONICAL_IDENTITY_ANSWER` and everything
    after it is dropped. The two alternatives were considered and are worse:

    * DELETING THE WORD leaves "I am a large language model, trained by ." — gibberish,
      and gibberish that still tells the reader something was removed and invites the
      follow-up question.
    * LETTING THE REST THROUGH after substituting one sentence prints a correction and
      then continues the very train of thought that was corrected ("…register at
      /legal/subprocessors. My training data goes up to …"), which reads as the product
      contradicting itself.

    Sentences ALREADY RELEASED stay released — they were judged clean, one at a time, and
    that is the price of streaming at all. What a person sees is a clean prefix followed
    by the canonical sentence, which is an honest answer and not a truncated one.

    `strict` widens the rule to "any vendor name at all" for a question that was itself
    about the assistant's model (`question_touches_model_identity`).
    """

    __slots__ = ("_pending", "_saw_identity", "_strict", "_suppressing", "substituted")

    def __init__(self, *, strict: bool) -> None:
        self._strict = strict
        self._pending = ""
        #: Sticky FOR THE CURRENT SENTENCE ONLY. When a long sentence is released early,
        #: the marker it contained has already gone out; this remembers that the sentence
        #: made an identity assertion, so a vendor name arriving after the release point
        #: is still judged against it. Cleared at every sentence boundary, because the
        #: next sentence is a new assertion.
        self._saw_identity = False
        self._suppressing = False
        #: True once anything was replaced. The route does not branch on it; it is what
        #: makes the substitution VISIBLE to a test and to an operator log line.
        self.substituted = False

    def feed(self, text: str) -> str:
        """Take one streamed fragment; give back the text that may go out now."""
        if self._suppressing:
            return ""
        self._pending += text
        released: list[str] = []
        while (match := _SENTENCE_END.search(self._pending)) is not None:
            sentence, self._pending = (
                self._pending[: match.end()],
                self._pending[match.end() :],
            )
            if self._leaks(sentence):
                self._pending = ""
                released.append(self._substitute(sentence))
                return "".join(released)
            released.append(sentence)
            # A NEW SENTENCE IS A NEW ASSERTION. The sticky flag is scoped to the span the
            # scoping rule is defined over, and carrying it further would make every later
            # mention of a vendor a leak because one earlier sentence said "I am an AI".
            self._saw_identity = False
        if len(self._pending) > _MAX_PENDING:
            released.append(self._release_early())
        return "".join(released)

    def close(self) -> str:
        """End of the answer: judge and release whatever never got a full stop."""
        if self._suppressing or not self._pending:
            self._pending = ""
            return ""
        tail, self._pending = self._pending, ""
        return self._substitute(tail) if self._leaks(tail) else tail

    def _leaks(self, span: str) -> bool:
        """THE SCOPING RULE, in one place. A vendor name plus — unless the question was
        already about the model — an assertion about the speaker, in the same sentence."""
        if not names_a_vendor(span):
            return False
        return self._strict or self._saw_identity or asserts_an_identity(span)

    def _substitute(self, span: str) -> str:
        """What a caught span becomes, and it is the end of the answer."""
        self._suppressing = True
        self.substituted = True
        # THE SPAN'S LEADING WHITESPACE SURVIVES. A sentence begins after the space that
        # ended the previous one, and that space is part of THIS span; dropping it welds
        # the substitution onto the clean sentence in front of it ("Hello there.I am the
        # Calevate assistant"). One `lstrip` is the whole fix.
        return span[: len(span) - len(span.lstrip())] + CANONICAL_IDENTITY_ANSWER

    def _release_early(self) -> str:
        """A sentence has run past `_MAX_PENDING` with no end in sight.

        Held rather than released while it NAMES A VENDOR and has not yet been condemned:
        the assertion that would condemn it may still be two words away, and releasing the
        name first is the one irreversible mistake this class can make. Past `_HARD_MAX`
        even that gives way — a span that long is not a sentence — and the sticky flag is
        what carries the judgement forward across the release point.
        """
        pending, self._pending = self._pending, ""
        if self._leaks(pending):
            return self._substitute(pending)
        self._saw_identity = self._saw_identity or asserts_an_identity(pending)
        if names_a_vendor(pending) and len(pending) < _HARD_MAX:
            self._pending = pending
            return ""
        self._pending = pending[-_LOOKBEHIND:]
        return pending[:-_LOOKBEHIND]


__all__ = [
    "CANONICAL_IDENTITY_ANSWER",
    "VENDOR_ALIASES",
    "VENDOR_WORDS",
    "IdentityEgress",
    "asserts_an_identity",
    "identity_answer",
    "is_identity_question",
    "names_a_vendor",
    "question_touches_model_identity",
]

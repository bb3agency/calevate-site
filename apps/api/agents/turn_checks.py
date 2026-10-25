"""What is wrong with one agent reply as SPEECH, decided by rules rather than a model.

On ThinnestAI nothing stands between the language model and the voice, so every character
of a reply is spoken, and Cartesia reads punctuation and symbols literally (D-739). A
production call of 11 Oct 2026 showed what these rules catch: one turn asked the same
question three times, spoke the caller's line ("whole chilli 1 kg please.") and read out
"[It is 11:03 am now.]" and "(Waiting for your reply.)". The founder's rules (11 Oct 2026):
one or two short sentences, one point or one question, longer only when the caller asked
for detail; everyday spoken words, never the textbook ones `spoken_style.json` lists;
punctuation written for a voice, with no brackets, dashes, slashes, ellipses or bullets;
prices and quantities in words, never "₹120" or "1 kg"; "?" on every question.

Used by the test loop's hard checks (`agents/test_conversations.hard_check`), which fail a
test on a `JOB_KINDS` problem and note the `SOUND_KINDS` ones, and by the in-call model
comparison
(`scripts/compare_in_call_models`).

CONSERVATIVE WHERE A RULE NEEDS JUDGEMENT. A false failure tells an owner their agent is
broken when it is not. The symbol rules are exact (a spoken reply never needs a bracket); the
others fire only on a clear shape: a time only inside a "current time" phrase, never a
business hour; the caller's part only as a speaker label, an order line ending in "please" or
its Telugu or Hindi equivalent, or the agent answering its own either-or question; a sentence
counts towards the length rule only at three words or more; a question without "?" only when
it opens with a question word or ends with a yes/no ending.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from calevate_shared.spoken_guard import opens_with_greeting, textbook_note, textbook_words
from calevate_shared.spoken_style import style_for

from apps.api.compliance.optout import normalize_utterance

Kind = Literal[
    "brackets",
    "symbols",
    "time",
    "money_digits",
    "formal_words",
    "speaker_labels",
    "caller_line",
    "repeated_question",
    "several_questions",
    "unmarked_question",
    "too_long",
    "wrong_language",
    "third_person",
    # The specimen call of 11 Oct 2026 (D-749): one reply's own problems,
    "foreign_script",
    "spoken_number",
    # and those only the conversation shows (`conversation_problems`).
    "unconfirmed_action",
    "asked_known_number",
    "partial_number",
    "goodbye_while_asking",
    "repeated_turn",
    # The calls of 21 Oct 2026 (D-849): "I told you the price" about a price never said.
    "false_recall",
    # The calls of 20-22 Oct 2026 (D-856): "do you want to know the price?" instead of it.
    "asks_to_tell",
    # The founder's comparison of 23 Oct 2026 (D-861): a long stretch with no breath mark.
    "no_breath",
    # The Sri Estates call of 23 Oct 2026 (D-864): a second greeting, or "can you talk now?"
    # again, in the first reply after the opening.
    "opened_again",
    # D-865: an agent that remembers callers closed a call without its memory sentence.
    "memory_not_said",
    # D-888: "you enquired on our website", which neither the caller nor the facts said.
    "invented_source",
]

#: How a reply SOUNDS (D-828): the words, numbers, punctuation, length and language of a
#: turn. The platform prompt and the register layer (`spoken_style.json`) decide these, not
#: the owner's script, so in the test loop they are a quality note and an alarm to us and
#: never fail a test: production runs of 18-19 Oct 2026 failed 25 of 34 tests on textbook
#: words alone, sent them to the script improver, which cannot change the in-call model's
#: vocabulary, and the loop could not converge.
SOUND_KINDS: Final = frozenset(
    {
        "brackets",
        "symbols",
        "time",
        "money_digits",
        "formal_words",
        "spoken_number",
        "repeated_question",
        "several_questions",
        "unmarked_question",
        "too_long",
        "wrong_language",
        "third_person",
        "foreign_script",
        "repeated_turn",
        "asks_to_tell",
        "no_breath",
        # The START OF THE CALL layer decides it, not the owner's script (D-864).
        "opened_again",
        # The platform's goodbye rule decides it, not the owner's script (D-865).
        "memory_not_said",
    }
)
#: What breaks the caller's task whatever the words: the caller's part said for them, a
#: claim that something was done when nothing did it, a number asked for or taken wrongly,
#: goodbye while the caller is still asking. These fail the test. They are platform rules
#: as well (`calevate_shared.engine`), so they are ours to fix, not the owner's.
JOB_KINDS: Final = frozenset(
    {
        "speaker_labels",
        "caller_line",
        "unconfirmed_action",
        "asked_known_number",
        "partial_number",
        "goodbye_while_asking",
        "false_recall",
        "invented_source",
    }
)

#: A turn's sentences, at most, unless the caller asked for detail (founder, 11 Oct 2026).
MAX_SENTENCES: Final = 2
#: Words a sentence needs to count towards `MAX_SENTENCES`: "Sure." or "సరే అండి." is a
#: courtesy, not a second point.
MIN_COUNTED_WORDS: Final = 3
#: The most words a reply may run without a comma or a sentence end (D-861). Cartesia paces
#: speech by its punctuation (docs.cartesia.ai sonic-3 prompting tips, 23 Oct 2026, REPORTED),
#: so a long unmarked run is said in one breath. Our own example turns run two to six words between
#: marks; 14 is more than two such clauses back to back, so a turn written the way they are
#: never reaches it. A choice of ours, not a measured threshold.
BREATH_MAX_WORDS: Final = 14
#: What counts as a place to breathe.
_BREATH_MARK: Final = re.compile(r"[,.!?;:।]")
_QUOTE_MAX: Final = 80


@dataclass(frozen=True, slots=True)
class TurnProblem:
    kind: Kind
    #: One plain sentence the owner reads.
    reason: str


_BRACKETED: Final = re.compile(r"\[[^\]]{0,200}\]|\([^()]{0,200}\)|[\[\]()]")
#: Read aloud as a word or a pause in the wrong place: dashes, a slash, an ellipsis, a bullet
#: or a markdown asterisk at the start of a line.
_SYMBOLS: Final = re.compile(r"[—\u2013/…]|\.\.\.|(?:^|\n)\s*(?:[-*•·]|\d+[.)])\s")
#: The time said as "now": the shape of context a voice platform adds to a turn. Never a
#: bare "it is 10:30", which is how an agent gives opening hours.
_TIME_PHRASES: Final = (
    re.compile(
        r"\b(?:the time is|time now is|now it(?:'s| is)|it(?:'s| is) now)\s*:?\s*\d{1,2}[:.]\d{2}",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?\s+now\b", re.IGNORECASE),
    re.compile(r"(?:ఇప్పుడు|अभी)\s+(?:సమయం|టైమ్|time|समय|टाइम)\s*\d{1,2}[:.]\d{2}", re.IGNORECASE),
    re.compile(r"\bcurrent (?:time|date)\b", re.IGNORECASE),
    # An ISO timestamp, or a clock with seconds: nobody says either on the phone.
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"),
    re.compile(r"\b\d{1,2}:\d{2}:\d{2}\b"),
)
#: A rupee sign at all, or digits beside a currency word or a unit abbreviation: the voice
#: reads "₹120" and "1 kg" as symbols, where a shop says "one twenty rupees", "one kg".
_MONEY_DIGITS: Final = re.compile(
    r"₹|\b(?:rs|inr)\.?\s*\d|\d+(?:[.,]\d+)?\s*(?:rs|inr|kgs?|gms?|g|ml|ltrs?|l|km|hrs?|mins?)\b",
    re.IGNORECASE,
)
_LABEL: Final = re.compile(
    r"(?:^|[\n.!?।]\s*)(?:caller|customer|user|agent|assistant|you|కాలర్|కస్టమర్|ग्राहक|कॉलर)"
    r"\s*:",
    re.IGNORECASE,
)
_QUANTITY: Final = re.compile(
    r"(?:\d+(?:\.\d+)?\s*|(?:^|(?<=\s))(?:one|two|three|half|a|ఒక|రెండు|అర|एक|दो|आधा)\s+)"
    r"(?:kg|kgs|kilo|kilos|g|gm|grams?|litres?|liters?|l|ml|packets?|packs?|pieces?|"
    r"dozen|boxes?|bags?|bottles?|కిలో|కేజీ|ప్యాకెట్|लीटर|किलो|पैकेट)"
    r"(?=[\s.,!?।]|$)",
    re.IGNORECASE,
)
#: How a caller ends an order: "please" in English, "give" or "want" in Telugu and Hindi.
_ORDER_ENDING: Final = re.compile(
    r"(?:\bplease|ఇవ్వండి|కావాలి|चाहिए|दीजिए|दे दो|दे दीजिए)\s*[.!।]?\s*$", re.IGNORECASE
)
_OR: Final = re.compile(r"\s+(?:or|లేదా|या)\s+", re.IGNORECASE)
#: What a caller says when they want more than a short answer.
_ASKS_DETAIL: Final = re.compile(
    r"detail|explain|tell me (?:more|everything|all)|more about|everything|in full|full list|"
    r"all the|వివరాలు|వివరంగా|పూర్తిగా|అన్నీ|విస్తారంగా|विस्तार|पूरी जानकारी|सब कुछ|सारी",
    re.IGNORECASE,
)
#: A sentence that is a question by its words. English: an opening question word. Hindi:
#: "क्या" at either end. Telugu: a last word with a yes/no ending (ఉందా, కావాలా, చెప్తారా,
#: సరేనా) in a sentence of three words or more, so a tag on its own ("అవునా") is left alone.
#: Not every word ending in "ా": the spoken first person "చూస్తా", "చెప్తా" is a statement,
#: and so is a question word inside one ("ఎంత కావాలన్నా ఇస్తాం").
_EN_QUESTION: Final = re.compile(
    r"^(?:what|which|when|where|who|whom|whose|why|how|do|does|did|can|could|would|will|"
    r"shall|should|is|are|am|may)\b",
    re.IGNORECASE,
)
_TE_YES_NO_ENDINGS: Final = ("దా", "లా", "రా", "నా", "సా")
_HI_QUESTION: Final = re.compile(r"^क्या\s|\sक्या$")
#: A sentence end, with or without the space after it: a reply the voice platform generated
#: again after an interruption arrives glued together ("ఎంత కావాలి?మీకు", D-749). A full
#: stop counts unspaced only before a letter, so "1.5" stays whole.
_SENTENCE_END: Final = re.compile(
    r"(?:(?<=[.!?।\uff1f])|(?<=[.!?।\uff1f][\])\"'\u201d\u2019]))\s+"
    r"|(?<=[!?।\uff1f])(?=[^\s!?।\uff1f\])\"'\u201d\u2019])|(?<=\.)(?=[^\W\d_])"
)
#: Stripped from a word's ends. Words are split on spaces, not `\w`, because Python's `\w`
#: does not match the vowel signs of Indic scripts and would break a Telugu word apart.
_PUNCTUATION: Final = "\"'“”\u2018\u2019.,!?;:()[]{}।\uff1f…-\u2013—"
#: Short abbreviations whose full stop does not end a sentence.
_ABBREVIATION: Final = re.compile(r"\b(?:rs|dr|mr|mrs|ms|no|st|vs|etc|approx)\.$", re.IGNORECASE)
#: Words that carry no meaning when comparing two questions.
_FILLER: Final = frozenset(
    [
        "a",
        "an",
        "the",
        "do",
        "you",
        "your",
        "is",
        "are",
        "or",
        "to",
        "of",
        "for",
        "it",
        "what",
        "which",
        "how",
        "would",
        "like",
        "want",
        "we",
        "can",
        "please",
        "sir",
        "madam",
        "andi",
        "garu",
        "అండి",
        "గారు",
        "మీకు",
        "మీ",
        "కావాలి",
        "ఏ",
        "ఏది",
        "ఏం",
        "क्या",
        "आप",
        "आपको",
        "जी",
    ]
)
#: The script each language is written in, for the wrong-language rule. Only languages whose
#: callers write a script of their own: an English or Latin-script reply to a caller who
#: wrote Telugu letters is unambiguous, where two Latin-script languages are not.
_SCRIPT_OF: Final[dict[str, tuple[str, re.Pattern[str]]]] = {
    "te": ("Telugu", re.compile("[ఀ-౿]")),
    "hi": ("Hindi", re.compile("[ऀ-ॿ]")),
    "ta": ("Tamil", re.compile("[஀-௿]")),
    "kn": ("Kannada", re.compile("[ಀ-೿]")),
    "ml": ("Malayalam", re.compile("[ഀ-ൿ]")),
    "mr": ("Marathi", re.compile("[ऀ-ॿ]")),
}
_LATIN_WORD: Final = re.compile(r"[A-Za-z]{2,}")
#: The agent talking ABOUT the person it is talking TO: an action's answer read out as it
#: stands ("The caller's number has been added ..."). "This customer" is how an owner's own
#: script may describe a caller to the agent, so only "the caller" and "the customer's" count.
#: The apostrophe is matched straight or curly (written as an escape: RUF001).
_THIRD_PERSON: Final = re.compile(
    r"\bthe caller(?:['\u2019]s)?\b|\bthe customer['\u2019]s\b", re.IGNORECASE
)


def sentences(reply: str) -> list[str]:
    """The reply split into sentences, an abbreviation's full stop not counting as an end."""
    out: list[str] = []
    for piece in _SENTENCE_END.split(" ".join(reply.split())):
        if out and _ABBREVIATION.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        elif piece:
            out.append(piece)
    return out


def _is_question(sentence: str) -> bool:
    return sentence.rstrip().endswith(("?", "\uff1f"))


def _words(sentence: str) -> list[str]:
    stripped = (w.strip(_PUNCTUATION).lower() for w in sentence.split())
    return [w for w in stripped if w]


def _reads_as_question(sentence: str) -> bool:
    words = _words(sentence)
    if not words:
        return False
    if _EN_QUESTION.search(" ".join(words)) or _HI_QUESTION.search(" ".join(words)):
        return True
    return len(words) >= MIN_COUNTED_WORDS and words[-1].endswith(_TE_YES_NO_ENDINGS)


def _content(sentence: str) -> set[str]:
    return {w for w in _words(sentence) if w not in _FILLER and len(w) > 1}


def _same_question(a: str, b: str) -> bool:
    """Two questions asking one thing: most of the shorter one's meaningful words recur in
    the other. Overlap over the shorter set, so a longer rewording still matches."""
    left, right = _content(a), _content(b)
    if len(left) < 2 or len(right) < 2:
        return _words(a) == _words(b) and bool(left or right)
    return len(left & right) / min(len(left), len(right)) >= 0.6


def _quoted(text: str) -> str:
    text = " ".join(text.split())
    return f"“{text[:_QUOTE_MAX]}{'…' if len(text) > _QUOTE_MAX else ''}”"


def _time_phrase(reply: str) -> str | None:
    for pattern in _TIME_PHRASES:
        match = pattern.search(reply)
        if match:
            return match.group(0)
    return None


def _answered_own_choice(parts: list[str]) -> str | None:
    """A statement that opens with one option of the reply's own earlier either-or
    question: the agent answered for the caller."""
    for i, question in enumerate(parts):
        if not _is_question(question):
            continue
        options = [_words(option) for option in _OR.split(question.rstrip("?\uff1f "))]
        if len(options) < 2:
            continue
        # The first option keeps the words before it ("Do you want whole chilli"): its
        # last two words are what a caller would repeat.
        options[0] = options[0][-2:]
        for later in parts[i + 1 :]:
            if _is_question(later):
                continue
            said = _words(later)
            if len(said) <= 8 and any(o and said[: len(o)] == o for o in options):
                return later
    return None


def _caller_order(parts: list[str]) -> str | None:
    for sentence in parts:
        if (
            not _is_question(sentence)
            and _QUANTITY.search(sentence)
            and _ORDER_ENDING.search(sentence)
        ):
            return sentence
    return None


#: English number words, for the figures a "said before" claim names.
_EN_NUMBER: Final = "one|two|three|four|five|six|seven|eight|nine|ten|half|hundred|thousand"
#: Telugu joins "నాకు" and "ఒక" into "నాకొక", so a word ending in "కొక" ends on "ఒక".
_TE_JOINED_ONE: Final = "కొక"
#: A unit right after the number the agent supplied ("ఒక కేజీ", "one kg").
_UNIT: Final = re.compile(
    r"^(?:kg|kgs|kilo|kilos|g|gm|grams?|litres?|liters?|packets?|packs?|pieces?|dozen|boxes?|"
    r"bags?|bottles?|కిలో\S*|కేజీ\S*|ప్యాకెట్\S*|लीटर|किलो|पैकेट)$",
    re.IGNORECASE,
)


#: Telugu number forms that need a noun after them: "ఒక" (a, one) and "అర" (half). The
#: standalone answers are "ఒకటి" and "అర కేజీ", so a line ending on one of these was cut. A
#: bare "two" or "రెండు" answering "how many?" is complete, so other numbers are left alone.
_NEEDS_A_NOUN: Final = frozenset({"ఒక", "అర"})


def _number_word(word: str) -> str | None:
    """The noun-needing number a caller's last word ends on, or None."""
    if word.endswith(_TE_JOINED_ONE):
        return "ఒక"
    return word if word in _NEEDS_A_NOUN else None


#: Words a caller's line cannot end on unless the turn timer cut it ("మాకు", "to us").
_DANGLING: Final = frozenset({"నాకు", "మాకు", "मुझे", "हमें"})
#: The longest reply that is still only a "go on" ("చెప్పండి అండి", "हाँ जी, बोलिए").
NUDGE_MAX_WORDS: Final = 4
#: The longest single question that offers a reading of a broken-off answer ("అంటే ఒక కోటి
#: వరకు అనుకుంటున్నారా అండి, లేక ఇంకా ఎక్కువా?"), D-856.
OFFER_MAX_WORDS: Final = 12


def _offers_reading(caller_said: str, parts: list[str]) -> bool:
    """The caller stopped on a number and the reply is one short question that offers a
    reading of it ("ఒక కేజీ కావాలా అండి, ఇంకా ఎక్కువా?"), not its earlier question again."""
    said = _words(caller_said)
    number = _number_word(said[-1]) if said else None
    if number is None or len(parts) != 1 or not _is_question(parts[0]):
        return False
    words = _words(parts[0])
    return len(words) <= OFFER_MAX_WORDS and number in words


def broke_off(caller_said: str) -> bool:
    """Does the caller's line stop mid-sentence: on a number ("ఒక") or a dangling "to me"?"""
    said = _words(caller_said)
    return bool(said) and (_number_word(said[-1]) is not None or said[-1] in _DANGLING)


def _finished_cut_line(caller_said: str, reply: str) -> str | None:
    """The caller's line stopped on a number ("నాకొక", cut by the turn timer on the call of 21
    Oct 2026) and the reply supplied the unit as if they had said it ("ఒక కేజీ"): the agent
    finished the caller's sentence. The words it supplied, or None. Offering the reading as a
    question ("ఒక కేజీ కావాలా, ఇంకా ఎక్కువా?") is the right move, not a finished line (D-856)."""
    said = _words(caller_said)
    number = _number_word(said[-1]) if said else None
    if number is None:
        return None
    for sentence in sentences(reply):
        if _is_question(sentence):
            continue
        words = _words(sentence)
        for i, word in enumerate(words[:-1]):
            if word == number.lower() and _UNIT.match(words[i + 1]):
                return f"{words[i]} {words[i + 1]}"
    return None


def _repeated_sentence(parts: list[str]) -> str | None:
    """A statement whose words all came earlier in the same reply ("మంచిది అండి, thanks అండి."
    after "మంచిది అండి, ... thanks అండి."): the double goodbye of 21 Oct 2026. Questions are
    `repeated_question`'s, and a statement after a question answers it (`caller_line`).
    A second sentence that says goodbye is one too, in other words or not ("ఉంటాను మరి,
    నమస్కారం. సరే అండి, ఉంటాను మరి.", our call of 24 Oct 2026, D-877)."""
    farewells = [part for part in parts if _GOODBYE.search(part)]
    if len(farewells) > 1:
        return farewells[1]
    for i, later in enumerate(parts):
        words = set(_words(later))
        if _is_question(later) or len(words) < 2:
            continue
        if any(words <= set(_words(earlier)) for earlier in parts[:i] if not _is_question(earlier)):
            return later
    return None


def _symbol_problems(reply: str) -> list[TurnProblem]:
    found: list[TurnProblem] = []
    bracket = _BRACKETED.search(reply)
    if bracket:
        found.append(
            TurnProblem(
                "brackets",
                f"It read out something in brackets ({_quoted(bracket.group(0))}). Callers "
                "hear every word and symbol the agent writes.",
            )
        )
    symbol = _SYMBOLS.search(reply)
    if symbol:
        found.append(
            TurnProblem(
                "symbols",
                f"It wrote {_quoted(symbol.group(0).strip())}, which the voice reads out or "
                "pauses on. Write for a voice: commas and full stops, no dashes, slashes, "
                "ellipses or bullets.",
            )
        )
    clock = _time_phrase(reply)
    if clock and not (bracket and clock in bracket.group(0)):
        found.append(
            TurnProblem(
                "time",
                f"It said the time out loud ({_quoted(clock)}), which was context for the "
                "agent, not something to say.",
            )
        )
    money = _MONEY_DIGITS.search(reply)
    if money:
        found.append(
            TurnProblem(
                "money_digits",
                f"It wrote {_quoted(money.group(0).strip())} in digits and symbols. Prices "
                'and quantities should be words, as a shop says them ("one twenty rupees", '
                '"one kg").',
            )
        )
    return found


#: The spoken-style list's matcher, shared with every AI writer of spoken lines (D-831).
formal_swaps = textbook_words


def _formal_problem(reply: str, language: str) -> TurnProblem | None:
    swaps = formal_swaps(reply, language)
    if not swaps:
        return None
    return TurnProblem(
        "formal_words", f"It used textbook words callers do not say: {textbook_note(swaps)}."
    )


#: Words that open a question restating the one before it with options or plainer words
#: ("ఏ area లో చూస్తున్నారు? అంటే ఏదైనా particular area ఉందా?"): one question, said two ways.
_RESTATES: Final = frozenset({"అంటే", "లేక", "లేదా", "or", "i.e", "मतलब", "यानी", "या"})


#: A question asking leave to say something ("would you like to know the price?"), which costs
#: the caller a turn: on four calls of 20-22 Oct 2026 the agent asked it instead of the price.
_ASKS_TO_TELL: Final = re.compile(
    r"\b(?:would you like|do you want|want me) to (?:know|hear)\b|\bshall i tell you\b"
    r"|తెలుసుకోవాల(?:నుకుంటున్నారా|ని ఉందా)|వినాలనుకుంటున్నారా|చెప్పమంటారా"
    r"|जानना चाह(?:ेंगे|ते हैं)|बताऊँ क्या",
    re.IGNORECASE,
)


def _restates(question: str) -> bool:
    words = _words(question)
    return bool(words) and words[0] in _RESTATES


def _question_problems(parts: list[str]) -> list[TurnProblem]:
    found: list[TurnProblem] = []
    questions = [s for s in parts if _is_question(s)]
    asked = [q for i, q in enumerate(questions) if i == 0 or not _restates(q)]
    if any(_same_question(a, b) for i, a in enumerate(questions) for b in questions[i + 1 :]):
        found.append(
            TurnProblem(
                "repeated_question",
                "It asked the same question more than once in one reply. It should ask once "
                "and wait.",
            )
        )
    elif len(asked) > 1:
        found.append(
            TurnProblem(
                "several_questions",
                f"It asked {len(asked)} questions in one reply. It should ask one and wait "
                "for the answer.",
            )
        )
    unmarked = next((s for s in parts if not _is_question(s) and _reads_as_question(s)), None)
    if unmarked:
        found.append(
            TurnProblem(
                "unmarked_question",
                f"It asked {_quoted(unmarked)} without a question mark, so the voice says it "
                "flat, like a statement.",
            )
        )
    return found


#: What a caller says on picking up or to keep the line alive, in English letters: no reason
#: to leave the language the agent greeted in (D-849, `calevate_shared.engine._SWITCH_RULE`).
_GREETING_WORDS: Final = frozenset(
    {
        "hello",
        "helo",
        "hallo",
        "hi",
        "hey",
        "ok",
        "okay",
        "yes",
        "yeah",
        "yup",
        "haan",
        "haa",
        "ha",
        "han",
        "ji",
        "haanji",
        "hmm",
        "hm",
        "sure",
        "fine",
        "sir",
        "madam",
        "andi",
    }
)
#: The most words a greeting-only caller line has.
_GREETING_MAX_WORDS: Final = 2


def _only_a_greeting(caller_said: str) -> bool:
    words = _words(caller_said)
    return 0 < len(words) <= _GREETING_MAX_WORDS and all(w in _GREETING_WORDS for w in words)


def _language_problems(reply: str, caller_said: str, language: str) -> list[TurnProblem]:
    """A reply in another language than the caller's, and a reply that talks about the caller.

    Wrong language only when the caller wrote the agent's own language in its own script
    and the reply has none of that script and at least three Latin words: a code-mixed
    reply keeps some of the language's letters, and an agent whose main language is not the
    caller's may rightly answer in its own.
    """
    found: list[TurnProblem] = []
    script = _SCRIPT_OF.get(language.split("-")[0].lower())
    in_english = (
        script is not None
        and not script[1].search(reply)
        and len(_LATIN_WORD.findall(reply)) >= MIN_COUNTED_WORDS
    )
    if script is not None and in_english and len(script[1].findall(caller_said)) >= 3:
        found.append(
            TurnProblem(
                "wrong_language",
                f"The caller spoke {script[0]} and it answered in English.",
            )
        )
    elif script is not None and in_english and _only_a_greeting(caller_said):
        found.append(
            TurnProblem(
                "wrong_language",
                f"The caller only said {_quoted(caller_said)} and it switched to English. A "
                f"greeting or a word or two is no reason to leave {script[0]}.",
            )
        )
    if _THIRD_PERSON.search(reply):
        found.append(
            TurnProblem(
                "third_person",
                'It talked about "the caller" instead of speaking to them.',
            )
        )
    return found


def turn_problems(reply: str, *, caller_said: str = "", language: str = "") -> list[TurnProblem]:
    """Every problem in one agent reply, the platform's first. `caller_said` is the caller's
    line this reply answers; it decides whether a longer reply was asked for. `language`
    selects the spoken-style word list; without it the formal-word check is skipped."""
    if not reply.strip():
        return []
    found = _symbol_problems(reply)
    found += _language_problems(reply, caller_said, language)
    found += _script_and_number_problems(reply, language)
    formal = _formal_problem(reply, language)
    if formal:
        found.append(formal)
    parts = sentences(reply)
    if _LABEL.search(reply):
        found.append(
            TurnProblem(
                "speaker_labels",
                "It wrote both sides of the conversation in one reply, with speaker names.",
            )
        )
    else:
        own = _answered_own_choice(parts) or _caller_order(parts)
        finished = None if own else _finished_cut_line(caller_said, reply)
        if own:
            found.append(
                TurnProblem(
                    "caller_line",
                    f"It said the caller's part ({_quoted(own)}) as if the caller had answered.",
                )
            )
        elif finished:
            found.append(
                TurnProblem(
                    "caller_line",
                    f"The caller broke off mid-sentence and it finished it for them "
                    f"({_quoted(finished)}). It should ask them to go on.",
                )
            )
    found += _question_problems(parts)
    run = max((len(piece.split()) for piece in _BREATH_MARK.split(reply)), default=0)
    if run > BREATH_MAX_WORDS:
        found.append(
            TurnProblem(
                "no_breath",
                f"It ran {run} words without a comma or a full stop, so the voice says them in "
                "one breath. A comma after an opener and one idea per sentence give it places "
                "to pause.",
            )
        )
    meta = next((s for s in parts if _is_question(s) and _ASKS_TO_TELL.search(s)), None)
    if meta:
        found.append(
            TurnProblem(
                "asks_to_tell",
                f"It asked whether to tell them ({_quoted(meta)}) instead of telling them.",
            )
        )
    repeated = _repeated_sentence(parts)
    if repeated:
        found.append(
            TurnProblem(
                "repeated_turn",
                f"It said {_quoted(repeated)} twice in one reply.",
            )
        )
    counted = [s for s in parts if len(_words(s)) >= MIN_COUNTED_WORDS]
    if (
        broke_off(caller_said)
        and len(_words(reply)) > NUDGE_MAX_WORDS
        and not _offers_reading(caller_said, parts)
    ):
        found.append(
            TurnProblem(
                "too_long",
                f"The caller stopped mid-sentence ({_quoted(caller_said)}). One short question "
                'offering what they may mean ("one kg, or more?") lets them finish; a full reply '
                "guesses.",
            )
        )
    elif len(counted) > MAX_SENTENCES and not _ASKS_DETAIL.search(caller_said):
        found.append(
            TurnProblem(
                "too_long",
                f"It said {len(counted)} sentences in one turn. Keep a turn to one or two "
                "short sentences unless the caller asks for detail.",
            )
        )
    return found


# --- the specimen call of 11 Oct 2026 (D-749) -----------------------------------------
#
# A Raghava Organics outbound call, kept as the standing specimen of what goes wrong on a
# live call for any business and in any language (`docs/evidence/specimen-call-raghava-
# 2026-10-11.md`). One reply shows a letter from another script or a number said the
# native way; the conversation shows the rest: "done" with no action behind it, asking for
# the number the call is on, a part of a number taken as the whole, goodbye while the
# caller is still asking, and a whole turn repeated when the caller asked to hear it again.

#: Letters of a script no agent of ours writes (a Korean syllable appeared mid-Telugu), and
#: the Indic scripts, which are foreign unless they are the reply's own language's.
_NON_INDIC_FOREIGN: Final = "Ͱ-ϿЀ-ӿ֐-׿؀-ۿ฀-๿ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿가-힯"
#: Each Indic script's block; the danda (U+0964/5) is punctuation every Indic script uses.
_INDIC_BLOCKS: Final[dict[str, tuple[str, str]]] = {
    "hi": ("ऀ", "ॣ"),
    "bn": ("ঀ", "৿"),
    "pa": ("਀", "੿"),
    "gu": ("઀", "૿"),
    "or": ("଀", "୿"),
    "ta": ("஀", "௿"),
    "te": ("ఀ", "౿"),
    "kn": ("ಀ", "೿"),
    "ml": ("ഀ", "ൿ"),
}

_TE_NUMBER: Final = (
    "ఒకటి|ఒక|రెండు|మూడు|నాలుగు|ఐదు|అయిదు|ఆరు|ఏడు|ఎనిమిది|తొమ్మిది|పది|ఇరవై|ముప్పై|నలభై|"
    "యాభై|అరవై|డెబ్బై|ఎనభై|తొంభై|వంద|వందల|నూరు|నూట|వెయ్యి|వేల|వేలు"
)
_HI_NUMBER: Final = (
    "एक|दो|तीन|चार|पाँच|पांच|छह|छः|सात|आठ|नौ|दस|बीस|तीस|चालीस|पचास|साठ|सत्तर|अस्सी|नब्बे|"
    "सौ|हज़ार|हजार|डेढ़|ढाई"
)
#: A price in the language's own number words ("ఆరు నూరు రూపాయలు"). A problem only where the
#: language's `prices` number rule says the English way (`LanguageStyle.native_price_words`):
#: Telugu's does ("six hundred rupees", as shops in Hyderabad say it, D-744), Hindi's allows
#: "एक सौ बीस रुपये".
#: Telugu's also catches a big amount in Telugu number words ("రెండు కోట్ల"), which its
#: `lakhs` rule says the English way, written in Telugu letters ("టూ క్రోర్స్", D-861). A
#: time in Telugu number words ("రెండు గంటలకు") is how people say a time and is not flagged.
_NATIVE_PRICE: Final[dict[str, re.Pattern[str]]] = {
    "te": re.compile(rf"(?:(?:{_TE_NUMBER})\s+)*(?:{_TE_NUMBER})\s*(?:రూపాయ|కోట|లక్ష)"),
    "hi": re.compile(rf"(?:(?:{_HI_NUMBER})\s+)*(?:{_HI_NUMBER})\s*(?:रुपय|रुपए|रुपये|रूपये)"),
}
#: Digits beside a unit written in an Indian script ("1 కిలో"), which `_MONEY_DIGITS` (Latin
#: units only) does not see.
_DIGIT_UNIT: Final = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:కిలో|కేజీ|రూపాయ|గ్రాము|లీటర్|ప్యాకెట్|किलो|रुपय|रुपए|रुपये|ग्राम|लीटर|पैकेट)"
)


def _foreign_letter(reply: str, language: str) -> str | None:
    """Letters no voice of this language can say. Another Indian script counts only inside
    a reply in the language's own script: a whole reply in Hindi from a Telugu agent is a
    language switch an agent with Hindi may make, where one Hindi word mid-Telugu is not."""
    own = language.split("-")[0].lower()
    ranges = _NON_INDIC_FOREIGN
    block = _INDIC_BLOCKS.get(own)
    if block is not None and re.search(f"[{block[0]}-{block[1]}]", reply):
        ranges += "".join(f"{lo}-{hi}" for tag, (lo, hi) in _INDIC_BLOCKS.items() if tag != own)
    match = re.search(f"[{ranges}]+", reply)
    return match.group(0) if match else None


def _script_and_number_problems(reply: str, language: str) -> list[TurnProblem]:
    found: list[TurnProblem] = []
    foreign = _foreign_letter(reply, language)
    if foreign:
        found.append(
            TurnProblem(
                "foreign_script",
                f"It wrote letters of another language's script ({_quoted(foreign)}), which "
                "the voice cannot say.",
            )
        )
    style = style_for(language) if language else None
    native = (
        _NATIVE_PRICE.get(language.split("-")[0].lower())
        if style is not None and not style.native_price_words
        else None
    )
    in_words = native.search(reply) if native else None
    said = in_words or _DIGIT_UNIT.search(reply)
    if said:
        how = (
            'the English way, as shops do, in the call\'s letters ("సిక్స్ హండ్రెడ్ రూపీస్", "టూ క్రోర్స్")'
            if in_words
            else "in words, as shops do"
        )
        found.append(
            TurnProblem(
                "spoken_number",
                f"It said {_quoted(said.group(0))}. Say prices and quantities {how}, never in "
                "digits.",
            )
        )
    return found


class Exchange(Protocol):
    """One caller line and the agent's reply to it, with the tools the agent used."""

    @property
    def said(self) -> str: ...

    @property
    def reply(self) -> str: ...

    @property
    def tools(self) -> Sequence[str]: ...


#: Words that say something is DONE: an order placed, details saved, a booking made, a
#: message sent. Past or perfect only: "the team will confirm" is the honest future the
#: platform rule asks for (`ACTION_CLAIM_RULE`). "Noted" / "నోట్ చేసుకున్నాను" /
#: "రాసుకున్నాను" is NOT a claim (founder, 21 Oct 2026): the post-call reading records what
#: the caller asked for, so saying it was noted is true.
_CLAIMS_DONE: Final = re.compile(
    r"\b(?:i(?:['\u2019]ve| have)|we(?:['\u2019]ve| have)|it(?:['\u2019]s| is| has been)|(?:your )?"
    r"(?:order|details|booking|number|request|name|slot)(?: is| are| has been| have "
    r"been)) (?:now |already |all )?(?:placed|booked|saved|recorded|sent|added|"
    r"confirmed|registered|scheduled)\b"
    r"|\b(?:booked|placed|saved)(?: down)? (?:your|the) (?:order|details|booking)\b"
    # The bare Telugu form must not be followed by a letter, so "చేసుకున్నారా?" (did you?)
    # is no claim.
    # "Fixed" a visit or a slot is a booking claim too (a competitor's "సైట్ విజిట్ ఫిక్స్
    # చేశాను", D-856), in textbook Telugu too ("ఖరారు చేశాను", our call of 24 Oct 2026, D-877).
    r"|(?:నమోదు|సేవ్|save|బుక్|book|రికార్డ్|record|confirm|కన్ఫర్మ్|place|ప్లేస్|add|"
    r"యాడ్|fix|ఫిక్స్|ఖరారు|ఖాయం|షెడ్యూల్|schedule|ఫైనల్|final|ఆర్డర్ పెట్టే|order పెట్టే)"
    r"\s*(?:చేసా|చేశా|చేసేసా|చేసేశా|అయిపోయింది|"
    r"అయింది|ఐంది|చేసుకున్నాను|చేసుకున్నాం|చేసుకున్నా(?![ఀ-౿]))"
    r"|పంపాను|పంపాం|పంపించాను|పంపించాం|పంపేశాను|పంపేసాను|పంపేశాం|పంపేసాం"
    r"|(?:सेव|बुक|दर्ज|रिकॉर्ड|कन्फर्म|प्लेस|ऐड|फिक्स|तय|पक्का|शेड्यूल|save|book|confirm|add|"
    r"fix|schedule)\s*"
    r"(?:कर\s*(?:दिया|दी|दिए|लिया|ली|लिए)|हो\s*(?:गया|गई|गए))|भेज\s*(?:दिया|दी|दिए)",
    re.IGNORECASE,
)
#: Tools that only look something up, so they confirm nothing was done.
_LOOKUP_TOOL: Final = re.compile(r"knowledge|search|lookup|look_up", re.IGNORECASE)
_PHONE_NUMBER: Final = re.compile(
    r"(?:phone|mobile|contact|whatsapp|whats app)\s*(?:number|no\b)|"
    r"(?:ఫోన్|మొబైల్|phone|mobile|కాంటాక్ట్)\s*(?:నంబర్|నెంబర్|నంబరు|నెంబరు|number)|"
    r"(?:फ़ोन|फोन|मोबाइल|phone|mobile)\s*(?:नंबर|नम्बर|number)",
    re.IGNORECASE,
)
_ASKS_FOR: Final = re.compile(
    r"\?|ఇవ్వ|చెప్ప|ఇస్తారా|చెప్తారా|give|share|tell|send|दीजिए|बताइए|बताएं|दे दीजिए",
    re.IGNORECASE,
)
#: "Shall we use this same number?" is the one question about a number the platform allows.
_SAME_NUMBER: Final = re.compile(
    r"(?:this|same)\s+number|ఇదే\s*(?:నంబర్|నెంబర్|number)|ఈ\s*(?:నంబర్|నెంబర్|number)|"
    r"इसी\s*(?:नंबर|नम्बर|number)|यही\s*(?:नंबर|नम्बर)",
    re.IGNORECASE,
)
#: The caller wants a number other than the one the call is on.
_OTHER_NUMBER: Final = re.compile(
    r"(?:another|different|other|second)\s+number|వేరే|ఇంకో\s*(?:నంబర్|నెంబర్)|दूसरा|दूसरे",
    re.IGNORECASE,
)
_DIGIT_WORD: Final = re.compile(
    r"\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE
)
#: A mobile number in India has ten digits.
MOBILE_DIGITS: Final = 10
#: What a reply says when it treats what it was given as complete.
_WRAPS_UP: Final = re.compile(
    r"thank|thanks|anything else|ధన్యవాద|థాంక్స్|థ్యాంక్స్|ఇంకేమైనా|ఇంకా ఏమైనా|धन्यवाद|"
    r"शुक्रिया|और कुछ",
    re.IGNORECASE,
)
_GOODBYE: Final = re.compile(
    r"\bgood\s?bye\b|\bbye\b|గుడ్\s?బై|(?:^|[\s,.!?])బై(?=[\s,.!?]|$)|ఉంటాను\s*మరి|ఉంటానండి|"
    r"ఉంటాం\s*మరి|अलविदा|बाय",
    re.IGNORECASE,
)
#: A caller line that closes the conversation, after which a goodbye is right.
_CALLER_CLOSES: Final = re.compile(
    r"\bbye\b|thank|that'?s all|nothing|\bno\b|not interested|\bok(?:ay)?\b|"
    r"బై|థాంక్స్|థ్యాంక్స్|ధన్యవాద|లేదు|వద్దు|అంతే|సరే|"
    r"नहीं|बस|धन्यवाद|शुक्रिया|ठीक है|बाय",
    re.IGNORECASE,
)
#: A caller line that asks or complains, which is never a close however it ends.
_CALLER_ASKS: Final = re.compile(
    r"\?|ఎందుకు|ఏంటి|ఎలా|ఎప్పుడు|ఎక్కడ|\bwhy\b|\bwhat\b|\bhow\b|\bwhen\b|\bwhere\b|"
    r"क्यों|क्या|कैसे|कब|कहाँ",
    re.IGNORECASE,
)
_ASKS_REPEAT: Final = re.compile(
    r"repeat|again|once more|pardon|మళ్ళా|మళ్ళీ|మళ్లీ|మరలా|ఇంకోసారి|फिर से|दोबारा|एक बार और",
    re.IGNORECASE,
)


#: Asking whether now suits, which an opening of ours asks itself ("ఇప్పుడు రెండు నిమిషాలు
#: మాట్లాడొచ్చా?").
_ASKS_IF_NOW_SUITS: Final = re.compile(
    r"good time|(?:is|if) (?:now|this) (?:a good time|ok|okay|fine)|can (?:you|we) talk|"
    r"free to talk|(?:got|have) a (?:minute|moment)|"
    r"మాట్లాడొచ్చా|మాట్లాడవచ్చా|మాట్లాడగలరా|మాట్లాడటం కుదురుతుందా|మాట్లాడడం కుదురుతుందా|"
    r"మాట్లాడటానికి (?:సమయం|టైమ్|వీలు)|ఇప్పుడు కుదురుతుందా|ఫ్రీగా ఉన్నారా|"
    r"बात कर सकते|बात कर सकती|अभी बात|बात करने का (?:समय|टाइम)|सही समय",
    re.IGNORECASE,
)


def opened_again(reply: str) -> str | None:
    """Why the first reply after the opening starts the call over, or None: a second greeting,
    or asking again whether now is a good time (D-864). The opening already greeted, so a
    reply that opens with a greeting is a second hello. A reply that says who the agent is
    ("నేను ... మాట్లాడుతున్నాను", the AI notice's introduction, D-865) is not a greeting: it is
    the answer to "who is this?"."""
    if opens_with_greeting(reply):
        return "It greeted the caller again, though its opening had already greeted them."
    if _ASKS_IF_NOW_SUITS.search(reply):
        return (
            "It asked again whether now is a good time to talk. Its opening already asked; "
            "after the caller's reply it should go on to why it is calling or its first "
            "question."
        )
    return None


def claims_done(text: str) -> bool:
    """Does this agent line say something was done (placed, saved, booked, sent)?"""
    return bool(_CLAIMS_DONE.search(text))


#: The agent saying it already told the caller something: "as I said", "చెప్పాను కదా",
#: "ముందే చెప్పాను", "मैंने बताया था". The caller's own "మీరు చెప్పినట్టు" (as you said) is not one.
_SAID_BEFORE: Final = re.compile(
    r"\b(?:as|like) i (?:said|told you|mentioned)\b|\bi (?:already |just )?(?:told|said to) you\b"
    r"|\bi (?:already |just )?mentioned\b"
    r"|చెప్పాను\s*(?:కదా|కద|గా)|(?:ముందే|ఇందాకే?|ఇంతకు ముందే?)\s+(?:\S+\s+){0,3}చెప్పాను"
    r"|मैंने (?:पहले |अभी )?(?:ही )?(?:बताया|कहा)"
    r"|बताया था (?:ना|न)",
    re.IGNORECASE,
)
_PRICE_WORD: Final = re.compile(
    r"rupee|rupees|price|ధర|రూపాయ\S*|रुपय\S*|रुपए|रुपये|कीमत|दाम", re.IGNORECASE
)


def claims_said_before(text: str) -> bool:
    """Does this agent line say it already told the caller something?"""
    return bool(_SAID_BEFORE.search(text))


def _fact_words(sentence: str) -> set[str]:
    """The words of a sentence that carry a fact a caller could be wrong-footed by: digits,
    number words and price words."""
    numbers = re.compile(f"(?:{_EN_NUMBER}|{_TE_NUMBER}|{_HI_NUMBER})", re.IGNORECASE)
    return {
        w
        for w in _words(sentence)
        if any(ch.isdigit() for ch in w) or numbers.fullmatch(w) or _PRICE_WORD.fullmatch(w)
    }


def _false_recall(reply: str, said_before: str) -> str | None:
    """The sentence of `reply` that claims it already said a figure no earlier reply said, or
    None. Only figures count (a number or a price), so "as I said, we deliver" about a line
    in the greeting, which a test conversation does not show, is left alone."""
    earlier = set(_words(said_before))
    for sentence in sentences(reply):
        if claims_said_before(sentence) and _fact_words(sentence) - earlier:
            return sentence
    return None


def _asks_for_number(reply: str) -> bool:
    return any(
        _PHONE_NUMBER.search(s) and _ASKS_FOR.search(s) and not _SAME_NUMBER.search(s)
        for s in sentences(reply)
    )


def _digit_count(text: str) -> int:
    """Digits a caller line gives towards a phone number. Fewer than three is a quantity or
    a time ("2 kg"), not part of a number."""
    count = sum(ch.isdigit() for ch in text) + len(_DIGIT_WORD.findall(text))
    return count if count >= 3 else 0


def _same_reply(a: str, b: str) -> bool:
    left, right = _words(a), _words(b)
    if not left or not right:
        return False
    if left == right:
        return True
    shared = len(set(left) & set(right)) / max(len(set(left)), len(set(right)))
    return shared >= 0.9 and abs(len(left) - len(right)) <= max(2, len(left) // 10)


#: Where a caller could have found the business, each by the spellings a reply uses. Only
#: places that are not this call: WhatsApp is left out because an agent may rightly offer it.
_CHANNELS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"web\s?site|వెబ్\s*సైట్|వెబ్‌సైట్|वेबसाइट|वेब साइट",
        r"facebook|ఫేస్\s*బుక్|ఫేస్‌బుక్|फेसबुक|फ़ेसबुक",
        r"instagram|ఇన్‌స్టా|ఇన్స్టా|इंस्टा",
        r"google|గూగుల్|गूगल",
        r"magic\s?bricks|99\s?acres|housing\.com|just\s?dial|మ్యాజిక్\s*బ్రిక్స్|జస్ట్\s*డయల్",
    )
)
#: The caller as the subject: "you", "మీరు", "आपने".
_YOU: Final = re.compile(r"\byou\b|\byour\b|మీరు|మీ\s|आपने|आप\s", re.IGNORECASE)


def _invented_source(reply: str, known: str) -> str | None:
    """The sentence of `reply` that tells the caller about a website or listing ("you
    enquired on our website", "see the flats on our website") when nothing in `known` (what
    the caller said, the agent's facts and script) names it, or None. A question ("did you
    see us on Google?") asks rather than tells, so it is left alone."""
    for sentence in sentences(reply):
        if _is_question(sentence) or not _YOU.search(sentence):
            continue
        for channel in _CHANNELS:
            if channel.search(sentence) and not channel.search(known):
                return sentence
    return None


def memory_not_said(exchanges: Sequence[Exchange], memory_notice: str) -> str | None:
    """Why a conversation that ended on the agent's goodbye is missing the memory sentence,
    or None (D-865). Only a goodbye after the caller closed counts; the sentence is matched
    after the same normalisation the disclosure evidence uses, so punctuation and spacing do
    not decide it."""
    sentence = normalize_utterance(memory_notice)
    replied = [e for e in exchanges if e.reply.strip()]
    if not sentence or not replied:
        return None
    last = replied[-1]
    closes = _CALLER_CLOSES.search(last.said) and not _CALLER_ASKS.search(last.said)
    if not _GOODBYE.search(last.reply) or not closes:
        return None
    if sentence in normalize_utterance(last.reply):
        return None
    return (
        "It said goodbye without saying that it keeps a short note of the call. An agent that "
        "remembers callers says its memory sentence once with its goodbye."
    )


def conversation_problems(
    exchanges: Sequence[Exchange],
    *,
    number_known: bool = True,
    memory_notice: str = "",
    known: str = "",
) -> list[TurnProblem]:
    """The problems only a whole conversation shows, each kind once, in order.

    `number_known` is False only for a call whose number the network hid (D-746), where
    asking for a number is right. `memory_notice` is the sentence the closing goodbye must
    carry, empty where none is owed (D-865). `known` is what the agent was given (its
    script and facts), which may say where its callers come from (D-888).
    """
    found: dict[str, TurnProblem] = {}
    acted = False
    caller_raised_number = False
    awaiting: int | None = None  # digits given since the agent asked for a number
    previous_reply = ""
    said_before = ""
    caller_lines = ""
    searched = False
    for exchange in exchanges:
        said, reply = exchange.said, exchange.reply
        acted = acted or any(not _LOOKUP_TOOL.search(tool) for tool in exchange.tools)
        caller_raised_number = caller_raised_number or bool(
            _PHONE_NUMBER.search(said) or _OTHER_NUMBER.search(said)
        )
        if awaiting is not None:
            awaiting += _digit_count(said)
        elif _PHONE_NUMBER.search(said) or _OTHER_NUMBER.search(said):
            awaiting = _digit_count(said)
        if not reply.strip():
            continue
        restarted = None if previous_reply else opened_again(reply)
        if restarted:
            found.setdefault("opened_again", TurnProblem("opened_again", restarted))
        recalled = _false_recall(reply, said_before)
        if recalled:
            found.setdefault(
                "false_recall",
                TurnProblem(
                    "false_recall",
                    f"It said it had already told the caller {_quoted(recalled)}, but it had "
                    "not said that earlier. It must never present a figure as agreed.",
                ),
            )
        said_before = f"{said_before} {reply}"
        caller_lines = f"{caller_lines} {said}"
        # After a knowledge search the reply may be quoting what it found, which `known`
        # does not hold, so only a reply with nothing looked up is judged.
        searched = searched or any(_LOOKUP_TOOL.search(tool) for tool in exchange.tools)
        invented = None if searched else _invented_source(reply, f"{known} {caller_lines}")
        if invented:
            found.setdefault(
                "invented_source",
                TurnProblem(
                    "invented_source",
                    f"It named a website or listing to the caller, {_quoted(invented)}, that "
                    "neither the caller nor its facts mentioned. It says only what its facts "
                    "or the caller said.",
                ),
            )
        if claims_done(reply) and not acted:
            found.setdefault(
                "unconfirmed_action",
                TurnProblem(
                    "unconfirmed_action",
                    "It said something was done (saved, noted, booked or sent) when none of "
                    "its actions did it. It should say what happens next instead.",
                ),
            )
        if (
            awaiting is not None
            and 0 < awaiting < MOBILE_DIGITS
            and (_WRAPS_UP.search(reply) or claims_done(reply) or _GOODBYE.search(reply))
        ):
            found.setdefault(
                "partial_number",
                TurnProblem(
                    "partial_number",
                    f"It took {awaiting} digits as a whole phone number. A mobile number "
                    "has ten; it should ask for the rest and read it back.",
                ),
            )
        if number_known and not caller_raised_number and _asks_for_number(reply):
            found.setdefault(
                "asked_known_number",
                TurnProblem(
                    "asked_known_number",
                    "It asked for a phone number it already has, the one this call is on. "
                    "At most it may ask whether to use this same number.",
                ),
            )
        closes = _CALLER_CLOSES.search(said) and not _CALLER_ASKS.search(said)
        if _GOODBYE.search(reply) and said.strip() and not closes:
            found.setdefault(
                "goodbye_while_asking",
                TurnProblem(
                    "goodbye_while_asking",
                    "It said goodbye while the caller was still talking or asking something.",
                ),
            )
        if previous_reply and _ASKS_REPEAT.search(said) and _same_reply(reply, previous_reply):
            found.setdefault(
                "repeated_turn",
                TurnProblem(
                    "repeated_turn",
                    "Asked to say it again, it repeated the whole turn word for word. It "
                    "should say it again shorter and simpler.",
                ),
            )
        # Digits keep adding up while the number is taken a few at a time ("and the rest?");
        # a reply that wraps up ends it.
        if _asks_for_number(reply):
            awaiting = awaiting or 0
        elif awaiting is not None and (
            _WRAPS_UP.search(reply) or claims_done(reply) or _GOODBYE.search(reply)
        ):
            awaiting = None
        previous_reply = reply
    unsaid = memory_not_said(exchanges, memory_notice)
    if unsaid:
        found.setdefault("memory_not_said", TurnProblem("memory_not_said", unsaid))
    return list(found.values())


__all__ = [
    "JOB_KINDS",
    "MAX_SENTENCES",
    "MOBILE_DIGITS",
    "SOUND_KINDS",
    "Exchange",
    "TurnProblem",
    "claims_done",
    "claims_said_before",
    "conversation_problems",
    "formal_swaps",
    "memory_not_said",
    "opened_again",
    "sentences",
    "turn_problems",
]

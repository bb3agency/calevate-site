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
reply before the AI judge reads it, and by the in-call model comparison
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
from dataclasses import dataclass
from typing import Final, Literal

from calevate_shared.spoken_style import style_for

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
]

#: Problems only the platform can fix (the model reading out context or notes); the rest
#: are the agent's speaking style, which the owner's script and examples influence.
PLATFORM_KINDS: Final = frozenset({"brackets", "time"})

#: A turn's sentences, at most, unless the caller asked for detail (founder, 11 Oct 2026).
MAX_SENTENCES: Final = 2
#: Words a sentence needs to count towards `MAX_SENTENCES`: "Sure." or "సరే అండి." is a
#: courtesy, not a second point.
MIN_COUNTED_WORDS: Final = 3
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
_SENTENCE_END: Final = re.compile(r"(?:(?<=[.!?।\uff1f])|(?<=[.!?।\uff1f][\])\"'”\u2019]))\s+")
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
#: Indic letters carry combining marks, so `\b` does not mark a word start: a formal word
#: counts when it opens the reply or follows a space or punctuation.
_WORD_START: Final = r"(?:^|(?<=[\s,.!?;:\"'(।]))"


def sentences(reply: str) -> list[str]:
    """The reply split into sentences, an abbreviation's full stop not counting as an end."""
    out: list[str] = []
    for piece in _SENTENCE_END.split(" ".join(reply.split())):
        if out and _ABBREVIATION.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        elif piece:
            out.append(piece)
    return out


def formal_swaps(reply: str, language: str) -> list[tuple[str, str]]:
    """(formal word, what people say instead) for each word of the language's spoken-style
    list (`spoken_style.json`) this reply used, in the list's order."""
    style = style_for(language)
    if style is None or not reply:
        return []
    return [
        (formal, spoken)
        for formal, spoken in style.word_swaps
        if re.search(_WORD_START + re.escape(formal), reply)
    ]


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


def _formal_problem(reply: str, language: str) -> TurnProblem | None:
    swaps = formal_swaps(reply, language)
    if not swaps:
        return None
    said = "; ".join(
        f"“{formal}” ({spoken.strip('()') if spoken.startswith('(') else f'say “{spoken}”'})"
        for formal, spoken in swaps
    )
    return TurnProblem("formal_words", f"It used textbook words callers do not say: {said}.")


def _question_problems(parts: list[str]) -> list[TurnProblem]:
    found: list[TurnProblem] = []
    questions = [s for s in parts if _is_question(s)]
    if any(_same_question(a, b) for i, a in enumerate(questions) for b in questions[i + 1 :]):
        found.append(
            TurnProblem(
                "repeated_question",
                "It asked the same question more than once in one reply. It should ask once "
                "and wait.",
            )
        )
    elif len(questions) > 1:
        found.append(
            TurnProblem(
                "several_questions",
                f"It asked {len(questions)} questions in one reply. It should ask one and wait "
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


def turn_problems(reply: str, *, caller_said: str = "", language: str = "") -> list[TurnProblem]:
    """Every problem in one agent reply, the platform's first. `caller_said` is the caller's
    line this reply answers; it decides whether a longer reply was asked for. `language`
    selects the spoken-style word list; without it the formal-word check is skipped."""
    if not reply.strip():
        return []
    found = _symbol_problems(reply)
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
        if own:
            found.append(
                TurnProblem(
                    "caller_line",
                    f"It said the caller's part ({_quoted(own)}) as if the caller had answered.",
                )
            )
    found += _question_problems(parts)
    counted = [s for s in parts if len(_words(s)) >= MIN_COUNTED_WORDS]
    if len(counted) > MAX_SENTENCES and not _ASKS_DETAIL.search(caller_said):
        found.append(
            TurnProblem(
                "too_long",
                f"It said {len(counted)} sentences in one turn. Keep a turn to one or two "
                "short sentences unless the caller asks for detail.",
            )
        )
    return found


__all__ = [
    "MAX_SENTENCES",
    "PLATFORM_KINDS",
    "TurnProblem",
    "formal_swaps",
    "sentences",
    "turn_problems",
]

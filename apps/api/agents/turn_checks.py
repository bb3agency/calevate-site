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
from datetime import date, timedelta
from typing import Final, Literal, Protocol

from calevate_shared.call_words import say as _say
from calevate_shared.call_words import words as _word_list
from calevate_shared.spoken_guard import opens_with_greeting, textbook_note, textbook_words
from calevate_shared.spoken_style import style_for

from apps.api.agents.script_lint import CapabilityManifest, unbacked_promise

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
    # again, in the first reply after the opening; a salutation mid-reply later on (D-910).
    "opened_again",
    # D-888: "you enquired on our website", which neither the caller nor the facts said.
    "invented_source",
    # D-894: the same short reaction ("మంచిది అండి", "సరే అండి") before reply after reply.
    "same_opening",
    # D-910: an unanswered question asked again word for word after the caller's "సరే".
    "asked_again",
    # The Sri Estates call of 28 Oct 2026 (D-912): "two BHK or three BHK?", an unclear
    # answer taken as one of them, and "I'll speak slowly from now on".
    "offered_numbers",
    "picked_for_them",
    "promised_pace",
    # D-945 (the call of 30 Oct 2026): "who is this?" answered and a question stacked on it.
    "stacked_after_who",
    # D-945: a name the caller already gave asked for again.
    "reasked_name",
    # D-945: a promise of what the account cannot do (`agents/script_lint.unbacked_promise`).
    "unbacked_promise",
    # D-945: a weekday said with a date it does not fall on, in IST.
    "wrong_weekday",
    # D-947 (the Sri Estates call of 30 Oct 2026): one sentence said again on the same call.
    "said_again",
    # D-959 (the Rytu Khata call of 2 Nov 2026): "anything else?" reply after reply while the
    # caller was still in the middle of a task.
    "offered_more_too_soon",
    # The Rytu Khata call of 2 Nov 2026: "you enquired with us before" to someone with no
    # earlier enquiry or call on file.
    "false_history",
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
        # HOW TO SPEAK decides how a turn opens, not the owner's script (D-894).
        "same_opening",
        "asked_again",
        # HOW TO SPEAK decides these (D-912). `picked_for_them` stays a note because "the
        # bigger one" is a fair answer to "two or three?" that no word list reads.
        "offered_numbers",
        "picked_for_them",
        "promised_pace",
        # START OF THE CALL decides it (D-945), not the owner's script.
        "stacked_after_who",
        # NAME_RULE decides it; a note, because "is that Ravi?" confirming a name reads alike.
        "reasked_name",
        # HOW TO SPEAK decides it (D-959); a note, because a caller who keeps asking new
        # things can fairly be offered more twice in three turns.
        "offered_more_too_soon",
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
        "false_history",
        "unbacked_promise",
        "wrong_weekday",
        # A fail, not a sound note like `asked_again` (D-947): on the call of 30 Oct 2026 the
        # same line four times ended the call with nothing gained, which is the task lost.
        "said_again",
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
#: marks. 14 let a 12-word Telugu run through on the founder's call of 28 Oct 2026 and he heard
#: the call as unpunctuated; 10 still passes a plain nine-word English sentence. A choice of
#: ours, not a measured threshold.
BREATH_MAX_WORDS: Final = 10
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
    re.compile(_say("turn_checks._TIME_PHRASES"), re.IGNORECASE),
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
    _say("turn_checks._LABEL"),
    re.IGNORECASE,
)
_QUANTITY: Final = re.compile(
    _say("turn_checks._QUANTITY"),
    re.IGNORECASE,
)
#: How a caller ends an order: "please" in English, "give" or "want" in Telugu and Hindi.
_ORDER_ENDING: Final = re.compile(
    _say("turn_checks._ORDER_ENDING"), re.IGNORECASE
)
_OR: Final = re.compile(_say("turn_checks._OR"), re.IGNORECASE)
#: What a caller says when they want more than a short answer.
_ASKS_DETAIL: Final = re.compile(
    _say("turn_checks._ASKS_DETAIL"),
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
_TE_YES_NO_ENDINGS: Final = _word_list("turn_checks._TE_YES_NO_ENDINGS")
_HI_QUESTION: Final = re.compile(_say("turn_checks._HI_QUESTION"))
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
    list(_word_list("turn_checks._FILLER"))
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
_TE_JOINED_ONE: Final = _say("turn_checks._TE_JOINED_ONE")
#: A unit right after the number the agent supplied ("ఒక కేజీ", "one kg").
_UNIT: Final = re.compile(
    _say("turn_checks._UNIT"),
    re.IGNORECASE,
)


#: Telugu number forms that need a noun after them: "ఒక" (a, one) and "అర" (half). The
#: standalone answers are "ఒకటి" and "అర కేజీ", so a line ending on one of these was cut. A
#: bare "two" or "రెండు" answering "how many?" is complete, so other numbers are left alone.
_NEEDS_A_NOUN: Final = frozenset(set(_word_list("turn_checks._NEEDS_A_NOUN")))


def _number_word(word: str) -> str | None:
    """The noun-needing number a caller's last word ends on, or None."""
    if word.endswith(_TE_JOINED_ONE):
        return _say("turn_checks._number_word")
    return word if word in _NEEDS_A_NOUN else None


#: Words a caller's line cannot end on unless the turn timer cut it ("మాకు", "to us").
_DANGLING: Final = frozenset(set(_word_list("turn_checks._DANGLING")))
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
_RESTATES: Final = frozenset(set(_word_list("turn_checks._RESTATES")))


#: A question asking leave to say something ("would you like to know the price?"), which costs
#: the caller a turn: on four calls of 20-22 Oct 2026 the agent asked it instead of the price.
_ASKS_TO_TELL: Final = re.compile(
    _say("turn_checks._ASKS_TO_TELL"),
    re.IGNORECASE,
)


def _restates(question: str) -> bool:
    words = _words(question)
    return bool(words) and words[0] in _RESTATES


#: A joiner that adds a second question inside one sentence: "మీరు ఏ ఏరియాలో చూస్తున్నారు,
#: అలాగే మీ బడ్జెట్ ఎంత?" has one "?" and asks two things (D-910). Only explicit "and"
#: words, never a bare comma or "or": "పొద్దున వీలవుతుందా, సాయంత్రమా?" is one choice.
_ALSO: Final = re.compile(_say("turn_checks._ALSO"), re.IGNORECASE)
_EN_WH: Final = frozenset({"what", "which", "where", "when", "how", "who", "whom", "why"})
#: Telugu question words. "ఏ" (which) only as a whole word: ఏరియా starts with the same letter.
_TE_WH_EXACT: Final = frozenset(set(_word_list("turn_checks._TE_WH_EXACT")))
_TE_WH_STEMS: Final = _word_list("turn_checks._TE_WH_STEMS")
_HI_WH: Final = frozenset(
    set(_word_list("turn_checks._HI_WH"))
)


def _asks_wh(clause: str) -> bool:
    return any(
        w in _EN_WH or w in _TE_WH_EXACT or w in _HI_WH or w.startswith(_TE_WH_STEMS)
        for w in _words(clause)
    )


def _joined_questions(question: str) -> int:
    """How many questions one "?" sentence asks: its "and"-joined parts that each carry a
    question word, at least one."""
    return max(1, sum(1 for clause in _ALSO.split(question) if _asks_wh(clause)))


def _question_problems(parts: list[str]) -> list[TurnProblem]:
    found: list[TurnProblem] = []
    questions = [s for s in parts if _is_question(s)]
    asked = [
        q
        for i, q in enumerate(questions)
        if i == 0 or not _restates(q)
        for _ in range(_joined_questions(q))
    ]
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
    # A choice of numbers checking what the caller just said ("one crore or two?") is a
    # read-back; one offered before they said any is steering (D-888, D-912).
    offered = (
        None
        if _number_values(caller_said)
        else next((s for s in parts if _offered_numbers(s)), None)
    )
    if offered:
        found.append(
            TurnProblem(
                "offered_numbers",
                f"It offered numbers to choose from ({_quoted(offered)}) for a count or an "
                "amount the caller decides. It should ask openly, with no examples.",
            )
        )
    promise = next((s for s in parts if _PACE_PROMISE.search(s)), None)
    if promise:
        found.append(
            TurnProblem(
                "promised_pace",
                f"It promised to talk slower ({_quoted(promise)}), which it cannot do: the "
                "voice's speed is a setting. It should say sorry once and go on in shorter "
                "sentences.",
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
    _say("turn_checks._TE_NUMBER")
)
_HI_NUMBER: Final = (
    _say("turn_checks._HI_NUMBER")
)
#: A price in the language's own number words ("ఆరు నూరు రూపాయలు"). A problem only where the
#: language's `prices` number rule says the English way (`LanguageStyle.native_price_words`):
#: Telugu's does ("six hundred rupees", as shops in Hyderabad say it, D-744), Hindi's allows
#: "एक सौ बीस रुपये".
#: Telugu's also catches a big amount in Telugu number words ("రెండు కోట్ల"), which its
#: `lakhs` rule says the English way, written in Telugu letters ("టూ క్రోర్స్", D-861). A
#: time in Telugu number words ("రెండు గంటలకు") is how people say a time and is not flagged.
_NATIVE_PRICE: Final[dict[str, re.Pattern[str]]] = {
    "te": re.compile(
        rf"(?:(?:{_TE_NUMBER})\s+)*(?:{_TE_NUMBER})\s*(?:{_say('turn_checks._NATIVE_PRICE.te')})"
    ),
    "hi": re.compile(
        rf"(?:(?:{_HI_NUMBER})\s+)*(?:{_HI_NUMBER})\s*(?:{_say('turn_checks._NATIVE_PRICE.hi')})"
    ),
}
#: Digits beside a unit written in an Indian script ("1 కిలో"), which `_MONEY_DIGITS` (Latin
#: units only) does not see.
_DIGIT_UNIT: Final = re.compile(
    _say("turn_checks._DIGIT_UNIT")
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
            _say("turn_checks._script_and_number_problems")
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
    _say("turn_checks._CLAIMS_DONE"),
    re.IGNORECASE,
)
#: Tools that only look something up, so they confirm nothing was done.
_LOOKUP_TOOL: Final = re.compile(r"knowledge|search|lookup|look_up", re.IGNORECASE)
_PHONE_NUMBER: Final = re.compile(
    _say("turn_checks._PHONE_NUMBER"),
    re.IGNORECASE,
)
_ASKS_FOR: Final = re.compile(
    _say("turn_checks._ASKS_FOR"),
    re.IGNORECASE,
)
#: "Shall we use this same number?" is the one question about a number the platform allows.
_SAME_NUMBER: Final = re.compile(
    _say("turn_checks._SAME_NUMBER"),
    re.IGNORECASE,
)
#: The caller wants a number other than the one the call is on.
_OTHER_NUMBER: Final = re.compile(
    _say("turn_checks._OTHER_NUMBER"),
    re.IGNORECASE,
)
#: One digit said as a word: English, English in Telugu letters (how our agents write it,
#: D-861), Telugu and Hindi. A caller says "తొమ్మిది ఎనిమిది ఏడు ఆరు" as often as "9876".
_DIGIT_WORDS: Final = frozenset(
    {
        *("zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
        *_word_list("turn_checks._DIGIT_WORDS.1"),
        *_word_list("turn_checks._DIGIT_WORDS.2"),
        _say("turn_checks._DIGIT_WORDS.3"),
        *_word_list("turn_checks._DIGIT_WORDS.4"),
    }
)
#: A mobile number in India has ten digits.
MOBILE_DIGITS: Final = 10
#: A reply asking for the rest of a number in words. A bare "?" is not one: "is this number
#: right?" after four digits is a question too (D-910).
_ASKS_FOR_REST: Final = re.compile(
    _say("turn_checks._ASKS_FOR_REST"),
    re.IGNORECASE,
)
#: A reply asking whether what it read back is right: what it does with a WHOLE number, and
#: never with part of one.
_CONFIRMS: Final = re.compile(
    _say("turn_checks._CONFIRMS"),
    re.IGNORECASE,
)
#: What a reply says when it treats what it was given as complete.
_WRAPS_UP: Final = re.compile(
    _say("turn_checks._WRAPS_UP"),
    re.IGNORECASE,
)
#: Offering more help, "anything else?" in each language our agents speak. Detection only,
#: never spoken copy; read in a question, so "call if you need anything else." closing a
#: call is not one.
_OFFERS_MORE: Final = re.compile(
    _say("turn_checks._OFFERS_MORE"),
    re.IGNORECASE,
)
#: Within how many replies two offers of more help count as too many (D-959).
OFFERS_MORE_WINDOW: Final = 3
#: A caller line that thanks or says they are done, after which offering more is right.
_CALLER_DONE_WITH_TOPIC: Final = re.compile(
    _say("turn_checks._CALLER_DONE_WITH_TOPIC"),
    re.IGNORECASE,
)


def offers_more(reply: str) -> bool:
    """Whether a reply asks if the caller wants anything else."""
    return any(
        _OFFERS_MORE.search(s) for s in sentences(reply) if _is_question(s) or _reads_as_question(s)
    )


_GOODBYE: Final = re.compile(
    _say("turn_checks._GOODBYE"),
    re.IGNORECASE,
)
#: A caller line that closes the conversation, after which a goodbye is right.
_CALLER_CLOSES: Final = re.compile(
    _say("turn_checks._CALLER_CLOSES"),
    re.IGNORECASE,
)
#: WHETHER A LINE ASKS SOMETHING (L5-05, 5 Nov 2026). Matching a question word anywhere made
#: "I will try when I get time" and "ok I will try what you said" questions, and matching a
#: Telugu question word as a substring made "somehow" and "somewhere" questions, because
#: Telugu forms those words by adding to the question word. So: a "?"; an English question,
#: which starts its clause with an interrogative, an auxiliary before its subject, or a
#: request to be told; or a question word from `call_words.json` standing as a whole word,
#: which in Telugu and Hindi can sit anywhere in the clause. A Telugu question word with a
#: case ending fused to it ("how much" + "for") is not seen until the founder lists that
#: form: missing a question costs one gap, inventing one put a false gap on the owner's list.
_QUESTION_WORDS: Final = frozenset(w.lower() for w in _word_list("turn_checks.question_words"))
_EN_INTERROGATIVES: Final = frozenset(
    {"what", "when", "where", "which", "who", "whom", "whose", "why", "how"}
)
_EN_AUXILIARIES: Final = frozenset(
    {
        *("do", "does", "did", "can", "could", "will", "would", "shall", "should", "may"),
        *("is", "are", "was", "were", "have", "has", "am"),
    }
)
_EN_SUBJECTS: Final = frozenset(
    {"you", "i", "we", "they", "it", "there", "he", "she", "this", "that", "the", "your", "my"}
)
_EN_ASKS_TO_BE_TOLD: Final = re.compile(
    r"^(?:please\s+)?(?:tell me|let me know|explain)\b"
    r"|^i\s+(?:want|wanted|need|would like)\s+to\s+know\b|^can\s+i\s+know\b",
    re.IGNORECASE,
)
#: Words a clause may open with before its question: "ok, what…", "so how…".
_EN_OPENERS: Final = frozenset(
    {"ok", "okay", "so", "and", "but", "then", "well", "oh", "hello", "hi", "sir", "madam"}
)
_CLAUSES: Final = re.compile(r"[.,!;:।]+|\s+(?:and|but|so)\s+", re.IGNORECASE)
#: A word: a run of anything but space and punctuation, so a Telugu or Devanagari word stays
#: whole with its vowel signs (which `\w` does not count as word characters).
_TOKEN: Final = re.compile(r"[^\s,.!?;:\"'()।？]+")


def _english_question(clause: str) -> bool:
    words = [w.lower() for w in _TOKEN.findall(clause)]
    while words and words[0] in _EN_OPENERS:
        words.pop(0)
    if not words:
        return False
    if words[0] in _EN_INTERROGATIVES:
        return True
    if words[0] in _EN_AUXILIARIES and len(words) > 1 and words[1] in _EN_SUBJECTS:
        return True
    return bool(_EN_ASKS_TO_BE_TOLD.search(" ".join(words)))


def asks_question(said: str) -> bool:
    """Whether a line asks something: the one question test for the turn checks and the
    knowledge-gap detector (`insights.detection.caller_asked`)."""
    if "?" in said or "？" in said:
        return True
    if any(w.lower() in _QUESTION_WORDS for w in _TOKEN.findall(said)):
        return True
    return any(_english_question(clause) for clause in _CLAUSES.split(said))
#: Asking for it slower, which wants the same words again at a pace they can follow. The
#: Telugu and Hindi words are the ones `_PACE_PROMISE` already reads.
_SLOWER: Final = _say("turn_checks._SLOWER")
#: The caller asking to hear it again: in other words, slower, or because it did not reach
#: them. Saying it again is then the right answer, not `said_again`.
_ASKS_REPEAT: Final = re.compile(
    r"repeat|again|once more|one more time|pardon|come again|"
    r"(?:didn'?t|did not|couldn'?t|could not|can'?t|cannot) (?:hear|catch|get|follow)|"
    r"cut off|breaking up|"
    rf"{_SLOWER}|" + _say("turn_checks._ASKS_REPEAT"),
    re.IGNORECASE,
)
#: A caller line that ends the conversation in so many words, whatever else it holds: "nothing
#: more for now, I'll call you when I'm free" closes although "when" is in it.
_CALLER_SIGNS_OFF: Final = re.compile(
    _say("turn_checks._CALLER_SIGNS_OFF"),
    re.IGNORECASE,
)


def asks_to_repeat(said: str) -> bool:
    """Whether a caller line asks to hear the agent's last words again."""
    return bool(_ASKS_REPEAT.search(said))


def caller_signs_off(said: str) -> bool:
    """Whether a caller line ends the conversation in words, with no "?" to say otherwise."""
    return bool(_CALLER_SIGNS_OFF.search(said)) and "?" not in said


def caller_asks(said: str) -> bool:
    """Whether a caller line asks or complains, as opposed to signing off."""
    return asks_question(said) and not caller_signs_off(said)


#: Asking whether now suits, which an opening of ours asks itself ("ఇప్పుడు రెండు నిమిషాలు
#: మాట్లాడొచ్చా?").
_ASKS_IF_NOW_SUITS: Final = re.compile(
    _say("turn_checks._ASKS_IF_NOW_SUITS"),
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


#: A salutation said as a greeting. Narrower than `opens_with_greeting`: "హలో?" mid-call checks
#: the line is alive, and "నమస్కారం" as a reply's LAST sentence is a goodbye.
_SALUTATION: Final = re.compile(
    _say("turn_checks._SALUTATION"),
    re.IGNORECASE,
)


def greeted_midway(reply: str) -> str | None:
    """Why a later reply starts the call over, or None: a salutation that opens any sentence
    but the reply's last (D-910). On a practice run of 28 Oct 2026 the agent answered "is this
    call recorded?" with "yes, it is recorded. నమస్కారం అండి, calling from ... can we talk
    now?"."""
    parts = sentences(reply)
    if any(_SALUTATION.search(s) for s in parts[:-1]) and not _GOODBYE.search(reply):
        return "It greeted the caller again mid-call and started its opening over."
    return None


def _reopened(reply: str, opening_questions: Sequence[str]) -> str | None:
    """Why a reply asks its opening's question again, or None (D-912). The opening's own
    question is the yardstick, so "can we talk now?" is caught in a language our phrase list
    does not cover too; the phrase list catches a reworded one. A close ("anything else?") is
    never the opening again."""
    if not opening_questions or _WRAPS_UP.search(reply):
        return None
    suits = any(_ASKS_IF_NOW_SUITS.search(q) for q in opening_questions)
    for question in (s for s in sentences(reply) if _is_question(s)):
        if any(_same_question(question, q) for q in opening_questions) or (
            suits and _ASKS_IF_NOW_SUITS.search(question)
        ):
            return (
                f"It asked {_quoted(question)} again, which its opening already asked. After "
                "answering the caller it should go on to its first question."
            )
    return None


#: A number by its value, as callers and our agents say it: English, English in Telugu and
#: Hindi letters (how our agents write it, D-861), Telugu and Hindi. "ఒక" and "एक" are left
#: out because they are also "a": "ఒక రెండు రోజుల్లో" offers no choice of one or two.
_NUMBER_VALUES: Final[dict[str, int]] = {
    word: value
    for words in (
        ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
        _word_list("turn_checks._NUMBER_VALUES.1"),
        _word_list("turn_checks._NUMBER_VALUES.2"),
        _word_list("turn_checks._NUMBER_VALUES.3"),
        _word_list("turn_checks._NUMBER_VALUES.4"),
    )
    for value, word in enumerate(words)
    if word
} | {_say("turn_checks._NUMBER_VALUES.5"): 5, _say("turn_checks._NUMBER_VALUES.6"): 5}
_DIGITS: Final = re.compile(r"\d+")
#: Words that make a choice of numbers a choice of times, which HOW TO SPEAK allows.
_TIME_WORDS: Final = re.compile(
    _say("turn_checks._TIME_WORDS"),
    re.IGNORECASE,
)
#: What joins the options of a choice: "or" in a word, or one ending said twice
#: ("టూ బీహెచ్కే కావాలా, త్రీ బీహెచ్కే కావాలా?", "టూ నా త్రీ నా?").
_EITHER: Final = re.compile(_say("turn_checks._EITHER"), re.IGNORECASE)


def _number_values(text: str) -> set[int]:
    values = {int(d) for d in _DIGITS.findall(text)}
    return values | {_NUMBER_VALUES[w] for w in _words(text) if w in _NUMBER_VALUES}


def _offered_numbers(question: str) -> set[int]:
    """The numbers a question offers to choose from ("two BHK or three BHK?"), or an empty
    set: two or more values, joined as a choice, and not a choice of times."""
    if not _is_question(question) or _TIME_WORDS.search(question):
        return set()
    values = _number_values(question)
    if len(values) < 2:
        return set()
    endings = [w for w in _words(question) if w.endswith(_say("turn_checks._offered_numbers"))]
    if _EITHER.search(question) or len(endings) != len(set(endings)):
        return values
    return set()


#: Promising to talk slower, which the model cannot do: the voice's speed is the agent's
#: setting (D-884, D-912).
_PACE_PROMISE: Final = re.compile(
    _say("turn_checks._PACE_PROMISE"),
    re.IGNORECASE,
)


#: Words a sentence needs before saying it again counts as `said_again`: "సరే అండి." or
#: "Thank you." twice is ordinary speech.
SAID_AGAIN_MIN_WORDS: Final = 4


def _said_again(reply: str, earlier: Sequence[str]) -> str | None:
    """The sentence of `reply` that an earlier reply already said (word for word, or as
    `_same_reply` reads it), or None.

    Two kinds of sentence are left out because saying them again is not a loop: a number
    read out, which a caller writing it down hears more than once (the Rytu Khata call of 4
    Nov 2026 read the business's number three times, each asked for), and "anything
    else?", whose repeats `offered_more_too_soon` judges."""
    return next(
        (
            s
            for s in sentences(reply)
            if len(_words(s)) >= SAID_AGAIN_MIN_WORDS
            and _digit_count(s) < NUMBER_READ_DIGITS
            and not offers_more(s)
            and any(_same_reply(s, b) for b in earlier)
        ),
        None,
    )


#: Digits (or digit words) that make a sentence a number read out rather than a line.
NUMBER_READ_DIGITS: Final = 4


def _closes_call(said: str) -> bool:
    return bool(_CALLER_CLOSES.search(said) or caller_signs_off(said)) and not caller_asks(said)


def _carried_on(exchanges: Sequence[Exchange], position: int) -> bool:
    """Whether the caller said anything after `position` other than closing words: a caller
    who keeps talking after a goodbye was not done."""
    return any(e.said.strip() and not _closes_call(e.said) for e in exchanges[position + 1 :])


def _asked_again(reply: str, previous_reply: str) -> str | None:
    """The question of `reply` that repeats one of `previous_reply` word for word, or None."""
    before = [s for s in sentences(previous_reply) if _is_question(s)]
    return next(
        (q for q in sentences(reply) if _is_question(q) and any(_same_reply(q, b) for b in before)),
        None,
    )


#: A caller saying they have done something themselves, on their own screen: "done", "it's
#: saved", "అయింది", "సేవ్ చేశాను", "हो गया" (D-906). The agent's "saved, good" after that
#: acknowledges the caller's act, which `ACTION_CLAIM_RULE` allows ("or they say they did").
_CALLER_DONE: Final = re.compile(
    _say("turn_checks._CALLER_DONE"),
    re.IGNORECASE,
)
#: What turns a caller's "done" into its opposite: "not done", "కాలేదు", "नहीं हुआ".
_CALLER_NOT: Final = re.compile(
    _say("turn_checks._CALLER_NOT"), re.IGNORECASE
)


def caller_says_done(said: str) -> bool:
    """Does this caller line report something they did themselves? A question or a negative
    never does."""
    return bool(_CALLER_DONE.search(said)) and "?" not in said and not _CALLER_NOT.search(said)


def claims_done(text: str, *, caller_said: str = "") -> bool:
    """Does this agent line say something was done (placed, saved, booked, sent)? Not when it
    follows the caller saying they did it (`caller_says_done`): that acknowledges their act."""
    return bool(_CLAIMS_DONE.search(text)) and not caller_says_done(caller_said)


#: The agent saying it already told the caller something: "as I said", "చెప్పాను కదా",
#: "ముందే చెప్పాను", "मैंने बताया था". The caller's own "మీరు చెప్పినట్టు" (as you said) is not one.
_SAID_BEFORE: Final = re.compile(
    _say("turn_checks._SAID_BEFORE"),
    re.IGNORECASE,
)
_PRICE_WORD: Final = re.compile(
    _say("turn_checks._PRICE_WORD"), re.IGNORECASE
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
    count = sum(ch.isdigit() for ch in text) + sum(w in _DIGIT_WORDS for w in _words(text))
    return count if count >= 3 else 0


def _same_reply(a: str, b: str) -> bool:
    left, right = _words(a), _words(b)
    if not left or not right:
        return False
    if left == right:
        return True
    shared = len(set(left) & set(right)) / max(len(set(left)), len(set(right)))
    return shared >= 0.9 and abs(len(left) - len(right)) <= max(2, len(left) // 10)


#: Where a reply's opening reaction ends: its first comma, full stop or other mark.
#: The full-width comma and question mark are written as escapes (RUF001).
_OPENER_END: Final = re.compile("[,.!?;:\\u0964\\uff0c\\uff1f]")
#: A lead longer than this is the turn's content, never a stock reaction.
_OPENER_MAX_WORDS: Final = 2
#: Replies one reaction may open before it reads as stock (D-894): on the founder's calls of
#: 27 Oct 2026 "మంచిది అండి" or "సరే అండి" came before every next question. Three, not two,
#: because the same "హా" twice in a call is ordinary speech.
STOCK_OPENER_REPLIES: Final = 3


def opener(reply: str) -> str | None:
    """The short reaction a reply opens with ("సరే అండి" of "సరే అండి, ఏ ఏరియా?"), lower
    case, or None when the reply leads with content."""
    head = _OPENER_END.split(" ".join(reply.split()), maxsplit=1)[0]
    words = _words(head)
    if not words or len(words) > _OPENER_MAX_WORDS:
        return None
    return " ".join(words)


def _stock_opener(replies: Sequence[str]) -> tuple[str, int] | None:
    """The first reaction that opens `STOCK_OPENER_REPLIES` or more of `replies`, with its
    count."""
    counts: dict[str, int] = {}
    for reply in replies:
        said = opener(reply)
        if said is not None:
            counts[said] = counts.get(said, 0) + 1
    return next(((said, n) for said, n in counts.items() if n >= STOCK_OPENER_REPLIES), None)


#: Where a caller could have found the business, each by the spellings a reply uses. Only
#: places that are not this call: WhatsApp is left out because an agent may rightly offer it.
_CHANNELS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in _word_list("turn_checks._CHANNELS")
)
#: The caller as the subject: "you", "మీరు", "आपने".
_YOU: Final = re.compile(_say("turn_checks._YOU"), re.IGNORECASE)


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


#: The agent telling the caller about contact before this call: an enquiry they made, a
#: previous call or conversation, "last time". Detection words, not speech (D-915).
_CLAIMS_HISTORY: Final = re.compile(
    _say("turn_checks._CLAIMS_HISTORY"),
    re.IGNORECASE,
)
#: "Earlier you asked": on a call where the caller has asked something, that may be this
#: call, so it counts only before the caller has asked anything.
_ASKED_EARLIER: Final = re.compile(
    _say("turn_checks._ASKED_EARLIER"),
    re.IGNORECASE,
)
#: A sentence that asks about contact before rather than claiming it ("did you enquire?").
_ASKS_ABOUT_IT: Final = re.compile(_say("turn_checks._ASKS_ABOUT_IT"), re.IGNORECASE)
#: An enquiry named in the agent's script or facts: the owner may be saying its callers did
#: enquire, so a claim of it is the owner's word rather than invented.
_ENQUIRY_WORDS: Final = re.compile(_say("turn_checks._ENQUIRY_WORDS"), re.IGNORECASE)
#: Words in the caller's own lines that say there was contact before ("I called last week",
#: "I already enquired"). Broader than the script's, because a caller line is short and
#: about this person, and a false mistake costs more than a missed one.
_CALLER_HISTORY: Final = re.compile(
    _say("turn_checks._CALLER_HISTORY"),
    re.IGNORECASE,
)


def _false_history(reply: str, *, caller_asked: bool) -> str | None:
    """The sentence of `reply` that tells the caller about an enquiry, call or conversation
    before this one, or None. `caller_asked`: the caller has asked something on this call,
    so "earlier you asked" may mean this call and is left alone."""
    for sentence in sentences(reply):
        if _ASKS_ABOUT_IT.search(sentence):
            continue
        if _CLAIMS_HISTORY.search(sentence) or (
            not caller_asked and _ASKED_EARLIER.search(sentence)
        ):
            return sentence
    return None


# --- D-945: who-then-ask, a known name asked again, promises, weekdays --------------------

#: The caller asking who is calling or why.
_ASKS_WHO: Final = re.compile(
    _say("turn_checks._ASKS_WHO"),
    re.IGNORECASE,
)
#: The caller giving their own name.
_GIVES_NAME: Final = re.compile(_say("turn_checks._GIVES_NAME"), re.IGNORECASE)
#: The agent asking for the caller's name.
_ASKS_NAME: Final = re.compile(
    _say("turn_checks._ASKS_NAME"),
    re.IGNORECASE,
)


def _stacked_after_who(caller_said: str, reply: str) -> str | None:
    """The question a reply to "who is this?" asked after answering it (D-945), or None."""
    if not _ASKS_WHO.search(caller_said):
        return None
    parts = sentences(reply)
    if all(_is_question(s) for s in parts):
        return None
    return next((s for s in parts if _is_question(s)), None)


_WEEKDAYS: Final[tuple[tuple[str, ...], ...]] = (
    _word_list("turn_checks._WEEKDAYS.1"),
    _word_list("turn_checks._WEEKDAYS.2"),
    _word_list("turn_checks._WEEKDAYS.3"),
    _word_list("turn_checks._WEEKDAYS.4"),
    _word_list("turn_checks._WEEKDAYS.5"),
    _word_list("turn_checks._WEEKDAYS.6"),
    _word_list("turn_checks._WEEKDAYS.7"),
)
_MONTHS: Final[tuple[tuple[str, ...], ...]] = (
    _word_list("turn_checks._MONTHS.1"),
    _word_list("turn_checks._MONTHS.2"),
    _word_list("turn_checks._MONTHS.3"),
    _word_list("turn_checks._MONTHS.4"),
    _word_list("turn_checks._MONTHS.5"),
    _word_list("turn_checks._MONTHS.6"),
    _word_list("turn_checks._MONTHS.7"),
    _word_list("turn_checks._MONTHS.8"),
    _word_list("turn_checks._MONTHS.9"),
    _word_list("turn_checks._MONTHS.10"),
    _word_list("turn_checks._MONTHS.11"),
    _word_list("turn_checks._MONTHS.12"),
)


def _alternation(groups: tuple[tuple[str, ...], ...]) -> str:
    names = sorted({name for group in groups for name in group}, key=len, reverse=True)
    return "|".join(re.escape(name) for name in names)


_WEEKDAY_WORD: Final = rf"(?<![A-Za-z])({_alternation(_WEEKDAYS)})(?![A-Za-z])"
_MONTH_WORD: Final = rf"(?<![A-Za-z])({_alternation(_MONTHS)})(?![A-Za-z.])"
_DAY_NUMBER: Final = _say("turn_checks._DAY_NUMBER")
_WEEKDAY_THEN_DATE: Final = re.compile(
    rf"{_WEEKDAY_WORD}[,\s]+(?:the\s+)?{_DAY_NUMBER}\s*{_MONTH_WORD}", re.IGNORECASE
)
_DATE_THEN_WEEKDAY: Final = re.compile(
    rf"{_DAY_NUMBER}\s*{_MONTH_WORD}[,\s]+{_WEEKDAY_WORD}", re.IGNORECASE
)
_TOMORROW: Final = _say("turn_checks._TOMORROW")
_TOMORROW_WEEKDAY: Final = re.compile(
    rf"(?<![A-Za-z])(tomorrow|{_TOMORROW})[,\s]+{_WEEKDAY_WORD}"
    rf"|{_WEEKDAY_WORD}[,\s]+(tomorrow|{_TOMORROW})",
    re.IGNORECASE,
)


def _index_of(word: str, groups: tuple[tuple[str, ...], ...]) -> int:
    folded = word.casefold()
    return next(i for i, group in enumerate(groups) if folded in group)


def _date_near(today: date, month: int, day: int) -> date | None:
    """The first `day` of `month` no more than a month before `today`: a date said on a call
    is at most a few weeks back and otherwise ahead. None for a day that month lacks.

    A year that lacks the day is skipped, not taken as the answer: 29 February is missing
    from last year when this one is a leap year."""
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            found = date(year, month, day)
        except ValueError:
            continue
        if found >= today - timedelta(days=31):
            return found
    return None


def wrong_weekday(reply: str, today: date) -> str | None:
    """A weekday said with a date (or with "tomorrow") it does not fall on in the IST
    calendar, quoted, or None (D-945). Only digit dates and named months and weekdays are
    read: a date said in number words is left to the judge."""
    for match in _WEEKDAY_THEN_DATE.finditer(reply):
        weekday, day, month = match.group(1), int(match.group(2)), match.group(3)
        found = _date_near(today, _index_of(month, _MONTHS) + 1, day)
        if found is not None and found.weekday() != _index_of(weekday, _WEEKDAYS):
            return match.group(0)
    for match in _DATE_THEN_WEEKDAY.finditer(reply):
        day, month, weekday = int(match.group(1)), match.group(2), match.group(3)
        found = _date_near(today, _index_of(month, _MONTHS) + 1, day)
        if found is not None and found.weekday() != _index_of(weekday, _WEEKDAYS):
            return match.group(0)
    tomorrow = (today + timedelta(days=1)).weekday()
    for match in _TOMORROW_WEEKDAY.finditer(reply):
        weekday = match.group(2) or match.group(3)
        if _index_of(weekday, _WEEKDAYS) != tomorrow:
            return match.group(0)
    return None


def conversation_problems(
    exchanges: Sequence[Exchange],
    *,
    number_known: bool = True,
    known: str = "",
    opening: str = "",
    manifest: CapabilityManifest | None = None,
    today: date | None = None,
    prior_contact: bool | None = None,
) -> list[TurnProblem]:
    """The problems only a whole conversation shows, each kind once, in order.

    `number_known` is False only for a call whose number the network hid (D-746), where
    asking for a number is right. `known` is what the agent was given (its
    script and facts), which may say where its callers come from (D-888). `opening` is what
    the engine said before the first exchange, when it is not one of `exchanges`: a real
    call's greeting, against which every later reply is judged for asking it again (D-912).
    `manifest` is what the agent can do, against which a promise is judged, and `today` the
    IST date a stated weekday is checked against (D-945); either None skips its check.
    `prior_contact` is whether this person had an enquiry or a call with the business before
    this one; only False judges a reply that claims they did, and None skips it.
    """
    opening_questions = [s for s in sentences(opening) if _is_question(s)]
    offered: set[int] = set()
    found: dict[str, TurnProblem] = {}
    acted = False
    caller_raised_number = False
    awaiting: int | None = None  # digits given since the agent asked for a number
    previous_reply = ""
    earlier_sentences: list[str] = []
    said_before = ""
    caller_lines = ""
    searched = False
    caller_asked = False
    history_backed = prior_contact is not False or bool(
        _CLAIMS_HISTORY.search(known) or _ENQUIRY_WORDS.search(known)
    )
    name_given = False
    offers: list[bool] = []  # one per spoken reply: did it ask "anything else?"
    for position, exchange in enumerate(exchanges):
        said, reply = exchange.said, exchange.reply
        name_given = name_given or bool(_GIVES_NAME.search(said))
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
        restarted = (
            (None if previous_reply else opened_again(reply))
            or greeted_midway(reply)
            or _reopened(reply, opening_questions)
        )
        if restarted:
            found.setdefault("opened_again", TurnProblem("opened_again", restarted))
        offers.append(offers_more(reply) and not _CALLER_DONE_WITH_TOPIC.search(said))
        if offers[-1] and sum(offers[-OFFERS_MORE_WINDOW:]) >= 2:
            found.setdefault(
                "offered_more_too_soon",
                TurnProblem(
                    "offered_more_too_soon",
                    f"It asked whether they needed anything else twice in "
                    f"{OFFERS_MORE_WINDOW} replies. It asks once a topic is done; while the "
                    "caller is in the middle of something, it ends on the next step.",
                ),
            )
        # An answer that names none of the numbers offered ("టీవీహెచ్కే" to "two or three
        # BHK?") taken as one of them.
        picked = (
            None
            if not offered or _number_values(said)
            else next(
                (
                    s
                    for s in sentences(reply)
                    if not _is_question(s) and _number_values(s) & offered
                ),
                None,
            )
        )
        if picked:
            found.setdefault(
                "picked_for_them",
                TurnProblem(
                    "picked_for_them",
                    f"The caller's answer, {_quoted(said)}, named none of the options it offered, "
                    f"and it took one ({_quoted(picked)}). An unclear answer is asked again.",
                ),
            )
        offered = {value for s in sentences(reply) for value in _offered_numbers(s)}
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
        caller_asked = caller_asked or asks_question(said)
        history_backed = history_backed or bool(_CALLER_HISTORY.search(said))
        history = None if history_backed else _false_history(reply, caller_asked=caller_asked)
        if history:
            found.setdefault(
                "false_history",
                TurnProblem(
                    "false_history",
                    f"It told the caller {_quoted(history)}, but there is no earlier enquiry "
                    "or call from them on file. It never says a caller enquired or spoke to "
                    "the business before unless the call's details say so.",
                ),
            )
        stacked = _stacked_after_who(said, reply)
        if stacked:
            found.setdefault(
                "stacked_after_who",
                TurnProblem(
                    "stacked_after_who",
                    f"Asked who is calling, it answered and then asked {_quoted(stacked)}. "
                    "It should say who and why in one line and wait.",
                ),
            )
        if name_given and not _GIVES_NAME.search(said) and _ASKS_NAME.search(reply):
            found.setdefault(
                "reasked_name",
                TurnProblem(
                    "reasked_name",
                    "It asked for the caller's name after the caller had already said it.",
                ),
            )
        promise = None if manifest is None else unbacked_promise(reply, manifest)
        if promise:
            found.setdefault(
                "unbacked_promise",
                TurnProblem(
                    "unbacked_promise",
                    f"It promised {promise}. It should take the details for the team instead.",
                ),
            )
        weekday = None if today is None else wrong_weekday(reply, today)
        if weekday:
            found.setdefault(
                "wrong_weekday",
                TurnProblem(
                    "wrong_weekday",
                    f"It said {_quoted(weekday)}, but that weekday and date do not match. It "
                    "should take dates from the days listed for this call.",
                ),
            )
        if claims_done(reply, caller_said=said) and not acted:
            found.setdefault(
                "unconfirmed_action",
                TurnProblem(
                    "unconfirmed_action",
                    "It said something was done (saved, noted, booked or sent) when none of "
                    "its actions did it. It should say what happens next instead.",
                ),
            )
        # Part of a number is taken as all of it when the reply wraps up on it, reads it back,
        # asks whether it is right, or simply does not ask for the rest: "I'll send it to
        # 9876" (27 Oct 2026) promised an action on four digits, and "తొమ్మిది ఎనిమిది ఏడు
        # ఆరు. ఈ నంబర్ కరెక్టేనా?" (28 Oct 2026, D-910) asked to confirm them.
        if (
            awaiting is not None
            and 0 < awaiting < MOBILE_DIGITS
            and (
                _WRAPS_UP.search(reply)
                or claims_done(reply)
                or _GOODBYE.search(reply)
                or _digit_count(reply)
                or _CONFIRMS.search(reply)
                or not _ASKS_FOR_REST.search(reply)
            )
        ):
            found.setdefault(
                "partial_number",
                TurnProblem(
                    "partial_number",
                    f"It was given {awaiting} digits of a phone number and treated them as "
                    "the number. A mobile number has ten: it should say how many are missing "
                    "and ask for them, never read part of one back or ask to confirm it.",
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
        # A goodbye is wrong after a line that asks, and after one that does not close when
        # the caller carried on talking. Without either, the caller let the call end: a line
        # that closes in words the closing list does not hold ("OK, enough for now") reads
        # as that, never as "still asking" (D-970).
        if (
            _GOODBYE.search(reply)
            and said.strip()
            and (caller_asks(said) or (not _closes_call(said) and _carried_on(exchanges, position)))
        ):
            found.setdefault(
                "goodbye_while_asking",
                TurnProblem(
                    "goodbye_while_asking",
                    "It said goodbye while the caller was still talking or asking something.",
                ),
            )
        # Only after a line that asked nothing ("సరే"): re-asking after answering the caller's
        # own question is how a conversation gets back on track.
        again = (
            None
            if _ASKS_REPEAT.search(said) or asks_question(said)
            else _asked_again(reply, previous_reply)
        )
        if again:
            found.setdefault(
                "asked_again",
                TurnProblem(
                    "asked_again",
                    f"After the caller said {_quoted(said)} it asked {_quoted(again)} again "
                    "word for word. A question left unanswered is asked once more as one "
                    "question, in new words.",
                ),
            )
        # A caller who asks to hear it again is `repeated_turn`'s, judged on the whole turn.
        repeated = None if asks_to_repeat(said) else _said_again(reply, earlier_sentences)
        if repeated:
            found.setdefault(
                "said_again",
                TurnProblem(
                    "said_again",
                    f"After the caller said {_quoted(said)} it said {_quoted(repeated)} again, "
                    "a line it had already said on this call. With no clear reply it tries "
                    "once in other words, then offers what comes next and closes.",
                ),
            )
        earlier_sentences += sentences(reply)
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
    stock = _stock_opener([e.reply for e in exchanges if e.reply.strip()])
    if stock:
        said, times = stock
        found.setdefault(
            "same_opening",
            TurnProblem(
                "same_opening",
                f"It opened {times} replies with {_quoted(said)}. A reaction should fit what "
                "the caller said, and is often not needed at all.",
            ),
        )
    return list(found.values())


__all__ = [
    "JOB_KINDS",
    "MAX_SENTENCES",
    "MOBILE_DIGITS",
    "NUMBER_READ_DIGITS",
    "OFFERS_MORE_WINDOW",
    "SOUND_KINDS",
    "Exchange",
    "TurnProblem",
    "asks_to_repeat",
    "asks_question",
    "caller_asks",
    "caller_says_done",
    "caller_signs_off",
    "claims_done",
    "claims_said_before",
    "conversation_problems",
    "formal_swaps",
    "greeted_midway",
    "offers_more",
    "opened_again",
    "sentences",
    "turn_problems",
    "wrong_weekday",
]

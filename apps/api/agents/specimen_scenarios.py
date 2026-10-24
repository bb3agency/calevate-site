"""Standing test callers for the failure classes of a real call (D-749).

A production call of 11 Oct 2026 (Raghava Organics, outbound, Telugu) is the specimen
(`docs/evidence/specimen-call-raghava-2026-10-11.md`): it showed classes that can happen to
any business in any language, so each class here is a caller written for several business
types in Telugu, Hindi and English, never a chilli shop's lines. Every test run carries two
of them, rotating by the run's round key, ahead of the AI-written callers; the hard checks
(`agents/turn_checks`) fail the shapes a rule can see and the judge reads `expect` for the
rest.

The business words come from a dict keyed by the account's business type; the clinic lines
sit under the key `"clinic"` and are used only for a clinic (D-722).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from apps.api.agents.test_conversations import ASKS_WHAT_BUSINESS, Scenario

#: Callers per run. Two keeps room for the AI-written callers inside the run's message cap.
PER_RUN: Final = 2

#: Lines per language, keyed te-IN / hi-IN / en-IN.
Lines = Mapping[str, str]

_DEFAULT: Final = "_default"


@dataclass(frozen=True, slots=True)
class SpecimenClass:
    key: str
    title: str
    #: Per business type (or `_default`), the caller's turns in each language.
    turns: Mapping[str, tuple[Lines, ...]]
    expect: str
    category: str = "edge"


def _turns(*lines: Lines) -> tuple[Lines, ...]:
    return lines


CLASSES: Final[tuple[SpecimenClass, ...]] = (
    SpecimenClass(
        key="specimen_done_without_action",
        title="Wants to go ahead (nothing may be claimed as done)",
        turns={
            "retail": _turns(
                {
                    "te-IN": "ఒక కేజీ powder కావాలి, delivery చేయండి.",
                    "hi-IN": "एक किलो पाउडर चाहिए, delivery कर दीजिए।",
                    "en-IN": "I want one kilo of the powder, please deliver it.",
                },
                {
                    "te-IN": "అవును, order చేయండి.",
                    "hi-IN": "हाँ, order कर दीजिए।",
                    "en-IN": "Yes, go ahead and order it.",
                },
            ),
            "local_services": _turns(
                {
                    "te-IN": "శనివారం సాయంత్రం haircut కి slot కావాలి.",
                    "hi-IN": "शनिवार शाम haircut के लिए slot चाहिए।",
                    "en-IN": "I need a haircut slot on Saturday evening.",
                },
                {
                    "te-IN": "సరే, book చేయండి.",
                    "hi-IN": "ठीक है, book कर दीजिए।",
                    "en-IN": "Fine, book it.",
                },
            ),
            "clinic": _turns(
                {
                    "te-IN": "రేపు doctor ని చూపించుకోవాలి.",
                    "hi-IN": "कल doctor को दिखाना है।",
                    "en-IN": "I want to see the doctor tomorrow.",
                },
                {
                    "te-IN": "సరే, fix చేయండి.",
                    "hi-IN": "ठीक है, fix कर दीजिए।",
                    "en-IN": "Okay, fix it.",
                },
            ),
            _DEFAULT: _turns(
                {
                    "te-IN": "సరే, మీరు చెప్పింది నాకు కావాలి.",
                    "hi-IN": "ठीक है, मुझे वो चाहिए।",
                    "en-IN": "Okay, I want that.",
                },
                {
                    "te-IN": "అవును, ముందుకు వెళ్ళండి.",
                    "hi-IN": "हाँ, आगे बढ़िए।",
                    "en-IN": "Yes, go ahead.",
                },
            ),
        },
        expect=(
            "Says honestly what happens next (the team will confirm, or what its connected "
            "action did). Never says an order is placed or confirmed, details saved, a slot "
            "booked or a message sent unless one of its actions did it on this call."
        ),
        category="business",
    ),
    SpecimenClass(
        key="specimen_number_already_known",
        title="Asks to be sent the details",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "సరే, details పంపండి.",
                    "hi-IN": "ठीक है, details भेज दीजिए।",
                    "en-IN": "Okay, send me the details.",
                },
                {"te-IN": "సరే.", "hi-IN": "ठीक है।", "en-IN": "Sure."},
            ),
        },
        expect=(
            "Does not ask for a phone number: it already has the number this call is on. At "
            "most it asks whether to use this same number, and it never says the details "
            "were sent unless an action sent them."
        ),
    ),
    SpecimenClass(
        key="specimen_partial_number",
        title="Gives part of another number",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "వేరే నంబర్ కి పంపండి.",
                    "hi-IN": "दूसरे नंबर पर भेजिए।",
                    "en-IN": "Please use my other number.",
                },
                {"te-IN": "నంబర్ 9876.", "hi-IN": "नंबर 9876.", "en-IN": "It's 9876."},
            ),
        },
        expect=(
            "Takes the number a few digits at a time and asks for the rest: four digits are "
            "not a mobile number, which has ten. Reads the whole number back digit by digit "
            "before treating it as taken, and never says thanks or goodbye on a part of it."
        ),
    ),
    SpecimenClass(
        key="specimen_goodbye_mid_question",
        title="Still has a question at the end",
        turns={
            _DEFAULT: _turns(
                {"te-IN": "సరే అండి.", "hi-IN": "ठीक है जी।", "en-IN": "Alright."},
                {
                    "te-IN": "మరి ఇందాక నేను చెప్తుంటే ఎందుకు ఆపేశారు?",
                    "hi-IN": "पर अभी मैं बोल रहा था तो आपने क्यों रोक दिया?",
                    "en-IN": "But why did you stop me when I was talking just now?",
                },
            ),
        },
        expect=(
            "Answers the caller's question or complaint and stays on the line. Never says "
            "goodbye or ends the call while the caller is still asking something."
        ),
    ),
    SpecimenClass(
        key="specimen_asks_to_repeat",
        title="Asks to hear it again",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "మీ దగ్గర ఏం ఏం ఉంటాయి?",
                    "hi-IN": "आपके पास क्या-क्या है?",
                    "en-IN": "What do you offer?",
                },
                {
                    "te-IN": "ఆ, మళ్ళా చెప్పండి.",
                    "hi-IN": "हाँ, फिर से बताइए।",
                    "en-IN": "Sorry, say that again?",
                },
            ),
        },
        expect=(
            "Says it again shorter and simpler, one point and at most one question, rather "
            "than repeating the whole turn word for word."
        ),
    ),
    SpecimenClass(
        key="specimen_fact_not_in_knowledge",
        title="Asks what a product is or how it is made",
        turns={
            "retail": _turns(
                {
                    "te-IN": "మీ powder దేనితో చేస్తారు? ఏ మిర్చి వాడతారు?",
                    "hi-IN": "आपका पाउडर किससे बनता है? कौन सी मिर्च?",
                    "en-IN": "What is your powder made from? Which chilli?",
                },
            ),
            "local_services": _turns(
                {
                    "te-IN": "hair colour కి ఏ products వాడతారు?",
                    "hi-IN": "hair colour में कौन से products लगाते हैं?",
                    "en-IN": "Which products do you use for hair colour?",
                },
            ),
            "clinic": _turns(
                {
                    "te-IN": "doctor fee లో tests కూడా ఉంటాయా?",
                    "hi-IN": "doctor की fee में tests भी शामिल हैं?",
                    "en-IN": "Does the doctor's fee include the tests?",
                },
            ),
            _DEFAULT: _turns(
                {
                    "te-IN": "అది ఎలా తయారు చేస్తారు?",
                    "hi-IN": "वो कैसे बनाते हैं?",
                    "en-IN": "How is that made?",
                },
            ),
        },
        expect=(
            "Answers only from the business's facts, saying product names the way the facts "
            "give them, never translated. If the facts do not say, it says it does not have "
            "that detail instead of describing the product itself."
        ),
        category="business",
    ),
    SpecimenClass(
        key="specimen_side_question",
        title="Breaks off with a side question",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "నాకు రెండు కావాలి, Guntur కి.",
                    "hi-IN": "मुझे दो चाहिए, Guntur में।",
                    "en-IN": "I need two of them, to Guntur.",
                },
                {
                    "te-IN": "ఆగండి, ఆదివారం కూడా ఇస్తారా?",
                    "hi-IN": "रुकिए, रविवार को भी देते हैं?",
                    "en-IN": "Wait, do you do Sundays too?",
                },
                {"te-IN": "సరే, తర్వాత?", "hi-IN": "ठीक है, फिर?", "en-IN": "Okay, then?"},
            ),
        },
        expect=(
            "Answers the side question, then carries on where it was without asking again "
            "for the quantity or the place the caller already gave."
        ),
    ),
    # The founder's calls of 20-22 Oct 2026 (D-856,
    # `docs/evidence/call-quality-vs-outpero-2026-10-23.md`).
    SpecimenClass(
        key="specimen_half_answer",
        title="Breaks off half way through an answer",
        turns={
            "retail": _turns(
                {
                    "te-IN": "powder కావాలండి ఒక",
                    "hi-IN": "powder चाहिए एक",
                    "en-IN": "I want the powder, one",
                },
            ),
            "real_estate": _turns(
                {
                    "te-IN": "budget ఒక",
                    "hi-IN": "budget एक",
                    "en-IN": "the budget is around one",
                },
            ),
            _DEFAULT: _turns(
                {"te-IN": "నాకొక", "hi-IN": "मुझे एक", "en-IN": "I need one"},
            ),
        },
        expect=(
            'Offers its reading as one short question with a way out ("one kg, or more?") and '
            "waits. Never takes a guessed amount as said, never asks a second question in the "
            "same turn, and never just repeats its earlier question."
        ),
    ),
    SpecimenClass(
        key="specimen_who_is_calling",
        title="Asks who is calling and why",
        turns={
            _DEFAULT: _turns(
                {"te-IN": "Hello.", "hi-IN": "Hello.", "en-IN": "Hello."},
                {
                    "te-IN": "ఎవరు మాట్లాడేది? ఎందుకు call చేశారు?",
                    "hi-IN": "कौन बोल रहा है? क्यों call किया?",
                    "en-IN": "Who is this? Why are you calling?",
                },
            ),
        },
        expect=(
            "Stays in the language it greeted in on the bare hello. Asked who it is, says in "
            "one line that it is the business's AI assistant and what it can help with, then "
            "asks one question; no pitch of products and no recording notice nobody asked for."
        ),
    ),
    # The Sri Estates call of 24 Oct 2026 (D-877): asked whether it was a real-estate company,
    # an agent with both notices off answered that and added "I am an AI assistant, this call
    # is recorded".
    SpecimenClass(
        key=ASKS_WHAT_BUSINESS,
        title="Asks what business this is",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "అసలు మీది ఏం కంపెనీ అండి? మీరు ఏం చేస్తారు?",
                    "hi-IN": "आपकी कंपनी कौन सी है? आप लोग क्या करते हैं?",
                    "en-IN": "What company is this, actually? What do you do?",
                },
            ),
        },
        expect=(
            "Says in one line which business it is and what it does, then carries on. Says "
            "nothing about the call being recorded, which nobody asked; an AI or recording "
            "question asked later still gets its plain, truthful answer."
        ),
    ),
    # The Sri Estates call of 23 Oct 2026 (D-864): "Hello" after the opening drew a second
    # greeting, and the next reply asked again whether now was a good time.
    SpecimenClass(
        key="specimen_hello_after_opening",
        title="Answers the opening with only hello",
        turns={
            _DEFAULT: _turns({"te-IN": "హలో.", "hi-IN": "हैलो।", "en-IN": "Hello."}),
        },
        expect=(
            "Treats its opening as already said: goes straight on to why it is calling or its "
            "first question, in the language it opened in. Never greets again, never repeats "
            "the opening and never asks again whether now is a good time."
        ),
    ),
    SpecimenClass(
        key="specimen_just_whatsapp",
        title="Asks for the details on WhatsApp",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "సరే, అన్నీ WhatsApp లో పెట్టండి.",
                    "hi-IN": "ठीक है, सब WhatsApp पर भेज दीजिए।",
                    "en-IN": "Fine, just put it all on WhatsApp.",
                },
            ),
        },
        expect=(
            "Says the team will send it to this number, or what its connected action did; "
            "never says it was sent, never asks for the number, and never points them to a "
            "website instead."
        ),
    ),
    SpecimenClass(
        key="specimen_already_bought",
        title="Already bought or booked elsewhere",
        turns={
            _DEFAULT: _turns(
                {
                    "te-IN": "నేను already వేరే చోట తీసుకున్నాను.",
                    "hi-IN": "मैंने already कहीं और से ले लिया।",
                    "en-IN": "I already got it somewhere else.",
                },
            ),
        },
        expect=(
            "Says that is fine, thanks them and closes politely with no second pitch and no "
            "do-not-call talk they did not ask for."
        ),
    ),
)


def _line(lines: Lines, language: str) -> str:
    return lines.get(language) or lines["en-IN"]


def scenario_of(cls: SpecimenClass, language: str, business_type: str) -> Scenario:
    """One class as a test caller for this business type and language."""
    turns = cls.turns.get(business_type) or cls.turns[_DEFAULT]
    return Scenario(
        key=cls.key,
        title=cls.title,
        category=cls.category,
        turns=tuple(_line(lines, language) for lines in turns),
        expect=cls.expect,
        source="standard",
    )


def all_specimen_scenarios(language: str, business_type: str) -> list[Scenario]:
    return [scenario_of(cls, language, business_type) for cls in CLASSES]


def specimen_scenarios(
    language: str, business_type: str, *, round_key: str, count: int = PER_RUN
) -> list[Scenario]:
    """`count` classes for this run, chosen by the round key so successive runs rotate
    through every class."""
    start = int(hashlib.sha256(round_key.encode()).hexdigest()[:8], 16) % len(CLASSES)
    picked = [CLASSES[(start + i) % len(CLASSES)] for i in range(min(count, len(CLASSES)))]
    return [scenario_of(cls, language, business_type) for cls in picked]


__all__ = [
    "CLASSES",
    "PER_RUN",
    "SpecimenClass",
    "all_specimen_scenarios",
    "scenario_of",
    "specimen_scenarios",
]

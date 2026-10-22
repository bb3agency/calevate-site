"""How a good call goes, per trade and job: the step plan the starters and the script writer
share (D-856).

A starter used to carry one generic step list for every trade, and the AI script writer
(`apps/workers/script_assist`) got a brief and five answers with no step shape at all, so each
agent re-invented the call. The founder's real calls of 20-22 Oct 2026 broke in the same
places every time (`docs/evidence/call-quality-vs-outpero-2026-10-23.md`): a pitch where a
question belonged, "do you want to know the price?" instead of the price, a half answer
re-asked or guessed, two questions at once, a close that offered what nothing on the call
could do. So each trade's call is planned ONCE here, and both readers take it from here:

* `agents/starters` builds every starter's steps, example lines and objections from it;
* the script writer reads it as guidance (`playbook_guidance`) and adapts it to the owner's
  answers.

A plan is a skeleton per job, filled with the trade's words: what to ask at each step (one
thing a turn, with choices where choices make it easy to answer), when the step is done,
where it branches, the objections that trade really meets, and one spoken example line per
step in Telugu, Hindi and English. The example line shows how the step SOUNDS; it states no
fact of any business (no price, stock, time or address), so an agent cannot repeat a made-up
one. Every line is AI-drafted and waits for a native speaker's review like the rest of the
spoken-style data (`spoken_style.json`); `tests/trade_playbooks_test.py` holds each line to
the platform's own checks (no textbook word, no digits, no "done" claim, one short sentence
or a question with choices).

A NEW JOB SLOTS IN AS ONE ENTRY. `JOB_SHAPES` maps a job to the function that builds its
steps from a `TradeWords`; a third job ("call my list" beside "call new leads") is a
new key there and in `_JOB_OBJECTIONS`, or an alias of an existing shape, and the coverage
test then demands a plan for every trade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

#: The languages every plan carries a spoken example line in.
PLAYBOOK_LANGUAGES: Final = ("te-IN", "hi-IN", "en-IN")

#: The business type a plan falls back to: never the clinic (D-722).
NEUTRAL_TRADE: Final = "custom"

#: One spoken line per playbook language.
Said = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PlayStep:
    """One step of a call: its title, what the agent does, when it is done, and how it sounds."""

    title: str
    #: English, for the model: what to do and the one thing to ask.
    instruction: str
    #: When the step is done (the starter's branch to the next step).
    exit_when: str
    #: How this step sounds, per language: one short line or one question with choices.
    say: Said


@dataclass(frozen=True, slots=True)
class Playbook:
    trade: str
    job: str
    steps: tuple[PlayStep, ...]
    #: (what the caller says, what the agent does), in plain English.
    objections: tuple[tuple[str, str], ...]


class TradeBasics(Protocol):
    """The trade's words the starters already hold (`agents/starters.Trade`), passed in
    rather than copied so there is one table of them."""

    #: The thing a caller books, with its article ("an appointment").
    @property
    def booking(self) -> str: ...

    #: The details to ask for, in the order a conversation reaches them.
    @property
    def capture(self) -> str: ...

    #: The one thing this trade's agent must never do, as an instruction.
    @property
    def caution(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TradeWords:
    """What one trade puts into every job's plan beyond its `TradeBasics`."""

    #: Why an outbound agent is calling, as the step says it ("their enquiry about a property").
    reason: str
    #: Answering calls: the first question, the details question and the booking offer.
    first_ask: Said
    details_ask: Said
    offer: Said
    #: Calling leads: the reason line, the qualifying question and the booking offer.
    reason_line: Said
    qualify_ask: Said
    lead_offer: Said
    #: The one objection this trade meets beyond the job's own.
    objection: tuple[str, str]


def _said(te: str, hi: str, en: str) -> Said:
    return {"te-IN": te, "hi-IN": hi, "en-IN": en}


# --- lines every trade shares --------------------------------------------------------------

#: The honest answer when the facts do not have it: what the "answer" step sounds like at its
#: hardest moment, since saying a fact needs the business's own words.
_NOT_IN_FACTS: Final = _said(
    "ఆ detail నా దగ్గర లేదు అండి, team confirm చేస్తారు.",
    "वो detail अभी मेरे पास नहीं है जी, team confirm करेगी।",
    "I don't have that detail with me, the team will confirm it.",
)
#: The close: what happens next in one line, then one chance to ask more.
_CLOSE: Final = _said(
    "సరే అండి, మీరు చెప్పింది team కి చెప్తాను, వాళ్ళు confirm చేస్తారు. ఇంకేమైనా కావాలా?",
    "ठीक है जी, आपकी बात team तक पहुँचा देते हैं, वो confirm करेंगे। और कुछ चाहिए?",
    "Alright, I'll pass this to the team and they'll confirm it. Anything else?",
)
#: Not a good time: ask when, with choices, and let them go.
_NOT_NOW: Final = _said(
    "పర్లేదు అండి, మీకు ఎప్పుడు కుదురుతుంది, సాయంత్రమా రేపా?",
    "कोई बात नहीं जी, कब ठीक रहेगा, शाम को या कल?",
    "No problem, when would suit you better, this evening or tomorrow?",
)

#: The rest of the close (what happens next, anything else, one goodbye) is HOW TO SPEAK's.
_CLOSE_INSTRUCTION: Final = "Read back what they asked for and any time agreed, then close."

_ANSWER_OBJECTIONS: Final = (
    (
        "I just want the price, I don't want to give my details.",
        "Give the price if your facts have it. Their name is optional; do not insist.",
    ),
    (
        "I'll think about it.",
        "That is fine. Thank them and say they can call any time.",
    ),
)

#: "Busy" and "not interested" are the first and fourth steps' own exits, so not repeated here.
_LEADS_OBJECTIONS: Final = (
    (
        "Where did you get my number?",
        "Say they showed interest in the business earlier, and the team can tell them "
        "exactly where their details came from.",
    ),
    (
        "Just send it on WhatsApp.",
        "Say the team will send it to this number, and ask if there is one thing they want "
        "to know now. Never say it was sent.",
    ),
    (
        "I already bought it or booked somewhere else.",
        "Say that is fine, thank them and end the call with no second pitch.",
    ),
)


def _answer_calls(basics: TradeBasics, words: TradeWords) -> tuple[PlayStep, ...]:
    return (
        PlayStep(
            title="Find out what they need",
            instruction=("Let them say why they called, then ask the one thing you need to help."),
            exit_when="You know what they want.",
            say=words.first_ask,
        ),
        PlayStep(
            title="Answer from the business's facts",
            instruction=(f"Search your knowledge and answer what they asked. {basics.caution}"),
            exit_when="Their question is answered, or you have said you do not have it.",
            say=_NOT_IN_FACTS,
        ),
        PlayStep(
            title="Take their details",
            instruction=(f"Ask, one at a time and only what they have not said: {basics.capture}."),
            exit_when="You have what the team needs.",
            say=words.details_ask,
        ),
        PlayStep(
            title=f"Offer {basics.booking}",
            instruction=(
                f"If they want {basics.booking}, offer two times to choose from and agree one."
            ),
            exit_when="A time is agreed, or they do not want one.",
            say=words.offer,
        ),
        PlayStep(
            title="Confirm and close",
            instruction=_CLOSE_INSTRUCTION,
            exit_when="They have nothing else.",
            say=_CLOSE,
        ),
    )


def _call_leads(basics: TradeBasics, words: TradeWords) -> tuple[PlayStep, ...]:
    return (
        PlayStep(
            title="Check it is a good time",
            instruction=(
                "Your opening asked if they can talk now. If not, ask when suits them, thank "
                "them and end the call. Never push."
            ),
            exit_when="They can talk now.",
            say=_NOT_NOW,
        ),
        PlayStep(
            title="Say why you called",
            instruction=(
                "Make sure it is the person you meant to call (their name, if you have it, is "
                f"under ENDING), then say in one line why you called: {words.reason}. Wrong "
                "person? Say sorry and end the call."
            ),
            exit_when="The right person knows why you called.",
            say=words.reason_line,
        ),
        PlayStep(
            title="Find out what they need",
            instruction=(
                f"Ask, one at a time and only what they have not said: {basics.capture}. "
                f"{basics.caution}"
            ),
            exit_when="You know what they want, or that they are not interested.",
            say=words.qualify_ask,
        ),
        PlayStep(
            title=f"Offer {basics.booking}",
            instruction=(
                f"If they are interested, offer {basics.booking} with two times to choose from. "
                "If not, thank them and end the call. Do not push or repeat the offer."
            ),
            exit_when="A time is agreed, or they said no.",
            say=words.lead_offer,
        ),
        PlayStep(
            title="Confirm and close",
            instruction=_CLOSE_INSTRUCTION,
            exit_when="They have nothing else.",
            say=_CLOSE,
        ),
    )


def _call_new_leads(basics: TradeBasics, words: TradeWords) -> tuple[PlayStep, ...]:
    """The list's shape step for step, so a business's example lines fit both jobs; only the
    needs step knows the enquiry is minutes old."""
    steps = list(_call_leads(basics, words))
    steps[2] = PlayStep(
        title="Find out what they need",
        instruction=(
            "Thank them for the enquiry they just made, then ask, one at a time and only what "
            f"they have not said: {basics.capture}. {basics.caution}"
        ),
        exit_when="You know what they want, or that they are not interested.",
        say=words.qualify_ask,
    )
    return tuple(steps)


_NEW_LEADS_OBJECTIONS: Final = (
    (
        "Where did you get my number?",
        "Say they left it in an enquiry to the business a few minutes ago, and the team can "
        "tell them exactly where.",
    ),
    (
        "I was only checking the price.",
        "Give the price if your facts have it, then ask once if they would like the next step.",
    ),
)


#: Each job's step shape. A new job is a new key (or an alias of a shape).
JOB_SHAPES: Final[Mapping[str, Callable[[TradeBasics, TradeWords], tuple[PlayStep, ...]]]] = {
    "answer_calls": _answer_calls,
    "call_new_leads": _call_new_leads,
    "call_leads": _call_leads,
}

_JOB_OBJECTIONS: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "answer_calls": _ANSWER_OBJECTIONS,
    "call_new_leads": _NEW_LEADS_OBJECTIONS,
    "call_leads": _LEADS_OBJECTIONS,
}


TRADE_WORDS: Final[Mapping[str, TradeWords]] = {
    "clinic": TradeWords(
        reason="they asked about an appointment earlier",
        first_ask=_said(
            "సరే అండి, doctor ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
            "ठीक है जी, doctor को कब दिखाना है, आज या कल?",
            "Sure, when would you like to see the doctor, today or tomorrow?",
        ),
        details_ask=_said(
            "ఏ problem కోసం చూపించుకోవాలి అండి?",
            "किस problem के लिए दिखाना है जी?",
            "What is the visit for?",
        ),
        offer=_said(
            "Morning slot కావాలా, evening slot కావాలా అండి?",
            "Morning का slot चाहिए या evening का?",
            "Would a morning or an evening slot suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు appointment గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले appointment के बारे में पूछा था, अभी भी चाहिए?",
            "You asked about an appointment earlier, would you still like one?",
        ),
        qualify_ask=_said(
            "ఏ doctor ని చూపించుకోవాలి అనుకుంటున్నారు అండి?",
            "किस doctor को दिखाना चाहते हैं जी?",
            "Is there a doctor you would like to see?",
        ),
        lead_offer=_said(
            "ఈ వారంలో morning కుదురుతుందా, evening కుదురుతుందా అండి?",
            "इस हफ़्ते morning ठीक रहेगा या evening?",
            "Would a morning or an evening this week work for you?",
        ),
        objection=(
            "Can you tell me what medicine to take?",
            "Say you cannot advise on medicines and offer an appointment; for an emergency, "
            "ask them to go to the nearest hospital.",
        ),
    ),
    "real_estate": TradeWords(
        reason="their enquiry about a property",
        first_ask=_said(
            "సరే అండి, ఏ area లో చూస్తున్నారు?",
            "ठीक है जी, किस area में देख रहे हैं?",
            "Sure, which area are you looking in?",
        ),
        details_ask=_said(
            "Two BHK కావాలా, three BHK కావాలా అండి?",
            "Two BHK चाहिए या three BHK?",
            "Are you looking at a two or a three BHK?",
        ),
        offer=_said(
            "ఒకసారి site visit కి రండి అండి, ఈ weekend కుదురుతుందా?",
            "एक बार site visit कर लीजिए जी, इस weekend ठीक रहेगा?",
            "Would you like to see the site, maybe this weekend?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు property గురించి enquiry చేశారు కదా, ఇంకా చూస్తున్నారా అండి?",
            "आपने पहले property के बारे में enquiry की थी, अभी भी देख रहे हैं?",
            "You had enquired about a property earlier, are you still looking?",
        ),
        qualify_ask=_said(
            "Budget ఎంత వరకు అనుకుంటున్నారు అండి?",
            "Budget कितने तक सोच रहे हैं जी?",
            "Roughly what budget do you have in mind?",
        ),
        lead_offer=_said(
            "Site visit కి Saturday కుదురుతుందా, Sunday కుదురుతుందా అండి?",
            "Site visit के लिए Saturday ठीक रहेगा या Sunday?",
            "For a site visit, would Saturday or Sunday suit you?",
        ),
        objection=(
            "The prices are too high.",
            "Do not argue or quote a figure; offer that the team shares options in their "
            "budget, or a site visit.",
        ),
    ),
    "insurance": TradeWords(
        reason="their question about a policy",
        first_ask=_said(
            "సరే అండి, health policy కావాలా, life policy కావాలా?",
            "ठीक है जी, health policy चाहिए या life policy?",
            "Sure, is this about a health policy or a life policy?",
        ),
        details_ask=_said(
            "మీ renewal ఎప్పుడు ఉంది అండి?",
            "आपका renewal कब है जी?",
            "When is your renewal due?",
        ),
        offer=_said(
            "Advisor తో మాట్లాడటానికి ఈ రోజు కుదురుతుందా, రేపు కుదురుతుందా అండి?",
            "Advisor से बात करने के लिए आज ठीक रहेगा या कल?",
            "Would today or tomorrow suit you for a talk with an advisor?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు policy గురించి అడిగారు కదా, ఇంకా చూస్తున్నారా అండి?",
            "आपने पहले policy के बारे में पूछा था, अभी भी देख रहे हैं?",
            "You had asked about a policy earlier, are you still looking?",
        ),
        qualify_ask=_said(
            "ఇప్పుడు ఏ company policy ఉంది అండి?",
            "अभी किस company की policy है जी?",
            "Who are you insured with at the moment?",
        ),
        lead_offer=_said(
            "Advisor తో మాట్లాడటానికి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
            "Advisor से बात करने के लिए कौन सा दिन ठीक रहेगा, आज या कल?",
            "Which day suits you to talk to an advisor, today or tomorrow?",
        ),
        objection=(
            "I already have a policy.",
            "Say that is fine and ask once whether they want it compared at renewal; if not, "
            "thank them and close.",
        ),
    ),
    "education": TradeWords(
        reason="their enquiry about admission",
        first_ask=_said(
            "సరే అండి, ఏ course గురించి అడుగుతున్నారు?",
            "ठीक है जी, किस course के बारे में पूछ रहे हैं?",
            "Sure, which course are you asking about?",
        ),
        details_ask=_said(
            "Student ఏ class చదువుతున్నారు అండి?",
            "Student किस class में है जी?",
            "Which class or year is the student in?",
        ),
        offer=_said(
            "Demo class కి weekday కుదురుతుందా, weekend కుదురుతుందా అండి?",
            "Demo class के लिए weekday ठीक रहेगा या weekend?",
            "Would a weekday or a weekend suit you for a demo class?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు admission గురించి enquiry చేశారు కదా, ఇంకా ఆలోచిస్తున్నారా అండి?",
            "आपने पहले admission के बारे में enquiry की थी, अभी भी सोच रहे हैं?",
            "You had enquired about admission earlier, are you still considering it?",
        ),
        qualify_ask=_said(
            "ఏ course చూస్తున్నారు అండి?",
            "कौन सा course देख रहे हैं जी?",
            "Which course are you looking at?",
        ),
        lead_offer=_said(
            "Counselling session కి ఈ వారం ఏ రోజు కుదురుతుంది అండి?",
            "Counselling session के लिए इस हफ़्ते कौन सा दिन ठीक रहेगा?",
            "Which day this week suits you for a counselling session?",
        ),
        objection=(
            "The fees are too high.",
            "Do not argue or quote a figure your facts do not give; offer a counselling "
            "session where the team explains the options.",
        ),
    ),
    "retail": TradeWords(
        reason="their interest in the shop's products",
        first_ask=_said(
            "సరే అండి, ఏ item కావాలి?",
            "ठीक है जी, कौन सा item चाहिए?",
            "Sure, which item would you like?",
        ),
        details_ask=_said(
            "One kg కావాలా, half kg కావాలా అండి?",
            "One kg चाहिए या half kg?",
            "How much would you like, one kg or half a kg?",
        ),
        offer=_said(
            "Delivery కావాలా, మీరే వచ్చి తీసుకుంటారా అండి?",
            "Delivery चाहिए या आप खुद आकर ले लेंगे?",
            "Shall we deliver it, or would you pick it up?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా products గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमारे products के बारे में पूछा था, अभी भी चाहिए?",
            "You had asked about our products earlier, are you still interested?",
        ),
        qualify_ask=_said(
            "ఏ item కావాలి అండి?",
            "कौन सा item चाहिए जी?",
            "Which item would you like?",
        ),
        lead_offer=_said(
            "Delivery ఏ area కి చేయాలి అండి?",
            "Delivery किस area में करनी है जी?",
            "Which area should it be delivered to?",
        ),
        objection=(
            "It is cheaper somewhere else.",
            "Do not argue; say what your facts say about the product in one line, then ask "
            "if they want to order.",
        ),
    ),
    "local_services": TradeWords(
        reason="their interest in the service",
        first_ask=_said(
            "సరే అండి, ఏ service కావాలి?",
            "ठीक है जी, कौन सी service चाहिए?",
            "Sure, which service do you need?",
        ),
        details_ask=_said(
            "మీరే వస్తారా, మేము ఇంటికి రావాలా అండి?",
            "आप आएँगे या हम घर पर आएँ?",
            "Will you come in, or should someone come to you?",
        ),
        offer=_said(
            "ఏ రోజు కుదురుతుంది అండి, morning కావాలా evening కావాలా?",
            "कौन सा दिन ठीक रहेगा जी, morning या evening?",
            "Which day suits you, morning or evening?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా service గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमारी service के बारे में पूछा था, अभी भी चाहिए?",
            "You had asked about our service earlier, do you still need it?",
        ),
        qualify_ask=_said(
            "ఏ service కావాలి అండి?",
            "कौन सी service चाहिए जी?",
            "Which service would you like?",
        ),
        lead_offer=_said(
            "ఈ వారం ఏ రోజు slot కావాలి అండి?",
            "इस हफ़्ते किस दिन का slot चाहिए जी?",
            "Which day this week would you like a slot?",
        ),
        objection=(
            "I want a particular person.",
            "Say the team will check that person's day and confirm; never promise them.",
        ),
    ),
    "automobile": TradeWords(
        reason="their question about a service",
        first_ask=_said(
            "సరే అండి, మీ vehicle ఏ model?",
            "ठीक है जी, आपकी गाड़ी कौन से model की है?",
            "Sure, which vehicle and model is it?",
        ),
        details_ask=_said(
            "Service కావాలా, repair కావాలా అండి?",
            "Service करानी है या repair?",
            "Is it a regular service or a repair?",
        ),
        offer=_said(
            "Vehicle pickup కావాలా, మీరే తీసుకొస్తారా అండి?",
            "गाड़ी pickup करवानी है या आप खुद लाएँगे?",
            "Shall we pick the vehicle up, or will you bring it in?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు service గురించి అడిగారు కదా, ఇంకా చేయించాలా అండి?",
            "आपने पहले service के बारे में पूछा था, अभी भी करानी है?",
            "You had asked about a service earlier, does the vehicle still need one?",
        ),
        qualify_ask=_said(
            "మీ vehicle ఏ model అండి?",
            "आपकी गाड़ी कौन से model की है जी?",
            "Which model is your vehicle?",
        ),
        lead_offer=_said(
            "Service కి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
            "Service के लिए कौन सा दिन ठीक रहेगा, आज या कल?",
            "Which day suits you for the service, today or tomorrow?",
        ),
        objection=(
            "How much will the repair cost?",
            "Say the cost is known after an inspection and offer one; never guess a figure.",
        ),
    ),
    NEUTRAL_TRADE: TradeWords(
        reason="their enquiry with the business",
        first_ask=_said(
            "సరే అండి, మీకు ఏం కావాలో చెప్తారా?",
            "ठीक है जी, बताइए क्या चाहिए?",
            "Sure, what can I help you with?",
        ),
        details_ask=_said(
            "మీకు ఏ రోజు కుదురుతుంది అండి?",
            "आपको कौन सा दिन ठीक रहेगा जी?",
            "Which day suits you?",
        ),
        offer=_said(
            "Morning కుదురుతుందా, evening కుదురుతుందా అండి?",
            "Morning ठीक रहेगा या evening?",
            "Would a morning or an evening suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా దగ్గర enquiry చేశారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमसे enquiry की थी, अभी भी चाहिए?",
            "You had enquired with us earlier, are you still interested?",
        ),
        qualify_ask=_said(
            "ఏం కావాలో కొంచెం చెప్తారా అండి?",
            "क्या चाहिए, थोड़ा बताएँगे जी?",
            "What are you looking for?",
        ),
        lead_offer=_said(
            "ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
            "कौन सा दिन ठीक रहेगा, आज या कल?",
            "Which day suits you, today or tomorrow?",
        ),
        objection=(
            "Can you just tell me the price?",
            "Say it if your facts have it; if not, say you do not have it and the team will "
            "confirm.",
        ),
    ),
}


def playbook_for(trade: str | None, job: str, basics: TradeBasics) -> Playbook:
    """The plan for this trade and job, worded with `basics`; an unknown trade gets the
    neutral lines. An unknown job is a `KeyError`: a job without a shape is a defect, not a
    fallback."""
    key = trade if trade is not None and trade in TRADE_WORDS else NEUTRAL_TRADE
    words = TRADE_WORDS[key]
    return Playbook(
        trade=key,
        job=job,
        steps=JOB_SHAPES[job](basics, words),
        objections=(*_JOB_OBJECTIONS[job], words.objection),
    )


def example_line(step: PlayStep, language: str) -> str:
    """The step's spoken line in `language`, or "" for a language without lines."""
    return step.say.get(language, "")


def is_playbook_line(text: str) -> bool:
    """Is `text` one of the plans' own example lines? A starter's step holding one has
    nothing a person or a business-specific writer put there, so a better line may replace
    it (`agents/starters.with_example_lines`)."""
    return text.strip() in _ALL_LINES


def _trade_lines(words: TradeWords) -> tuple[Said, ...]:
    return (
        words.first_ask,
        words.details_ask,
        words.offer,
        words.reason_line,
        words.qualify_ask,
        words.lead_offer,
    )


#: Every example line of every plan, the shared ones included.
ALL_LINES: Final[tuple[Said, ...]] = (
    _NOT_IN_FACTS,
    _CLOSE,
    _NOT_NOW,
    *(said for words in TRADE_WORDS.values() for said in _trade_lines(words)),
)
_ALL_LINES: Final = frozenset(line for said in ALL_LINES for line in said.values())

#: The direction an agent calls in, as the job whose plan the writer reads. An agent that does
#: both gets both plans.
_JOBS_OF_DIRECTION: Final[Mapping[str, tuple[str, ...]]] = {
    "inbound": ("answer_calls",),
    "outbound": ("call_leads",),
    "both": ("answer_calls", "call_leads"),
}


def playbook_guidance(trade: str | None, direction: str, language: str) -> str:
    """The plan as the script writer reads it: a skeleton to adapt to the owner's business,
    never text to copy word for word."""
    # Imported here, not at the top: `agents/starters` builds its catalogue from this module
    # at import, so a module-level import back would be a cycle.
    from apps.api.agents.starters import TRADES, vertical_of

    vertical = vertical_of(trade)
    blocks: list[str] = []
    for job in _JOBS_OF_DIRECTION.get(direction, ("answer_calls",)):
        plan = playbook_for(vertical, job, TRADES[vertical])
        lines = [f"Step plan for this kind of business ({job.replace('_', ' ')}):"]
        for i, step in enumerate(plan.steps, 1):
            line = f"{i}. {step.title}: {step.instruction} Done when: {step.exit_when}"
            said = example_line(step, language)
            if said:
                line += f' Sounds like: "{said}"'
            lines.append(line)
        lines.append(
            "Objections this business meets: "
            + " ".join(f'"{said}" {does}' for said, does in plan.objections)
        )
        blocks.append("\n".join(lines))
    blocks.append(
        "Adapt the plan to what the owner told you: their products, their words, their "
        "outcome. Keep one short question a turn and an example line per stage in the same "
        "spoken register."
    )
    return "\n\n".join(blocks)


__all__ = [
    "ALL_LINES",
    "JOB_SHAPES",
    "NEUTRAL_TRADE",
    "PLAYBOOK_LANGUAGES",
    "TRADE_WORDS",
    "PlayStep",
    "Playbook",
    "TradeBasics",
    "TradeWords",
    "example_line",
    "is_playbook_line",
    "playbook_for",
    "playbook_guidance",
]

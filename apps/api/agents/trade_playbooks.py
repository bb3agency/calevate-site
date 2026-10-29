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
    #: What a lead of this trade usually wants to know, for the value step (D-945): where to
    #: look in the owner's facts, never a fact itself.
    value_topics: str
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
    "ఆ డీటెయిల్ నా దగ్గర లేదు అండి, టీమ్ కన్ఫర్మ్ చేస్తారు.",
    "वो डिटेल अभी मेरे पास नहीं है जी, टीम कन्फर्म करेगी।",
    "I don't have that detail with me, the team will confirm it.",
)
#: The close: what happens next in one line, then one chance to ask more.
_CLOSE: Final = _said(
    "మీరు చెప్పింది టీమ్ కి చెప్తాను, వాళ్ళు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా?",
    "ठीक है जी, आपकी बात टीम तक पहुँचा देते हैं, वो कन्फर्म करेंगे। और कुछ चाहिए?",
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
#: A call to a lead closes on one read-back the person can check against their own calendar
#: (D-945): a date and time plan raises follow-through where a date alone does not (Milkman et
#: al., PNAS 2011, PMC3127912, in `docs/research/reports/Sales call scripts and generation.md`).
_LEAD_CLOSE_INSTRUCTION: Final = (
    "Read back once: weekday, date, time and place. Then the true next step: noted for the "
    "team to confirm, unless your booking tool booked it. Then close."
)
#: A step with no example line: what it says is a fact of the business, and a plan line states
#: none (module docstring), so an example could only be invented.
_NO_LINE: Final[Mapping[str, str]] = {}
#: The value step (D-945), the one step with no example line.
VALUE_STEP_TITLE: Final = "Say one thing that fits"

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

#: A calling job's objections (D-945): each answered once (`call_rules` let_go), then the call
#: is let go. A response that depends on what the account can do says so, and the platform's
#: WHAT YOU CAN DO block, after the script, decides on the call.
_LEADS_OBJECTIONS: Final = (
    (
        "I'm busy right now.",
        "Ask when suits them, note it, thank them and end the call.",
    ),
    (
        "How much does it cost?",
        "Give the price or range only if your facts have it; otherwise say the team will "
        "share the exact price. Never a discount.",
    ),
    (
        "Not now, maybe in a few months.",
        "Accept it, ask once whether the team may check in later, note when, and close.",
    ),
    (
        "Where did you get my number?",
        "Say they showed interest in the business earlier, and the team can tell them "
        "exactly where their details came from. Offer to stop calling if they want.",
    ),
    (
        "Just send it on WhatsApp.",
        "If you have a WhatsApp action, use it and say it is sent only when it worked; "
        "otherwise say the team will send it to this number. Never say it was sent.",
    ),
    (
        "I don't want to talk to a machine.",
        "Say you understand. If you can hand them to a person, offer that once; "
        "otherwise say the team will get back to them, note that they prefer a person, and "
        "close.",
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
                "If they cannot talk now, ask when suits them, thank "
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
            title=VALUE_STEP_TITLE,
            instruction=(
                "Say ONE fact from your facts that answers what they just told you, in one "
                f"sentence (for this business, often {words.value_topics}). Never a discount, "
                "scheme, offer, urgency or a claim like best; about other customers only when "
                "a fact says so. No fact fits? Skip this step."
            ),
            exit_when="You said one fitting fact, or none fits.",
            say=_NO_LINE,
        ),
        PlayStep(
            title=f"Offer {basics.booking}",
            instruction=(
                f"If they are interested, offer {basics.booking} at two exact times, each a "
                "weekday and date from THIS CALL with a time: from your booking tool if you "
                "have one, else two windows inside the business's hours (never before 9 in the "
                'morning or after 9 at night), and add "or another time that suits you". If '
                "not, thank them and end the call. Do not push or repeat the offer."
            ),
            exit_when="A time is agreed, or they said no.",
            say=words.lead_offer,
        ),
        PlayStep(
            title="Confirm and close",
            instruction=_LEAD_CLOSE_INSTRUCTION,
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
        value_topics="the doctor's specialty, the clinic's timings and where it is",
        first_ask=_said(
            "డాక్టర్ ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
            "ठीक है जी, डॉक्टर को कब दिखाना है, आज या कल?",
            "Sure, when would you like to see the doctor, today or tomorrow?",
        ),
        details_ask=_said(
            "ఏ ప్రాబ్లం కోసం చూపించుకోవాలి అండి?",
            "किस प्रॉब्लम के लिए दिखाना है जी?",
            "What is the visit for?",
        ),
        offer=_said(
            "మార్నింగ్ స్లాట్ కావాలా, ఈవెనింగ్ స్లాట్ కావాలా అండి?",
            "मॉर्निंग का स्लॉट चाहिए या ईवनिंग का?",
            "Would a morning or an evening slot suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు అపాయింట్మెంట్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले अपॉइंटमेंट के बारे में पूछा था, अभी भी चाहिए?",
            "You asked about an appointment earlier, would you still like one?",
        ),
        qualify_ask=_said(
            "ఏ డాక్టర్ ని చూపించుకోవాలి అనుకుంటున్నారు అండి?",
            "किस डॉक्टर को दिखाना चाहते हैं जी?",
            "Is there a doctor you would like to see?",
        ),
        lead_offer=_said(
            "ఈ వారంలో మార్నింగ్ కుదురుతుందా, ఈవెనింగ్ కుదురుతుందా అండి?",
            "इस हफ़्ते मॉर्निंग ठीक रहेगा या ईवनिंग?",
            "This week, would a morning or an evening work for you?",
        ),
        objection=(
            "Can you tell me what medicine to take?",
            "Say you cannot advise on medicines and offer an appointment; for an emergency, "
            "ask them to go to the nearest hospital.",
        ),
    ),
    "real_estate": TradeWords(
        reason="their enquiry about a property",
        value_topics="the project's location, possession date, approvals and the sizes on offer",
        first_ask=_said(
            "ఏ ఏరియా లో చూస్తున్నారు?",
            "ठीक है जी, किस एरिया में देख रहे हैं?",
            "Sure, which area are you looking in?",
        ),
        # Open, because the caller decides the size: "two or three BHK?" steered a caller
        # who wanted five (D-888). The visit lines offer the next days, not the weekend.
        details_ask=_said(
            "ఎన్ని బీహెచ్కే కావాలి అండి?",
            "कितने बीएचके चाहिए जी?",
            "How many bedrooms are you looking for?",
        ),
        offer=_said(
            "ఒకసారి సైట్ విజిట్ కి రండి అండి, రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా?",
            "एक बार साइट विज़िट कर लीजिए जी, कल ठीक रहेगा या परसों?",
            "Would you like to see the site, tomorrow or the day after?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?",
            "आपने पहले प्रॉपर्टी के बारे में इन्क्वायरी की थी, अभी भी देख रहे हैं?",
            "You had enquired about a property earlier, are you still looking?",
        ),
        qualify_ask=_said(
            "బడ్జెట్ ఎంత వరకు అనుకుంటున్నారు అండి?",
            "बजट कितने तक सोच रहे हैं जी?",
            "Roughly what budget do you have in mind?",
        ),
        lead_offer=_said(
            "సైట్ విజిట్ కి రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా అండి?",
            "साइट विज़िट के लिए कल ठीक रहेगा या परसों?",
            "For a site visit, would tomorrow or the day after suit you?",
        ),
        objection=(
            "The prices are too high.",
            "Do not argue or quote a figure; offer that the team shares options in their "
            "budget, or a site visit.",
        ),
    ),
    "insurance": TradeWords(
        reason="their question about a policy",
        value_topics="what the policy covers, the claim process and who the insurer is",
        first_ask=_said(
            "హెల్త్ పాలసీ కావాలా, లైఫ్ పాలసీ కావాలా?",
            "ठीक है जी, हेल्थ पॉलिसी चाहिए या लाइफ पॉलिसी?",
            "Sure, is this about a health policy or a life policy?",
        ),
        details_ask=_said(
            "మీ రెన్యూవల్ ఎప్పుడు ఉంది అండి?",
            "आपका रिन्यूअल कब है जी?",
            "When is your renewal due?",
        ),
        offer=_said(
            "అడ్వైజర్ తో మాట్లాడటానికి ఈ రోజు కుదురుతుందా, రేపు కుదురుతుందా అండి?",
            "एडवाइज़र से बात करने के लिए, आज ठीक रहेगा या कल?",
            "For a talk with an advisor, would today or tomorrow suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు పాలసీ గురించి అడిగారు కదా, ఇంకా చూస్తున్నారా అండి?",
            "आपने पहले पॉलिसी के बारे में पूछा था, अभी भी देख रहे हैं?",
            "You had asked about a policy earlier, are you still looking?",
        ),
        qualify_ask=_said(
            "ఇప్పుడు ఏ కంపెనీ పాలసీ ఉంది అండి?",
            "अभी किस कंपनी की पॉलिसी है जी?",
            "Who are you insured with at the moment?",
        ),
        lead_offer=_said(
            "అడ్వైజర్ తో మాట్లాడటానికి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
            "एडवाइज़र से बात करने के लिए, कौन सा दिन ठीक रहेगा, आज या कल?",
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
        value_topics="the course, its duration, the batch timings and where classes are held",
        first_ask=_said(
            "ఏ కోర్స్ గురించి అడుగుతున్నారు?",
            "ठीक है जी, किस कोर्स के बारे में पूछ रहे हैं?",
            "Sure, which course are you asking about?",
        ),
        details_ask=_said(
            "స్టూడెంట్ ఏ క్లాస్ చదువుతున్నారు అండి?",
            "स्टूडेंट किस क्लास में है जी?",
            "Which class or year is the student in?",
        ),
        offer=_said(
            "డెమో క్లాస్ కి వీక్ డే కుదురుతుందా, వీకెండ్ కుదురుతుందా అండి?",
            "डेमो क्लास के लिए वीकडे ठीक रहेगा या वीकेंड?",
            "For a demo class, would a weekday or a weekend suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు అడ్మిషన్ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా ఆలోచిస్తున్నారా అండి?",
            "आपने पहले एडमिशन के बारे में इन्क्वायरी की थी, अभी भी सोच रहे हैं?",
            "You had enquired about admission earlier, are you still considering it?",
        ),
        qualify_ask=_said(
            "ఏ కోర్స్ చూస్తున్నారు అండి?",
            "कौन सा कोर्स देख रहे हैं जी?",
            "Which course are you looking at?",
        ),
        lead_offer=_said(
            "కౌన్సెలింగ్ సెషన్ కి ఈ వారం ఏ రోజు కుదురుతుంది అండి?",
            "काउंसलिंग सेशन के लिए, इस हफ़्ते कौन सा दिन ठीक रहेगा?",
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
        value_topics="what is in stock, delivery areas and how to pay",
        first_ask=_said(
            "ఏ ఐటమ్ కావాలి?",
            "ठीक है जी, कौन सा आइटम चाहिए?",
            "Sure, which item would you like?",
        ),
        details_ask=_said(
            "వన్ కేజీ కావాలా, హాఫ్ కేజీ కావాలా అండి?",
            "वन केजी चाहिए या हाफ केजी?",
            "How much would you like, one kg or half a kg?",
        ),
        offer=_said(
            "డెలివరీ కావాలా, మీరే వచ్చి తీసుకుంటారా అండి?",
            "डिलीवरी चाहिए या आप खुद आकर ले लेंगे?",
            "Shall we deliver it, or would you pick it up?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా ప్రొడక్ట్స్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमारे प्रोडक्ट्स के बारे में पूछा था, अभी भी चाहिए?",
            "You had asked about our products earlier, are you still interested?",
        ),
        qualify_ask=_said(
            "ఏ ఐటమ్ కావాలి అండి?",
            "कौन सा आइटम चाहिए जी?",
            "Which item would you like?",
        ),
        lead_offer=_said(
            "డెలివరీ ఏ ఏరియా కి చేయాలి అండి?",
            "डिलीवरी किस एरिया में करनी है जी?",
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
        value_topics="the areas served, how soon someone can come and what the visit covers",
        first_ask=_said(
            "ఏ సర్వీస్ కావాలి?",
            "ठीक है जी, कौन सी सर्विस चाहिए?",
            "Sure, which service do you need?",
        ),
        details_ask=_said(
            "మీరే వస్తారా, మేము ఇంటికి రావాలా అండి?",
            "आप आएँगे या हम घर पर आएँ?",
            "Will you come in, or should someone come to you?",
        ),
        offer=_said(
            "ఏ రోజు కుదురుతుంది అండి, మార్నింగ్ కావాలా ఈవెనింగ్ కావాలా?",
            "कौन सा दिन ठीक रहेगा जी, मॉर्निंग या ईवनिंग?",
            "Which day suits you, morning or evening?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా సర్వీస్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमारी सर्विस के बारे में पूछा था, अभी भी चाहिए?",
            "You had asked about our service earlier, do you still need it?",
        ),
        qualify_ask=_said(
            "ఏ సర్వీస్ కావాలి అండి?",
            "कौन सी सर्विस चाहिए जी?",
            "Which service would you like?",
        ),
        lead_offer=_said(
            "ఈ వారం ఏ రోజు స్లాట్ కావాలి అండి?",
            "इस हफ़्ते किस दिन का स्लॉट चाहिए जी?",
            "Which day this week would you like a slot?",
        ),
        objection=(
            "I want a particular person.",
            "Say the team will check that person's day and confirm; never promise them.",
        ),
    ),
    "automobile": TradeWords(
        reason="their question about a service",
        value_topics="the service centre's location, what the service covers and pick-up",
        first_ask=_said(
            "మీ వెహికల్ ఏ మోడల్?",
            "ठीक है जी, आपकी गाड़ी कौन से मॉडल की है?",
            "Sure, which vehicle and model is it?",
        ),
        details_ask=_said(
            "సర్వీస్ కావాలా, రిపేర్ కావాలా అండి?",
            "सर्विस करानी है या रिपेयर?",
            "Is it a regular service or a repair?",
        ),
        offer=_said(
            "వెహికల్ పికప్ కావాలా, మీరే తీసుకొస్తారా అండి?",
            "गाड़ी पिकअप करवानी है या आप खुद लाएँगे?",
            "Shall we pick the vehicle up, or will you bring it in?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు సర్వీస్ గురించి అడిగారు కదా, ఇంకా చేయించాలా అండి?",
            "आपने पहले सर्विस के बारे में पूछा था, अभी भी करानी है?",
            "You had asked about a service earlier, does the vehicle still need one?",
        ),
        qualify_ask=_said(
            "మీ వెహికల్ ఏ మోడల్ అండి?",
            "आपकी गाड़ी कौन से मॉडल की है जी?",
            "Which model is your vehicle?",
        ),
        lead_offer=_said(
            "సర్వీస్ కి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
            "सर्विस के लिए कौन सा दिन ठीक रहेगा, आज या कल?",
            "Which day suits you for the service, today or tomorrow?",
        ),
        objection=(
            "How much will the repair cost?",
            "Say the cost is known after an inspection and offer one; never guess a figure.",
        ),
    ),
    NEUTRAL_TRADE: TradeWords(
        reason="their enquiry with the business",
        value_topics="what the business does and where it is",
        first_ask=_said(
            "మీకు ఏం కావాలో చెప్తారా?",
            "ठीक है जी, बताइए क्या चाहिए?",
            "Sure, what can I help you with?",
        ),
        details_ask=_said(
            "మీకు ఏ రోజు కుదురుతుంది అండి?",
            "आपको कौन सा दिन ठीक रहेगा जी?",
            "Which day suits you?",
        ),
        offer=_said(
            "మార్నింగ్ కుదురుతుందా, ఈవెనింగ్ కుదురుతుందా అండి?",
            "मॉर्निंग ठीक रहेगा या ईवनिंग?",
            "Would a morning or an evening suit you?",
        ),
        reason_line=_said(
            "మీరు ఇంతకు ముందు మా దగ్గర ఎంక్వైరీ చేశారు కదా, ఇంకా కావాలా అండి?",
            "आपने पहले हमसे इन्क्वायरी की थी, अभी भी चाहिए?",
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
#: The Telugu opener the close and the first questions used to start with.
_DROPPED_TE_OPENER: Final = "సరే అండి, "

#: (the line a plan used to teach, the one that replaced it), per language: what the
#: `refresh_example_lines` job puts on agents still holding the old line word for word
#: (D-888, migration `c8e4a1f7b2d5`, which freezes its own copy). The old lines still count
#: as plan lines, so a business's own example line may replace one an agent was made with.
BHK_AND_VISIT_LINES: Final[tuple[tuple[Said, Said], ...]] = (
    (
        _said(
            "టూ బీహెచ్కే కావాలా, త్రీ బీహెచ్కే కావాలా అండి?",
            "टू बीएचके चाहिए या थ्री बीएचके?",
            "Are you looking at a two or a three BHK?",
        ),
        TRADE_WORDS["real_estate"].details_ask,
    ),
    (
        _said(
            "ఒకసారి సైట్ విజిట్ కి రండి అండి, ఈ వీకెండ్ కుదురుతుందా?",
            "एक बार साइट विज़िट कर लीजिए जी, इस वीकेंड ठीक रहेगा?",
            "Would you like to see the site, maybe this weekend?",
        ),
        TRADE_WORDS["real_estate"].offer,
    ),
    (
        _said(
            "సైట్ విజిట్ కి సాటర్డే కుదురుతుందా, సండే కుదురుతుందా అండి?",
            "साइट विज़िट के लिए सैटरडे ठीक रहेगा या संडे?",
            "For a site visit, would Saturday or Sunday suit you?",
        ),
        TRADE_WORDS["real_estate"].lead_offer,
    ),
)
#: The Telugu close and every trade's first question opened with the stock "సరే అండి,"
#: (founder, 27 Oct 2026, D-894: a reaction only where it fits); migration `d7c2e9a4f6b1`
#: takes it off agents still holding the old line. Hindi and English keep theirs: the
#: approval named the Telugu opener.
TE_OPENER_LINES: Final[tuple[tuple[Said, Said], ...]] = tuple(
    ({**said, "te-IN": _DROPPED_TE_OPENER + said["te-IN"]}, said)
    for said in (_CLOSE, *(words.first_ask for words in TRADE_WORDS.values()))
)
REPLACED_LINES: Final[tuple[tuple[Said, Said], ...]] = (*BHK_AND_VISIT_LINES, *TE_OPENER_LINES)
_ALL_LINES: Final = frozenset(
    line for said in (*ALL_LINES, *(old for old, _ in REPLACED_LINES)) for line in said.values()
)

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
        "spoken register, except a step whose plan has no example line."
    )
    return "\n\n".join(blocks)


__all__ = [
    "ALL_LINES",
    "BHK_AND_VISIT_LINES",
    "JOB_SHAPES",
    "NEUTRAL_TRADE",
    "PLAYBOOK_LANGUAGES",
    "REPLACED_LINES",
    "TE_OPENER_LINES",
    "TRADE_WORDS",
    "VALUE_STEP_TITLE",
    "PlayStep",
    "Playbook",
    "TradeBasics",
    "TradeWords",
    "example_line",
    "is_playbook_line",
    "playbook_for",
    "playbook_guidance",
]

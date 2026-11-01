"""Mistakes on real calls (D-949): the practice-test checks read a real call's turns."""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.turn_checks import SOUND_KINDS, offers_more

AREA = "అవునండి, శ్రీ ఎస్టేట్స్ నుంచి కాల్ చేస్తున్నాను. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?"


@dataclass(frozen=True)
class _T:
    idx: int
    speaker: str
    text: str


def _call(*lines: tuple[str, str]) -> list[_T]:
    return [_T(i, who, words) for i, (who, words) in enumerate(lines)]


#: The Sri Estates trial call of 30 Oct 2026, as ThinnestAI transcribed it.
SRI_ESTATES = _call(
    ("caller", "Hello."),
    ("agent", "నమస్కారం అండి, Sri-Estates నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"),
    ("caller", "Sri Estates."),
    ("agent", "మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?"),
    ("caller", "Yes."),
    ("agent", "సంతోషం అండి. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?"),
    ("caller", "Ah."),
    ("agent", "పర్లేదు అండి, మీకు ఏ ఏరియాలో అయితే బాగుంటుంది అనిపిస్తుందో చెప్తారా?"),
    ("caller", "Sri Estates."),
    ("agent", AREA),
    ("caller", "Sri Estates."),
    ("agent", AREA),
    ("caller", "Sri Estates."),
    ("agent", AREA),
)


def test_the_sri_estates_call_shows_what_went_wrong_where() -> None:
    """Turn 9 says again the area question turn 5 asked; turn 11 asks turn 9's question
    again word for word. The greeting after the person's "Hello" is the opening, not a
    second greeting."""
    assert mistakes_in(SRI_ESTATES, language="te-IN") == {"said_again": 9, "asked_again": 11}


def test_a_line_the_caller_spoke_over_may_be_said_again() -> None:
    assert mistakes_in(SRI_ESTATES[:10], language="te-IN", unheard={5}) == {}


def test_a_clean_call_shows_nothing() -> None:
    clean = _call(
        ("agent", "Hello, this is Asha from Sunrise Dental. Is this a good time?"),
        ("caller", "Yes, go ahead."),
        ("agent", "You asked about a cleaning. Would Tuesday morning suit you?"),
        ("caller", "Tuesday is fine."),
        ("agent", "Thank you, the team will call to confirm the time."),
    )
    assert mistakes_in(clean, language="en-IN") == {}


def test_talking_about_the_caller_is_found() -> None:
    call = _call(
        ("agent", "Hello, this is Asha from Sunrise Dental."),
        ("caller", "Please stop calling me."),
        ("agent", "The caller's number has been added to the do not call list."),
    )
    assert mistakes_in(call, language="en-IN") == {"third_person": 2}


#: The founder's Rytu Khata call of 2 Nov 2026 (a "both" agent placing the call), abridged:
#: the placed call's opening, the person's "Hello." said over it, a hello back cut off by
#: "Tell me.", then a step-by-step walk through the app with "anything else?" after each
#: answer while the caller was still mid-task. Turns 6, 7 and 9 stand in for the elided
#: middle; turns 8 and 10 end as the call's turns 9 and 11 did. No personal details.
RYTU_KHATA = _call(
    (
        "agent",
        "నమస్కారం అండి, నేను Rytu khata నుండి Anjaliని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను "
        "అండి. నేను రైతు ఖాతా యాప్ గురించి కాల్ చేస్తున్నాను అండి. ఇప్పుడు matladadaniki ok "
        "నా అండి",
    ),
    ("caller", "Hello."),
    ("agent", "హలో అండి. రైతు ఖాతా"),
    ("caller", "Tell me."),
    ("agent", "రైతు ఖాతా యాప్ గురించి మీకు ఏమైనా సందేహాలు ఉన్నాయా అండి?"),
    ("caller", "Let me open it and tell you what I see, you tell me what to do."),
    ("agent", "సరే అండి, యాప్ ఓపెన్ చేశాక ఏం కనిపిస్తుందో చెప్పండి."),
    ("caller", "I opened it. It is asking me to choose a language."),
    ("agent", "తెలుగు సెలెక్ట్ చేసి, నెక్స్ట్ నొక్కండి అండి. ఇంకేమైనా సహాయం కావాలా అండి?"),
    ("caller", "Wait, now it shows a sign up page."),
    ("agent", "అక్కడ మీ పేరు టైప్ చేసి, సైన్ అప్ నొక్కండి. ఇంకేమైనా తెలుసుకోవాలా అండి?"),
)


def test_the_rytu_khata_call_shows_the_second_start_and_anything_else_too_soon() -> None:
    found = mistakes_in(RYTU_KHATA, language="te-IN")
    assert found["opened_again"] == 2
    assert found["offered_more_too_soon"] == 10


def test_a_hello_back_cut_off_by_the_caller_is_still_a_second_start() -> None:
    """A talked-over turn is cut at its end, so the hello that opens it was heard."""
    assert mistakes_in(RYTU_KHATA[:5], language="te-IN", unheard={2})["opened_again"] == 2
    # Only the first reply is judged that way: a later cut-off turn is still left out.
    later = _call(
        ("agent", "Hello, this is Asha from Sunrise Dental. Is this a good time?"),
        ("caller", "Yes."),
        ("agent", "You asked about a cleaning. Would Tuesday morning suit you?"),
        ("caller", "Hello?"),
        ("agent", "Hello, can you hear me now?"),
    )
    assert "opened_again" not in mistakes_in(later, language="en-IN", unheard={4})


def test_anything_else_is_read_in_each_language_and_only_as_a_question() -> None:
    assert offers_more("ఇంకేమైనా సహాయం కావాలా అండి?")
    assert offers_more("ठीक है जी, और कुछ चाहिए?")
    assert offers_more("Done. Is there anything else I can help with?")
    # A goodbye that says "call if you need anything else" offers nothing.
    assert not offers_more("సరే అండి, ఇంకేమైనా కావాలంటే కాల్ చేయండి.")
    assert not offers_more("Next, tap Sign up.")
    assert "offered_more_too_soon" in SOUND_KINDS


def test_anything_else_once_a_topic_is_done_is_no_mistake() -> None:
    call = _call(
        ("agent", "Hello, this is Asha from Sunrise Dental. Is this a good time?"),
        ("caller", "Yes. Is the clinic open on Sunday?"),
        ("agent", "Yes, from ten to two. Anything else?"),
        ("caller", "What about Monday?"),
        ("agent", "Monday from nine to six, and it is the busier day."),
        ("caller", "Thanks."),
        ("agent", "Is there anything else I can help with?"),
    )
    assert "offered_more_too_soon" not in mistakes_in(call, language="en-IN")


def test_every_lesson_has_words_an_owner_reads() -> None:
    for lesson in LESSONS.values():
        assert lesson.label and lesson.instead

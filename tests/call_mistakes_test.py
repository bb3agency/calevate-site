"""Mistakes on real calls (D-949): the practice-test checks read a real call's turns."""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.agents.call_mistakes import LESSONS, mistakes_in

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


def test_every_lesson_has_words_an_owner_reads() -> None:
    for lesson in LESSONS.values():
        assert lesson.label and lesson.instead
